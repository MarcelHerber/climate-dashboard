#!/usr/bin/env python3
"""Build 1991–2020 CPC-grid daily normals from verified original CFS TMP2M files.

Require 30 complete years and 4 genuine zero-lead UTC samples/day. CFSR ends
March 2011; CFSv2 starts April 2011. A missing or forecast-replaced sample
blocks publication. Never use CPC or ERA5 as a substitute.
"""
from __future__ import annotations
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import re
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"gfs_analysis_europe"/"reference_sources"
DEST=ROOT/"gfs_analysis_europe"/"climatology_1991_2020.npz"
H,W=76,140
REFERENCE_NAME="CFSR 1991-03/2011 + CFSv2 04/2011-2020"
APPROVED_HOSTS={"www.ncei.noaa.gov","ncei.noaa.gov","gdex.ucar.edu","rda.ucar.edu"}

def expected_days(year: int)->list[str]:
    start=date(year,1,1)
    stop=date(year+1,1,1)
    days=[start+timedelta(days=n) for n in range((stop-start).days)]
    return [d.isoformat() for d in days if (d.month,d.day)!=(2,29)]

def expected_product(year: int)->str:
    return "CFSR" if year<=2010 else ("CFSR+CFSv2" if year==2011 else "CFSv2")

def check_source(year:int,path:Path)->tuple[np.ndarray,dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing official CFSR/CFSv2 year {year}: {path}")
    with np.load(path,allow_pickle=False) as z:
        values=np.asarray(z["temp_c"],dtype=np.float32)
        days=z["dates"].tolist()
        meta=json.loads(str(z["metadata_json"]))
    if values.shape!=(365,4,H,W) or days!=expected_days(year):
        raise ValueError(f"Wrong dates, 4 cycles or grid: {year}")
    if meta.get("year")!=year or meta.get("product")!=expected_product(year):
        raise ValueError(f"Wrong CFSR/CFSv2 split or product in {year}")
    if meta.get("forecast_hour")!=0 or meta.get("hours_utc")!=[0,6,12,18]:
        raise ValueError(f"Wrong zero-lead synoptic field selection in {year}")
    if meta.get("parameter")!="2m temperature" or meta.get("units")!="degC":
        raise ValueError(f"Incorrect temperature variable/units in {year}")
    origins=meta.get("source_files",[])
    if len(origins)!=12 or [item.get("month") for item in origins]!=list(range(1,13)):
        raise ValueError(f"Missing NCEI monthly GRIB source checksums: {year}")
    for source in origins:
        m=source["month"]
        expected="CFSR" if (year,m)<(2011,4) else "CFSv2"
        url=source.get("primary_source_url","")
        checksum=source.get("primary_source_sha256","")
        if source.get("product")!=expected or not isinstance(url,str) or not url.startswith("https://"):
            raise ValueError(f"Unverified historical source product in {year}-{m:02d}")
        if url.split("/")[2] not in APPROVED_HOSTS or not re.fullmatch("[0-9a-f]{64}",str(checksum)):
            raise ValueError(f"Invalid original NCEI/NCAR provenance in {year}-{m:02d}")
        actual=len([d for d in expected_days(year) if d[5:7]==f"{m:02d}"])
        if source.get("days")!=actual:
            raise ValueError(f"Wrong source-day coverage in {year}-{m:02d}")
    if not np.isfinite(values).all() or not np.all((-100<values)&(values<80)):
        raise ValueError(f"Missing/implausible real CFS 2m temperatures: {year}")
    return values,meta

def make_normals(source:Path=SOURCE)->tuple[np.ndarray,np.ndarray,list[dict]]:
    total=np.zeros((365,H,W),dtype=np.float64)
    count=np.zeros((365,H,W),dtype=np.int16)
    origins=[]
    for year in range(1991,2021):
        sample,meta=check_source(year,source/f"t2m_6h_{year}.npz")
        day=sample.mean(axis=1,dtype=np.float64)
        total+=day
        count+=np.isfinite(day).astype(np.int16)
        origins.append(meta)
    if not np.all(count==30):
        raise ValueError("Incomplete 1991–2020 climatology: not 30 years/day/grid cell")
    base=total/count
    smooth=sum(np.roll(base,delta,axis=0) for delta in (-2,-1,0,1,2))/5
    return smooth.astype(np.float32),count,origins

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,default=SOURCE)
    p.add_argument("--output",type=Path,default=DEST)
    args=p.parse_args()
    normal,count,origins=make_normals(args.source)
    metadata={
        "source":REFERENCE_NAME,
        "first_year":1991,"last_year":2020,"years":30,
        "sample_hours_utc":[0,6,12,18],
        "forecast_hour":0,
        "grid":"CPC-aligned GFS 0.5 degree Europe",
        "reference":"1991-2020",
        "reference_smoothing":"circular five-day daily normal",
        "daily_source_files":len(origins),
        "source_months":sum(len(meta["source_files"]) for meta in origins),
        "sources":origins,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(args.output,normal_t2m_c=normal,
                        year_count=count,metadata_json=json.dumps(metadata))
    print("Built CFSR/CFSv2 1991–2020 reference from 360 verified monthly originals",
          args.output, normal.shape, flush=True)

if __name__=="__main__":
    main()
