#!/usr/bin/env python3
"""ERA5 daily diagnostics at 60N and the northern polar cap.

Only actual CDS values enter published JSON. This module is separate from
scripts/update_era5_europe.py and never edits ERA5 map data.
"""
from __future__ import annotations

import argparse
import calendar
import json
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "era5_stratosphere"
HISTORY = OUTPUT / "history"
CACHE = ROOT / ".era5_stratosphere_cache"
DATASET = "derived-era5-pressure-levels-daily-statistics"
VARS = ["u_component_of_wind", "v_component_of_wind", "temperature",
        "geopotential", "ozone_mass_mixing_ratio", "potential_vorticity"]
LEVELS = ["10", "30", "50", "100"]
METRICS = [
    "u60_10", "u60_30", "u60_50", "u60_100",
    "tcap_10", "tcap_30", "tcap_50", "tcap_100", "zcap_10",
    "wave1_10", "wave2_10", "heatflux_100", "o3cap_50",
    "pv60_10", "ssw_wind_reversal", "ssw_major_events", "nam_10", "vortex_area_10"
]
ALIASES = {"u":"u", "v":"v", "t":"t", "z":"z", "o3":"o3", "pv":"pv"}

def safe_number(value):
    value = float(value)
    return round(value, 4) if np.isfinite(value) else None

def polar_cap_mean(field, lats):
    """Cosine-latitude weighted Arctic mean, 60 through 90 N."""
    lats = np.asarray(lats)
    mask = lats >= 60
    weights = np.cos(np.deg2rad(lats[mask]))[:, None]
    values = np.asarray(field[mask, :], dtype=float)
    valid = np.isfinite(values)
    denominator = np.sum(np.where(valid, weights, 0))
    if denominator <= 0:
        raise ValueError("No valid polar-cap data")
    return float(np.nansum(np.where(valid, values * weights, 0)) / denominator)

def zonal_at_60(field, lats):
    idx = int(np.argmin(abs(np.asarray(lats) - 60.0)))
    if abs(float(lats[idx]) - 60) > 0.51:
        raise ValueError("60N not included in ERA5 selection")
    return np.asarray(field[idx, :], dtype=float)

def spectral_amplitude(longitude_series, harmonic):
    """2*FFT amplitude of geopotential-height departures, gpm."""
    a = np.asarray(longitude_series, dtype=float)
    if a.size < 8 or not np.isfinite(a).all():
        raise ValueError("Incomplete global longitude circle")
    return float(2 * np.abs(np.fft.rfft(a - a.mean())[harmonic]) / a.size)

def daily_diagnostics(fields, lats, longitudes):
    """Compute indicators from daily ERA5 grids for one day, no invented values."""
    lon = np.asarray(longitudes, dtype=float)
    # 0/360 or -180/180 duplicated grid endpoint would bias FFT/means.
    if len(lon) > 2 and np.isclose((lon[-1] - lon[0]) % 360, 0, atol=.01):
        fields = {key: np.asarray(value)[:, :-1] for key, value in fields.items()}
    metric = {}
    for level in (10, 30, 50, 100):
        metric[f"u60_{level}"] = safe_number(
            np.nanmean(zonal_at_60(fields[f"u_{level}"], lats)))
    for level in (10, 30, 50, 100):
        metric[f"tcap_{level}"] = safe_number(
            polar_cap_mean(fields[f"t_{level}"], lats) - 273.15)
    metric["zcap_10"] = safe_number(
        polar_cap_mean(fields["z_10"], lats) / 9.80665)
    z60 = zonal_at_60(fields["z_10"], lats) / 9.80665
    metric["wave1_10"] = safe_number(spectral_amplitude(z60, 1))
    metric["wave2_10"] = safe_number(spectral_amplitude(z60, 2))
    v = zonal_at_60(fields["v_100"], lats)
    t = zonal_at_60(fields["t_100"], lats)
    metric["heatflux_100"] = safe_number(np.nanmean(
        (v - np.nanmean(v)) * (t - np.nanmean(t))))
    metric["o3cap_50"] = safe_number(
        polar_cap_mean(fields["o3_50"], lats) * 1e6)  # kg/kg -> mg/kg
    metric["pv60_10"] = safe_number(
        np.nanmean(zonal_at_60(fields["pv_10"], lats)) * 1e6)
    metric["ssw_wind_reversal"] = int(metric["u60_10"] < 0)
    # Major SSW / NAM / vortex-area require complete winters or calibration;
    # never silently substitute a wind reversal for a formal SSW event.
    return metric

