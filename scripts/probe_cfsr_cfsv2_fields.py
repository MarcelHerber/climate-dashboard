#!/usr/bin/env python3
"""Lightweight live GRIB2 metadata proof before the massive CFS archive backfill.

Only small HTTPS byte ranges are downloaded, never the whole monthly archive.
Samples span CFSR 1991, CFSR March 2011, CFSv2 April 2011 and CFSv2 2020.
"""
from __future__ import annotations
import io
import collections
import requests

try:
    from scripts.import_cfsr_cfsv2_1991_2020 import source_url
except ModuleNotFoundError:
    from import_cfsr_cfsv2_1991_2020 import source_url

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
    cursor=io.BytesIO(raw)
    meta=[]
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
        finally:
            ec.codes_release(gid)
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
