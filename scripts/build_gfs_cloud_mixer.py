#!/usr/bin/env python3
"""Real GFS 0.25-degree low/mid/high/total cloud grids for the private mixer.

NOMADS GRIB Filter returns one cropped GRIB2 with four cloud products.
No synthetic cloud fields. Hourly ICON-D2 continues to fill times for which
GFS has no matching valid UTC time.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta,timezone
import json
import logging
from pathlib import Path
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from http.client import RemoteDisconnected,HTTPException
import eccodes
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
from build_icon_d2_cloud_film import WEST,EAST,SOUTH,NORTH,STEP,WIDTH,HEIGHT

LOG=logging.getLogger("gfs-mixer")
HOURS=tuple(range(0,37,3))
NUMBER_KIND={1:"clct",3:"clcl",4:"clcm",5:"clch"}
ROOT="https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"


def url_for(run,hour):
    args={
       "file":f"gfs.t{run:%H}z.pgrb2.0p25.f{hour:03d}",
       "var_LCDC":"on","var_MCDC":"on","var_HCDC":"on","var_TCDC":"on",
       "lev_low_cloud_layer":"on","lev_middle_cloud_layer":"on",
       "lev_high_cloud_layer":"on",
       "lev_entire_atmosphere_(considered_as_a_single_layer)":"on",
       "subregion":"","leftlon":"4","rightlon":"18","toplat":"57","bottomlat":"46",
       "dir":f"/gfs.{run:%Y%m%d}/{run:%H}/atmos",
    }
    return ROOT+"?"+urlencode(args)


def retrieve(url,retries=5):
    for attempt in range(retries):
        try:
            with urlopen(Request(url,headers={"User-Agent":"Climate-Dashboard-GFS-Clouds/1.0",
                                              "Connection":"close"}),timeout=90) as f:
                raw=f.read()
            if len(raw)<1000 or not raw.startswith(b"GRIB"):
                raise ValueError("No complete filtered cloud GRIB")
            return raw
        except HTTPError as err:
            if err.code in (400,403,404):
                raise RuntimeError(f"No matching GFS forecast or filter error: HTTP {err.code}") from err
            cause=err
        except (URLError,RemoteDisconnected,HTTPException,TimeoutError,OSError,ValueError) as err:
            cause=err
        if attempt==retries-1:raise RuntimeError(f"GFS fetch failed: {cause}") from cause
        time.sleep(min(3*2**attempt,40))
    raise AssertionError("unreachable")


def decode(raw):
    found={}
    with tempfile.TemporaryFile() as f:
        f.write(raw);f.seek(0)
        while True:
            handle=eccodes.codes_grib_new_from_file(f)
            if handle is None:break
            try:
                category=int(eccodes.codes_get(handle,"parameterCategory"))
                number=int(eccodes.codes_get(handle,"parameterNumber"))
                if category!=6 or number not in NUMBER_KIND:continue
                kind=NUMBER_KIND[number]
                lat=np.asarray(eccodes.codes_get_array(handle,"latitudes"),dtype=np.float32)
                lon=np.asarray(eccodes.codes_get_array(handle,"longitudes"),dtype=np.float32)
                values=np.asarray(eccodes.codes_get_values(handle),dtype=np.float32)
                units=str(eccodes.codes_get(handle,"units"))
                if len(values)<1000 or len(values)!=len(lat) or len(values)!=len(lon):
                    raise RuntimeError("GFS grid invalid")
                if units not in ("%","percent"):
                    raise RuntimeError(f"Unexpected GFS cloud unit: {units}")
                if np.nanmin(values)<0 or np.nanmax(values)>100.01:
                    raise RuntimeError("GFS cloud values outside 0-100 percent")
                if kind in found:raise RuntimeError(f"Multiple GFS {kind} fields, level filter ambiguous")
                found[kind]=(lat,lon,values)
            finally:eccodes.codes_release(handle)
    if set(found)!=set(NUMBER_KIND.values()):
        raise RuntimeError(f"GFS filtered cloud fields missing: {set(NUMBER_KIND.values())-set(found)}")
    return found


def output_array(lat,lon,values):
    longitude=np.where(lon>180,lon-360,lon)
    xlon,xlat=np.meshgrid(np.linspace(WEST,EAST,WIDTH),np.linspace(NORTH,SOUTH,HEIGHT))
    tree=cKDTree(np.column_stack((lat.ravel(),longitude.ravel())))
    dist,index=tree.query(np.column_stack((xlat.ravel(),xlon.ravel())),workers=2)
    valid=(dist<=0.23)&np.isfinite(values[index])
    if valid.mean()<.995:
        raise RuntimeError(f"GFS cloud coverage too low: {valid.mean():.2%}")
    out=np.full(WIDTH*HEIGHT,255,dtype=np.uint8)
    out[valid]=np.round(np.clip(values[index][valid],0,100)*2.54).astype(np.uint8)
    return out.reshape(HEIGHT,WIDTH)


def find_run():
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    now-=timedelta(hours=now.hour%6)
    for lag in range(1,6):
        run=now-timedelta(hours=lag*6)
        try:
            decode(retrieve(url_for(run,HOURS[-1]),retries=1))
            return run
        except Exception as exc:
            LOG.warning("GFS +36h unavailable %s: %s",run,exc)
    raise RuntimeError("No complete public GFS cloud cycle")


def build(out):
    out.mkdir(parents=True,exist_ok=True)
    run=find_run()
    path=out/"current.json"
    if path.exists():
        try:
            old=json.loads(path.read_text())
            if old.get("cycle")==f"{run:%Y%m%d%H}" and len(old.get("frames",[]))==len(HOURS):
                if all((out/f).exists() for row in old["frames"] for f in row["layers"].values()):
                    LOG.info("GFS already complete");return
        except (ValueError,OSError,KeyError):pass
    frames=[]
    for hour in HOURS:
        fields=decode(retrieve(url_for(run,hour)))
        dest=out/"frames"/f"{run:%Y%m%d%H}";dest.mkdir(parents=True,exist_ok=True)
        layers={}
        for kind,(lat,lon,values) in fields.items():
            filename=f"{kind}_{hour:03d}.png"
            Image.fromarray(output_array(lat,lon,values),mode="L").save(dest/filename,optimize=True)
            layers[kind]=f"frames/{run:%Y%m%d%H}/{filename}"
        frames.append({"hour":hour,
                       "valid_utc":(run+timedelta(hours=hour)).isoformat().replace("+00:00","Z"),
                       "layers":layers})
        LOG.info("GFS clouds +%02d complete",hour)
        time.sleep(2)
    manifest={
       "schema":1,"source_id":"gfs","model":"NOAA GFS 0.25 degree",
       "cycle":f"{run:%Y%m%d%H}","initialized_utc":run.isoformat().replace("+00:00","Z"),
       "built_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
       "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,"step":STEP,
               "width":WIDTH,"height":HEIGHT},
       "source_resolution":"0.25 degree native; reprojected to 0.025 degree for display ONLY",
       "step_hours":3,"unit":"cloud_cover_percent",
       "encoding":"PNG L: 0-254 cloud 0-100%, 255 missing",
       "layers":{"clcl":"LCDC","clcm":"MCDC","clch":"HCDC","clct":"TCDC"},
       "frames":frames,"source":"NOAA NOMADS GRIB Filter GFS 0.25 degree",
    }
    for frame in frames:
        for f in frame["layers"].values():
            if not (out/f).is_file():raise RuntimeError(f"Missing GFS file: {f}")
    tmp=out/"current.json.tmp"
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    tmp.replace(path)
    LOG.info("Published %d genuine GFS cloud forecasts",len(frames))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    logging.basicConfig(level=logging.INFO)
    build(args.out)
