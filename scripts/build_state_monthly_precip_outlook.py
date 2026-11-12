#!/usr/bin/env python3
"""Build observation-anchored monthly precipitation ensemble summaries.

Consecutive DWD HYRAS-DE-PRE region observations are continued with the
individual GEFS/IFS/AIFS/ICON-EU 06–06 UTC precipitation member totals.
Do not bridge unobserved days with zero or interpolate across API gaps.
"""
from __future__ import annotations

import argparse
import calendar
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from build_state_monthly_ensemble_outlook import (
    MODEL_CONFIG, REGION_ORDER, build_support_points, collect_model,
    load_geometries, merge_running_outlook, running_sum,
)


def validate_observed(doc: dict[str, Any]) -> tuple[list[str], list[str]]:
    if doc.get("schema_version") != 1 or doc.get("forecast") is not False:
        raise ValueError("Unexpected HYRAS observed precipitation schema")
    if doc.get("unit") != "mm":
        raise ValueError("HYRAS precipitation must be in millimetres")
    observed_dates = doc.get("dates")
    if not isinstance(observed_dates, list) or not observed_dates:
        raise ValueError("No observed HYRAS daily dates available")
    month = str(doc.get("month"))
    if len(month) != 7 or any(day[:7] != month for day in observed_dates):
        raise ValueError("Observed days span more than one month")
    start = date.fromisoformat(month + "-01")
    expected = [(start.fromordinal(start.toordinal() + i)).isoformat()
                for i in range(len(observed_dates))]
    if observed_dates != expected or observed_dates[-1] != doc.get("data_through"):
        raise ValueError("HYRAS daily dates are not contiguous")
    if set(doc.get("regions", {})) != set(REGION_ORDER):
        raise ValueError("Not all 17 regions have precipitation observations")
    for region in REGION_ORDER:
        samples = doc["regions"][region].get("daily", [])
        if len(samples) != len(observed_dates):
            raise ValueError(f"Missing HYRAS daily region observations: {region}")
        if any(v is None or not isinstance(v, (int, float)) or not 0 <= v < 1000 for v in samples):
            raise ValueError(f"Invalid HYRAS daily rainfall in {region}")
    return observed_dates, [*REGION_ORDER]


def build_payload(doc: dict[str, Any], model_data: dict[str, dict], support: dict) -> dict:
    observed_dates, regions_order = validate_observed(doc)
    year, month = map(int, doc["month"].split("-"))
    full_dates = [date(year, month, d).isoformat()
                  for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    regions = {}
    for region in regions_order:
        observed_values = doc["regions"][region]["daily"]
        run = running_sum(observed_values)
        curves = {}
        for key, mdata in model_data.items():
            curves[key] = {
                "label": mdata["label"],
                "run": mdata.get("run"),
                "api_model": mdata.get("api_model"),
                **merge_running_outlook(
                    observed_dates, observed_values,
                    mdata["regions"][region], full_dates,
                    aggregation="sum",
                ),
            }
        regions[region] = {
            "observed_through": observed_dates[-1],
            "observed_running": [round(v, 3) for v in run] + [None] * (len(full_dates) - len(run)),
            "observed_current": round(run[-1], 3),
            "models": curves,
        }
    return {
        "schema_version": 1,
        "product": "state_monthly_ensemble_precipitation",
        "parameter": "precipitation",
        "unit": "mm",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "year": year,
        "month": month,
        "dates": full_dates,
        "regions_order": regions_order,
        "models_order": list(model_data),
        "observation_source": "DWD HYRAS-DE-PRE 1 km",
        "observation_data_through": observed_dates[-1],
        "climatology_available": False,
        "forecast_source": "Open-Meteo Ensemble API",
        "method": {
            "observation": "Daily 1 km HYRAS area means (millimetres), accumulated from the first day of the month.",
            "forecast": "Hourly ensemble precipitation (mm) summed to HYRAS 06–06 UTC days per member and support point, then accumulated.",
            "gap_policy": "No zero-filling and no forecasting across unavailable days between the last observation and first model day.",
            "reference": "1991-2020 regional daily precipitation climatology to be added separately.",
        },
        "regions": regions,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--observed", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--models", default=",".join(MODEL_CONFIG))
    ap.add_argument("--batch-size", type=int, default=8)
    args = ap.parse_args()
    observed = json.loads(args.observed.read_text(encoding="utf-8"))
    validate_observed(observed)
    requested = [s.strip() for s in args.models.split(",") if s.strip()]
    if not requested or any(key not in MODEL_CONFIG for key in requested):
        raise ValueError("Unknown or empty model selection")

    support = build_support_points(load_geometries())
    forecasts, errors = {}, {}
    for key in requested:
        try:
            forecasts[key] = collect_model(
                key, support, args.batch_size, variable="precipitation", time_resolution="hourly")
            print(key, "Niederschlagsmember:", forecasts[key]["member_count"], flush=True)
        except Exception as exc:
            errors[key] = str(exc)
            print(key, "nicht verfügbar:", exc, flush=True)
    if not forecasts:
        raise RuntimeError("No ensemble precipitation models available")

    payload = build_payload(observed, forecasts, support)
    payload["model_errors"] = errors
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("Niederschlagsausblick:", payload["year"], payload["month"], "bis", payload["observation_data_through"], "Modelle:", list(forecasts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
