#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from era5_running_season import RUNNING_SEASON_IDS, season_spec

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


def current_running_season(running: dict) -> tuple[str, dict]:
    periods = running.get("periods") or {}
    data_through_text = running.get("data_through")
    if not data_through_text:
        raise RuntimeError("data_through fehlt im laufenden ERA5-Land-Index.")
    data_through = date.fromisoformat(str(data_through_text))
    spec = season_spec(data_through)
    period = periods.get(spec.period_id)
    if isinstance(period, dict):
        return spec.period_id, period

    month = periods.get("running_month")
    if not isinstance(month, dict):
        raise RuntimeError("running_month fehlt im laufenden ERA5-Land-Index.")
    if spec.completed_months:
        raise RuntimeError(
            f"{spec.period_id} fehlt, obwohl bereits vollständige Saisonmonate einbezogen werden müssten."
        )

    period = copy.deepcopy(month)
    period.update({
        "id": spec.period_id,
        "label": spec.label,
        "date_start": spec.start.isoformat(),
        "date_end": data_through.isoformat(),
        "completed_months": [],
        "partial_month": data_through.month,
    })
    return spec.period_id, period


def expose_running(main: dict, running: dict) -> dict:
    if running.get("ready") is not True:
        raise RuntimeError("Laufender ERA5-Land-Datensatz ist nicht bereit.")

    running_periods = running.get("periods") or {}
    month = running_periods.get("running_month")
    if not isinstance(month, dict):
        raise RuntimeError("running_month fehlt im laufenden ERA5-Land-Index.")
    season_id, season = current_running_season(running)

    periods = dict(main.get("periods") or {})
    periods["running_month"] = expose_period(month, running)
    for candidate in RUNNING_SEASON_IDS:
        periods.pop(candidate, None)
    periods[season_id] = expose_period(season, running)
    main["periods"] = periods

    main["running"] = {
        "ready": True,
        "data_through": running.get("data_through"),
        "source_file": "era5_land_europe/running/index.json",
        "preliminary": bool(running.get("preliminary", True)),
        "availability_note": running.get("availability_note"),
        "reference_note": running.get("reference_note"),
        "season_id": season_id,
    }
    main["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return main


def main() -> int:
    if not MAIN_INDEX.exists() or not RUNNING_INDEX.exists():
        raise RuntimeError("ERA5-Hauptindex oder laufender Index fehlt.")

    payload = expose_running(
        json.loads(MAIN_INDEX.read_text(encoding="utf-8")),
        json.loads(RUNNING_INDEX.read_text(encoding="utf-8")),
    )
    atomic_json(MAIN_INDEX, payload)
    season_id = payload.get("running", {}).get("season_id")
    print(
        "ERA5 Frontend: laufender Monat und laufende Saison bereitgestellt · "
        f"{season_id} · Daten bis {payload.get('running', {}).get('data_through')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
