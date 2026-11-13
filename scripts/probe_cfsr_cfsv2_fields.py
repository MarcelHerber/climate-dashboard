#!/usr/bin/env python3
"""Lightweight live GRIB2 metadata proof before the massive CFS archive backfill.

Only small HTTPS byte ranges are downloaded, never the whole monthly archive.
Samples span CFSR 1991, CFSR March 2011, CFSv2 April 2011 and CFSv2 2020.
"""
from __future__ import annotations
import tempfile
import numpy as np
import collections
import requests

try:
    from scripts.import_cfsr_cfsv2_1991_2020 import source_url, interpolate_europe
except ModuleNotFoundError:
    from import_cfsr_cfsv2_1991_2020 import source_url, interpolate_europe

MONTHS = [(1991,1),(2011,3),(2011,4),(2020,12)]
BYTES_PER_SAMPLE=16*1024*1024

def inspect(year:int,month:int)->dict:
    import eccodes as ec
    u=source_url(year,month)
    resp=requests.get(u,headers={
        "Range": f"bytes=0-{BYTES_PER_SAMPLE-1}",
        "Accept-Encoding":"identity",
        "User-Agent":"climate-dashboard CFS reference validation",
    },timeout=(30,150))
    resp.raise_for_status()
    if resp.status_code!=206:
        raise ValueError(f"Range not honored by {u}: HTTP {resp.status_code}")
    raw=resp.content
    if len(raw)!=BYTES_PER_SAMPLE or not raw.startswith(b"GRIB"):
        raise ValueError(f"Not an intact GRIB prefix: {u}, bytes={len(raw)}")
    cursor=tempfile.TemporaryFile(mode='w+b')
    cursor.write(raw)
    cursor.seek(0)
    meta=[]
    real_field_checked=False
    while cursor.tell() < len(raw)-2_000_000 and len(meta)<32:
        pos=cursor.tell()
        try:
            gid=ec.codes_grib_new_from_file(cursor)
        except Exception as exc:
            print(f"Sample truncated at byte {pos}: {str(exc)[:180]}",flush=True)
            break
        if gid is None:break
        try:
            keys=("dataDate","dataTime","validityDate","validityTime",
                  "forecastTime","stepRange","typeOfLevel","level",
                  "shortName","Ni","Nj")
            values={}
            for key in keys:
                try: values[key]=ec.codes_get(gid,key)
                except Exception: values[key]="unavailable"
            meta.append(values)
            if (not real_field_checked and values["forecastTime"]==0 and
                values["typeOfLevel"]=="heightAboveGround" and
                values["level"]==2 and values["shortName"]=="2t"):
                ni,nj=int(values["Ni"]),int(values["Nj"])
                temp=np.asarray(ec.codes_get_values(gid),dtype=np.float32).reshape(nj,ni)
                lats=np.asarray(ec.codes_get_array(gid,"latitudes")).reshape(nj,ni)
                lons=np.asarray(ec.codes_get_array(gid,"longitudes")).reshape(nj,ni)
                europe=interpolate_europe(temp,lats,lons)
                assert europe.shape==(76,140) and np.isfinite(europe).all()
                print(f"REAL 2m f000 Europe spatial interpolated {year}-{month:02d}: "
                      f"min={europe.min():.1f} C max={europe.max():.1f} C "
                      f"source={ni}x{nj}",flush=True)
                real_field_checked=True
        finally:
            ec.codes_release(gid)
    if not real_field_checked:
        raise ValueError(f'No real f000 2m temperature remappable for {year}-{month:02d}')
    if not meta:
        raise ValueError(f"No readable GRIB messages at {u}")
    print(f"OFFICIAL {year}-{month:02d} fields={len(meta)} {u}")
    for x in meta[:20]:print(x,flush=True)
    print("steps",dict(collections.Counter(str(x["forecastTime"]) for x in meta)),flush=True)
    return {"ym":f"{year}-{month:02d}","fields":len(meta),
            "steps":sorted(set(str(x["forecastTime"]) for x in meta)),
            "shapes":sorted(set((str(x["Ni"]),str(x["Nj"])) for x in meta))}

if __name__=="__main__":
    for year,month in MONTHS:
        print(inspect(year,month),flush=True)
