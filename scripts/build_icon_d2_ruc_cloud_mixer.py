#!/usr/bin/env python3
"""Publish REAL hourly ICON-D2-RUC cloud layers for the private multi-model mixer.

No source field can be silently synthesized; 255 in PNG means missing.
Grid is geographic Germany at 0.025 deg, distinct from native model resolution.
"""
from __future__ import annotations

import argparse
import bz2
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from http.client import HTTPException, RemoteDisconnected
import json
import logging
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import eccodes
import numpy as np
from PIL import Image
from netCDF4 import Dataset
from build_icon_d2_cloud_film import (build_mapping, sample, WIDTH, HEIGHT,
                                       WEST, EAST, NORTH, SOUTH, STEP)

LOG=logging.getLogger("mixer-ruc")
LAYERS={"CLCL":"clcl","CLCM":"clcm","CLCH":"clch","CLCT":"clct"}
HOURS=tuple(range(25))
ROOT="https://opendata.dwd.de/weather/nwp/v1/m/icon-d2-ruc/p"
GRID_URL="https://opendata.dwd.de/weather/lib/cdo/icon_grid_0047_R19B07_L.nc.bz2"


def url_for(run, parameter, hour):
    return (f"{ROOT}/{parameter}/r/{run:%Y-%m-%dT%H}:00/s/"
            f"PT{hour:03d}H00M.grib2")


def request(url, retries=5):
    for attempt in range(retries):
        try:
            with urlopen(Request(url,headers={"User-Agent":"Climate-Dashboard-Cloud-Mixer/1.0",
                                            "Connection":"close"}),timeout=55) as response:
                raw=response.read()
            if len(raw)<500 or not raw.startswith(b"GRIB"):
                raise RuntimeError("No complete GRIB2 data")
            return raw
        except HTTPError as exc:
            if exc.code==404:
                raise RuntimeError(f"RUC forecast unavailable: {url}") from exc
            error=exc
        except (URLError,RemoteDisconnected,HTTPException,TimeoutError,OSError,RuntimeError) as exc:
            error=exc
        if attempt==retries-1:
            raise RuntimeError(f"DWD download failed after {retries} attempts: {url}; {error}") from error
        time.sleep(min(2**attempt*4,40))
    raise AssertionError("unreachable")


def external_coordinates():
    """DWD ICON-D2 native grid #47; GRIB2 has no lat/lon coordinates of its own."""
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        path=Path(directory)/"dwd_grid_0047.nc"
        with urlopen(Request(GRID_URL,headers={"User-Agent":"Climate-Dashboard-RUC-Grid/1.0"}),
                     timeout=180) as stream, path.open("wb") as destination:
            decoder=bz2.BZ2Decompressor()
            while True:
                block=stream.read(1024*1024)
                if not block:break
                destination.write(decoder.decompress(block))
        with Dataset(path,"r") as nc:
            if "clat" not in nc.variables or "clon" not in nc.variables:
                raise RuntimeError("DWD ICON grid missing clat/clon")
            lat=np.asarray(nc.variables["clat"][:],dtype=np.float32).ravel()
            lon=np.asarray(nc.variables["clon"][:],dtype=np.float32).ravel()
        if lat.size!=542040 or lon.size!=lat.size:
            raise RuntimeError(f"Unexpected DWD ICON-D2-RUC grid cell count: {lat.size}")
        # ICON grid coordinates are in radians, unlike the display grid.
        return np.rad2deg(lat),np.rad2deg(lon)


def field(raw,coordinates):
    with tempfile.TemporaryFile() as handle:
        handle.write(raw);handle.seek(0)
        grib=eccodes.codes_grib_new_from_file(handle)
        if grib is None:raise RuntimeError("RUC GRIB missing")
        try:
            grid=str(eccodes.codes_get(grib,"gridType"))
            if grid!="unstructured_grid":
                raise RuntimeError("Unexpected DWD RUC grid: "+grid)
            grid_no=int(eccodes.codes_get(grib,"numberOfGridUsed"))
            if grid_no!=47:
                raise RuntimeError("RUC grid mismatch; expected grid 47, got "+str(grid_no))
            lat,lon=coordinates
            v=np.asarray(eccodes.codes_get_values(grib),dtype=np.float32)
            unit=str(eccodes.codes_get(grib,"units"))
            if not (len(lat)==len(lon)==len(v)) or len(v)<100000:
                raise RuntimeError("Invalid ICON-D2-RUC grid")
            if unit not in ("%","percent"):
                raise RuntimeError(f"Unexpected cloud unit {unit}")
            if not (np.nanmin(v)>=0 and np.nanmax(v)<=100.01):
                raise RuntimeError("Invalid cloud-cover percentage")
            return lat,lon,v
        finally:eccodes.codes_release(grib)


