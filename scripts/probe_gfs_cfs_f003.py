#!/usr/bin/env python3
"""Read authentic CFSR/CFSv2 f003 2m GRIB messages and GFS 0.5deg f003.

Verify a *uniform* 3-hour lead across 1991, transition years and both
previously missing archival months before starting an expensive backfill.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import tempfile
import requests
import numpy as np
import eccodes as ec
from scripts.import_cfsr_cfsv2_1991_2020 import (source_url,alternate_source_urls,interpolate_europe)

SAMPLES=[
 (1991,1,False),(1992,7,True),
 (2011,3,False),(2011,4,False),
 (2018,9,True),(2020,12,False)
]
LIMIT=12*1024*1024

def historical_probe(year:int,month:int,alternate:bool)->None:
    url=(alternate_source_urls(year,month)[0] if alternate else source_url(year,month))
    print("HISTORICAL",year,month,"alternate",alternate,url,flush=True)
    with requests.get(url,headers={"Range":f"bytes=0-{LIMIT-1}","Accept-Encoding":"identity"},
                      timeout=(25,120),stream=True) as r:
        r.raise_for_status()
        assert r.status_code==206, "source must support safe byte ranges"
        with tempfile.TemporaryFile(mode="w+b") as f:
            total=0
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk);total+=len(chunk)
                if total>=LIMIT:break
            f.seek(0)
            found=[]
            while len(found)<2:
                try:gid=ec.codes_grib_new_from_file(f)
                except Exception:break  # truncated suffix after a complete message
                if gid is None:break
                try:
                    if (int(ec.codes_get(gid,"forecastTime"))==3
                        and ec.codes_get(gid,"typeOfLevel")=="heightAboveGround"
                        and int(ec.codes_get(gid,"level"))==2
                        and ec.codes_get(gid,"shortName")=="2t"):
                        ni,nj=(int(ec.codes_get(gid,k)) for k in ("Ni","Nj"))
                        grid=np.asarray(ec.codes_get_values(gid)).reshape(nj,ni)
                        lats=np.asarray(ec.codes_get_array(gid,"latitudes")).reshape(nj,ni)
                        lons=np.asarray(ec.codes_get_array(gid,"longitudes")).reshape(nj,ni)
                        europe=interpolate_europe(grid,lats,lons)
                        assert europe.shape==(76,140) and np.isfinite(europe).all()
                        found.append((int(ec.codes_get(gid,"dataTime")),
                                      int(ec.codes_get(gid,"validityTime")),
                                      float(europe.mean())))
                finally:ec.codes_release(gid)
            assert found and found[0][0]==0 and found[0][1]==300, (year,month,found)
            print("PASS historical f003 (initial UTC -> valid UTC, mean degC):",found,flush=True)

def gfs_probe()->None:
    # GFS 0.5-degree publishes f003, but not f001 (0.25-degree only).
    for shift in (1,2,0):
        day=(datetime.now(timezone.utc)-timedelta(days=shift)).strftime("%Y%m%d")
        base=(f"https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{day}/00/atmos/"
              "gfs.t00z.pgrb2.0p50.f003")
        try:
            response=requests.get(base+".idx",timeout=(20,40))
            response.raise_for_status()
            records=[x.split(":") for x in response.text.splitlines() if x.strip()]
            rows=[i for i,p in enumerate(records)
                  if len(p)>=6 and p[3]=="TMP" and p[4]=="2 m above ground"
                  and p[5].strip().lower()=="3 hour fcst"]
            assert len(rows)==1, f"Expected one 2m TMP 3 hour forecast in {base}.idx, {rows}"
            i=rows[0]
            assert i+1<len(records)
            first,last=int(records[i][1]),int(records[i+1][1])-1
            assert 10000<last-first<3000000
            with requests.get(base,headers={"Range":f"bytes={first}-{last}"},
                              timeout=(25,65),stream=True) as r:
                assert r.status_code==206
                r.raise_for_status()
                raw=r.content
            assert len(raw)==last-first+1 and raw.startswith(b"GRIB")
            with tempfile.TemporaryFile(mode="w+b") as f:
                f.write(raw);f.seek(0)
                gid=ec.codes_grib_new_from_file(f)
            try:
                assert gid is not None
                assert int(ec.codes_get(gid,"forecastTime"))==3
                assert ec.codes_get(gid,"shortName")=="2t"
                assert int(ec.codes_get(gid,"Ni"))==720
                assert int(ec.codes_get(gid,"Nj"))==361
                print("PASS live NOAA GFS 0.5 degree f003 2m TMP",base,
                      "raw_bytes",len(raw),"sha256",sha256(raw).hexdigest(),flush=True)
                return
            finally:
                if gid is not None:ec.codes_release(gid)
        except (AssertionError,requests.RequestException) as exc:
            print("GFS date unavailable:",day,str(exc)[:200],flush=True)
    raise RuntimeError("No live 0.5 degree GFS f003 2m file verified; do not start backfill")

if __name__=="__main__":
    for y,m,alt in SAMPLES:historical_probe(y,m,alt)
    gfs_probe()
