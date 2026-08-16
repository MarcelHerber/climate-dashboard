#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from update_station_records import (
    INTERNAL_UNKNOWN,
    STATE_ORDER,
    MetadataIndex,
    Observation,
    download,
    iter_downloaded_observations,
    list_station_files,
    parse_metadata,
)

VERSION = 4
TOP_K = 50

# Qualitätsfilter für vergleichbare NN-Luftdruckrekorde.
# Der DWD weist darauf hin, dass auch historische Daten noch Einzel-
# fehler enthalten können. Die Schranken liegen bewusst etwas außerhalb
# der publizierten deutschen Luftdruckextreme und dienen nur dazu,
# offensichtliche Fehlwerte/Fehlzuordnungen zu entfernen.
PRESSURE_MIN_HPA = 954.4
PRESSURE_MAX_HPA = 1060.8
MAX_STATION_HEIGHT_M = 750
ALLOWED_QN_8 = {2, 3, 5, 7, 8, 9, 10}

BASE_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/hourly/pressure"
)
HISTORICAL_URL = f"{BASE_URL}/historical/"
RECENT_URL = f"{BASE_URL}/recent/"
METADATA_URL = f"{RECENT_URL}P0_Stundenwerte_Beschreibung_Stationen.txt"

HISTORICAL_PATTERN = re.compile(
    r'href=["\'](stundenwerte_P0_\d{5}_\d{8}_\d{8}_hist\.zip)["\']',
    re.IGNORECASE,
)
RECENT_PATTERN = re.compile(
    r'href=["\'](stundenwerte_P0_\d{5}_akt\.zip)["\']',
    re.IGNORECASE,
)
STATION_PATTERN = re.compile(r"stundenwerte_P0_(\d{5})_", re.IGNORECASE)

METRIC_CONFIG = {
    "p_high": {
        "label": "Höchster Luftdruck NN",
        "unit": "hPa",
        "direction": "desc",
        "source_column": "P",
    },
    "p_low": {
        "label": "Niedrigster Luftdruck NN",
        "unit": "hPa",
        "direction": "asc",
        "source_column": "P",
    },
}

MONTH_NAMES = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

AREAS = ["Deutschland", *STATE_ORDER]


def decade_no(day: date) -> int:
    if day.day <= 10:
        return 1
    if day.day <= 20:
        return 2
    return 3


def period_id(day: date) -> str:
    return f"month-{day.month:02d}-d{decade_no(day)}"


def build_periods() -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = []
    for month, month_name in enumerate(MONTH_NAMES, start=1):
        for decade in (1, 2, 3):
            day_range = (
                "01.–10."
                if decade == 1
                else "11.–20."
                if decade == 2
                else "21.–Monatsende"
            )
            periods.append(
                {
                    "id": f"month-{month:02d}-d{decade}",
                    "month": month,
                    "month_label": month_name,
                    "decade": decade,
                    "label": f"{month_name} · {decade}. Dekade",
                    "day_range": day_range,
                }
            )
    return periods


def decode_product(data: bytes) -> str:
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "MESS_DATUM" in text:
            return text
    return data.decode("latin-1", errors="replace")


def plausible_pressure(value: float) -> bool:
    return (
        math.isfinite(value)
        and PRESSURE_MIN_HPA <= value <= PRESSURE_MAX_HPA
    )


