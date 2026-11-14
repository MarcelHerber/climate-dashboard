#!/usr/bin/env python3
"""Probe genuine 1991–2020 CFSR/CFSv2 TMP2M f003 on a wider map.

Before expanding the GFS anomaly map, check that the SAME native original
GRIB2 month supports an extended 0.5 degree grid from the North Atlantic to
the Urals without inventing new temperature normals.

The current validated core Europe rectangle is a strict subset of the new
target, and native old/new values must be numerically identical on the overlap.
This pilot DOES NOT claim a completed 1991–2020 extended reference.
"""
from __future__ import annotations
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile
import numpy as np

from scripts import import_cfsr_cfsv2_f003_1991_2020 as orig

NORTH=84.75
WEST=-80.25
GRID_DEG=0.5
H,W=121,361
CORE_Y=26
CORE_X=111
CORE_H,CORE_W=76,140

def configure_extended():
    orig.H=H
    orig.W=W
    orig.TARGET_LAT=NORTH-np.arange(H)*GRID_DEG
    orig.TARGET_LON=(WEST+np.arange(W)*GRID_DEG)%360

def probe(year:int,month:int,out:Path) -> dict:
    if not 1991<=year<=2020 or not 1<=month<=12:
        raise ValueError("Original CFSR/CFSv2 source must be 1991–2020")
    sources=[orig.source_url(year,month)]+orig.alternate_source_urls(year,month)
    with tempfile.TemporaryDirectory(prefix="cfs-extended-") as td:
        target=Path(td)/"source.grib2"
        errors=[]
        values=None
        for url in sources:
            try:
                digest=orig.download_original(url,target)
                configure_extended()
                values=orig.decode_month(target,year,month)
                print("Extended original GRIB verified",url,flush=True)
                break
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        if values is None:
            raise RuntimeError("No genuine expanded CFSR/CFSv2 source: "+" / ".join(errors[-3:]))
        # Compare same original GRIB fields on the old verified target grid:
        orig.H=CORE_H
        orig.W=CORE_W
        orig.TARGET_LAT=71.75-np.arange(CORE_H)*0.5
        orig.TARGET_LON=(-24.75+np.arange(CORE_W)*0.5)%360
        core=orig.decode_month(target,year,month)
    if set(values)!=set(core):
        raise ValueError("Different available days on expanded target")
    max_abs=0
    for day in sorted(values):
        enlarged=values[day]
        reference=core[day]
        if enlarged.shape!=(4,H,W) or reference.shape!=(4,CORE_H,CORE_W):
            raise ValueError("Wrong original 4 cycles or target dimensions")
        difference=np.max(np.abs(enlarged[:,CORE_Y:CORE_Y+CORE_H,
                                          CORE_X:CORE_X+CORE_W]-reference))
        max_abs=max(max_abs,float(difference))
    if max_abs>0.001:
        raise ValueError(f"Extended regrid changed existing CFSR reference pixels: {max_abs}")
    daily=np.stack([values[d].mean(axis=0) for d in sorted(values)])
    if not np.isfinite(daily).all() or not np.all((-100<daily)&(70>daily)):
        raise ValueError("Unphysical original expanded 2m temperature")
    meta={
        "pilot_only":True,
        "period":f"{year:04d}-{month:02d}",
        "reference_model":orig.product_for_month(year,month),
        "forecast_hour":3,
        "hours_utc":[3,9,15,21],
        "original_url":url,
        "original_sha256":digest,
        "original_2m_grib_samples":len(values)*4,
        "grid_degrees":GRID_DEG,
        "north":NORTH,"west":WEST,"height":H,"width":W,
        "south":NORTH-(H-1)*GRID_DEG,"east":WEST+(W-1)*GRID_DEG,
        "original_core_max_difference_k":max_abs,
        "extended_1991_2020_complete":False
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out,temperature_daily_c=daily.astype(np.float32),
                        dates=np.asarray([d.isoformat() for d in sorted(values)]),
                        metadata_json=json.dumps(meta))
    print(json.dumps(meta,indent=2),flush=True)
    return meta

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--year",type=int,default=2020)
    ap.add_argument("--month",type=int,default=12)
    ap.add_argument("--out",type=Path,default=Path("gfs_analysis_europe/extended_pilot_2020_12.npz"))
    args=ap.parse_args()
    probe(args.year,args.month,args.out)
