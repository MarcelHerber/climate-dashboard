#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from update_station_records import (
    HISTORICAL_PATTERN,
    HISTORICAL_URL,
    INTERNAL_UNKNOWN,
    METADATA_URL,
    RECENT_PATTERN,
    RECENT_URL,
    STATE_ORDER,
    STATION_ID_PATTERN,
    MetadataIndex,
    NoUsableProductFileError,
    Observation,
    download,
    iter_downloaded_observations,
    list_station_files,
    parse_metadata,
)

VERSION = 1
TOP_K = 50
METRIC = "shk_high"
AREAS = ["Deutschland", *STATE_ORDER]

METRIC_CONFIG = {
    "label": "Höchste Schneehöhe",
    "unit": "cm",
    "direction": "desc",
    "source_column": "SHK_TAG",
    "source_aliases": ["SHK_TAG", "SHK"],
}

MONTH_NAMES = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


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


def parse_snow_station_zip(
    content: bytes,
    station_id_hint: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> list[Observation]:
    """Liest gültige tägliche Schneehöhen SHK_TAG/SHK aus DWD-KL-ZIPs."""
    observations: list[Observation] = []

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        product_files: list[str] = []

        for name in archive.namelist():
            if not name.lower().endswith(".txt"):
                continue
            if "produkt" not in name.lower():
                continue
            try:
                first_line = (
                    archive.read(name)
                    .splitlines()[0]
                    .decode("latin-1", errors="replace")
                )
            except (KeyError, IndexError):
                continue

            columns = {part.strip().upper() for part in first_line.split(";")}
            if {"STATIONS_ID", "MESS_DATUM"}.issubset(columns) and (
                "SHK_TAG" in columns or "SHK" in columns
            ):
                product_files.append(name)

        if not product_files:
            # Manche KL-Archive enthalten andere Produktvarianten ohne Schnee.
            # Das ist kein Datenfehler, sondern wird bewusst übersprungen.
            return []

        for product_name in product_files:
            text = decode_product(archive.read(product_name))
            reader = csv.DictReader(io.StringIO(text), delimiter=";")
            fields = [(field or "").strip() for field in (reader.fieldnames or [])]
            lookup = {field.upper(): field for field in fields}

            station_field = lookup.get("STATIONS_ID")
            date_field = lookup.get("MESS_DATUM")
            snow_field = lookup.get("SHK_TAG") or lookup.get("SHK")

            if not station_field or not date_field or not snow_field:
                continue

            for raw_row in reader:
                row = {
                    (key or "").strip(): (
                        value.strip() if isinstance(value, str) else value
                    )
                    for key, value in raw_row.items()
                }

                stamp = str(row.get(date_field) or "").strip()
                try:
                    day = datetime.strptime(stamp, "%Y%m%d").date()
                except ValueError:
                    continue

                if day < start_date or day > end_date:
                    continue

                raw_value = row.get(snow_field)
                if raw_value in (None, ""):
                    continue

                try:
                    value = float(str(raw_value).replace(",", "."))
                except ValueError:
                    continue

                # DWD-Schneehöhe in cm; negative Fehlwerte niemals als 0 werten.
                if not math.isfinite(value) or value < 0 or value > 999:
                    continue

                station_raw = str(row.get(station_field) or "").strip()
                station_id = (
                    station_raw.zfill(5)
                    if station_raw
                    else station_id_hint
                )
                segment = metadata.segment_for(station_id, day)

                observations.append(
                    Observation(
                        day=day,
                        metadata_key=segment.key,
                        state=segment.state,
                        station_id=station_id,
                        values={METRIC: round(value, 1)},
                        preliminary=preliminary,
                    )
                )

    return observations


def entry_for(observation: Observation) -> list[Any]:
    return [
        round(float(observation.values[METRIC]), 1),
        observation.day.isoformat(),
        observation.metadata_key,
        1 if observation.preliminary else 0,
    ]


def better(new: list[Any], old: list[Any]) -> bool:
    new_value = float(new[0])
    old_value = float(old[0])

    if new_value != old_value:
        return new_value > old_value

    new_date = str(new[1])
    old_date = str(old[1])
    if new_date != old_date:
        return new_date < old_date

    new_station = str(new[2]).split(":", 1)[0]
    old_station = str(old[2]).split(":", 1)[0]
    return new_station < old_station


class SnowAccumulator:
    def __init__(self) -> None:
        # area -> period -> station_id -> entry
        self.station_records: dict[
            str, dict[str, dict[str, list[Any]]]
        ] = defaultdict(lambda: defaultdict(dict))

        self.observation_count = 0
        self.first_day: date | None = None
        self.last_day: date | None = None

    def add(self, observation: Observation) -> None:
        entry = entry_for(observation)
        pid = period_id(observation.day)

        areas = ["Deutschland"]
        if observation.state in STATE_ORDER:
            areas.append(observation.state)

        for area in areas:
            bucket = self.station_records[area][pid]
            old = bucket.get(observation.station_id)
            if old is None or better(entry, old):
                bucket[observation.station_id] = entry

        self.observation_count += 1
        self.first_day = (
            observation.day
            if self.first_day is None
            else min(self.first_day, observation.day)
        )
        self.last_day = (
            observation.day
            if self.last_day is None
            else max(self.last_day, observation.day)
        )

    def public_station_records(
        self,
        periods: list[dict[str, Any]],
    ) -> dict[str, Any]:
        period_ids = [item["id"] for item in periods]
        result: dict[str, Any] = {}

        for area in AREAS:
            area_out: dict[str, Any] = {}
            for pid in period_ids:
                records = self.station_records.get(area, {}).get(pid, {})
                area_out[pid] = {
                    station_id: records[station_id]
                    for station_id in sorted(records)
                }
            result[area] = area_out

        return result

    def public_leaders(
        self,
        periods: list[dict[str, Any]],
    ) -> dict[str, Any]:
        period_ids = [item["id"] for item in periods]
        result: dict[str, Any] = {}

        for area in AREAS:
            area_out: dict[str, Any] = {}
            for pid in period_ids:
                records = self.station_records.get(area, {}).get(pid, {})
                ranked = sorted(
                    records.values(),
                    key=lambda entry: (
                        -float(entry[0]),
                        str(entry[1]),
                        int(str(entry[2]).split(":", 1)[0])
                        if str(entry[2]).split(":", 1)[0].isdigit()
                        else 99999,
                    ),
                )
                area_out[pid] = ranked[:TOP_K]
            result[area] = area_out

        return result


def referenced_metadata_keys(payload_part: Any, target: set[str]) -> None:
    if isinstance(payload_part, dict):
        for value in payload_part.values():
            referenced_metadata_keys(value, target)
        return

    if isinstance(payload_part, list):
        if (
            len(payload_part) == 4
            and isinstance(payload_part[1], str)
            and isinstance(payload_part[2], str)
            and ":" in payload_part[2]
        ):
            target.add(payload_part[2])
            return

        for value in payload_part:
            referenced_metadata_keys(value, target)


def consume_archives(
    accumulator: SnowAccumulator,
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
        station_pattern=STATION_ID_PATTERN,
        parser=parse_snow_station_zip,
        failure_tolerance=failure_tolerance,
    ):
        for observation in observations:
            accumulator.add(observation)

    return accumulator.observation_count - before


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Historische DWD-Schneehöhenrekorde SHK_TAG "
            "für 36 meteorologische Dekaden bauen."
        )
    )
    parser.add_argument(
        "--output",
        default="data/dwd_decade_snow_records.json",
    )
    parser.add_argument("--max-workers", type=int, default=10)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    print("=== DWD DEKADENREKORDE · SCHNEEHÖHE ===", flush=True)
    print("Parameter: höchste tägliche Schneehöhe SHK_TAG/SHK", flush=True)
    print("Gebiete: Deutschland + 16 Bundesländer", flush=True)
    print("Fenster: 36 meteorologische Dekaden", flush=True)
    print("Stationsfilter: keiner – alle verfügbaren DWD-KL-Stationen", flush=True)

    metadata = parse_metadata(download(METADATA_URL, timeout=90))
    print(
        f"Stations-Metadatensegmente: {len(metadata.segments):,}",
        flush=True,
    )

    historical_files = list_station_files(
        HISTORICAL_URL,
        HISTORICAL_PATTERN,
        minimum=500,
    )
    recent_files = list_station_files(
        RECENT_URL,
        RECENT_PATTERN,
        minimum=300,
    )

    print(f"Historische KL-Archive: {len(historical_files):,}", flush=True)
    print(f"Aktuelle KL-Archive: {len(recent_files):,}", flush=True)

    accumulator = SnowAccumulator()
    today = datetime.now(timezone.utc).date()

    historical_count = consume_archives(
        accumulator,
        metadata,
        historical_files,
        HISTORICAL_URL,
        date(1750, 1, 1),
        today,
        False,
        args.max_workers,
        failure_tolerance=0.01,
    )
    print(
        f"Historische gültige SHK-Tageswerte verarbeitet: "
        f"{historical_count:,}",
        flush=True,
    )

    recent_count = consume_archives(
        accumulator,
        metadata,
        recent_files,
        RECENT_URL,
        date(today.year - 2, 1, 1),
        today,
        True,
        args.max_workers,
        failure_tolerance=0.02,
    )
    print(
        f"Aktuelle gültige SHK-Tageswerte verarbeitet: {recent_count:,}",
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
        "source": "DWD CDC daily climate KL · SHK_TAG/SHK",
        "metric": METRIC,
        "metric_meta": METRIC_CONFIG,
        "data_start": (
            accumulator.first_day.isoformat()
            if accumulator.first_day
            else None
        ),
        "data_through": (
            accumulator.last_day.isoformat()
            if accumulator.last_day
            else None
        ),
        "areas": AREAS,
        "periods": periods,
        "top_k": TOP_K,
        "stations": stations,
        "leaders": leaders,
        "station_records": station_records,
        "valid_observations": accumulator.observation_count,
        "method_note": (
            "Meteorologische Dekaden: 1.=01.–10., 2.=11.–20., "
            "3.=21.–Monatsende. Aus allen verfügbaren historischen und "
            "aktuellen täglichen DWD-KL-Archiven werden gültige SHK_TAG/SHK-"
            "Messungen in cm ausgewertet. Fehlwerte werden verworfen und "
            "niemals als 0 cm interpretiert. Pro Station und Dekade wird die "
            "höchste beobachtete Schneehöhe verwendet."
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

    if len(payload["areas"]) != 17:
        raise RuntimeError("Gebietsliste unvollständig.")
    if len(payload["periods"]) != 36:
        raise RuntimeError("Dekadenliste unvollständig.")
    if not payload["data_start"] or not payload["data_through"]:
        raise RuntimeError("Kein gültiger Schneehöhen-Datenzeitraum.")
    if payload["valid_observations"] < 100_000:
        raise RuntimeError(
            f"Unplausibel wenige Schneehöhenwerte: "
            f"{payload['valid_observations']:,}"
        )

    germany = payload["leaders"]["Deutschland"]
    nonempty = sum(bool(germany[item["id"]]) for item in periods)
    if nonempty < 30:
        raise RuntimeError(
            f"Nur {nonempty}/36 Deutschland-Dekaden enthalten Werte."
        )

    print("Schneehöhen-Dekadenrekorde erfolgreich gebaut.", flush=True)
    print(
        f"Datenzeitraum: {payload['data_start']} bis "
        f"{payload['data_through']}",
        flush=True,
    )
    print(
        f"Gültige SHK-Beobachtungen: "
        f"{payload['valid_observations']:,}",
        flush=True,
    )
    print(
        f"Stations-Metadatensegmente in Ausgabe: "
        f"{len(payload['stations']):,}",
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
