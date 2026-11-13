#!/usr/bin/env python3
"""NOAA CPC observation-only European temperature anomalies, 1991–2020 normals.

Daily value = (observed Tmax + Tmin)/2. This is NOT the 24h-mean temperature.
NOAA PSL CPC Global Unified Temperature uses gridded GTS station observations.
All baselines come from the matching NOAA 1991–2020 daily normal products.
"""
from __future__ import annotations

import argparse
import base64
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

SOURCE = "https://psl.noaa.gov/thredds/dodsC/Datasets/cpc_global_temp/"
WEST, EAST, SOUTH, NORTH = -25.0, 45.0, 34.0, 72.0
FILL = -32768
REFERENCE_MIN_YEARS = 10
EUROPE = {
    "Albania", "Andorra", "Armenia", "Austria", "Azerbaijan", "Belarus",
    "Belgium", "Bosnia and Herzegovina", "Bulgaria", "Croatia", "Cyprus",
    "Czechia", "Czech Republic", "Denmark", "Estonia", "Finland", "France",
    "Georgia", "Germany", "Greece", "Hungary", "Iceland", "Ireland", "Italy",
    "Kosovo", "Latvia", "Liechtenstein", "Lithuania", "Luxembourg", "Malta",
    "Moldova", "Montenegro", "Netherlands", "North Macedonia", "Norway",
    "Poland", "Portugal", "Romania", "Russia", "San Marino", "Serbia",
    "Slovakia", "Slovenia", "Spain", "Sweden", "Switzerland", "Turkey",
    "Türkiye", "Ukraine", "United Kingdom", "Vatican", "Vatican City",
}
DISPLAY = {
    "Austria":"Österreich","Belgium":"Belgien","Belarus":"Belarus",
    "Bosnia and Herzegovina":"Bosnien-Herzegowina","Bulgaria":"Bulgarien",
    "Croatia":"Kroatien","Czechia":"Tschechien","Czech Republic":"Tschechien",
    "Denmark":"Dänemark","Estonia":"Estland","Finland":"Finnland",
    "France":"Frankreich","Germany":"Deutschland","Greece":"Griechenland",
    "Hungary":"Ungarn","Iceland":"Island","Ireland":"Irland","Italy":"Italien",
    "Latvia":"Lettland","Lithuania":"Litauen","Luxembourg":"Luxemburg",
    "Moldova":"Moldau","Montenegro":"Montenegro","Netherlands":"Niederlande",
    "North Macedonia":"Nordmazedonien","Norway":"Norwegen","Poland":"Polen",
    "Portugal":"Portugal","Romania":"Rumänien","Russia":"Russland",
    "Serbia":"Serbien","Slovakia":"Slowakei","Slovenia":"Slowenien",
    "Spain":"Spanien","Sweden":"Schweden","Switzerland":"Schweiz",
    "Turkey":"Türkei","Türkiye":"Türkei","Ukraine":"Ukraine",
    "United Kingdom":"Großbritannien","Albania":"Albanien",
}

def day_number(day: date) -> int:
    """1 Jan is 0; leap-day uses separate interpolation; 1 Mar is always 59."""
    if (day.month, day.day) == (2, 29):
        return -1
    return (date(2001, day.month, day.day) - date(2001, 1, 1)).days

def daily_reference(normals: np.ndarray, day: date) -> np.ndarray:
    if (day.month, day.day) == (2, 29):
        return (normals[58] + normals[59]) / 2.0
    return normals[day_number(day)]

def grid_bounds(ds: xr.Dataset) -> tuple[slice, slice, slice]:
    lat = np.asarray(ds["lat"].values, dtype=float)
    lon = np.asarray(ds["lon"].values, dtype=float)
    ys = np.where((lat >= SOUTH) & (lat <= NORTH))[0]
    west = np.where((lon >= (360 + WEST)) & (lon <= 359.99))[0]
    east = np.where((lon >= 0) & (lon <= EAST))[0]
    if len(ys) < 70 or len(west) < 45 or len(east) < 80:
        raise RuntimeError("NOAA grid coverage missing")
    return slice(int(ys[0]), int(ys[-1]) + 1), slice(int(west[0]), int(west[-1]) + 1), slice(int(east[0]), int(east[-1]) + 1)

