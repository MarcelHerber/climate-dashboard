#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "update_era5_land_europe.py"
INDEX_PATH = ROOT / "era5_land_europe" / "index.json"
MAP_DIR = ROOT / "era5_land_europe" / "maps"
MONTH_NAMES = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}
PATCH_VERSION = 1


def load_core():
    spec = importlib.util.spec_from_file_location("era5_update_core_current_tp", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"ERA5-Hauptskript konnte nicht importiert werden: {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def latest_complete_key(payload: dict) -> tuple[int, int]:
    raw = str(payload.get("latest_month_key") or "")
    match = re.fullmatch(r"(\d{4})-(\d{2})", raw)
    if not match:
        raw = str(payload.get("data_through") or "")
        match = re.match(r"(\d{4})-(\d{2})", raw)
    if not match:
        raise RuntimeError("Jüngster vollständiger ERA5-Monat konnte aus index.json nicht bestimmt werden.")
    year, month = int(match.group(1)), int(match.group(2))
    if month < 1 or month > 12:
        raise RuntimeError(f"Ungültiger Zielmonat: {year}-{month:02d}")
    return year, month


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def map_paths(month: int) -> dict[str, Path]:
    pid = f"month_{month:02d}"
    return {
        "temp_absolute": MAP_DIR / f"temperature_{pid}_absolute.png",
        "temp_anomaly": MAP_DIR / f"temperature_{pid}_anomaly.png",
        "precip_absolute": MAP_DIR / f"precipitation_{pid}_absolute.png",
        "precip_percent": MAP_DIR / f"precipitation_{pid}_percent.png",
    }


def finite_weighted_mean(core, field: np.ndarray, lat: np.ndarray) -> float | None:
    return core.weighted_mean(np.asarray(field, dtype=float), np.asarray(lat, dtype=float))


def render_month(core, month: int, year: int, current: tuple, climate: tuple, force: bool,
                 previous_year: int | None, previous_months: set[int]) -> dict:
    lat, lon, temp, precip = current
    clim_lat, clim_lon, clim_temp, clim_precip = climate
    if not (np.array_equal(np.asarray(lat), np.asarray(clim_lat)) and np.array_equal(np.asarray(lon), np.asarray(clim_lon))):
        raise RuntimeError(f"Aktuelles Raster und Klimaraster stimmen für {MONTH_NAMES[month]} nicht überein.")

    temp = np.asarray(temp, dtype=float)
    precip = np.asarray(precip, dtype=float)
    clim_temp = np.asarray(clim_temp, dtype=float)
    clim_precip = np.asarray(clim_precip, dtype=float)
    temp_anom = temp - clim_temp
    with np.errstate(invalid="ignore", divide="ignore"):
        precip_pct = np.where(clim_precip > 1.0, precip / clim_precip * 100.0, np.nan)

    files = map_paths(month)
    same_current_year = previous_year == year and month in previous_months
    need_render = force or not same_current_year or any(not path.exists() for path in files.values())
    label = f"{MONTH_NAMES[month]} {year}"

    if need_render:
        print(f"Erzeuge aktuelle T/P-Monatskarten: {label}")
        core.render_map(
            temp, lat, lon,
            title=f"ERA5-Land Europa · 2-m-Temperatur · {label}",
            subtitle="Absolutwert · Landflächen", unit="°C",
            filename=files["temp_absolute"], kind="temp_absolute",
        )
        core.render_map(
            temp_anom, lat, lon,
            title=f"ERA5-Land Europa · Temperaturabweichung · {label}",
            subtitle="gegenüber 1991–2020 · Landflächen", unit="K",
            filename=files["temp_anomaly"], kind="temp_anomaly",
        )
        core.render_map(
            precip, lat, lon,
            title=f"ERA5-Land Europa · Niederschlag · {label}",
            subtitle="Niederschlagssumme · Landflächen", unit="mm",
            filename=files["precip_absolute"], kind="precip_absolute",
        )
        core.render_map(
            precip_pct, lat, lon,
            title=f"ERA5-Land Europa · Niederschlag · {label}",
            subtitle="Prozent vom Mittel 1991–2020 · Landflächen", unit="% vom Mittel",
            filename=files["precip_percent"], kind="precip_percent",
        )
    else:
        print(f"Aktuelle T/P-Monatskarten vorhanden: {label}")

    temp_cur = finite_weighted_mean(core, temp, lat)
    temp_ref = finite_weighted_mean(core, clim_temp, lat)
    precip_cur = finite_weighted_mean(core, precip, lat)
    precip_ref = finite_weighted_mean(core, clim_precip, lat)

    return {
        "id": f"month_{month:02d}",
        "label": label,
        "year": int(year),
        "months": [int(month)],
        "historical_only": False,
        "tp_month_current": True,
        "analysis_ready": False,
        "parameters": ["temperature", "precipitation"],
        "temperature": {
            "absolute": {"file": rel(files["temp_absolute"]), "unit": "°C", "label": "Temperatur"},
            "anomaly": {"file": rel(files["temp_anomaly"]), "unit": "K", "label": "Abweichung 1991–2020"},
            "stats": {
                "current": temp_cur,
                "reference": temp_ref,
                "difference": None if temp_cur is None or temp_ref is None else temp_cur - temp_ref,
            },
        },
        "precipitation": {
            "absolute": {"file": rel(files["precip_absolute"]), "unit": "mm", "label": "Niederschlag"},
            "percent": {"file": rel(files["precip_percent"]), "unit": "%", "label": "Prozent vom Mittel 1991–2020"},
            "stats": {
                "current": precip_cur,
                "reference": precip_ref,
                "percent": None if precip_ref is None or precip_ref == 0 or precip_cur is None else precip_cur / precip_ref * 100.0,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aktuelle ERA5-Land Monatskarten für T/P von Januar bis zum jüngsten vollständigen Monat ergänzen."
    )
    parser.add_argument("--force", action="store_true", help="Aktuelle Monats-PNGs neu rendern")
    args = parser.parse_args()

    if not INDEX_PATH.exists():
        raise RuntimeError("era5_land_europe/index.json fehlt.")
    payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    year, latest_month = latest_complete_key(payload)
    months = list(range(1, latest_month + 1))
    if not months:
        raise RuntimeError("Keine vollständigen Monate im aktuellen ERA5-Jahr gefunden.")

    previous = payload.get("tp_current_months") if isinstance(payload.get("tp_current_months"), dict) else {}
    previous_year = int(previous.get("year")) if str(previous.get("year", "")).isdigit() else None
    previous_months = {int(m) for m in previous.get("months", []) if str(m).isdigit()}

    core = load_core()
    client = core.cds_client()

    print("=== ERA5-LAND EUROPA · AKTUELLE T/P-MONATE ===")
    print(f"Zieljahr: {year}")
    print(f"Vollständige Monate: Januar–{MONTH_NAMES[latest_month]} ({len(months)})")
    print("Historische 1950–2025-Packs werden nicht neu aufgebaut.")

    # Der Hauptworkflow hat genau diese Monatsdatei bereits geladen. Falls der Actions-Cache
    # sie wider Erwarten nicht enthält, lädt diese Funktion nur das aktuelle Jahr nach.
    current = core.load_current_months(client, year, months, False)
    climate = {month: core.load_climatology_month(client, month, False) for month in months}

    periods = dict(payload.get("periods") or {})
    for month in months:
        periods[f"month_{month:02d}"] = render_month(
            core, month, year, current[month], climate[month], args.force, previous_year, previous_months
        )
    payload["periods"] = periods
    payload["payload_version"] = max(10, int(payload.get("payload_version", 0) or 0))
    payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["tp_current_months"] = {
        "ready": True,
        "version": PATCH_VERSION,
        "year": int(year),
        "months": months,
        "latest_complete_month": int(latest_month),
        "note": (
            "Temperatur und Niederschlag sind im aktuellen ERA5-Land-Jahr für alle vollständig "
            "verfügbaren Monate einzeln auswählbar. Historische Jahre bleiben für dieselben Monate ab 1950 verfügbar."
        ),
    }
    history_map = dict(payload.get("history_map") or {})
    history_map["temperature_precipitation_current_year"] = int(year)
    history_map["temperature_precipitation_current_months"] = months
    payload["history_map"] = history_map
    atomic_json(INDEX_PATH, payload)

    print("=== SUMMARY ===")
    print(f"Aktuelle T/P-Monate bereit: {len(months)}/{latest_month}")
    print("Monate:", ", ".join(f"{MONTH_NAMES[m]} {year}" for m in months))
    print("Historische Monatsauswahl bleibt: 1950–2025")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
