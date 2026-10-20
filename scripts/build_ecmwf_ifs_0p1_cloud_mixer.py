#!/usr/bin/env python3
"""ECMWF IFS Open Data 0.1-degree real cloud layers for the private Germany mixer.

The 0.1-degree OPEN-DATA grid (about 9 km) is distinct from the common
0.025-degree geographic display raster. No extra detail is manufactured.
A complete verified set of original LCC/MCC/HCC/TCC fields is published
atomically. The older IFS 0.25-degree manifest is left unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import tempfile

import eccodes
from ecmwf.opendata import Client
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

from build_icon_d2_cloud_film import WEST,EAST,SOUTH,NORTH,STEP,WIDTH,HEIGHT

LOG=logging.getLogger("ecmwf-ifs-0p1-clouds")
SOURCE_ID="ecmwf-ifs-0p1"
FIELDS={"lcc":"clcl","mcc":"clcm","hcc":"clch","tcc":"clct"}
HOURS=tuple(range(0,37,3))
SOURCE_RESOLUTION="0p1"
# 0.1 degree regular geographic input: half-cell diagonal ~0.071 degree.
DISTANCE_TOLERANCE=0.085

lat_target,lon_target=np.meshgrid(np.linspace(NORTH,SOUTH,HEIGHT),
                                   np.linspace(WEST,EAST,WIDTH),indexing="ij")
TARGETS=np.column_stack((lat_target.ravel(),lon_target.ravel()))


def to_germany(lat,lon,cloud_percent):
    """Nearest source cell, no sharpening/interpolation inventing detail."""
    longitude=np.where(lon>180,lon-360,lon)
    subset=(lat>=SOUTH-.4)&(lat<=NORTH+.4)&(longitude>=WEST-.4)&(longitude<=EAST+.4)
    if np.count_nonzero(subset)<3000:
        raise RuntimeError("ECMWF IFS 0.1° GRIB lacks Germany / unexpected coordinates")
    positions=np.column_stack((lat[subset],longitude[subset]))
    values=cloud_percent[subset]
    tree=cKDTree(positions)
    distance,index=tree.query(TARGETS,k=1,workers=2)
    sampled=values[index]
    good=(distance<=DISTANCE_TOLERANCE)&np.isfinite(sampled)&(sampled>=0)&(sampled<=100)
    if good.mean()<.99:
        raise RuntimeError(f"ECMWF IFS 0.1° Germany coverage only {good.mean():.2%}")
    encoded=np.full(WIDTH*HEIGHT,255,dtype=np.uint8)
    encoded[good]=np.rint(sampled[good]*2.54).astype(np.uint8)
    return encoded.reshape(HEIGHT,WIDTH)


def read_cloud_images(path):
    result={}
    with path.open("rb") as stream:
        while True:
            handle=eccodes.codes_grib_new_from_file(stream)
            if handle is None:break
            try:
                name=str(eccodes.codes_get(handle,"shortName")).lower()
                if name not in FIELDS:continue
                kind=FIELDS[name]
                if kind in result:
                    raise RuntimeError(f"IFS 0.1° duplicate {name} in filtered data")
                unit=str(eccodes.codes_get(handle,"units")).strip()
                # Decode one source field at a time and discard global arrays
                # immediately; retaining 4 global 0.1° fields uses much RAM.
                lat=np.asarray(eccodes.codes_get_array(handle,"latitudes"),dtype=np.float32)
                lon=np.asarray(eccodes.codes_get_array(handle,"longitudes"),dtype=np.float32)
                cloud=np.asarray(eccodes.codes_get_values(handle),dtype=np.float32)
                if len(lat)!=len(lon) or len(lat)!=len(cloud) or len(cloud)<100000:
                    raise RuntimeError(f"Invalid IFS 0.1° grid for {name}")
                if unit in ("(0 - 1)","1","~","fraction"):
                    cloud*=100
                elif unit not in ("%","percent"):
                    raise RuntimeError(f"Unknown ECMWF cloud unit for {name}: {unit}")
                result[kind]=to_germany(lat,lon,cloud)
            finally:
                eccodes.codes_release(handle)
    if set(result)!=set(FIELDS.values()):
        raise RuntimeError("IFS 0.1° missing genuine layers: "
                           +", ".join(sorted(set(FIELDS.values())-set(result))))
    return result


def retrieve_clouds(client,run,hour):
    with tempfile.TemporaryDirectory() as folder:
        target=Path(folder)/"ifs_0p1_clouds.grib2"
        # ecCodes/ECMWF .index byte-range retrieval: fetch only four clouds,
        # never download the full, much larger 0.1° forecast files.
        client.retrieve(date=run.strftime("%Y%m%d"),time=run.hour,
                        stream="oper",type="fc",step=hour,levtype="sfc",
                        param=list(FIELDS),resol="0p1",target=str(target))
        if not target.is_file() or target.stat().st_size<1000:
            raise RuntimeError("ECMWF IFS 0.1° index request returned no GRIB2 data")
        return read_cloud_images(target)


def candidates():
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    aligned=now-timedelta(hours=now.hour%6)
    # The new 0.1° open-data products are released after the 0.25° products.
    return [aligned-timedelta(hours=6*lag) for lag in range(1,9)]


def build(out:Path):
    out.mkdir(parents=True,exist_ok=True)
    client=Client(source="ecmwf",model="ifs",resol="0p1")
    cycle=None
    for candidate in candidates():
        try:
            retrieve_clouds(client,candidate,HOURS[-1])
            cycle=candidate
            break
        except Exception as err:
            LOG.warning("IFS 0.1° %s not fully released: %s",candidate,err)
    if cycle is None:
        raise RuntimeError("No verified ECMWF IFS 0.1° cloud cycle available")
    oldpath=out/"current.json"
    if oldpath.is_file():
        try:
            old=json.loads(oldpath.read_text(encoding="utf-8"))
            if old.get("source_id")==SOURCE_ID and old.get("cycle")==f"{cycle:%Y%m%d%H}":
                if len(old.get("frames",[]))>=12 and all(
                    (out/f).is_file() for row in old["frames"] for f in row["layers"].values()
                ):
                    LOG.info("IFS 0.1° data already complete for %s",cycle);return
        except (OSError,ValueError,KeyError):
            pass
    frames=[]
    dest=out/"frames"/f"{cycle:%Y%m%d%H}"
    dest.mkdir(parents=True,exist_ok=True)
    for hour in HOURS:
        try:
            data=retrieve_clouds(client,cycle,hour)
        except Exception:
            if hour==0:
                # Some ECMWF cloud parameters have no lead-zero forecast:
                # do not fabricate +0 or block the rest of the genuine run.
                LOG.warning("IFS 0.1° +0 h cloud fields missing; starting with +3 h")
                continue
            raise
        names={}
        for kind,values in data.items():
            filename=f"{kind}_{hour:03d}.png"
            Image.fromarray(values).save(dest/filename,optimize=True)
            names[kind]=f"frames/{cycle:%Y%m%d%H}/{filename}"
        frames.append({
            "hour":hour,
            "valid_utc":(cycle+timedelta(hours=hour)).isoformat().replace("+00:00","Z"),
            "layers":names,
        })
        LOG.info("ECMWF IFS 0.1° +%02d: all 4 original cloud levels",hour)
    if len(frames)<12 or any(set(row["layers"])!=set(FIELDS.values()) for row in frames):
        raise RuntimeError("IFS 0.1° incomplete cloud set; keeping previous manifest")
    manifest={
        "schema":1,"source_id":SOURCE_ID,"model":"ECMWF IFS HRES Open Data 0.1°",
        "cycle":f"{cycle:%Y%m%d%H}",
        "initialized_utc":cycle.isoformat().replace("+00:00","Z"),
        "built_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,"step":STEP,
                "width":WIDTH,"height":HEIGHT},
        "source_resolution":"0.1 degree ECMWF Open Data (~9 km); 0.025 degree image display only",
        "step_hours":3,"unit":"cloud_cover_percent",
        "encoding":"PNG L: 0-254 cloud cover 0-100%, 255 missing",
        "layers":{"clcl":"ECMWF low clouds (lcc)","clcm":"ECMWF middle clouds (mcc)",
                  "clch":"ECMWF high clouds (hcc)","clct":"ECMWF total cloud cover (tcc)"},
        "frames":frames,
        "source":"ECMWF IFS 0.1 degree Free Open Data, CC BY 4.0",
        "notice":"The 0.025-degree display raster does not increase the native 0.1-degree resolution."
    }
    tmp=out/"current.json.tmp"
    tmp.write_text(json.dumps(manifest,separators=(",",":"),ensure_ascii=False),encoding="utf-8")
    tmp.replace(oldpath)
    LOG.info("VERIFIED: ECMWF IFS 0.1° %s, %d genuine cloud frames",cycle,len(frames))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    a=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    build(a.out)
