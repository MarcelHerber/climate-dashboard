#!/usr/bin/env python3
"""DWD RADOLAN RY five-minute radar composite, faithfully georeferenced.

RY HDF5/ODIM 1200 x 1100, 1 km; quantity RATE (mm/h), gain 0.01.
Pixel encoding: 0 = no detectable rain, 1..254 = log-scaled mm/h,
255 = radar no-data. Never fills absent frames or masks no-data as dry.
Only real DWD HDF5 files are used.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import time

import h5py
import numpy as np
from PIL import Image
from pyproj import CRS, Transformer
import requests

LOG=logging.getLogger("dwd-radar")
URL="https://opendata.dwd.de/weather/radar/radolan/ry/"
FILE_RE=re.compile(r'raa01-ry_10000-(\d{10})-dwd---bin\.hdf5')
WEST,EAST,SOUTH,NORTH=1.,19.,45.,56.
WIDTH,HEIGHT=900,550
MAX_RATE=120.
LOG_BASE=.05
N_FRAMES=36

def filenames(html:str, now:datetime, count:int=N_FRAMES) -> list[tuple[datetime,str]]:
    found={}
    for match in FILE_RE.finditer(html):
        stamp=match.group(1)
        try:
            instant=datetime.strptime(stamp,"%y%m%d%H%M").replace(tzinfo=timezone.utc)
        except ValueError:continue
        if instant>now+timedelta(minutes=5) or instant<now-timedelta(hours=16):continue
        found[instant]=match.group(0)
    ordered=sorted(found.items())
    # A rolling DWD list should not be advertised as current if its newest
    # observation is older than 35 minutes.
    if len(ordered)<12 or now-ordered[-1][0]>timedelta(minutes=35):
        raise RuntimeError("DWD RY index contains insufficient or stale frames")
    selected=ordered[-count:]
    # Do not invent a missing radar time step; gaps remain in the timestamps.
    return selected

def meta(group,key,default=None):
    return group.attrs.get(key,default)

def scalar_string(value)->str:
    if isinstance(value,bytes):return value.decode("utf-8")
    return str(value)

def grid_lookup(file:h5py.File)->tuple[np.ndarray,np.ndarray]:
    loc=file["where"]
    projection=scalar_string(meta(loc,"projdef"))
    if not projection or projection=="None":raise ValueError("Missing ODIM projection")
    xs=int(meta(loc,"xsize"));ys=int(meta(loc,"ysize"))
    step_x=float(meta(loc,"xscale"));step_y=float(meta(loc,"yscale"))
    if (xs,ys)!=(1100,1200) or not 990<step_x<1010 or not 990<step_y<1010:
        raise ValueError("Unexpected DWD RY extent/resolution")
    transf=Transformer.from_crs("EPSG:4326",CRS.from_user_input(projection),always_xy=True)
    ulx,uly=transf.transform(float(meta(loc,"UL_lon")),float(meta(loc,"UL_lat")))
    urx,ury=transf.transform(float(meta(loc,"UR_lon")),float(meta(loc,"UR_lat")))
    llx,lly=transf.transform(float(meta(loc,"LL_lon")),float(meta(loc,"LL_lat")))
    if abs(urx-ulx-xs*step_x)>2200 or abs(uly-lly-ys*step_y)>2200:
        raise ValueError("ODIM image corners do not match geographic projection")
    lons=WEST+(np.arange(WIDTH,dtype=np.float64)+.5)*(EAST-WEST)/WIDTH
    lats=NORTH-(np.arange(HEIGHT,dtype=np.float64)+.5)*(NORTH-SOUTH)/HEIGHT
    longitude,latitude=np.meshgrid(lons,lats)
    x,y=transf.transform(longitude,latitude)
    ix=np.floor((x-ulx)/step_x).astype(np.int32)
    iy=np.floor((uly-y)/step_y).astype(np.int32)
    return ix,iy

def decode(blob:bytes,lookup:tuple[np.ndarray,np.ndarray]|None=None):
    with h5py.File(BytesIO(blob),"r") as f:
        if scalar_string(meta(f["dataset1/data1/what"],"quantity"))!="RATE":
            raise ValueError("DWD RY does not contain precipitation RATE")
        raw=f["dataset1/data1/data"][:]
        what=f["dataset1/data1/what"]
        gain=float(meta(what,"gain"));offset=float(meta(what,"offset"))
        nodata=float(meta(what,"nodata"));undetect=float(meta(what,"undetect"))
        if raw.shape!=(1200,1100) or not (.00001<gain<1.) or abs(offset)>10:
            raise ValueError("Invalid RY data shape, gain or offset")
        if lookup is None:lookup=grid_lookup(f)
        end_day=scalar_string(meta(f["dataset1/what"],"enddate"))
        end_clock=scalar_string(meta(f["dataset1/what"],"endtime"))
        if not re.fullmatch(r"\d{8}",end_day) or not re.fullmatch(r"\d{6}",end_clock):
            raise ValueError("Missing ODIM observation end time")
        valid_end=datetime.strptime(end_day+end_clock,"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        ix,iy=lookup
        inside=(ix>=0)&(ix<raw.shape[1])&(iy>=0)&(iy<raw.shape[0])
        arr=np.full((HEIGHT,WIDTH),255,np.uint8)
        if inside.any():
            vals=raw[iy[inside],ix[inside]]
            # 65534 is a reserved upper-end uint16 code encountered in RY;
            # never interpret it as an extreme 655.34 mm/h radar echo.
            valid=np.isfinite(vals)&(vals!=nodata)&(vals!=65534)
            rates=vals.astype(np.float32)*gain+offset
            out=np.zeros(len(vals),np.uint8)
            detected=valid&(vals!=undetect)&(rates>=.05)
            v=np.clip(rates[detected],.05,MAX_RATE)
            out[detected]=1+np.rint(253*np.log1p(v/LOG_BASE)/np.log1p(MAX_RATE/LOG_BASE)).astype(np.uint8)
            out[~valid]=255
            arr[inside]=out
        coverage=(arr!=255).mean()
        if coverage<.15 or coverage>.99:
            raise ValueError(f"Implausible DWD coverage {coverage:.3f}; check ODIM georeference")
        valid_raw=(raw!=nodata)&(raw!=65534)&(raw!=undetect)
        stats={"coverage":round(float(coverage),4),
               "reserved_65534_cells":int(np.count_nonzero(raw==65534)),
               "wet_fraction":round(float(((arr>0)&(arr<255)).mean()),4),
               "max_rate_mm_h":round(float(np.nanmax(np.where(valid_raw,raw.astype(np.float32)*gain+offset,0))),2)}
        return arr,lookup,stats,valid_end

def build(out:Path, count:int=N_FRAMES)->dict:
    out.mkdir(parents=True,exist_ok=True)
    session=requests.Session()
    session.headers["User-Agent"]="ClimateDashboard-DWD-Radar-Lab/1.0 (research; GitHub Pages project)"
    now=datetime.now(timezone.utc)
    index=session.get(URL,timeout=35)
    index.raise_for_status()
    selected=filenames(index.text,now,count)
    previous=None
    if (out/"current.json").exists():
        try:previous=json.loads((out/"current.json").read_text())
        except (OSError,ValueError):pass
    rows=[]
    lookup=None
    folder=out/"frames"
    folder.mkdir(parents=True,exist_ok=True)
    for instant,name in selected:
        stamp=instant.strftime("%Y%m%d%H%M")
        relative="frames/"+stamp+".png"
        target=out/relative
        if previous and target.exists() and any(f.get("utc")==instant.isoformat().replace("+00:00","Z") for f in previous.get("frames",[])):
            with Image.open(target) as im:
                if im.size==(WIDTH,HEIGHT) and im.mode=="L":
                    rows.append({"utc":instant.isoformat().replace("+00:00","Z"),"end_utc":(instant+timedelta(minutes=5)).isoformat().replace("+00:00","Z"),"image":relative})
                    continue
        resp=session.get(URL+name,timeout=45)
        resp.raise_for_status()
        grid,lookup,stats,valid_end=decode(resp.content,lookup)
        if not 0<= (valid_end-instant).total_seconds() <= 600:
            raise ValueError("Radar HDF5 observation time does not match filename")
        Image.fromarray(grid,mode="L").save(target,optimize=True)
        rows.append({"utc":instant.isoformat().replace("+00:00","Z"),"end_utc":valid_end.isoformat().replace("+00:00","Z"),"image":relative,"stats":stats})
        LOG.info("DWD RY %s coverage=%s max=%.2f mm/h",stamp,stats["coverage"],stats["max_rate_mm_h"])
    if len(rows)<12:raise RuntimeError("Insufficient verified radar snapshots")
    # Last radar timestamp must really be current. Publishing older data isn't a live composite.
    end=datetime.fromisoformat(rows[-1]["utc"].replace("Z","+00:00"))
    if now-end>timedelta(minutes=35):raise RuntimeError("Latest verified frame too old")
    manifest={
        "schema":1,
        "product":"DWD RADOLAN RY / ODIM HDF5",
        "source":"Deutscher Wetterdienst / Open Data",
        "credit":"DWD, Datenlizenz Deutschland - Namensnennung - Version 2.0",
        "built_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,"width":WIDTH,"height":HEIGHT},
        "palette":{"no_echo":0,"nodata":255,"max_rate":MAX_RATE,"log_base":LOG_BASE,
                   "levels_mm_h":[.1,.5,1,2,5,10,20,30,50,80,120]},
        "units":"mm/h",
        "frames":rows
    }
    tmp=out/"current.json.tmp"
    tmp.write_text(json.dumps(manifest,separators=(",",":"),ensure_ascii=False),encoding="utf-8")
    tmp.replace(out/"current.json")
    # Retain only 36 latest verified images, no accidental multi-week growth.
    wanted={f["image"] for f in rows}
    for p in folder.glob("*.png"):
        if p.relative_to(out).as_posix() not in wanted:p.unlink()
    return manifest

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--frames",type=int,default=N_FRAMES)
    args=ap.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    if not 12<=args.frames<=36:raise ValueError("frames must be 12..36")
    m=build(args.out,args.frames)
    print("Verified DWD radar RY",len(m["frames"]),"latest",m["frames"][-1]["utc"])