def open_cds_file(path):
    """Read NetCDF or zip-of-NetCDF downloaded from CDS."""
    if not zipfile.is_zipfile(path):
        with xr.open_dataset(path) as ds:
            return ds.load()
    with tempfile.TemporaryDirectory() as temporary:
        files = []
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if member.lower().endswith((".nc", ".netcdf")):
                    target = Path(temporary) / Path(member).name
                    target.write_bytes(archive.read(member))
                    files.append(target)
        if not files:
            raise ValueError("CDS ZIP contains no NetCDF files")
        datasets = []
        for name in files:
            with xr.open_dataset(name) as ds:
                datasets.append(ds.load())
        return xr.combine_by_coords(datasets) if len(datasets) > 1 else datasets[0]

def select_array(ds, varname, pressure):
    candidates = (varname,)
    long_names = {
        "u":("u_component_of_wind",), "v":("v_component_of_wind",),
        "t":("temperature",), "z":("geopotential",),
        "o3":("ozone_mass_mixing_ratio",), "pv":("potential_vorticity",)
    }
    for name in candidates + long_names[varname]:
        if name in ds.data_vars:
            a = ds[name]
            break
    else:
        raise ValueError(f"Missing ERA5 variable {varname}; found {list(ds.data_vars)}")
    level_dim = next((name for name in ("pressure_level", "level", "isobaricInhPa") if name in a.dims), None)
    if level_dim:
        a = a.sel({level_dim:float(pressure)})
    for dimension in list(a.dims):
        if dimension in ("expver", "number") and a.sizes[dimension] > 1:
            combined = a.isel({dimension:0},drop=True)
            for i in range(1, a.sizes[dimension]):
                combined = combined.combine_first(a.isel({dimension:i},drop=True))
            a = combined
        elif dimension in ("expver", "number"):
            a = a.isel({dimension:0},drop=True)
    return a

def normalized_data(ds):
    sample = select_array(ds, "u", 10)
    time_dim = next((k for k in ("valid_time", "time", "date") if k in sample.dims), None)
    lat_dim = next((k for k in ("latitude", "lat") if k in sample.dims), None)
    lon_dim = next((k for k in ("longitude", "lon") if k in sample.dims), None)
    if not all((time_dim, lat_dim, lon_dim)):
        raise ValueError(f"Unexpected ERA5 dimensions: {sample.dims}")
    times = [str(np.datetime64(x, "D")) for x in sample[time_dim].values]
    lats = np.asarray(sample[lat_dim].values, dtype=float)
    lons = np.asarray(sample[lon_dim].values, dtype=float)
    variables = {f"{name}_{level}": select_array(ds, name, level)
                 for name, level in (
                     ("u",10),("u",30),("u",50),("u",100),
                     ("t",10),("t",30),("t",50),("t",100),("z",10),
                     ("v",100),("o3",50),("pv",10))}
    out = {}
    for key, array in variables.items():
        array = array.transpose(time_dim, lat_dim, lon_dim)
        if array.sizes[time_dim] != len(times):
            raise ValueError("ERA5 time axes do not match")
        out[key] = np.asarray(array.values, dtype=float)
    return times, lats, lons, out

