#!/usr/bin/env python3
"""Daily *verified* ERA5 north-of-80N T2m and month-relative anomaly maps.

All maps require actual CDS grids. No synthetic values, proxy maps, or placeholder
raster. Daily product uses 24 hourly ERA5 fields, aggregated in UTC via the
official derived ERA5 daily statistics service; anomalies subtract the
1991–2020 ERA5 *monthly* mean (not a calendar-day climatology).

CDSAPI_KEY/.cdsapirc and CDS licence acceptance are required on the workflow.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "arctic_era5_maps"
DAILY_DATASET = "derived-era5-single-levels-daily-statistics"
MONTHLY_DATASET = "reanalysis-era5-single-levels-monthly-means"
BASELINE_START, BASELINE_END = 1991, 2020
RESOLUTION = 0.5
LAT_SOUTH = 80.0
DOI_DAILY = "10.24381/cds.4991cf48"
DOI_MONTHLY = "10.24381/cds.f17050d7"
PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")
TEMP_LEVELS = np.arange(-45, 20, 5)
ANOM_LEVELS = np.arange(-15, 18, 3)


def daily_request(day: date) -> dict:
    return {
        "product_type": "reanalysis",
        "variable": ["2m_temperature"],
        "year": str(day.year),
        "month": [f"{day.month:02d}"],
        "day": [f"{day.day:02d}"],
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": [90, -180, 80, 180],
        "grid": "0.5/0.5",
    }


def monthly_request(month: int) -> dict:
    return {
        "product_type": "monthly_averaged_reanalysis",
        "variable": "2m_temperature",
        "year": [str(y) for y in range(BASELINE_START, BASELINE_END + 1)],
        "month": [f"{month:02d}"],
        "time": "00:00",
        "area": [90, -180, 80, 180],
        "grid": "0.5/0.5",
        "data_format": "netcdf",
    }


def get_dataarray(path: Path):
    """Return loaded xarray DataArray from direct NetCDF or CDS ZIP."""
    import xarray as xr

    def extract(filename):
        with xr.open_dataset(filename, engine="netcdf4") as ds:
            keys = ["t2m", "2m_temperature", "var167"]
            candidates = [key for key in keys if key in ds.data_vars]
            if not candidates:
                candidates = [
                    k for k, v in ds.data_vars.items()
                    if any(d in v.dims for d in ("latitude", "lat"))
                    and any(d in v.dims for d in ("longitude", "lon"))
                ]
            if len(candidates) != 1:
                raise ValueError(f"Expected a single ERA5 T2m field; got {list(ds.data_vars)}")
            return ds[candidates[0]].load()

    if zipfile.is_zipfile(path):
        with tempfile.TemporaryDirectory(prefix="era5-n80-zip-") as tmp:
            with zipfile.ZipFile(path) as archive:
                names = [
                    n for n in archive.namelist()
                    if n.endswith((".nc", ".netcdf")) and not n.startswith("__MACOSX/")
                ]
                if len(names) != 1:
                    raise ValueError(f"Expected exactly one NetCDF in CDS ZIP; found {names}")
                target = Path(tmp) / "source.nc"
                with archive.open(names[0]) as fin, target.open("wb") as fout:
                    import shutil
                    shutil.copyfileobj(fin, fout)
            return extract(target)
    return extract(path)


def standardize(da):
    """Canonical [time, lat, lon] and unique longitude ordering."""
    lat_name = next((d for d in ("latitude", "lat") if d in da.dims), None)
    lon_name = next((d for d in ("longitude", "lon") if d in da.dims), None)
    if not lat_name or not lon_name:
        raise ValueError(f"Missing spatial dimensions: {da.dims}")
    time_name = next(
        (d for d in ("valid_time", "time", "date", "forecast_reference_time") if d in da.dims),
        None,
    )
    # CDS ERA5/ERA5T may expose separate expver slices. Prefer the verified
    # reanalysis (1), fill only truly absent values from expver 5.
    if "expver" in da.dims:
        versions = list(np.asarray(da["expver"].values))
        pref = 1 if 1 in versions else versions[0]
        primary = da.sel(expver=pref)
        for secondary in versions:
            if secondary != pref:
                primary = primary.combine_first(da.sel(expver=secondary))
        da = primary
    for dim in list(da.dims):
        if dim not in (lat_name, lon_name, time_name):
            if da.sizes[dim] != 1:
                raise ValueError(f"Unrecognized non-singleton ERA5 axis {dim}: {da.sizes[dim]}")
            da = da.isel({dim: 0}, drop=True)
    if time_name is None:
        da = da.expand_dims({"sample_time": [np.datetime64("1970-01-01")]})
        time_name = "sample_time"
    da = da.transpose(time_name, lat_name, lon_name)
    lats = np.asarray(da[lat_name].values, dtype=float)
    lons = np.asarray(da[lon_name].values, dtype=float)
    if lats.size < 20 or lats.min() > 80.01 or lats.max() < 89.99:
        raise ValueError("ERA5 north-polar latitude selection is incomplete")
    if lons.size < 710 or np.ptp(lons) < 350:
        raise ValueError("ERA5 longitude coverage is not global")
    lons = (lons + 180) % 360 - 180
    lat_order = np.argsort(lats)
    lon_order = np.argsort(lons)
    lats, lons = lats[lat_order], lons[lon_order]
    field = np.asarray(da.values, dtype=float)[:, lat_order, :][:, :, lon_order]
    keep = np.insert(np.diff(lons) > 0.001, 0, True)
    lons, field = lons[keep], field[:, :, keep]
    if lons.size < 710 or abs(np.median(np.diff(lons)) - RESOLUTION) > 0.02:
        raise ValueError("ERA5 grid does not match stated 0.5-degree resolution")
    if np.any(np.diff(lats) <= 0) or np.any(np.diff(lons) <= 0):
        raise ValueError("ERA5 coordinate axes are not strictly increasing")
    return lats, lons, field, da[time_name].values


def validate_daily(array, day: date):
    lat, lon, cubes, times = standardize(array)
    timestamps = [str(np.datetime64(t, "D")) for t in times]
    if len(timestamps) != 1 or timestamps[0] != day.isoformat():
        raise ValueError(f"Wrong ERA5 daily timestamps: {timestamps} for {day}")
    kelvin = cubes[0]
    if not np.isfinite(kelvin).all() or np.nanmin(kelvin) < 180 or np.nanmax(kelvin) > 320:
        raise ValueError("ERA5 daily T2m has missing or implausible Kelvin values")
    return lat, lon, kelvin


def validate_monthly(array, month: int):
    lat, lon, cubes, times = standardize(array)
    years = [int(str(np.datetime64(t, "D"))[:4]) for t in times]
    actual = sorted(set(years))
    expected = list(range(BASELINE_START, BASELINE_END + 1))
    if actual != expected or len(years) != 30:
        raise ValueError(f"ERA5 monthly reference incomplete, received years {actual}")
    if not np.isfinite(cubes).all() or cubes.min() < 180 or cubes.max() > 320:
        raise ValueError("ERA5 baseline contains invalid temperatures")
    for t in times:
        if int(str(np.datetime64(t, "D"))[5:7]) != month:
            raise ValueError("ERA5 baseline returned another calendar month")
    return lat, lon, cubes.mean(axis=0)


def cap_mean(values: np.ndarray, lats: np.ndarray) -> float:
    weights = np.cos(np.deg2rad(lats))
    return float((values * weights[:, None]).sum() /
                 (weights.sum() * values.shape[1]))


def render_map(lats, lons, values, day: date, mode: str, path: Path, mean: float):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import matplotlib.path as mpath
    import cartopy.crs as ccrs
    from cartopy.util import add_cyclic_point

    if mode not in ("temperature", "anomaly"):
        raise ValueError("Unknown map mode")
    order = np.argsort(lons)
    lon = np.asarray(lons)[order]
    grid = np.asarray(values)[:, order]
    wrapped, lon_w = add_cyclic_point(grid, coord=lon)
    levels = TEMP_LEVELS if mode == "temperature" else ANOM_LEVELS
    cmap = plt.get_cmap("RdYlBu_r" if mode == "temperature" else "RdBu_r")
    norm = mcolors.BoundaryNorm(levels, cmap.N, extend="both")
    fig = plt.figure(figsize=(10.4, 10.3), facecolor="#ffffff", dpi=130)
    ax = fig.add_axes([0.12, 0.175, 0.76, 0.69], projection=ccrs.NorthPolarStereo())
    ax.set_extent([-180, 180, 79.8, 90], crs=ccrs.PlateCarree())
    theta = np.linspace(0, 2 * np.pi, 220)
    boundary = mpath.Path(np.column_stack([0.5 + .5*np.sin(theta),
                                           0.5 + .5*np.cos(theta)]))
    ax.set_boundary(boundary, transform=ax.transAxes)
    mesh = ax.pcolormesh(lon_w, lats, wrapped, transform=ccrs.PlateCarree(),
                         cmap=cmap, norm=norm, shading="auto", rasterized=True)
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            feature = ax.coastlines(resolution="110m", linewidth=.75,
                                    color="#263d52", alpha=.80)
            fig.canvas.draw()
    except Exception as err:
        try:
            feature.remove()
        except Exception:
            pass
        print(f"Coastline warning (gridded ERA5 remains valid): {err}", flush=True)
    gl = ax.gridlines(draw_labels=False, linewidth=.6, alpha=.32,
                      color="#43576a", linestyle="--")
    import matplotlib.ticker as mticker
    gl.xlocator = mticker.FixedLocator(np.arange(-180, 180, 30))
    gl.ylocator = mticker.FixedLocator([80, 85])
    fig.text(.07, .955, "KLIMADASHBOARD  |  HOCHARKTIS >80° N",
             fontsize=12, color="#215b82", weight="bold")
    title = "Lufttemperatur in 2 m Höhe" if mode=="temperature" else "Abweichung vom Monatsklima"
    subtitle = ("ERA5-Tagesmittel · 00–24 UTC" if mode=="temperature" else
                "ERA5-Tagesmittel minus Monatsmittel 1991–2020")
    fig.text(.07, .909, title, fontsize=23, color="#132b43", weight="bold")
    fig.text(.07, .876, f"{day:%d.%m.%Y} · {subtitle} · 0,5°-Raster",
             fontsize=10.5, color="#566b80")
    cb = fig.colorbar(mesh, ax=ax, orientation="horizontal", fraction=.054,
                      pad=.07, aspect=29, ticks=levels[::2], extend="both")
    cb.set_label("2-m-Lufttemperatur (°C)" if mode=="temperature"
                 else "Differenz zum Monatsklima (K)", fontsize=11)
    fig.text(.07, .080,
             ("Flächengewichtetes Kappenmittel: " + f"{mean:+.1f} " +
              ("°C" if mode=="temperature" else "K")),
             fontsize=11, color="#264763")
    fig.text(.07, .053, f"Copernicus C3S / ECMWF · ERA5 · Tagesdaten DOI {DOI_DAILY}",
             fontsize=9, color="#536679")
    fig.text(.07, .030,
             ("Reanalyse, keine Prognose · Monatsreferenz 1991–2020 · " +
              "nicht identisch mit DMI >80°N Index"),
             fontsize=8.8, color="#536679")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white", dpi=130)
    plt.close(fig)


def load_reference(client, month: int, output: Path, workspace: Path):
    path = output/"reference"/f"{month:02d}.npz"
    if path.exists():
        with np.load(path) as cached:
            lat = cached["latitude"].copy()
            lon = cached["longitude"].copy()
            grid = cached["kelvin"].copy()
        if lat.size>=20 and lon.size>=710 and np.isfinite(grid).all():
            print(f"Using verified 1991–2020 climatology for month {month:02d}", flush=True)
            return lat, lon, grid
    raw = workspace/f"monthly_{month:02d}.zip"
    client.retrieve(MONTHLY_DATASET, monthly_request(month), str(raw))
    if not raw.exists() or raw.stat().st_size < 2000:
        raise RuntimeError("ERA5 monthly climatology not downloaded")
    lats, lons, baseline = validate_monthly(get_dataarray(raw), month)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.npz")
    np.savez_compressed(temporary, latitude=lats, longitude=lons, kelvin=baseline)
    os.replace(temporary, path)
    return lats, lons, baseline


def valid_image(path: Path) -> bool:
    return path.exists() and path.stat().st_size >= 25000 and path.open("rb").read(8) == PNG_SIGNATURE


def make_one_day(day: date, client, output: Path, workspace: Path):
    raw = workspace/f"daily_{day:%Y%m%d}.zip"
    client.retrieve(DAILY_DATASET, daily_request(day), str(raw))
    if not raw.exists() or raw.stat().st_size < 2000:
        raise RuntimeError("ERA5 daily data not downloaded")
    lats, lons, kelvin = validate_daily(get_dataarray(raw), day)
    ref_lats, ref_lons, baseline = load_reference(client, day.month, output, workspace)
    if not np.allclose(lats, ref_lats) or not np.allclose(lons, ref_lons):
        raise ValueError("Daily ERA5 grid and 1991–2020 reference mismatch")
    tc = kelvin - 273.15
    anomaly = kelvin - baseline
    tc_mean = cap_mean(tc, lats)
    anomaly_mean = cap_mean(anomaly, lats)
    if not (-65 < tc_mean < 15 and -30 < anomaly_mean < 30):
        raise ValueError("Implausible polar cap temperature/anomaly mean")
    day_key = day.strftime("%Y%m%d")
    directory = output/"maps"
    temp_png = directory/f"t2m_{day_key}.png"
    anom_png = directory/f"anomaly_{day_key}.png"
    tmp_temp = workspace/f"temp_{day_key}.png"
    tmp_anom = workspace/f"anom_{day_key}.png"
    render_map(lats, lons, tc, day, "temperature", tmp_temp, tc_mean)
    render_map(lats, lons, anomaly, day, "anomaly", tmp_anom, anomaly_mean)
    if not valid_image(tmp_temp) or not valid_image(tmp_anom):
        raise RuntimeError("ERA5 images failed PNG integrity checks")
    directory.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_temp, temp_png)
    os.replace(tmp_anom, anom_png)
    record = {
        "date": day.isoformat(),
        "temperature_png": f"maps/{temp_png.name}",
        "anomaly_png": f"maps/{anom_png.name}",
        "mean_c": round(tc_mean, 2),
        "mean_anomaly_k": round(anomaly_mean, 2),
        "min_c": round(float(tc.min()), 2),
        "max_c": round(float(tc.max()), 2),
        "min_anomaly_k": round(float(anomaly.min()), 2),
        "max_anomaly_k": round(float(anomaly.max()), 2),
    }
    print("Verified ERA5 >80N maps:", record, flush=True)
    return record


def validate_manifest(data: dict, root: Path) -> None:
    if data.get("schema") != 1 or data.get("ready") is not True:
        raise ValueError("ERA5 polar map index is not ready")
    if data.get("reference_period") != "1991-2020":
        raise ValueError("ERA5 polar map climatology reference mismatch")
    records = data.get("days")
    if not isinstance(records, list) or not records:
        raise ValueError("ERA5 map index lacks actual days")
    seen = set()
    for entry in records:
        day = date.fromisoformat(entry["date"])
        if day in seen:
            raise ValueError("Duplicate map date")
        seen.add(day)
        for key in ("temperature_png", "anomaly_png"):
            relative = Path(entry[key])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe ERA5 image relative path")
            if not valid_image(root/relative):
                raise ValueError(f"Missing/invalid ERA5 PNG: {relative}")
        for val in ("mean_c", "mean_anomaly_k"):
            if not math.isfinite(float(entry[val])):
                raise ValueError("Nonfinite area-mean map value")
    if data["latest_date"] != max(entry["date"] for entry in records):
        raise ValueError("ERA5 latest_date mismatch")


def build(output: Path = OUTPUT, today: date | None = None, client=None,
          max_new_days: int=2):
    output = Path(output)
    today = today or datetime.now(timezone.utc).date()
    index = output/"index.json"
    old = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}
    previous = old.get("days", []) if old.get("ready") else []
    previous = [r for r in previous if all(valid_image(output/r[k])
                 for k in ("temperature_png", "anomaly_png"))]
    by_date = {row["date"]: row for row in previous}
    if client is None:
        import cdsapi
        client = cdsapi.Client()
    built=0
    errors=[]
    with tempfile.TemporaryDirectory(prefix="era5-arctic80-") as tmp:
        work=Path(tmp)
        for ago in range(7, 13):
            day=today-timedelta(days=ago)
            if day.isoformat() in by_date:
                continue
            # Reject older history that would displace existing, newer real images.
            if previous and day.isoformat() < max(r["date"] for r in previous):
                continue
            try:
                row=make_one_day(day, client, output, work)
                by_date[row["date"]]=row
                built+=1
                if built>=max_new_days:
                    break
            except Exception as exc:
                errors.append(f"{day}: {type(exc).__name__}: {exc}")
                print("ERA5 north-polar maps not available:", errors[-1], flush=True)
        if not by_date:
            raise RuntimeError("No real ERA5 north-polar temperature/anomaly maps available: "+
                               " | ".join(errors)) 
    records=sorted(by_date.values(), key=lambda r:r["date"], reverse=True)[:12]
    payload={
        "schema":1,"ready":True,
        "source":"Copernicus Climate Change Service (C3S) / ECMWF ERA5",
        "daily_dataset":DAILY_DATASET, "monthly_dataset":MONTHLY_DATASET,
        "daily_doi":DOI_DAILY, "monthly_doi":DOI_MONTHLY,
        "parameter":"2m_temperature", "statistic":"daily_mean",
        "frequency":"1_hourly", "time_zone":"UTC+00:00",
        "reference_period":"1991-2020", "anomaly_reference":"monthly_mean_same_calendar_month",
        "domain":"80°N–90°N, 180°W–180°E", "grid_resolution_degrees":RESOLUTION,
        "area_mean":"cos(latitude) weighting on displayed regular lat-lon grid",
        "forecast":False, "latest_date":records[0]["date"],"days":records,
        "generated_utc":datetime.now(timezone.utc).isoformat(timespec="seconds")
    }
    validate_manifest(payload, output)
    index.parent.mkdir(parents=True, exist_ok=True)
    temp=index.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    os.replace(temp,index)
    return payload


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=OUTPUT)
    parser.add_argument("--max-new-days",type=int,default=2)
    args=parser.parse_args()
    result=build(output=args.output,max_new_days=args.max_new_days)
    print(f"Ready: {result['latest_date']} | {len(result['days'])} available real ERA5 maps")


if __name__=="__main__":
    main()
