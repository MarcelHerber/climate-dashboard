#!/usr/bin/env python3
"""Operational ECMWF Open Data IFS/AIFS North Atlantic extratropical-low tracking.

Uses REAL open-data IFS and AIFS-single MSLP fields (not tropical cyclone BUFR).
Models are downloaded at native public 0.25° grid, cropped to 27-75N,
105W-8W and tracked in 6-hour steps with the same center algorithm as GFS.
These are research MSLP minima, NOT validated named storms or Hart CPS.
"""
from __future__ import annotations
import argparse
import datetime as dt
import importlib.util
import json
import logging
from pathlib import Path
import tempfile
import time
import math

import numpy as np
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_release
from ecmwf.opendata import Client

spec=importlib.util.spec_from_file_location("gfs_cps",Path(__file__).resolve().with_name("update_north_atlantic_cps.py"))
gfs=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gfs)
UTC=dt.timezone.utc
STEPS=list(range(0,73,6))
MODELS={"ifs-atl":("ifs","ECMWF IFS"),
        "aifs-atl":("aifs-single","ECMWF AIFS Single")}

def decode_grib(path):
    """Parse multi-step ECMWF global GRIB and crop to Atlantic sector."""
    times={};unknown=[]
    with path.open("rb") as fp:
        while (handle:=codes_grib_new_from_file(fp)) is not None:
            try:
                short=str(codes_get(handle,"shortName"))
                if short not in ("msl","prmsl"):
                    continue
                try:
                    lead=int(codes_get(handle,"endStep"))
                except Exception:
                    lead=int(codes_get(handle,"step"))
                ni=int(codes_get(handle,"Ni"));nj=int(codes_get(handle,"Nj"))
                values=np.asarray(codes_get_array(handle,"values"),dtype=np.float32).reshape((nj,ni))
                lat=np.asarray(codes_get_array(handle,"latitudes"),dtype=np.float32).reshape((nj,ni))
                lon=np.asarray(codes_get_array(handle,"longitudes"),dtype=np.float32).reshape((nj,ni))
                lon=(lon+180)%360-180
                # A bounding box avoids retaining global 0.25° arrays for all steps.
                mask=(lat>=22)&(lat<=80)&(lon>=-111)&(lon<=-3)
                rows=np.flatnonzero(mask.any(axis=1))
                cols=np.flatnonzero(mask.any(axis=0))
                if rows.size<100 or cols.size<100:
                    raise ValueError("Unexpected ECMWF grid/orientation/coverage")
                sl=np.s_[rows[0]:rows[-1]+1,cols[0]:cols[-1]+1]
                pr=values[sl].copy()
                if np.nanmedian(pr)>2000:
                    pr/=100  # Pa -> hPa
                times[lead]=(pr,lat[sl].copy(),lon[sl].copy())
            finally:
                codes_release(handle)
    if not times:
        raise ValueError("No MSLP fields found in ECMWF GRIB")
    return times

def model_candidates(now):
    # Open Data is distributed with a delay after each operational cycle.
    # 00/12 runs only; at least 8h lag to avoid transient partial products.
    runs=[]
    for days in range(0,4):
        day=now.date()-dt.timedelta(days=days)
        for hour in (12,0):
            r=dt.datetime.combine(day,dt.time(hour),tzinfo=UTC)
            if r<=now-dt.timedelta(hours=8):
                runs.append(r)
    return runs

def fetch_model(model,run,target):
    client=Client(source="ecmwf",model=model)
    client.retrieve(
        date=run.strftime("%Y-%m-%d"),
        time=run.hour,
        stream="oper",
        type="fc",
        param="msl",
        step=STEPS,
        target=str(target),
    )
    if not target.exists() or target.stat().st_size<10000:
        raise ValueError("Missing ECMWF GRIB contents")
    return target

def attach_deepening(tracks):
    for t in tracks:
        index={p["h"]:p for p in t["points"]}
        for p in t["points"]:
            older=index.get(p["h"]-24)
            p["cyclogenesis_24h"]=gfs.bergeron_24h(p,older) if older else None
    return tracks

