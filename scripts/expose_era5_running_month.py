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


def atomic_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def expose_period(source: dict, running: dict) -> dict:
    period = copy.deepcopy(source)
    period.update({
        "historical_only": False,
        "analysis_ready": False,
        "running_only": True,
        "partial_daily": True,
        "running_data_through": running.get("data_through"),
        "parameters": ["temperature", "precipitation"],
    })
    return period


def main() -> int:
    if not MAIN_INDEX.exists() or not RUNNING_INDEX.exists():
        raise RuntimeError("ERA5-Hauptindex oder laufender Index fehlt.")

    main = json.loads(MAIN_INDEX.read_text(encoding="utf-8"))
    running = json.loads(RUNNING_INDEX.read_text(encoding="utf-8"))
    if running.get("ready") is not True:
        raise RuntimeError("Laufender ERA5-Land-Datensatz ist nicht bereit.")

    running_periods = running.get("periods") or {}
    month = running_periods.get("running_month")
    summer = running_periods.get("running_summer")
    if not isinstance(month, dict) or not isinstance(summer, dict):
        raise RuntimeError("running_month oder running_summer fehlt im laufenden ERA5-Land-Index.")

    periods = dict(main.get("periods") or {})
    periods["running_month"] = expose_period(month, running)
    periods["running_summer"] = expose_period(summer, running)
    main["periods"] = periods

    main["running"] = {
        "ready": True,
        "data_through": running.get("data_through"),
        "source_file": "era5_land_europe/running/index.json",
        "preliminary": bool(running.get("preliminary", True)),
        "availability_note": running.get("availability_note"),
        "reference_note": running.get("reference_note"),
    }
    main["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    atomic_json(MAIN_INDEX, main)
    print(
        "ERA5 Frontend: laufender Monat und laufender Sommer bereitgestellt · "
        f"Daten bis {running.get('data_through')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