def _wind_rows_from_dataset(dataset, levels, requested):
    """Read actual ERA5 u at 60 N; reject truncated longitude coverage."""
    result = {}
    expected = set(requested)
    for level in levels:
        series = select_array(dataset, "u", level)
        timedim = next((d for d in ("valid_time","time","date") if d in series.dims), None)
        latdim = next((d for d in ("latitude","lat") if d in series.dims), None)
        londim = next((d for d in ("longitude","lon") if d in series.dims), None)
        if not (timedim and latdim and londim):
            raise ValueError(f"Unexpected CDS ERA5 wind dimensions {series.dims}")
        lats = np.asarray(series[latdim].values, dtype=float)
        lons = np.asarray(series[londim].values, dtype=float)
        idx = int(np.argmin(abs(lats-60)))
        if abs(lats[idx]-60) > 0.51:
            raise ValueError("ERA5 60N latitude missing")
        if len(lons) < 100 or np.ptp(lons) < 350:
            raise ValueError("Incomplete ERA5 longitude circle at 60N")
        selected = series.isel({latdim:idx}).transpose(timedim,londim)
        values = np.asarray(selected.values,dtype=float)
        dates = [str(np.datetime64(t,"D")) for t in selected[timedim].values]
        if set(dates) != expected or len(dates) != len(expected):
            raise ValueError(f"ERA5 days incomplete: requested {sorted(expected)}, received {dates}")
        for day, row in zip(dates,values):
            # Drop the repeated longitude endpoint (e.g. -180 and +180).
            if len(lons)>1 and np.isclose((lons[-1]-lons[0]),360,atol=.01):
                row = row[:-1]
            if not np.isfinite(row).all():
                raise ValueError(f"Non-finite ERA5 u at {level} hPa on {day}")
            result.setdefault(day,{"date":day})[f"u60_{level}"] = safe_number(np.mean(row))
    return result


def retrieve_wind_chunk(client, year, month, days, levels=(10,30,50,100)):
    """Request a narrow global 60N band; split CDS cost-limited jobs recursively."""
    CACHE.mkdir(parents=True,exist_ok=True)
    days = tuple(sorted(days))
    levels = tuple(levels)
    key = f"u60_{year}_{month:02d}_d{days[0]:02d}-{days[-1]:02d}_l{'-'.join(map(str,levels))}_v2.zip"
    path = CACHE/key
    if not path.exists() or path.stat().st_size==0:
        request = {
            "product_type":"reanalysis",
            "variable":["u_component_of_wind"],
            "pressure_level":[str(level) for level in levels],
            "year":str(year),
            "month":[f"{month:02d}"],
            "day":[f"{day:02d}" for day in days],
            "daily_statistic":"daily_mean",
            "time_zone":"utc+00:00",
            "frequency":"6_hourly",
            "area":[61,-180,59,180],
            "grid":"1/1"
        }
        print(f"CDS ERA5 u at 60N {year}-{month:02d}, days {days}, levels {levels}",flush=True)
        try:
            client.retrieve(DATASET,request,str(path))
        except Exception as exc:
            path.unlink(missing_ok=True)
            # CDS charges by requested field volume. Retry smaller real requests.
            if "cost limits exceeded" in str(exc).lower() or "too large" in str(exc).lower():
                if len(days)>1:
                    split = len(days)//2
                    a=retrieve_wind_chunk(client,year,month,days[:split],levels)
                    b=retrieve_wind_chunk(client,year,month,days[split:],levels)
                    a.update(b)
                    return a
                if len(levels)>1:
                    split = len(levels)//2
                    a=retrieve_wind_chunk(client,year,month,days,levels[:split])
                    b=retrieve_wind_chunk(client,year,month,days,levels[split:])
                    for day,row in b.items():
                        a.setdefault(day,{"date":day}).update(row)
                    return a
            raise
    try:
        ds=open_cds_file(path)
        return _wind_rows_from_dataset(ds,levels,
            [f"{year}-{month:02d}-{d:02d}" for d in days])
    except Exception:
        path.unlink(missing_ok=True)
        raise


def read_rows(year):
    path = HISTORY / f"{year}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["series"] if payload.get("schema_version") == 1 else []

