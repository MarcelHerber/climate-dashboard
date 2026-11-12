#!/usr/bin/env python3
"""Official DWD 1991–2020 monthly normals for DE and all 16 states.

Precipitation: HYRAS-DE-PR v6.1 monthly reference NetCDF, EPSG:3035.
Sunshine: DWD CDC monthly sunshine 1991-2020 ESRI-ASCII, EPSG:31467.
Both are historical *monthly totals*, not daily climatological trajectories.
The historical sunshine station interpolation is methodologically different
from the current DUETT satellite+stations product.
"""
from __future__ import annotations

import argparse
import calendar
import gzip
import io
import json
import math
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
import xarray as xr
from pyproj import Transformer

from build_hyras_tmean_regions import EXPECTED_STATES, geometry_mask, load_states, build_masks
from update_hyras_maps import grid_xy, pick_precip_var

PRECIP_URL = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/precipitation/"
SUN_URL = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/sunshine_duration/"
SUN_FILE = "grids_germany_multi_annual_sunshine_duration_1991-2020_{month:02d}.asc.gz"
MONTH_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
REGIONS = ("Deutschland", *EXPECTED_STATES)
UA = "climate-dashboard-monthly-reference/1.0 (DWD CDC)"
MIN_COVERAGE = 0.90


def download(url: str, cache: Path) -> Path:
    """Cache finite binary downloads and fail clearly on partial responses."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and cache.stat().st_size > 10000:
        return cache
    response = requests.get(url, timeout=180, headers={"User-Agent": UA})
    response.raise_for_status()
    if len(response.content) < 10000:
        raise RuntimeError(f"Suspect empty DWD file at {url}")
    tmp = cache.with_name(cache.name + ".tmp")
    tmp.write_bytes(response.content)
    tmp.replace(cache)
    return cache


def precipitation_filename(listing: str, month: int) -> str:
    """Prefer DWD 1991–2020 HYRAS v6.1; never pick another normal period."""
    abbr = MONTH_ABBR[month - 1]
    pattern = re.compile(
        rf'href="(pr_hyras_1_1991_2020_v(\d+)-(\d+)_de_{abbr}\.nc)"'
    )
    matches = [(int(major), int(minor), name)
               for name, major, minor in pattern.findall(listing)]
    if not matches:
        raise RuntimeError(f"1991–2020 HYRAS precipitation reference missing: {abbr}")
    return max(matches)[2]


def ascii_grid(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read fixed-width or whitespace-separated ESRI-ASCII gzip, north-first.

    Monthly DWD CDC sunshine files are 654 x 866 cells in EPSG:31467,
    and may contain compact 4-character numbers without separators.
    """
    with gzip.open(path, "rt", encoding="ascii", errors="strict") as f:
        header = {}
        for _ in range(6):
            line = f.readline().strip().split()
            if len(line) != 2:
                raise ValueError(f"Unexpected ESRI-ASCII header in {path.name}: {line!r}")
            header[line[0].lower()] = float(line[1])
        ncols = int(header["ncols"])
        nrows = int(header["nrows"])
        step = float(header["cellsize"])
        if ncols != 654 or nrows != 866 or step != 1000:
            raise ValueError(f"Unexpected DWD sunshine grid dimensions: {ncols}x{nrows}, step={step}")
        if "xllcorner" in header:
            x0 = header["xllcorner"] + step / 2
        else:
            x0 = header["xllcenter"]
        if "yllcorner" in header:
            y0 = header["yllcorner"] + step / 2
        else:
            y0 = header["yllcenter"]
        no_data = float(header.get("nodata_value", -999))
        data = np.empty((nrows, ncols), dtype=np.float32)
        for j in range(nrows):
            row = f.readline().strip()
            if not row:
                raise ValueError(f"Missing sunshine raster row {j+1}/{nrows}")
            parsed = np.fromstring(row, sep=" ", dtype=np.float32)
            if len(parsed) != ncols:
                compact = "".join(row.split())
                if len(compact) != ncols * 4:
                    raise ValueError(f"Unrecognized DWD fixed-width sunshine row {j+1}: {len(compact)} characters")
                parsed = np.asarray([float(compact[i:i+4])
                                     for i in range(0, len(compact), 4)], dtype=np.float32)
            data[j] = parsed
        if f.read().strip():
            raise ValueError("Unexpected trailing ESRI-ASCII raster content")
    x = x0 + np.arange(ncols, dtype=np.float64) * step
    y = y0 + np.arange(nrows - 1, -1, -1, dtype=np.float64) * step
    data[~np.isfinite(data) | np.isclose(data, no_data) | (data < 0)] = np.nan
    if not (math.isfinite(float(np.nanmean(data))) and 0 <= float(np.nanmax(data)) <= 550):
        raise ValueError("Unphysical 1991–2020 sunshine monthly hours")
    return x, y, data


def area_total(grid: np.ndarray, masks: dict[str, np.ndarray]) -> dict[str, dict]:
    result = {}
    for name in REGIONS:
        mask = masks[name]
        if mask.shape != grid.shape or not mask.any():
            raise ValueError(f"Raster/mask mismatch: {name}")
        valid = mask & np.isfinite(grid) & (grid >= 0)
        coverage = float(valid.sum() / mask.sum())
        if coverage < MIN_COVERAGE:
            raise ValueError(f"DWD reference low coverage {name}: {coverage:.1%}")
        result[name] = {"month_total": round(float(grid[valid].mean()), 3),
                        "coverage": round(coverage, 4)}
    return result


