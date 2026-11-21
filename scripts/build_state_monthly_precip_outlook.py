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
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from build_state_monthly_ensemble_outlook import (
    MODEL_CONFIG, REGION_ORDER, build_support_points, collect_model,
    load_geometries, merge_running_outlook, running_sum, outlook_months,
    month_observations, empty_hydro_observations, month_forecast_days, merge_month_caches,
)


def validate_observed(doc: dict[str, Any]) -> tuple[list[str], list[str]]:
    if doc.get("schema_version") != 1 or doc.get("forecast") is not False:
        raise ValueError("Unexpected HYRAS observed precipitation schema")
    if doc.get("unit") != "mm":
        raise ValueError("HYRAS precipitation must be in millimetres")
    observed_dates = doc.get("dates")
    if not isinstance(observed_dates, list):
        raise ValueError("Invalid observed HYRAS daily dates")
    month = str(doc.get("month"))
    if len(month) != 7 or any(day[:7] != month for day in observed_dates):
        raise ValueError("Observed days span more than one month")
    start = date.fromisoformat(month + "-01")
    expected = [(start.fromordinal(start.toordinal() + i)).isoformat()
                for i in range(len(observed_dates))]
    if observed_dates != expected or (observed_dates[-1] if observed_dates else None) != doc.get("data_through"):
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


