#!/usr/bin/env python3
"""Optional observed sunshine estimate for current-month provisional Gebietsmittel.

DWD daily KL SDK station readings are interpolated onto an area-uniform 12 km
grid using the three nearest stations. This is an approximation, not an official
DWD grid-product regional mean; never mix it with finalized DWD monthly values.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import numpy as np
import requests
import xarray as xr
from pyproj import Transformer

from build_hyras_tmean_regions import build_masks, load_states
from update_hyras_maps import grid_xy, pick_precip_var, time_dim

BASE="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent/"
HEADERS={"User-Agent":"ClimateDashboard-Monthly-Provisional/1.0"}


def get(url: str, timeout: int=45) -> bytes:
    r=requests.get(url,timeout=timeout,headers=HEADERS)
    r.raise_for_status()
    return r.content


def metadata(text: str, start_date: str) -> dict[str,tuple[float,float]]:
    stations={}
    pat=re.compile(r"^\s*(\d{5})\s+\d{8}\s+(\d{8})\s+-?\d+\s+([\d.]+)\s+([\d.]+)")
    for line in text.splitlines():
        match=pat.match(line)
        if not match or match.group(2)<start_date.replace("-",""):
            continue
        lat,lon=map(float,(match.group(3),match.group(4)))
        if 46<lat<56 and 5<lon<16:
            stations[match.group(1)]=(lat,lon)
    return stations


def parse_zip(blob: bytes, dates: set[str]) -> dict[str,float]:
    result={}
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        member=next((n for n in archive.namelist() if n.lower().endswith(".txt") and
                     "produkt_klima_tag" in n.lower()),None)
        if not member:
            return result
        text=archive.read(member).decode("latin-1")
        reader=csv.DictReader(io.StringIO(text),delimiter=";")
        for row in reader:
            stamp=(row.get("MESS_DATUM") or "").strip()
            if stamp not in dates:
                continue
            raw=(row.get("SDK") or "").strip().replace(",",".")
            try:
                hours=float(raw)
            except ValueError:
                continue
            if 0<=hours<=24:
                result[stamp]=hours
    return result


def estimate(doc: dict, root: Path, work: Path, workers: int=12) -> dict:
    year,month=map(int,doc["month"].split("-"))
    through=doc["data_through"]
    dates=[f"{year:04d}{month:02d}{d:02d}" for d in range(1,int(through[-2:])+1)]
    desired=set(dates)
    listing=get(BASE).decode("latin-1")
    ids=set(re.findall(r"tageswerte_KL_(\d{5})_akt\.zip",listing))
    positions=metadata(get(BASE+"KL_Tageswerte_Beschreibung_Stationen.txt").decode("latin-1"),f"{year}-{month:02d}-01")
    ids=sorted(ids.intersection(positions))
    if len(ids)<80:
        raise RuntimeError("Insufficient current DWD climate stations for sunshine interpolation")
    measurements={}
    def fetch_one(station):
        return station,parse_zip(get(BASE+f"tageswerte_KL_{station}_akt.zip"),desired)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(fetch_one,s) for s in ids]
        for future in as_completed(futures):
            try:
                station,values=future.result()
                if values:
                    measurements[station]=values
            except Exception:
                continue
    if len(measurements)<50:
        raise RuntimeError("Too few DWD KL stations with actual SDK sunshine readings")

    source_idx=json.loads((root/"hyras_index.json").read_text(encoding="utf-8"))
    source_nc=work/source_idx["daily_source_file"]
    with xr.open_dataset(source_nc) as dataset:
        field=pick_precip_var(dataset)
        x,y=grid_xy(field)
    masks=build_masks(load_states(work),x,y)
    stride=12
    xx,yy=np.meshgrid(x[::stride],y[::stride])
    grid_coords=np.column_stack([xx.ravel(),yy.ravel()])
    spatial_masks={name:mask[::stride,::stride].ravel() for name,mask in masks.items()}
    from build_monthly_provisional import COMBINED
    spatial_masks.update({name:np.logical_or.reduce([spatial_masks[p] for p in parts])
                          for name,parts in COMBINED.items()})
    transformer=Transformer.from_crs(4326,3035,always_xy=True)
    valid_days={}
    for day in dates:
        selected=[(stations,values[day]) for stations,values in measurements.items() if day in values]
        if len(selected)<45:
            continue
        xstations,ystations=transformer.transform(
            [positions[s][1] for s,_ in selected],
            [positions[s][0] for s,_ in selected])
        station_coords=np.column_stack([xstations,ystations])
        readings=np.asarray([value for _,value in selected],dtype=float)
        estimated=np.full(len(grid_coords),np.nan,dtype=float)
        for pos in range(0,len(grid_coords),800):
            cells=grid_coords[pos:pos+800]
            dist2=np.square(cells[:,None,:]-station_coords[None,:,:]).sum(axis=2)
            nearest=np.argpartition(dist2,2,axis=1)[:,:3]
            d=np.take_along_axis(dist2,nearest,axis=1)
            w=1/np.maximum(d,1000**2)
            values=readings[nearest]
            near=np.sqrt(np.min(d,axis=1))<=60000
            estimated[pos:pos+800]=np.where(near,(values*w).sum(axis=1)/w.sum(axis=1),np.nan)
        valid_days[day]=estimated

    if len(valid_days)!=len(dates):
        raise RuntimeError("Daily SDK observations incomplete for current HYRAS cutoff")

    coverage_by_area={}
    for name,area in spatial_masks.items():
        cells=int(area.sum())
        if cells<4:
            continue
        total=0.0
        okay=True
        for day in dates:
            sample=valid_days[day][area]
            finite=np.isfinite(sample)
            if finite.sum()/cells<.9:
                okay=False
                break
            total+=float(sample[finite].mean())
        if okay:
            doc["areas"].setdefault(name,{})["sun"]=round(total,2)
            coverage_by_area[name]=cells
    doc["source"]["sun"]="DWD KL daily sunshine SDK, spatial 3-station IDW estimate (12 km)"
    doc["sun_method"]="Area-weighted station interpolation (12 km; three-nearest IDW); provisional, NOT official DWD regional mean."
    doc["sun_station_count"]=len(measurements)
    doc["sun_area_count"]=len(coverage_by_area)
    return doc


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-root",type=Path,default=Path("/tmp/hyras-data"))
    parser.add_argument("--work",type=Path,default=Path("/tmp/hyras-work"))
    args=parser.parse_args()
    target=args.data_root/"monthly_current_provisional.json"
    doc=json.loads(target.read_text(encoding="utf-8"))
    try:
        doc=estimate(doc,args.data_root,args.work)
        print(f"Vorläufige Sonnen-Gebietsmittel: {doc['sun_area_count']} Gebiete, {doc['sun_station_count']} DWD-Stationen")
    except Exception as exc:
        print(f"Hinweis: Stationssonnenschein nicht bereit; Temperatur und Niederschlag bleiben gültig. {exc}")
    target.write_text(json.dumps(doc,ensure_ascii=False,separators=(",",":")),encoding="utf-8")


if __name__=="__main__":
    main()
