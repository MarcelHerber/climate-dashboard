#!/usr/bin/env python3
"""Real GEFS perturbation-member Hart CPS sampled around tracked GFS Atlantic lows.

NOAA NOMADS 0.5° primary parameters provide HGT 925/850/700/500/400/300;
900, 600 and 400 hPa are computed by log-pressure interpolation and are therefore
APPROXIMATIONS to classic Hart CPS, NOT direct native GEFS pressure levels.

This is a targeted research pilot: each GEFS member's local MSLP minimum is
searched within 450 km of the matching GFS low valid time. Members that cannot
be linked are excluded rather than creating fictitious tracks.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen

import numpy as np
from eccodes import codes_grib_new_from_file,codes_get,codes_get_array,codes_release

spec=importlib.util.spec_from_file_location("gfs_tracker",Path(__file__).resolve().with_name("update_north_atlantic_cps.py"))
gfs=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gfs)
LEVELS=[925,850,700,500,300]
FILTER="https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p50a.pl"
TIMEOUT=95

def interpolate_height(p,p1,p2,z1,z2):
    weight=math.log(p/p1)/math.log(p2/p1)
    return z1+weight*(z2-z1)

def read_grib(path):
    fields={};lat=lon=None
    with path.open("rb") as f:
        while (msg:=codes_grib_new_from_file(f)) is not None:
            try:
                short=str(codes_get(msg,"shortName"))
                leveltype=str(codes_get(msg,"typeOfLevel"))
                level=int(codes_get(msg,"level"))
                key=None
                if leveltype=="isobaricInhPa" and short in ("gh","z") and level in LEVELS:
                    key=f"z{level}"
                elif leveltype in ("meanSea","meanSeaLevel") and short in ("msl","prmsl"):key="msl"
                elif leveltype=="surface" and short in ("sp","pres"):key="sp"
                if key is None:continue
                ny=int(codes_get(msg,"Nj"));nx=int(codes_get(msg,"Ni"))
                grid=np.asarray(codes_get_array(msg,"values"),dtype=np.float32).reshape(ny,nx)
                fields[key]=grid
                if lat is None:
                    lat=np.asarray(codes_get_array(msg,"latitudes"),dtype=np.float32).reshape(ny,nx)
                    lon=np.asarray(codes_get_array(msg,"longitudes"),dtype=np.float32).reshape(ny,nx)
            finally:codes_release(msg)
    required=["msl"]+[f"z{p}" for p in LEVELS]
    missing=[k for k in required if k not in fields]
    if missing:raise ValueError(f"Missing GEFS fields {missing}; available={list(fields)}")
    fields["z900"]=interpolate_height(900,925,850,fields["z925"],fields["z850"])
    fields["z600"]=interpolate_height(600,700,500,fields["z700"],fields["z500"])
    fields["z400"]=interpolate_height(400,500,300,fields["z500"],fields["z300"])
    if np.nanmedian(fields["msl"])>1500:fields["msl"]/=100
    if "sp" in fields and np.nanmedian(fields["sp"])>1500:fields["sp"]/=100
    return fields,lat,((lon+180)%360)-180

def retrieve(run,member,lead,target):
    prefix="gec00" if member==0 else f"gep{member:02d}"
    name=f"{prefix}.t{run:%H}z.pgrb2a.0p50.f{lead:03d}"
    query={
        "file":name,"dir":f"/gefs.{run:%Y%m%d}/{run:%H}/atmos/pgrb2ap5",
        "subregion":"","leftlon":"225","rightlon":"359.5",
        "toplat":"79","bottomlat":"24",
        "var_HGT":"on","var_PRMSL":"on","var_PRES":"on",
        "lev_mean_sea_level":"on","lev_surface":"on",
        **{f"lev_{p}_mb":"on" for p in LEVELS},
    }
    request=Request(FILTER+"?"+urlencode(query),headers={"User-Agent":"ClimateDashboardScience/GEFS-CPS"})
    with urlopen(request,timeout=TIMEOUT) as response:
        data=response.read(13_000_000)
    if len(data)<2000 or not data.startswith(b"GRIB"):
        raise ValueError(f"GEFS {name}: invalid GRIB")
    target.write_bytes(data)

def nearest_member_center(fields,lat,lon,target):
    # Prefer the modeled local sea-level-pressure center rather than assuming
    # all members share the deterministic GFS central location.
    la,lo=target["lat"],target["lon"]
    inside,_,_,dist=gfs.region(lat,lon,la,lo,450)
    eligible=inside&np.isfinite(fields["msl"])&(lat>=26)&(lat<=76)
    if not eligible.any():return None
    search=np.where(eligible,fields["msl"],np.inf)
    i,j=np.unravel_index(np.argmin(search),search.shape)
    center={"lat":float(lat[i,j]),"lon":float(lon[i,j]),
            "mslp_hpa":round(float(fields["msl"][i,j]),1)}
    if gfs.haversine(la,lo,center["lat"],center["lon"])>450:return None
    return center

def process_member(run,member,base_tracks,steps):
    out={t["id"]:[] for t in base_tracks}
    warnings=[]
    with tempfile.TemporaryDirectory(prefix="gefs-") as temp:
        for lead in steps:
            path=Path(temp)/f"{member:02d}_{lead:03d}.grb2"
            try:
                for attempt in range(2):
                    try:
                        retrieve(run,member,lead,path)
                        fields,lat,lon=read_grib(path)
                        break
                    except Exception:
                        if attempt:raise
                        time.sleep(1)
                valid=run+dt.timedelta(hours=lead)
                stamp=valid.strftime("%Y-%m-%dT%H:%M:%SZ")
                for t in base_tracks:
                    candidates={p["time"]:p for p in t["points"]}
                    p=candidates.get(stamp)
                    if p is None or p.get("cps") is None:continue
                    center=nearest_member_center(fields,lat,lon,p)
                    if center is None:continue
                    idx=t["points"].index(p)
                    p0=t["points"][max(0,idx-1)];p1=t["points"][min(len(t["points"])-1,idx+1)]
                    motion=((p1["lon"]-p0["lon"])*111.2*math.cos(math.radians(center["lat"])),
                            (p1["lat"]-p0["lat"])*111.2)
                    cps=gfs.calculate_cps(fields,lat,lon,center,motion)
                    if cps is None:continue
                    cps["interpolated_levels_hpa"]=[900,600,400]
                    out[t["id"]].append({"time":stamp,"h":int((valid-dt.datetime.fromisoformat(t["run"].replace("Z","+00:00"))).total_seconds()/3600),
                         "lat":round(center["lat"],2),"lon":round(center["lon"],2),
                         "mslp_hpa":center["mslp_hpa"],
                         "cps":cps,"phase":gfs.phase(cps)})
            except Exception as exc:
                warnings.append(f"+{lead}: {str(exc)[:180]}")
            finally:path.unlink(missing_ok=True)
    return member,out,warnings

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--atlantic",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--members",type=int,default=int(os.getenv("GEFS_MEMBERS","10")))
    parser.add_argument("--max-hour",type=int,default=72)
    args=parser.parse_args()
    atlas=json.loads(args.atlantic.read_text())
    base_tracks=[t for t in atlas.get("tracks",[]) if t.get("model")=="gfs" and
                 sum(p.get("cps") is not None for p in t["points"])>=2]
    if not base_tracks:raise SystemExit("No current GFS Atlantic CPS base tracks")
    base_run=dt.datetime.fromisoformat(atlas["models"][0]["run"].replace("Z","+00:00"))
    # GEFS cycles are 00,06,12,18 UTC; use the same initialization for
    # comparable valid dates and explicitly encode it in exported metadata.
    member_ids=list(range(min(30,args.members)+1))
    steps=list(range(0,args.max_hour+1,12))
    all_members={t["id"]:[] for t in base_tracks}
    errors={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks={pool.submit(process_member,base_run,m,base_tracks,steps):m for m in member_ids}
        for future in as_completed(tasks):
            m=tasks[future]
            try:
                _,result,fail=future.result()
                for tid,points in result.items():
                    if len(points)>=2:
                        all_members[tid].append({
                            "member":f"ge{'c00' if m==0 else 'p'+str(m).zfill(2)}",
                            "run":base_run.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "points":sorted(points,key=lambda p:p["time"])})
                if fail:errors[str(m)]=fail[:2]
            except Exception as exc:errors[str(m)]=[str(exc)[:160]]
            print(f"GEFS member {m:02d}: completed",flush=True)
    valid_members={t:len(m) for t,m in all_members.items() if len(m)>=2}
    if not valid_members:raise SystemExit(f"No verified 2-member GEFS matched CPS tracks, errors={errors}")
    payload={"schema":1,"updated_utc":dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "run":base_run.strftime("%Y-%m-%dT%H:%M:%SZ"),"model":"GEFS","source":"NOAA/NCEP GEFS 0.5° 30 perturbations + control",
       "members_requested":len(member_ids),
       "members_with_cps":len(set(m["member"] for arr in all_members.values() for m in arr)),
       "pressure_levels_native":[925,850,700,500,300],
       "pressure_levels_interpolated":[900,600,400],
       "method":"Hart 500km around nearest GEFS sea-level-pressure center within 450km of GFS baseline; 900/600/400hPa log-pressure height interpolation; 12h steps",
       "status":"partial" if errors else "ok","errors":errors,"storms":[
         {"base_id":tid,"members":records} for tid,records in all_members.items() if records]}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n")
    print(json.dumps({"run":payload["run"],"storm_matches":len(valid_members),
        "valid_members":payload["members_with_cps"],"requested":len(member_ids),"errors":len(errors)}),flush=True)

if __name__=="__main__":main()