def find_run():
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    for lag in range(2,9):
        run=now-timedelta(hours=lag)
        try:
            for kind in LAYERS:
                request(url_for(run,kind,HOURS[-1]),retries=1)
            return run
        except RuntimeError:
            continue
    raise RuntimeError("No complete +24h hourly RUC run; previous data stays published")


def produce(args):
    run,kind,hour,root,mapping,reference=args
    lat,lon,values=field(request(url_for(run,kind,hour)),reference)
    for index in (0,1001,20001):
        if index < len(lat):
            if abs(float(lat[index])-float(reference[0][index]))>0.0001 or abs(float(lon[index])-float(reference[1][index]))>0.0001:
                raise RuntimeError("RUC geolocation changed between fields")
    arr=sample(values,mapping)
    fn=f"{LAYERS[kind]}_{hour:03d}.png"
    dest=root/"frames"/run.strftime("%Y%m%d%H")
    dest.mkdir(parents=True,exist_ok=True)
    Image.fromarray(arr,mode="L").save(dest/fn,optimize=True)
    return hour,LAYERS[kind],f"frames/{run:%Y%m%d%H}/{fn}"


def build(out,workers):
    out.mkdir(parents=True,exist_ok=True)
    run=find_run()
    current=out/"current.json"
    if current.exists():
        try:
            old=json.loads(current.read_text())
            if old.get("cycle")==f"{run:%Y%m%d%H}" and len(old.get("frames",[]))==len(HOURS):
                if all((out/f).is_file() for row in old["frames"] for f in row["layers"].values()):
                    LOG.info("RUC run already complete: %s",run);return
        except (OSError,ValueError,KeyError):
            pass
    geometry=external_coordinates()
    first=field(request(url_for(run,"CLCL",0)),geometry)
    mapping=build_mapping(first[0],first[1])
    tasks=[(run,kind,hour,out,mapping,first[:2]) for hour in HOURS for kind in LAYERS]
    results={}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(produce,task):task for task in tasks}
        for future in as_completed(futures):
            hour,kind,path=future.result()
            results[hour,kind]=path
            LOG.info("DWD RUC +%02d %s",hour,kind)
    frames=[{"hour":hour,
             "valid_utc":(run+timedelta(hours=hour)).isoformat().replace("+00:00","Z"),
             "layers":{key:results[hour,key] for key in LAYERS.values()}}
            for hour in HOURS]
    manifest={
        "schema":1,"source_id":"icon-d2-ruc","model":"DWD ICON-D2-RUC",
        "cycle":f"{run:%Y%m%d%H}",
        "initialized_utc":run.isoformat().replace("+00:00","Z"),
        "built_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,"step":STEP,
                "width":WIDTH,"height":HEIGHT},
        "source_resolution":"~2.1 km native rotated grid; 0.025 degree geographic image grid",
        "step_hours":1,"unit":"cloud_cover_percent",
        "encoding":"PNG L: 0-254 cloud 0-100%, 255 missing",
        "layers":{"clcl":"Low clouds","clcm":"Middle clouds",
                  "clch":"High clouds","clct":"Total clouds"},
        "frames":frames,"source":"DWD Open Data ICON-D2-RUC GRIB2"
    }
    for frame in frames:
        for f in frame["layers"].values():
            if not (out/f).is_file():raise RuntimeError(f"Missing real RUC field: {f}")
    tmp=out/"current.json.tmp"
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    tmp.replace(current)
    LOG.info("PUBLISHED complete RUC cycle %s with %d hourly frames",run,len(frames))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--max-workers",type=int,default=2)
    options=p.parse_args()
    logging.basicConfig(level=logging.INFO)
    build(options.out,options.max_workers)
