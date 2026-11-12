#!/usr/bin/env python3
"""Regional daily HYRAS-DE-PR climatology for 1991–2020, from existing 2-km cache.

The existing dashboard's HYRAS daily-reference cache is made from all 30
official DWD annual 1-km grids, subsampled by 2 for web visualizations.
This script spatially averages each of the 366 already-calculated day-of-year
rasters over Germany and each Bundesland, with at least 90% valid coverage.

IMPORTANT: For Feb 29 the underlying climatology contains only leap years.
This is NOT a 1/30 weighted leap-day monthly baseline. Use actual calendar
dates when plotting, never blindly map day-of-year index across leap years.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from build_hyras_tmean_regions import EXPECTED_STATES, build_masks, load_states

REGIONS = ("Deutschland", *EXPECTED_STATES)
MIN_COVERAGE = 0.90
REFERENCE = "1991-2020"
EXPECTED_CACHE_NAME = "hyras_daily_reference_1991_2020_web2_v1.npz"


def load_reference(cache_file: Path):
    if not cache_file.exists():
        raise FileNotFoundError(
            f"HYRAS 1991–2020 daily reference cache is missing: {cache_file}. "
            "Restore the existing GitHub Actions HYRAS cache; do not invent days "
            "from monthly normals."
        )
    with np.load(cache_file, allow_pickle=False) as npz:
        for key in ("daily_mean", "months", "days", "x", "y", "crs"):
            if key not in npz.files:
                raise ValueError(f"HYRAS daily cache missing required array {key}")
        dates = list(zip(npz["months"].astype(int).tolist(), npz["days"].astype(int).tolist()))
        x, y = np.asarray(npz["x"], dtype=float), np.asarray(npz["y"], dtype=float)
        crs = str(np.asarray(npz["crs"]).item())
        if crs not in ("EPSG:3035", "ETRS89-extended / LAEA Europe"):
            raise ValueError(f"Unexpected HYRAS projected CRS: {crs}")
        if not (x.ndim == y.ndim == 1 and np.isfinite(x).all() and np.isfinite(y).all()):
            raise ValueError("Invalid HYRAS projected coordinates")
        if len(x)<100 or len(y)<100:
            raise ValueError("Unexpectedly small HYRAS grid")
        grid = np.asarray(npz["daily_mean"], dtype=np.float32)
    if grid.shape != (366, len(y), len(x)):
        raise ValueError(f"Daily reference grid has invalid shape: {grid.shape}")
    expected = [(month, day) for month in range(1,13)
                for day in range(1, calendar.monthrange(2000, month)[1]+1)]
    if dates != expected:
        raise ValueError("HYRAS daily cache calendar is incomplete or out of order")
    if np.nanmax(grid)>800 or np.nanmin(grid)<-0.001:
        raise ValueError("Unphysical daily HYRAS precipitation in climatology")
    return grid, x, y, dates


def region_daily_series(grid: np.ndarray, masks: dict[str, np.ndarray], *,
                        minimum_coverage: float = MIN_COVERAGE):
    """Return area-weighted daily means, independently requiring 90% per day."""
    if grid.ndim != 3:
        raise ValueError("Expected [day,y,x] daily climate raster")
    result={}
    for name in REGIONS:
        mask=masks[name]
        if mask.shape!=grid.shape[1:] or not mask.any():
            raise ValueError(f"HYRAS reference mask does not fit: {name}")
        values=grid[:,mask]
        good=np.isfinite(values)&(values>=0)
        fractions=good.sum(axis=1)/values.shape[1]
        if np.any(fractions<minimum_coverage):
            first=int(np.flatnonzero(fractions<minimum_coverage)[0])
            raise ValueError(f"HYRAS 1991-2020 reference {name} too sparse on day index {first}: {fractions[first]:.1%}")
        daily=np.nansum(np.where(good,values,0.0),axis=1)/good.sum(axis=1)
        if not np.all(np.isfinite(daily)):
            raise ValueError(f"Invalid daily reference values: {name}")
        result[name]=daily.astype(float).tolist()
    return result


def build_payload(series: dict[str,list[float]], monthly: dict) -> dict:
    if monthly.get("reference_period") != REFERENCE or "months" not in monthly:
        raise ValueError("Expected official HYRAS monthly normals for 1991-2020")
    expected_dates=[(month, day) for month in range(1,13)
                    for day in range(1,calendar.monthrange(2000,month)[1]+1)]
    if set(series)!=set(REGIONS) or any(len(vals)!=366 for vals in series.values()):
        raise ValueError("All 17 regions need 366 historical daily normal values")
    months={}
    for month in range(1,13):
        key=f"{month:02d}"
        dates=[f"{m:02d}-{day:02d}" for m,day in expected_dates if m==month]
        indices=[i for i,(m,_) in enumerate(expected_dates) if m==month]
        regions={}
        for name in REGIONS:
            daily=[float(series[name][i]) for i in indices]
            if any(not math.isfinite(v) or v<0 or v>100 for v in daily):
                raise ValueError(f"Invalid daily normal: {name} {key}")
            running=np.cumsum(daily)
            actual=monthly["months"][key]["precipitation"][name]["month_total"]
            if not isinstance(actual,(int,float)) or actual<=0:
                raise ValueError(f"Invalid official 1991-2020 normal: {name} {key}")
            # In leap February the 29-day sum is not directly equivalent to
            # the DWD mean calendar-month total (30-year mixture of 28/29 days).
            comparable=float(running[-1] - (daily[-1]*22/30 if month==2 else 0))
            relative_difference=(comparable/actual-1)
            if abs(relative_difference)>0.20:
                raise ValueError(
                    f"Reference 2-km daily sum vs official 1-km monthly "
                    f"normal disagrees by {relative_difference:.1%} in {name}/{key}"
                )
            regions[name]={
                "daily_mm":[round(value,4) for value in daily],
                "running_mm":[round(float(value),3) for value in running],
                "official_month_total_mm":round(float(actual),3),
                "difference_vs_official_pct":round(relative_difference*100,2),
            }
        months[key]={"dates":dates,"regions":regions}
    return {
        "schema_version":1,
        "product":"state_monthly_daily_precip_climatology",
        "parameter":"precipitation",
        "reference_period":REFERENCE,
        "unit":"mm",
        "generated_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "regions_order":list(REGIONS),
        "months":months,
        "daily_climatology_available":True,
        "underlying_data":"DWD HYRAS-DE-PRE 1991–2020 daily reference grids, existing website web-factor=2 cache (approx. 2-km spatial resolution)",
        "method":"For each calendar day: mean of historical daily cell values 1991–2020, then regional equal-area grid mean; >90% region valid cells daily; cumulative sums from 01 of month.",
        "leap_day_note":"02-29 is an average of historical leap years only. The 29-day February reference is not directly comparable with a 30-year mixture of leap and non-leap monthly totals.",
        "spatial_comparability_note":"Historical daily references use a 2-km web raster. The separately published official monthly normals are 1-km; small differences at month end can occur. No monthly climatology values were distributed evenly into invented daily values.",
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cache",type=Path,required=True)
    p.add_argument("--monthly",type=Path,required=True)
    p.add_argument("--work",type=Path,default=Path("/tmp/monthly-daily-reference-work"))
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    args.work.mkdir(parents=True,exist_ok=True)
    grid,x,y,_=load_reference(args.cache)
    masks=build_masks(load_states(args.work),x,y)
    series=region_daily_series(grid,masks)
    monthly=json.loads(args.monthly.read_text(encoding="utf-8"))
    payload=build_payload(series,monthly)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print("Daily HYRAS climate 1991–2020:",len(payload["months"]),"months,",
          len(payload["regions_order"]),"regions,",
          "November DE",payload["months"]["11"]["regions"]["Deutschland"]["running_mm"][-1],"mm",
          "February leap-year reference available",flush=True)


if __name__=="__main__":
    main()
