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
    RR_HISTORICAL_PATTERN,
    RR_HISTORICAL_URL,
    RR_METADATA_URL,
    RR_RECENT_PATTERN,
    RR_RECENT_URL,
    RR_STATION_ID_PATTERN,
    STATE_ORDER,
    STATION_ID_PATTERN,
    MetadataIndex,
    Observation,
    download,
    iter_downloaded_observations,
    list_station_files,
    parse_metadata,
    parse_rr_station_zip,
)

VERSION = 1
START_YEAR = 1861
LIST_MIN_YEAR = 1881
AREAS = ["Deutschland", *STATE_ORDER]

METRICS = {
    "tnn": {
        "label": "TNn",
        "description": "Tiefstes Tagesminimum des Jahres",
        "unit": "°C",
        "kind": "extreme",
        "direction": "asc",
        "source": "DWD daily/kl · TNK",
    },
    "txx": {
        "label": "TXx",
        "description": "Höchstes Tagesmaximum des Jahres",
        "unit": "°C",
        "kind": "extreme",
        "direction": "desc",
        "source": "DWD daily/kl · TXK",
    },
    "summer_days_max": {
        "label": "max. Tage >25 °C",
        "description": "Höchste Zahl der Tage mit TXK > 25,0 °C an einer Station",
        "unit": "Tage",
        "kind": "station_year_count",
        "threshold": "TXK > 25.0",
        "direction": "desc",
        "source": "DWD daily/kl · TXK",
    },
    "hot_days_max": {
        "label": "max. Tage >30 °C",
        "description": "Höchste Zahl der Tage mit TXK > 30,0 °C an einer Station",
        "unit": "Tage",
        "kind": "station_year_count",
        "threshold": "TXK > 30.0",
        "direction": "desc",
        "source": "DWD daily/kl · TXK",
    },
    "desert_days_max": {
        "label": "max. Wüstentage ≥35 °C",
        "description": "Höchste Zahl der Tage mit TXK >= 35,0 °C an einer Station",
        "unit": "Tage",
        "kind": "station_year_count",
        "threshold": "TXK >= 35.0",
        "direction": "desc",
        "source": "DWD daily/kl · TXK",
    },
    "tropical_nights_max": {
        "label": "Tropennächte ≥20 °C",
        "description": "Höchste Zahl der Tropennächte an einer Station; Nachtminimum 18 UTC bis 06 UTC >= 20,0 °C",
        "unit": "Nächte",
        "kind": "station_year_count",
        "threshold": "Nachtminimum 18–06 UTC >= 20.0 °C",
        "direction": "desc",
        "source": "DWD hourly/air_temperature · TT_TU",
    },
    "rr24x": {
        "label": "RR24x",
        "description": "Höchste tägliche Niederschlagssumme des Jahres",
        "unit": "mm",
        "kind": "extreme",
        "direction": "desc",
        "source": "DWD daily/more_precip · RS",
    },
    "snox_ge_400": {
        "label": "SNOx ≥400 m",
        "description": "Höchste Schneehöhe des Jahres an Stationen ab 400 m",
        "unit": "cm",
        "kind": "extreme",
        "direction": "desc",
        "source": "DWD daily/kl · SHK_TAG/SHK",
        "height_rule": "Stationshöhe >= 400 m",
    },
    "snox_lt_400": {
        "label": "SNOx <400 m",
        "description": "Höchste Schneehöhe des Jahres an Stationen unter 400 m",
        "unit": "cm",
        "kind": "extreme",
        "direction": "desc",
        "source": "DWD daily/kl · SHK_TAG/SHK",
        "height_rule": "Stationshöhe < 400 m",
    },
}


def decode_product(data: bytes) -> str:
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "MESS_DATUM" in text:
            return text
    return data.decode("latin-1", errors="replace")


