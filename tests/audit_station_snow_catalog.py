#!/usr/bin/env python3
"""Check every published DWD snow station JSON without inventing measurements.

Used in CI; verifies base+extra catalogue consistency and all per-station
archives and current records, not merely a handful of sample stations.
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

def load(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf8"))

def main():
    base=load("station_snow_height_index.json")
    extra=load("station_snow_height_additional_index.json")
    current=load("station_snow_height_current_index.json")
    stations=[*base["stations"],*extra["stations"]]
    assert len(stations)==len({str(s["id"]) for s in stations}),"duplicate DWD IDs"
    assert base["station_count"]==len(base["stations"])
    assert extra["station_count"]==len(extra["stations"])
    assert len(stations)>5000,"full additional snow network unavailable"
    valid_points=0
    with_history=0
    current_count=0
    ref_insufficient=0
    quality_30=0
    historic_days=0
    for station in stations:
        sid=str(station["id"])
        profile_path=Path(station["file"])
        year_path=Path(station["year_file"])
        assert profile_path.is_file(), str(profile_path)
        assert year_path.is_file(), str(year_path)
        profile=load(profile_path)
        archive=load(year_path)
        assert str(profile["station_id"])==sid
        assert str(archive["station_id"])==sid
        assert len(profile["daily"])==366,("daily",sid)
        assert len(archive["month_days"])==366,("month_days",sid)
        assert archive["month_days"][0]=="11-01"
        assert archive["month_days"][-1]=="10-31"
        years=archive.get("years",[])
        q=profile["quality"]
        accepted=int(q.get("accepted_history_years",0))
        assert int(station.get("accepted_history_years",0))==accepted,sid
        if station.get("meets_30_year_filter") is not None:
            assert bool(station["meets_30_year_filter"])==(accepted>=30),sid
        if accepted>=30:quality_30+=1
        assert len(years)==int(q.get("observed_history_years",len(years))),sid
        n=0
        for year in years:
            assert len(year["values"])==366,("bad year axis",sid,year["year"])
            n+=sum(v is not None and v>=0 for v in year["values"])
            assert all(v is None or (isinstance(v,(int,float)) and v>=0)
                       for v in year["values"]),("negative/invalid",sid)
        assert n or (station.get("current_available") and station.get("current_file")),sid
        if n:with_history+=1
        historic_days+=n
        if int(q.get("reference_years_available",0))<10:
            ref_insufficient+=1
            assert all(row[2] is None for row in profile["daily"]),("unsafe climatology",sid)
        if station.get("lat") is not None and station.get("lon") is not None:
            lat=float(station["lat"]);lon=float(station["lon"])
            if 47<=lat<=56 and 5<=lon<=16:valid_points+=1
        current_file=station.get("current_file")
        if current_file and station.get("current_available"):
            cpath=Path(current_file)
            assert cpath.is_file(),(sid,cpath)
            payload=load(cpath)
            assert str(payload["station_id"])==sid
            cols=payload["columns"]
            si=cols.index("snow_cm")
            for row in payload["rows"]:
                assert row[si] is not None and row[si]>=0,("current invalid",sid)
            current_count+=1
    assert quality_30>=267
    assert historic_days>100000
    print(json.dumps({
        "checked":len(stations),
        "base":len(base["stations"]),
        "additional":len(extra["stations"]),
        "quality_30":quality_30,
        "station_files_with_history":with_history,
        "current_extra_files_checked":current_count,
        "reference_insufficient_correctly_hidden":ref_insufficient,
        "geolocatable_stations":valid_points,
        "authentic_historical_daily_observations":historic_days,
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
