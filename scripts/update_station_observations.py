#!/usr/bin/env python3
"""Build compact recent DWD hourly station observations for the dashboard.

Version 1:
  - 2 m air temperature (TT_TU)
  - hourly precipitation (R1)
  - dew point (TD)

Sources:
  DWD CDC hourly/recent station observations.

Output:
  station_observations_index.json
  station_observations_current/<station_id>.json

Each station file stores at most the most recent 31 days. The browser then
filters those rows to 3 / 7 / 14 / 30 days.

Only real DWD station measurements are used. No raster/model data.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import shutil
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/hourly"
)

PRODUCTS = {
    "temperature": {
        "path": "air_temperature",
        "prefix": "TU",
        "fields": ("TT_TU", "TT"),
    },
    "precipitation": {
        "path": "precipitation",
        "prefix": "RR",
        "fields": ("R1", "RWS", "RWS_10"),
    },
    "dewpoint": {
        "path": "dew_point",
        "prefix": "TD",
        "fields": ("TD", "TD_TU", "TTD"),
    },
}

INDEX_FILE = "station_observations_index.json"
DATA_DIR = "station_observations_current"
WINDOW_DAYS = 31
MAX_TEMPERATURE_STALENESS_HOURS = 96

UA = "climate-dashboard-station-observations/1.0 (+GitHub Actions)"
TIMEOUT = 90
TRIES = 4

GERMAN_STATES = (
    "Baden-Württemberg",
    "Bayern",
    "Berlin",
    "Brandenburg",
    "Bremen",
    "Hamburg",
    "Hessen",
    "Mecklenburg-Vorpommern",
    "Niedersachsen",
    "Nordrhein-Westfalen",
    "Rheinland-Pfalz",
    "Saarland",
    "Sachsen",
    "Sachsen-Anhalt",
    "Schleswig-Holstein",
    "Thüringen",
)


@dataclass
class StationMeta:
    station_id: str
    name: str
    state: str
    height: float | None
    lat: float | None
    lon: float | None
    start: str | None
    end: str | None


def log(message: str = "") -> None:
    print(message, flush=True)


def request_bytes(url: str, attempts: int = TRIES) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last_error}")


def request_text(url: str) -> str:
    raw = request_bytes(url)
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def recent_dir(product_key: str) -> str:
    product = PRODUCTS[product_key]
    return f"{BASE}/{product['path']}/recent/"


def recent_zip_url(product_key: str, station_id: str) -> str:
    product = PRODUCTS[product_key]
    return (
        recent_dir(product_key)
        + f"stundenwerte_{product['prefix']}_{station_id}_akt.zip"
    )


def metadata_url() -> str:
    return recent_dir("temperature") + "TU_Stundenwerte_Beschreibung_Stationen.txt"


def list_recent_station_ids(product_key: str) -> set[str]:
    product = PRODUCTS[product_key]
    listing = request_text(recent_dir(product_key))
    prefix = re.escape(product["prefix"])
    pattern = rf"stundenwerte_{prefix}_(\d{{5}})_akt\.zip"
    ids = set(re.findall(pattern, listing))
    if not ids:
        raise RuntimeError(
            f"Keine Recent-Dateien für {product_key} im DWD-Verzeichnis gefunden."
        )
    return ids


def parse_station_metadata(text: str) -> dict[str, StationMeta]:
    stations: dict[str, StationMeta] = {}

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        lowered = line.lower()
        if "stations_id" in lowered or "stationsname" in lowered:
            continue
        if set(line.strip()) <= {"-", " "}:
            continue

        parts = line.split(maxsplit=6)
        if len(parts) < 7 or not parts[0].isdigit():
            continue

        station_id = parts[0].zfill(5)
        start = parts[1] if re.fullmatch(r"\d{8}", parts[1]) else None
        end = parts[2] if re.fullmatch(r"\d{8}", parts[2]) else None

        try:
            height = float(parts[3].replace(",", "."))
        except ValueError:
            height = None
        try:
            lat = float(parts[4].replace(",", "."))
        except ValueError:
            lat = None
        try:
            lon = float(parts[5].replace(",", "."))
        except ValueError:
            lon = None

        remainder = parts[6].strip()
        name = remainder
        state = "Unbekannt"

        for candidate in sorted(GERMAN_STATES, key=len, reverse=True):
            if remainder.endswith(" " + candidate):
                name = remainder[: -len(candidate)].strip()
                state = candidate
                break
            if remainder == candidate:
                name = f"Station {station_id}"
                state = candidate
                break

        stations[station_id] = StationMeta(
            station_id=station_id,
            name=name or f"Station {station_id}",
            state=state,
            height=height,
            lat=lat,
            lon=lon,
            start=start,
            end=end,
        )

    if len(stations) < 100:
        raise RuntimeError(
            f"Stationsmetadaten unplausibel: nur {len(stations)} Einträge."
        )
    return stations


def decode_product_text(data: bytes) -> str:
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "MESS_DATUM" in text:
            return text
    return data.decode("latin-1", errors="replace")


def parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%Y%m%d%H", "%Y%m%d%H%M"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def finite_value(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    try:
        value = float(str(raw).replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(value) or value <= -900:
        return None
    return value


def choose_field(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized = {header.strip().upper(): header for header in headers}
    for candidate in candidates:
        found = normalized.get(candidate.upper())
        if found:
            return found
    return None


def parse_recent_zip(
    raw: bytes,
    product_key: str,
    cutoff: datetime,
) -> dict[datetime, float]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".txt")
            and name.split("/")[-1].lower().startswith("produkt_")
        ]
        if not members:
            members = [
                name
                for name in archive.namelist()
                if name.lower().endswith(".txt")
                and "metadaten" not in name.lower()
            ]
        if not members:
            raise RuntimeError("Keine DWD-Produktdatei im ZIP gefunden.")
        text = decode_product_text(archive.read(members[0]))

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    headers = [(field or "").strip() for field in (reader.fieldnames or [])]
    field = choose_field(headers, PRODUCTS[product_key]["fields"])
    if not field:
        raise RuntimeError(
            f"{product_key}: erwartetes Messfeld nicht gefunden. Header={headers}"
        )

    result: dict[datetime, float] = {}
    for raw_row in reader:
        row = {
            (key or "").strip(): (
                value.strip() if isinstance(value, str) else value
            )
            for key, value in raw_row.items()
        }
        dt = parse_datetime(str(row.get("MESS_DATUM") or ""))
        if dt is None or dt < cutoff:
            continue

        value = finite_value(row.get(field))
        if value is None:
            continue

        if product_key == "precipitation" and value < 0:
            continue

        result[dt] = round(value, 2)

    return result


def load_product(
    product_key: str,
    station_id: str,
    cutoff: datetime,
) -> tuple[dict[datetime, float], str | None]:
    try:
        values = parse_recent_zip(
            request_bytes(recent_zip_url(product_key, station_id)),
            product_key,
            cutoff,
        )
        return values, None
    except Exception as exc:
        return {}, str(exc)


def station_payload(
    station_id: str,
    meta: StationMeta,
    available_sets: dict[str, set[str]],
    cutoff: datetime,
    now: datetime,
) -> tuple[str, dict[str, Any] | None, list[str]]:
    warnings: list[str] = []

    temperature, error = load_product(
        "temperature",
        station_id,
        cutoff,
    )
    if error:
        warnings.append(f"{station_id} Temperatur: {error}")

    if not temperature:
        return station_id, None, warnings

    latest_temperature = max(temperature)
    if now - latest_temperature > timedelta(
        hours=MAX_TEMPERATURE_STALENESS_HOURS
    ):
        warnings.append(
            f"{station_id} übersprungen: Temperatur zuletzt "
            f"{latest_temperature.isoformat()}."
        )
        return station_id, None, warnings

    precipitation: dict[datetime, float] = {}
    dewpoint: dict[datetime, float] = {}

    if station_id in available_sets["precipitation"]:
        precipitation, error = load_product(
            "precipitation",
            station_id,
            cutoff,
        )
        if error:
            warnings.append(f"{station_id} Niederschlag: {error}")

    if station_id in available_sets["dewpoint"]:
        dewpoint, error = load_product(
            "dewpoint",
            station_id,
            cutoff,
        )
        if error:
            warnings.append(f"{station_id} Taupunkt: {error}")

    timestamps = sorted(
        set(temperature) | set(precipitation) | set(dewpoint)
    )

    rows = []
    for dt in timestamps:
        rows.append(
            [
                dt.strftime("%Y-%m-%dT%H:%MZ"),
                temperature.get(dt),
                dewpoint.get(dt),
                precipitation.get(dt),
            ]
        )

    available = ["temperature"]
    if dewpoint:
        available.append("dewpoint")
    if precipitation:
        available.append("precipitation")

    latest_by_parameter = {
        "temperature": (
            max(temperature).strftime("%Y-%m-%dT%H:%MZ")
            if temperature
            else None
        ),
        "dewpoint": (
            max(dewpoint).strftime("%Y-%m-%dT%H:%MZ")
            if dewpoint
            else None
        ),
        "precipitation": (
            max(precipitation).strftime("%Y-%m-%dT%H:%MZ")
            if precipitation
            else None
        ),
    }

    payload = {
        "version": 1,
        "station_id": station_id,
        "name": meta.name,
        "state": meta.state,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": WINDOW_DAYS,
        "columns": [
            "time_utc",
            "temperature_c",
            "dewpoint_c",
            "precipitation_mm",
        ],
        "available": available,
        "latest": latest_by_parameter,
        "rows": rows,
    }
    return station_id, payload, warnings


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def build(root: Path, workers: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)

    log("=== DWD STATIONS-MESSWERTE ===")
    log("Parameter: 2-m-Temperatur + Niederschlag + Taupunkt")
    log(f"Fenster: letzte {WINDOW_DAYS} Tage")
    log(f"Worker: {workers}")
    log()

    log("Lese DWD-Recent-Inventare ...")
    available_sets = {
        key: list_recent_station_ids(key)
        for key in PRODUCTS
    }

    for key, ids in available_sets.items():
        log(f"  {key}: {len(ids):,} Recent-Stationen")

    log("Lese DWD-Stationsmetadaten ...")
    metadata = parse_station_metadata(request_text(metadata_url()))

    # Temperature is the anchor network for this first dashboard version.
    candidate_ids = sorted(
        station_id
        for station_id in available_sets["temperature"]
        if station_id in metadata
    )
    log(f"Temperatur-Ankerstationen mit Metadaten: {len(candidate_ids):,}")

    output_dir = root / DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    station_results: dict[str, dict[str, Any]] = {}
    all_warnings: list[str] = []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                station_payload,
                station_id,
                metadata[station_id],
                available_sets,
                cutoff,
                now,
            ): station_id
            for station_id in candidate_ids
        }

        done = 0
        total = len(futures)

        for future in as_completed(futures):
            station_id = futures[future]
            done += 1
            try:
                sid, payload, warnings = future.result()
            except Exception as exc:
                all_warnings.append(f"{station_id}: {exc}")
                payload = None
                sid = station_id
                warnings = []

            all_warnings.extend(warnings)

            if payload is not None:
                station_results[sid] = payload

            if done % 25 == 0 or done == total:
                log(
                    f"  verarbeitet {done:,}/{total:,} | "
                    f"brauchbar {len(station_results):,}"
                )

    if not station_results:
        raise RuntimeError("Keine aktuellen Stations-Messwerte erzeugt.")

    current_ids = set(station_results)

    # Write station files.
    for station_id, payload in station_results.items():
        atomic_write_json(
            output_dir / f"{station_id}.json",
            payload,
        )

    # Remove stale old station files.
    for path in output_dir.glob("*.json"):
        if path.stem not in current_ids:
            path.unlink()

    stations = []
    data_through_values = []

    for station_id, payload in station_results.items():
        meta = metadata[station_id]
        latest = payload["latest"]

        for value in latest.values():
            if value:
                data_through_values.append(value)

        stations.append(
            {
                "id": station_id,
                "name": meta.name,
                "state": meta.state,
                "height": meta.height,
                "lat": meta.lat,
                "lon": meta.lon,
                "available": payload["available"],
                "latest": latest,
                "file": f"{DATA_DIR}/{station_id}.json",
            }
        )

    stations.sort(
        key=lambda station: (
            station["state"],
            station["name"].casefold(),
            station["id"],
        )
    )

    states = sorted(
        {
            station["state"]
            for station in stations
            if station["state"] != "Unbekannt"
        },
        key=str.casefold,
    )

    index = {
        "version": 1,
        "ready": True,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_through": (
            max(data_through_values) if data_through_values else None
        ),
        "window_days": WINDOW_DAYS,
        "parameters": [
            {
                "id": "temperature",
                "label": "Temperatur 2 m",
                "unit": "°C",
                "source_field": "TT_TU",
                "chart": "line",
            },
            {
                "id": "precipitation",
                "label": "Niederschlag",
                "unit": "mm",
                "source_field": "R1",
                "chart": "bar",
            },
            {
                "id": "dewpoint",
                "label": "Taupunkt",
                "unit": "°C",
                "source_field": "TD",
                "chart": "line",
            },
        ],
        "periods": [3, 7, 14, 30],
        "states": states,
        "station_count": len(stations),
        "stations": stations,
        "source_note": (
            "DWD Climate Data Center (CDC), stündliche Stationsmessungen aus "
            "air_temperature/recent (TT_TU), precipitation/recent (R1) und "
            "dew_point/recent (TD). Recent-Werte sind noch nicht abschließend "
            "qualitätsgeprüft."
        ),
    }

    atomic_write_json(root / INDEX_FILE, index)

    log()
    log("=" * 88)
    log("FERTIG")
    log("=" * 88)
    log(f"Stationen: {len(stations):,}")
    log(f"Bundesländer: {len(states)}")
    log(f"Datenstand: {index['data_through']}")
    log(f"Stationsdateien: {DATA_DIR}/")
    log(f"Index: {INDEX_FILE}")

    if all_warnings:
        log()
        log(f"Hinweise/Einzelfehler: {len(all_warnings):,}")
        for warning in all_warnings[:40]:
            log(f"  - {warning}")
        if len(all_warnings) > 40:
            log(f"  ... weitere {len(all_warnings)-40:,} Hinweise ausgeblendet")

    return {
        "station_count": len(stations),
        "data_through": index["data_through"],
        "warnings": len(all_warnings),
    }


def self_test() -> None:
    # Metadata parser.
    lines = [
        "Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge Stationsname Bundesland",
        "01420 19490101 20261231 100 50.0259 8.5213 Frankfurt/Main Hessen",
        "04336 19360101 20261231 320 49.2140 7.1070 Saarbrücken-Ensheim Saarland",
    ]
    # Pad the synthetic metadata to satisfy the plausibility guard.
    for i in range(100):
        lines.append(
            f"{50000+i:05d} 20000101 20261231 100 50.0 8.0 Test {i} Hessen"
        )
    meta = parse_station_metadata("\n".join(lines))
    assert meta["01420"].name == "Frankfurt/Main"
    assert meta["01420"].state == "Hessen"
    assert meta["04336"].state == "Saarland"

    # ZIP/product parser.
    def make_zip(header: str, rows: list[str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "produkt_test_stunde_20260810_20260811_01420.txt",
                header + "\n" + "\n".join(rows) + "\n",
            )
        return buf.getvalue()

    cutoff = datetime(2026, 8, 9, tzinfo=timezone.utc)

    tu = make_zip(
        "STATIONS_ID;MESS_DATUM;QN_9;TT_TU;RF_TU;eor",
        [
            "1420;2026081000;10;21.4;65;eor",
            "1420;2026081001;10;-999;66;eor",
            "1420;2026081002;10;22.6;63;eor",
        ],
    )
    rr = make_zip(
        "STATIONS_ID;MESS_DATUM;QN_8;R1;RS_IND;WRTR;eor",
        [
            "1420;2026081000;10;0.0;0;0;eor",
            "1420;2026081001;10;1.7;1;1;eor",
        ],
    )
    td = make_zip(
        "STATIONS_ID;MESS_DATUM;QN_8;TT;TD;eor",
        [
            "1420;2026081000;10;21.4;14.5;eor",
            "1420;2026081001;10;21.8;15.0;eor",
        ],
    )

    tu_values = parse_recent_zip(tu, "temperature", cutoff)
    rr_values = parse_recent_zip(rr, "precipitation", cutoff)
    td_values = parse_recent_zip(td, "dewpoint", cutoff)

    assert len(tu_values) == 2
    assert max(tu_values.values()) == 22.6
    assert sum(rr_values.values()) == 1.7
    assert max(td_values.values()) == 15.0

    print("update_station_observations.py self-test OK")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel DWD downloads (default: 8)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    root = Path(args.root).resolve()
    result = build(root, workers=max(1, args.workers))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
