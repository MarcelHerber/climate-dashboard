#!/usr/bin/env python3
"""Fully verified 1991–2020 0.5° CFSR/CFSv2 f003 climatology on wider map.

Extended domain: 80.25°W–99.75°E, 24.75°N–84.75°N (121×361).
Uses only 30 complete annual daily means from original 360 monthly sources.
A strict overlap check guarantees the ORIGINAL 76×140 European climatology
is unchanged. No extended anomaly is published unless this test passes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import numpy as np

from scripts import build_gfs_cfsr_f003_1991_2020 as core
from scripts import probe_cfs_f003_wider_europe as wide

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"gfs_analysis_europe/reference_sources_f003_extended"
DEST=ROOT/"gfs_analysis_europe/climatology_1991_2020_f003_extended.npz"
CORE=ROOT/"gfs_analysis_europe/climatology_1991_2020_f003.npz"


def check_year(year:int,path:Path)->tuple[np.ndarray,dict]:
    if year not in range(1991,2021) or not path.exists():
        raise FileNotFoundError(f"Missing expanded original CFS reference year {year}")
    with np.load(path,allow_pickle=False) as z:
        sample=np.asarray(z["temperature_daily_c"],dtype=np.float32)
        dates=z["dates"].tolist()
        meta=json.loads(str(z["metadata_json"]))
    if sample.shape!=(365,wide.H,wide.W) or dates!=core.expected_days(year):
        raise ValueError(f"Extended original year {year} missing days or wrong spatial grid")
    if (meta.get("year")!=year or meta.get("product")!=core.expected_product(year)
        or meta.get("forecast_hour")!=3 or meta.get("hours_utc")!=[3,9,15,21]
        or meta.get("cycles_utc")!=[0,6,12,18]):
        raise ValueError(f"Incorrect CFSR/CFSv2 original source identity: {year}")
    if (meta.get("shape")!=[365,wide.H,wide.W]
        or meta.get("north")!=wide.NORTH or meta.get("west")!=wide.WEST
        or meta.get("east")!=wide.WEST+.5*(wide.W-1)):
        raise ValueError(f"Expanded grid metadata invalid: {year}")
    provenance=meta.get("source_files")
    if not isinstance(provenance,list) or len(provenance)!=12:
        raise ValueError(f"Missing verified monthly f003 source archive checksums: {year}")
    for i,p in enumerate(provenance,1):
        product="CFSR" if (year,i)<(2011,4) else "CFSv2"
        url=p.get("primary_source_url","")
        if (p.get("month")!=i or p.get("product")!=product
            or not url.startswith("https://")
            or url.split("/")[2] not in core.APPROVED_HOSTS
            or not re.fullmatch(r"[0-9a-f]{64}",str(p.get("primary_source_sha256","")))):
            raise ValueError(f"Original monthly source invalid {year}-{i:02d}")
        n=len([d for d in dates if int(d[5:7])==i])
        if p.get("days")!=n:
            raise ValueError(f"Missing days in monthly original {year}-{i:02d}")
    if not np.isfinite(sample).all() or not np.all((-100<sample)&(sample<70)):
        raise ValueError(f"Historical original temperatures out of bounds {year}")
    return sample,meta


def build(source:Path=SOURCE,dest:Path=DEST,core_path:Path=CORE)->dict:
    total=np.zeros((365,wide.H,wide.W),dtype=np.float64)
    count=np.zeros((365,wide.H,wide.W),dtype=np.uint8)
    annual=[]
    for year in range(1991,2021):
        data,meta=check_year(year,source/f"t2m_f003_extended_{year}.npz")
        total+=data
        count+=1
        annual.append(meta)
        print(f"Verified enlarged {year}/30 years",flush=True)
    if not np.all(count==30):
        raise ValueError("Not all 30 original CFS years cover the enlarged 0.5° grid")
    normal=total/30
    smoothed=sum(np.roll(normal,dy,axis=0) for dy in (-2,-1,0,1,2))/5
    smoothed=smoothed.astype(np.float32)
    if not core_path.exists():
        raise RuntimeError("Old independently verified 1991–2020 core reference missing")
    with np.load(core_path,allow_pickle=False) as baseline:
        core_normal=np.asarray(baseline["normal_t2m_c"],dtype=np.float32)
        original_meta=json.loads(str(baseline["metadata_json"]))
    if original_meta.get("source_months")!=360 or original_meta.get("forecast_hour")!=3:
        raise ValueError("Old core 30-year f003 reference is unverified")
    actual_core=smoothed[:,wide.CORE_Y:wide.CORE_Y+wide.CORE_H,
                            wide.CORE_X:wide.CORE_X+wide.CORE_W]
    max_overlap=float(np.max(np.abs(actual_core-core_normal)))
    if core_normal.shape!=(365,76,140) or max_overlap>0.001:
        raise ValueError(f"Expanded 1991–2020 original-reference mismatch in Europe: {max_overlap} K")
    meta={
        "source":"CFSR 1991-03/2011 + CFSv2 04/2011-2020 (T2M f003)",
        "reference_version":"cfsr-cfsv2-t2m-f003-extended-v1",
        "reference":"1991-2020","forecast_hour":3,
        "first_year":1991,"last_year":2020,"years":30,
        "sample_hours_utc":[3,9,15,21],"cycles_utc":[0,6,12,18],
        "source_months":sum(len(y["source_files"]) for y in annual),
        "grid_degrees":.5,"height":wide.H,"width":wide.W,
        "lat_north":wide.NORTH,"lon_west":wide.WEST,
        "lat_south":wide.NORTH-.5*(wide.H-1),
        "lon_east":wide.WEST+.5*(wide.W-1),
        "reference_smoothing":"circular five-day daily normal",
        "old_core_max_difference_k":max_overlap,
        "source_years":[{"year":y["year"],"product":y["product"],
                         "source_files":y["source_files"]} for y in annual]
    }
    if meta["source_months"]!=360:
        raise ValueError("Missing original 360 CFSR/CFSv2 monthly archive checksums")
    dest.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(dest,normal_t2m_c=smoothed,
                        year_count=count,metadata_json=json.dumps(meta,separators=(",",":")))
    print(f"VERIFIED enlarged CFSR/CFSv2 f003 climatology: {dest} "
          f"shape={smoothed.shape} old_core_difference={max_overlap}K",flush=True)
    return meta


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,default=SOURCE)
    p.add_argument("--dest",type=Path,default=DEST)
    args=p.parse_args()
    build(args.source,args.dest)
