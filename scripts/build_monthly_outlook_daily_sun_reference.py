#!/usr/bin/env python3
"""Reconstruct Germany's daily 1991–2020 sunshine normals from DWD KL SDK.

This is NOT an official DWD daily sunshine grid and NOT a DUETT climatology.
Compute station calendar-day means from actual 1991–2020 DWD historical
daily sunshine readings (SDK), interpolate to a uniform ~6km German grid by
inverse distance weighting, then calibrate each region's monthly sum to the
official DWD 1-km 1991–2020 sunshine monthly normals. This preserves the
observed seasonal *within-month* pattern without inventing daily values by
spreading the monthly normal uniformly.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import math
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from pyproj import Transformer

from build_hyras_tmean_regions import EXPECTED_STATES, load_states
from build_monthly_outlook_climatology import SUN_FILE, SUN_URL, ascii_grid, download, sun_masks

HIST="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/historical/"
UA="climate-dashboard-sunshine-day-climate/1.0 (DWD CDC)"
REGIONS=("Deutschland", *EXPECTED_STATES)
START=1991
END=2020
STRIDE=6
MIN_YEARS=18
MIN_LEAP_YEARS=5
MIN_AREA_COVERAGE=.90
MAX_STATION_DISTANCE_M=160000
STATION_NEIGHBORS=8
INDEX_RE=re.compile(r'href="(tageswerte_KL_(\d{5})_(\d{8})_(\d{8})_hist\.zip)"')


def get(url: str, timeout: int=100, tries: int=3) -> bytes:
    exc=None
    for attempt in range(tries):
        try:
            r=requests.get(url,timeout=timeout,headers={"User-Agent":UA})
            r.raise_for_status()
            return r.content
        except (requests.RequestException,OSError) as error:
            exc=error
            if attempt+1<tries: time.sleep(attempt+1)
    raise RuntimeError(f"DWD station request failed: {url}: {exc}")


def day_template():
    return [(m, d) for m in range(1,13)
            for d in range(1,calendar.monthrange(2000,m)[1]+1)]


def stations_metadata(txt: str) -> dict[str,tuple[float,float]]:
    found={}
    pattern=re.compile(r'^\s*(\d{5})\s+(\d{8})\s+(\d{8})\s+-?\d+\s+([\d.]+)\s+([\d.]+)')
    for line in txt.splitlines():
        match=pattern.match(line)
        if not match:continue
        station,start,end,lat,lon=match.groups()
        if start>"19950101" or end<"20161231":continue
        lat,lon=float(lat),float(lon)
        if 46<lat<56 and 5<lon<16:
            found[station]=(lat,lon)
    return found


def available_station_zips(listing: str, positions: dict[str,tuple[float,float]]) -> dict[str,str]:
    chosen={}
    for filename,station,start,end in INDEX_RE.findall(listing):
        if station not in positions or start>"19950101" or end<"20161231":continue
        if station not in chosen or filename>chosen[station]:
            chosen[station]=filename
    if len(chosen)<60:
        raise RuntimeError(f"Too few long-duration historical DWD climate station files: {len(chosen)}")
    return chosen


def parse_sdk_zip(blob: bytes) -> dict:
    """Mean sunshine hours per month-day; reject invalid and sparse records."""
    years={}
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        name=next((n for n in archive.namelist()
                   if n.lower().endswith(".txt") and "produkt_klima_tag" in n.lower()),None)
        if not name:
            raise ValueError("No produkt_klima_tag in DWD KL archive")
        text=io.TextIOWrapper(archive.open(name),encoding="latin-1")
        for raw_row in csv.DictReader(text,delimiter=";"):
            # DWD KL historical files often contain spaces in column headers
            # (e.g. " SDK" instead of "SDK"); normalize before selecting fields.
            row={str(k).strip():v for k,v in raw_row.items() if k is not None}
            stamp=str(row.get("MESS_DATUM","")).strip()
            if len(stamp)!=8 or not stamp.isdigit():continue
            year=int(stamp[:4])
            if year<START or year>END:continue
            raw=str(row.get("SDK","")).strip().replace(",",".")
            try:hours=float(raw)
            except ValueError:continue
            if not math.isfinite(hours) or hours<0 or hours>24:continue
            md=stamp[4:]
            years.setdefault(md,{})[year]=hours
    means=[];counts=[]
    for month,day in day_template():
        md=f"{month:02d}{day:02d}"
        readings=list(years.get(md,{}).values())
        count=len(readings)
        minimum=MIN_LEAP_YEARS if (month,day)==(2,29) else MIN_YEARS
        means.append(round(sum(readings)/count,5) if count>=minimum else None)
        counts.append(count)
    return {"daily_h":means,"year_samples":counts}


def station_normals(chosen:dict[str,str],cache:Path,workers:int=10) -> tuple[dict[str,dict],dict]:
    cache.mkdir(parents=True,exist_ok=True)
    good={}
    failed={}
    def one(station,filename):
        target=cache/(station+".json")
        if target.is_file():
            try:
                obj=json.loads(target.read_text(encoding="utf-8"))
                if obj.get("source_file")==filename and len(obj.get("daily_h",[]))==366:
                    return station,obj
            except (ValueError,OSError):pass
        record=parse_sdk_zip(get(HIST+filename))
        record["source_file"]=filename
        target.write_text(json.dumps(record,separators=(",",":")),encoding="utf-8")
        return station,record
    with ThreadPoolExecutor(max_workers=max(1,min(workers,16))) as pool:
        tasks={pool.submit(one,station,filename):station
               for station,filename in chosen.items()}
        for i,future in enumerate(as_completed(tasks),start=1):
            station=tasks[future]
            try:
                _,row=future.result()
                if sum(v is not None for v in row["daily_h"])>=330:
                    good[station]=row
                else:
                    failed[station]="fewer than 330 day-of-year climate means"
            except Exception as exc:
                failed[station]=str(exc)
            if i%50==0:
                print("DWD KL station downloads",i,"/",len(tasks),"accepted",len(good),flush=True)
    if len(good)<60:
        raise RuntimeError(f"Historical SDK coverage insufficient: {len(good)} stations with valid calendar-year normals")
    return good,failed


def sun_region_interpolation(stations: dict, positions: dict, x: np.ndarray, y: np.ndarray,
                             full_masks:dict[str,np.ndarray]) -> tuple[dict[str,list[float]],dict]:
    """IDW on a 6-km lattice; require two nearby valid reference stations."""
    names=sorted(stations)
    transformer=Transformer.from_crs(4326,31467,always_xy=True)
    xx,yy=transformer.transform(
        [positions[s][1] for s in names],
        [positions[s][0] for s in names])
    station_points=np.column_stack([xx,yy])
    xxg,yyg=np.meshgrid(x[::STRIDE],y[::STRIDE])
    lattice=np.column_stack([xxg.ravel(),yyg.ravel()])
    region_masks={name:mask[::STRIDE,::STRIDE].ravel() for name,mask in full_masks.items()}
    if any(region_masks[name].sum()<4 for name in REGIONS):
        raise ValueError("At least one region has too few 6-km sunshine grid cells")

    closest=[]
    for start in range(0,len(lattice),600):
        delta=lattice[start:start+600,None,:]-station_points[None,:,:]
        d2=np.square(delta).sum(axis=2)
        k=min(STATION_NEIGHBORS,len(names))
        idx=np.argpartition(d2,k-1,axis=1)[:,:k]
        dist=np.take_along_axis(d2,idx,axis=1)
        order=np.argsort(dist,axis=1)
        closest.append((np.take_along_axis(idx,order,axis=1),
                        np.take_along_axis(dist,order,axis=1)))
    nearest=np.concatenate([z[0] for z in closest])
    d2=np.concatenate([z[1] for z in closest])
    weights=np.where(d2<MAX_STATION_DISTANCE_M**2,1/np.maximum(d2,1e6),0.0)
    station_means=np.array([stations[name]["daily_h"] for name in names],dtype=float)
    series={name:[] for name in REGIONS}
    coverage={name:[] for name in REGIONS}
    for day in range(366):
        selected=station_means[nearest,day]
        good=np.isfinite(selected)
        usable=weights*good
        sums=usable.sum(axis=1)
        counts=(usable>0).sum(axis=1)
        interpolated=np.full(len(lattice),np.nan,dtype=float)
        valid=(sums>0)&(counts>=2)
        interpolated[valid]=(np.where(good,selected,0.0)*usable).sum(axis=1)[valid]/sums[valid]
        for region in REGIONS:
            mask=region_masks[region]
            values=interpolated[mask]
            coverage_day=float(np.isfinite(values).sum()/len(values))
            if coverage_day<MIN_AREA_COVERAGE:
                raise ValueError(f"Historical DWD SDK reference lacks grid coverage: {region}, "
                                 f"day {day+1}, {coverage_day:.1%}")
            series[region].append(float(np.nanmean(values)))
            coverage[region].append(coverage_day)
    return series,{"stations":len(names),
                   "grid_km":STRIDE,
                   "coverage_by_region":{r:round(min(coverage[r]),3) for r in REGIONS}}


def build_payload(series:dict[str,list[float]],monthly:dict,quality:dict) -> dict:
    if monthly.get("reference_period")!="1991-2020" or set(series)!=set(REGIONS):
        raise ValueError("Region normals or official DWD 1991–2020 monthly baseline incomplete")
    dates=day_template()
    if any(len(v)!=366 for v in series.values()):
        raise ValueError("Expected 366 sunshine climatological days per region")
    months={}
    for m in range(1,13):
        key=f"{m:02d}"
        indexes=[i for i,(month,_) in enumerate(dates) if month==m]
        day_names=[f"{m:02d}-{dates[i][1]:02d}" for i in indexes]
        regions={}
        for region in REGIONS:
            raw=np.array([series[region][i] for i in indexes],dtype=float)
            if not np.all(np.isfinite(raw)) or np.any((raw<0)|(raw>24)):
                raise ValueError(f"Invalid sunshine reference day in {region}/{key}")
            # 1991–2020 has eight leap years. February mean calendar-month
            # sum includes 8/30 of a Feb-29 mean, not an entire extra day.
            weighted=float(raw.sum()-(raw[-1]*22/30 if m==2 else 0))
            official=monthly["months"][key]["sunshine"][region]["month_total"]
            if weighted<=0 or not isinstance(official,(int,float)) or official<=0:
                raise ValueError(f"Invalid station or DWD monthly sunshine normal in {region}/{key}")
            scale=float(official/weighted)
            if not (0.60<=scale<=1.40):
                raise ValueError(f"Station daily sunshine must be scaled {scale:.1%} "
                                 f"to match official {region}/{key} monthly climate; "
                                 "reference too uncertain to publish")
            corrected=raw*scale
            if np.any(corrected>24.01):
                raise ValueError(f"Sunshine calibration produces unphysical daily hours: {region}/{key}")
            regions[region]={
                "daily_h":[round(float(v),4) for v in corrected],
                "running_h":[round(float(v),3) for v in np.cumsum(corrected)],
                "official_month_total_h":float(official),
                "raw_station_month_total_h":round(weighted,3),
                "monthly_shape_adjustment_factor":round(scale,5),
            }
        months[key]={"dates":day_names,"regions":regions}
    return {
        "schema_version":1,
        "product":"state_monthly_daily_sunshine_climatology_station_reconstruction",
        "parameter":"sunshine",
        "unit":"h",
        "reference_period":"1991-2020",
        "generated_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "regions_order":list(REGIONS),
        "months":months,
        "daily_climatology_available":True,
        "quality":quality,
        "source":"DWD CDC historical daily KL station SDK 1991–2020, plus official DWD station-interpolated monthly 1-km sunshine normals",
        "method":"DWD station SDK day-of-calendar historical means (min 18 years; 5 for Feb 29), inverse-square distance station interpolation on ~6-km grid, area mean, month-wise multiplicative adjustment to official 1991–2020 DWD 1-km monthly normal. This is a reconstruction, NOT an official daily grid.",
        "duett_note":"Current DUETT blends satellite and station observations. Historical SDK station interpolation is not a DUETT-equivalent data source; some method bias may remain.",
        "leap_day_note":"02-29 is sampled from eight 1991–2020 leap years and included in the cumulative curve only in leap-year Februaries.",
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--monthly",type=Path,required=True)
    p.add_argument("--work",type=Path,default=Path("/tmp/monthly-daily-sun-work"))
    p.add_argument("--cache",type=Path,default=Path("/tmp/monthly-daily-sun-cache"))
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--workers",type=int,default=10)
    args=p.parse_args()
    args.work.mkdir(parents=True,exist_ok=True)
    monthly=json.loads(args.monthly.read_text(encoding="utf-8"))
    listing=get(HIST,timeout=120).decode("latin-1")
    positions=stations_metadata(get(HIST+"KL_Tageswerte_Beschreibung_Stationen.txt").decode("latin-1"))
    station_files=available_station_zips(listing,positions)
    print("Historical DWD KL stations eligible:",len(station_files),flush=True)
    stations,errors=station_normals(station_files,args.cache,args.workers)
    print("Stations with sunshine >=330 calendar-day normals:",len(stations),"excluded:",len(errors),flush=True)

    sunfile=SUN_FILE.format(month=11)
    target=download(SUN_URL+sunfile,args.work/sunfile)
    x,y,_=ascii_grid(target)
    features=load_states(args.work)
    masks=sun_masks(features,x,y)
    series,quality=sun_region_interpolation(stations,positions,x,y,masks)
    quality.update({"station_candidates":len(station_files),"station_excluded":len(errors),
                    "station_day_min_years":MIN_YEARS,"leap_day_min_years":MIN_LEAP_YEARS,
                    "max_interpolation_distance_km":MAX_STATION_DISTANCE_M/1000})
    result=build_payload(series,monthly,quality)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print("Station sunshine day-climate ready: 12 months, 17 regions ·",
          "November DE",result["months"]["11"]["regions"]["Deutschland"]["running_h"][-1],"hours",flush=True)


if __name__=="__main__":
    main()
