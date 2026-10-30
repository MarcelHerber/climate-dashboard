#!/usr/bin/env python3
"""Etappe 2 + early Etappe 3: ERA5 polar-cap T, Z, planetary waves and ozone.

Uses small, resumable requests independent of existing zonal wind and map data.
The CDS daily product aggregates four 6-hourly ERA5 fields in UTC.
"""
from __future__ import annotations

import argparse
import calendar
import json
from datetime import date, datetime, timezone

import numpy as np
import update_era5_stratosphere as base

# Retrieve one physical variable at a time to avoid CDS cost limits.
GROUPS = (
    ("temperature", (10, 30, 50, 100), "t"),
    ("geopotential", (10,), "z"),
    ("ozone_mass_mixing_ratio", (50,), "o3"),
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
            elif var == "o3":
                results[day][f"o3cap_{level}"] = base.safe_number(mean*1e6)
            else:
                results[day][f"zcap_{level}"] = base.safe_number(mean/9.80665)
                if level == 10:
                    z60 = base.zonal_at_60(values,lats) / 9.80665
                    results[day]["wave1_10"] = base.safe_number(base.spectral_amplitude(z60,1))
                    results[day]["wave2_10"] = base.safe_number(base.spectral_amplitude(z60,2))
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
                if any(any(k not in existing.get(day,{}) for k in (
                    tuple(f"{group[2]}cap_{level}" for level in group[1])
                    + (("wave1_10","wave2_10") if group[2]=="z" else ())
                )) for day in dates)
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

# Prioritize complete Sep–May seasons surrounding major SSW central dates.
# The dates control retrieval order; they are not synthetic ERA5 values.
PRIORITY_EVENTS = (
    (2009, (date(2010, 2, 9), date(2010, 3, 24))),
    (2017, (date(2018, 2, 12),)),
    (2018, (date(2019, 1, 2),)),
)
TEMPERATURE_LEVELS = (10, 30, 50, 100)
TEMPERATURE_FIELDS = tuple(f"tcap_{level}" for level in TEMPERATURE_LEVELS)


def priority_chunk_plan(start_year):
    """All 5-day calendar chunks September–May, sorted by SSW onset proximity."""
    events = dict(PRIORITY_EVENTS)[start_year]
    chunks = []
    for year, months in ((start_year, range(9, 13)), (start_year + 1, range(1, 6))):
        for month in months:
            end = calendar.monthrange(year, month)[1]
            for first in range(1, end + 1, 5):
                days = tuple(range(first, min(first + 5, end + 1)))
                distance = min(abs((date(year, month, d) - onset).days)
                               for d in days for onset in events)
                chunks.append((distance, year, month, days))
    return sorted(chunks, key=lambda c: (c[0], c[1], c[2], c[3][0]))


def priority_work_plan(rows_by_year, max_chunks):
    """Round-robin the three SSW winters; request only the missing pressure levels."""
    queues = []
    for season, _ in PRIORITY_EVENTS:
        queue = []
        for _, year, month, days in priority_chunk_plan(season):
            existing = rows_by_year.get(year, {})
            stamps = _dates(year, month, days)
            levels = tuple(level for level in TEMPERATURE_LEVELS if
                any(f"tcap_{level}" not in existing.get(day, {}) for day in stamps))
            if levels:
                queue.append((season, year, month, days, levels))
        queues.append(queue)
    result = []
    while len(result) < max_chunks and any(queues):
        for queue in queues:
            if queue and len(result) < max_chunks:
                result.append(queue.pop(0))
    return result


def backfill_priority_temperatures(client, *, max_chunks=9):
    """Retrieve real ERA5 temperatures only; preserve wind, geopotential and ozone."""
    years = sorted({year for season, _ in PRIORITY_EVENTS
                    for year in (season, season + 1)})
    by_year = {year: {row["date"]: row for row in base.read_rows(year)}
               for year in years}
    work = priority_work_plan(by_year, max_chunks)
    completed = 0
    failed = 0
    for season, year, month, days, levels in work:
        print(f"Priority SSW winter {season}/{season+1}: ERA5 T "
              f"{year}-{month:02d} days {days[0]}–{days[-1]}, levels {levels}",
              flush=True)
        try:
            values = retrieve_chunk(client, year, month, days,
                                    ("temperature", levels, "t"))
        except Exception as error:
            failed += 1
            print(f"WARNING: ERA5 priority chunk unavailable, retaining prior data: "
                  f"{year}-{month:02d} days {days}, {error}", flush=True)
            if failed >= 2:
                print("Two ERA5 priority requests failed; preserving completed chunks "
                      "and publishing the partial verified data.", flush=True)
                break
            continue
        existing = by_year[year]
        for day, row in values.items():
            existing[day] = {**existing.get(day, {"date": day}), **row}
        base.store_rows(year, list(existing.values()))
        completed += 1
        print(f"Saved verified ERA5 polar temperature: {year}-{month:02d}, "
              f"{len(existing)} year records", flush=True)
    return completed, not bool(priority_work_plan(by_year, 1)), failed


def priority_self_test():
    """Verify season boundaries, round-robin, missing-level repair and resumability."""
    assert len(PRIORITY_EVENTS) == 3
    for season, _ in PRIORITY_EVENTS:
        plan = priority_chunk_plan(season)
        included = {d for _, year, month, days in plan
                    for d in _dates(year, month, days)}
        assert f"{season}-09-01" in included
        assert f"{season+1}-05-31" in included
        assert f"{season+1}-06-01" not in included
        assert len(included) == (date(season+1, 6, 1)-date(season, 9, 1)).days
    work = priority_work_plan({}, 6)
    assert len(work) == 6 and [r[0] for r in work] == [2009, 2017, 2018]*2
    _, year, month, days, levels = work[0]
    assert levels == TEMPERATURE_LEVELS
    old = {year: {d: {"date": d, "tcap_10": -50.0,
                     "tcap_50": -55.0, "tcap_100": -60.0}
                  for d in _dates(year, month, days)}}
    again = priority_work_plan(old, 3)
    assert again[0][4] == (30,)
    for d in _dates(year, month, days):
        old[year][d]["tcap_30"] = -52.0
    skipped = priority_work_plan(old, 3)
    assert skipped[0][1:4] != (year, month, days)
    print("Priority ERA5 SSW backfill self-test OK", flush=True)


def reference_chunk_plan():
    """Five-day calendar windows in SSW-relevant order (then the remaining year)."""
    windows = []
    for month in range(1, 13):
        for first in range(1, calendar.monthrange(2000, month)[1]+1, 5):
            finish = min(first+4, calendar.monthrange(2000, month)[1])
            canonical = [date(2000, month, day) for day in range(first, finish+1)]
            key = min(abs((point-event).days) for point in canonical
                      for event in (date(2000, 1, 2),date(2000, 2, 9),
                                    date(2000, 2, 12),date(2000, 3, 24)))
            windows.append((key,month,first))
    return sorted(windows)


def climatology_work_plan(rows_by_year, max_chunks):
    """Group equal calendar dates across the 30 reference years to release real
    complete-day means as early as possible, not a partial-year 'climatology'."""
    requests = []
    for _, month, first in reference_chunk_plan():
        for year in range(1991, 2021):
            count = calendar.monthrange(year,month)[1]
            if first>count:
                continue
            days = tuple(range(first,min(first+5,count+1)))
            stamps = _dates(year,month,days)
            old = rows_by_year.get(year,{})
            levels = tuple(level for level in TEMPERATURE_LEVELS if
                any(f"tcap_{level}" not in old.get(d,{}) for d in stamps))
            if levels:
                requests.append((year,month,days,levels))
                if len(requests)>=max_chunks:
                    return requests
    return requests


def backfill_reference_temperatures(client, *, max_chunks=2):
    """Fills four true polar-cap T levels in 1991–2020, without guessing means."""
    years = range(1991,2021)
    by_year = {y:{row["date"]:row for row in base.read_rows(y)} for y in years}
    plan = climatology_work_plan(by_year,max_chunks)
    done,failed = 0,0
    for year,month,days,levels in plan:
        try:
            result=retrieve_chunk(client,year,month,days,("temperature",levels,"t"))
        except Exception as error:
            failed+=1
            print(f"WARNING: reference 1991–2020 {year}-{month:02d} "
                  f"{days[0]}–{days[-1]} failed: {error}",flush=True)
            if failed>=2:
                break
            continue
        for day,row in result.items():
            old=by_year[year].get(day,{"date":day})
            by_year[year][day]={**old,**row}
        base.store_rows(year,list(by_year[year].values()))
        done+=1
        print(f"Saved real reference-temperature chunk {year}-{month:02d} "
              f"{days[0]}–{days[-1]}",flush=True)
    return done,not bool(climatology_work_plan(by_year,1)),failed


def coverage_summary():
    """Report four-level completeness separately from any historical wind data."""
    seasons={}
    all_years={}
    for season,_ in PRIORITY_EVENTS:
        all_years.setdefault(season,{row["date"]:row for row in base.read_rows(season)})
        all_years.setdefault(season+1,{row["date"]:row for row in base.read_rows(season+1)})
        complete,total=0,0
        per_level={str(level):0 for level in TEMPERATURE_LEVELS}
        for year,months in ((season,range(9,13)),(season+1,range(1,6))):
            for month in months:
                for d in range(1,calendar.monthrange(year,month)[1]+1):
                    stamp=f"{year}-{month:02d}-{d:02d}"
                    row=all_years[year].get(stamp,{})
                    total+=1
                    for level in TEMPERATURE_LEVELS:
                        if isinstance(row.get(f"tcap_{level}"),(int,float)):
                            per_level[str(level)]+=1
                    if all(isinstance(row.get(field),(int,float))
                           for field in TEMPERATURE_FIELDS):
                        complete+=1
        seasons[str(season)]={"days_total":total,"all_four_days":complete,
                             "days_per_level":per_level}
    ref_by_year={}
    reference_complete=0
    for year in range(1991,2021):
        rows=all_years.get(year)
        if rows is None:
            rows={r["date"]:r for r in base.read_rows(year)}
        days=366 if calendar.isleap(year) else 365
        good=sum(1 for r in rows.values()
                 if all(isinstance(r.get(field),(int,float))
                        and np.isfinite(r[field]) for field in TEMPERATURE_FIELDS))
        wind_fields=tuple(f"u60_{level}" for level in TEMPERATURE_LEVELS)
        wind_good=sum(1 for r in rows.values()
                      if all(isinstance(r.get(field),(int,float))
                             and np.isfinite(r[field]) for field in wind_fields))
        ref_by_year[str(year)]={"complete_days":good,"wind_complete_days":wind_good,
                               "total_days":days}
        if base.full_year_coverage(year,list(rows.values()),TEMPERATURE_FIELDS):
            reference_complete+=1
    # Only calendar days backed by all 30 years (8 for leap day) qualify.
    reference = base.reference_climatology({
        y:list(all_years.get(y,{}).values()) for y in range(1991,2021)
    })
    def complete_calendar_days(prefix):
        return len(set.intersection(*(
            set(reference.get(f"{prefix}_{level}",{}))
            for level in TEMPERATURE_LEVELS)))
    wind_years=sum(base.full_year_coverage(year,base.read_rows(year),
                    tuple(f"u60_{level}" for level in TEMPERATURE_LEVELS))
                   for year in range(1991,2021))
    return {"priority_seasons":seasons,"reference_1991_2020":{
        "years_complete_four_temperatures":reference_complete,
        "years_complete_four_winds":wind_years,
        "complete_temperature_calendar_days":complete_calendar_days("tcap"),
        "complete_wind_calendar_days":complete_calendar_days("u60"),
        "years":ref_by_year}}


def publish_backfill_status(stats):
    base.OUTPUT.mkdir(parents=True,exist_ok=True)
    summary={"schema_version":1,
             "updated_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "source":"Copernicus C3S ERA5; verified values only",
             "last_run":stats,**coverage_summary()}
    (base.OUTPUT/"backfill_status.json").write_text(
        json.dumps(summary,ensure_ascii=False,separators=(",",":"))+"\n",
        encoding="utf-8")
    print("Polar ERA5 backfill status",json.dumps(
        {"priority":summary["priority_seasons"],
         "reference_completed":summary["reference_1991_2020"][
             "years_complete_four_temperatures"],"run":stats}),flush=True)


def choose_backfill_year():
    endyear=base.last_available_date().year
    for year in [*range(1991,2021),*range(1940,1991),*range(2021,endyear)]:
        rows=base.read_rows(year)
        expected=366 if calendar.isleap(year) else 365
        if len(rows)<expected or any(any(k not in row for k in
             ("tcap_10","tcap_30","tcap_50","tcap_100","zcap_10","wave1_10","wave2_10","o3cap_50")) for row in rows):
            return year
    return None

def test():
    lat=np.arange(90,59,-1)
    lon=np.arange(-180,180,1)
    from xarray import DataArray, Dataset
    dims=("valid_time","latitude","longitude")
    coords={"valid_time":np.array(["2026-10-01","2026-10-02"],dtype="datetime64[ns]"),
            "latitude":lat, "longitude":lon,"pressure_level": [10,30,50,100]}
    temp=np.stack([np.full((2,len(lat),len(lon)),v) for v in (225.,230.,235.,245.)],axis=1)
    z=np.full((2,4,len(lat),len(lon)),30000.*9.80665)
    o3=np.full((2,4,len(lat),len(lon)),4e-6)
    ds=Dataset({"t":DataArray(temp,dims=("valid_time","pressure_level","latitude","longitude"),coords=coords),
                "z":DataArray(z,dims=("valid_time","pressure_level","latitude","longitude"),coords=coords),
                "o3":DataArray(o3,dims=("valid_time","pressure_level","latitude","longitude"),coords=coords)})
    days=["2026-10-01","2026-10-02"]
    t=_cap_rows(ds,"t",(10,30,50,100),days)
    g=_cap_rows(ds,"z",(10,),days)
    o=_cap_rows(ds,"o3",(50,),days)
    assert abs(t[days[0]]["tcap_10"]-(225.-273.15))<.001
    assert abs(t[days[1]]["tcap_100"]-(245.-273.15))<.001
    assert abs(t[days[0]]["tcap_30"]-(230.-273.15))<.001
    assert abs(g[days[0]]["zcap_10"]-30000)<.001
    assert abs(o[days[0]]["o3cap_50"]-4)<.001
    assert abs(g[days[0]]["wave1_10"])<.001
    assert abs(g[days[0]]["wave2_10"])<.001
    print("ERA5 polar-cap stage-2 scientific self-test OK")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--current",action="store_true")
    parser.add_argument("--backfill-one",action="store_true")
    parser.add_argument("--priority-backfill",action="store_true",
                        help="fill historical SSW winters 2009/10, 2017/18 and 2018/19 first")
    parser.add_argument("--priority-chunks",type=int,default=9,
                        help="max sequential priority 5-day ERA5 requests")
    parser.add_argument("--climatology-backfill",action="store_true",
                        help="also fill 1991–2020 temperature baseline in shared calendar windows")
    parser.add_argument("--climatology-chunks",type=int,default=2,
                        help="max real 5-day requests for climatology per run")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        test()
        priority_self_test()
        assert len(reference_chunk_plan())>70
        early=climatology_work_plan({},4)
        assert [r[0] for r in early]==[1991,1992,1993,1994]
        assert all(len(r[3])==4 for r in early)
        print("ERA5 climatology reference scheduling self-test OK",flush=True)
        return
    if not any((args.current, args.backfill_one, args.priority_backfill, args.climatology_backfill)):
        parser.error("Select --current, --priority-backfill or --backfill-one")
    if not 1 <= args.priority_chunks <= 30 or not 1 <= args.climatology_chunks <= 12:
        parser.error("Priority chunks must be 1..30; climatology chunks 1..12")
    import cdsapi
    client=cdsapi.Client(quiet=False,progress=False)
    run_stats={"current":bool(args.current),"priority_chunks_completed":0,
               "climatology_chunks_completed":0,"climatology_errors":0,
               "errors":[]}
    if args.current:
        for year in range(2026,base.last_available_date().year+1):
            try:
                done=update_year_polar(client,year,current=True,max_chunks=2)
                print(f"Stage 2 current {year}: {done} new chunks",flush=True)
            except Exception as error:
                run_stats["errors"].append(f"current {year}: {error}")
                print(f"WARNING: current ERA5 cap download unavailable: {error}",
                      flush=True)
    priority_incomplete = False
    if args.priority_backfill:
        try:
            done, finished, p_failed = backfill_priority_temperatures(
                client, max_chunks=args.priority_chunks)
            priority_incomplete = not finished
            run_stats["priority_chunks_completed"]=done
            run_stats["priority_errors"]=p_failed
            run_stats["priority_complete"]=finished
            print(f"Priority SSW ERA5 chunks in this run: {done}; "
                  f"all target windows complete: {finished}",flush=True)
        except Exception as error:
            priority_incomplete=True
            run_stats["errors"].append(f"priority: {error}")
            print(f"WARNING: priority backfill failed: {error}",flush=True)
    if args.climatology_backfill:
        try:
            c_done,c_finished,c_failed=backfill_reference_temperatures(
                client,max_chunks=args.climatology_chunks)
            run_stats["climatology_chunks_completed"]=c_done
            run_stats["climatology_errors"]=c_failed
            run_stats["climatology_complete"]=c_finished
        except Exception as error:
            run_stats["errors"].append(f"climatology: {error}")
            print(f"WARNING: climatology temperature run failed: {error}",
                  flush=True)
    if args.backfill_one and not priority_incomplete:
        year=choose_backfill_year()
        if year is not None:
            try:
                done=update_year_polar(client,year,max_chunks=1)
                print(f"Stage 2 historical {year}: {done} new chunks",flush=True)
            except Exception as error:
                run_stats["errors"].append(f"regular history {year}: {error}")
                print(f"WARNING: regular history {year} failed: {error}",flush=True)
    elif args.backfill_one:
        print("Defer regular historical stage-2 backfill until SSW temperature "
              "priority windows complete.",flush=True)
    base.rebuild_index()
    publish_backfill_status(run_stats)

if __name__=="__main__":
    main()
