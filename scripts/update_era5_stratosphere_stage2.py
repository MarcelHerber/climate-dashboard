#!/usr/bin/env python3
"""Etappe 2: real ERA5 polar-cap daily T (10/50/100 hPa) and Z (10 hPa).

Uses small, resumable requests independent of existing zonal wind and map data.
The CDS daily product aggregates four 6-hourly ERA5 fields in UTC.
"""
from __future__ import annotations

import argparse
import calendar
import json
from datetime import date

import numpy as np
import update_era5_stratosphere as base

# Retrieve one physical variable at a time to avoid CDS cost limits.
GROUPS = (
    ("temperature", (10, 50, 100), "t"),
    ("geopotential", (10,), "z"),
)

def _dates(year, month, days):
    return [f"{year}-{month:02d}-{d:02d}" for d in days]

def _cap_rows(dataset, var, levels, days):
    """Validate coordinate coverage and compute area-weighted polar means."""
    results = {day: {"date": day} for day in days}
    for level in levels:
        da = base.select_array(dataset, var, level)
        time_dim = next((d for d in ("valid_time", "time", "date") if d in da.dims), None)
        lat_dim = next((d for d in ("latitude", "lat") if d in da.dims), None)
        lon_dim = next((d for d in ("longitude", "lon") if d in da.dims), None)
        if not all((time_dim, lat_dim, lon_dim)):
            raise ValueError(f"Unexpected ERA5 coordinates: {da.dims}")
        lats = np.asarray(da[lat_dim].values, dtype=float)
        lons = np.asarray(da[lon_dim].values, dtype=float)
        if lats.size < 20 or abs(lats.max()-90) > .51 or abs(lats.min()-60) > .51:
            raise ValueError("Polar-cap latitude range 60–90 N not complete")
        if lons.size < 180 or np.ptp(lons) < 350:
            raise ValueError("Polar-cap global longitude range not complete")
        field = da.transpose(time_dim, lat_dim, lon_dim)
        observed = [str(np.datetime64(d, "D")) for d in field[time_dim].values]
        if set(observed) != set(days) or len(observed) != len(days):
            raise ValueError(f"Missing daily ERA5 polar-cap data: {observed}")
        for day, values in zip(observed, np.asarray(field.values, dtype=float)):
            if lons.size > 1 and np.isclose(abs(lons[-1]-lons[0]), 360, atol=.01):
                values = values[:, :-1]
            if not np.isfinite(values).all():
                raise ValueError(f"Nonfinite polar cap field on {day}")
            mean = base.polar_cap_mean(values, lats)
            if var == "t":
                results[day][f"tcap_{level}"] = base.safe_number(mean-273.15)
            else:
                results[day][f"zcap_{level}"] = base.safe_number(mean/9.80665)
    return results

def retrieve_chunk(client, year, month, days, group):
    """CDS request with recursive cost-limit splitting, no simulated fallback."""
    variable, levels, short = group
    days = tuple(sorted(days))
    levels = tuple(levels)
    base.CACHE.mkdir(parents=True, exist_ok=True)
    fname = f"cap_{short}_{year}_{month:02d}_d{days[0]:02d}-{days[-1]:02d}_l{'-'.join(map(str,levels))}_v1.zip"
    path = base.CACHE / fname
    if not path.exists() or path.stat().st_size == 0:
        request = {
            "product_type": "reanalysis",
            "variable": [variable],
            "pressure_level": [str(level) for level in levels],
            "year": str(year),
            "month": [f"{month:02d}"],
            "day": [f"{day:02d}" for day in days],
            "daily_statistic": "daily_mean",
            "time_zone": "utc+00:00",
            "frequency": "6_hourly",
            "area": [90, -180, 60, 180],
            "grid": "1/1"
        }
        print(f"CDS ERA5 polar cap {variable} {levels}, {year}-{month:02d} days {days}", flush=True)
        try:
            client.retrieve(base.DATASET, request, str(path))
        except Exception as error:
            path.unlink(missing_ok=True)
            message = str(error).lower()
            if "cost limits exceeded" in message or "too large" in message:
                if len(days)>1:
                    half = len(days)//2
                    left = retrieve_chunk(client,year,month,days[:half],group)
                    right = retrieve_chunk(client,year,month,days[half:],group)
                    return {**left,**right}
                if len(levels)>1:
                    half = len(levels)//2
                    left = retrieve_chunk(client,year,month,days,(variable,levels[:half],short))
                    right = retrieve_chunk(client,year,month,days,(variable,levels[half:],short))
                    return {day:{**left[day],**right[day]} for day in left}
            raise
    try:
        ds = base.open_cds_file(path)
        return _cap_rows(ds, short, levels, _dates(year,month,days))
    except Exception:
        path.unlink(missing_ok=True)
        raise

