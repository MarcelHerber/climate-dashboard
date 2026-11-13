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

def probe(year, month):
    """True=verified, False=definitely unavailable/invalid, None=transient network issue.

    Source availability is checked again by the strict full-year importer: never
    interpret a timeout as missing data or silently fabricate measurements.
    """
    import time
    url=gdex_url(year,month)
    for attempt in range(3):
        try:
            with requests.get(url,headers={"Range":"bytes=0-15",
                "Accept-Encoding":"identity","User-Agent":"ClimateDashboard/1.0 source-verification"},
                timeout=(15,50),stream=True) as response:
                if response.status_code in (404,410):
                    print(f"{year}-{month:02d}: confirmed missing HTTP {response.status_code} {url}",flush=True)
                    return False
                if response.status_code in (429,500,502,503,504):
                    print(f"{year}-{month:02d}: temporary HTTP {response.status_code} attempt={attempt+1}",flush=True)
                    if attempt<2:
                        time.sleep((attempt+1)*3)
                        continue
                    return None
                response.raise_for_status()
                head=response.raw.read(16)
                good=(head.startswith(b"GRIB") and len(head)>=8 and head[7]==2)
                print(f"{year}-{month:02d}: status={response.status_code} "
                      f"GRIB2={good} range={response.headers.get('Content-Range','')} url={url}",flush=True)
                return bool(good)
        except requests.RequestException as exc:
            print(f"{year}-{month:02d}: transient network issue on attempt {attempt+1}: "
                  f"{str(exc)[:140]}",flush=True)
            if attempt<2:
                time.sleep((attempt+1)*3)
                continue
            return None
    return None

if __name__=="__main__":
    results={f"{y:04d}-{m:02d}":probe(y,m) for y,m in CASES}
    confirmed=sum(x is True for x in results.values())
    uncertain=sum(x is None for x in results.values())
    print("Confirmed official high-resolution GRIB2 origins:",confirmed,
          "of",len(results),"; transient network failures:",uncertain,flush=True)
    # A network timeout must never block otherwise valid archival imports.
    # Every annual importer independently downloads/decodes ALL originals.
    if any(x is False for x in results.values()):
        raise SystemExit("A source returned a definitive 404 or invalid GRIB2; block historical import")
    if uncertain:
        print("WARNING: Archive connection timed out for some sources; "
              "allow strict annual import to verify complete GRIB2 before accepting data",flush=True)