def run_model(code,model,run):
    with tempfile.TemporaryDirectory(prefix="ecmwf-atl-") as scratch:
        path=Path(scratch)/"msl.grib2"
        fetch_model(model,run,path)
        grids=decode_grib(path)
    if len(grids)<5:
        raise ValueError(f"Incomplete ECMWF forecast; got {len(grids)} steps")
    centers={}
    for hour,(press,lat,lon) in sorted(grids.items()):
        centers[hour]=gfs.centers({"msl":press},lat,lon)
        print(f"{code} {run:%Y%m%d%H} +{hour:03d}: {len(centers[hour])} candidate low centers",flush=True)
    # Reuse tested GFS center-matching logic but replace model identity/source.
    tracks=gfs.tracks_from_centers(centers,run)
    for t in tracks:
        t["model"]=code
        t["id"]=t["id"].replace("gfs-atl-",code+"-")
        t["storm_id"]=t["storm_id"].replace("ATL-","ATL-"+code.upper()+"-")
        t["source"]="ECMWF Open Data "+model+" 0.25° MSLP"
        t["cps"]=None
        for p in t["points"]:
            p["phase"]=None
            p["cps"]=None
            p["wind_radii"]=None
        t["run"]=run.strftime("%Y-%m-%dT%H:%M:%SZ")
    attach_deepening(tracks)
    return {
        "model":code,"label":MODELS[code][1],
        "run":run.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status":"ok" if tracks else "no_storms",
        "tracks":tracks,"steps":sorted(grids)
    }

def update(out,model_ids):
    now=dt.datetime.now(UTC)
    old=None
    if out.exists():
        try:old=json.loads(out.read_text())
        except Exception:pass
    results=[];tracks=[];errors={}
    for code in model_ids:
        model=MODELS[code][0];selected=None
        for run in model_candidates(now)[:3]:
            try:
                selected=run_model(code,model,run)
                break
            except Exception as exc:
                logging.warning("%s %s failed: %s",code,run,exc)
                errors.setdefault(code,[]).append(f"{run:%Y%m%d%H}: {str(exc)[:160]}")
        if selected:
            tracks.extend(selected["tracks"])
            results.append({k:selected[k] for k in ("model","run","status")})
        else:
            # If a model's access fails, retain its earlier valid dataset
            # with the old timestamp instead of implying zero cyclones.
            previous=[t for t in (old or {}).get("tracks",[]) if t.get("model")==code]
            entry=next((m for m in (old or {}).get("models",[]) if m.get("model")==code),None)
            if previous and entry:
                tracks.extend(previous)
                results.append({**entry,"status":"stale"})
            else:
                results.append({"model":code,"run":None,"status":"unavailable"})
    if not any(m["status"] in ("ok","no_storms") for m in results) and not tracks:
        raise SystemExit("ECMWF open data none available: "+json.dumps(errors)[:1200])
    payload={
        "schema":1,"updated_utc":now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":"ECMWF IFS & AIFS Open Data forecasts, MSLP, 0.25°",
        "scope":"North Atlantic 27–75N, 105W–8W",
        "method":"Local MSLP minima and >=3 hPa annular pressure contrast; nearest-center trajectory matching every 6h, >=12h persistence",
        "limitations":"Research low-center matching, not validated storm identity. This MSLP-only archive has no CPS; model-run-matched Hart CPS is published separately from ECMWF geopotential and surface pressure fields when available. No 10-m wind radii from an MSLP-only forecast.",
        "models":results,"tracks":tracks,"errors":errors
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n")
    print(json.dumps({"models":results,"tracks":len(tracks),"errors":errors},ensure_ascii=False),flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=Path("data/cyclone-tracker/ecmwf_atlantic.json"))
    parser.add_argument("--model",choices=("both",*MODELS),default="both")
    args=parser.parse_args()
    update(args.out,list(MODELS) if args.model=="both" else [args.model])

if __name__=="__main__":
    main()
