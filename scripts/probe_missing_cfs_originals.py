#!/usr/bin/env python3
"""Probe high-resolution CFSR/CFSv2 original month fallbacks from NCAR GDEX.

Read only the first 16 bytes using streamed HTTP; never download big originals
during this inexpensive source availability test.
"""
from __future__ import annotations
import requests
CASES = [(1992,7),(1996,8),(1998,4),(2000,4),(2001,5),(2002,12),(2007,4),(2008,9),(2009,2),(2010,1),(2018,9)]

def gdex_url(year, month):
    dataset = "d093001" if (year,month)<(2011,4) else "d094001"
    ym=f"{year:04d}{month:02d}"
    filename = (f"tmp2m.gdas.{ym}.grb2" if dataset=="d093001"
                else f"tmp2m.cdas1.{ym}.grb2")
    return f"https://tds.gdex.ucar.edu/thredds/fileServer/files/g/{dataset}/{year}/{filename}"

def probe(year,month):
    url=gdex_url(year,month)
    try:
        with requests.get(url,headers={"Range":"bytes=0-15",
            "Accept-Encoding":"identity","User-Agent":"ClimateDashboard/1.0 source-verification"},
            timeout=(10,40),stream=True) as response:
            head = response.raw.read(16) if response.status_code in (200,206) else b""
            good=(head.startswith(b"GRIB") and len(head)>=8 and head[7]==2)
            print(f"{year}-{month:02d}: status={response.status_code} "
                  f"GRIB2={good} range={response.headers.get('Content-Range','')} url={url}",flush=True)
            return good
    except requests.RequestException as exc:
        print(f"{year}-{month:02d}: error={exc!s} url={url}",flush=True)
        return False

if __name__=="__main__":
    results={f"{y:04d}-{m:02d}":probe(y,m) for y,m in CASES}
    print("Available alternate originals:",sum(results.values()),"of",len(results),flush=True)
    if not all(results.values()):
        raise SystemExit("Some high-resolution originals need another source; do not substitute low-resolution files")
