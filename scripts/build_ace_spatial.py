#!/usr/bin/env python3
"""Gridded ACE anomalies, NOAA IBTrACS USA_WIND, historical archive.

Grid: 4° longitude x 4° latitude, Gaussian point kernel sigma=4°.
For a given year's last data date, its reference uses the same MM-DD cutoff
in all 30 years (1991–2020). The reference is not a full-year climatology
when the current year is incomplete. No spatial statistical significance
is claimed. Uses ACE approximation from six-hourly best track records.
"""
import csv
import io
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URL=("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-"
     "stewardship-ibtracs/v04r01/access/csv/ibtracs.since1980.list.v04r01.csv")
LATEST=URL.replace("ibtracs.since1980.list","ibtracs.last3years.list")
YEARS=range(1980,datetime.now(timezone.utc).year+1)
GRID_LONS=[-178+4*i for i in range(90)]
GRID_LATS=[-58+4*i for i in range(30)]
VALID={"NA","EP","WP","NI","SI","SP"}
SIGMA=4.0
OUT=Path("ace/spatial")

def observations():
    result={}
    for url in (URL,LATEST):
        try:
            with urlopen(Request(url,headers={"User-Agent":"ClimateDashboard/1.0"}),timeout=150) as response:
                reader=csv.DictReader(io.TextIOWrapper(response,encoding="utf-8-sig",newline=""))
                next(reader,None)
                for row in reader:
                    if row.get("BASIN") not in VALID or row.get("NATURE") not in ("TS","SS"):
                        continue
                    stamp=row.get("ISO_TIME","")
                    if len(stamp)<19 or stamp[11:16] not in ("00:00","06:00","12:00","18:00"):
                        continue
                    try:
                        wind=float(row.get("USA_WIND") or ""); lat=float(row.get("LAT") or "")
                        lon=float(row.get("LON") or "")
                        year=int(stamp[:4])
                    except (TypeError,ValueError):continue
                    if wind<34 or year not in YEARS or not math.isfinite(lat+lon+wind):continue
                    lon=((lon+180)%360)-180
                    result[(row.get("SID"),stamp)]=(year,stamp[5:10],lat,lon,wind*wind/10000)
        except Exception as exc:
            if url==URL: raise
            print("Rolling IBTrACS feed unavailable:",exc,file=sys.stderr)
    return list(result.values())

def build():
    import numpy as np
    from scipy.ndimage import gaussian_filter
    OUT.mkdir(parents=True,exist_ok=True)
    obs=observations()
    latest=max((x[1] for x in obs if x[0]==datetime.now(timezone.utc).year),default=None)
    last_current=max((date(x[0],int(x[1][:2]),int(x[1][3:])) for x in obs
                      if x[0]==datetime.now(timezone.utc).year),default=None)
    # Bucket each observation into its nearest 4° grid cell.
    daily=defaultdict(list)
    for year,mmdd,lat,lon,ace in obs:
        if not -60<=lat<62:continue
        yi=int(round((lat-GRID_LATS[0])/4))
        xi=int(round((lon-GRID_LONS[0])/4))%90
        if 0<=yi<len(GRID_LATS):daily[year].append((mmdd,yi,xi,ace))
    cutoff=last_current.strftime("%m-%d") if last_current else None
    all_years=sorted(year for year in YEARS if year<=datetime.now(timezone.utc).year-1 or
                     (year==datetime.now(timezone.utc).year and cutoff))
    # Same spatial spreading everywhere; longitude wraps at dateline.
    def grid(year,end):
        counts=np.zeros((len(GRID_LATS),len(GRID_LONS)),dtype=np.float64)
        for mmdd,yi,xi,val in daily.get(year,[]):
            if mmdd<=end:counts[yi,xi]+=val
        # smooth across longitudes, but no wrap in latitude
        counts=gaussian_filter(counts,sigma=(1.0,1.0),mode=("constant","wrap"))
        return counts
    complete={year:grid(year,"12-31") for year in all_years if year!=datetime.now(timezone.utc).year}
    # 30-year baseline for full calendar years is shared and cached.
    full_base=np.stack([complete[y] for y in range(1991,2021)])
    full_mean=full_base.mean(0);full_sd=full_base.std(0,ddof=1)
    manifest={"ready":True,"years":[],"resolution_deg":4,"kernel_sigma_deg":4,
              "latitudes":GRID_LATS,"longitudes":GRID_LONS,
              "reference_period":[1991,2020],"last_current_date":str(last_current) if last_current else None,
              "units":"ACE (10^4 kn^2) smoothed per grid cell",
              "source":"NOAA IBTrACS USA_WIND, six-hourly, NATURE TS/SS, >=34 kt",
              "method":"Spatially smoothed ACE contribution, Gaussian sigma 4 degrees; no significance overlay",
              "generated_utc":datetime.now(timezone.utc).isoformat()}
    for year in all_years:
        partial=year==datetime.now(timezone.utc).year
        end=cutoff if partial else "12-31"
        field=grid(year,end) if partial else complete[year]
        if partial:
            subset=np.stack([grid(y,end) for y in range(1991,2021)])
            mean=subset.mean(0); sd=subset.std(0,ddof=1)
        else:mean=full_mean;sd=full_sd
        z=np.divide(field-mean,sd,out=np.full_like(field,np.nan),where=sd>0.005)
        # Mask cells with tiny baseline: low variance is unstable for Z.
        z=np.where(mean>=0.005,np.clip(z,-4,4),np.nan)
        payload={"year":year,"ready":True,"provisional":partial,"through":str(last_current) if partial else str(year)+"-12-31",
                 "z":[[None if not math.isfinite(v) else round(float(v),2) for v in row] for row in z]}
        (OUT/f"{year}.json").write_text(json.dumps(payload,separators=(",",":"))+"\n")
        manifest["years"].append(year)
        print("ACE map:",year,flush=True)
    (OUT/"index.json").write_text(json.dumps(manifest,separators=(",",":"))+"\n")

if __name__=="__main__":build()