def parse_pressure_zip(
    content: bytes,
    station_id_hint: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> list[Observation]:
    """
    Liest stündlichen DWD-Luftdruck P.

    DWD-Datensatzbeschreibung:
      P  = Luftdruck auf Meereshöhe NN [hPa]
      P0 = Luftdruck auf Stationshöhe [hPa]

    Ausgewertet wird ausschließlich P.
    """
    observations: list[Observation] = []

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        product_files: list[str] = []

        for name in archive.namelist():
            if not name.lower().endswith(".txt") or "produkt" not in name.lower():
                continue
            try:
                first_line = (
                    archive.read(name)
                    .splitlines()[0]
                    .decode("latin-1", errors="replace")
                )
            except (KeyError, IndexError):
                continue

            columns = {
                part.strip().upper()
                for part in first_line.split(";")
            }
            if {"STATIONS_ID", "MESS_DATUM", "QN_8", "P"}.issubset(columns):
                product_files.append(name)

        if not product_files:
            return []

        # Normalerweise genau eine Produktdatei; defensiv alle passenden lesen.
        for product_name in product_files:
            text = decode_product(archive.read(product_name))
            reader = csv.DictReader(io.StringIO(text), delimiter=";")
            fields = [
                (field or "").strip()
                for field in (reader.fieldnames or [])
            ]
            lookup = {field.upper(): field for field in fields}

            station_field = lookup.get("STATIONS_ID")
            date_field = lookup.get("MESS_DATUM")
            quality_field = lookup.get("QN_8")
            pressure_field = lookup.get("P")

            if (
                not station_field
                or not date_field
                or not quality_field
                or not pressure_field
            ):
                continue

            for raw_row in reader:
                row = {
                    (key or "").strip(): (
                        value.strip()
                        if isinstance(value, str)
                        else value
                    )
                    for key, value in raw_row.items()
                }

                stamp = str(row.get(date_field) or "").strip()
                if len(stamp) < 10:
                    continue
                try:
                    moment = datetime.strptime(
                        stamp[:10],
                        "%Y%m%d%H",
                    )
                except ValueError:
                    continue

                day = moment.date()
                if day < start_date or day > end_date:
                    continue

                raw_quality = row.get(quality_field)
                try:
                    quality_level = int(float(str(raw_quality).strip()))
                except (TypeError, ValueError):
                    continue
                if quality_level not in ALLOWED_QN_8:
                    continue

                raw_value = row.get(pressure_field)
                if raw_value in (None, ""):
                    continue
                try:
                    value = float(
                        str(raw_value).strip().replace(",", ".")
                    )
                except ValueError:
                    continue

                station_raw = str(
                    row.get(station_field) or ""
                ).strip()
                station_id = (
                    station_raw.zfill(5)
                    if station_raw
                    else station_id_hint
                )
                segment = metadata.segment_for(station_id, day)

                # Vergleichbare NN-Rekorde nur aus Stationen bis 750 m.
                # Bei höheren Bergstationen kann die Reduktion auf
                # Meereshöhe sehr empfindlich bzw. historisch inkonsistent
                # sein. Unbekannte Höhen werden ebenfalls nicht verwendet.
                if segment.height is None or segment.height > MAX_STATION_HEIGHT_M:
                    continue

                if not plausible_pressure(value):
                    continue

                observations.append(
                    Observation(
                        day=day,
                        metadata_key=segment.key,
                        state=segment.state,
                        station_id=station_id,
                        values={
                            # Beide Sortierrichtungen basieren auf demselben
                            # beobachteten NN-Luftdruck P.
                            "p_high": round(value, 1),
                            "p_low": round(value, 1),
                            # Interne Zusatzinfos.
                            "_hour": moment.hour,
                            "_qn8": quality_level,
                        },
                        preliminary=preliminary,
                    )
                )

    return observations


def entry_for(
    observation: Observation,
    metric: str,
) -> list[Any]:
    hour = int(observation.values["_hour"])
    return [
        round(float(observation.values[metric]), 1),
        observation.day.isoformat(),
        observation.metadata_key,
        1 if observation.preliminary else 0,
        f"{hour:02d}:00 UTC",
        int(observation.values["_qn8"]),
    ]


def entry_time_key(entry: list[Any]) -> tuple[str, str]:
    return str(entry[1]), str(entry[4] if len(entry) > 4 else "")


def better(
    metric: str,
    new: list[Any],
    old: list[Any],
) -> bool:
    new_value = float(new[0])
    old_value = float(old[0])
    direction = METRIC_CONFIG[metric]["direction"]

    if new_value != old_value:
        return (
            new_value > old_value
            if direction == "desc"
            else new_value < old_value
        )

    new_time = entry_time_key(new)
    old_time = entry_time_key(old)
    if new_time != old_time:
        return new_time < old_time

    new_station = str(new[2]).split(":", 1)[0]
    old_station = str(old[2]).split(":", 1)[0]
    return new_station < old_station


class PressureAccumulator:
    def __init__(self) -> None:
        self.station_records: dict[
            str,
            dict[str, dict[str, dict[str, list[Any]]]],
        ] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(dict))
        )
        self.observation_count = 0
        self.first_moment: tuple[date, int] | None = None
        self.last_moment: tuple[date, int] | None = None

    def add(self, observation: Observation) -> None:
        pid = period_id(observation.day)

        areas = ["Deutschland"]
        if observation.state in STATE_ORDER:
            areas.append(observation.state)

        hour = int(observation.values["_hour"])
        moment_key = (observation.day, hour)

        for metric in METRIC_CONFIG:
            entry = entry_for(observation, metric)
            for area in areas:
                bucket = self.station_records[metric][area][pid]
                old = bucket.get(observation.station_id)
                if old is None or better(metric, entry, old):
                    bucket[observation.station_id] = entry

        self.observation_count += 1
        self.first_moment = (
            moment_key
            if self.first_moment is None
            else min(self.first_moment, moment_key)
        )
        self.last_moment = (
            moment_key
            if self.last_moment is None
            else max(self.last_moment, moment_key)
        )

    def public_station_records(
        self,
        periods: list[dict[str, Any]],
    ) -> dict[str, Any]:
        period_ids = [item["id"] for item in periods]
        result: dict[str, Any] = {}

        for metric in METRIC_CONFIG:
            metric_out: dict[str, Any] = {}
            for area in AREAS:
                area_out: dict[str, Any] = {}
                for pid in period_ids:
                    records = (
                        self.station_records
                        .get(metric, {})
                        .get(area, {})
                        .get(pid, {})
                    )
                    area_out[pid] = {
                        station_id: records[station_id]
                        for station_id in sorted(records)
                    }
                metric_out[area] = area_out
            result[metric] = metric_out

        return result

    def public_leaders(
        self,
        periods: list[dict[str, Any]],
    ) -> dict[str, Any]:
        period_ids = [item["id"] for item in periods]
        result: dict[str, Any] = {}

        for metric, meta in METRIC_CONFIG.items():
            metric_out: dict[str, Any] = {}
            direction = meta["direction"]

            for area in AREAS:
                area_out: dict[str, Any] = {}

                for pid in period_ids:
                    records = (
                        self.station_records
                        .get(metric, {})
                        .get(area, {})
                        .get(pid, {})
                    )

                    def sort_key(entry: list[Any]) -> tuple[Any, ...]:
                        value = float(entry[0])
                        station_text = str(entry[2]).split(":", 1)[0]
                        station_number = (
                            int(station_text)
                            if station_text.isdigit()
                            else 99999
                        )
                        base = (
                            str(entry[1]),
                            str(entry[4] if len(entry) > 4 else ""),
                            station_number,
                        )
                        return (
                            (-value, *base)
                            if direction == "desc"
                            else (value, *base)
                        )

                    ranked = sorted(
                        records.values(),
                        key=sort_key,
                    )
                    area_out[pid] = ranked[:TOP_K]

                metric_out[area] = area_out

            result[metric] = metric_out

        return result


