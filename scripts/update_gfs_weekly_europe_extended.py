#!/usr/bin/env python3
"""Production NOAA GFS 0.5° f003..f165 weekly temperature anomalies on wider Europe.

The original 76x140 GFS/CFSR Europe remains intact.  This publishes a
*separate* extended 121x361 NOAA GFS forecast and checks the historical
1991–2020 CFSR/CFSv2 f003 climatology before any wide anomaly release.

Bounds (grid centres): 80.25°W..99.75°E and 24.75°N..84.75°N.
No f000 substitutions, no synthetic time slices, no incomplete lead steps.
"""
from __future__ import annotations
import argparse
from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time

import numpy as np
import requests

from scripts import update_gfs_weekly_europe as base
from scripts import update_gfs_f003_europe as daily

ROOT=Path(__file__).resolve().parents[1]
NORMAL=ROOT/"gfs_analysis_europe/climatology_1991_2020_f003_extended.npz"
OUTPUT=ROOT/"gfs_analysis_europe/weekly_f003_extended.json"
H,W=121,361
LAT_NORTH,LAT_SOUTH=84.75,24.75
LON_WEST,LON_EAST=-80.25,99.75
Y0,X0=26,111


def load_reference(path:Path=NORMAL)->tuple[np.ndarray,dict]:
    if not path.exists():
        raise RuntimeError("The full 30-year extended original CFSR/CFSv2 climatology has not finished")
    with np.load(path,allow_pickle=False) as z:
        vals=np.asarray(z["normal_t2m_c"],dtype=np.float32)
        count=np.asarray(z["year_count"])
        meta=json.loads(str(z["metadata_json"]))
    if (vals.shape!=(365,H,W) or count.shape!=vals.shape or
        np.any(count!=30) or not np.isfinite(vals).all() or
        meta.get("reference_version")!="cfsr-cfsv2-t2m-f003-extended-v1" or
        meta.get("years")!=30 or meta.get("source_months")!=360 or
        meta.get("forecast_hour")!=3 or
        meta.get("old_core_max_difference_k",999)>0.001 or
        meta.get("grid_degrees")!=0.5 or
        (meta.get("lat_north"),meta.get("lat_south"),
         meta.get("lon_west"),meta.get("lon_east"))!=
        (LAT_NORTH,LAT_SOUTH,LON_WEST,LON_EAST)):
        raise ValueError("Extended CFSR/CFSv2 climate normal does not meet original-source contract")
    return vals,meta


def decode_extended_grib(raw:bytes,run:datetime,lead:int)->np.ndarray:
    import eccodes as ec
    # Validates exact NOAA TMP2m GRIB metadata, valid UTC time, lead and
    # original 0.5 degree 720x361 global raster as well as old-Europe control.
    previous=base.decode_grib(raw,run,lead)
    with tempfile.TemporaryFile(mode="w+b") as stream:
        stream.write(raw)
        stream.seek(0)
        gid=ec.codes_grib_new_from_file(stream)
        if gid is None:
            raise ValueError("Empty original NOAA GFS GRIB2")
        try:
            globe=np.asarray(ec.codes_get_values(gid),dtype=np.float32).reshape(361,720)
        finally:
            ec.codes_release(gid)
    # Native GFS points are lon 0/0.5/...359.5, lat 90/89.5/...-90.
    # Target centres are offset 0.25° from native points on both axes:
    # first upper native latitude is 85°N (global row 10)
    # first western native longitude is -80.5° (global column 559)
    region=globe[10:10+H+1,:][:,(559+np.arange(W+1))%720]
    if region.shape!=(H+1,W+1) or not np.isfinite(region).all():
        raise ValueError("NOAA extended global grid is incomplete")
    new=((region[:-1,:-1]+region[:-1,1:]+
          region[1:,:-1]+region[1:,1:])*np.float32(.25)-
         np.float32(273.15))
    if new.shape!=(H,W) or not np.all((-100<new)&(new<70)):
        raise ValueError("Extended original NOAA GFS temperatures out of physical bounds")
    match=float(np.max(np.abs(new[Y0:Y0+76,X0:X0+140]-previous)))
    if match>0.0001:
        raise ValueError(f"Old and extended real GFS overlap differ: {match} K")
    return new.astype(np.float32)