def read_subset(filename: str, variable: str, time_range: slice | None = None, *,
                count: bool = False) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    """Read only Europe via two contiguous OPeNDAP lon slabs."""
    url = SOURCE + filename
    with xr.open_dataset(url, engine="netcdf4", decode_times=False) as ds:
        ys, west, east = grid_bounds(ds)
        time_slice = time_range or slice(None)
        var = "valid_yr_count" if count else variable
        left = ds[var].isel(time=time_slice, lat=ys, lon=west).load().values
        right = ds[var].isel(time=time_slice, lat=ys, lon=east).load().values
        field = np.concatenate([left, right], axis=-1).astype(np.float32)
        times = np.asarray(ds["time"].isel(time=time_slice).values, dtype=float)
        lat = np.asarray(ds["lat"].isel(lat=ys).values, dtype=float)
        lon = np.concatenate([
            np.asarray(ds["lon"].isel(lon=west).values, dtype=float) - 360.0,
            np.asarray(ds["lon"].isel(lon=east).values, dtype=float)
        ])
        field[(field < -150) | (field > 150)] = np.nan if not count else 0
        return field, lat, lon, times

def actual_dates(times: np.ndarray) -> list[date]:
    origin = datetime(1900, 1, 1)
    return [(origin + timedelta(hours=float(x))).date() for x in times]

def countries_and_overlay(lat: np.ndarray, lon: np.ndarray, out: Path):
    from cartopy.io import shapereader
    from PIL import Image, ImageDraw
    from shapely import contains_xy
    from shapely.geometry import MultiPolygon, Polygon, box

    shp = shapereader.natural_earth(resolution="50m", category="cultural", name="admin_0_countries")
    frame = box(WEST, SOUTH, EAST, NORTH)
    grid_lon, grid_lat = np.meshgrid(lon, lat)
    mask = np.full(grid_lon.shape, -1, dtype=np.int16)
    w, h = 1400, 760
    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    nations = []

    def outlines(g):
        if isinstance(g, Polygon):
            yield g.exterior
            for ring in g.interiors:
                yield ring
        elif isinstance(g, MultiPolygon) or hasattr(g, "geoms"):
            for sub in g.geoms:
                yield from outlines(sub)

    for rec in shapereader.Reader(shp).records():
        name = rec.attributes.get("ADMIN") or rec.attributes.get("NAME_EN")
        geom = rec.geometry
        if not geom.intersects(frame):
            continue
        clip = geom.intersection(frame)
        for ring in outlines(clip):
            pts = [((float(x) - WEST) / (EAST - WEST) * w,
                    (NORTH - float(y)) / (NORTH - SOUTH) * h)
                   for x, y in ring.coords]
            if len(pts) > 1:
                draw.line(pts, fill=(67, 79, 88, 188), width=2, joint="curve")
        if name not in EUROPE:
            continue
        inside = contains_xy(geom, grid_lon, grid_lat)
        if not np.any(inside):
            continue
        idx = len(nations)
        mask[inside] = idx
        nations.append({"id":idx,"name":DISPLAY.get(name,name),"source_name":name,
                        "cells":int(np.count_nonzero(inside))})

    names = {item["name"] for item in nations}
    needed = {"Deutschland","Frankreich","Spanien","Italien","Polen","Großbritannien"}
    if not needed.issubset(names):
        raise RuntimeError(f"Unvollständiger Ländermasken-Import: {needed-names}")
    img.save(out / "boundaries.png", optimize=True)
    return mask, nations

def load_current(first_day: date, today: date, lat: np.ndarray, lon: np.ndarray):
    latest = {}
    for year in range(first_day.year, today.year + 1):
        per_var = []
        dates_for_year = None
        for var in ("tmax", "tmin"):
            filename = f"{var}.{year}.nc"
            # Only download requested time steps, never whole-world or full-year arrays.
            with xr.open_dataset(SOURCE + filename, engine="netcdf4", decode_times=False) as ds:
                dates = actual_dates(np.asarray(ds["time"].values,dtype=float))
                ids = [i for i,day in enumerate(dates) if first_day <= day <= today]
                if not ids:
                    continue
                selected = slice(ids[0], ids[-1] + 1)
            data, lat2, lon2, _ = read_subset(filename, var, selected)
            if not np.allclose(lat2,lat) or not np.allclose(lon2,lon):
                raise RuntimeError("NOAA CPC observed grid changed")
            per_var.append(data)
            if dates_for_year is None:
                dates_for_year = dates[ids[0]:ids[-1]+1]
            elif dates_for_year != dates[ids[0]:ids[-1]+1]:
                raise RuntimeError("Tmax/Tmin time axes do not match")
        if len(per_var) != 2 or dates_for_year is None:
            continue
        for i, day in enumerate(dates_for_year):
            latest[day] = (per_var[0][i] + per_var[1][i]) / 2.0
    return latest