def sun_masks(features: dict, x: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
    transformer = Transformer.from_crs(4326, 31467, always_xy=True)
    result = {}
    combined = np.zeros((len(y), len(x)), dtype=bool)
    for region in EXPECTED_STATES:
        mask = geometry_mask(features[region]["geometry"], x, y, transformer)
        if int(mask.sum()) < 5:
            raise ValueError(f"Insufficient GK3 1-km cells in {region}")
        result[region] = mask
        combined |= mask
    return {"Deutschland": combined, **result}


def reference_month(month: int, cache_root: Path, features: dict, precip_listing: str,
                    state: dict) -> dict:
    abbr = MONTH_ABBR[month - 1]
    filename = precipitation_filename(precip_listing, month)
    nc_path = download(PRECIP_URL + filename, cache_root / filename)
    with xr.open_dataset(nc_path, mask_and_scale=True) as ds:
        field = pick_precip_var(ds).squeeze(drop=True)
        if field.ndim != 2:
            raise ValueError(f"HYRAS monthly reference not 2D: {field.dims}")
        # HYRAS spatial dims are y,x after reordering.
        ydim, xdim = field.dims[-2:]
        field = field.transpose(ydim, xdim)
        x, y = grid_xy(field)
        grid = np.asarray(field.values, dtype=np.float32)
        units = str(field.attrs.get("units", "")).lower()
        if not any(tag in units for tag in ("mm", "kg m-2", "kg/m2", "kg m**-2")):
            raise ValueError(f"Unrecognized HYRAS reference precipitation units: {units!r}")
        if not math.isfinite(float(np.nanmax(grid))) or np.nanmax(grid) > 5000:
            raise ValueError("Unphysical HYRAS monthly reference precipitation")
        masks = state.get("precip_masks")
        if masks is None:
            masks = build_masks(features, x, y)
            state["precip_masks"] = masks
            state["precip_x"], state["precip_y"] = x, y
        elif not np.array_equal(x, state["precip_x"]) or not np.array_equal(y, state["precip_y"]):
            raise ValueError("HYRAS monthly reference grid changed between months")
        rain = area_total(grid, masks)

    sunfile = SUN_FILE.format(month=month)
    sunpath = download(SUN_URL + sunfile, cache_root / sunfile)
    sx, sy, sunshine_grid = ascii_grid(sunpath)
    masks = state.get("sun_masks")
    if masks is None:
        masks = sun_masks(features, sx, sy)
        state["sun_masks"] = masks
        state["sun_x"], state["sun_y"] = sx, sy
    elif not np.array_equal(sx, state["sun_x"]) or not np.array_equal(sy, state["sun_y"]):
        raise ValueError("DWD monthly sunshine reference grid changed between months")
    sunshine = area_total(sunshine_grid, masks)
    return {
        "precipitation": rain,
        "sunshine": sunshine,
        "source_files": {"precipitation": filename, "sunshine": sunfile},
    }


def build(months: list[int], cache_root: Path, work: Path) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    features = load_states(work)
    listing = requests.get(PRECIP_URL, timeout=100, headers={"User-Agent": UA})
    listing.raise_for_status()
    state: dict = {}
    output = {}
    for month in months:
        if month < 1 or month > 12:
            raise ValueError("Months must be 1..12")
        output[f"{month:02d}"] = reference_month(month, cache_root, features, listing.text, state)
        print("Referenz 1991–2020 berechnet:", MONTH_ABBR[month-1],
              "Niederschlag", output[f"{month:02d}"]["precipitation"]["Deutschland"]["month_total"],
              "mm · Sonne", output[f"{month:02d}"]["sunshine"]["Deutschland"]["month_total"], "h", flush=True)
    return {
        "schema_version": 1,
        "product": "state_monthly_hydro_sun_climatology",
        "reference_period": "1991-2020",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "months": output,
        "regions_order": list(REGIONS),
        "parameter_meta": {
            "precipitation": {
                "unit": "mm", "source": "DWD HYRAS-DE-PR v6 monthly 1-km climate grid",
                "method": "1991-2020 mean monthly precipitation total, averaged across equal-area 1km cells (EPSG:3035)",
            },
            "sunshine": {
                "unit": "h", "source": "DWD CDC 1991–2020 monthly sunshine duration 1-km station-interpolated grid",
                "method": "1991–2020 mean monthly sunshine hours (EPSG:31467), not DUETT-specific reference",
                "comparability_note": "Station-interpolated historical climatology and current blended satellite+station DUETT are methodologically distinct.",
            },
        },
        "daily_climatology_available": False,
        "daily_reference_note": "Monthly normals do not specify a historical day-by-day cumulative curve; only the full-month reference is available.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", default="all", help="Comma-separated 1-12 or 'all'")
    ap.add_argument("--cache", type=Path, default=Path("/tmp/state-monthly-climate-cache"))
    ap.add_argument("--work", type=Path, default=Path("/tmp/state-monthly-climate-work"))
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    months = list(range(1, 13)) if args.months == "all" else sorted(set(int(x) for x in args.months.split(",")))
    out = build(months, args.cache, args.work)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("DWD 1991–2020 monthly climatologies ready:", len(out["months"]), "months")


if __name__ == "__main__":
    main()
