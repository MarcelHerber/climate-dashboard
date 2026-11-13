#!/usr/bin/env python3
"""Verified ERA5 Arctic 60/70/80N maps and 30-day growing archive.

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
LAT_SOUTH = 60.0
REGIONS = (80, 70, 60)
TARGET_ARCHIVE_DAYS = 30
# CDS post-processed daily statistics normally lag by about 6 days.
# Probe D-5 as well: availability can change during the day, and all output
# still requires validated genuine ERA5 grids (never assume source readiness).
EARLIEST_ERA5_AGE_DAYS = 5
ARCHIVE_LOOKBACK_DAYS = 38
DOI_DAILY = "10.24381/cds.4991cf48"
DOI_MONTHLY = "10.24381/cds.f17050d7"
PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")
TEMP_LEVELS = np.arange(-45, 20, 5)
ANOM_LEVELS = np.arange(-15, 18, 3)
# Rendering contract: only publish a map when the polar coastline layer exists.
# Earlier outputs silently omitted it when Cartopy's Natural Earth DownloadWarning
# was accidentally converted to an exception.
BOUNDARY_VERSION = 3
LEGACY_BOUNDARY_VERSION = 2
_BOUNDARY_GEOMETRIES = None


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
        "area": [90, -180, 60, 180],
        "grid": "0.5/0.5",
    }


def monthly_request(month: int) -> dict:
    return {
        "product_type": "monthly_averaged_reanalysis",
        "variable": "2m_temperature",
        "year": [str(y) for y in range(BASELINE_START, BASELINE_END + 1)],
        "month": [f"{month:02d}"],
        "time": "00:00",
        "area": [90, -180, 60, 180],
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
    if lats.size < 60 or lats.min() > 60.01 or lats.max() < 89.99:
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




def load_polar_boundaries():
    """Fetch and validate Natural Earth 10m shorelines plus political borders.

    Unlike the original renderer, neither a download warning nor a cache miss
    is grounds for silently publishing a boundary-free map.  The coastline
    data are downloaded once per runner into Cartopy's Natural Earth cache.
    Subsequent maps reuse the verified geometries.
    """
    global _BOUNDARY_GEOMETRIES
    if _BOUNDARY_GEOMETRIES is not None:
        return _BOUNDARY_GEOMETRIES

    import warnings
    from cartopy.io import shapereader

    def candidates(resolution, category, name):
        with warnings.catch_warnings():
            # DownloadWarning is informational: Cartopy uses it while fetching
            # valid Natural Earth shapefiles for the first time.
            warnings.simplefilter("default")
            path = shapereader.natural_earth(
                resolution=resolution, category=category, name=name)
        geometries = []
        for geom in shapereader.Reader(path).geometries():
            if not geom.is_empty and geom.bounds[3] >= 59.5:
                geometries.append(geom)
        return geometries

    # The 110m line lacks small high-Arctic archipelago detail.  At 10m the
    # Greenland coast, Svalbard, Franz Josef Land and Canadian islands appear.
    coast = candidates("10m", "physical", "coastline")
    if len(coast) < 20:
        raise ValueError(
            f"Natural Earth polar coastline incomplete: {len(coast)} geometries")
    # Administrative boundaries above 80N are sparse; their absence in the
    # *actual 80–90N domain* is not itself a download error.  Require the source
    # dataset to exist, but do not invent or extrapolate national borders.
    borders = candidates("50m", "cultural", "admin_0_boundary_lines_land")
    _BOUNDARY_GEOMETRIES = (coast, borders)
    print(
        f"VERIFIED Natural Earth boundary geometries north of 79.5N: "
        f"{len(coast)} coastlines, {len(borders)} land borders",
        flush=True)
    return _BOUNDARY_GEOMETRIES


def render_map(lats, lons, values, day: date, mode: str, path: Path, mean: float,
               lat_south: int = 80):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import matplotlib.path as mpath
    import cartopy.crs as ccrs
    from cartopy.util import add_cyclic_point

    if mode not in ("temperature", "anomaly"):
        raise ValueError("Unknown map mode")
    if lat_south not in REGIONS:
        raise ValueError("Only 60, 70 and 80 north are valid map extents")
    keep_lat = np.asarray(lats) >= lat_south - 0.01
    if keep_lat.sum() < 20 or np.asarray(lats)[keep_lat].max() < 89.99:
        raise ValueError("Incomplete ERA5 latitude coverage for chosen polar extent")
    lats = np.asarray(lats)[keep_lat]
    values = np.asarray(values)[keep_lat, :]
    order = np.argsort(lons)
    lon = np.asarray(lons)[order]
    grid = np.asarray(values)[:, order]
    wrapped, lon_w = add_cyclic_point(grid, coord=lon)
    levels = TEMP_LEVELS if mode == "temperature" else ANOM_LEVELS
    cmap = plt.get_cmap("RdYlBu_r" if mode == "temperature" else "RdBu_r")
    norm = mcolors.BoundaryNorm(levels, cmap.N, extend="both")
    fig = plt.figure(figsize=(10.4, 10.3), facecolor="#ffffff", dpi=130)
    ax = fig.add_axes([0.12, 0.175, 0.76, 0.69], projection=ccrs.NorthPolarStereo())
    ax.set_extent([-180, 180, lat_south - 0.2, 90], crs=ccrs.PlateCarree())
    theta = np.linspace(0, 2 * np.pi, 220)
    boundary = mpath.Path(np.column_stack([0.5 + .5*np.sin(theta),
                                           0.5 + .5*np.cos(theta)]))
    ax.set_boundary(boundary, transform=ax.transAxes)
    mesh = ax.pcolormesh(lon_w, lats, wrapped, transform=ccrs.PlateCarree(),
                         cmap=cmap, norm=norm, shading="auto", rasterized=True)
    # Keep real coastlines on top of the colored field.  If the geographic
    # source fails, fail the map build rather than silently dropping borders.
    from matplotlib import patheffects
    coast, borders = load_polar_boundaries()
    shore = ax.add_geometries(
        coast, crs=ccrs.PlateCarree(), facecolor="none",
        edgecolor="#142b42", linewidth=1.20, zorder=12)
    shore.set_path_effects([
        patheffects.Stroke(linewidth=2.4, foreground="#f7fbff", alpha=.85),
        patheffects.Normal()])
    if borders:
        line = ax.add_geometries(
            borders, crs=ccrs.PlateCarree(), facecolor="none",
            edgecolor="#25384c", linewidth=.85, linestyle="--", zorder=13)
        line.set_path_effects([
            patheffects.Stroke(linewidth=1.9, foreground="#fff", alpha=.7),
            patheffects.Normal()])
    # Force rendering now: Natural Earth errors must propagate and block publish.
    fig.canvas.draw()
    gl = ax.gridlines(draw_labels=False, linewidth=.6, alpha=.32,
                      color="#43576a", linestyle="--")
    import matplotlib.ticker as mticker
    gl.xlocator = mticker.FixedLocator(np.arange(-180, 180, 30))
    parallels = [p for p in (60, 70, 80, 85) if p >= lat_south]
    gl.ylocator = mticker.FixedLocator(parallels)
    # Graticule and labels support orientation in the largely oceanic 80–90N
    # domain, even where there are no international land borders.
    for latlabel in parallels:
        ax.text(35, latlabel, f"{latlabel}°N", transform=ccrs.PlateCarree(),
                fontsize=8, color="#1b3448", weight="bold",
                zorder=15, ha="left", va="bottom",
                path_effects=[
                    patheffects.withStroke(linewidth=2.2, foreground="white")])
    for lonlabel in (-180, -90, 0, 90):
        label = f"{abs(lonlabel)}°{'W' if lonlabel<0 else ('E' if lonlabel>0 else '')}"
        ax.text(lonlabel, lat_south + .55, label, transform=ccrs.PlateCarree(),
                fontsize=7.5, color="#20384d", zorder=15,
                ha="center", va="center",
                path_effects=[
                    patheffects.withStroke(linewidth=2.0, foreground="white")])
    fig.text(.07, .955, f"KLIMADASHBOARD  |  ARKTIS {lat_south}–90° N",
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
              "feste Legende in allen Regionen"),
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
        if lat.size>=60 and lat.min()<=60.01 and lat.max()>=89.99 and lon.size>=710 and np.isfinite(grid).all():
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



def _region_png(day: date, region: int, mode: str) -> str:
    suffix = "t2m" if mode == "temperature" else "anomaly"
    return f"maps/{suffix}_{region}n_{day:%Y%m%d}.png"


def _region_complete(region: dict, output: Path) -> bool:
    return (region.get("boundary_version") in (LEGACY_BOUNDARY_VERSION, BOUNDARY_VERSION)
            and all(valid_image(output / region[k])
                    for k in ("temperature_png", "anomaly_png")))


def _migrate_legacy(row: dict, output: Path) -> dict | None:
    """Keep already verified >80N images while adding 60/70N from actual ERA5."""
    regions = dict(row.get("regions", {}))
    if not regions and all(k in row for k in ("temperature_png", "anomaly_png")):
        regions["80"] = {k: row[k] for k in (
            "boundary_version", "temperature_png", "anomaly_png",
            "mean_c", "mean_anomaly_k", "min_c", "max_c",
            "min_anomaly_k", "max_anomaly_k") if k in row}
        regions["80"]["boundary_version"] = row.get("boundary_version")
    regions = {key: data for key, data in regions.items()
               if key in tuple(map(str, REGIONS)) and _region_complete(data, output)}
    return {"date": row["date"], "regions": regions} if regions else None


def make_one_day(day: date, client, output: Path, workspace: Path):
    """One full 60–90N ERA5 download -> all 3 independently labeled map pairs."""
    raw = workspace / f"daily_{day:%Y%m%d}.zip"
    client.retrieve(DAILY_DATASET, daily_request(day), str(raw))
    if not raw.exists() or raw.stat().st_size < 2000:
        raise RuntimeError("ERA5 daily data not downloaded")
    lats, lons, kelvin = validate_daily(get_dataarray(raw), day)
    ref_lats, ref_lons, baseline = load_reference(client, day.month, output, workspace)
    if not np.allclose(lats, ref_lats) or not np.allclose(lons, ref_lons):
        raise ValueError("Daily ERA5 grid and 1991–2020 reference mismatch")
    tc = kelvin - 273.15
    anomaly = kelvin - baseline
    regions = {}
    staged = []
    for south in REGIONS:
        keep = lats >= south - .01
        mean_c = cap_mean(tc[keep], lats[keep])
        mean_anomaly = cap_mean(anomaly[keep], lats[keep])
        if not (-65 < mean_c < 25 and -35 < mean_anomaly < 35):
            raise ValueError(f"Implausible ERA5 polar mean for {south}N")
        targets = {
            "temperature_png": _region_png(day, south, "temperature"),
            "anomaly_png": _region_png(day, south, "anomaly")
        }
        for mode, values, mean, key in (
            ("temperature", tc, mean_c, "temperature_png"),
            ("anomaly", anomaly, mean_anomaly, "anomaly_png")
        ):
            dest = workspace / f"{south}_{mode}_{day:%Y%m%d}.png"
            render_map(lats, lons, values, day, mode, dest, mean, lat_south=south)
            if not valid_image(dest):
                raise RuntimeError(f"ERA5 {south}N {mode} PNG failed integrity check")
            staged.append((dest, output / targets[key]))
        regions[str(south)] = {
            "boundary_version": BOUNDARY_VERSION,
            "temperature_png": targets["temperature_png"],
            "anomaly_png": targets["anomaly_png"],
            "mean_c": round(mean_c, 2),
            "mean_anomaly_k": round(mean_anomaly, 2),
            "min_c": round(float(tc[keep].min()), 2),
            "max_c": round(float(tc[keep].max()), 2),
            "min_anomaly_k": round(float(anomaly[keep].min()), 2),
            "max_anomaly_k": round(float(anomaly[keep].max()), 2),
        }
    # Publish only after all six real maps are validated.
    for source, destination in staged:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
    print(f"Verified ERA5 regions {list(regions)}: {day.isoformat()}", flush=True)
    return {"date": day.isoformat(), "regions": regions}


def validate_manifest(data: dict, root: Path) -> None:
    if data.get("schema") != 2 or data.get("ready") is not True:
        raise ValueError("ERA5 polar map index must be ready schema 2")
    if data.get("reference_period") != "1991-2020":
        raise ValueError("ERA5 climate baseline mismatch")
    records = data.get("days")
    if not isinstance(records, list) or not records:
        raise ValueError("ERA5 archive must contain at least one real day")
    seen = set()
    for row in records:
        date.fromisoformat(row["date"])
        if row["date"] in seen: raise ValueError("Duplicate map date")
        seen.add(row["date"])
        regions = row.get("regions", {})
        if not isinstance(regions, dict) or not regions:
            raise ValueError("No verified maps in archived day")
        for key, detail in regions.items():
            if key not in {"60","70","80"}:
                raise ValueError("Unrecognized polar region")
            if detail.get("boundary_version") not in (LEGACY_BOUNDARY_VERSION, BOUNDARY_VERSION):
                raise ValueError("Polar map boundaries not validated")
            for image in ("temperature_png", "anomaly_png"):
                path = Path(detail[image])
                if path.is_absolute() or ".." in path.parts or len(path.parts) != 2 or path.parts[0] != "maps":
                    raise ValueError("Unsafe ERA5 map path")
                if not valid_image(root / path):
                    raise ValueError(f"Missing or invalid ERA5 map: {path}")
            for metric in ("mean_c", "mean_anomaly_k"):
                if not math.isfinite(float(detail[metric])):
                    raise ValueError("Nonfinite ERA5 polar mean")
    if data["latest_date"] != max(row["date"] for row in records):
        raise ValueError("Latest date mismatch")
    if int(data.get("target_days",0)) != TARGET_ARCHIVE_DAYS:
        raise ValueError("Incorrect archive target")


def _candidate_days(today: date):
    """Try the newest plausible CDS day, then complete a 30-day window."""
    return [today - timedelta(days=age)
            for age in range(EARLIEST_ERA5_AGE_DAYS,
                             EARLIEST_ERA5_AGE_DAYS + TARGET_ARCHIVE_DAYS)]


def _selected_rows(by_date: dict, today: date):
    # A 30-day INITIAL backfill, not a 30-day rolling deletion. Once verified,
    # previously published historical days remain in the archive permanently.
    return sorted(by_date.values(), key=lambda r: r["date"], reverse=True)


def build(output: Path = OUTPUT, today: date | None = None, client=None,
          max_new_days: int=4):
    output = Path(output)
    today = today or datetime.now(timezone.utc).date()
    old_path = output / "index.json"
    old = json.loads(old_path.read_text(encoding="utf-8")) if old_path.exists() else {}
    previous = old.get("days", []) if old.get("ready") is True else []
    by_date = {}
    for row in previous:
        migrated = _migrate_legacy(row, output)
        if migrated:
            by_date[row["date"]] = migrated
    missing = [
        day for day in _candidate_days(today)
        if day.isoformat() not in by_date
        or any(str(lat) not in by_date[day.isoformat()]["regions"] for lat in REGIONS)
    ]
    failures=[]
    built=0
    if missing:
        if client is None:
            import cdsapi
            client=cdsapi.Client()
        with tempfile.TemporaryDirectory(prefix="era5-arctic-3region-") as tmp:
            workspace=Path(tmp)
            for day in missing:
                if built>=max_new_days:
                    break
                try:
                    row = make_one_day(day, client, output, workspace)
                    by_date[day.isoformat()] = row
                    built += 1
                except Exception as exc:
                    failures.append(f"{day}: {type(exc).__name__}: {exc}")
                    print("ERA5 candidate unavailable:", failures[-1], flush=True)
                    # Most recent day can lag; don't invent a field.
    records=_selected_rows(by_date, today)
    if not records:
        raise RuntimeError("No real ERA5 Arctic maps available: "+" | ".join(failures))
    payload={
        "schema":2, "ready":True,
        "boundary_version": BOUNDARY_VERSION,
        "boundary_source":"Natural Earth 10m coastline / 50m land borders",
        "source":"Copernicus Climate Change Service (C3S) / ECMWF ERA5",
        "daily_dataset":DAILY_DATASET, "monthly_dataset":MONTHLY_DATASET,
        "daily_doi":DOI_DAILY, "monthly_doi":DOI_MONTHLY,
        "parameter":"2m_temperature", "statistic":"daily_mean",
        "frequency":"1_hourly", "time_zone":"UTC+00:00",
        "reference_period":"1991-2020",
        "anomaly_reference":"monthly_mean_same_calendar_month",
        "regions":[80,70,60], "domain":"60°N–90°N, 180°W–180°E",
        "grid_resolution_degrees":RESOLUTION,
        "fixed_temperature_scale_c":[float(TEMP_LEVELS[0]),float(TEMP_LEVELS[-1])],
        "fixed_anomaly_scale_k":[float(ANOM_LEVELS[0]),float(ANOM_LEVELS[-1])],
        "area_mean":"cos(latitude) weights per selected polar cap",
        "forecast":False,
        "target_days":TARGET_ARCHIVE_DAYS,
        "initial_backfill_days":sum(row["date"] in
            {day.isoformat() for day in _candidate_days(today)} for row in records),
        "archive_policy":"append_only",
        "archive_days":len(records), "fully_mapped_days":sum(
            all(str(lat) in row["regions"] for lat in REGIONS) for row in records),
        "latest_date":records[0]["date"],"days":records,
        "generated_utc":datetime.now(timezone.utc).isoformat(timespec="seconds")
    }
    validate_manifest(payload, output)
    output.mkdir(parents=True, exist_ok=True)
    tmp=old_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp, old_path)
    print(f"Published ERA5 Arctic archive: {len(records)}/{TARGET_ARCHIVE_DAYS} days; "
          f"fully mapped {payload['fully_mapped_days']}; newly mapped {built}")
    return payload

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=OUTPUT)
    parser.add_argument("--max-new-days",type=int,default=4)
    args=parser.parse_args()
    result=build(output=args.output,max_new_days=args.max_new_days)
    print(f"Ready: {result['latest_date']} | {len(result['days'])} available real ERA5 maps")


if __name__=="__main__":
    main()