def fetch_field(run:datetime,lead:int)->tuple[np.ndarray,dict]:
    errors=[]
    for host in base.HOSTS:
        url=base.source_url(run,lead,host)
        for attempt in range(2):
            try:
                idx=requests.get(url+".idx",headers=base.USER_AGENT,timeout=(15,45))
                idx.raise_for_status()
                start,end=base.field_range(idx.text,run,lead)
                with requests.get(url,headers={**base.USER_AGENT,
                                  "Range":f"bytes={start}-{end}"},
                                  timeout=(20,70),stream=True) as response:
                    if response.status_code!=206:
                        raise ValueError(f"Server didn't honor exact GRIB byte-range: {response.status_code}")
                    response.raise_for_status()
                    raw=response.content
                if len(raw)!=end-start+1:
                    raise ValueError("Truncated original GFS field")
                field=decode_extended_grib(raw,run,lead)
                valid=run+timedelta(hours=lead)
                return field,{
                    "forecast_hour":lead,
                    "valid_utc":valid.isoformat().replace("+00:00","Z"),
                    "source_url":url,
                    "byte_range":f"bytes={start}-{end}",
                    "sha256":sha256(raw).hexdigest(),
                    "bytes":len(raw)
                }
            except (requests.RequestException,ValueError) as exc:
                errors.append(f"{host}/{attempt+1}: {exc}")
                if attempt==0:time.sleep(1)
    raise RuntimeError(f"Authentic GFS extended f{lead:03d} unavailable: "+" | ".join(errors[-4:]))


def calculate(run:datetime,fields:list[np.ndarray],normals:np.ndarray,meta:dict)->dict:
    if len(fields)!=28 or any(x.shape!=(H,W) or not np.isfinite(x).all() for x in fields):
        raise ValueError("Exactly 28 finite true NOAA GFS wider 0.5° fields required")
    if normals.shape!=(365,H,W):
        raise ValueError("Daily 30-year extended original normal has wrong shape")
    valid=[run+timedelta(hours=h) for h in base.LEADS]
    actual=np.mean(np.stack(fields),axis=0,dtype=np.float64).astype(np.float32)
    anomalies=np.mean(np.stack([
        sample-daily.normal_for_date(normals,at.date())
        for sample,at in zip(fields,valid)
    ]),axis=0,dtype=np.float64).astype(np.float32)
    if not np.isfinite(anomalies).all():
        raise ValueError("Incomplete extended CFSR anomalies")
    return {
      "schema":1,"type":"model_forecast_7day_not_observation",
      "provider":"NOAA NCEP GFS 0.5° short-to-medium-range forecast",
      "run_utc":run.isoformat().replace("+00:00","Z"),
      "valid_from_utc":valid[0].isoformat().replace("+00:00","Z"),
      "valid_to_utc":valid[-1].isoformat().replace("+00:00","Z"),
      "lead_hours":list(base.LEADS),"sample_count":28,"period_days":7,
      "grid_degrees":0.5,"width":W,"height":H,
      "lat_north":LAT_NORTH,"lat_south":LAT_SOUTH,
      "lon_west":LON_WEST,"lon_east":LON_EAST,
      "reference":"CFSR 1991-03/2011 + CFSv2 04/2011-2020; f003; 1991–2020",
      "reference_version":"cfsr-cfsv2-t2m-f003-extended-v1",
      "forecast_mean_q10_b64":daily.encode_q10(actual),
      "anomaly_mean_q10_b64":daily.encode_q10(anomalies),
      "method":"28 genuine NOAA GFS 0.5° TMP2m original fields f003–f165, "
               "each matched to date-valid original CFSR/CFSv2 f003 1991–2020 reference; "
               "five-day climatology smoothing; no f000 mixing",
      "reference_metadata":{
          "source":meta["source"],"years":meta["years"],
          "source_months":meta["source_months"],
          "forecast_hour":meta["forecast_hour"],
          "reference_version":meta["reference_version"],
          "old_core_max_difference_k":meta["old_core_max_difference_k"]
      }
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--run-date",type=date.fromisoformat)
    p.add_argument("--cycle",type=int)
    p.add_argument("--output",type=Path,default=OUTPUT)
    args=p.parse_args()
    reference,meta=load_reference()
    errors=[]
    for run in base.run_candidates(datetime.now(timezone.utc),
                                   day=args.run_date,cycle=args.cycle):
        try:
            fields,sources=[],[]
            for lead in base.LEADS:
                field,source=fetch_field(run,lead)
                fields.append(field)
                sources.append(source)
                print(f"Verified extended original GFS {run:%Y%m%d%H} f{lead:03d}",flush=True)
            result=calculate(run,fields,reference,meta)
            result["sources"]=sources
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,separators=(",",":"),ensure_ascii=False),
                                   encoding="utf-8")
            print("Verified GFS 7-day wider genuine 0.5° anomalies "+str(args.output),
                  run.isoformat(),flush=True)
            return
        except (RuntimeError,ValueError) as exc:
            errors.append(f"{run.isoformat()}: {exc}")
            print("GFS original run incomplete:",errors[-1],flush=True)
    raise RuntimeError("No fully verified GFS run on enlarged 0.5° grid: "+" | ".join(errors))


if __name__=="__main__":
    main()