def parse_float(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_annual_kl_zip(
    content: bytes,
    station_id_hint: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> list[Observation]:
    """Liest TXK, TNK und SHK_TAG/SHK in einem einzigen KL-Durchlauf."""
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
            if {"STATIONS_ID", "MESS_DATUM", "TXK", "TNK"}.issubset(columns):
                product_files.append(name)

        if not product_files:
            return []

        # Normalerweise genau eine KL-Produktdatei.
        product_name = product_files[0]
        text = decode_product(archive.read(product_name))
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        fields = [(field or "").strip() for field in (reader.fieldnames or [])]
        lookup = {field.upper(): field for field in fields}

        station_field = lookup.get("STATIONS_ID")
        date_field = lookup.get("MESS_DATUM")
        txk_field = lookup.get("TXK")
        tnk_field = lookup.get("TNK")
        snow_field = lookup.get("SHK_TAG") or lookup.get("SHK")

        if not station_field or not date_field or not txk_field or not tnk_field:
            return []

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

            station_raw = str(row.get(station_field) or "").strip()
            station_id = station_raw.zfill(5) if station_raw else station_id_hint
            segment = metadata.segment_for(station_id, day)

            values: dict[str, float] = {}

            txk = parse_float(row.get(txk_field))
            if txk is not None and -60.0 <= txk <= 60.0:
                values["txk"] = round(txk, 1)

            tnk = parse_float(row.get(tnk_field))
            if tnk is not None and -60.0 <= tnk <= 60.0:
                values["tnk"] = round(tnk, 1)

            if snow_field:
                snow = parse_float(row.get(snow_field))
                # Negative DWD-Fehlwerte niemals als 0 cm interpretieren.
                if snow is not None and 0.0 <= snow <= 2000.0:
                    values["snow"] = round(snow, 1)

            if values:
                observations.append(
                    Observation(
                        day=day,
                        metadata_key=segment.key,
                        state=segment.state,
                        station_id=station_id,
                        values=values,
                        preliminary=preliminary,
                    )
                )

    return observations


def extreme_entry(
    value: float,
    day: date,
    metadata_key: str,
    preliminary: bool,
) -> list[Any]:
    return [
        round(float(value), 1),
        day.isoformat(),
        metadata_key,
        1 if preliminary else 0,
    ]


def count_entry(
    count: int,
    metadata_key: str,
    preliminary: bool,
) -> list[Any]:
    return [
        int(count),
        metadata_key,
        1 if preliminary else 0,
    ]


def better_extreme(metric: str, new: list[Any], old: list[Any]) -> bool:
    direction = str(METRICS[metric]["direction"])
    nv = float(new[0])
    ov = float(old[0])

    if nv != ov:
        return nv > ov if direction == "desc" else nv < ov

    nd = str(new[1])
    od = str(old[1])
    if nd != od:
        return nd < od

    ns = str(new[2]).split(":", 1)[0]
    os = str(old[2]).split(":", 1)[0]
    return ns < os


def better_count(new: list[Any], old: list[Any]) -> bool:
    nc = int(new[0])
    oc = int(old[0])
    if nc != oc:
        return nc > oc
    ns = str(new[1]).split(":", 1)[0]
    os = str(old[1]).split(":", 1)[0]
    return ns < os


class AnnualAccumulator:
    def __init__(self) -> None:
        # area -> year -> metric -> entry
        self.records: dict[
            str, dict[int, dict[str, list[Any]]]
        ] = defaultdict(lambda: defaultdict(dict))

        # station/year/state -> counters
        self.counts: dict[
            tuple[str, int, str], dict[str, Any]
        ] = {}

        # Bitset verhindert Doppelzählung in historical/recent-Überlappungen.
        self.seen_temp_days: dict[tuple[str, int], int] = {}

        self.first_day: date | None = None
        self.last_day: date | None = None
        self.kl_observations = 0
        self.rr_observations = 0

    def _areas(self, state: str) -> list[str]:
        result = ["Deutschland"]
        if state in STATE_ORDER:
            result.append(state)
        return result

    def _update_extreme(
        self,
        area: str,
        year: int,
        metric: str,
        entry: list[Any],
    ) -> None:
        bucket = self.records[area][year]
        old = bucket.get(metric)
        if old is None or better_extreme(metric, entry, old):
            bucket[metric] = entry

    def add_kl(self, observation: Observation) -> None:
        year = observation.day.year
        if year < START_YEAR:
            return

        state = observation.state
        areas = self._areas(state)
        values = observation.values

        if "tnk" in values:
            entry = extreme_entry(
                values["tnk"],
                observation.day,
                observation.metadata_key,
                observation.preliminary,
            )
            for area in areas:
                self._update_extreme(area, year, "tnn", entry)

        if "txk" in values:
            entry = extreme_entry(
                values["txk"],
                observation.day,
                observation.metadata_key,
                observation.preliminary,
            )
            for area in areas:
                self._update_extreme(area, year, "txx", entry)

        if "snow" in values:
            segment_height = None
            # Höhe wird später aus metadata_key über station dict gelesen;
            # für die Klassifikation brauchen wir sie bereits hier und tragen
            # sie deshalb im Observation-Wert nicht ein. Der Aufrufer setzt
            # observation._annual_height nicht, daher wird die Klasse über
            # self.station_heights befüllt.
            pass

        # Kenntage: jedes Stationsdatum nur einmal zählen.
        key_day = (observation.station_id, year)
        bit = 1 << (observation.day.timetuple().tm_yday - 1)
        already_seen = bool(self.seen_temp_days.get(key_day, 0) & bit)

        if not already_seen:
            self.seen_temp_days[key_day] = self.seen_temp_days.get(key_day, 0) | bit

            count_key = (
                observation.station_id,
                year,
                state if state in STATE_ORDER else INTERNAL_UNKNOWN,
            )
            info = self.counts.get(count_key)
            if info is None:
                info = {
                    "summer_days_max": 0,
                    "hot_days_max": 0,
                    "desert_days_max": 0,
                    "tropical_nights_max": 0,
                    "metadata_key": observation.metadata_key,
                    "preliminary": False,
                }
                self.counts[count_key] = info

            # Neuere Metadaten innerhalb desselben Jahres sind für die
            # Stationsbezeichnung im späteren Frontend hilfreicher.
            info["metadata_key"] = observation.metadata_key
            info["preliminary"] = bool(
                info["preliminary"] or observation.preliminary
            )

            txk = values.get("txk")
            if txk is not None:
                # Exakt wie in der Excel-Vorlage: strikt > 25 / > 30.
                if float(txk) > 25.0:
                    info["summer_days_max"] += 1
                if float(txk) > 30.0:
                    info["hot_days_max"] += 1
                if float(txk) >= 35.0:
                    info["desert_days_max"] += 1

            tnk = values.get("tnk")
            if tnk is not None and float(tnk) > 20.0:
                info["tropical_nights_max"] += 1

        self.kl_observations += 1
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

    def add_snow(
        self,
        observation: Observation,
        height: int | None,
    ) -> None:
        if "snow" not in observation.values or height is None:
            return
        year = observation.day.year
        if year < START_YEAR:
            return

        metric = "snox_ge_400" if height >= 400 else "snox_lt_400"
        entry = extreme_entry(
            observation.values["snow"],
            observation.day,
            observation.metadata_key,
            observation.preliminary,
        )
        for area in self._areas(observation.state):
            self._update_extreme(area, year, metric, entry)

    def add_rr(self, observation: Observation) -> None:
        value = observation.values.get("rsk_high")
        if value is None:
            return
        year = observation.day.year
        if year < START_YEAR:
            return

        entry = extreme_entry(
            value,
            observation.day,
            observation.metadata_key,
            observation.preliminary,
        )
        for area in self._areas(observation.state):
            self._update_extreme(area, year, "rr24x", entry)

        self.rr_observations += 1
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

    def finalize_counts(self) -> None:
        for (station_id, year, state), info in self.counts.items():
            areas = self._areas(state)
            for metric in (
                "summer_days_max",
                "hot_days_max",
                "desert_days_max",
                "tropical_nights_max",
            ):
                entry = count_entry(
                    int(info[metric]),
                    str(info["metadata_key"]),
                    bool(info["preliminary"]),
                )
                for area in areas:
                    bucket = self.records[area][year]
                    old = bucket.get(metric)
                    if old is None or better_count(entry, old):
                        bucket[metric] = entry

    def public_records(self, end_year: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        metric_ids = list(METRICS)

        for area in AREAS:
            years: dict[str, Any] = {}
            for year in range(START_YEAR, end_year + 1):
                raw = self.records.get(area, {}).get(year, {})
                years[str(year)] = {
                    metric: raw.get(metric)
                    for metric in metric_ids
                }
            result[area] = years

        return result


def consume_kl(
    accumulator: AnnualAccumulator,
    metadata: MetadataIndex,
    filenames: list[str],
    base_url: str,
    start_date: date,
    end_date: date,
    preliminary: bool,
    max_workers: int,
) -> int:
    before = accumulator.kl_observations

    for observations in iter_downloaded_observations(
        filenames,
        base_url,
        metadata,
        start_date,
        end_date,
        preliminary,
        max_workers,
        station_pattern=STATION_ID_PATTERN,
        parser=parse_annual_kl_zip,
        failure_tolerance=0.02,
    ):
        for observation in observations:
            accumulator.add_kl(observation)
            segment = metadata.segment_for(
                observation.station_id,
                observation.day,
            )
            accumulator.add_snow(observation, segment.height)

    return accumulator.kl_observations - before


def consume_rr(
    accumulator: AnnualAccumulator,
    metadata: MetadataIndex,
    filenames: list[str],
    base_url: str,
    start_date: date,
    end_date: date,
    preliminary: bool,
    max_workers: int,
) -> int:
    before = accumulator.rr_observations

    for observations in iter_downloaded_observations(
        filenames,
        base_url,
        metadata,
        start_date,
        end_date,
        preliminary,
        max_workers,
        station_pattern=RR_STATION_ID_PATTERN,
        parser=parse_rr_station_zip,
        failure_tolerance=0.02,
    ):
        for observation in observations:
            accumulator.add_rr(observation)

    return accumulator.rr_observations - before


def referenced_metadata_keys(part: Any, target: set[str]) -> None:
    if isinstance(part, dict):
        for value in part.values():
            referenced_metadata_keys(value, target)
        return

    if isinstance(part, list):
        # Extreme: [value,date,metadata_key,preliminary]
        if (
            len(part) == 4
            and isinstance(part[1], str)
            and isinstance(part[2], str)
            and ":" in part[2]
        ):
            target.add(part[2])
            return
        # Count: [count,metadata_key,preliminary]
        if (
            len(part) == 3
            and isinstance(part[1], str)
            and ":" in part[1]
        ):
            target.add(part[1])
            return
        for value in part:
            referenced_metadata_keys(value, target)


def merge_station_metadata(
    kl_metadata: MetadataIndex,
    rr_metadata: MetadataIndex,
    records: dict[str, Any],
) -> dict[str, Any]:
    keys: set[str] = set()
    referenced_metadata_keys(records, keys)

    merged = kl_metadata.public_dict()
    for key, value in rr_metadata.public_dict().items():
        merged.setdefault(key, value)

    return {
        key: merged[key]
        for key in sorted(keys)
        if key in merged
    }



def first_available_year(years: dict[str, Any]) -> int | None:
    found: list[int] = []

    for year_text, row in years.items():
        if not isinstance(row, dict):
            continue
        if not any(value is not None for value in row.values()):
            continue
        try:
            found.append(int(year_text))
        except ValueError:
            continue

    return min(found) if found else None


def derive_area_start_years(
    records: dict[str, Any],
) -> dict[str, int | None]:
    result: dict[str, int | None] = {}

    for area in AREAS:
        first = first_available_year(records.get(area, {}))
        result[area] = (
            max(LIST_MIN_YEAR, first)
            if first is not None
            else None
        )

    return result



def merge_official_tropical_nights(
    records: dict[str, Any],
) -> dict[str, Any]:
    path = Path("data/dwd_annual_tropical_nights.json")
    if not path.is_file():
        raise RuntimeError(
            "Offizielle Tropennacht-Datenbasis fehlt: "
            "data/dwd_annual_tropical_nights.json"
        )

    tropical = json.loads(path.read_text(encoding="utf-8"))
    if tropical.get("areas") != AREAS:
        raise RuntimeError(
            "Tropennacht-Gebietsliste passt nicht zur Hauptdatei."
        )

    for area in AREAS:
        tropical_years = tropical["records"][area]
        for year, row in records[area].items():
            row["tropical_nights_max"] = tropical_years.get(year)

    return tropical


def reference_value(
    records: dict[str, Any],
    area: str,
    year: int,
    metric: str,
) -> float | int | None:
    entry = records.get(area, {}).get(str(year), {}).get(metric)
    return entry[0] if entry else None


def print_baden_wuerttemberg_reference(records: dict[str, Any]) -> None:
    """
    Kontrollwerte aus der vom Nutzer bereitgestellten Excel-Tabelle
    'Extremwerte'. Sie dienen nur als Vergleich und lassen den Workflow
    nicht fehlschlagen, weil der aktuelle DWD-Bestand nachträglich
    korrigierte oder zusätzliche Stationen enthalten kann.
    """
    expected = {
        2003: {
            "tnn": -22.5,
            "txx": 40.2,
            "summer_days_max": 112,
            "hot_days_max": 60,
            "tropical_nights_max": 31,
            "rr24x": 97.0,
            "snox_ge_400": 170.0,
            "snox_lt_400": 65.0,
        },
        2015: {
            "tnn": -20.4,
            "txx": 40.2,
            "summer_days_max": 71,
            "hot_days_max": 37,
            "tropical_nights_max": 15,
            "rr24x": 147.3,
            "snox_ge_400": 95.0,
            "snox_lt_400": 23.0,
        },
        2024: {
            "tnn": -19.5,
            "txx": 35.4,
            "summer_days_max": 54,
            "hot_days_max": 13,
            "tropical_nights_max": 5,
            "rr24x": 129.7,
            "snox_ge_400": 93.0,
            "snox_lt_400": 7.0,
        },
    }

    print("=== Vergleich Baden-Württemberg mit Excel 'Extremwerte' ===")
    for year, metrics in expected.items():
        print(f"{year}:")
        for metric, excel_value in metrics.items():
            dwd_value = reference_value(
                records,
                "Baden-Württemberg",
                year,
                metric,
            )
            print(
                f"  {metric:22s} "
                f"DWD={dwd_value!s:>8} | Excel={excel_value}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="data/dwd_annual_extremes.json",
    )
    parser.add_argument("--max-workers", type=int, default=10)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).date()
    start_date = date(START_YEAR, 1, 1)

    print("=== DWD JÄHRLICHE EXTREMWERTE · STUFE 1 ===", flush=True)
    print("Gebiete: Deutschland + 16 Bundesländer", flush=True)
    print(f"Jahre: ab {START_YEAR}", flush=True)
    print(
        "Parameter: TNn, TXx, >25, >30, Tmin>20, RR24x, "
        "SNOx >=400 m, SNOx <400 m",
        flush=True,
    )
    print(
        "Kenntage werden strikt nach Excel als >25, >30 und >20 gezählt.",
        flush=True,
    )

    kl_metadata = parse_metadata(download(METADATA_URL, timeout=90))
    rr_metadata = parse_metadata(download(RR_METADATA_URL, timeout=90))

    kl_historical = list_station_files(
        HISTORICAL_URL,
        HISTORICAL_PATTERN,
        minimum=500,
    )
    kl_recent = list_station_files(
        RECENT_URL,
        RECENT_PATTERN,
        minimum=300,
    )
    rr_historical = list_station_files(
        RR_HISTORICAL_URL,
        RR_HISTORICAL_PATTERN,
        minimum=1000,
    )
    rr_recent = list_station_files(
        RR_RECENT_URL,
        RR_RECENT_PATTERN,
        minimum=500,
    )

    print(f"KL historical: {len(kl_historical):,}", flush=True)
    print(f"KL recent:     {len(kl_recent):,}", flush=True)
    print(f"RR historical: {len(rr_historical):,}", flush=True)
    print(f"RR recent:     {len(rr_recent):,}", flush=True)

    acc = AnnualAccumulator()

    n = consume_kl(
        acc,
        kl_metadata,
        kl_historical,
        HISTORICAL_URL,
        start_date,
        today,
        False,
        args.max_workers,
    )
    print(f"KL historical Beobachtungen: {n:,}", flush=True)

    # Recent überlappt historical. Die Bitset-Deduplizierung verhindert
    # doppelte Kenntage; Extremwerte sind gegen identische Dopplungen robust.
    n = consume_kl(
        acc,
        kl_metadata,
        kl_recent,
        RECENT_URL,
        date(today.year - 2, 1, 1),
        today,
        True,
        args.max_workers,
    )
    print(f"KL recent Beobachtungen: {n:,}", flush=True)

    n = consume_rr(
        acc,
        rr_metadata,
        rr_historical,
        RR_HISTORICAL_URL,
        start_date,
        today,
        False,
        args.max_workers,
    )
    print(f"RR historical Beobachtungen: {n:,}", flush=True)

    n = consume_rr(
        acc,
        rr_metadata,
        rr_recent,
        RR_RECENT_URL,
        date(today.year - 2, 1, 1),
        today,
        True,
        args.max_workers,
    )
    print(f"RR recent Beobachtungen: {n:,}", flush=True)

    acc.finalize_counts()
    records = acc.public_records(today.year)
    tropical_data = merge_official_tropical_nights(records)
    area_start_years = derive_area_start_years(records)
    stations = merge_station_metadata(
        kl_metadata,
        rr_metadata,
        records,
    )
    for key, value in tropical_data.get("stations", {}).items():
        stations.setdefault(key, value)

    payload = {
        "version": VERSION,
        "generated_at": (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "project": "Jährliche Extremwerte",
        "source_template": (
            "Vom Nutzer bereitgestellte Excel-Tabelle "
            "'Extremwerte_Baden-Württemberg.xlsx', Blatt 'Extremwerte'"
        ),
        "data_sources": {
            "temperature_snow": (
                "DWD CDC observations_germany/climate/daily/kl"
            ),
            "precipitation": (
                "DWD CDC observations_germany/climate/daily/more_precip"
            ),
        },
        "data_start": (
            acc.first_day.isoformat()
            if acc.first_day
            else None
        ),
        "data_through": (
            acc.last_day.isoformat()
            if acc.last_day
            else None
        ),
        "start_year": START_YEAR,
        "list_min_year": LIST_MIN_YEAR,
        "area_start_years": area_start_years,
        "end_year": today.year,
        "areas": AREAS,
        "metrics": METRICS,
        "entry_schema": {
            "extreme": [
                "value",
                "date",
                "metadata_key",
                "preliminary",
            ],
            "station_year_count": [
                "count",
                "metadata_key",
                "preliminary",
            ],
        },
        "stations": stations,
        "records": records,
        "stats": {
            "kl_observations": acc.kl_observations,
            "rr_observations": acc.rr_observations,
            "station_year_count_series": len(acc.counts),
        },
        "method_note": (
            "Rohdaten werden ab 1861 ausgewertet. Für spätere Jahreslisten ""beginnt jedes Gebiet frühestens 1881; liegt der erste tatsächlich ""vorhandene Jahreswert später, wird dieses spätere Jahr verwendet. ""TNn und TXx stammen aus TNK/TXK. "
            "Die drei Kenntage werden entsprechend der Excel-Vorlage strikt "
            "mit TXK >25,0 °C, TXK >30,0 °C und TXK >=35,0 °C gezählt. ""Tropennächte werden separat nach DWD-Definition aus ""TT_TU-Stundenwerten für 18–06 UTC mit Minimum >=20,0 °C übernommen; "
            "pro Gebiet/Jahr wird die höchste Stationsanzahl gespeichert. "
            "RR24x verwendet das erweiterte tägliche DWD-RR-Netz (RS). "
            "SNOx verwendet SHK_TAG/SHK aus daily/kl und wird nach "
            "Stationshöhe getrennt: 400 m zählt zur Klasse >=400 m. "
            "Windextreme sind bewusst noch nicht Bestandteil von Stufe 1."
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

    # Strukturprüfungen
    assert len(payload["areas"]) == 17
    assert set(payload["metrics"]) == {
        "tnn",
        "txx",
        "summer_days_max",
        "hot_days_max",
        "desert_days_max",
        "tropical_nights_max",
        "rr24x",
        "snox_ge_400",
        "snox_lt_400",
    }
    assert payload["data_start"] is not None
    assert payload["data_through"] is not None
    assert payload["stats"]["kl_observations"] > 1_000_000
    assert payload["stats"]["rr_observations"] > 1_000_000

    # Aktuelle/neuere Jahre müssen für Baden-Württemberg Kerndaten enthalten.
    bw_2024 = records["Baden-Württemberg"]["2024"]
    for metric in (
        "tnn",
        "txx",
        "summer_days_max",
        "hot_days_max",
        "desert_days_max",
        "tropical_nights_max",
        "rr24x",
        "snox_ge_400",
        "snox_lt_400",
    ):
        assert bw_2024[metric] is not None, (
            f"Baden-Württemberg 2024 ohne {metric}"
        )

    print_baden_wuerttemberg_reference(records)

    print("Jährliche Extremwert-Datenbasis erfolgreich gebaut.", flush=True)
    print(
        f"Datenzeitraum: {payload['data_start']} bis "
        f"{payload['data_through']}",
        flush=True,
    )
    print(
        f"KL Beobachtungen: {acc.kl_observations:,}",
        flush=True,
    )
    print(
        f"RR Beobachtungen: {acc.rr_observations:,}",
        flush=True,
    )
    print(
        f"Stationsjahre für Kenntage: {len(acc.counts):,}",
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
