#!/usr/bin/env python3
"""Build hourly JSON chunks of 10-minute ECMWF MSLP forecast isolines.

The only meteorological inputs are verified IFS GRIB2 MSLP grids (hPa).
At each intermediate valid time, interpolate *grid-point pressures* linearly
between surrounding IFS steps, THEN recompute real 5-hPa contours and
separate Europe-only 2-hPa contour geometries.
No imaginary 10-minute ECMWF model output or satellite observations claimed.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np

UTC = dt.timezone.utc
TEN_MINUTES = 600
MODEL_STEPS_HOURS = (0, 3, 6, 9, 12, 15, 18)
PREFIX = "r"
MAX_HOURS = 18
# Crop derived contours only for viewer; don't change raw GRIB-based contours.
# Natural Earth/FCI geographic views span this range.
DISPLAY_BBOX = (-70.5, 14.5, 49.5, 75.5)
EUROPE_BBOX = (-37.5, 23.5, 49.5, 73.5)
FINE_REGIONS = ("europe", "southwest", "central", "germany")


def intersects(a, b, bbox=DISPLAY_BBOX):
    return (max(a[0], b[0]) >= bbox[0] and
            min(a[0], b[0]) <= bbox[2] and
            max(a[1], b[1]) >= bbox[1] and
            min(a[1], b[1]) <= bbox[3])


def cropped_runs(line, bbox=DISPLAY_BBOX):
    run = []
    for a, b in zip(line, line[1:]):
        if intersects(a, b, bbox):
            if not run:
                run = [a]
            run.append(b)
        elif len(run) >= 2:
            yield run
            run = []
        else:
            run = []
    if len(run) >= 2:
        yield run


def perpendicular_sq(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    if dx == 0 and dy == 0:
        return (p[0]-a[0])**2 + (p[1]-a[1])**2
    alpha = min(1.0, max(0.0, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return (p[0]-a[0]-alpha*dx)**2+(p[1]-a[1]-alpha*dy)**2


def simplify(points, tolerance=0.045):
    if len(points) <= 2:
        return [[round(x, 3), round(y, 3)] for x, y in points]
    keep = {0, len(points)-1}
    stack = [(0, len(points)-1)]
    limit = tolerance*tolerance
    while stack:
        start, end = stack.pop()
        farthest = -1.0
        index = None
        for i in range(start+1, end):
            d = perpendicular_sq(points[i], points[start], points[end])
            if d > farthest:
                farthest, index = d, i
        if farthest > limit and index is not None:
            keep.add(index)
            stack.extend(((start, index), (index, end)))
    return [[round(points[i][0], 3), round(points[i][1], 3)] for i in sorted(keep)]


def concise_contours(lons, lats, field, spacing=5, bbox=DISPLAY_BBOX):
    """Contour interpolated MSLP on the native grid, then compact SVG geometry."""
    import contourpy
    maker = contourpy.contour_generator(
        x=lons, y=lats, z=field, name="serial",
        line_type="Separate", corner_mask=False,
    )
    groups = []
    if spacing not in (2, 5):
        raise ValueError("Only authentic 2-hPa or 5-hPa pressure contours are supported")
    for hpa in range(900, 1071, spacing):
        paths = []
        for line in maker.lines(float(hpa)):
            if len(line) < 2:
                continue
            for cropped in cropped_runs(line, bbox=bbox):
                compact = simplify(cropped)
                if len(compact) >= 2:
                    paths.append(compact)
        if paths:
            groups.append({"hpa": hpa, "lines": paths})
    return groups


def interpolate_field(grids, forecast_minute):
    """Return pressure grid and strict source provenance; no extrapolation."""
    if forecast_minute < 0 or forecast_minute > MAX_HOURS*60 or forecast_minute % 10:
        raise ValueError("Outside supported 10-minute forecast interval")
    low_hour = 3*(forecast_minute//180)
    high_hour = min(MAX_HOURS, low_hour+3)
    if forecast_minute == MAX_HOURS*60:
        low_hour = high_hour = MAX_HOURS
    xa, ya, a = grids[low_hour]
    if high_hour == low_hour:
        return (xa, ya, a, (low_hour, high_hour), 0.0)
    xb, yb, b = grids[high_hour]
    if not (np.array_equal(xa, xb) and np.array_equal(ya, yb) and a.shape == b.shape):
        raise ValueError("Cannot interpolate incompatible MSLP model grids")
    fraction = (forecast_minute-low_hour*60)/((high_hour-low_hour)*60)
    if not 0 <= fraction <= 1:
        raise ValueError("Invalid interpolation fraction")
    pressure = np.asarray(a, dtype=float)*(1-fraction)+np.asarray(b, dtype=float)*fraction
    return (xa, ya, pressure, (low_hour, high_hour), fraction)


def frame_from_grids(grids, run, forecast_minute):
    x, y, pressure, source_steps, fraction = interpolate_field(grids, forecast_minute)
    if not (np.isfinite(pressure).all() and 800 <= float(np.min(pressure)) <= 1050
            and 950 <= float(np.max(pressure)) <= 1120):
        raise ValueError("Invalid interpolated MSLP values")
    contours = concise_contours(x, y, pressure, spacing=5)
    fine_contours = concise_contours(x, y, pressure, spacing=2, bbox=EUROPE_BBOX)
    if not fine_contours:
        raise ValueError("No real 2-hPa contours in Europe from ECMWF MSLP")
    if not contours:
        raise ValueError("No real contours in the interpolated MSLP field")
    at = run + dt.timedelta(minutes=forecast_minute)
    exact = forecast_minute % 180 == 0
    return {
        "valid_utc": at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "forecast_minute": forecast_minute,
        "forecast_hour": forecast_minute/60,
        "interpolated": not exact,
        "interpolation_method": "linear_mslp_grid_then_contours" if not exact else "original_ifs_grid",
        "source_steps_hours": list(source_steps) if not exact else [forecast_minute//60],
        "source_valid_utc": [
            (run + dt.timedelta(hours=h)).isoformat(timespec="seconds").replace("+00:00", "Z")
            for h in (source_steps if not exact else [forecast_minute//60])
        ],
        "min_hpa": round(float(np.min(pressure)), 1),
        "max_hpa": round(float(np.max(pressure)), 1),
        "contours": contours,
        "fine_contours": fine_contours,
    }


def build_10min(grids, run, generated_at, root):
    """Commit immutable run directory first, then index atomically as last write."""
    if set(grids) != set(MODEL_STEPS_HOURS):
        raise ValueError("All verified ECMWF IFS source steps are required")
    root = Path(root)
    run_id = PREFIX + run.strftime("%Y%m%d%H")
    run_dir = root/run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    chunks = {}
    fine_chunks = {}
    for hour in range(MAX_HOURS+1):
        frames = []
        fine_frames = []
        for minute in range(hour*60, min((hour+1)*60, MAX_HOURS*60+1), 10):
            full = frame_from_grids(grids, run, minute)
            fine = full.pop("fine_contours")
            frames.append(full)
            fine_frames.append({**full, "contours": fine})
        if not frames:
            raise ValueError("No valid contours for an hourly chunk")
        name = f"h{hour:02d}.json"
        payload = {
            "schema_version": 2,
            "model": "ECMWF IFS Open Data",
            "run_utc": run.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "hour": hour,
            "frames": frames,
        }
        target = run_dir/name
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
        temporary.replace(target)
        chunks[f"h{hour:02d}"] = f"{run_id}/{name}"
        fine_name = f"h{hour:02d}_2hpa.json"
        fine_target = run_dir/fine_name
        fine_payload = {**payload, "interval_hpa": 2, "regions": list(FINE_REGIONS),
                        "frames": fine_frames}
        fine_temp = fine_target.with_suffix(".tmp")
        fine_temp.write_text(json.dumps(fine_payload, separators=(",", ":"), ensure_ascii=False,
                                       allow_nan=False)+"\n", encoding="utf-8")
        fine_temp.replace(fine_target)
        fine_chunks[f"h{hour:02d}"] = f"{run_id}/{fine_name}"
    index = {
        "schema_version": 2,
        "model": "ECMWF IFS Open Data",
        "field": "mean sea-level pressure",
        "units": "hPa",
        "resolution_degrees": 0.25,
        "interval_hpa": 5,
        "run_utc": run.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "generated_at": generated_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "valid_start_utc": run.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "valid_end_utc": (run+dt.timedelta(hours=MAX_HOURS)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "time_resolution_minutes": 10,
        "source_interval_hours": 3,
        "interpolation_method": "linear_mslp_grid_then_contours",
        "source": "ECMWF IFS Open Data (© ECMWF, CC BY 4.0)",
        "note": "10-minute intervals are interpolated IFS MSLP forecasts, NOT separate 10-minute observations or model runs.",
        "hours": chunks,
        "fine_hours": fine_chunks,
        "fine_interval_hpa": 2,
        "fine_regions": list(FINE_REGIONS),
        "fine_bbox": list(EUROPE_BBOX),
    }
    tmp = root/"index.tmp"
    tmp.write_text(json.dumps(index, separators=(",", ":"), ensure_ascii=False)+"\n", encoding="utf-8")
    tmp.replace(root/"index.json")
    # Keep one previous valid run to protect browsers with a cached index.
    older = sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith(PREFIX)), reverse=True)
    import shutil
    for path in older[2:]:
        shutil.rmtree(path)
    return index
