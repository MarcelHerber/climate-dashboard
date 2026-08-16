#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from update_station_records import (
    STATE_ORDER,
    INTERNAL_UNKNOWN,
    MetadataIndex,
    Observation,
    download,
    iter_downloaded_observations,
    list_station_files,
    parse_metadata,
)

BASE_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/hourly/air_temperature"
)
HISTORICAL_URL = f"{BASE_URL}/historical/"
RECENT_URL = f"{BASE_URL}/recent/"
METADATA_URL = f"{HISTORICAL_URL}TU_Stundenwerte_Beschreibung_Stationen.txt"

HISTORICAL_PATTERN = re.compile(
    r'href=["\'](stundenwerte_TU_\d{5}_\d{8}_\d{8}_hist\.zip)["\']',
    re.IGNORECASE,
)
RECENT_PATTERN = re.compile(
    r'href=["\'](stundenwerte_TU_\d{5}_akt\.zip)["\']',
    re.IGNORECASE,
)
STATION_ID_PATTERN = re.compile(
    r"stundenwerte_TU_(\d{5})_",
    re.IGNORECASE,
)

OUTPUT = Path("data/dwd_annual_tropical_nights.json")
MAIN_JSON = Path("data/dwd_annual_extremes.json")

AREAS = ["Deutschland", *STATE_ORDER]
THRESHOLD_C = 20.0
FULL_MASK = (1 << 13) - 1

METRIC_META = {
    "label": "Tropennächte ≥20 °C",
    "description": (
        "Höchste Zahl der Tropennächte an einer Station; "
        "Nachtminimum 18 UTC bis 06 UTC >= 20,0 °C"
    ),
    "unit": "Nächte",
    "kind": "station_year_count",
    "threshold": "Nachtminimum 18–06 UTC >= 20.0 °C",
    "direction": "desc",
    "source": "DWD hourly/air_temperature · TT_TU",
}


def parse_float(raw: str) -> float | None:
    text = str(raw).strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if not math.isfinite(value) or value <= -999:
        return None
    return value


def slot_for_hour(hour: int) -> int | None:
    if 18 <= hour <= 23:
        return hour - 18
    if 0 <= hour <= 6:
        return 6 + hour
    return None


def night_end_for_timestamp(stamp: datetime) -> date | None:
    if stamp.hour >= 18:
        return stamp.date() + timedelta(days=1)
    if stamp.hour <= 6:
        return stamp.date()
    return None


