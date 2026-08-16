#!/usr/bin/env python3
from __future__ import annotations

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
    Observation,
    download,
    iter_downloaded_observations,
    list_station_files,
    parse_metadata,
)

MAIN_JSON = Path("data/dwd_annual_extremes.json")
MAIN_BUILDER = Path("scripts/build_dwd_annual_extremes.py")

START_YEAR = 1861
THRESHOLD_C = 35.0
METRIC = "desert_days_max"

METRIC_META = {
    "label": "max. Wüstentage ≥35 °C",
    "description": "Höchste Zahl der Tage mit TXK >= 35,0 °C an einer Station",
    "unit": "Tage",
    "kind": "station_year_count",
    "threshold": "TXK >= 35.0",
    "direction": "desc",
    "source": "DWD daily/kl · TXK",
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


def parse_tmax_zip(
    content: bytes,
    station_id_hint: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> list[Observation]:
    observations: list[Observation] = []

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        product_name = None

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

            columns = {part.strip().upper() for part in first_line.split(";")}
            if {"STATIONS_ID", "MESS_DATUM", "TXK"}.issubset(columns):
                product_name = name
                break

        if not product_name:
            return []

        text = decode_product(archive.read(product_name))
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        fields = [(field or "").strip() for field in (reader.fieldnames or [])]
        lookup = {field.upper(): field for field in fields}

        station_field = lookup.get("STATIONS_ID")
        date_field = lookup.get("MESS_DATUM")
        txk_field = lookup.get("TXK")
        if not station_field or not date_field or not txk_field:
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

            txk = parse_float(row.get(txk_field))
            if txk is None or not (-60.0 <= txk <= 60.0):
                continue

            station_raw = str(row.get(station_field) or "").strip()
            station_id = station_raw.zfill(5) if station_raw else station_id_hint
            segment = metadata.segment_for(station_id, day)

            observations.append(
                Observation(
                    day=day,
                    metadata_key=segment.key,
                    state=segment.state,
                    station_id=station_id,
                    values={"txk": round(txk, 1)},
                    preliminary=preliminary,
                )
            )

    return observations


class DesertCounter:
    def __init__(self) -> None:
        self.counts: dict[tuple[str, int, str], dict[str, Any]] = {}
        self.seen_days: dict[tuple[str, int], int] = {}
        self.valid_tmax_observations = 0
        self.desert_day_observations = 0

    def add(self, observation: Observation) -> None:
        year = observation.day.year
        if year < START_YEAR:
            return

        day_key = (observation.station_id, year)
        bit = 1 << (observation.day.timetuple().tm_yday - 1)
        seen = self.seen_days.get(day_key, 0)
        if seen & bit:
            return
        self.seen_days[day_key] = seen | bit

        self.valid_tmax_observations += 1
        txk = float(observation.values["txk"])
        if txk < THRESHOLD_C:
            return

        self.desert_day_observations += 1

        state = (
            observation.state
            if observation.state in STATE_ORDER
            else INTERNAL_UNKNOWN
        )
        key = (observation.station_id, year, state)
        info = self.counts.get(key)
        if info is None:
            info = {
                "count": 0,
                "metadata_key": observation.metadata_key,
                "preliminary": False,
            }
            self.counts[key] = info

        info["count"] += 1
        info["metadata_key"] = observation.metadata_key
        info["preliminary"] = bool(
            info["preliminary"] or observation.preliminary
        )

    @staticmethod
    def better(new: list[Any], old: list[Any]) -> bool:
        if int(new[0]) != int(old[0]):
            return int(new[0]) > int(old[0])
        ns = str(new[1]).split(":", 1)[0]
        os = str(old[1]).split(":", 1)[0]
        return ns < os

    def area_records(
        self,
        areas: list[str],
        start_year: int,
        end_year: int,
    ) -> dict[str, dict[str, list[Any] | None]]:
        result = {
            area: {
                str(year): None
                for year in range(start_year, end_year + 1)
            }
            for area in areas
        }

        for (station_id, year, state), info in self.counts.items():
            entry = [
                int(info["count"]),
                str(info["metadata_key"]),
                1 if info["preliminary"] else 0,
            ]
            target_areas = ["Deutschland"]
            if state in STATE_ORDER:
                target_areas.append(state)

            for area in target_areas:
                old = result[area][str(year)]
                if old is None or self.better(entry, old):
                    result[area][str(year)] = entry

        return result


def consume(
    counter: DesertCounter,
    metadata: MetadataIndex,
    filenames: list[str],
    base_url: str,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> None:
    for observations in iter_downloaded_observations(
        filenames,
        base_url,
        metadata,
        start_date,
        end_date,
        preliminary,
        10,
        station_pattern=STATION_ID_PATTERN,
        parser=parse_tmax_zip,
        failure_tolerance=0.02,
    ):
        for observation in observations:
            counter.add(observation)


def patch_main_builder() -> None:
    text = MAIN_BUILDER.read_text(encoding="utf-8")
    original = text

    if '"desert_days_max": {' not in text:
        needle = '    "tropical_nights_max": {\n'
        block = (
            '    "desert_days_max": {\n'
            '        "label": "max. Wüstentage ≥35 °C",\n'
            '        "description": "Höchste Zahl der Tage mit TXK >= 35,0 °C an einer Station",\n'
            '        "unit": "Tage",\n'
            '        "kind": "station_year_count",\n'
            '        "threshold": "TXK >= 35.0",\n'
            '        "direction": "desc",\n'
            '        "source": "DWD daily/kl · TXK",\n'
            '    },\n'
        )
        if needle not in text:
            raise RuntimeError("METRICS-Einfügepunkt nicht gefunden.")
        text = text.replace(needle, block + needle, 1)

    if '"desert_days_max": 0,' not in text:
        needle = (
            '                    "hot_days_max": 0,\n'
            '                    "tropical_nights_max": 0,\n'
        )
        replacement = (
            '                    "hot_days_max": 0,\n'
            '                    "desert_days_max": 0,\n'
            '                    "tropical_nights_max": 0,\n'
        )
        if needle not in text:
            raise RuntimeError("Count-Initialisierung nicht gefunden.")
        text = text.replace(needle, replacement, 1)

    if 'info["desert_days_max"] += 1' not in text:
        needle = (
            '                if float(txk) > 30.0:\n'
            '                    info["hot_days_max"] += 1\n'
        )
        replacement = (
            '                if float(txk) > 30.0:\n'
            '                    info["hot_days_max"] += 1\n'
            '                if float(txk) >= 35.0:\n'
            '                    info["desert_days_max"] += 1\n'
        )
        if needle not in text:
            raise RuntimeError("TXK-Kenntageblock nicht gefunden.")
        text = text.replace(needle, replacement, 1)

    # finalize_counts
    if (
        '"desert_days_max",' not in
        text[text.find("def finalize_counts"):text.find("def public_records")]
    ):
        needle = (
            '                "hot_days_max",\n'
            '                "tropical_nights_max",\n'
        )
        replacement = (
            '                "hot_days_max",\n'
            '                "desert_days_max",\n'
            '                "tropical_nights_max",\n'
        )
        if needle not in text:
            raise RuntimeError("finalize_counts-Marker nicht gefunden.")
        text = text.replace(needle, replacement, 1)

    # Spätere Prüfsets und BW-Kontrollschleife.
    text = text.replace(
        '        "hot_days_max",\n        "tropical_nights_max",\n',
        '        "hot_days_max",\n        "desert_days_max",\n        "tropical_nights_max",\n',
    )
    text = text.replace(
        '        "hot_days_max",\n        "tropical_nights_max",\n        "rr24x",\n',
        '        "hot_days_max",\n        "desert_days_max",\n        "tropical_nights_max",\n        "rr24x",\n',
    )

    if "TXK >=35,0 °C" not in text:
        text = text.replace(
            '"mit TXK >25,0 °C, TXK >30,0 °C und TNK >20,0 °C gezählt; "',
            '"mit TXK >25,0 °C, TXK >30,0 °C, TXK >=35,0 °C und TNK >20,0 °C gezählt; "',
        )

    if text != original:
        MAIN_BUILDER.write_text(text, encoding="utf-8")
        print("Haupt-Builder dauerhaft um Wüstentage ergänzt.")
    else:
        print("Haupt-Builder war bereits aktuell.")


def main() -> int:
    if not MAIN_JSON.is_file():
        raise SystemExit(f"Fehlt: {MAIN_JSON}")
    if not MAIN_BUILDER.is_file():
        raise SystemExit(f"Fehlt: {MAIN_BUILDER}")

    data = json.loads(MAIN_JSON.read_text(encoding="utf-8"))
    areas = list(data["areas"])
    start_year = int(data["start_year"])
    end_year = int(data["end_year"])

    metadata = parse_metadata(download(METADATA_URL, timeout=90))
    historical = list_station_files(
        HISTORICAL_URL,
        HISTORICAL_PATTERN,
        minimum=500,
    )
    recent = list_station_files(
        RECENT_URL,
        RECENT_PATTERN,
        minimum=300,
    )

    today = datetime.now(timezone.utc).date()

    print("=== DWD JÄHRLICHE EXTREMWERTE · WÜSTENTAGE ===")
    print("Definition: TXK >= 35,0 °C")
    print(f"KL historical: {len(historical):,}")
    print(f"KL recent:     {len(recent):,}")

    counter = DesertCounter()

    consume(
        counter,
        metadata,
        historical,
        HISTORICAL_URL,
        date(START_YEAR, 1, 1),
        today,
        False,
    )
    consume(
        counter,
        metadata,
        recent,
        RECENT_URL,
        date(today.year - 2, 1, 1),
        today,
        True,
    )

    print(
        "Gültige Tmax-Werte:",
        f"{counter.valid_tmax_observations:,}",
    )
    print(
        "Stations-Tage >=35,0 °C:",
        f"{counter.desert_day_observations:,}",
    )

    area_records = counter.area_records(
        areas,
        start_year,
        end_year,
    )

    for area in areas:
        for year in range(start_year, end_year + 1):
            year_key = str(year)
            row = data["records"][area][year_key]
            entry = area_records[area][year_key]

            # 0 als echter Wert, wenn Temperaturdaten vorhanden waren,
            # aber keine Station 35,0 °C erreichte.
            if entry is None:
                base = row.get("summer_days_max") or row.get("hot_days_max")
                if base is not None:
                    entry = [0, base[1], base[2]]

            row[METRIC] = entry

    data["metrics"][METRIC] = METRIC_META
    data["version"] = max(int(data.get("version", 1)), 3)

    stats = dict(data.get("stats", {}))
    stats["desert_day_observations_ge_35c"] = (
        counter.desert_day_observations
    )
    stats["desert_day_station_year_series"] = len(counter.counts)
    data["stats"] = stats

    public_stations = metadata.public_dict()
    for area in areas:
        for row in data["records"][area].values():
            entry = row.get(METRIC)
            if not entry:
                continue
            key = str(entry[1])
            if key in public_stations:
                data["stations"].setdefault(key, public_stations[key])

    note = str(data.get("method_note") or "")
    desert_note = (
        " Wüstentage werden als Tage mit TXK >=35,0 °C definiert; "
        "pro Gebiet und Jahr wird die höchste Stationsanzahl gespeichert."
    )
    if "Wüstentage werden als Tage mit TXK >=35,0 °C" not in note:
        data["method_note"] = note.rstrip() + desert_note

    MAIN_JSON.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )

    patch_main_builder()

    assert METRIC in data["metrics"]
    assert len(data["metrics"]) == 11
    assert len(data["areas"]) == 17

    print("Wüstentage erfolgreich in Haupt-JSON eingebaut.")
    print("Parameter gesamt:", len(data["metrics"]))
    for area in ("Deutschland", "Baden-Württemberg", "Saarland"):
        print(
            area,
            end_year,
            data["records"][area][str(end_year)][METRIC],
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
