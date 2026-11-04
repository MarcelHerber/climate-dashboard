#!/usr/bin/env python3
"""Add measured DWD daily snow-height stations outside the existing KL archive.

Sources:
  daily/more_precip/historical + recent -> SH_TAG (snow depth, NOT NSH_TAG)
  daily/kl/historical + recent -> SHK_TAG (only IDs absent in more_precip)

The existing high-quality KL station profiles always take precedence for an
identical ID. This importer never invents missing values, treats genuine 0 cm
as a measurement, and does not claim a climate baseline without enough years.

The full CDC network is large. Repeated idempotent Actions runs process a
bounded number of station IDs and publish a truthful completeness manifest.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from build_dwd_snow_height_history import parse_metadata, StationMeta
from build_dwd_snow_height_profiles import (
    HYDRO_AXIS, MIN_ACCEPTED_HISTORY_YEARS, PROFILE_VERSION,
    build_year_archive, build_year_maps, profile_from_cache,
    write_json_compact, reference_status,
)

ROOT = Path(".")
RR_BASE = ("https://opendata.dwd.de/climate_environment/CDC/"
           "observations_germany/climate/daily/more_precip/")
KL_BASE = ("https://opendata.dwd.de/climate_environment/CDC/"
           "observations_germany/climate/daily/kl/")
PROGRESS_PATH = Path("data/snow_additional_import_progress.json")
INDEX_PATH = Path("station_snow_height_additional_index.json")
PROFILE_DIR = Path("station_snow_height_additional_profiles")
YEAR_DIR = Path("station_snow_height_additional_years")
CURRENT_DIR = Path("station_snow_height_additional_current")
BASE_INDEX = Path("station_snow_height_index.json")
USER_AGENT = "ClimateDashboard-SnowCoverage/1.0 (+noncommercial DWD CDC)"
ZIP_MAX_BYTES = 12_000_000
MAX_WORKERS = 14
MAX_STATIONS_PER_RUN = 350
BERLIN = ZoneInfo("Europe/Berlin")

def read_json(path: Path, fallback: Any = None) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))

def request(url: str, tries: int = 3) -> bytes:
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=75) as resp:
                raw = resp.read(ZIP_MAX_BYTES + 1)
            if len(raw) > ZIP_MAX_BYTES:
                raise ValueError("Oversized DWD resource " + url)
            return raw
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt + 1 < tries:
                time.sleep(1.4 * (attempt + 1))
    raise RuntimeError(f"HTTP download failed: {url}: {last}")

def listing(base: str, period: str, kind: str) -> dict[str, list[str]]:
    html = request(base + period + "/").decode("utf-8", "replace")
    suffix = ("_akt.zip" if period == "recent" else "_hist.zip")
    result: dict[str, list[str]] = defaultdict(list)
    # Use filename instead of fragile HTML position or untrusted hrefs.
    full_pattern = (rf"tageswerte_{kind}_\d{{5}}_akt\.zip" if period == "recent"
                    else rf"tageswerte_{kind}_\d{{5}}_\d{{8}}_\d{{8}}_hist\.zip")
    for filename in set(re.findall(full_pattern, html, re.I)):
        if not filename.endswith(suffix):
            continue
        sid = filename.split("_")[2]
        result[sid].append(filename)
    for key in result:
        result[key].sort()
    if not result:
        raise RuntimeError("Empty DWD " + kind + "/" + period + " inventory")
    return dict(result)

def extract_snow_zip(data: bytes, field: str, end: date) -> dict[date, float]:
    """Read only product rows with the exact source-specific snow-depth field."""
    result: dict[date, float] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [name for name in archive.namelist()
                   if name.lower().endswith(".txt")
                   and name.split("/")[-1].lower().startswith("produkt_")]
        if not members:
            raise ValueError("DWD ZIP has no product TXT")
        for member in members:
            with archive.open(member) as source:
                header = source.readline().decode("latin-1", "replace")
                columns = [part.strip().upper() for part in header.strip().split(";")]
                if "MESS_DATUM" not in columns or field not in columns:
                    continue
                di, vi = columns.index("MESS_DATUM"), columns.index(field)
                max_idx = max(di, vi)
                # DWD product files are latin-1; stream rows, do not hold
                # an inflated 100-year ZIP as a giant decoded text string.
                with io.TextIOWrapper(source, encoding="latin-1", errors="replace") as text:
                    for row in csv.reader(text, delimiter=";"):
                        if len(row) <= max_idx:
                            continue
                        stamp = row[di].strip()
                        if len(stamp) != 8 or not stamp.isdigit():
                            continue
                        try:
                            day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
                            value = float(row[vi].replace(",", "."))
                        except (ValueError, OverflowError):
                            continue
                        if day > end or not math.isfinite(value) or value < 0 or value > 2000:
                            continue
                        result[day] = round(value, 1)
    return result

def hydro_year_for(day: date) -> int:
    return day.year + 1 if day.month >= 11 else day.year

def empty_profile(meta: StationMeta, sid: str) -> dict[str, Any]:
    daily = [[md, 0, None, None, None, None, None, None] for md in HYDRO_AXIS]
    return {
        "version": PROFILE_VERSION, "station_id": sid, "name": meta.name,
        "state": meta.state, "height": meta.height, "lat": meta.lat,
        "lon": meta.lon,
        "quality": {
            "hydrological_year_min_coverage": .98,
            "accepted_history_years": 0,
            "observed_history_years": 0,
            "history_start_year": None, "history_end_year": None,
            "meets_30_year_filter": False,
            "reference_years_available": 0,
            "reference_status": "insufficient",
        },
        "reference": {"start_hydrological_year": 1991,
                      "end_hydrological_year": 2020,"available_years":[]},
        "daily_columns": ["month_day","n_reference","median_cm","p16_cm",
                          "p84_cm","p2_5_cm","p97_5_cm","historical_max_cm"],
        "daily": daily, "annual": [],
        "records": {"max_snow_depth_cm": None, "hydrological_years":[]},
    }

def empty_year_archive(sid: str) -> dict[str, Any]:
    return {"version": 1, "station_id": sid, "year_label": "hydrological_year_ending",
            "month_days": HYDRO_AXIS, "years":[]}

def current_payload(sid: str, meta: StationMeta, profile: dict[str, Any],
                    observations: dict[date, float], now: date) -> dict[str, Any] | None:
    year = hydro_year_for(now)
    values = {d:v for d,v in observations.items()
              if hydro_year_for(d) == year and d <= now}
    if not values:
        return None
    cols = profile["daily_columns"]
    mi,vi = cols.index("month_day"), cols.index("median_cm")
    medians = {row[mi]: row[vi] for row in profile["daily"] if row[vi] is not None}
    rows = []
    for day, value in sorted(values.items()):
        baseline = medians.get(day.strftime("%m-%d"))
        rows.append([day.isoformat(), value, baseline,
                     round(value-baseline, 1) if baseline is not None else None])
    highest = max(values.values())
    maxdays = [d.isoformat() for d,v in sorted(values.items()) if v==highest]
    last = max(values)
    return {
        "version":1, "station_id":sid, "name":meta.name, "state":meta.state,
        "height":meta.height, "hydrological_year":year,
        "period_start":f"{year-1}-11-01", "period_end":f"{year}-10-31",
        "columns":["date","snow_cm","reference_median_cm","anomaly_cm"],
        "rows":rows,
        "summary":{
            "last_observation":last.isoformat(),
            "last_value_cm":values[last],
            "last_anomaly_cm":rows[-1][3],
            "max_cm":highest, "max_dates":maxdays,
            "snow_cover_days_observed":{"1":sum(x>=1 for x in values.values())}
        }
    }

def process_one(sid: str, rr_hist: dict[str,list[str]],rr_recent: dict[str,list[str]],
                kl_hist: dict[str,list[str]],kl_recent: dict[str,list[str]],
                metadata: dict[str,StationMeta],today: date) -> tuple[str,Any,str|None]:
    # RR and KL sometimes contain different intervals for the same ID.
    # Read both, then let a valid RR SH_TAG value win on overlapping dates.
    # This also keeps legitimate KL SHK_TAG measurements when RR has gaps.
    observations: dict[date,float] = {}
    good_files = 0
    failures = []
    source_counts: dict[str,int] = {}
    for kind,base,field,hist,recent in (
        ("KL",KL_BASE,"SHK_TAG",kl_hist,kl_recent),
        ("RR",RR_BASE,"SH_TAG",rr_hist,rr_recent),
    ):
        values_for_source: dict[date,float] = {}
        for period,items in (("historical",hist.get(sid,[])),
                             ("recent",recent.get(sid,[]))):
            for fn in items:
                try:
                    values=extract_snow_zip(request(base+period+"/"+fn),field,today)
                    values_for_source.update(values)
                    good_files+=1
                except (OSError,ValueError,RuntimeError,zipfile.BadZipFile) as exc:
                    failures.append(str(exc)[:160])
        if values_for_source:
            source_counts[kind]=len(values_for_source)
            observations.update(values_for_source)
    if not observations:
        if not good_files:
            return sid,None,"; ".join(failures[:2]) or "No readable products"
        return sid,None,None  # no genuinely measured snow-depth days
    kind = "RR+KL" if len(source_counts)>1 else next(iter(source_counts))
    field = "SH_TAG/SHK_TAG" if len(source_counts)>1 else (
        "SH_TAG" if "RR" in source_counts else "SHK_TAG")

    meta = metadata.get(sid) or StationMeta(
        station_id=sid,name="DWD-Station "+sid,state="Unbekannt",
        height=None,lat=None,lon=None)
    # Only hydro years up to 2026 enter historical profiles. Current-year
    # values are exposed by the independent current overlay, not climate stats.
    history_rows = [[d.isoformat(),v] for d,v in sorted(observations.items())
                    if hydro_year_for(d) <= 2026]
    cache_like = {
        "station_id":sid,"name":meta.name,"state":meta.state,
        "height":meta.height,"lat":meta.lat,"lon":meta.lon,
        "rows":history_rows
    }
    if history_rows:
        profile,diag = profile_from_cache(cache_like)
        if profile is None:
            return sid,None,"Profile builder rejected real snow observations"
        archive = build_year_archive(sid,build_year_maps(history_rows))
    else:
        profile, archive = empty_profile(meta,sid),empty_year_archive(sid)
    current = current_payload(sid,meta,profile,observations,today)
    quality=profile["quality"]
    historical_years=quality.get("observed_history_years") or 0
    return sid,{
        "station":{
            "id":sid,"name":meta.name,"state":meta.state,
            "height":meta.height,"lat":meta.lat,"lon":meta.lon,
            "source":f"DWD-{kind} · {field}",
            "accepted_history_years":quality.get("accepted_history_years",0),
            "observed_history_years":historical_years,
            "history_start_year":quality.get("history_start_year"),
            "history_end_year":quality.get("history_end_year"),
            "reference_years_available":quality.get("reference_years_available",0),
            "reference_status":quality.get("reference_status","insufficient"),
            "meets_30_year_filter":quality.get("meets_30_year_filter",False),
            "record_max_cm":profile["records"]["max_snow_depth_cm"],
            "file":f"{PROFILE_DIR}/{sid}.json",
            "year_file":f"{YEAR_DIR}/{sid}.json",
            "current_available": current is not None,
            "current_file":f"{CURRENT_DIR}/{sid}.json" if current else None,
            "last_observation":current["summary"]["last_observation"] if current else None,
            "last_value_cm":current["summary"]["last_value_cm"] if current else None,
            "current_max_cm":current["summary"]["max_cm"] if current else None,
        },
        "profile":profile,"archive":archive,"current":current
    },None

def inventory() -> tuple[dict[str,list[str]], ...]:
    return (
        listing(RR_BASE,"historical","RR"),
        listing(RR_BASE,"recent","RR"),
        listing(KL_BASE,"historical","KL"),
        listing(KL_BASE,"recent","KL"),
    )

def ordered_candidates(rr_hist,rr_recent,kl_hist,kl_recent,exclude:set[str]) -> list[str]:
    # Prioritize active DWD stations; closed historical stations remain
    # candidates and are included in subsequent batches.
    order=[rr_recent,kl_recent,rr_hist,kl_hist]
    candidates=[]
    seen=set(exclude)
    for group in order:
        for sid in sorted(group):
            if sid not in seen:
                seen.add(sid)
                candidates.append(sid)
    return candidates

def self_test() -> None:
    import zipfile
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w") as z:
        z.writestr("produkt_test.txt",
          "STATIONS_ID;MESS_DATUM;QN_6;RS;SH_TAG;NSH_TAG;eor\n"
          "42;20251101;3;0;15;1;eor\n"
          "42;20251102;3;0;0;12;eor\n"
          "42;20251103;3;0;-999;100;eor\n"
          "42;20261101;3;0;7;3;eor\n")
    parsed=extract_snow_zip(b.getvalue(),"SH_TAG",date(2026,11,4))
    assert parsed=={date(2025,11,1):15,date(2025,11,2):0,date(2026,11,1):7}
    assert hydro_year_for(date(2025,11,1))==2026
    fake=StationMeta("00042","Teststation","Hessen",100,50.,8.)
    rr={"00042":["tageswerte_RR_00042_akt.zip"]}
    ordered=ordered_candidates({},rr,{},{"00043":["x"]},{"00043"})
    assert ordered==["00042"]
    cp=current_payload("00042",fake,empty_profile(fake,"00042"),parsed,date(2026,11,4))
    assert cp["summary"]["last_value_cm"]==7
    assert cp["rows"][0][1]==7
    assert not cp["summary"]["last_anomaly_cm"]
    print("DWD snow additional network self-test OK")

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--batch-size",type=int,default=MAX_STATIONS_PER_RUN)
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    batch_size=max(1,min(args.batch_size,800))
    base=read_json(BASE_INDEX,{"stations":[]})
    if not base.get("ready"):
        raise RuntimeError("Existing KL snow index not available")
    base_ids={str(s["id"]) for s in base["stations"]}
    old=read_json(PROGRESS_PATH,{}) or {}
    processed=set(str(s) for s in old.get("processed_ids",[]))
    (rr_hist,rr_recent,kl_hist,kl_recent)=inventory()
    all_candidates=ordered_candidates(rr_hist,rr_recent,kl_hist,kl_recent,base_ids)
    candidates=[sid for sid in all_candidates if sid not in processed][:batch_size]
    # Reuse existing index so each run appends data rather than replacing
    # a previously processed subset. Shared IDs are excluded by the KL index.
    prev=read_json(INDEX_PATH,{"stations":[]})
    stations={str(s["id"]):s for s in prev.get("stations",[])
              if str(s["id"]) not in base_ids}
    metadata={}
    for source,files in ((RR_BASE,"RR_Tageswerte_Beschreibung_Stationen.txt"),
                         (KL_BASE,"KL_Tageswerte_Beschreibung_Stationen.txt")):
        try:
            entries=parse_metadata(request(source+"recent/"+files).decode("latin-1","replace"))
            metadata.update({sid:meta for sid,meta in entries.items()
                             if sid not in metadata or source==RR_BASE})
        except Exception as exc:
            print("Metadata warning",source,exc,flush=True)
    today=datetime.now(BERLIN).date()
    accepted, missing, errors={},[],{}
    print("Candidates",len(all_candidates),"previously scanned",len(processed),
          "this run",len(candidates),flush=True)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures={pool.submit(process_one,sid,rr_hist,rr_recent,kl_hist,kl_recent,
                             metadata,today):sid for sid in candidates}
        for done in as_completed(futures):
            sid=futures[done]
            try:
                _,item,error=done.result()
            except Exception as exc:
                item,error=None,str(exc)
            if error is not None:
                errors[sid]=error
                continue
            processed.add(sid)
            if item is None:
                missing.append(sid)
                continue
            accepted[sid]=item
            stations[sid]=item["station"]
            write_json_compact(PROFILE_DIR/(sid+".json"),item["profile"])
            write_json_compact(YEAR_DIR/(sid+".json"),item["archive"])
            if item["current"]:
                write_json_compact(CURRENT_DIR/(sid+".json"),item["current"])
            else:
                (CURRENT_DIR/(sid+".json")).unlink(missing_ok=True)

    for sid in base_ids:
        stations.pop(sid,None)
    for folder in (PROFILE_DIR,YEAR_DIR,CURRENT_DIR):
        for oldfile in folder.glob("*.json"):
            if oldfile.stem in base_ids:
                oldfile.unlink()
    unresolved=[sid for sid in all_candidates if sid not in processed]
    count_long=sum(int(s.get("accepted_history_years",0))>=30 for s in stations.values())
    all_stations=sorted(stations.values(),key=lambda s:(
        str(s.get("state") or ""),str(s.get("name") or "").casefold(),s["id"]))
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    index={
        "version":1,"ready":True,"generated_at":now,
        "station_count":len(all_stations),"stations_meeting_30_year_filter":count_long,
        "source_note":"DWD CDC RR SH_TAG (Schneehöhe, kein Neuschnee), ergänzt durch KL SHK_TAG.",
        "candidate_count":len(all_candidates),
        "processed_candidate_count":len([sid for sid in processed if sid in all_candidates]),
        "pending_candidate_count":len(unresolved),
        "complete":not unresolved,
        "stations":all_stations,
    }
    write_json_compact(INDEX_PATH,index)
    write_json_compact(PROGRESS_PATH,{
        "version":1,"last_run":now,"processed_ids":sorted(processed),
        "candidate_count":len(all_candidates),
        "pending_candidate_count":len(unresolved),"complete":not unresolved,
        "added_this_run":len(accepted),"not_snow_stations_this_run":len(missing),
        "retry_errors":dict(list(errors.items())[:25]),
        "total_added_stations":len(all_stations)
    })
    print(f"Additional measured snow stations total {len(all_stations)};"
          f" added this run {len(accepted)};"
          f" no valid snow measurements {len(missing)};"
          f" download errors {len(errors)};"
          f" still to scan {len(unresolved)}",flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
