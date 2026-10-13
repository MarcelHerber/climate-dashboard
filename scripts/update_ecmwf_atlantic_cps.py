#!/usr/bin/env python3
"""Actual IFS/AIFS Hart Cyclone Phase Space from ECMWF Open Data.

Separate from operational MSLP low-centre archive to avoid overwriting good
tracks on a missing pressure-level product or partially available forecast.

Uses native ECMWF geopotential levels 925/850/700/600/500/400/300 hPa
and log-pressure interpolation ONLY for 900 hPa. ECMWF GRIB 'z' is
geopotential (m²/s²), converted to geometric/geopotential height in metres
by standard gravity. Excludes 900 hPa below surface using surface pressure.

CPS diagnostics at selected 12-h leads must be from the SAME model run as
the tracked low; no warm-core inference from central pressure.
"""
from __future__ import annotations
import argparse
import datetime as dt
import importlib.util
import json
import logging
import math
from pathlib import Path
import tempfile

import numpy as np
from eccodes import codes_get,codes_get_array,codes_grib_new_from_file,codes_release
from ecmwf.opendata import Client

spec=importlib.util.spec_from_file_location("gfs_core",Path(__file__).resolve().with_name("update_north_atlantic_cps.py"))
gfs=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gfs)

LEVELS=(925,850,700,600,500,400,300)
CPS_STEPS=(0,12,24,36,48,60,72)
GRAVITY=9.80665
ECMWF_MODELS={"ifs-atl":"ifs","aifs-atl":"aifs-single"}

def parse_utc(stamp):
    return dt.datetime.fromisoformat(stamp.replace("Z","+00:00"))

def retrieve(run,model,parameter,target,levelist=None,steps=CPS_STEPS):
    client=Client(source="ecmwf",model=model)
    kwargs=dict(date=run.strftime("%Y-%m-%d"),time=run.hour,
                stream="oper",type="fc",param=parameter,
                step=list(steps),target=str(target))
    if levelist:kwargs["levelist"]=list(levelist)
    client.retrieve(**kwargs)
    if not target.is_file() or target.stat().st_size<2000:
        raise RuntimeError("Empty ECMWF GRIB "+model+" "+parameter)

def decode_fields(path,need_geopotential):
    """Decode GRIB and crop all global fields to common Atlantic grid."""
    by_step={}
    grid_lat=grid_lon=None
    sl=None
    seen=0
    with path.open("rb") as fp:
        while (h:=codes_grib_new_from_file(fp)) is not None:
            try:
                name=str(codes_get(h,"shortName"))
                typelevel=str(codes_get(h,"typeOfLevel"))
                level=int(codes_get(h,"level"))
                if need_geopotential:
                    if typelevel!="isobaricInhPa" or level not in LEVELS or name not in ("z","gh"):
                        continue
                    key=f"z{level}"
                else:
                    if name!="sp" or typelevel not in ("surface","heightAboveGround"):
                        continue
                    key="sp"
                try:step=int(codes_get(h,"endStep"))
                except Exception:step=int(codes_get(h,"step"))
                if step not in CPS_STEPS:
                    continue
                nj=int(codes_get(h,"Nj"));ni=int(codes_get(h,"Ni"))
                if sl is None:
                    la=np.asarray(codes_get_array(h,"latitudes"),dtype=np.float32).reshape(nj,ni)
                    lo=np.asarray(codes_get_array(h,"longitudes"),dtype=np.float32).reshape(nj,ni)
                    lo=(lo+180)%360-180
                    inside=(la>=22)&(la<=80)&(lo>=-111)&(lo<=-3)
                    rows=np.flatnonzero(inside.any(axis=1))
                    cols=np.flatnonzero(inside.any(axis=0))
                    if rows.size<100 or cols.size<100:
                        raise ValueError("Unexpected ECMWF GRIB spatial grid")
                    sl=np.s_[rows[0]:rows[-1]+1,cols[0]:cols[-1]+1]
                    grid_lat=la[sl].copy()
                    grid_lon=lo[sl].copy()
                a=np.asarray(codes_get_array(h,"values"),dtype=np.float32).reshape(nj,ni)[sl].copy()
                if need_geopotential and name=="z":
                    a/=GRAVITY
                if key=="sp" and np.nanmedian(a)>1500:
                    a/=100
                by_step.setdefault(step,{})[key]=a
                seen+=1
            finally:
                codes_release(h)
    required=set("z"+str(p) for p in LEVELS) if need_geopotential else {"sp"}
    valid_steps={k:v for k,v in by_step.items() if set(v)>=required}
    print(f"Read {seen} {('geopotential' if need_geopotential else 'surface-pressure')} GRIB fields; "
          f"complete steps: {sorted(valid_steps)}",flush=True)
    return valid_steps,grid_lat,grid_lon

def motion_vector(points,idx):
    p=points[idx]
    previous=points[max(0,idx-1)]
    following=points[min(len(points)-1,idx+1)]
    # Motion in km over nearest available 6h track sections. CPS B uses
    # direction, not speed. Handle dateline-relative dx conservatively.
    diff=(following["lon"]-previous["lon"]+180)%360-180
    dx=diff*111.195*math.cos(math.radians(p["lat"]))
    dy=(following["lat"]-previous["lat"])*111.195
    return dx,dy

