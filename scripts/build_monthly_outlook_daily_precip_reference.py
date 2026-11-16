#!/usr/bin/env python3
"""Regional daily HYRAS-DE-PR climatology for 30-year periods, from existing 2-km cache.

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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xarray as xr
from pyproj import CRS
import re

from build_hyras_tmean_regions import EXPECTED_STATES, build_masks, load_states
from build_monthly_outlook_climatology import SUPPORTED_REFERENCES, precipitation_filename
from update_hyras_maps import (DAILY_BASE, daily_file_map, detect_data_crs, directory_text,
                               download, pick_precip_var, sample_2d_for_web, sample_daily_for_web)

REGIONS = ("Deutschland", *EXPECTED_STATES)
MIN_COVERAGE = 0.90
REFERENCE = "1991-2020"
EXPECTED_CACHE_NAME = "hyras_daily_reference_1991_2020_web2_v1.npz"


def monthly_grid_coordinates(monthly_grid_dir: Path, reference_period: str):
    """Read the matching official monthly HYRAS grid and apply web sampling.

    Read a downloaded official NetCDF rather than guessing grid origins.
    Every annual source is compared with this exact grid before accumulation.
    """
    listing = "\n".join(f'<a href="{p.name}">' for p in monthly_grid_dir.glob("*.nc"))
    filename = precipitation_filename(listing, 1, reference_period)
    with xr.open_dataset(monthly_grid_dir / filename, mask_and_scale=True) as ds:
        field = pick_precip_var(ds).squeeze(drop=True)
        if field.ndim != 2:
            raise ValueError("HYRAS monthly reference must be 2D")
        crs = detect_data_crs(ds, field).to_string()
        _, x, y = sample_2d_for_web(field, 2)
    if not (np.allclose(np.diff(x), 2000) and np.allclose(np.diff(y), -2000)):
        raise ValueError("Expected sampled 2-km HYRAS grid coordinates")
    return x, y, crs


def cache_name(reference_period: str) -> str:
    version = 2 if reference_period == "1961-1990" else 1
    return f"hyras_daily_reference_{reference_period.replace('-', '_')}_web2_v{version}.npz"


def validated_annual_sample(path: Path, year: int, expected_x: np.ndarray,
                            expected_y: np.ndarray):
    """Read one original DWD annual field and prove its grid and dates."""
    with xr.open_dataset(path, decode_times=True, mask_and_scale=True) as ds:
        field = pick_precip_var(ds)
        units = str(field.attrs.get("units", "")).lower()
        if not any(tag in units for tag in ("mm", "kg m-2", "kg/m2", "kg m**-2")):
            raise ValueError(f"Unrecognized HYRAS precipitation units: {units!r}")
        if detect_data_crs(ds, field).to_epsg() != 3035:
            raise ValueError(f"Unexpected HYRAS CRS in {path.name}")
        values, dates, x, y = sample_daily_for_web(field, 2)
    if not np.array_equal(x, expected_x) or not np.array_equal(y, expected_y):
        raise ValueError(f"HYRAS source grid differs from monthly reference: {path.name}")
    first = date(year, 1, 1)
    expected = [(first + timedelta(days=i)).isoformat()
                for i in range(366 if calendar.isleap(year) else 365)]
    if dates != expected or values.shape != (len(expected), len(y), len(x)):
        raise ValueError(f"Incomplete or misordered HYRAS daily calendar: {path.name}")
    if np.any(values[np.isfinite(values)] > 800):
        raise ValueError(f"Unphysical HYRAS daily precipitation: {path.name}")
    return values, dates


def build_verified_cache(cache_file: Path, monthly_grid_dir: Path, work: Path):
    """Build the old-period v2 cache from all 30 validated original annual grids."""
    reference_period = "1961-1990"
    if cache_file.name != cache_name(reference_period):
        raise ValueError("Refusing to write a verified cache under a different reference name")
    if cache_file.exists():
        return
    x, y, crs = monthly_grid_coordinates(monthly_grid_dir, reference_period)
    if CRS.from_user_input(crs).to_epsg() != 3035:
        raise ValueError("Expected EPSG:3035 monthly reference grid")
    md = [(m,d) for m in range(1,13) for d in range(1,calendar.monthrange(2000,m)[1]+1)]
    md_index = {item:i for i,item in enumerate(md)}
    shape = (len(md), len(y), len(x))
    sums = np.zeros(shape, dtype=np.float32)
    counts = np.zeros(shape, dtype=np.uint8)
    years = range(1961,1991)
    source_files = daily_file_map(directory_text(DAILY_BASE + "/"), years)
    source_root = work / "original_daily"
    source_root.mkdir(parents=True, exist_ok=True)
    for year in years:
        name = source_files[year]
        path = source_root / name
        if not path.exists():
            partial = path.with_suffix(".nc.part")
            download(f"{DAILY_BASE}/{name}", partial)
            partial.replace(path)
        values, dates = validated_annual_sample(path,year,x,y)
        for i, iso in enumerate(dates):
            day = date.fromisoformat(iso)
            j = md_index[(day.month,day.day)]
            good = np.isfinite(values[i]) & (values[i] >= 0)
            sums[j][good] += values[i][good]
            counts[j][good] += 1
        del values
        path.unlink()
        print(f"Verified HYRAS 1961–1990: {year-1960}/30 source years",flush=True)
    samples_needed = np.array([7 if (m,d)==(2,29) else 30 for m,d in md],dtype=np.float32)
    min_samples = np.ceil(samples_needed * 0.9).astype(np.uint8)
    daily_mean = np.divide(sums,counts,out=np.full(shape,np.nan,dtype=np.float32),
                          where=counts >= min_samples[:,None,None])
    cache_file.parent.mkdir(parents=True,exist_ok=True)
    partial_cache = cache_file.with_suffix(".npz.part")
    with partial_cache.open("wb") as f:
        np.savez_compressed(f, daily_mean=daily_mean,
                            months=[m for m,d in md], days=[d for m,d in md],
                            x=x, y=y, crs=crs, reference_period=reference_period,
                            method_version=2, source_files=[source_files[year] for year in years])
    partial_cache.replace(cache_file)


def load_reference(cache_file: Path, reference_period: str = REFERENCE,
                   monthly_grid_dir: Path | None = None):
    if reference_period not in SUPPORTED_REFERENCES:
        raise ValueError(f"Unsupported reference period: {reference_period}")
    if not cache_file.exists():
        raise FileNotFoundError(
            f"HYRAS {reference_period} daily reference cache is missing: {cache_file}. "
            "Restore the existing GitHub Actions HYRAS cache; do not invent days "
            "from monthly normals."
        )
    expected_name = cache_name(reference_period)
    if cache_file.name != expected_name:
        raise ValueError(f"Unexpected daily reference cache filename: {cache_file.name}; expected {expected_name}")
    with np.load(cache_file, allow_pickle=False) as npz:
        for key in ("daily_mean", "months", "days", "x", "y", "crs"):
            if key not in npz.files:
                raise ValueError(f"HYRAS daily cache missing required array {key}")
        dates = list(zip(npz["months"].astype(int).tolist(), npz["days"].astype(int).tolist()))
        x, y = np.asarray(npz["x"], dtype=float), np.asarray(npz["y"], dtype=float)
        crs = str(np.asarray(npz["crs"]).item())
        if reference_period == "1961-1990":
            if not all(k in npz.files for k in ("reference_period","method_version","source_files")):
                raise ValueError("Unverified HYRAS 1961–1990 cache")
            if str(npz["reference_period"].item()) != reference_period or int(npz["method_version"].item()) != 2:
                raise ValueError("Incorrect HYRAS cache period or method")
            source_files = npz["source_files"].tolist()
            if len(source_files) != 30 or any(
                not re.fullmatch(rf"pr_hyras_1_{year}_v\d+-\d+_de\.nc", str(name))
                for year,name in zip(range(1961,1991), source_files)
            ):
                raise ValueError("HYRAS verified provenance must contain all source years")
            if monthly_grid_dir is not None:
                expected_x,expected_y,_ = monthly_grid_coordinates(monthly_grid_dir,reference_period)
                if not np.array_equal(x,expected_x) or not np.array_equal(y,expected_y):
                    raise ValueError("HYRAS cache grid differs from official monthly reference")
        if CRS.from_user_input(crs).to_epsg() != 3035:
            raise ValueError(f"Unexpected HYRAS projected CRS: {crs}")
        if not (x.ndim == y.ndim == 1 and np.isfinite(x).all() and np.isfinite(y).all()):
            raise ValueError("Invalid HYRAS projected coordinates")
        if len(x)<100 or len(y)<100:
            raise ValueError("Unexpectedly small HYRAS grid")
        if not (np.allclose(np.diff(x), 2000) and np.allclose(np.diff(y), -2000)):
            raise ValueError("HYRAS daily cache is not an oriented 2-km grid")
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
            raise ValueError(f"HYRAS reference {name} too sparse on day index {first}: {fractions[first]:.1%}")
        daily=np.nansum(np.where(good,values,0.0),axis=1)/good.sum(axis=1)
        if not np.all(np.isfinite(daily)):
            raise ValueError(f"Invalid daily reference values: {name}")
        result[name]=daily.astype(float).tolist()
    return result


def build_payload(series: dict[str,list[float]], monthly: dict,
                  reference_period: str = REFERENCE) -> dict:
    if reference_period not in SUPPORTED_REFERENCES:
        raise ValueError(f"Unsupported reference period: {reference_period}")
    if monthly.get("reference_period") != reference_period or "months" not in monthly:
        raise ValueError(f"Expected official HYRAS monthly normals for {reference_period}")
    start, end = map(int, reference_period.split("-"))
    non_leap_fraction = sum(not calendar.isleap(year) for year in range(start, end+1)) / (end-start+1)
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
                raise ValueError(f"Invalid official {reference_period} normal: {name} {key}")
            # In leap February the 29-day sum is not directly equivalent to
            # the DWD mean calendar-month total (30-year mixture of 28/29 days).
            comparable=float(running[-1] - (daily[-1]*non_leap_fraction if month==2 else 0))
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
        "reference_period":reference_period,
        "unit":"mm",
        "generated_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "regions_order":list(REGIONS),
        "months":months,
        "daily_climatology_available":True,
        "underlying_data":f"DWD HYRAS-DE-PRE {reference_period} daily reference grids, existing website web-factor=2 cache (approx. 2-km spatial resolution)",
        "method":f"For each calendar day: mean of historical daily cell values {reference_period}, then regional equal-area grid mean; >90% region valid cells daily; cumulative sums from 01 of month.",
        "leap_day_note":"02-29 is an average of historical leap years only. The 29-day February reference is not directly comparable with a 30-year mixture of leap and non-leap monthly totals.",
        "spatial_comparability_note":"Historical daily references use a 2-km web raster. The separately published official monthly normals are 1-km; small differences at month end can occur. No monthly climatology values were distributed evenly into invented daily values.",
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cache",type=Path,required=True)
    p.add_argument("--reference-period",choices=SUPPORTED_REFERENCES,default=REFERENCE)
    p.add_argument("--monthly-grid-dir",type=Path,help="DWD monthly NetCDF cache directory for verified 1961–1990 georeferencing")
    p.add_argument("--build-cache",action="store_true",help="Build a validated 1961–1990 daily cache from all 30 original annual DWD files if absent")
    p.add_argument("--monthly",type=Path,required=True)
    p.add_argument("--work",type=Path,default=Path("/tmp/monthly-daily-reference-work"))
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    args.work.mkdir(parents=True,exist_ok=True)
    if args.build_cache:
        if args.reference_period != "1961-1990" or args.monthly_grid_dir is None:
            p.error("--build-cache requires --reference-period 1961-1990 and --monthly-grid-dir")
        build_verified_cache(args.cache,args.monthly_grid_dir,args.work)
    grid,x,y,_=load_reference(args.cache,args.reference_period,args.monthly_grid_dir)
    masks=build_masks(load_states(args.work),x,y)
    series=region_daily_series(grid,masks)
    monthly=json.loads(args.monthly.read_text(encoding="utf-8"))
    payload=build_payload(series,monthly,args.reference_period)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(f"Daily HYRAS climate {args.reference_period}:",len(payload["months"]),"months,",
          len(payload["regions_order"]),"regions,",
          "November DE",payload["months"]["11"]["regions"]["Deutschland"]["running_mm"][-1],"mm",
          "February leap-year reference available",flush=True)


if __name__=="__main__":
    main()
