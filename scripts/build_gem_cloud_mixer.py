#!/usr/bin/env python3
"""Probe/publication adapter for native GEM/GDPS TOTAL cloud cover only.

ECCC GDPS publishes native total cloud cover, not individual low/mid/high.
Discover actual GRIB2 files in the official Datamart directory and verify
their GRIB discipline/category/parameter metadata before trusting a product.
No inferred layers or cloudiness calculated from humidity are accepted.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta,timezone
import html
from html.parser import HTMLParser
import json
import logging
from pathlib import Path
import re
import time
from urllib.parse import unquote,urljoin
from urllib.request import Request,urlopen
import tempfile
import eccodes
import numpy as np
from scipy.spatial import cKDTree
from PIL import Image
from build_icon_d2_cloud_film import WEST,EAST,SOUTH,NORTH,STEP,WIDTH,HEIGHT

LOG=logging.getLogger("mixer-gem")
ROOT="https://dd.weather.gc.ca/today/model_gdps/15km"
HOURS=tuple(range(0,37,3))
CLOUD_PATTERN=re.compile(r"(?:CloudCover|TotalCloud|TCDC|Cloudiness|CloudAmount)",re.I)


class DirectoryParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items=[]
    def handle_starttag(self,tag,attrs):
        if tag!="a":return
        href=dict(attrs).get("href","")
        if href.lower().endswith(".grib2"):self.items.append(unquote(href))


def list_directory(url):
    with urlopen(Request(url,headers={"User-Agent":"Climate-Dashboard-GEM-Clouds/1.0"}),timeout=50) as response:
        if response.status!=200:raise RuntimeError(f"GDPS index unavailable {response.status}")
        text=response.read().decode("utf-8",errors="replace")
    parser=DirectoryParser();parser.feed(text)
    return parser.items


def download(url):
    with urlopen(Request(url,headers={"User-Agent":"Climate-Dashboard-GEM-Clouds/1.0"}),timeout=100) as response:
        raw=response.read()
    if len(raw)<1000 or not raw.startswith(b"GRIB"):
        raise RuntimeError("Invalid GEM GRIB2")
    return raw


def decode_native_total(raw):
    with tempfile.TemporaryFile() as file:
        file.write(raw);file.seek(0)
        handle=eccodes.codes_grib_new_from_file(file)
        if handle is None:raise RuntimeError("GDPS GRIB2 empty")
        try:
            category=int(eccodes.codes_get(handle,"parameterCategory"))
            number=int(eccodes.codes_get(handle,"parameterNumber"))
            if category!=6 or number!=1:
                raise RuntimeError(f"Not native total cloud cover (category={category}, number={number})")
            lat=np.asarray(eccodes.codes_get_array(handle,"latitudes"),dtype=np.float32)
            lon=np.asarray(eccodes.codes_get_array(handle,"longitudes"),dtype=np.float32)
            val=np.asarray(eccodes.codes_get_values(handle),dtype=np.float32)
            unit=str(eccodes.codes_get(handle,"units"))
            if unit not in ("%","percent") or val.size!=lat.size or val.size!=lon.size or val.size<1000:
                raise RuntimeError(f"Unexpected GDPS cloud unit or grid: {unit}")
            if np.nanmin(val)<-.01 or np.nanmax(val)>100.1:
                raise RuntimeError("GDPS total cloud outside percent limits")
            return lat,lon,np.clip(val,0,100)
        finally:eccodes.codes_release(handle)


def to_germany(lat,lon,values):
    shift=np.where(lon>180,lon-360,lon)
    mask=(lat>=SOUTH-1)&(lat<=NORTH+1)&(shift>=WEST-1)&(shift<=EAST+1)
    if mask.sum()<100:raise RuntimeError("GDPS field lacks Germany")
    lat2,lon2=np.meshgrid(np.linspace(NORTH,SOUTH,HEIGHT),np.linspace(WEST,EAST,WIDTH),indexing="ij")
    tree=cKDTree(np.column_stack((lat[mask],shift[mask])))
    dist,idx=tree.query(np.column_stack((lat2.ravel(),lon2.ravel())),workers=2)
    sampled=values[mask][idx]
    valid=(dist<0.18)&np.isfinite(sampled)
    if np.mean(valid)<.99:raise RuntimeError("GDPS Germany grid not sufficiently covered")
    arr=np.full(WIDTH*HEIGHT,255,dtype=np.uint8)
    arr[valid]=np.round(sampled[valid]*2.54).astype(np.uint8)
    return arr.reshape(HEIGHT,WIDTH)


def locate_native_product(run,hour):
    folder=f"{ROOT}/{run:%H}/{hour:03d}/"
    candidates=[name for name in list_directory(folder) if CLOUD_PATTERN.search(name)]
    good=[]
    for filename in candidates:
        try:
            # Reject files from an older cycle left on CDN.
            if not filename.startswith(f"{run:%Y%m%dT%H}Z_MSC_GDPS_"):
                continue
            payload=download(urljoin(folder,filename))
            content=decode_native_total(payload)
            good.append((filename,content))
        except Exception as e:
            LOG.info("Skipping unverified GDPS cloud candidate %s: %s",filename,e)
    if len(good)!=1:
        raise RuntimeError(f"Expected exactly one native GDPS TCDC field in {folder}; found {len(good)} verified files")
    return good[0]


def build(out):
    out.mkdir(parents=True,exist_ok=True)
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    now-=timedelta(hours=now.hour%12)
    run=None
    for lag in range(1,5):
        candidate=now-timedelta(hours=12*lag)
        try:
            locate_native_product(candidate,3)
            run=candidate
            break
        except Exception as error:
            LOG.warning("GEM GDPS native cloud unavailable for %s: %s",candidate,error)
    if run is None:
        raise RuntimeError("GEM open Datamart did not expose verifiable native total-cloud GRIB2")
    frames=[]
    for hour in HOURS:
        filename,content=locate_native_product(run,hour)
        folder=out/"frames"/f"{run:%Y%m%d%H}";folder.mkdir(parents=True,exist_ok=True)
        name=f"clct_{hour:03d}.png"
        Image.fromarray(to_germany(*content),mode="L").save(folder/name,optimize=True)
        frames.append({"hour":hour,
                       "valid_utc":(run+timedelta(hours=hour)).isoformat().replace("+00:00","Z"),
                       "layers":{"clct":f"frames/{run:%Y%m%d%H}/{name}"}})
        LOG.info("Verified real GDPS total cloud +%02dh from %s",hour,filename)
        time.sleep(1)
    manifest={
        "schema":1,"source_id":"gem","model":"ECCC GEM GDPS",
        "cycle":f"{run:%Y%m%d%H}",
        "initialized_utc":run.isoformat().replace("+00:00","Z"),
        "built_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,"step":STEP,
                "width":WIDTH,"height":HEIGHT},
        "source_resolution":"0.15 degree GEM GDPS, displayed on 0.025 degree grid",
        "step_hours":3,"layers":{"clct":"Native GEM total cloud cover only"},
        "unit":"cloud_cover_percent","encoding":"PNG L: 0-254 = 0-100%, 255 missing",
        "frames":frames,"source":"ECCC MSC GDPS official Datamart",
        "note":"Low/mid/high clouds are NOT derived from humidity or estimated.",
    }
    tmp=out/"current.json.tmp"
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    tmp.replace(out/"current.json")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    build(args.out)
