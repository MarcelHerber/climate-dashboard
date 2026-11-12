#!/usr/bin/env python3
"""Produce georeferenced 5 hPa ECMWF IFS sea-level-pressure contours for MTG.

Input: REAL ECMWF IFS Open Data MSL (GRIB2 0.25°).
Output: compact vector contour JSON, preserving forecast run, lead and valid UTC.
A failed real download must NEVER produce fictional pressure fields or dates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import tempfile
from pathlib import Path

import numpy as np

UTC = dt.timezone.utc
BBOX = (-75.0, 12.0, 55.0, 80.0)
LEADS = (0, 3, 6, 9, 12, 15, 18)
LEVELS = tuple(range(900, 1071, 5))
SOURCE_URL = "https://www.ecmwf.int/en/forecasts/datasets/open-data"
MAX_AGE_HOURS = 36


def candidate_runs(now: dt.datetime):
    """Try newest operational cycles with a 6h buffer; fetch checks real availability."""
    now = now.astimezone(UTC)
    out = []
    for days in range(4):
        day = now.date() - dt.timedelta(days=days)
        for hour in (18, 12, 6, 0):
            t = dt.datetime.combine(day, dt.time(hour), tzinfo=UTC)
            if t <= now - dt.timedelta(hours=6):
                out.append(t)
    return sorted(out, reverse=True)[:5]


def fetch_grib(run, path):
    """Read the freshest actually available GRIB, with an official AWS mirror."""
    from ecmwf.opendata import Client
    errors = []
    for backend in ("ecmwf", "aws"):
        try:
            path.unlink(missing_ok=True)
            client = Client(source=backend, model="ifs", resol="0p25")
            client.retrieve(
                date=run.strftime("%Y-%m-%d"),
                time=run.hour,
                stream="oper",
                type="fc",
                param="msl",
                step=list(LEADS),
                target=str(path),
            )
            if not path.exists() or path.stat().st_size < 100_000:
                raise ValueError("Downloaded GRIB too small or missing")
            logging.info("ECMWF GRIB %s: %s from %s", run.isoformat(), path.stat().st_size, backend)
            return path
        except Exception as exc:
            errors.append(f"{backend}: {type(exc).__name__}: {exc}")
            logging.warning("IFS source %s for %s unavailable: %s", backend, run, exc)
    raise RuntimeError("Both official ECMWF sources unavailable: " + "; ".join(errors))


def decode_grib(path, run):
    from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release
    outputs = {}
    with path.open("rb") as fp:
        while (message := codes_grib_new_from_file(fp)) is not None:
            try:
                if str(codes_get(message, "shortName")).lower() not in ("msl", "prmsl"):
                    continue
                step = int(codes_get(message, "endStep"))
                if step not in LEADS:
                    continue
                origin = dt.datetime.strptime(
                    f'{int(codes_get(message, "dataDate")):08d}{int(codes_get(message, "dataTime")):04d}',
                    "%Y%m%d%H%M",
                ).replace(tzinfo=UTC)
                if origin != run:
                    raise ValueError(f"GRIB run mismatch: {origin.isoformat()} != {run.isoformat()}")
                ni, nj = int(codes_get(message, "Ni")), int(codes_get(message, "Nj"))
                if ni < 500 or nj < 300:
                    raise ValueError("Unexpectedly coarse IFS MSLP grid")
                values = np.asarray(codes_get_array(message, "values"), dtype=np.float64).reshape(nj, ni)
                lat = np.asarray(codes_get_array(message, "latitudes"), dtype=np.float64).reshape(nj, ni)
                lon = np.asarray(codes_get_array(message, "longitudes"), dtype=np.float64).reshape(nj, ni)
                lon = (lon + 180) % 360 - 180
                # Rectangular global lon/lat fields: filter both axes,
                # then sort to avoid discontinuity at the 0/360 seam.
                r = np.flatnonzero((lat[:, 0] >= BBOX[1]) & (lat[:, 0] <= BBOX[3]))
                c = np.flatnonzero((lon[0, :] >= BBOX[0]) & (lon[0, :] <= BBOX[2]))
                if len(r) < 200 or len(c) < 400:
                    raise ValueError(f"Incomplete Atlantic/European coverage: {len(r)}×{len(c)}")
                rows = r[np.argsort(lat[r, 0])]
                cols = c[np.argsort(lon[0, c])]
                yy = lat[rows, 0]
                xx = lon[0, cols]
                field = values[np.ix_(rows, cols)]
                if np.nanmedian(field) > 2000:
                    field /= 100.0
                if not (np.isfinite(field).all()
                        and np.all(np.diff(xx) > 0)
                        and np.all(np.diff(yy) > 0)):
                    raise ValueError("MSLP field contains gaps, invalid values or unsorted coordinates")
                if not (800 <= float(field.min()) <= 1050 and 950 <= float(field.max()) <= 1120):
                    raise ValueError("MSLP field not plausible hPa")
                outputs[step] = (xx, yy, field)
            finally:
                codes_release(message)
    if not all(step in outputs for step in LEADS):
        raise ValueError(f"Missing ECMWF pressure leads: {[s for s in LEADS if s not in outputs]}")
    return outputs


def contour_lines(lons, lats, pressure, levels=LEVELS):
    """Compute geographic (lon,lat) polylines, not rendered chart pixels."""
    import contourpy
    if pressure.shape != (len(lats), len(lons)):
        raise ValueError("Grid axes and pressure field mismatch")
    lines_out = []
    builder = contourpy.contour_generator(
        x=lons, y=lats, z=pressure, name="serial",
        line_type="Separate", corner_mask=False,
    )
    for level in levels:
        paths = []
        for points in builder.lines(float(level)):
            if len(points) < 4:
                continue
            # Step sampling preserves source-grid fidelity without huge JSON;
            # every vertex remains in actual geographical coordinates.
            arr = np.asarray(points, dtype=float)
            if len(arr) > 1100:
                idx = np.unique(np.r_[np.arange(0, len(arr), math.ceil(len(arr)/1100)), len(arr)-1])
                arr = arr[idx]
            coords = np.round(arr, 3).tolist()
            if all(np.isfinite(arr.ravel())):
                paths.append(coords)
        if paths:
            lines_out.append({"hpa": int(level), "lines": paths})
    if not lines_out:
        raise ValueError("No isobar contours generated from the genuine pressure field")
    return lines_out


def build_payload(grids, run, generated_at):
    if set(grids) != set(LEADS):
        raise ValueError("Pressure data missing required forecast steps")
    frames = []
    for lead in LEADS:
        lons, lats, press = grids[lead]
        frames.append({
            "valid_utc": (run + dt.timedelta(hours=lead)).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "forecast_hour": lead,
            "min_hpa": round(float(press.min()), 1),
            "max_hpa": round(float(press.max()), 1),
            "contours": contour_lines(lons, lats, press),
        })
    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "model": "ECMWF IFS Open Data",
        "source_url": SOURCE_URL,
        "license": "CC BY 4.0 · © ECMWF",
        "field": "mean sea-level pressure",
        "units": "hPa",
        "resolution_degrees": 0.25,
        "bbox": list(BBOX),
        "interval_hpa": 5,
        "run_utc": run.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "note": "IFS deterministic forecast, not a satellite observation or official synoptic analysis. Never interpolate across missing valid times.",
        "frames": frames,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("data/satellite_mslp/latest.json"))
    parser.add_argument("--ten-minute-dir", type=Path, default=Path("data/satellite_mslp/ten_minute"))
    args = parser.parse_args()
    now = dt.datetime.now(UTC)
    errors = []
    from build_satellite_mslp_10min import build_10min
    for run in candidate_runs(now):
        try:
            # Re-running an unchanged cycle must not waste compute or commits.
            if args.out.is_file() and (args.ten_minute_dir/"index.json").is_file():
                previous = json.loads(args.out.read_text(encoding="utf-8"))
                manifest = json.loads((args.ten_minute_dir/"index.json").read_text(encoding="utf-8"))
                valid_run = run.isoformat(timespec="seconds").replace("+00:00", "Z")
                if (previous.get("run_utc")==valid_run and manifest.get("run_utc")==valid_run
                        and manifest.get("schema_version")==2
                        and len(manifest.get("hours", {}))==19
                        and manifest.get("fine_interval_hpa")==2
                        and set(manifest.get("fine_regions",[]))=={"europe","southwest","central","germany"}
                        and len(manifest.get("fine_hours",{}))==19
                        and all((args.ten_minute_dir/path).is_file()
                                for path in list(manifest["hours"].values())+list(manifest["fine_hours"].values()))):
                    print(json.dumps({"status":"unchanged","run_utc":valid_run,
                                      "ten_minute_frames":109,"fine_2hpa":True}))
                    return 0
            with tempfile.TemporaryDirectory(prefix="sat-mslp-") as tmp:
                path = Path(tmp)/"ifs_msl.grib2"
                fetch_grib(run, path)
                grids = decode_grib(path, run)
            payload = build_payload(grids, run, now)
            age_h = (now-run).total_seconds()/3600
            if age_h > MAX_AGE_HOURS:
                raise ValueError("Selected model run too old")
            ten_index = build_10min(grids, run, now, args.ten_minute_dir)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            target = args.out.with_suffix(".tmp")
            target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",",":"), allow_nan=False)+"\n", encoding="utf-8")
            target.replace(args.out)
            logging.info("Published true ECMWF MSLP: run %s, %d UTC frames, %d bytes",
                         run.isoformat(),len(payload["frames"]),args.out.stat().st_size)
            print(json.dumps({"status":"ok","run_utc":payload["run_utc"],
                              "frames":[v["valid_utc"] for v in payload["frames"]],
                              "size_bytes":args.out.stat().st_size, "ten_minute_frames":109, "chunks":len(ten_index["hours"]),"fine_2hpa_chunks":len(ten_index["fine_hours"])}))
            return 0
        except Exception as exc:
            errors.append(f"{run:%Y-%m-%dT%H:%MZ}: {type(exc).__name__}: {str(exc)[:160]}")
            logging.warning("IFS MSLP unavailable for %s: %s",run,exc)
    raise SystemExit("No verified ECMWF IFS MSLP run. Nothing published: "+"; ".join(errors))


if __name__ == "__main__":
    raise SystemExit(main())
