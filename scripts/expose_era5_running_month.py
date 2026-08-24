#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_INDEX = ROOT / "era5_land_europe" / "index.json"
RUNNING_INDEX = ROOT / "era5_land_europe" / "running" / "index.json"

MONTH_NAMES = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}


def atomic_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def main() -> int:
    if not MAIN_INDEX.exists() or not RUNNING_INDEX.exists():
        raise RuntimeError("ERA5-Hauptindex oder laufender Index fehlt.")

    main = json.loads(MAIN_INDEX.read_text(encoding="utf-8"))
    running = json.loads(RUNNING_INDEX.read_text(encoding="utf-8"))
    if running.get("ready") is not True:
        raise RuntimeError("Laufender ERA5-Land-Datensatz ist nicht bereit.")

    source = (running.get("periods") or {}).get("running_month")
    if not isinstance(source, dict):
        raise RuntimeError("running_month fehlt im laufenden ERA5-Land-Index.")

    start = str(source.get("date_start") or "")
    try:
        year = int(start[:4])
        month = int(start[5:7])
    except Exception as exc:
        raise RuntimeError(f"Ungültiger laufender Monatsbeginn: {start!r}") from exc
    if month not in MONTH_NAMES:
        raise RuntimeError(f"Ungültiger Monat: {month}")

    period_id = f"month_{month:02d}"
    period = copy.deepcopy(source)
    period.update({
        "id": period_id,
        # Bewusst ohne 'bis ...': Bei historischen Karten kann das Frontend
        # dadurch sauber nur das Kartenjahr austauschen.
        "label": f"{MONTH_NAMES[month]} {year}",
        "year": year,
        "months": [month],
        "historical_only": False,
        "analysis_ready": False,
        "partial_daily": True,
        "running_data_through": running.get("data_through"),
        "running_label": source.get("label"),
        "parameters": ["temperature", "precipitation"],
    })

    periods = dict(main.get("periods") or {})
    periods[period_id] = period
    main["periods"] = periods

    history = dict(main.get("history_map") or {})
    current_months = {
        int(value)
        for value in history.get("temperature_precipitation_current_months", [])
        if str(value).isdigit()
    }
    current_months.add(month)
    history["temperature_precipitation_current_year"] = year
    history["temperature_precipitation_current_months"] = sorted(current_months)
    main["history_map"] = history

    main["running"] = {
        "ready": True,
        "data_through": running.get("data_through"),
        "source_file": "era5_land_europe/running/index.json",
        "current_period": period_id,
        "preliminary": bool(running.get("preliminary", True)),
        "note": running.get("availability_note"),
    }
    main["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    atomic_json(MAIN_INDEX, main)
    print(
        f"ERA5 Frontend: {MONTH_NAMES[month]} {year} als laufender Monat sichtbar · "
        f"Daten bis {running.get('data_through')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