def build_payload(doc: dict[str, Any], model_data: dict[str, dict], support: dict, *, target=None) -> dict:
    _, regions_order = validate_observed(doc)
    year, month = target or tuple(map(int, doc["month"].split("-")))
    observed_dates, daily = month_observations(doc, year, month)
    full_dates = [date(year, month, d).isoformat()
                  for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    regions = {}
    for region in regions_order:
        observed_values = daily[region]
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
            "observed_through": observed_dates[-1] if observed_dates else None,
            "observed_running": [round(v, 3) for v in run] + [None] * (len(full_dates) - len(run)),
            "observed_current": round(run[-1], 3) if run else None,
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
        "observation_data_through": observed_dates[-1] if observed_dates else None,
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


def usable_run(value, now):
    try:
        run = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return run if run.tzinfo and timedelta(0) <= now - run <= timedelta(hours=48) else None
    except (TypeError, ValueError, AttributeError):
        return None


def usable_curve(curve, payload):
    """Require a forecast immediately after the observed period, never a gap."""
    try:
        cutoff = payload["observation_data_through"]
        index = payload["dates"].index(cutoff) + 1 if cutoff else 0
        dates = payload["dates"]
        end = dates.index(curve["forecast_through"])
        if index > end or curve["forecast_from"] != dates[index] or curve["member_count"] <= 0:
            return False
        def numeric(v):
            return isinstance(v, (int, float)) and math.isfinite(v) and v >= 0
        for key in ("min", "p05", "p20", "mean", "p80", "p95", "max"):
            values = curve["stats"][key]
            if len(values) != len(dates) or any(not numeric(v) for v in values[index:end+1]):
                return False
            if any(v is not None for v in values[:index] + values[end+1:]):
                return False
        control = curve["control"]
        return len(control) == len(dates) and all(v is None or numeric(v) for v in control)
    except (TypeError, ValueError, IndexError, KeyError):
        return False


def build_resilient_payload(observed, fresh, cached, previous, errors, now, *, target=None):
    payload = build_payload(observed, {}, {}, target=target)
    if (isinstance(previous, dict) and previous.get("parameter") == "precipitation"
            and isinstance(previous.get("observation_data_through"), str)
            and previous["observation_data_through"] > (payload["observation_data_through"] or (date.fromisoformat(payload['dates'][0])-timedelta(days=1)).isoformat())):
        raise ValueError("HYRAS observation date regressed; previous publication preserved")
    if not isinstance(cached, dict):
        cached = {}
    payload["observation_complete"] = payload["observation_data_through"] == payload["dates"][-1]
    if payload["observation_complete"]:
        payload["model_errors"] = {}
        payload["retained_models"] = []
        return payload, {}
    errors = dict(errors)
    next_cache = {}
    retained = []
    for key in MODEL_CONFIG:
        candidates = []
        for is_cached, source in ((False, fresh), (True, cached), (True, cached.get("__preview", {}))):
            model = source.get(key)
            if not isinstance(model, dict):
                continue
            run = usable_run(model.get("run"), now)
            if run is None and (is_cached or model.get("run") is not None):
                continue
            try:
                built = build_payload(observed, {key: model}, {}, target=target)
                curves = {r: built["regions"][r]["models"][key] for r in REGION_ORDER}
                if all(usable_curve(c, payload) for c in curves.values()):
                    candidates.append((run or datetime.min.replace(tzinfo=timezone.utc), not is_cached, curves, model))
            except (ValueError, KeyError, TypeError, RuntimeError, IndexError):
                continue
        # A cached forecast can be recomputed at member level against the new
        # observations. Never overwrite it with a less recent model run.
        if candidates:
            _, is_fresh, curves, model = max(candidates, key=lambda c: (c[0], c[1]))
            next_cache[key] = model
        else:
            is_fresh = False
            curves = {}
            # Pre-cache releases carry only aggregated quantiles. These are
            # safe to reuse only with the identical observation anchor.
            if (isinstance(previous, dict) and previous.get("parameter") == "precipitation"
                    and previous.get("dates") == payload["dates"]
                    and previous.get("observation_data_through") == payload["observation_data_through"]):
                try:
                    for r in REGION_ORDER:
                        old = previous["regions"][r]
                        curve = old["models"][key]
                        if (old["observed_running"] != payload["regions"][r]["observed_running"]
                                or not usable_run(curve.get("run"), now) or not usable_curve(curve, payload)):
                            raise ValueError("incompatible legacy forecast")
                        curves[r] = curve
                except (KeyError, TypeError, ValueError, AttributeError):
                    curves = {}
        if not curves:
            errors.setdefault(key, "Kein lückenloser Niederschlagslauf verfügbar")
            continue
        if not is_fresh:
            retained.append(key)
            errors.setdefault(key, "Vorheriger Modelllauf wiederverwendet")
        for r, curve in curves.items():
            payload["regions"][r]["models"][key] = {**curve, "retained": not is_fresh}
        payload["models_order"].append(key)
    payload["model_errors"] = errors
    payload["retained_models"] = retained
    return payload, next_cache


def build_precip_documents(observed, fresh, cached, previous, errors, now, today):
    current, preview_target = outlook_months(today)
    prev_preview = previous.get("next_month") if isinstance(previous, dict) else None
    def previous_for(target):
        for doc in (previous, prev_preview):
            if isinstance(doc, dict) and (doc.get("year"), doc.get("month")) == target:
                return doc
        return None
    payload, current_cache = build_resilient_payload(
        observed, fresh, cached, previous_for(current), errors, now, target=current)
    preview, preview_cache = build_resilient_payload(
        observed, fresh, cached, previous_for(preview_target), {}, now, target=preview_target)
    if preview["models_order"]:
        # Limited lead time is expected in a preview, not an acquisition error.
        preview["model_errors"] = {k: v for k, v in preview["model_errors"].items() if k in preview["models_order"]}
        payload["next_month"] = preview
    return payload, merge_month_caches(current_cache, preview_cache)


def read_previous(path):
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"Vorheriger Datenstand nicht lesbar: {exc}", flush=True)
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--observed", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--cache", type=Path, help="Daily regional member cache, read and updated in place")
    ap.add_argument("--models", default=",".join(MODEL_CONFIG))
    ap.add_argument("--batch-size", type=int, default=8)
    args = ap.parse_args()
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    observed = (json.loads(args.observed.read_text(encoding="utf-8"))
                if args.observed and args.observed.is_file() else empty_hydro_observations(today, "mm"))
    validate_observed(observed)
    requested = [s.strip() for s in args.models.split(",") if s.strip()]
    if not requested or any(key not in MODEL_CONFIG for key in requested):
        raise ValueError("Unknown or empty model selection")

    forecasts, errors = {}, {}
    support = build_support_points(load_geometries())
    horizon = month_forecast_days(today, *outlook_months(today)[1])
    for key in requested:
        try:
            forecasts[key] = collect_model(
                key, support, args.batch_size, variable="precipitation", time_resolution="hourly", forecast_days=horizon)
            print(key, "Niederschlagsmember:", forecasts[key]["member_count"], flush=True)
        except Exception as exc:
            errors[key] = str(exc)
            print(key, "nicht verfügbar:", exc, flush=True)
    old_cache = read_previous(args.cache)
    cached = old_cache.get("models", {}) if isinstance(old_cache, dict) and old_cache.get("schema_version") == 1 else {}
    payload, next_cache = build_precip_documents(observed, forecasts, cached, read_previous(args.previous), errors, datetime.now(timezone.utc), today)
    if not payload["models_order"] and not payload["observation_data_through"] and not payload.get("next_month"):
        raise RuntimeError("No precipitation observations or valid forecasts")
    if not payload["models_order"] and not payload["observation_complete"]:
        print("No usable ensemble precipitation models available; publishing valid observations only", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if args.cache:
        args.cache.write_text(json.dumps({"schema_version":1,"models":next_cache}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("Niederschlagsausblick:", payload["year"], payload["month"], "bis", payload["observation_data_through"], "Modelle:", payload["models_order"], "aus Cache:", payload["retained_models"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