def diagnose_tracks(tracks,geopotential,surface_pressure,lat,lon,model,run):
    out=[];valid=0
    for track in tracks:
        if track["model"]!=model or parse_utc(track["run"])!=run:
            continue
        points=[]
        for idx,p in enumerate(track["points"]):
            hour=p["h"]
            if hour not in geopotential:
                continue
            z=geopotential[hour]
            # Explicitly refuse to make up 900 hPa below-ground values.
            sp=surface_pressure.get(hour,{}).get("sp")
            if sp is None:
                continue
            fields=dict(z,sp=sp)
            fields["z900"]=(
                fields["z925"]+
                (fields["z850"]-fields["z925"])*
                math.log(900/925)/math.log(850/925)
            )
            cps=gfs.calculate_cps(fields,lat,lon,p,motion_vector(track["points"],idx))
            if cps is None:
                continue
            cps["interpolated_levels_hpa"]=[900]
            cps["native_levels_hpa"]=list(LEVELS)
            cps["source"]="ECMWF "+ECMWF_MODELS[model]+" z/pl and sp/sfc"
            points.append({"h":hour,"time":p["time"],"cps":cps,"phase":gfs.phase(cps)})
            valid+=1
        if points:
            out.append({"id":track["id"],"model":model,"run":track["run"],"points":points})
    return out,valid

def build(tracks_archive,out,models):
    base=json.loads(tracks_archive.read_text())
    if not isinstance(base.get("models"),list) or not isinstance(base.get("tracks"),list):
        raise RuntimeError("No valid ECMWF low-track archive")
    all_cps=[]
    result=[]
    old=None
    if out.exists():
        try:old=json.loads(out.read_text())
        except Exception:pass
    for model in models:
        entry=next((x for x in base["models"] if x["model"]==model),None)
        if not entry or entry.get("status")!="ok":
            result.append({"model":model,"status":"no_matching_mslp_run","run":None,"cps_points":0})
            continue
        run=parse_utc(entry["run"])
        native=ECMWF_MODELS[model]
        try:
            with tempfile.TemporaryDirectory(prefix="ecmwf-cps-") as temp:
                zpath=Path(temp)/"geopotential.grib2"
                spath=Path(temp)/"surfacepressure.grib2"
                retrieve(run,native,"z",zpath,LEVELS)
                retrieve(run,native,"sp",spath)
                z,lat,lon=decode_fields(zpath,True)
                sp,slat,slon=decode_fields(spath,False)
                if not z or not sp:
                    raise ValueError("No complete ECMWF z/sp vertical fields")
                if lat.shape!=slat.shape or not np.allclose(lat,slat) or not np.allclose(lon,slon):
                    raise ValueError("ECMWF z/pl and sp/sfc regional grids differ")
                tracks,n=diagnose_tracks(base["tracks"],z,sp,lat,lon,model,run)
                if n<3:
                    raise ValueError("Too few genuine Hart-CPS points: "+str(n))
                all_cps.extend(tracks)
                result.append({"model":model,"status":"ok","run":entry["run"],
                               "cps_points":n,"matched_tracks":len(tracks),
                               "steps":sorted(set(p["h"] for t in tracks for p in t["points"]))})
                print(model,"CPS",n,"points",len(tracks),"tracks",flush=True)
        except Exception as exc:
            logging.exception("ECMWF CPS model %s failed: %s",model,exc)
            # Retain only if still attached to matching model run/track IDs.
            ids={t["id"] for t in base["tracks"] if t["model"]==model}
            archived=[t for t in (old or {}).get("tracks",[])
                      if t["model"]==model and t["run"]==entry["run"] and t["id"] in ids]
            if archived:
                all_cps.extend(archived)
                result.append({"model":model,"status":"previous_same_run",
                               "run":entry["run"],"cps_points":sum(len(t["points"]) for t in archived)})
            else:
                result.append({"model":model,"status":"unavailable","run":entry["run"],
                               "cps_points":0})
    good=sum(x["status"] in ("ok","previous_same_run") for x in result)
    if not good:
        raise SystemExit("No verified IFS/AIFS CPS diagnostics; previous file left intact")
    payload={
        "schema":1,"updated_utc":dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":"ECMWF IFS/AIFS Open Data 0.25° geopotential (z) and surface pressure (sp)",
        "method":"Hart B / lower & upper −VT in 500-km disks; native 925/850/700/600/500/400/300 hPa; logarithmically interpolated 900 hPa; 900-hPa underground excluded via sp",
        "models":result,"tracks":all_cps
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n")
    print(json.dumps({"models":result,"valid_tracks":len(all_cps)},ensure_ascii=False),flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--atlantic",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--model",choices=["both",*ECMWF_MODELS],default="both")
    args=parser.parse_args()
    build(args.atlantic,args.out,tuple(ECMWF_MODELS) if args.model=="both" else (args.model,))

if __name__=="__main__":
    main()