def store_rows(year, rows):
    HISTORY.mkdir(parents=True, exist_ok=True)
    ordered = sorted({row["date"]:row for row in rows}.values(), key=lambda r:r["date"])
    payload = {"schema_version":1, "year":year, "series":ordered}
    (HISTORY / f"{year}.json").write_text(
        json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")

def last_available_date():
    # CDS daily ERA5 has about a six-day delay; avoid incomplete most recent days.
    return datetime.now(timezone.utc).date() - timedelta(days=8)

def update_year(client, year, *, current=False, max_chunks=3):
    """Incrementally publish authentic Stage-1 zonal-wind data, newest first."""
    cutoff = last_available_date() if current else date(year,12,31)
    by_date={row["date"]:row for row in read_rows(year)}
    months=range(12,0,-1) if current else range(1,13)
    processed=0
    for month in months:
        if processed>=max_chunks:
            break
        if date(year,month,1)>cutoff:
            continue
        day_count=calendar.monthrange(year,month)[1]
        if year==cutoff.year and month==cutoff.month:
            day_count=min(day_count,cutoff.day)
        chunks=[list(range(start,min(start+5,day_count+1)))
                for start in range(1,day_count+1,5)]
        if current:
            chunks.reverse()
        for days in chunks:
            if processed>=max_chunks:
                break
            stamp=[f"{year}-{month:02d}-{day:02d}" for day in days]
            if all(all(isinstance(by_date.get(day,{}).get(f"u60_{lev}"), (int,float))
                           and np.isfinite(by_date[day][f"u60_{lev}"])
                           for lev in (10,30,50,100))
                   for day in stamp):
                continue
            try:
                rows=retrieve_wind_chunk(client,year,month,days)
            except Exception as error:
                print(f"ERROR: real ERA5 wind could not be retrieved: {error}",flush=True)
                # Keep verified earlier data. If no data exist, fail clearly at fetch.
                if not by_date:
                    raise
                return len(by_date)
            for day,row in rows.items():
                values={**by_date.get(day,{"date":day}),**row}
                if "u60_10" in values:
                    values["ssw_wind_reversal"]=int(values["u60_10"]<0)
                by_date[day]=values
            store_rows(year,list(by_date.values()))
            processed+=1
            print(f"Saved {len(rows)} real 60N daily ERA5 wind records; total {len(by_date)} in {year}",flush=True)
    return len(by_date)


def choose_backfill_year():
    cutoff = last_available_date().year
    priority = list(range(1991,2021)) + list(range(1940,1991)) + list(range(2021,cutoff))
    for year in priority:
        # Temperature-only rows are not a complete wind archive. Verify all
        # actual dates and four finite 60 N winds before advancing to the next year.
        rows = {row["date"]:row for row in read_rows(year)}
        expected = {date(year,1,1) + timedelta(days=i) for i in
                    range(366 if calendar.isleap(year) else 365)}
        if any((stamp.isoformat() not in rows or
                any(not isinstance(rows[stamp.isoformat()].get(f"u60_{level}"),(int,float))
                    or not np.isfinite(rows[stamp.isoformat()][f"u60_{level}"])
                    for level in (10,30,50,100))) for stamp in expected):
            return year
    return None

def reference_climatology(all_years):
    reference = {}
    # Full coverage is mandatory: never display a partly sampled 1991–2020 climatology.
    for metric in METRICS:
        by_day = {}
        for year in range(1991,2021):
            for row in all_years.get(year,[]):
                number = row.get(metric)
                if isinstance(number,(int,float)) and np.isfinite(number):
                    by_day.setdefault(row["date"][5:],[]).append(float(number))
        eligible = {}
        for day,values in by_day.items():
            required = 8 if day == "02-29" else 30
            if len(values) == required:
                eligible[day] = {
                    "mean":safe_number(np.mean(values)),
                    "p10":safe_number(np.percentile(values,10)),
                    "p90":safe_number(np.percentile(values,90))
                }
        if eligible:
            reference[metric] = eligible
    return reference

def rebuild_index():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    years = sorted(int(path.stem) for path in HISTORY.glob("????.json"))
    rows_by_year = {year:read_rows(year) for year in years}
    rows = [row for year in years for row in rows_by_year[year]]
    if not rows:
        print("No verified daily values; leaving existing index untouched.",flush=True)
        return
    payload = {
        "schema_version":1,
        "ready":True,
        "source_name":"Copernicus C3S ERA5 daily pressure-level statistics",
        "source_dataset":DATASET,
        "reference_period":"1991–2020",
        # Do not call a year complete unless all four real temperature levels
        # exist on every calendar date. Row coverage alone can be only zonal wind.
        "reference_years_completed":sum(
            len(rows_by_year.get(y,[]))==(366 if calendar.isleap(y) else 365)
            and all(all(isinstance(row.get(f"tcap_{level}"),(int,float))
                        and np.isfinite(row[f"tcap_{level}"])
                        for level in (10,30,50,100))
                    for row in rows_by_year.get(y,[]))
            for y in range(1991,2021)),
        "reference_temperature_years_completed_by_level":{
            str(level):sum(
                len(rows_by_year.get(y,[]))==(366 if calendar.isleap(y) else 365)
                and all(isinstance(row.get(f"tcap_{level}"),(int,float))
                        and np.isfinite(row[f"tcap_{level}"])
                        for row in rows_by_year.get(y,[]))
                for y in range(1991,2021))
            for level in (10,30,50,100)},
        "generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_through":max(row["date"] for row in rows),
        "metrics":METRICS,
        "series":rows,
        "reference":reference_climatology(rows_by_year),
    }
    (OUTPUT / "index.json").write_text(
        json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    print(f"Published index: {len(rows)} genuine days, reference years {payload['reference_years_completed']}/30",flush=True)

def self_test():
    lats=np.arange(90,44,-1,dtype=float)
    lons=np.arange(-180,180,1,dtype=float)
    phase=np.deg2rad(lons)
    a=np.broadcast_to((5*np.cos(phase)+2*np.cos(2*phase)),(len(lats),len(lons)))
    fields={f"u_{lev}":np.full_like(a,15.) for lev in (10,30,50,100)}
    fields.update({f"t_{lev}":np.full_like(a,230.) for lev in (10,30,50,100)})
    fields.update({"z_10":(30000+a)*9.80665,"v_100":np.broadcast_to(np.cos(phase),a.shape),
        "o3_50":np.full_like(a,4e-6),"pv_10":np.full_like(a,2e-5)})
    x=daily_diagnostics(fields,lats,lons)
    assert abs(x["u60_10"]-15)<.001
    assert abs(x["tcap_10"]-(230-273.15))<.001
    assert abs(x["tcap_30"]-(230-273.15))<.001
    assert abs(x["wave1_10"]-5)<.001
    assert abs(x["wave2_10"]-2)<.001
    assert abs(x["o3cap_50"]-4)<.001
    assert x["ssw_wind_reversal"]==0
    print("ERA5 stratosphere offline scientific self-test OK")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--current",action="store_true",help="update recent daily ERA5, starting in 2026")
    parser.add_argument("--backfill-one",action="store_true",help="archive one historical year, prioritizing 1991–2020")
    parser.add_argument("--backfill-chunks",type=int,default=1,
                        help="max number of genuine 5-day wind chunks in the historical year (1..24)")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not 1 <= args.backfill_chunks <= 24:
        parser.error("--backfill-chunks must be between 1 and 24")
    if not (args.current or args.backfill_one):
        parser.error("Select --current and/or --backfill-one")
    import cdsapi
    client=cdsapi.Client(quiet=False,progress=False)
    if args.current:
        for year in range(2026,last_available_date().year+1):
            print(f"Current {year}: {update_year(client,year,current=True)} records")
    if args.backfill_one:
        year=choose_backfill_year()
        if year is not None:
            print(f"Backfilling historical ERA5 year {year}",flush=True)
            update_year(client,year,max_chunks=args.backfill_chunks)
        else:
            print("Historical ERA5 years completed")
    rebuild_index()

if __name__=="__main__":
    main()
