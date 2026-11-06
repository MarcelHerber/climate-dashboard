#!/usr/bin/env python3
"""Build observation-only provisional monthly state averages from daily HYRAS.

Output is kept separate from final DWD monthly regional averages. No forecasts,
no extrapolation, and no replacement of finalized historic monthly values.
"""
from __future__ import annotations

import argparse
import calendar
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

from build_hyras_tmean_regions import build_masks, load_states
from update_hyras_maps import grid_xy, pick_precip_var, time_dim

COMBINED = {
    "Brandenburg/Berlin": ("Brandenburg", "Berlin"),
    "Niedersachsen/Hamburg/Bremen": ("Niedersachsen", "Hamburg", "Bremen"),
    "Thüringen/Sachsen-Anhalt": ("Thüringen", "Sachsen-Anhalt"),
}
# The monthly DWD dataset contains separate and combined territorial series.
ALIASES = {"Baden-Wuerttemberg": "Baden-Württemberg", "Thueringen": "Thüringen"}


def dates_for_month(year: int, month: int, through: str) -> list[str]:
    last = date.fromisoformat(through)
    if (last.year, last.month) != (year, month):
        raise ValueError("Cutoff date must belong to selected current month")
    return [date(year, month, d).isoformat() for d in range(1, last.day + 1)]


def build(root: Path, work: Path) -> dict:
    tmean_idx = json.loads((root / "tmean/regions/index.json").read_text(encoding="utf-8"))
    year = int(tmean_idx["year"])
    tmean_file = root / "tmean/regions" / tmean_idx["current_file"]
    tmean = json.loads(tmean_file.read_text(encoding="utf-8"))
    rain_idx = json.loads((root / "hyras_index.json").read_text(encoding="utf-8"))
    rain_file = work / rain_idx["daily_source_file"]
    if not rain_file.exists():
        raise FileNotFoundError("HYRAS precipitation NetCDF missing: " + str(rain_file))

    # Only publish the last common, fully observed day, never a future day.
    through = min(str(tmean["data_through"]), str(rain_idx["data_through"]),
                  (date.today() - timedelta(days=1)).isoformat())
    cutoff = date.fromisoformat(through)
    month = cutoff.month
    dates = dates_for_month(year, month, through)
    indices = {d: i for i, d in enumerate(tmean["dates"])}
    if any(d not in indices for d in dates):
        raise ValueError("Daily HYRAS temperature series contains gaps in current month")
    if len(tmean["dates"]) != len(set(tmean["dates"])):
        raise ValueError("Duplicate dates in HYRAS temperature data")

    results = {}
    for name, series in tmean["regions"].items():
        vals = [series[indices[d]] for d in dates]
        if any(v is None or not np.isfinite(float(v)) for v in vals):
            continue
        results[name] = {"temp": round(float(np.mean(vals)), 2)}

    with xr.open_dataset(rain_file, decode_times=True) as ds:
        da = pick_precip_var(ds).squeeze(drop=True)
        td = time_dim(da)
        ydim, xdim = [dim for dim in da.dims if dim != td]
        da = da.transpose(td, ydim, xdim)
        x, y = grid_xy(da)
        masks = build_masks(load_states(work), x, y)
        iso = [str(d) for d in da[td].values.astype("datetime64[D]")]
        positions = {d: i for i, d in enumerate(iso)}
        if any(d not in positions for d in dates) or len(iso) != len(positions):
            raise ValueError("Daily HYRAS precipitation series has gaps/duplicate dates")
        arr = np.asarray(da.isel({td: [positions[d] for d in dates]}).values, dtype=np.float32)

    if arr.shape[1:] != next(iter(masks.values())).shape:
        raise ValueError("HYRAS region masks do not fit precipitation grid")
    if np.nanmin(arr) < -1e-3:
        raise ValueError("Negative HYRAS precipitation values detected")
    # Sum along time per cell and average over the union of geographical cells.
    valid = np.isfinite(arr) & (arr >= 0)
    complete = valid.all(axis=0)
    totals = np.where(valid, arr, 0).sum(axis=0)
    for name, mask in masks.items():
        selected = mask & complete
        coverage = selected.sum() / max(1, int(mask.sum()))
        if coverage < 0.9:
            continue
        if name not in results:
            results[name] = {}
        results[name]["rain"] = round(float(totals[selected].mean()), 2)
    for combined, parts in COMBINED.items():
        mask = np.logical_or.reduce([masks[p] for p in parts])
        selected = mask & complete
        if selected.sum() / max(1, int(mask.sum())) >= 0.9:
            results[combined] = {"rain": round(float(totals[selected].mean()), 2)}
        # Temperature: weight daily state means by valid HYRAS grid-cell counts.
        counts = np.array([masks[p].sum() for p in parts], dtype=float)
        if all(p in results and "temp" in results[p] for p in parts):
            results.setdefault(combined, {})["temp"] = round(float(np.average([results[p]["temp"] for p in parts], weights=counts)), 2)
    for name, target in ALIASES.items():
        if target in results:
            results[name] = dict(results[target])

    # Sunshine comes from a separate station-based daily source, never from HYRAS.
    return {
        "schema": 1,
        "month": f"{year:04d}-{month:02d}",
        "data_through": through,
        "days_observed": len(dates),
        "days_in_month": calendar.monthrange(year, month)[1],
        "source": {"temp": "DWD HYRAS-DE TAS 1 km", "rain": "DWD HYRAS-DE PR 1 km"},
        "method": "Daily spatial region mean: arithmetic mean for temperature, sum of daily spatial means for precipitation.",
        "complete": False,
        "forecast": False,
        "areas": results,
    }


