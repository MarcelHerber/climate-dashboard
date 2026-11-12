#!/usr/bin/env python3
"""Publish regional daily HYRAS-DE-PRE observations for the monthly outlook.

Runs in the existing HYRAS job, reusing its *already downloaded* annual
precipitation NetCDF and geographical masks.  No forecast is generated here.
Missing or incompletely covered days fail closed rather than becoming zero.
"""
from __future__ import annotations

import argparse
import calendar
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

from build_hyras_tmean_regions import EXPECTED_STATES, build_masks, load_states
from update_hyras_maps import grid_xy, pick_precip_var, time_dim

REGIONS = ("Deutschland", *EXPECTED_STATES)
MIN_COVERAGE = 0.9


def daily_area_mean(field: np.ndarray, mask: np.ndarray, threshold: float = MIN_COVERAGE) -> tuple[float | None, float]:
    """Return (mm per day, coverage) for equal-area projected HYRAS cells."""
    values = np.asarray(field, dtype=np.float64)
    area = np.asarray(mask, dtype=bool)
    if values.shape != area.shape or not area.any():
        raise ValueError("HYRAS grid/mask mismatch or empty region")
    valid = area & np.isfinite(values) & (values >= 0)
    coverage = int(valid.sum()) / int(area.sum())
    if coverage < threshold:
        return None, round(coverage, 5)
    return round(float(values[valid].mean()), 4), round(coverage, 5)


def month_days(cutoff: date) -> list[str]:
    return [date(cutoff.year, cutoff.month, d).isoformat() for d in range(1, cutoff.day + 1)]


def build(root: Path, work: Path, threshold: float = MIN_COVERAGE) -> dict:
    index = json.loads((root / "hyras_index.json").read_text(encoding="utf-8"))
    source_file = work / index["daily_source_file"]
    if not source_file.is_file():
        raise FileNotFoundError(f"HYRAS precipitation NetCDF not present: {source_file}")
    cutoff = date.fromisoformat(index["data_through"])
    if cutoff > datetime.now(timezone.utc).date():
        raise ValueError("HYRAS reports a future observation day")
    days = month_days(cutoff)
    masks = None
    areas = {region: [] for region in REGIONS}
    coverage_by_area = {region: [] for region in REGIONS}
    with xr.open_dataset(source_file, decode_times=True) as ds:
        da = pick_precip_var(ds).squeeze(drop=True)
        td = time_dim(da)
        ydim, xdim = [dim for dim in da.dims if dim != td]
        da = da.transpose(td, ydim, xdim)
        x, y = grid_xy(da)
        masks = build_masks(load_states(work), x, y)
        if any(region not in masks for region in REGIONS):
            raise ValueError("Not all 17 HYRAS region masks are available")
        time_values = [str(day) for day in da[td].values.astype("datetime64[D]")]
        if len(time_values) != len(set(time_values)):
            raise ValueError("Duplicate HYRAS precipitation dates")
        positions = {day: i for i, day in enumerate(time_values)}
        missing = [day for day in days if day not in positions]
        if missing:
            raise ValueError(f"HYRAS precipitation days missing: {missing[:4]}")
        for day in days:
            field = np.asarray(da.isel({td: positions[day]}).values, dtype=np.float32)
            for region in REGIONS:
                value, cov = daily_area_mean(field, masks[region], threshold)
                areas[region].append(value)
                coverage_by_area[region].append(cov)

    # Cannot anchor an ensemble forecast to an incomplete observation total.
    incomplete = [f"{r}: {days[i]}" for r in REGIONS for i, v in enumerate(areas[r]) if v is None]
    if incomplete:
        raise ValueError("HYRAS area observation incomplete: " + ", ".join(incomplete[:8]))
    return {
        "schema_version": 1,
        "product": "monthly_outlook_hyras_precipitation_observations",
        "source": "DWD HYRAS-DE-PRE daily 1km",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "month": f"{cutoff.year:04d}-{cutoff.month:02d}",
        "data_through": cutoff.isoformat(),
        "days_in_month": calendar.monthrange(cutoff.year, cutoff.month)[1],
        "dates": days,
        "unit": "mm",
        "regions_order": list(REGIONS),
        "regions": {
            region: {
                "daily": areas[region],
                "running": [round(float(sum(areas[region][:i+1])), 3) for i in range(len(days))],
                "minimum_coverage": round(min(coverage_by_area[region]), 4),
            }
            for region in REGIONS
        },
        "complete": len(days) == calendar.monthrange(cutoff.year, cutoff.month)[1],
        "forecast": False,
        "method": "Equal-area arithmetic regional mean of daily HYRAS precipitation in EPSG:3035; consecutive observed days only.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, default=Path("/tmp/hyras-data"))
    ap.add_argument("--work", type=Path, default=Path("/tmp/hyras-work"))
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()
    payload = build(args.data_root, args.work)
    target = args.output or args.data_root / "monthly_outlook/observed_precip.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(target)
    print(f"Monatsausblick HYRAS-Niederschlag: {payload['month']} bis {payload['data_through']} · {len(payload['regions'])} Gebiete")


if __name__ == "__main__":
    main()