def referenced_metadata_keys(
    payload_part: Any,
    target: set[str],
) -> None:
    if isinstance(payload_part, dict):
        for value in payload_part.values():
            referenced_metadata_keys(value, target)
        return

    if isinstance(payload_part, list):
        if (
            len(payload_part) >= 4
            and isinstance(payload_part[1], str)
            and isinstance(payload_part[2], str)
            and ":" in payload_part[2]
        ):
            target.add(payload_part[2])
            return

        for value in payload_part:
            referenced_metadata_keys(value, target)


def consume_archives(
    accumulator: PressureAccumulator,
    metadata: MetadataIndex,
    filenames: list[str],
    base_url: str,
    start_date: date,
    end_date: date,
    preliminary: bool,
    max_workers: int,
    *,
    failure_tolerance: float,
) -> int:
    before = accumulator.observation_count

    for observations in iter_downloaded_observations(
        filenames,
        base_url,
        metadata,
        start_date,
        end_date,
        preliminary,
        max_workers,
        station_pattern=STATION_PATTERN,
        parser=parse_pressure_zip,
        failure_tolerance=failure_tolerance,
    ):
        for observation in observations:
            accumulator.add(observation)

    return accumulator.observation_count - before


def moment_text(moment: tuple[date, int] | None) -> str | None:
    if moment is None:
        return None
    day, hour = moment
    return f"{day.isoformat()}T{hour:02d}:00:00Z"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "DWD-Dekadenrekorde des auf Meereshöhe reduzierten "
            "stündlichen Luftdrucks P."
        )
    )
    parser.add_argument(
        "--output",
        default="data/dwd_decade_pressure_records.json",
    )
    parser.add_argument("--max-workers", type=int, default=10)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    print(
        "=== DWD DEKADENREKORDE · LUFTDRUCK NN ===",
        flush=True,
    )
    print(
        "Quelle: DWD hourly/pressure · Spalte P",
        flush=True,
    )
    print(
        "P = auf Meereshöhe NN reduzierter Luftdruck [hPa]",
        flush=True,
    )
    print(
        "Parameter: höchster + niedrigster stündlicher Luftdruck",
        flush=True,
    )
    print(
        "Gebiete: Deutschland + 16 Bundesländer",
        flush=True,
    )
    print(
        "Fenster: 36 meteorologische Dekaden",
        flush=True,
    )

    metadata = parse_metadata(
        download(METADATA_URL, timeout=90)
    )
    print(
        f"Stations-Metadatensegmente: {len(metadata.segments):,}",
        flush=True,
    )

    historical_files = list_station_files(
        HISTORICAL_URL,
        HISTORICAL_PATTERN,
        minimum=200,
    )
    recent_files = list_station_files(
        RECENT_URL,
        RECENT_PATTERN,
        minimum=100,
    )

    print(
        f"Historische P0-Archive: {len(historical_files):,}",
        flush=True,
    )
    print(
        f"Aktuelle P0-Archive: {len(recent_files):,}",
        flush=True,
    )

    accumulator = PressureAccumulator()
    today = datetime.now(timezone.utc).date()

    historical_count = consume_archives(
        accumulator,
        metadata,
        historical_files,
        HISTORICAL_URL,
        date(1800, 1, 1),
        today,
        False,
        args.max_workers,
        failure_tolerance=0.01,
    )
    print(
        f"Historische gültige P-Stundenwerte verarbeitet: "
        f"{historical_count:,}",
        flush=True,
    )

    # Historical ist aktuell bis Ende des Vorjahres versioniert.
    # Für den laufenden Stand genügt recent ab Jahresbeginn; so vermeiden
    # wir Doppelzählung im überlappenden ~500-Tage-Fenster.
    recent_count = consume_archives(
        accumulator,
        metadata,
        recent_files,
        RECENT_URL,
        date(today.year, 1, 1),
        today,
        True,
        args.max_workers,
        failure_tolerance=0.02,
    )
    print(
        f"Aktuelle gültige P-Stundenwerte verarbeitet: "
        f"{recent_count:,}",
        flush=True,
    )

    periods = build_periods()
    station_records = accumulator.public_station_records(periods)
    leaders = accumulator.public_leaders(periods)

    metadata_keys: set[str] = set()
    referenced_metadata_keys(station_records, metadata_keys)

    public_meta = metadata.public_dict()
    stations = {
        key: public_meta[key]
        for key in sorted(metadata_keys)
        if key in public_meta
    }

    payload = {
        "version": VERSION,
        "generated_at": (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "source": (
            "DWD CDC hourly pressure · P "
            "(Luftdruck auf Meereshöhe NN)"
        ),
        "source_urls": {
            "historical": HISTORICAL_URL,
            "recent": RECENT_URL,
        },
        "data_start": (
            accumulator.first_moment[0].isoformat()
            if accumulator.first_moment
            else None
        ),
        "data_through": (
            accumulator.last_moment[0].isoformat()
            if accumulator.last_moment
            else None
        ),
        "data_start_timestamp": moment_text(
            accumulator.first_moment
        ),
        "data_through_timestamp": moment_text(
            accumulator.last_moment
        ),
        "areas": AREAS,
        "metrics": METRIC_CONFIG,
        "periods": periods,
        "top_k": TOP_K,
        "entry_schema": [
            "value_hpa",
            "date",
            "metadata_key",
            "preliminary",
            "time_utc",
            "qn_8",
        ],
        "stations": stations,
        "leaders": leaders,
        "station_records": station_records,
        "valid_observations": accumulator.observation_count,
        "quality_filter": {
            "pressure_min_hpa": PRESSURE_MIN_HPA,
            "pressure_max_hpa": PRESSURE_MAX_HPA,
            "max_station_height_m": MAX_STATION_HEIGHT_M,
            "allowed_qn_8": sorted(ALLOWED_QN_8),
            "reason": (
                "Verwendet die DWD-Qualitätsniveaus 2, 3, 5, 7, 8, 9 und 10, "
                "schließt Bergstationen über 750 m aus "
                "und interpretiert Werte außerhalb des vom DWD dokumentierten "
                "deutschen Rekordrahmens 954,4–1060,8 hPa nicht automatisch "
                "als Stationsrekorde."
            ),
        },
        "method_note": (
            "Meteorologische Dekaden: 1.=01.–10., 2.=11.–20., "
            "3.=21.–Monatsende. Aus dem stündlichen DWD-Datensatz "
            "hourly/pressure wird ausschließlich P ausgewertet. Laut DWD "
            "ist P der auf Meereshöhe NN reduzierte Luftdruck in hPa; "
            "P0 ist dagegen der Luftdruck auf Stationshöhe. Für den "
            "vergleichbaren NN-Rekord werden nur Stationen bis 750 m "
            "verwendet. Zusätzlich werden offensichtliche Rohdatenfehler "
            "außerhalb 945–1062 hPa verworfen. Pro Station und Dekade "
            "werden höchster und niedrigster beobachteter P-Stundenwert "
            "bestimmt. Recent-Werte sind als vorläufig gekennzeichnet."
        ),
    }

    output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    expected_metrics = {"p_high", "p_low"}

    if len(payload["areas"]) != 17:
        raise RuntimeError("Gebietsliste unvollständig.")
    if len(payload["periods"]) != 36:
        raise RuntimeError("Dekadenliste unvollständig.")
    if set(payload["metrics"]) != expected_metrics:
        raise RuntimeError("Luftdruck-Parameter unvollständig.")
    if not payload["data_start"] or not payload["data_through"]:
        raise RuntimeError("Kein Luftdruck-Datenzeitraum ermittelt.")
    if payload["valid_observations"] < 1_000_000:
        raise RuntimeError(
            f"Unplausibel wenige P-Stundenwerte: "
            f"{payload['valid_observations']:,}"
        )

    if any(
        station.get("height") is None
        or float(station["height"]) > MAX_STATION_HEIGHT_M
        for station in payload["stations"].values()
    ):
        raise RuntimeError("Höhenfilter wurde nicht vollständig angewendet.")

    for metric in expected_metrics:
        germany = payload["leaders"][metric]["Deutschland"]
        nonempty = sum(
            bool(germany[item["id"]])
            for item in periods
        )
        if nonempty < 36:
            raise RuntimeError(
                f"{metric}: nur {nonempty}/36 Deutschland-Dekaden "
                "enthalten Werte."
            )

    print(
        "Luftdruck-Dekadenrekorde erfolgreich gebaut.",
        flush=True,
    )
    print(
        f"Datenzeitraum: {payload['data_start_timestamp']} bis "
        f"{payload['data_through_timestamp']}",
        flush=True,
    )
    print(
        f"Gültige P-Stundenwerte nach QC: "
        f"{payload['valid_observations']:,}",
        flush=True,
    )
    print(
        f"QC: {PRESSURE_MIN_HPA:.1f}–{PRESSURE_MAX_HPA:.1f} hPa | "
        f"Stationshöhe <= {MAX_STATION_HEIGHT_M} m | "
        f"QN_8 in {sorted(ALLOWED_QN_8)}",
        flush=True,
    )
    print(
        f"Stations-Metadatensegmente in Ausgabe: "
        f"{len(payload['stations']):,}",
        flush=True,
    )

    for metric in ("p_high", "p_low"):
        sample = payload["leaders"][metric]["Deutschland"]["month-01-d2"]
        print(
            f"Beispiel Januar 2. Dekade {metric}: "
            f"{sample[0] if sample else 'keine Werte'}",
            flush=True,
        )

    print(
        f"Ausgabe: {output} "
        f"({output.stat().st_size / 1024 / 1024:.1f} MB)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