def valid_snapshot(payload: object) -> bool:
    """Accept only a coherent real-observation snapshot."""
    if not isinstance(payload, dict):
        return False
    month = payload.get("month")
    through = payload.get("data_through")
    return (
        payload.get("schema") == 1
        and payload.get("forecast") is False
        and isinstance(month, str) and len(month) == 7
        and isinstance(through, str) and through[:7] == month
        and isinstance(payload.get("areas"), dict)
        and bool(payload["areas"])
    )


def persist_provisional(root: Path, payload: dict) -> None:
    """Keep recent provisional months until DWD publishes their monthly values.

    The HYRAS job starts each run by copying the existing hyras-data branch.
    Read the old snapshot *before* replacing it, so the November/December
    boundary never discards November's still-unpublished observations.
    """
    if not valid_snapshot(payload):
        raise ValueError("Invalid current-month observation payload")

    current_path = root / "monthly_current_provisional.json"
    archive_path = root / "monthly_provisional_history.json"
    records: list[dict] = []
    if archive_path.exists():
        try:
            previous_archive = json.loads(archive_path.read_text(encoding="utf-8"))
            if previous_archive.get("schema") == 1:
                records.extend(previous_archive.get("months", []))
        except (ValueError, TypeError, AttributeError):
            pass
    if current_path.exists():
        try:
            records.append(json.loads(current_path.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            pass
    records.append(payload)

    by_month: dict[str, dict] = {}
    for item in records:
        if not valid_snapshot(item):
            continue
        month = item["month"]
        old = by_month.get(month)
        # Prefer a later cutoff; at equal cutoff prefer snapshots enriched with
        # station sunshine (the sunshine pipeline runs after the HYRAS builder).
        if old is None or item["data_through"] > old["data_through"] or (
            item["data_through"] == old["data_through"]
            and sum(len(v) for v in item["areas"].values() if isinstance(v, dict))
            >= sum(len(v) for v in old["areas"].values() if isinstance(v, dict))
        ):
            by_month[month] = item

    # 24 months is ample for a delayed official data release, including January.
    months = [by_month[k] for k in sorted(by_month)[-24:]]
    archive = {
        "schema": 1,
        "forecast": False,
        "source": "DWD HYRAS observations; final DWD monthly values take precedence",
        "months": months,
    }

    def save_atomic(path: Path, data: dict) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)

    # First preserve history. A partial failure must not destroy the old months.
    save_atomic(archive_path, archive)
    save_atomic(current_path, payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("/tmp/hyras-data"))
    parser.add_argument("--work", type=Path, default=Path("/tmp/hyras-work"))
    args = parser.parse_args()
    out = build(args.data_root, args.work)
    persist_provisional(args.data_root, out)
    print("Vorläufige Monats-Gebietsmittel:", out["month"], out["data_through"], len(out["areas"]), "Gebiete")


if __name__ == "__main__":
    main()
