#!/usr/bin/env python3
"""Cumulative DUETT sunshine observation + hourly-model ensemble outlook.

DUETT reports per-hour sunshine in minutes; the accompanying observation
generator has already converted complete UTC days to hours. Open-Meteo
ensemble hourly sunshine_duration is in seconds; converted to daily hours by
hourly_sunshine_to_daily before combining with observed running sums.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from build_state_monthly_ensemble_outlook import (
    MODEL_CONFIG, REGION_ORDER, build_support_points, collect_model,
    load_geometries, merge_running_outlook, running_sum,
)


def validate_observations(doc: dict) -> list[str]:
    if (doc.get("schema_version") != 1 or doc.get("forecast") is not False
            or doc.get("unit") != "h"
            or doc.get("product") != "state_monthly_duett_sunshine_observations"):
        raise ValueError("Expected observed DWD DUETT sunshine hours schema")
    dates = doc.get("dates")
    if not isinstance(dates, list) or not dates:
        raise ValueError("No observed DUETT days found")
    month = str(doc.get("month", ""))
    if len(month) != 7 or dates[0] != month + "-01":
        raise ValueError("Invalid DUETT month")
    start = date.fromisoformat(month + "-01")
    if dates != [(start + timedelta(days=i)).isoformat() for i in range(len(dates))]:
        raise ValueError("DUETT observation days are not consecutive")
    if doc.get("data_through") != dates[-1]:
        raise ValueError("DUETT observed cutoff does not match dates")
    if set(doc.get("regions", {})) != set(REGION_ORDER):
        raise ValueError("DUETT must contain Germany and all 16 states")
    for region in REGION_ORDER:
        values = doc["regions"][region].get("daily", [])
        if len(values) != len(dates) or any(
            not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 24
            for v in values
        ):
            raise ValueError(f"DUETT sunshine observation invalid for {region}")
    return dates


def build_payload(doc: dict, models: dict) -> dict:
    observed_days = validate_observations(doc)
    year, month = map(int, doc["month"].split("-"))
    period_dates = [date(year, month, d).isoformat()
                    for d in range(1, calendar.monthrange(year, month)[1]+1)]
    regions = {}
    for region in REGION_ORDER:
        observed = doc["regions"][region]["daily"]
        observed_running = running_sum(observed)
        converted = {}
        for key, model in models.items():
            converted[key] = {
                "label": model["label"],
                "run": model.get("run"),
                "api_model": model.get("api_model"),
                **merge_running_outlook(
                    observed_days, observed, model["regions"][region],
                    period_dates, aggregation="sum",
                ),
            }
        regions[region] = {
            "observed_through": observed_days[-1],
            "observed_running": [round(v, 3) for v in observed_running]
                                + [None] * (len(period_dates)-len(observed_running)),
            "observed_current": round(observed_running[-1], 3),
            "models": converted,
        }
    return {
        "schema_version": 1,
        "product": "state_monthly_ensemble_sunshine",
        "parameter": "sunshine",
        "unit": "h",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "year": year,
        "month": month,
        "dates": period_dates,
        "regions_order": list(REGION_ORDER),
        "models_order": list(models),
        "observation_source": "DWD DUETT SDU 1km satellite+stations",
        "observation_data_through": observed_days[-1],
        "forecast_source": "Open-Meteo Ensemble API (hourly sunshine_duration)",
        "climatology_available": False,
        "regions": regions,
        "method": {
            "observation": "DUETT per-hour region means in minutes, accumulated to complete 24-hour UTC days and converted to hours",
            "forecast": "Hourly sunshine_duration per ensemble member (seconds), 24 hours ending 01:00 through next-day 00:00 UTC (closest to DUETT :50 synoptic hours), converted to hours; area support-point means",
            "gap_policy": "Missing observed hours or model hours are never counted as zero",
            "reference": "Climatology 1991-2020 will be added from a separate historical product",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", default=",".join(MODEL_CONFIG))
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    observed = json.loads(args.observed.read_text(encoding="utf-8"))
    validate_observations(observed)
    wanted = [key.strip() for key in args.models.split(",") if key.strip()]
    if not wanted or any(key not in MODEL_CONFIG for key in wanted):
        parser.error("Unknown or empty ensemble model selection")
    support = build_support_points(load_geometries())
    forecasts = {}
    errors = {}
    for key in wanted:
        try:
            forecasts[key] = collect_model(
                key, support, args.batch_size,
                variable="sunshine_duration", time_resolution="hourly",
            )
            print(key, "Sonnenschein-Member:", forecasts[key]["member_count"], flush=True)
        except Exception as exc:
            print(key, "nicht verfügbar:", exc, flush=True)
            errors[key] = str(exc)
    if not forecasts:
        raise RuntimeError("None of the sunshine ensemble models could be downloaded")
    payload = build_payload(observed, forecasts)
    payload["model_errors"] = errors
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("Sonnenausblick:", payload["year"], payload["month"], payload["observation_data_through"],
          "Modelle:", payload["models_order"])


if __name__ == "__main__":
    main()
