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
START_YEAR = 1861
LIST_MIN_YEAR = 1881
MIN_GUST_KMH = 75.0
AREAS = ["Deutschland", *STATE_ORDER]

METRICS = {
    "fgx_ge_400": {
        "label": "FGx ≥400 m",
        "description": (
            "Stärkste tägliche Windspitze des Jahres an Stationen "
            "ab 400 m, sofern mindestens 75 km/h"
        ),
        "unit": "km/h",
        "direction": "desc",
        "source": "DWD daily/kl · FX",
        "height_rule": "Stationshöhe >= 400 m",
        "minimum": "75 km/h (9 Bft.)",
    },
    "fgx_lt_400": {
        "label": "FGx <400 m",
        "description": (
            "Stärkste tägliche Windspitze des Jahres an Stationen "
            "unter 400 m, sofern mindestens 75 km/h"
        ),
        "unit": "km/h",
        "direction": "desc",
        "source": "DWD daily/kl · FX",
        "height_rule": "Stationshöhe < 400 m",
        "minimum": "75 km/h (9 Bft.)",
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


def parse_wind_station_zip(
    content: bytes,
    station_id_hint: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> list[Observation]:
    """Liest FX/FXK aus dem täglichen KL-Produkt."""
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

            columns = {
                part.strip().upper()
                for part in first_line.split(";")
            }
            if (
                "STATIONS_ID" in columns
                and "MESS_DATUM" in columns
                and ("FX" in columns or "FXK" in columns)
            ):
                product_files.append(name)

        if not product_files:
            return []

        product_name = product_files[0]
        text = decode_product(archive.read(product_name))
        reader = csv.DictReader(io.StringIO(text), delimiter=";")

        fields = [
            (field or "").strip()
            for field in (reader.fieldnames or [])
        ]
        lookup = {field.upper(): field for field in fields}

        station_field = lookup.get("STATIONS_ID")
        date_field = lookup.get("MESS_DATUM")
        fx_field = lookup.get("FX") or lookup.get("FXK")

        if not station_field or not date_field or not fx_field:
            return []

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
            try:
                day = datetime.strptime(stamp, "%Y%m%d").date()
            except ValueError:
                continue

            if day < start_date or day > end_date:
                continue

            fx_ms = parse_float(row.get(fx_field))
            if fx_ms is None:
                continue

            # DWD FX ist m/s. Fehlwerte sind negativ; zusätzlich nur
            # physikalisch plausible Spitzen bis 120 m/s zulassen.
            if not (0.0 <= fx_ms <= 120.0):
                continue

            fx_kmh = fx_ms * 3.6
            if fx_kmh < MIN_GUST_KMH:
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
                    values={
                        "fx_kmh": round(fx_kmh, 1),
                        "fx_ms": round(fx_ms, 1),
                    },
                    preliminary=preliminary,
                )
            )

    return observations


def entry_for(observation: Observation) -> list[Any]:
    return [
        round(float(observation.values["fx_kmh"]), 1),
        observation.day.isoformat(),
        observation.metadata_key,
        1 if observation.preliminary else 0,
        round(float(observation.values["fx_ms"]), 1),
    ]


def better(new: list[Any], old: list[Any]) -> bool:
    nv = float(new[0])
    ov = float(old[0])

    if nv != ov:
        return nv > ov

    nd = str(new[1])
    od = str(old[1])
    if nd != od:
        return nd < od

    ns = str(new[2]).split(":", 1)[0]
    os = str(old[2]).split(":", 1)[0]
    return ns < os


class WindAccumulator:
    def __init__(self) -> None:
        self.records: dict[
            str,
            dict[int, dict[str, list[Any]]],
        ] = defaultdict(lambda: defaultdict(dict))

        self.observation_count = 0
        self.first_day: date | None = None
        self.last_day: date | None = None

    @staticmethod
    def areas_for(state: str) -> list[str]:
        areas = ["Deutschland"]
        if state in STATE_ORDER:
            areas.append(state)
        return areas

    def add(
        self,
        observation: Observation,
        height: int | None,
    ) -> None:
        if height is None:
            return

        year = observation.day.year
        if year < START_YEAR:
            return

        metric = (
            "fgx_ge_400"
            if height >= 400
            else "fgx_lt_400"
        )
        entry = entry_for(observation)

        for area in self.areas_for(observation.state):
            bucket = self.records[area][year]
            old = bucket.get(metric)
            if old is None or better(entry, old):
                bucket[metric] = entry

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

    def public_records(self, end_year: int) -> dict[str, Any]:
        result: dict[str, Any] = {}

        for area in AREAS:
            years: dict[str, Any] = {}
            for year in range(START_YEAR, end_year + 1):
                raw = self.records.get(area, {}).get(year, {})
                years[str(year)] = {
                    "fgx_ge_400": raw.get("fgx_ge_400"),
                    "fgx_lt_400": raw.get("fgx_lt_400"),
                }
            result[area] = years

        return result


def consume(
    accumulator: WindAccumulator,
    metadata: MetadataIndex,
    filenames: list[str],
    base_url: str,
    start_date: date,
    end_date: date,
    preliminary: bool,
    max_workers: int,
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
        parser=parse_wind_station_zip,
        failure_tolerance=0.02,
    ):
        for observation in observations:
            segment = metadata.segment_for(
                observation.station_id,
                observation.day,
            )
            accumulator.add(observation, segment.height)

    return accumulator.observation_count - before


def referenced_metadata_keys(
    records: dict[str, Any],
) -> set[str]:
    keys: set[str] = set()

    for years in records.values():
        for row in years.values():
            for entry in row.values():
                if (
                    isinstance(entry, list)
                    and len(entry) >= 3
                    and isinstance(entry[2], str)
                    and ":" in entry[2]
                ):
                    keys.add(entry[2])

    return keys


def station_dict(
    metadata: MetadataIndex,
    records: dict[str, Any],
) -> dict[str, Any]:
    keys = referenced_metadata_keys(records)
    public = metadata.public_dict()
    return {
        key: public[key]
        for key in sorted(keys)
        if key in public
    }


def load_area_start_years() -> dict[str, int]:
    path = Path("data/dwd_annual_extremes.json")
    if not path.is_file():
        raise RuntimeError(
            "data/dwd_annual_extremes.json fehlt. "
            "Bitte zuerst Stufe 1 bauen."
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    starts = data.get("area_start_years")
    if not isinstance(starts, dict) or len(starts) != 17:
        raise RuntimeError(
            "Regionale Startjahre fehlen in "
            "data/dwd_annual_extremes.json."
        )

    return {
        str(area): int(year)
        for area, year in starts.items()
    }


def excel_bw_reference(
    records: dict[str, Any],
) -> None:
    expected = {
        2003: {
            "fgx_ge_400": 194,
            "fgx_lt_400": 113,
        },
        2015: {
            "fgx_ge_400": 157,
            "fgx_lt_400": 118,
        },
        2024: {
            "fgx_ge_400": 153,
            "fgx_lt_400": 108,
        },
    }

    print("=== Baden-Württemberg · Wind DWD vs. Excel ===")
    bw = records["Baden-Württemberg"]

    for year, metrics in expected.items():
        print(f"{year}:")
        for metric, excel_value in metrics.items():
            entry = bw[str(year)][metric]
            dwd_value = entry[0] if entry else None
            print(
                f"  {metric:16s} "
                f"DWD={dwd_value!s:>7} km/h | "
                f"Excel={excel_value:>3} km/h"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="data/dwd_annual_wind_extremes.json",
    )
    parser.add_argument("--max-workers", type=int, default=10)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).date()
    start_date = date(START_YEAR, 1, 1)

    print("=== DWD JÄHRLICHE EXTREMWERTE · WIND STUFE 2 ===")
    print("Quelle: DWD daily/kl · FX")
    print("FX = Tagesmaximum der Windspitze")
    print("Einheit Quelle: m/s | Ausgabe: km/h")
    print("Mindestwert: 75 km/h (9 Bft.)")
    print("Höhenklassen: >=400 m und <400 m")
    print("Gebiete: Deutschland + 16 Bundesländer")

    area_start_years = load_area_start_years()
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

    print(f"KL historical: {len(historical):,}")
    print(f"KL recent:     {len(recent):,}")

    acc = WindAccumulator()

    n = consume(
        acc,
        metadata,
        historical,
        HISTORICAL_URL,
        start_date,
        today,
        False,
        args.max_workers,
    )
    print(f"Historical gültige FGx-Werte >=75 km/h: {n:,}")

    n = consume(
        acc,
        metadata,
        recent,
        RECENT_URL,
        date(today.year - 2, 1, 1),
        today,
        True,
        args.max_workers,
    )
    print(f"Recent gültige FGx-Werte >=75 km/h: {n:,}")

    records = acc.public_records(today.year)
    stations = station_dict(metadata, records)

    payload = {
        "version": VERSION,
        "generated_at": (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "project": "Jährliche Extremwerte · Wind",
        "source": "DWD CDC observations_germany/climate/daily/kl · FX",
        "source_parameter": {
            "column": "FX",
            "description": "Tagesmaximum Windspitze",
            "source_unit": "m/s",
            "output_unit": "km/h",
            "conversion": "km/h = m/s × 3.6",
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
        "entry_schema": [
            "value_kmh",
            "date",
            "metadata_key",
            "preliminary",
            "raw_value_ms",
        ],
        "stations": stations,
        "records": records,
        "stats": {
            "valid_gust_observations_ge_75_kmh": (
                acc.observation_count
            ),
        },
        "method_note": (
            "Für jedes Kalenderjahr wird aus DWD daily/kl, Spalte FX, "
            "das stärkste Tagesmaximum der Windspitze bestimmt. "
            "FX wird vom DWD in m/s bereitgestellt und mit Faktor 3,6 "
            "in km/h umgerechnet. Entsprechend der Excel-Vorlage werden "
            "nur Werte ab 75 km/h (9 Bft.) berücksichtigt. Die Stationen "
            "werden anhand ihrer DWD-Stationshöhe in >=400 m und <400 m "
            "aufgeteilt. Die regionalen Listen-Startjahre werden aus der "
            "bereits geprüften Stufe-1-Datenbasis übernommen."
        ),
    }

    assert len(payload["areas"]) == 17
    assert set(payload["metrics"]) == {
        "fgx_ge_400",
        "fgx_lt_400",
    }
    assert payload["data_start"] is not None
    assert payload["data_through"] is not None
    assert acc.observation_count > 100_000

    # Neuere Kontrolljahre müssen in BW Werte in beiden Höhenklassen haben.
    for year in ("2003", "2015", "2024"):
        for metric in ("fgx_ge_400", "fgx_lt_400"):
            assert (
                records["Baden-Württemberg"][year][metric]
                is not None
            ), f"BW {year} ohne {metric}"

    output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )

    excel_bw_reference(records)

    print("Wind-Datenbasis erfolgreich gebaut.")
    print(
        f"Datenzeitraum: {payload['data_start']} "
        f"bis {payload['data_through']}"
    )
    print(
        "Gültige Windspitzen >=75 km/h:",
        f"{acc.observation_count:,}",
    )
    print(
        f"Ausgabe: {output} "
        f"({output.stat().st_size / 1024 / 1024:.1f} MB)"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