def encode_q10(values: np.ndarray) -> str:
    a = np.asarray(values, dtype=np.float32)
    out = np.full(a.shape, FILL, dtype="<i2")
    valid = np.isfinite(a) & (a >= -150) & (a <= 150)
    out[valid] = np.rint(a[valid] * 10).astype("<i2")
    return base64.b64encode(out.tobytes(order="C")).decode("ascii")

def build(out: Path, *, today: date, days: int = 110) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    ref_max, lat, lon, _ = read_subset("tmax.day.ltm.1991-2020.nc", "tmax")
    ref_min, lat2, lon2, _ = read_subset("tmin.day.ltm.1991-2020.nc", "tmin")
    if ref_max.shape[0] != 365 or not np.allclose(lat,lat2) or not np.allclose(lon,lon2):
        raise RuntimeError("Invalid NOAA CPC 1991-2020 normal calendar or grid")
    if ref_min.shape != ref_max.shape:
        raise RuntimeError("Tmax/Tmin reference grids differ")
    # NOAA valid_yr_count protects the normals against poorly sampled cells.
    max_count, _, _, _ = read_subset("tmax.day.ltm.1991-2020.nc", "tmax", count=True)
    min_count, _, _, _ = read_subset("tmin.day.ltm.1991-2020.nc", "tmin", count=True)
    baseline = (ref_max + ref_min) / 2.0
    baseline[(max_count < REFERENCE_MIN_YEARS) | (min_count < REFERENCE_MIN_YEARS)] = np.nan
    countries, nations = countries_and_overlay(lat, lon, out)
    first = today - timedelta(days=days+12)
    observed = load_current(first, today, lat, lon)
    if not observed:
        raise RuntimeError("No NOAA CPC observation dates available")
    candidate_days = sorted(d for d in observed if d < today)
    valid_days = []
    anomalies = []
    coverage = []
    for d in candidate_days:
        norm = daily_reference(baseline, d)
        field = observed[d] - norm
        field[(countries < 0)] = np.nan
        supported = (countries >= 0) & np.isfinite(norm)
        good = int(np.isfinite(field).sum())
        ratio = good / max(1,int(supported.sum()))
        # Do not mistake an incompletely published most-recent observation for a valid day.
        if ratio < 0.60:
            continue
        valid_days.append(d)
        anomalies.append(field)
        coverage.append(round(ratio,3))
    if not valid_days:
        raise RuntimeError("No complete CPC European observation day passed coverage QA")
    last = valid_days[-1]
    minimum = last - timedelta(days=days-1)
    selected = [(d,a,c) for d,a,c in zip(valid_days,anomalies,coverage) if d>=minimum]
    if len(selected) < 30:
        raise RuntimeError("Insufficient NOAA CPC daily history for period selection")
    # Disallow a misleading seasonal average from missing entire days.
    maximum_gap = max((selected[i][0]-selected[i-1][0]).days for i in range(1,len(selected)))
    if maximum_gap > 3:
        raise RuntimeError("CPC archive has gap > 3 days in selected period")
    arr = np.stack([r[1] for r in selected])
    # Idempotent JSON, generated only from real dates/values; never sample or fallback data.
    payload = {
        "schema": 1,
        "provider": "NOAA CPC Global Unified Temperature",
        "source": SOURCE,
        "reference": "NOAA CPC daily long-term means 1991–2020",
        "metric": "(Tmax + Tmin) / 2, kein 24-h-Tagesmittel",
        "grid_degrees": 0.5,
        "data_through": last.isoformat(),
        "first_date": selected[0][0].isoformat(),
        "dates": [x[0].isoformat() for x in selected],
        "coverage": [x[2] for x in selected],
        "lat": np.round(lat,4).tolist(), "lon": np.round(lon,4).tolist(),
        "width":len(lon), "height":len(lat),
        "countries":nations,
        "country_mask_b64":base64.b64encode(countries.astype("<i2").tobytes(order="C")).decode("ascii"),
        "anomaly_q10_b64":encode_q10(arr),
        "missing":FILL,
        "tenths_per_kelvin":10,
        "preliminary_days":7,
    }
    (out/"index.json").write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    print(f"NOAA CPC Europa {selected[0][0]}..{last}, {len(selected)} Tage, "
          f"{len(nations)} Länder, Raster {arr.shape}, "
          f"heutige Abdeckung {selected[-1][2]:.1%}")
    return payload

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output",type=Path,default=Path("cpc_europe"))
    p.add_argument("--days",type=int,default=110)
    p.add_argument("--today",type=date.fromisoformat,default=date.today())
    args = p.parse_args()
    if not 30<=args.days<=180:
        p.error("--days must be between 30 and 180")
    build(args.output,today=args.today,days=args.days)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
