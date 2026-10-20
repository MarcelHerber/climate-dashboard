#!/usr/bin/env python3
"""ECMWF Open Data cloud adapter: AIFS cloud layers, IFS total cloud only.

AIFS exposes LCC/MCC/HCC/TCC at 0.25 degrees and 6-hour times;
open IFS exposes TCC at 0.25 degrees and 3-hour times.
Never manufacture low/mid/high from IFS TCC or upscale genuine resolution.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta,timezone
import json
import logging
from pathlib import Path
import tempfile
import eccodes
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
from ecmwf.opendata import Client
from build_icon_d2_cloud_film import WEST,EAST,SOUTH,NORTH,STEP,WIDTH,HEIGHT

LOG=logging.getLogger("ecmwf-cloud-mixer")
MODELS={"ecmwf-aifs":{"model":"aifs-single","kinds":{"lcc":"clcl","mcc":"clcm","hcc":"clch","tcc":"clct"},"hours":tuple(range(6,37,6))},
        "ecmwf-ifs":{"model":"ifs","kinds":{"tcc":"clct"},"hours":tuple(range(0,37,3))}}


def field_data(path,kinds):
    result={}
    with path.open("rb") as f:
        while True:
            handle=eccodes.codes_grib_new_from_file(f)
            if handle is None:break
            try:
                name=str(eccodes.codes_get(handle,"shortName")).lower()
                if name not in kinds:continue
                lat=np.asarray(eccodes.codes_get_array(handle,"latitudes"),dtype=np.float32)
                lon=np.asarray(eccodes.codes_get_array(handle,"longitudes"),dtype=np.float32)
                val=np.asarray(eccodes.codes_get_values(handle),dtype=np.float32)
                unit=str(eccodes.codes_get(handle,"units"))
                if len(val)!=len(lat) or len(val)!=len(lon) or len(val)<1000:
                    raise RuntimeError("ECMWF cloud grid invalid")
                if unit in ("(0 - 1)","1","~","fraction"):
                    val=val*100
                elif unit not in ("%","percent"):
                    # ecCodes can label ECMWF fractions as numeric '1'.
                    if np.nanmax(val)<=1.001 and np.nanmin(val)>=0:
                        val=val*100
                    else:
                        raise RuntimeError("Unknown ECMWF cloud unit: "+unit)
                if np.nanmin(val)<-.001 or np.nanmax(val)>100.1:
                    raise RuntimeError("ECMWF cloud field outside valid fraction")
                result[kinds[name]]=(lat,lon,np.clip(val,0,100))
            finally:eccodes.codes_release(handle)
    if set(result)!=set(kinds.values()):
        raise RuntimeError("ECMWF cloud fields missing; no synthetic replacement: "
                           +str(set(kinds.values())-set(result)))
    return result


def to_germany(lat,lon,values):
    shifted=np.where(lon>180,lon-360,lon)
    subset=(lat>=SOUTH-1)&(lat<=NORTH+1)&(shifted>=WEST-1)&(shifted<=EAST+1)
    coords=np.column_stack((lat[subset],shifted[subset]))
    if coords.shape[0]<1000:raise RuntimeError("ECMWF GRIB does not cover Germany")
    lat2,lon2=np.meshgrid(np.linspace(NORTH,SOUTH,HEIGHT),np.linspace(WEST,EAST,WIDTH),indexing="ij")
    tree=cKDTree(coords)
    dist,index=tree.query(np.column_stack((lat2.ravel(),lon2.ravel())),workers=2)
    # 0.25-degree source, nearest point within 0.23 degree.
    good=(dist<=0.23)&np.isfinite(values[subset][index])
    if np.mean(good)<.995:raise RuntimeError("ECMWF Germany map incomplete")
    arr=np.full(WIDTH*HEIGHT,255,np.uint8)
    arr[good]=np.round(values[subset][index][good]*2.54).astype(np.uint8)
    return arr.reshape(HEIGHT,WIDTH)


def fetch(client,run,hour,kinds):
    with tempfile.TemporaryDirectory() as d:
        path=Path(d)/"clouds.grib2"
        client.retrieve(date=run.strftime("%Y%m%d"),time=run.hour,stream="oper",
                        type="fc",step=hour,levtype="sfc",param=list(kinds),target=str(path))
        return field_data(path,kinds)


def cycle_candidates():
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    aligned=now-timedelta(hours=now.hour%6)
    return [aligned-timedelta(hours=6*lag) for lag in range(1,9)]


def build(model_id,out):
    cfg=MODELS[model_id];out.mkdir(parents=True,exist_ok=True)
    client=Client(source="ecmwf",model=cfg["model"])
    run=None
    for candidate in cycle_candidates():
        try:
            fetch(client,candidate,cfg["hours"][-1],cfg["kinds"])
            run=candidate
            break
        except Exception as error:
            LOG.warning("%s incomplete cycle %s: %s",model_id,candidate,error)
    if run is None:raise RuntimeError("No verified current ECMWF cloud cycle")
    out_manifest=out/"current.json"
    if out_manifest.exists():
        try:
            old=json.loads(out_manifest.read_text())
            if old.get("cycle")==f"{run:%Y%m%d%H}" and len(old.get("frames",[]))==len(cfg["hours"]):
                if all((out/f).exists() for row in old["frames"] for f in row["layers"].values()):
                    LOG.info("Current ECMWF cloud output already complete");return
        except (ValueError,OSError,KeyError):pass
    frames=[]
    for hour in cfg["hours"]:
        fields=fetch(client,run,hour,cfg["kinds"])
        folder=out/"frames"/f"{run:%Y%m%d%H}"
        folder.mkdir(parents=True,exist_ok=True)
        layers={}
        for kind,(lat,lon,val) in fields.items():
            filename=f"{kind}_{hour:03d}.png"
            Image.fromarray(to_germany(lat,lon,val),mode="L").save(folder/filename,optimize=True)
            layers[kind]=f"frames/{run:%Y%m%d%H}/{filename}"
        frames.append({"hour":hour,"valid_utc":(run+timedelta(hours=hour)).isoformat().replace("+00:00","Z"),
                       "layers":layers})
        LOG.info("ECMWF %s +%02dh downloaded",model_id,hour)
    manifest={
      "schema":1,"source_id":model_id,"model":"ECMWF "+cfg["model"],
      "cycle":f"{run:%Y%m%d%H}","initialized_utc":run.isoformat().replace("+00:00","Z"),
      "built_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,"step":STEP,"width":WIDTH,"height":HEIGHT},
      "source_resolution":"0.25 degree native; geographically regridded 0.025 degree for display only",
      "step_hours":cfg["hours"][1],"unit":"cloud_cover_percent",
      "encoding":"PNG L: 0-254 cloud 0-100 percent, 255 missing",
      "layers":{kind:kind for kind in cfg["kinds"].values()},
      "frames":frames,"source":"ECMWF Free Open Data, CC-BY-4.0",
    }
    for f in frames:
        for src in f["layers"].values():
            if not (out/src).is_file():raise RuntimeError("Missing ECMWF forecast: "+src)
    tmp=out/"current.json.tmp"
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    tmp.replace(out_manifest)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source-id",required=True,choices=MODELS)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    logging.basicConfig(level=logging.INFO)
    build(a.source_id,a.out)