def parse_hourly_station_zip(
    content: bytes,
    station_id_hint: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> list[Observation]:
    """Aggregiert TT_TU direkt zu Stations-Jahreswerten."""
    nights: dict[date, list[Any]] = {}

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        product_name = None
        for name in archive.namelist():
            if not name.lower().endswith(".txt") or "produkt" not in name.lower():
                continue
            try:
                with archive.open(name) as candidate:
                    header_line = candidate.readline().decode(
                        "latin-1", errors="replace"
                    )
            except (KeyError, OSError):
                continue
            columns = {
                part.strip().upper()
                for part in header_line.split(";")
            }
            if {"STATIONS_ID", "MESS_DATUM", "TT_TU"}.issubset(columns):
                product_name = name
                break

        if not product_name:
            return []

        with archive.open(product_name) as raw:
            text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
            reader = csv.reader(text, delimiter=";")
            header = [column.strip().upper() for column in next(reader)]
            date_idx = header.index("MESS_DATUM")
            temp_idx = header.index("TT_TU")
            maximum_index = max(date_idx, temp_idx)

            for row in reader:
                if len(row) <= maximum_index:
                    continue

                try:
                    stamp = datetime.strptime(
                        row[date_idx].strip(),
                        "%Y%m%d%H",
                    )
                except ValueError:
                    continue

                night_end = night_end_for_timestamp(stamp)
                if night_end is None:
                    continue
                if night_end < start_date or night_end > end_date:
                    continue

                slot = slot_for_hour(stamp.hour)
                if slot is None:
                    continue

                temperature = parse_float(row[temp_idx])
                if temperature is None or not (-60.0 <= temperature <= 60.0):
                    continue

                state = nights.get(night_end)
                if state is None:
                    state = [0, temperature]
                    nights[night_end] = state
                state[0] |= 1 << slot
                state[1] = min(float(state[1]), temperature)

    annual: dict[tuple[int, str, str], dict[str, int]] = defaultdict(
        lambda: {"complete": 0, "tropical": 0}
    )

    for night_end, (mask, minimum) in nights.items():
        if int(mask) != FULL_MASK:
            continue

        segment = metadata.segment_for(station_id_hint, night_end)
        state = (
            segment.state
            if segment.state in STATE_ORDER
            else INTERNAL_UNKNOWN
        )
        key = (night_end.year, state, segment.key)
        annual[key]["complete"] += 1
        if float(minimum) >= THRESHOLD_C:
            annual[key]["tropical"] += 1

    observations: list[Observation] = []
    for (year, state, metadata_key), info in annual.items():
        observations.append(
            Observation(
                day=date(year, 1, 1),
                metadata_key=metadata_key,
                state=state,
                station_id=station_id_hint,
                values={
                    "complete_nights": float(info["complete"]),
                    "tropical_nights": float(info["tropical"]),
                },
                preliminary=preliminary,
            )
        )

    return observations


class AnnualAccumulator:
    def __init__(self) -> None:
        self.station_years: dict[
            tuple[str, int, str, str],
            dict[str, Any],
        ] = {}
        self.complete_nights = 0
        self.tropical_nights = 0
        self.first_complete_year: int | None = None

    def add(self, observation: Observation) -> None:
        complete = int(round(observation.values["complete_nights"]))
        tropical = int(round(observation.values["tropical_nights"]))
        if complete <= 0:
            return

        key = (
            observation.station_id,
            observation.day.year,
            observation.state,
            observation.metadata_key,
        )
        old = self.station_years.get(key)
        if old is None:
            self.station_years[key] = {
                "complete": complete,
                "tropical": tropical,
                "preliminary": bool(observation.preliminary),
            }
        else:
            old["complete"] = max(int(old["complete"]), complete)
            old["tropical"] = max(int(old["tropical"]), tropical)
            old["preliminary"] = bool(
                old["preliminary"] or observation.preliminary
            )

        self.complete_nights += complete
        self.tropical_nights += tropical
        self.first_complete_year = (
            observation.day.year
            if self.first_complete_year is None
            else min(self.first_complete_year, observation.day.year)
        )

    @staticmethod
    def better(new: list[Any], old: list[Any]) -> bool:
        if int(new[0]) != int(old[0]):
            return int(new[0]) > int(old[0])
        ns = str(new[1]).split(":", 1)[0]
        os = str(old[1]).split(":", 1)[0]
        return ns < os

    def build_records(
        self,
        start_year: int,
        end_year: int,
    ) -> tuple[
        dict[str, dict[str, list[Any] | None]],
        dict[str, int | None],
    ]:
        records = {
            area: {
                str(year): None
                for year in range(start_year, end_year + 1)
            }
            for area in AREAS
        }
        availability = {area: None for area in AREAS}

        for (
            station_id,
            year,
            state,
            metadata_key,
        ), info in self.station_years.items():
            entry = [
                int(info["tropical"]),
                metadata_key,
                1 if info["preliminary"] else 0,
            ]

            target_areas = ["Deutschland"]
            if state in STATE_ORDER:
                target_areas.append(state)

            for area in target_areas:
                if availability[area] is None or year < int(availability[area]):
                    availability[area] = year

                old = records[area][str(year)]
                if old is None or self.better(entry, old):
                    records[area][str(year)] = entry

        return records, availability


def consume(
    accumulator: AnnualAccumulator,
    metadata: MetadataIndex,
    filenames: list[str],
    base_url: str,
    start_date: date,
    end_date: date,
    preliminary: bool,
    max_workers: int,
) -> None:
    for observations in iter_downloaded_observations(
        filenames,
        base_url,
        metadata,
        start_date,
        end_date,
        preliminary,
        max_workers,
        station_pattern=STATION_ID_PATTERN,
        parser=parse_hourly_station_zip,
        failure_tolerance=0.02,
    ):
        for observation in observations:
            accumulator.add(observation)


def referenced_metadata_keys(records: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for years in records.values():
        for entry in years.values():
            if isinstance(entry, list) and len(entry) >= 2:
                keys.add(str(entry[1]))
    return keys


def station_dict(
    metadata: MetadataIndex,
    records: dict[str, Any],
) -> dict[str, Any]:
    public = metadata.public_dict()
    return {
        key: public[key]
        for key in sorted(referenced_metadata_keys(records))
        if key in public
    }


def merge_into_main(payload: dict[str, Any]) -> None:
    main = json.loads(MAIN_JSON.read_text(encoding="utf-8"))
    assert main["areas"] == payload["areas"]

    for area in main["areas"]:
        for year, row in main["records"][area].items():
            row["tropical_nights_max"] = payload["records"][area].get(year)

    main["metrics"]["tropical_nights_max"] = payload["metric"]

    for key, value in payload["stations"].items():
        main["stations"].setdefault(key, value)

    main["tropical_night_start_years"] = payload["area_start_years"]
    main["tropical_night_data_through"] = payload["data_through"]

    stats = dict(main.get("stats", {}))
    stats["tropical_complete_nights_18_06"] = payload["stats"]["complete_nights"]
    stats["tropical_nights_18_06_ge_20c"] = payload["stats"]["tropical_nights"]
    main["stats"] = stats
    main["version"] = max(int(main.get("version", 1)), 4)

    note = str(main.get("method_note") or "")
    add_note = (
        " Tropennächte werden nach DWD-Definition separat aus "
        "stündlichen TT_TU-Daten bestimmt: Minimum der 13 Stundenwerte "
        "von 18 UTC bis einschließlich 06 UTC >=20,0 °C. Nur Nächte "
        "mit allen 13 Stundenwerten werden ausgewertet."
    )
    if "Tropennächte werden nach DWD-Definition separat" not in note:
        main["method_note"] = note.rstrip() + add_note

    MAIN_JSON.write_text(
        json.dumps(
            main,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if not MAIN_JSON.is_file():
        raise SystemExit(f"Fehlt: {MAIN_JSON}")

    main = json.loads(MAIN_JSON.read_text(encoding="utf-8"))
    start_year = int(main["start_year"])
    end_year = int(main["end_year"])

    today = datetime.now(timezone.utc).date()
    current_year = today.year

    print("=== DWD TROPENNÄCHTE NACH OFFIZIELLER DEFINITION ===")
    print("Nachtminimum 18 UTC bis 06 UTC >= 20,0 °C")
    print("QC: nur 13/13 vorhandene Stundenwerte")
    print("Nacht wird dem Datum ihres Endes um 06 UTC zugeordnet.")

    metadata = parse_metadata(download(METADATA_URL, timeout=90))
    historical = list_station_files(
        HISTORICAL_URL,
        HISTORICAL_PATTERN,
        minimum=300,
    )
    recent = list_station_files(
        RECENT_URL,
        RECENT_PATTERN,
        minimum=300,
    )

    print(f"TU historical: {len(historical):,}")
    print(f"TU recent:     {len(recent):,}")

    accumulator = AnnualAccumulator()

    consume(
        accumulator,
        metadata,
        historical,
        HISTORICAL_URL,
        date(1800, 1, 1),
        date(current_year - 1, 12, 31),
        False,
        6,
    )

    print(
        "Nach historical:",
        f"{accumulator.complete_nights:,} vollständige Nächte |",
        f"{accumulator.tropical_nights:,} Tropennächte",
    )

    consume(
        accumulator,
        metadata,
        recent,
        RECENT_URL,
        date(current_year, 1, 1),
        today,
        True,
        8,
    )

    records, availability = accumulator.build_records(
        start_year,
        end_year,
    )
    stations = station_dict(metadata, records)

    payload = {
        "version": 1,
        "generated_at": (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "source": (
            "DWD CDC observations_germany/climate/hourly/"
            "air_temperature · TT_TU"
        ),
        "official_definition": (
            "Minimum der Lufttemperatur von 18 UTC bis 06 UTC >= 20,0 °C"
        ),
        "completeness_rule": (
            "Nur Nächte mit allen 13 Stundenwerten 18,19,...23,00,...06 UTC"
        ),
        "night_year_assignment": (
            "Kalenderdatum des Nachtendes um 06 UTC"
        ),
        "metric": METRIC_META,
        "areas": AREAS,
        "start_year": start_year,
        "end_year": end_year,
        "area_start_years": availability,
        "data_start_year": accumulator.first_complete_year,
        "data_through": today.isoformat(),
        "stations": stations,
        "records": records,
        "stats": {
            "complete_nights": accumulator.complete_nights,
            "tropical_nights": accumulator.tropical_nights,
            "station_year_segments": len(accumulator.station_years),
        },
    }

    assert len(payload["areas"]) == 17
    assert payload["stats"]["complete_nights"] > 100_000
    assert payload["stats"]["tropical_nights"] > 100
    assert payload["data_start_year"] is not None

    OUTPUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )

    merge_into_main(payload)

    print()
    print("DWD-Plausibilitätsreferenzen:")
    print("2003: Kehl 21 Tropennächte")
    print("2015: Waghäusel-Kirrlach 13 Tropennächte")
    for year in ("2003", "2015", str(current_year)):
        print(
            "Baden-Württemberg",
            year,
            "=>",
            records["Baden-Württemberg"].get(year),
        )

    print()
    print("Tropennacht-Datenbasis:", OUTPUT)
    print("Hauptdatei korrigiert:", MAIN_JSON)
    print("Frühestes Jahr mit vollständigen Nachtfenstern:", payload["data_start_year"])
    print(
        "Gesamt:",
        f"{payload['stats']['complete_nights']:,} vollständige Nächte |",
        f"{payload['stats']['tropical_nights']:,} Tropennächte",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
