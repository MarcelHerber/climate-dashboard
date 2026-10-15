#!/usr/bin/env python3
"""Create one verified NH polar-vortex ERA5 10-hPa daily geopotential map.

No forecast/placeholder. Existing published image stays untouched if CDS fails.
Uses the ERA5-derived daily mean (UTC, four 6-hourly fields).
"""
from __future__ import annotations
import argparse
import json
import math
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

GRAVITY = 9.80665
DATASET = "derived-era5-pressure-levels-daily-statistics"
DOI = "10.24381/cds.50314f4c"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "polar_vortex"


def request_for(day):
    return {
        "product_type": "reanalysis",
        "variable": ["geopotential"],
        "pressure_level": ["10"],
        "year": str(day.year),
        "month": [f"{day.month:02d}"],
        "day": [f"{day.day:02d}"],
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "6_hourly",
        "area": [90, -180, 25, 180],
        "grid": "1/1",
    }


def validated_field(ds, requested_day):
    """Reject wrong time, incomplete polar domain, non-finite or implausible data."""
    import update_era5_stratosphere as era
    arr = era.select_array(ds, "z", 10)
    time_name = next((d for d in ("valid_time", "time", "date") if d in arr.dims), None)
    lat_name = next((d for d in ("latitude", "lat") if d in arr.dims), None)
    lon_name = next((d for d in ("longitude", "lon") if d in arr.dims), None)
    if not lat_name or not lon_name or not time_name:
        raise ValueError(f"Missing time/lat/lon in ERA5 geopotential: {arr.dims}")
    times = [str(np.datetime64(t, "D")) for t in arr[time_name].values]
    if times != [requested_day.isoformat()]:
        raise ValueError(f"ERA5 returned {times} instead of {requested_day}")
    field = arr.transpose(time_name, lat_name, lon_name).values[0]
    lats = np.asarray(arr[lat_name].values, dtype=float)
    lons = np.asarray(arr[lon_name].values, dtype=float)
    if lats.size < 50 or not (lats.min() <= 25.5 and lats.max() >= 89.5):
        raise ValueError("ERA5 polar latitude extent incomplete")
    if lons.size < 350 or np.ptp(lons) < 350:
        raise ValueError("ERA5 polar longitude extent incomplete")
    if not np.isfinite(field).all():
        raise ValueError("Missing/nonfinite ERA5 grid cells")
    if np.isclose(abs(lons[-1]-lons[0]), 360.0, atol=.05):
        lons = lons[:-1]
        field = field[:, :-1]
    data = np.asarray(field / GRAVITY, dtype=float)
    if data.min() < 19000 or data.max() > 37000 or data.max() <= data.min():
        raise ValueError("Implausible 10-hPa geopotential height, expected gpm")
    return lats, lons, data


def plot_map(lats, lons, values, day, dest):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.path as mpath
    import cartopy.crs as ccrs
    from cartopy.util import add_cyclic_point

    # Plot only the observed field, without interpolation over missing values.
    order = np.argsort(lons)
    lons = lons[order]
    values = values[:, order]
    if np.any(np.diff(lons) <= 0):
        raise ValueError("Nonunique longitude coordinates")
    cyclic, lon_cyclic = add_cyclic_point(values, coord=lons)
    min_z, max_z = float(values.min()), float(values.max())
    step = 250
    lower = math.floor(min_z / step) * step
    upper = math.ceil(max_z / step) * step
    levels = np.arange(lower, upper + step, step)
    if len(levels) < 3:
        levels = np.linspace(min_z - 100, max_z + 100, 5)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig = plt.figure(figsize=(10.6, 10.2), dpi=150, facecolor="#ffffff")
    ax = fig.add_axes([.11, .16, .78, .70], projection=ccrs.NorthPolarStereo())
    ax.set_extent([-180, 180, 25, 90], crs=ccrs.PlateCarree())
    theta = np.linspace(0, 2*np.pi, 180)
    boundary = mpath.Path(np.column_stack([.5+.5*np.sin(theta), .5+.5*np.cos(theta)]))
    ax.set_boundary(boundary, transform=ax.transAxes)
    kw = {"transform": ccrs.PlateCarree()}
    chart = ax.contourf(lon_cyclic, lats, cyclic, levels=levels,
                        cmap="PuBuGn_r", extend="both", **kw)
    contour = ax.contour(lon_cyclic, lats, cyclic, levels=levels[::2],
                         colors="#17324a", linewidths=.63, alpha=.72, **kw)
    ax.clabel(contour, inline=True, fontsize=7, fmt="%d")
    ax.coastlines(resolution="110m", linewidth=.8, color="#253447", alpha=.9)
    gl = ax.gridlines(crs=ccrs.PlateCarree(), linewidth=.6,
                      color="#475569", alpha=.3, linestyle="--")
    gl.xlocator = __import__("matplotlib.ticker", fromlist=["FixedLocator"]).FixedLocator(np.arange(-180,180,30))
    gl.ylocator = __import__("matplotlib.ticker", fromlist=["FixedLocator"]).FixedLocator([30,45,60,75])
    fig.text(.06,.946,"POLARWIRBEL  |  NORDHEMISPHÄRE", fontsize=11,
             weight="bold", color="#19588c")
    fig.text(.06,.907,"Geopotenzialhöhe in 10 hPa", fontsize=22,
             weight="bold", color="#15263c")
    fig.text(.06,.866,f"ERA5-Tagesmittel (00–24 UTC)  ·  {day:%d.%m.%Y}  ·  25–90° N",
             fontsize=11, color="#536578")
    cbar = fig.colorbar(chart,ax=ax,orientation="horizontal",
                        fraction=.055,pad=.065,aspect=30)
    cbar.set_label("Geopotenzialhöhe (gpm)",fontsize=11)
    cbar.ax.tick_params(labelsize=9)
    fig.text(.06,.053,"Daten: Copernicus C3S / ECMWF · ERA5 · DOI: "+DOI,
             fontsize=9,color="#516275")
    fig.text(.06,.032,"Reanalyse · Tagesmittel, keine Prognose · Climate Dashboard Deutschland",
             fontsize=9,color="#516275")
    dest.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(dest,facecolor="white",dpi=150)
    plt.close(fig)


