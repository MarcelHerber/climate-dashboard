#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from update_station_records import (
    HISTORICAL_PATTERN,
    HISTORICAL_URL,
    METADATA_URL,
    RECENT_PATTERN,
    RECENT_URL,
    STATE_ORDER,
    STATION_ID_PATTERN,
    MetadataIndex,
    Observation,
    download,
    iter_downloaded_observations,
    list_station_files,
    parse_metadata,
)

VERSION = 1
START_YEAR = 1881
AREAS = ["Deutschland", *STATE_ORDER]
HOLIDAYS = ["easter", "christmas"]

METRICS = {
    "tnn": {
        "label": "TNn",
        "description": "Niedrigstes Tagesminimum im Feiertagsfenster",
        "unit": "°C",
        "direction": "asc",
        "source": "DWD daily/kl · TNK",
    },
    "txx": {
        "label": "TXx",
        "description": "Höchstes Tagesmaximum im Feiertagsfenster",
        "unit": "°C",
        "direction": "desc",
        "source": "DWD daily/kl · TXK",
    },
}

HOLIDAY_META = {
    "easter": {
        "label": "Ostern",
        "rule": "Karfreitag bis Ostermontag",
        "days": 4,
    },
    "christmas": {
        "label": "Weihnachten",
        "rule": "24. bis 26. Dezember",
        "days": 3,
    },
}


