#!/usr/bin/env python3
"""Build compact near-real-time DWD 10-minute temperature station data.

Data source:
DWD CDC observations_germany/climate/10_minutes/air_temperature/now/

The script is designed for a separate, force-replaced ``live-data`` branch.
It checks the DWD directory listing every run. Only if the listing or station
metadata changed are the station ZIP files downloaded again.
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

NOW_BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/now/"
META_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/historical/zehn_min_tu_Beschreibung_Stationen.txt"
BERLIN = ZoneInfo("Europe/Berlin")
USER_AGENT = "climate-dashboard-current/13.1 (+GitHub Actions; DWD Open Data)"
GERMAN_STATES = sorted([
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg",
    "Hessen", "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen",
    "Rheinland-Pfalz", "Saarland", "Sachsen", "Sachsen-Anhalt",
    "Schleswig-Holstein", "Thüringen",
], key=len, reverse=True)


def request_bytes(url: str, timeout: int = 35) -> bytes:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.content


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
    return round(number, 2)


def parse_product_zip(raw: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [name for name in archive.namelist() if Path(name).name.lower().startswith("produkt_") and name.lower().endswith(".txt")]
        if not names:
            names = [name for name in archive.namelist() if name.lower().endswith(".txt") and "metadaten" not in name.lower()]
        if not names:
            raise RuntimeError("Keine Produktdatei im DWD-ZIP gefunden")
        data = archive.read(names[0])
    text = data.decode("utf-8", errors="replace")
    if "MESS_DATUM" not in text:
        text = data.decode("cp1252", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        row = {(key or "").strip(): (value.strip() if isinstance(value, str) else value) for key, value in raw_row.items()}
        stamp = row.get("MESS_DATUM")
        if not stamp:
            continue
        try:
            dt = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        rows.append({
            "dt": dt,
            "temp": as_number(row.get("TT_10")),
            "humidity": as_number(row.get("RF_10")),
            "dewpoint": as_number(row.get("TD_10")),
            "pressure": as_number(row.get("PP_10")),
            "ground_temp": as_number(row.get("TM5_10")),
            "quality": row.get("QN") or row.get("QN_9") or None,
        })
    rows.sort(key=lambda item: item["dt"])
    return rows


def average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def build_station_profile(station_id: str, filename: str, metadata: dict[str, dict[str, Any]], now_utc: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = request_bytes(NOW_BASE + filename)
    rows = parse_product_zip(raw)
    if not rows:
        raise RuntimeError("keine Messwerte")

    cutoff = now_utc - timedelta(hours=30)
    rows = [row for row in rows if row["dt"] >= cutoff]
    if not rows:
        raise RuntimeError("keine Messwerte in den letzten 30 Stunden")

    latest = max(rows, key=lambda item: item["dt"])
    latest_local = latest["dt"].astimezone(BERLIN)
    today_local = now_utc.astimezone(BERLIN).date()
    today = [row for row in rows if row["dt"].astimezone(BERLIN).date() == today_local]
    today_temps = [row["temp"] for row in today if row["temp"] is not None]

    meta = metadata.get(station_id, {
        "id": station_id, "name": f"Station {station_id}", "state": "",
        "elevation_m": None, "lat": None, "lon": None, "from": "", "to": "",
    })
    series = []
    for row in rows:
        local_dt = row["dt"].astimezone(BERLIN)
        series.append([
            local_dt.isoformat(timespec="minutes"),
            row["temp"], row["humidity"], row["dewpoint"], row["pressure"], row["ground_temp"],
        ])

    summary = {
        **meta,
        "latest_local": latest_local.isoformat(timespec="minutes"),
        "latest_utc": latest["dt"].isoformat(timespec="minutes").replace("+00:00", "Z"),
        "temperature_c": latest["temp"],
        "humidity_pct": latest["humidity"],
        "dewpoint_c": latest["dewpoint"],
        "pressure_hpa": latest["pressure"],
        "ground_temp_c": latest["ground_temp"],
        "today_min_c": round(min(today_temps), 2) if today_temps else None,
        "today_max_c": round(max(today_temps), 2) if today_temps else None,
        "today_mean_10min_c": average(today_temps),
        "today_count": len(today_temps),
        "profile": f"stations/{station_id}.json",
    }
    profile = {
        "schema_version": 1,
        "station": meta,
        "latest": {
            "local": summary["latest_local"],
            "utc": summary["latest_utc"],
            "temperature_c": latest["temp"],
            "humidity_pct": latest["humidity"],
            "dewpoint_c": latest["dewpoint"],
            "pressure_hpa": latest["pressure"],
            "ground_temp_c": latest["ground_temp"],
            "quality": latest["quality"],
        },
        "today": {
            "date": today_local.isoformat(),
            "min_c": summary["today_min_c"],
            "max_c": summary["today_max_c"],
            "mean_10min_c": summary["today_mean_10min_c"],
            "count": summary["today_count"],
        },
        "series_columns": ["time_local", "temperature_c", "humidity_pct", "dewpoint_c", "pressure_hpa", "ground_temp_c"],
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
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    now_utc = datetime.now(timezone.utc)

    listing = request_text(NOW_BASE)
    metadata_text = request_text(META_URL)
    lines = sorted(line.strip() for line in listing.splitlines() if "10minutenwerte_TU_" in line and "_now.zip" in line)
    filenames = sorted(set(re.findall(r"10minutenwerte_TU_(\d{5})_now\.zip", listing)))
    if not filenames:
        raise RuntimeError("Im DWD-now-Verzeichnis wurden keine TU-Stationsdateien gefunden")
    file_map = {station_id: f"10minutenwerte_TU_{station_id}_now.zip" for station_id in filenames}

    source_hash = hashlib.sha256(("\n".join(lines) + "\n" + metadata_text).encode("utf-8", errors="replace")).hexdigest()
    state_path = output / "state.json"
    old_state = {}
    if state_path.exists():
        try:
            old_state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            old_state = {}
    if not args.force and old_state.get("source_hash") == source_hash and (output / "current_index.json").exists():
        print("DWD-now-Bestand unverändert – kein neuer Live-Datensatz nötig.")
        set_output("changed", "false")
        return 0

    metadata = parse_station_metadata(metadata_text)
    print(f"DWD-now-Bestand geändert: {len(file_map)} Stationsarchive werden verarbeitet …")
    stations: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    profiles: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(build_station_profile, station_id, filename, metadata, now_utc): station_id
            for station_id, filename in file_map.items()
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
                print(f"  {completed}/{len(futures)} Archive verarbeitet")

    if len(stations) < max(20, int(len(file_map) * 0.5)):
        raise RuntimeError(f"Zu wenige Stationen erfolgreich verarbeitet: {len(stations)} von {len(file_map)}")

    stations.sort(key=lambda item: (item.get("state") or "", item.get("name") or "", item["id"]))
    latest_times = [item["latest_utc"] for item in stations if item.get("latest_utc")]
    latest_source = max(latest_times) if latest_times else None

    stations_dir = output / "stations"
    stations_dir.mkdir(parents=True, exist_ok=True)
    # Remove obsolete station profiles from the live snapshot.
    valid_paths = {f"{station_id}.json" for station_id in profiles}
    for old_file in stations_dir.glob("*.json"):
        if old_file.name not in valid_paths:
            old_file.unlink()
    for station_id, profile in profiles.items():
        write_json(stations_dir / f"{station_id}.json", profile)

    index = {
        "schema_version": 1,
        "generated_at_utc": now_utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "latest_measurement_utc": latest_source,
        "station_count": len(stations),
        "failed_station_count": len(failures),
        "source": "DWD CDC 10-minute air_temperature/now",
        "source_note": "10-Minuten-Messwerte; DWD-now-Verzeichnis wird laut Datensatzbeschreibung in Abständen unter einer Stunde aktualisiert; aktuelle Werte sind vorläufig.",
        "stations": stations,
        "failures": failures[:50],
    }
    write_json(output / "current_index.json", index)
    write_json(state_path, {
        "source_hash": source_hash,
        "generated_at_utc": index["generated_at_utc"],
        "latest_measurement_utc": latest_source,
        "station_count": len(stations),
    })
    print(f"Live-Datensatz erstellt: {len(stations)} Stationen, {len(failures)} Fehler, letzter Messzeitpunkt {latest_source}")
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