def build(output=OUTPUT, today=None, client=None):
    import update_era5_stratosphere as era
    today = today or datetime.now(timezone.utc).date()
    output = Path(output)
    meta_path = output/"current.json"
    existing = {}
    if meta_path.is_file():
        try:
            existing=json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            existing={}
    current_date=existing.get("analysis_date")
    if current_date and (output/"polar_vortex_10hpa_current.png").is_file():
        try:
            if date.fromisoformat(current_date) >= today-timedelta(days=8):
                print("Polarvortex ERA5 already up to date:",current_date)
                return existing
        except ValueError:
            pass
    if client is None:
        import cdsapi
        client=cdsapi.Client()
    last_error=None
    # The daily derived product is usually delayed by about six days.
    for ago in (8, 9, 10, 11):
        day = today-timedelta(days=ago)
        if current_date:
            try:
                if day <= date.fromisoformat(current_date):
                    continue
            except ValueError:
                pass
        print("Attempting verified ERA5 10 hPa map for",day,flush=True)
        with tempfile.TemporaryDirectory(prefix="polar-vortex-") as workdir:
            path=Path(workdir)/"raw.zip"
            try:
                client.retrieve(DATASET,request_for(day),str(path))
                ds=era.open_cds_file(path)
                lats,lons,data=validated_field(ds,day)
                tmp_png=Path(workdir)/"map.png"
                plot_map(lats,lons,data,day,tmp_png)
                if not tmp_png.is_file() or tmp_png.stat().st_size < 25000:
                    raise ValueError("Map rendering produced an invalid PNG")
                payload={
                    "schema_version":1,
                    "ready":True,
                    "analysis_date":day.isoformat(),
                    "statistic":"daily_mean",
                    "analysis_time_description":"00–24 UTC, mean of 6-hourly ERA5 reanalysis fields",
                    "pressure_hpa":10,
                    "parameter":"geopotential_height",
                    "unit":"gpm",
                    "region":"Northern Hemisphere 25–90 N",
                    "grid_resolution_degrees":1.0,
                    "min_gpm":round(float(data.min()),1),
                    "max_gpm":round(float(data.max()),1),
                    "image":"polar_vortex_10hpa_current.png",
                    "source":"Copernicus Climate Change Service (C3S) / ECMWF ERA5",
                    "doi":DOI,
                    "generated_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "forecast":False,
                    "note":"ERA5 daily reanalysis; latest available date can lag by several days"
                }
                # Promote the validated PNG first, then publish metadata last.
                output.mkdir(parents=True,exist_ok=True)
                os.replace(tmp_png,output/"polar_vortex_10hpa_current.png")
                tmp_json=output/"current.json.tmp"
                tmp_json.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                os.replace(tmp_json,meta_path)
                print("Published verified polar vortex map for",day)
                return payload
            except Exception as e:
                last_error=e
                print(f"ERA5 map unavailable for {day}: {type(e).__name__}: {e}",flush=True)
    if current_date:
        print("No newer verified ERA5 available; preserving existing map",current_date)
        return existing
    raise RuntimeError("No verified ERA5 10 hPa daily grid was available") from last_error


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,default=OUTPUT)
    args=p.parse_args()
    build(output=args.output)


if __name__=="__main__":
    main()