def easter_sunday(year: int) -> date:
    """Gregorianisches Osterdatum nach Meeus/Jones/Butcher."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=None)
def holiday_days(year: int) -> dict[date, str]:
    easter = easter_sunday(year)
    result: dict[date, str] = {}
    for offset in (-2, -1, 0, 1):
        result[easter + timedelta(days=offset)] = "easter"
    for day in (24, 25, 26):
        result[date(year, 12, day)] = "christmas"
    return result


@lru_cache(maxsize=None)
def holiday_stamp_lookup(start_year: int, end_year: int) -> set[str]:
    result: set[str] = set()
    for year in range(start_year, end_year + 1):
        result.update(day.strftime("%Y%m%d") for day in holiday_days(year))
    return result


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


def parse_holiday_kl_zip(
    content: bytes,
    station_id_hint: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> list[Observation]:
    """Liest ausschließlich TXK/TNK an den gewünschten Feiertagstagen."""
    observations: list[Observation] = []
    wanted = holiday_stamp_lookup(start_date.year, end_date.year)

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        product_name: str | None = None
        for name in archive.namelist():
            if not name.lower().endswith(".txt") or "produkt" not in name.lower():
                continue
            try:
                first_line = archive.read(name).splitlines()[0].decode(
                    "latin-1", errors="replace"
                )
            except (KeyError, IndexError):
                continue
            columns = {part.strip().upper() for part in first_line.split(";")}
            if {"STATIONS_ID", "MESS_DATUM", "TXK", "TNK"}.issubset(columns):
                product_name = name
                break

        if product_name is None:
            return []

        text = decode_product(archive.read(product_name))
        reader = csv.DictReader(io.StringIO(text), delimiter=";")

        # DWD-Header enthalten teils Leerzeichen. Deshalb wird jede Zeile
        # auf bereinigte Spaltennamen normalisiert, bevor darauf zugegriffen wird.
        for raw_row in reader:
            row = {
                (key or "").strip().upper(): (
                    value.strip() if isinstance(value, str) else value
                )
                for key, value in raw_row.items()
            }

            stamp = str(row.get("MESS_DATUM") or "").strip()
            if stamp not in wanted:
                continue

            try:
                day = datetime.strptime(stamp, "%Y%m%d").date()
            except ValueError:
                continue
            if day < start_date or day > end_date:
                continue

            station_raw = str(row.get("STATIONS_ID") or "").strip()
            station_id = station_raw.zfill(5) if station_raw else station_id_hint
            segment = metadata.segment_for(station_id, day)

            values: dict[str, float] = {}
            txk = parse_float(row.get("TXK"))
            if txk is not None and -60.0 <= txk <= 60.0:
                values["txk"] = round(txk, 1)
            tnk = parse_float(row.get("TNK"))
            if tnk is not None and -60.0 <= tnk <= 60.0:
                values["tnk"] = round(tnk, 1)

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
    return [round(float(value), 1), day.isoformat(), metadata_key, 1 if preliminary else 0]


def better_extreme(metric: str, new: list[Any], old: list[Any]) -> bool:
    direction = str(METRICS[metric]["direction"])
    nv = float(new[0])
    ov = float(old[0])
    if nv != ov:
        return nv > ov if direction == "desc" else nv < ov

    nd, od = str(new[1]), str(old[1])
    if nd != od:
        return nd < od
    ns = str(new[2]).split(":", 1)[0]
    os = str(old[2]).split(":", 1)[0]
    return ns < os


class HolidayAccumulator:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, dict[int, dict[str, list[Any]]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(dict))
        )
        self.observations = 0
        self.first_day: date | None = None
        self.last_day: date | None = None

    @staticmethod
    def _areas(state: str) -> list[str]:
        result = ["Deutschland"]
        if state in STATE_ORDER:
            result.append(state)
        return result

    def add(self, observation: Observation) -> None:
        if observation.day.year < START_YEAR:
            return
        holiday = holiday_days(observation.day.year).get(observation.day)
        if holiday is None:
            return

        for metric, source_key in (("tnn", "tnk"), ("txx", "txk")):
            value = observation.values.get(source_key)
            if value is None:
                continue
            entry = extreme_entry(
                value,
                observation.day,
                observation.metadata_key,
                observation.preliminary,
            )
            for area in self._areas(observation.state):
                bucket = self.records[area][holiday][observation.day.year]
                old = bucket.get(metric)
                if old is None or better_extreme(metric, entry, old):
                    bucket[metric] = entry

        self.observations += 1
        self.first_day = observation.day if self.first_day is None else min(self.first_day, observation.day)
        self.last_day = observation.day if self.last_day is None else max(self.last_day, observation.day)

    def public_records(self, end_year: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for area in AREAS:
            result[area] = {}
            for holiday in HOLIDAYS:
                result[area][holiday] = {}
                for year in range(START_YEAR, end_year + 1):
                    raw = self.records.get(area, {}).get(holiday, {}).get(year, {})
                    result[area][holiday][str(year)] = {
                        metric: raw.get(metric) for metric in METRICS
                    }
        return result


def consume_kl(
    accumulator: HolidayAccumulator,
    metadata: MetadataIndex,
    filenames: list[str],
    base_url: str,
    start_date: date,
    end_date: date,
    preliminary: bool,
    max_workers: int,
) -> int:
    before = accumulator.observations
    for observations in iter_downloaded_observations(
        filenames,
        base_url,
        metadata,
        start_date,
        end_date,
        preliminary,
        max_workers,
        station_pattern=STATION_ID_PATTERN,
        parser=parse_holiday_kl_zip,
        failure_tolerance=0.02,
    ):
        for observation in observations:
            accumulator.add(observation)
    return accumulator.observations - before


def referenced_metadata_keys(part: Any, target: set[str]) -> None:
    if isinstance(part, dict):
        for value in part.values():
            referenced_metadata_keys(value, target)
        return
    if isinstance(part, list):
        if len(part) == 4 and isinstance(part[2], str) and ":" in part[2]:
            target.add(part[2])
            return
        for value in part:
            referenced_metadata_keys(value, target)


def selected_station_metadata(metadata: MetadataIndex, records: dict[str, Any]) -> dict[str, Any]:
    keys: set[str] = set()
    referenced_metadata_keys(records, keys)
    public = metadata.public_dict()
    return {key: public[key] for key in sorted(keys) if key in public}


def first_available_year(years: dict[str, Any]) -> int | None:
    found: list[int] = []
    for year_text, row in years.items():
        if isinstance(row, dict) and any(value is not None for value in row.values()):
            try:
                found.append(int(year_text))
            except ValueError:
                pass
    return min(found) if found else None


def derive_area_start_years(records: dict[str, Any]) -> dict[str, Any]:
    return {
        area: {
            holiday: first_available_year(records.get(area, {}).get(holiday, {}))
            for holiday in HOLIDAYS
        }
        for area in AREAS
    }


def holiday_date_metadata(end_year: int) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for year in range(START_YEAR, end_year + 1):
        easter = easter_sunday(year)
        rows[str(year)] = {
            "easter": {
                "from": (easter - timedelta(days=2)).isoformat(),
                "to": (easter + timedelta(days=1)).isoformat(),
                "easter_sunday": easter.isoformat(),
            },
            "christmas": {
                "from": date(year, 12, 24).isoformat(),
                "to": date(year, 12, 26).isoformat(),
            },
        }
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/dwd_holiday_extremes.json")
    parser.add_argument("--max-workers", type=int, default=10)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).date()
    start_date = date(START_YEAR, 1, 1)

    print("=== DWD FEIERTAGS-EXTREMWERTE · DATENBASIS ===", flush=True)
    print("Gebiete: Deutschland + 16 Bundesländer", flush=True)
    print(f"Jahre: {START_YEAR} bis {today.year}", flush=True)
    print("Ostern: Karfreitag bis Ostermontag", flush=True)
    print("Weihnachten: 24. bis 26. Dezember", flush=True)
    print("Parameter: TNn und TXx", flush=True)

    metadata = parse_metadata(download(METADATA_URL, timeout=90))
    historical = list_station_files(HISTORICAL_URL, HISTORICAL_PATTERN, minimum=500)
    recent = list_station_files(RECENT_URL, RECENT_PATTERN, minimum=300)

    print(f"KL historical: {len(historical):,}", flush=True)
    print(f"KL recent:     {len(recent):,}", flush=True)

    acc = HolidayAccumulator()
    n = consume_kl(
        acc, metadata, historical, HISTORICAL_URL,
        start_date, today, False, args.max_workers,
    )
    print(f"Feiertags-Beobachtungen historical: {n:,}", flush=True)

    n = consume_kl(
        acc, metadata, recent, RECENT_URL,
        date(max(START_YEAR, today.year - 2), 1, 1), today,
        True, args.max_workers,
    )
    print(f"Feiertags-Beobachtungen recent:     {n:,}", flush=True)

    records = acc.public_records(today.year)
    stations = selected_station_metadata(metadata, records)

    payload = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project": "Feiertags-Extremwerte",
        "source": "DWD CDC observations_germany/climate/daily/kl",
        "areas": AREAS,
        "start_year": START_YEAR,
        "end_year": today.year,
        "run_date": today.isoformat(),
        "holidays": HOLIDAY_META,
        "metrics": METRICS,
        "entry_schema": ["value", "date", "metadata_key", "preliminary"],
        "area_start_years": derive_area_start_years(records),
        "holiday_dates": holiday_date_metadata(today.year),
        "stations": stations,
        "records": records,
        "stats": {
            "holiday_observations": acc.observations,
            "referenced_stations": len(stations),
            "first_holiday_observation": acc.first_day.isoformat() if acc.first_day else None,
            "last_holiday_observation": acc.last_day.isoformat() if acc.last_day else None,
        },
        "method_note": (
            "Ausgewertet werden DWD-Tageswerte des KL-Netzes. Ostern umfasst "
            "Karfreitag, Karsamstag, Ostersonntag und Ostermontag. Weihnachten "
            "umfasst den 24., 25. und 26. Dezember. Für jedes Gebiet und Jahr "
            "wird innerhalb des jeweiligen Feiertagsfensters das niedrigste "
            "Tagesminimum TNK als TNn und das höchste Tagesmaximum TXK als TXx gespeichert."
        ),
    }

    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )

    assert len(payload["areas"]) == 17
    assert set(payload["holidays"]) == {"easter", "christmas"}
    assert set(payload["metrics"]) == {"tnn", "txx"}
    assert easter_sunday(2024) == date(2024, 3, 31)
    assert easter_sunday(2025) == date(2025, 4, 20)
    assert easter_sunday(2026) == date(2026, 4, 5)
    assert payload["stats"]["holiday_observations"] > 0

    print("Feiertags-Datenbasis erfolgreich gebaut.", flush=True)
    print(f"Feiertags-Beobachtungen: {acc.observations:,}", flush=True)
    print(f"Referenzierte Stationen: {len(stations):,}", flush=True)
    print(f"Ausgabe: {output} ({output.stat().st_size / 1024 / 1024:.2f} MB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
