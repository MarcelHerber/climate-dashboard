#!/usr/bin/env python3
"""FMI Finland current-year daily Tmin/Tmax cache."""
from __future__ import annotations

import argparse
import gzip
import json
import os
import pickle
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import update_fmi_finland_station_cache as hist

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
CURRENT_TMAX_EMERGENCY_CEILING_C = 45.0
CURRENT_TMIN_EMERGENCY_FLOOR_C = -60.0


def log(msg: str = "") -> None:
    print(msg, flush=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"fmi_finland_current_{year}_v{FORMAT_VERSION}.pkl.gz"


def status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"fmi_finland_current_{year}_status.json"


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp_name=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent)); os.close(fd); tmp=Path(tmp_name)
    try:
        with gzip.open(tmp,"wb",compresslevel=6) as f: pickle.dump(obj,f,protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp,path)
    finally: tmp.unlink(missing_ok=True)


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp_name=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent)); os.close(fd); tmp=Path(tmp_name)
    try:
        tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); os.replace(tmp,path)
    finally: tmp.unlink(missing_ok=True)


def record_events(baseline: dict[str, Any], records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    old_records=baseline.get("records",{}); events=[]
    for sid,rec in records.items():
        old=old_records.get(sid)
        if not isinstance(old,dict): continue
        for mmdd,pair in rec.get("calendar_tmax",{}).items():
            prior=old.get("calendar_tmax",{}).get(mmdd)
            if prior is not None and float(pair[0]) > float(prior[0]):
                events.append({"station_id":sid,"date":pair[1],"element":"TMAX","value":float(pair[0]),"previous_value":float(prior[0]),"previous_date":str(prior[1])})
        for mmdd,pair in rec.get("calendar_tmin",{}).items():
            prior=old.get("calendar_tmin",{}).get(mmdd)
            if prior is not None and float(pair[0]) < float(prior[0]):
                events.append({"station_id":sid,"date":pair[1],"element":"TMIN","value":float(pair[0]),"previous_value":float(prior[0]),"previous_date":str(prior[1])})
    events.sort(key=lambda x:(x["date"],x["station_id"],x["element"])); return events


def validate_current_day(sid: str, d: date, tmin: float | None, tmax: float | None) -> None:
    if tmax is not None and float(tmax) > CURRENT_TMAX_EMERGENCY_CEILING_C:
        raise RuntimeError(f"FMI Current Plausibilitätsfehler: {sid} TMAX {tmax} C am {d}")
    if tmin is not None and float(tmin) < CURRENT_TMIN_EMERGENCY_FLOOR_C:
        raise RuntimeError(f"FMI Current Plausibilitätsfehler: {sid} TMIN {tmin} C am {d}")
    if tmin is not None and tmax is not None and tmin > tmax:
        raise RuntimeError(f"FMI Current Plausibilitätsfehler: {sid} TMIN {tmin} > TMAX {tmax} am {d}")


def build_current(cache_dir: Path, year: int, *, force: bool=False) -> Path:
    cache_dir.mkdir(parents=True,exist_ok=True); out=current_path(cache_dir,year)
    if force: out.unlink(missing_ok=True); status_path(cache_dir,year).unlink(missing_ok=True)
    baseline=hist.load_baseline(cache_dir,year-1)
    today=date.today(); through=today if today.year==year else date(year,12,31)
    log("=== FMI FINNLAND AKTUELLES JAHR ==="); log(f"{year} | daily multipointcoverage | {hist.PARAM_TMIN}/{hist.PARAM_TMAX}")

    records: dict[str,dict[str,Any]]={}; inventory=dict(baseline.get("inventory",{})); request_blocks=0
    for start,end in hist.current_blocks(year,through):
        raws=hist.fetch_period(start,end); request_blocks += 1
        for raw in raws:
            inventory_delta,rows=hist.parse_mpc_response(raw)
            for sid,meta in inventory_delta.items():
                old=inventory.get(sid)
                if not isinstance(old,dict): inventory[sid]=meta
                else:
                    for key in ("name","lat","lon","network","source"):
                        value=meta.get(key)
                        if value not in (None,""): old[key]=value
            for sid,d,tmin,tmax in rows:
                if d.year != year: continue
                validate_current_day(sid,d,tmin,tmax)
                if tmin is None and tmax is None: continue
                rec=records.setdefault(sid,hist.empty_record()); hist.consume_day(rec,d,tmin,tmax)
        station_days=sum(int(r.get("observation_days",0)) for r in records.values())
        log(f"FMI Current: {start} bis {end} | {len(records)} Stationsreihen | {station_days:,} Stationstage")

    if not records: raise RuntimeError("FMI Finland Current enthält keine Stationsreihen.")
    first_dates=[r["first_date"] for r in records.values() if r.get("first_date")]; last_dates=[r["last_date"] for r in records.values() if r.get("last_date")]
    first_date=min(first_dates) if first_dates else None; last_date=max(last_dates) if last_dates else None
    station_days=sum(int(r.get("observation_days",0)) for r in records.values())
    latest_by_station={sid:r["last_date"] for sid,r in records.items() if r.get("last_date")}
    events=record_events(baseline,records)
    payload={
        "format_version":FORMAT_VERSION,"source":hist.SOURCE,"country":hist.COUNTRY,"country_code":hist.COUNTRY_CODE,"year":year,"complete":True,
        "parameters":{"TMIN":hist.PARAM_TMIN,"TMAX":hist.PARAM_TMAX},"stored_query":hist.STORED_QUERY,"bbox":hist.FINLAND_BBOX,
        "inventory":inventory,"records":records,"latest_observation_by_station":latest_by_station,"data_first_date":first_date,"data_last_date":last_date,
        "rows_with_temperature":station_days,"record_events":events,"request_blocks":request_blocks,"historical_cutoff_year":year-1,
        "historical_baseline_file":str(hist.baseline_path(cache_dir,year-1)),"public_url":hist.PUBLIC_URL,
    }
    atomic_pickle_gzip(out,payload)
    status={"format_version":FORMAT_VERSION,"source":hist.SOURCE,"country":hist.COUNTRY,"year":year,"complete":True,"station_count":len(records),"inventory_count":len(inventory),"rows_with_temperature":station_days,"data_first_date":first_date,"data_last_date":last_date,"record_event_count":len(events),"request_blocks":request_blocks,"current_file":str(out)}
    atomic_json(status_path(cache_dir,year),status)
    log(); log("=== FMI FINLAND CURRENT SUMMARY ==="); log(f"Stationsreihen mit {year}-Daten: {len(records)}"); log(f"Inventar inkl. Historie: {len(inventory)} FMISIDs"); log(f"Stationstage: {station_days:,}"); log(f"Datenzeitraum: {first_date} bis {last_date}"); log(f"Neue historische Tagesrekorde: {len(events):,}"); log(f"Output: {out}"); log("FMI Finland current OK."); return out


def self_test() -> None:
    baseline={"records":{"100001":{"calendar_tmax":{"08-09":[30.0,"2010-08-09"]},"calendar_tmin":{"08-09":[-2.0,"1999-08-09"]}}}}
    current={"100001":{"calendar_tmax":{"08-09":[31.0,"2026-08-09"]},"calendar_tmin":{"08-09":[-3.0,"2026-08-09"]}}}
    events=record_events(baseline,current); assert len(events)==2 and {x["element"] for x in events}=={"TMAX","TMIN"}
    validate_current_day("100001",date(2026,1,1),-20.0,10.0)
    for tmin,tmax in [(-61.0,-20.0),(-10.0,46.0),(5.0,4.0)]:
        try: validate_current_day("100001",date(2026,1,1),tmin,tmax)
        except RuntimeError: pass
        else: raise AssertionError("FMI Current plausibility guard did not reject bad value")
    print("FMI Finland current-year self-test OK")


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--self-test",action="store_true"); parser.add_argument("--cache-dir",default=str(CACHE_DIR_DEFAULT)); parser.add_argument("--year",type=int,default=date.today().year); parser.add_argument("--force",action="store_true"); args=parser.parse_args()
    if args.self_test: self_test(); return 0
    build_current(Path(args.cache_dir),args.year,force=args.force); return 0

if __name__ == "__main__": raise SystemExit(main())
