#!/usr/bin/env python3
"""Build compact near-real-time DWD 10-minute station data (v13.2.1).

Primary station network:
- DWD CDC 10-minute air_temperature/now

Additional parameters are joined by the same DWD station ID where available:
- wind/now: FF_10, DD_10
- extreme_wind/now: FX_10, DX_10
- precipitation/now: RWS_10, RWS_DAU_10, RWS_IND_10

The script is designed for the force-replaced ``live-data`` branch. It checks
all four DWD now-directory listings every run. If none of the listings (or the
station metadata) changed, no new snapshot is published.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import threading
import time

TEMP_BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/now/"
WIND_BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/wind/now/"
GUST_BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/extreme_wind/now/"
PRECIP_BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/precipitation/now/"
META_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/historical/zehn_min_tu_Beschreibung_Stationen.txt"

BERLIN = ZoneInfo("Europe/Berlin")
USER_AGENT = "climate-dashboard-current/13.2.1 (+GitHub Actions; DWD Open Data)"
GERMAN_STATES = sorted([
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg",
    "Hessen", "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen",
    "Rheinland-Pfalz", "Saarland", "Sachsen", "Sachsen-Anhalt",
    "Schleswig-Holstein", "Thüringen",
], key=len, reverse=True)

LIVE_SCHEMA_VERSION = 3
AUX_SEMAPHORE = threading.Semaphore(4)

SOURCE_CONFIG = {
    "temperature": {
        "base": TEMP_BASE,
        "pattern": re.compile(r"10minutenwerte_TU_(\d{5})_now\.zip"),
        "filename": "10minutenwerte_TU_{id}_now.zip",
        "fields": {
            "temp": "TT_10",
            "humidity": "RF_10",
            "dewpoint": "TD_10",
            "pressure": "PP_10",
            "ground_temp": "TM5_10",
        },
    },
    "wind": {
        "base": WIND_BASE,
        "pattern": re.compile(r"10minutenwerte_wind_(\d{5})_now\.zip"),
        "filename": "10minutenwerte_wind_{id}_now.zip",
        "fields": {"wind_speed": "FF_10", "wind_direction": "DD_10"},
    },
    "gust": {
        "base": GUST_BASE,
        "pattern": re.compile(r"10minutenwerte_extrema_wind_(\d{5})_now\.zip"),
        "filename": "10minutenwerte_extrema_wind_{id}_now.zip",
        "fields": {"gust_speed": "FX_10", "gust_direction": "DX_10"},
    },
    "precipitation": {
        "base": PRECIP_BASE,
        "pattern": re.compile(r"10minutenwerte_nieder_(\d{5})_now\.zip"),
        "filename": "10minutenwerte_nieder_{id}_now.zip",
        "fields": {
            "precip_10min": "RWS_10",
            "precip_duration": "RWS_DAU_10",
            "precip_indicator": "RWS_IND_10",
        },
    },
}


def request_bytes(url: str, timeout: int = 35, attempts: int = 5) -> bytes:
    """HTTP GET with short retries. DWD occasionally throttles many small ZIP requests."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if response.status_code in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(f"HTTP {response.status_code} for {url}", response=response)
            response.raise_for_status()
            return response.content
        except (requests.RequestException, OSError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(min(8.0, 0.8 * (2 ** (attempt - 1))))
    raise RuntimeError(f"DWD-Abruf fehlgeschlagen nach {attempts} Versuchen: {last_error}")


def request_text(url: str, timeout: int = 35) -> str:
    raw = request_bytes(url, timeout)
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1", errors="replace")


def parse_station_metadata(text: str) -> dict[str, dict[str, Any]]:
    stations: dict[str, dict[str, Any]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("stations_id") or set(line) <= {"-", " "}:
            continue
        parts = line.split(maxsplit=6)
        if len(parts) < 7 or not parts[0].isdigit():
            continue
        station_id = parts[0].zfill(5)
        try:
            elevation = float(parts[3].replace(",", "."))
            lat = float(parts[4].replace(",", "."))
            lon = float(parts[5].replace(",", "."))
        except ValueError:
            continue
        remainder = parts[6].strip()
        state = ""
        name = remainder
        for candidate in GERMAN_STATES:
            if remainder == candidate or remainder.endswith(" " + candidate):
                state = candidate
                name = remainder[: -len(candidate)].strip()
                break
        stations[station_id] = {
            "id": station_id,
            "name": name or f"Station {station_id}",
            "state": state,
            "elevation_m": elevation,
            "lat": lat,
            "lon": lon,
            "from": parts[1],
            "to": parts[2],
        }
    return stations


def as_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if number <= -900:
        return None
    return round(number, 3)


def parse_product_zip(raw: bytes, fields: dict[str, str]) -> list[dict[str, Any]]:
    """Parse one DWD 10-minute product ZIP using a logical->CSV field map."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [
            name for name in archive.namelist()
            if Path(name).name.lower().startswith("produkt_") and name.lower().endswith(".txt")
        ]
        if not names:
            names = [
                name for name in archive.namelist()
                if name.lower().endswith(".txt") and "metadaten" not in name.lower()
            ]
        if not names:
            raise RuntimeError("Keine Produktdatei im DWD-ZIP gefunden")
        data = archive.read(names[0])

    text = data.decode("utf-8", errors="replace")
    if "MESS_DATUM" not in text:
        text = data.decode("cp1252", errors="replace")

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        row = {
            (key or "").strip(): (value.strip() if isinstance(value, str) else value)
            for key, value in raw_row.items()
        }
        stamp = row.get("MESS_DATUM")
        if not stamp:
            continue
        try:
            dt = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        item: dict[str, Any] = {"dt": dt, "quality": row.get("QN") or row.get("QN_9") or None}
        for logical_name, csv_name in fields.items():
            item[logical_name] = as_number(row.get(csv_name))
        rows.append(item)
    rows.sort(key=lambda item: item["dt"])
    return rows


def average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def latest_with_value(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any] | None:
    for row in reversed(rows):
        if any(row.get(key) is not None for key in keys):
            return row
    return rows[-1] if rows else None


def iso_local(row: dict[str, Any] | None) -> str | None:
    return row["dt"].astimezone(BERLIN).isoformat(timespec="minutes") if row else None


def iso_utc(row: dict[str, Any] | None) -> str | None:
    return row["dt"].isoformat(timespec="minutes").replace("+00:00", "Z") if row else None


def source_file_sets(listings: dict[str, str]) -> dict[str, set[str]]:
    sets: dict[str, set[str]] = {}
    for source, config in SOURCE_CONFIG.items():
        sets[source] = set(config["pattern"].findall(listings[source]))
    return sets


def fetch_source_rows(source: str, station_id: str, available: set[str], cutoff: datetime) -> list[dict[str, Any]]:
    if station_id not in available:
        return []
    config = SOURCE_CONFIG[source]
    filename = config["filename"].format(id=station_id)

    # Temperature is the primary source. Auxiliary products are deliberately
    # throttled because the DWD serves hundreds of very small ZIP files and can
    # temporarily reject a burst of parallel requests.
    if source == "temperature":
        raw = request_bytes(config["base"] + filename)
    else:
        with AUX_SEMAPHORE:
            raw = request_bytes(config["base"] + filename)
    rows = parse_product_zip(raw, config["fields"])
    return [row for row in rows if row["dt"] >= cutoff]


def build_station_profile(
    station_id: str,
    metadata: dict[str, dict[str, Any]],
    available_files: dict[str, set[str]],
    now_utc: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    temp_cutoff = now_utc - timedelta(hours=30)
    # Auxiliary DWD now products do not always arrive at the same time as TU.
    # Keep a wider safety window, while the frontend still plots only 24 h.
    aux_cutoff = now_utc - timedelta(hours=72)
    source_rows: dict[str, list[dict[str, Any]]] = {}
    source_errors: dict[str, str] = {}

    # Temperature is the primary network and must be readable.
    source_rows["temperature"] = fetch_source_rows("temperature", station_id, available_files["temperature"], temp_cutoff)
    if not source_rows["temperature"]:
        raise RuntimeError("keine Temperatur-Messwerte in den letzten 30 Stunden")

    # Auxiliary sources are optional per station. A single failed source must not
    # hide an otherwise valid temperature station from the live dashboard.
    for source in ("wind", "gust", "precipitation"):
        if station_id not in available_files[source]:
            source_rows[source] = []
            continue
        try:
            source_rows[source] = fetch_source_rows(source, station_id, available_files[source], aux_cutoff)
        except Exception as exc:
            source_rows[source] = []
            source_errors[source] = str(exc)[:180]

    temp_latest = latest_with_value(source_rows["temperature"], ("temp", "humidity", "dewpoint", "pressure", "ground_temp"))
    wind_latest = latest_with_value(source_rows["wind"], ("wind_speed", "wind_direction"))
    gust_latest = latest_with_value(source_rows["gust"], ("gust_speed", "gust_direction"))
    precip_latest = latest_with_value(source_rows["precipitation"], ("precip_10min", "precip_duration", "precip_indicator"))

    all_latest = [row for row in (temp_latest, wind_latest, gust_latest, precip_latest) if row]
    overall_latest = max(all_latest, key=lambda item: item["dt"]) if all_latest else temp_latest

    today_local = now_utc.astimezone(BERLIN).date()
    today_temp = [row for row in source_rows["temperature"] if row["dt"].astimezone(BERLIN).date() == today_local]
    today_wind = [row for row in source_rows["wind"] if row["dt"].astimezone(BERLIN).date() == today_local]
    today_gust = [row for row in source_rows["gust"] if row["dt"].astimezone(BERLIN).date() == today_local]
    today_precip = [row for row in source_rows["precipitation"] if row["dt"].astimezone(BERLIN).date() == today_local]

    today_temps = [float(row["temp"]) for row in today_temp if row.get("temp") is not None]
    today_winds = [float(row["wind_speed"]) for row in today_wind if row.get("wind_speed") is not None]
    today_gusts = [float(row["gust_speed"]) for row in today_gust if row.get("gust_speed") is not None]
    today_precip_values = [max(0.0, float(row["precip_10min"])) for row in today_precip if row.get("precip_10min") is not None]

    meta = metadata.get(station_id, {
        "id": station_id, "name": f"Station {station_id}", "state": "",
        "elevation_m": None, "lat": None, "lon": None, "from": "", "to": "",
    })

    # Merge all source rows on their UTC timestamps. This keeps the JSON compact
    # while allowing charts/tables to show asynchronously arriving DWD products.
    merged: dict[datetime, dict[str, Any]] = {}
    for source, rows in source_rows.items():
        for row in rows:
            item = merged.setdefault(row["dt"], {})
            for key, value in row.items():
                if key not in {"dt", "quality"}:
                    item[key] = value

    series = []
    for dt in sorted(merged):
        item = merged[dt]
        series.append([
            dt.astimezone(BERLIN).isoformat(timespec="minutes"),
            item.get("temp"), item.get("humidity"), item.get("dewpoint"), item.get("pressure"), item.get("ground_temp"),
            item.get("wind_speed"), item.get("wind_direction"), item.get("gust_speed"), item.get("gust_direction"),
            item.get("precip_10min"), item.get("precip_duration"), item.get("precip_indicator"),
        ])

    latest = {
        "local": iso_local(overall_latest),
        "utc": iso_utc(overall_latest),
        "temperature_local": iso_local(temp_latest),
        "temperature_utc": iso_utc(temp_latest),
        "temperature_c": temp_latest.get("temp") if temp_latest else None,
        "humidity_pct": temp_latest.get("humidity") if temp_latest else None,
        "dewpoint_c": temp_latest.get("dewpoint") if temp_latest else None,
        "pressure_hpa": temp_latest.get("pressure") if temp_latest else None,
        "ground_temp_c": temp_latest.get("ground_temp") if temp_latest else None,
        "wind_local": iso_local(wind_latest),
        "wind_utc": iso_utc(wind_latest),
        "wind_speed_ms": wind_latest.get("wind_speed") if wind_latest else None,
        "wind_direction_deg": wind_latest.get("wind_direction") if wind_latest else None,
        "gust_local": iso_local(gust_latest),
        "gust_utc": iso_utc(gust_latest),
        "gust_speed_ms": gust_latest.get("gust_speed") if gust_latest else None,
        "gust_direction_deg": gust_latest.get("gust_direction") if gust_latest else None,
        "precipitation_local": iso_local(precip_latest),
        "precipitation_utc": iso_utc(precip_latest),
        "precip_10min_mm": precip_latest.get("precip_10min") if precip_latest else None,
        "precip_duration_min": precip_latest.get("precip_duration") if precip_latest else None,
        "precip_indicator": precip_latest.get("precip_indicator") if precip_latest else None,
        "quality_temperature": temp_latest.get("quality") if temp_latest else None,
        "quality_wind": wind_latest.get("quality") if wind_latest else None,
        "quality_gust": gust_latest.get("quality") if gust_latest else None,
        "quality_precipitation": precip_latest.get("quality") if precip_latest else None,
    }

    today = {
        "date": today_local.isoformat(),
        "min_c": round(min(today_temps), 2) if today_temps else None,
        "max_c": round(max(today_temps), 2) if today_temps else None,
        "mean_10min_c": average(today_temps),
        "temperature_count": len(today_temps),
        "mean_wind_ms": average(today_winds),
        "max_wind_ms": round(max(today_winds), 2) if today_winds else None,
        "max_gust_ms": round(max(today_gusts), 2) if today_gusts else None,
        "precip_sum_mm": round(sum(today_precip_values), 2) if today_precip_values else None,
        "precip_count": len(today_precip_values),
        "wet_intervals": sum(1 for value in today_precip_values if value > 0),
    }

    availability = {
        "temperature": bool(source_rows["temperature"]),
        "wind": bool(source_rows["wind"]),
        "gust": bool(source_rows["gust"]),
        "precipitation": bool(source_rows["precipitation"]),
    }

    summary = {
        **meta,
        "latest_local": latest["local"],
        "latest_utc": latest["utc"],
        "temperature_c": latest["temperature_c"],
        "humidity_pct": latest["humidity_pct"],
        "dewpoint_c": latest["dewpoint_c"],
        "pressure_hpa": latest["pressure_hpa"],
        "ground_temp_c": latest["ground_temp_c"],
        "wind_speed_ms": latest["wind_speed_ms"],
        "wind_direction_deg": latest["wind_direction_deg"],
        "gust_speed_ms": latest["gust_speed_ms"],
        "precip_10min_mm": latest["precip_10min_mm"],
        "today_min_c": today["min_c"],
        "today_max_c": today["max_c"],
        "today_mean_10min_c": today["mean_10min_c"],
        "today_max_gust_ms": today["max_gust_ms"],
        "today_precip_sum_mm": today["precip_sum_mm"],
        "availability": availability,
        "profile": f"stations/{station_id}.json",
    }

    profile = {
        "schema_version": LIVE_SCHEMA_VERSION,
        "station": meta,
        "availability": availability,
        "source_errors": source_errors,
        "latest": latest,
        "today": today,
        "series_columns": [
            "time_local", "temperature_c", "humidity_pct", "dewpoint_c", "pressure_hpa", "ground_temp_c",
            "wind_speed_ms", "wind_direction_deg", "gust_speed_ms", "gust_direction_deg",
            "precip_10min_mm", "precip_duration_min", "precip_indicator",
        ],
        "series": series,
    }
    return summary, profile


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)


def set_output(name: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="live_output")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    now_utc = datetime.now(timezone.utc)

    print("Prüfe DWD-now-Verzeichnisse: Temperatur, Wind, Böen, Niederschlag …")
    listings = {source: request_text(config["base"]) for source, config in SOURCE_CONFIG.items()}
    metadata_text = request_text(META_URL)
    available_files = source_file_sets(listings)

    if not available_files["temperature"]:
        raise RuntimeError("Im DWD-now-Verzeichnis wurden keine TU-Stationsdateien gefunden")

    # The HTML directory listings contain filename, modification time and size.
    # Hashing all four listings makes asynchronous DWD product updates visible.
    source_hash_payload = "\n---SOURCE---\n".join(
        [f"{source}\n{listings[source]}" for source in sorted(listings)] + [f"metadata\n{metadata_text}"]
    )
    source_hash = hashlib.sha256(source_hash_payload.encode("utf-8", errors="replace")).hexdigest()

    state_path = output / "state.json"
    old_state: dict[str, Any] = {}
    if state_path.exists():
        try:
            old_state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            old_state = {}

    state_is_current = old_state.get("schema_version") == LIVE_SCHEMA_VERSION
    if not args.force and state_is_current and old_state.get("source_hash") == source_hash and (output / "current_index.json").exists():
        print("Alle DWD-now-Bestände unverändert – kein neuer Live-Datensatz nötig.")
        set_output("changed", "false")
        return 0
    if not state_is_current:
        print(f"Live-Schema wird auf Version {LIVE_SCHEMA_VERSION} aktualisiert – erzwinge einmaligen Neuaufbau.")

    metadata = parse_station_metadata(metadata_text)
    temp_station_ids = sorted(available_files["temperature"])
    print(
        "DWD-now-Bestand geändert: "
        f"{len(temp_station_ids)} Temperaturstationen; passende Zusatzquellen: "
        f"Wind {len(available_files['wind'] & available_files['temperature'])}, "
        f"Böen {len(available_files['gust'] & available_files['temperature'])}, "
        f"Niederschlag {len(available_files['precipitation'] & available_files['temperature'])}."
    )

    stations: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    profiles: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(build_station_profile, station_id, metadata, available_files, now_utc): station_id
            for station_id in temp_station_ids
        }
        completed = 0
        for future in as_completed(futures):
            station_id = futures[future]
            completed += 1
            try:
                summary, profile = future.result()
                stations.append(summary)
                profiles[station_id] = profile
            except Exception as exc:
                failures.append({"id": station_id, "error": str(exc)[:220]})
            if completed % 50 == 0 or completed == len(futures):
                print(f"  {completed}/{len(futures)} Temperaturstationen verarbeitet")

    if len(stations) < max(20, int(len(temp_station_ids) * 0.5)):
        raise RuntimeError(f"Zu wenige Stationen erfolgreich verarbeitet: {len(stations)} von {len(temp_station_ids)}")

    stations.sort(key=lambda item: (item.get("state") or "", item.get("name") or "", item["id"]))
    latest_times = [item["latest_utc"] for item in stations if item.get("latest_utc")]
    latest_source = max(latest_times) if latest_times else None

    stations_dir = output / "stations"
    stations_dir.mkdir(parents=True, exist_ok=True)
    valid_paths = {f"{station_id}.json" for station_id in profiles}
    for old_file in stations_dir.glob("*.json"):
        if old_file.name not in valid_paths:
            old_file.unlink()
    for station_id, profile in profiles.items():
        write_json(stations_dir / f"{station_id}.json", profile)

    availability_counts = {
        source: sum(1 for station in stations if station.get("availability", {}).get(source))
        for source in ("temperature", "wind", "gust", "precipitation")
    }

    # Diagnostic summary is intentionally printed into the Actions log. It makes
    # it obvious whether a source is missing from the DWD listing or failed while
    # downloading/parsing.
    source_error_counts = {source: 0 for source in ("wind", "gust", "precipitation")}
    source_error_samples: dict[str, list[str]] = {source: [] for source in source_error_counts}
    for profile in profiles.values():
        for source, message in (profile.get("source_errors") or {}).items():
            if source in source_error_counts:
                source_error_counts[source] += 1
                if len(source_error_samples[source]) < 3:
                    source_error_samples[source].append(message)
    print("Erfolgreich mit Zusatzdaten:", availability_counts)
    print("Fehler je Zusatzquelle:", source_error_counts)
    for source, samples in source_error_samples.items():
        if samples:
            print(f"  {source} – Beispiel(e): " + " | ".join(samples))

    index = {
        "schema_version": LIVE_SCHEMA_VERSION,
        "generated_at_utc": now_utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "latest_measurement_utc": latest_source,
        "station_count": len(stations),
        "failed_station_count": len(failures),
        "availability_counts": availability_counts,
        "source_error_counts": source_error_counts,
        "source": "DWD CDC 10-minute now: air_temperature + wind + extreme_wind + precipitation",
        "source_note": "10-Minuten-Messwerte; DWD-now-Produkte werden in Abständen unter einer Stunde aktualisiert; aktuelle Werte sind vorläufig. Zusatzparameter werden über dieselbe Stations-ID verknüpft und können zeitversetzt zum Temperaturprodukt eintreffen.",
        "stations": stations,
        "failures": failures[:50],
    }
    write_json(output / "current_index.json", index)
    write_json(state_path, {
        "source_hash": source_hash,
        "generated_at_utc": index["generated_at_utc"],
        "latest_measurement_utc": latest_source,
        "station_count": len(stations),
        "availability_counts": availability_counts,
        "schema_version": LIVE_SCHEMA_VERSION,
    })

    print(
        f"Live-Datensatz erstellt: {len(stations)} Stationen, {len(failures)} Fehler, "
        f"Wind {availability_counts['wind']}, Böen {availability_counts['gust']}, "
        f"Niederschlag {availability_counts['precipitation']}, letzter Messzeitpunkt {latest_source}"
    )
    set_output("changed", "true")
    set_output("station_count", str(len(stations)))
    set_output("latest_measurement", str(latest_source or ""))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        set_output("changed", "false")
        raise