def update_year_polar(client, year, *, current=False, max_chunks=2):
    """Fill only missing stage-2 fields, preserving all existing Stage-1 data."""
    cutoff = base.last_available_date() if current else date(year,12,31)
    existing = {row["date"]:row for row in base.read_rows(year)}
    completed = 0
    months = range(12,0,-1) if current else range(1,13)
    for month in months:
        if completed >= max_chunks: break
        if date(year,month,1)>cutoff: continue
        n_days = calendar.monthrange(year,month)[1]
        if cutoff.year==year and cutoff.month==month:
            n_days=min(n_days,cutoff.day)
        spans = [list(range(i,min(i+5,n_days+1))) for i in range(1,n_days+1,5)]
        if current: spans.reverse()
        for days in spans:
            if completed >= max_chunks: break
            dates = _dates(year,month,days)
            needs = [
                group for group in GROUPS
                if any(any(f"{group[2]}cap_{level}" not in existing.get(day,{})
                           for level in group[1]) for day in dates)
            ]
            if not needs: continue
            fetched = {day:{"date":day} for day in dates}
            for group in needs:
                result = retrieve_chunk(client,year,month,days,group)
                for day,entry in result.items():
                    fetched[day].update(entry)
            for day,values in fetched.items():
                existing[day]={**existing.get(day,{"date":day}),**values}
            base.store_rows(year,list(existing.values()))
            completed += 1
            print(f"Saved ERA5 polar cap on {dates[0]} … {dates[-1]}; year has {len(existing)} dates",flush=True)
    return completed

def choose_backfill_year():
    endyear=base.last_available_date().year
    for year in [*range(1991,2021),*range(1940,1991),*range(2021,endyear)]:
        rows=base.read_rows(year)
        expected=366 if calendar.isleap(year) else 365
        if len(rows)<expected or any(any(k not in row for k in
             ("tcap_10","tcap_50","tcap_100","zcap_10")) for row in rows):
            return year
    return None

def test():
    lat=np.arange(90,59,-1)
    lon=np.arange(-180,180,1)
    from xarray import DataArray, Dataset
    import numpy as np
    dims=("valid_time","latitude","longitude")
    coords={"valid_time":np.array(["2026-10-01","2026-10-02"],dtype="datetime64[ns]"),
            "latitude":lat, "longitude":lon,"pressure_level": [10,50,100]}
    temp=np.stack([np.full((2,len(lat),len(lon)),v) for v in (225.,235.,245.)],axis=1)
    z=np.full((2,3,len(lat),len(lon)),30000.*9.80665)
    ds=Dataset({"t":DataArray(temp,dims=("valid_time","pressure_level","latitude","longitude"),coords=coords),
                "z":DataArray(z,dims=("valid_time","pressure_level","latitude","longitude"),coords=coords)})
    days=["2026-10-01","2026-10-02"]
    t=_cap_rows(ds,"t",(10,50,100),days)
    g=_cap_rows(ds,"z",(10,),days)
    assert abs(t[days[0]]["tcap_10"]-(225.-273.15))<.001
    assert abs(t[days[1]]["tcap_100"]-(245.-273.15))<.001
    assert abs(g[days[0]]["zcap_10"]-30000)<.001
    print("ERA5 polar-cap stage-2 scientific self-test OK")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--current",action="store_true")
    parser.add_argument("--backfill-one",action="store_true")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        test()
        return
    if not args.current and not args.backfill_one:
        parser.error("Select --current or --backfill-one")
    import cdsapi
    client=cdsapi.Client(quiet=False,progress=False)
    if args.current:
        for year in range(2026,base.last_available_date().year+1):
            print(f"Stage 2 current {year}: {update_year_polar(client,year,current=True,max_chunks=2)} new chunks",flush=True)
    if args.backfill_one:
        year=choose_backfill_year()
        if year is not None:
            print(f"Stage 2 historical {year}: {update_year_polar(client,year,max_chunks=1)} new chunks",flush=True)
    base.rebuild_index()

if __name__=="__main__":
    main()
