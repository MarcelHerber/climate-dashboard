#!/usr/bin/env python3
"""Check exact official NCEI GRIB monthly endpoints with <=16 bytes transferred.

A streamed HTTP request is closed immediately after the GRIB signature; it
never loads a whole 0.5–1 GB month. A 200 without byte-range support is
still safe here, but is reported as such.
"""
from __future__ import annotations
import argparse
import requests
try:
    from scripts.import_cfsr_cfsv2_1991_2020 import source_url
except ModuleNotFoundError:
    from import_cfsr_cfsv2_1991_2020 import source_url


def probe(url: str) -> dict:
    with requests.get(
        url,
        headers={"Range":"bytes=0-15","Accept-Encoding":"identity",
                 "User-Agent":"climate-dashboard/1.0 official CFS reference probe"},
        stream=True,timeout=(20,60),allow_redirects=True,
    ) as response:
        response.raise_for_status()
        sig=response.raw.read(16)
        if not sig.startswith(b"GRIB"):
            raise ValueError(f"Not an original GRIB2 file at {url}: {sig!r}")
        if len(sig)<8 or sig[7]!=2:
            raise ValueError(f"Not a GRIB2 header at {url}")
        return {"status":response.status_code,"source":url,
                "grib_edition":2,
                "partial_response":response.status_code==206}


def main()->None:
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int,default=1991)
    p.add_argument("--month",type=int,default=1)
    args=p.parse_args()
    targets=[(args.year,args.month),(2011,3),(2011,4),(2020,12)]
    for year,month in targets:
        result=probe(source_url(year,month))
        print(f"Verified live NCEI original {year}-{month:02d}: {result}",flush=True)

if __name__=="__main__":
    main()
