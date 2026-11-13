#!/usr/bin/env python3
"""Bounded live GRIB2 metadata inspection of NCAR GDEX historical TMP2M files.

Downloads the first ~16 MB only, checks GRIB metadata in the same ecCodes
decoder as production; never assumes GRIB2 header alone means f000 analysis.
"""
from __future__ import annotations
import argparse
import tempfile
import requests
from scripts.import_cfsr_cfsv2_1991_2020 import alternate_source_urls

MONTHS=[(1992,7),(2002,12),(2018,9)]
BYTES=16*1024*1024
KEYS=["edition","shortName","discipline","parameterCategory","parameterNumber",
      "typeOfLevel","level","dataDate","dataTime","validityDate","validityTime",
      "forecastTime","stepRange","stepType","typeOfGeneratingProcess","Ni","Nj"]

def inspect(year:int,month:int,require_zero_lead:bool=False)->None:
    import eccodes as ec
    url=alternate_source_urls(year,month)[0]
    print(f"INSPECT {year}-{month:02d}: {url}",flush=True)
    r=requests.get(url,headers={"Range":f"bytes=0-{BYTES-1}","Accept-Encoding":"identity"},
                   timeout=(25,150),stream=True)
    r.raise_for_status()
    if r.status_code!=206:
        raise ValueError(f"Range unsupported: {r.status_code}")
    with tempfile.TemporaryFile(mode="w+b") as f:
        for chunk in r.iter_content(chunk_size=1024*1024):
            f.write(chunk)
            if f.tell() >= BYTES:break
        f.seek(0)
        print(f"  downloaded {BYTES} bytes; response={r.status_code}",flush=True)
        seen=0
        first_day_steps=set()
        while seen<20:
            pos=f.tell()
            try:gid=ec.codes_grib_new_from_file(f)
            except Exception as exc:
                print(f"  reached partial frame at {pos}: {str(exc)[:130]}",flush=True)
                break
            if gid is None:break
            try:
                result={}
                for key in KEYS:
                    try:result[key]=ec.codes_get(gid,key)
                    except Exception as exc:result[key]=str(exc)[:60]
                if (result.get("dataDate")==year*10000+month*100+1 and
                    result.get("parameterNumber")==0 and result.get("level")==2):
                    first_day_steps.add(result.get("forecastTime"))
                print(f"  GRIB {seen}: {result}",flush=True)
                seen+=1
            finally:ec.codes_release(gid)
        if not seen:
            raise RuntimeError(f"No readable GRIB2 messages in first {BYTES} bytes: {url}")
        print(f"  fields observed {seen}; first day steps {sorted(first_day_steps)}",flush=True)
        if require_zero_lead and 0 not in first_day_steps:
            raise RuntimeError(
                f"NCAR GDEX fallback {year}-{month:02d} lacks CFS TMP2M f000; "
                "this valid GRIB2 source provides only short forecasts. "
                "STOP recovery: do not mix f001 with f000 in the 1991–2020 reference."
            )

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--require-zero-lead",action="store_true")
    args=parser.parse_args()
    for year,month in MONTHS:
        inspect(year,month,require_zero_lead=args.require_zero_lead)
