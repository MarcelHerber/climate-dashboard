#!/usr/bin/env python3
"""ERA5 synoptic analysis: genuine hourly data, not monthly-mean proxies.

Daily maps are the actual 12:00 UTC synoptic state. Monthly event-frequency
maps are computed only after all 24 hourly slots of every calendar day are
verified. No frequency maps are published from incomplete months.
A pilot at 0.5° limits CDS demand; resolution is explicit in metadata.
"""
from __future__ import annotations

import argparse
import calendar
import json
import time
from pathlib import Path
from datetime import date, timedelta

import numpy as np
import xarray as xr

from update_era5_europe import (
    MONTH_NAMES, cds_client, normalize_dataarray, render_field, robust_range
)

AREA=[80.0,-40.0,20.0,50.0]
GRID=[0.5,0.5]
HOURS=[f"{hour:02d}:00" for hour in range(24)]
REPO="MarcelHerber/climate-dashboard"
PL="reanalysis-era5-pressure-levels"
SL="reanalysis-era5-single-levels"
# (key, variable, pressure level, NetCDF variable aliases)
FIELDS={
    "vo500":("vorticity","500",("vo","vorticity")),
    "div300":("divergence","300",("d","divergence")),
    "pv300":("potential_vorticity","300",("pv","potential_vorticity")),
    "omega700":("vertical_velocity","700",("w","vertical_velocity")),
    "cape":("convective_available_potential_energy",None,("cape","convective_available_potential_energy")),
    "cin":("convective_inhibition",None,("cin","convective_inhibition")),
    "ivte":("vertical_integral_of_eastward_water_vapour_flux",None,("viwve","vertical_integral_of_eastward_water_vapour_flux")),
    "ivtn":("vertical_integral_of_northward_water_vapour_flux",None,("viwvn","vertical_integral_of_northward_water_vapour_flux")),
    "u250":("u_component_of_wind","250",("u","u_component_of_wind")),
    "v250":("v_component_of_wind","250",("v","v_component_of_wind")),
}
MAPS={
    "vo500":("Relative Vorticity 500 hPa","10⁻⁵ s⁻¹","RdBu_r",1e5),
    "div300":("Divergenz 300 hPa","10⁻⁵ s⁻¹","RdBu_r",1e5),
    "pv300":("Potenzielle Vorticity 300 hPa","PVU","Spectral_r",1e6),
    "omega700":("Vertikalbewegung 700 hPa","Pa/s","PuOr",1.0),
    "cape":("CAPE","J/kg","YlOrRd",1.0),
    "cin":("CIN","J/kg","PuBu",1.0),
    "ivt":("Integrierter Wasserdampftransport (IVT)","kg/(m·s)","YlOrRd",1.0),
    "jet250":("Windgeschwindigkeit 250 hPa","m/s","plasma",1.0),
}
THRESHOLDS={
    "cape1000":("cape",">=",1000.0,"CAPE ≥ 1000 J/kg"),
    "ivt500":("ivt",">=",500.0,"IVT ≥ 500 kg/(m·s)"),
    "jet40":("jet250",">=",40.0,"250-hPa-Wind ≥ 40 m/s"),
    "lift700":("omega700","<=",-0.2,"Omega 700 hPa ≤ −0,2 Pa/s"),
    "vo500_10":("vo500",">=",1e-4,"Vorticity 500 hPa ≥ 10 · 10⁻⁵ s⁻¹"),
}


def parse_day(value: str) -> date:
    d=date.fromisoformat(value)
    if d.year < 1940: raise ValueError(value)
    return d


def hourly(client, which: str, day: date, folder: Path):
    variable, level, aliases=FIELDS[which]
    path=folder/f"{day}-{which}.nc"
    request={
        "product_type":["reanalysis"],"variable":[variable],
        "year":[f"{day.year:04d}"],"month":[f"{day.month:02d}"],"day":[f"{day.day:02d}"],
        "time":HOURS,"data_format":"netcdf","download_format":"unarchived",
        "area":AREA,"grid":GRID,
    }
    if level:
        request["pressure_level"]=[level]
    for attempt in range(1,4):
        try:
            client.retrieve(PL if level else SL,request,str(path))
            if not path.exists() or path.stat().st_size<1024:
                raise RuntimeError(f"ERA5 file missing for {which}/{day}")
            with xr.open_dataset(path) as ds:
                lat,lon,times,values=normalize_dataarray(ds,aliases)
            slots=[np.datetime_as_string(t,unit="h") for t in times]
            expected=[f"{day.isoformat()}T{h[:2]}" for h in HOURS]
            if slots!=expected or values.shape!=(24,len(lat),len(lon)):
                raise RuntimeError(f"Hourly coverage incomplete for {which}/{day}: {slots[:4]}")
            finite_fraction=float(np.isfinite(values).mean())
            if which!="cin" and finite_fraction<.95:
                raise RuntimeError(f"Missing gridded ERA5 data {which}/{day}")
            # CIN may be masked/undefined where convection is absent; missing
            # samples must never be silently reinterpreted as zero inhibition.
            if which=="cin":
                print(f"CIN valid-grid fraction: {finite_fraction:.1%}",flush=True)
            return lat,lon,np.asarray(values,dtype="float32")
        except Exception:
            if attempt==3: raise
            print(f"Retry ERA5 hourly {which}/{day} ({attempt}/3)",flush=True)
            time.sleep(attempt*10)
        finally:
            path.unlink(missing_ok=True)


def valid_grid(lon,lat,lng,latitude):
    if not(np.allclose(lon,lng) and np.allclose(lat,latitude)):
        raise RuntimeError("ERA5 hourly grid differs between variables")


def build_day(day_str: str, folder: Path):
    day=parse_day(day_str)
    folder.mkdir(parents=True,exist_ok=True)
    client=cds_client()
    cubes={}
    lat=lon=None
    for which in FIELDS:
        la,lo,data=hourly(client,which,day,folder)
        if lat is None:
            lat,lon=la,lo
        else:
            valid_grid(lon,lat,lo,la)
        if which=="cin" and np.isfinite(data).mean()<0.05:
            print("CIN too sparsely defined for a representative map; omit, never fill NaN with zero",flush=True)
            continue
        cubes[which]=data
        print(f"ERA5 daily {day}: {which} 24/24 hourly samples",flush=True)
    cubes["ivt"]=np.hypot(cubes.pop("ivte"),cubes.pop("ivtn"))
    cubes["jet250"]=np.hypot(cubes.pop("u250"),cubes.pop("v250"))
    result={}
    for key,(label,unit,cmap,scale) in MAPS.items():
        if key not in cubes:
            continue
        field=cubes[key][12]*np.float32(scale)
        target=folder/f"{day}-{key}.png"
        lo,hi=robust_range(field)
        render_field(field,lat,lon,title=label,subtitle=f"{day} · 12:00 UTC · ERA5 0,5°",
                     unit=unit,filename=target,cmap=cmap,vmin=lo,vmax=hi)
        if target.stat().st_size<1000: raise RuntimeError(target)
        result[key]={
            "label":label,"unit":unit,"time":"12:00 UTC",
            "file":f"https://github.com/{REPO}/releases/download/era5-synoptic-{day.year}-v1/{target.name}",
        }
    counts={}
    for key,(source,op,value,label) in THRESHOLDS.items():
        raw=cubes[source]
        finite=np.isfinite(raw)
        hit=(raw>=value if op==">=" else raw<=value)&finite
        counts[key]=np.sum(hit,axis=0).astype("uint8")
        counts["valid_"+key]=np.sum(finite,axis=0).astype("uint8")
    countfile=folder/f"{day}-hourly-counts.npz"
    np.savez_compressed(countfile,lat=lat.astype("float32"),lon=lon.astype("float32"),
                        date=np.str_(day_str),samples=np.int16(24),**counts)
    with np.load(countfile,allow_pickle=False) as pack:
        if set(THRESHOLDS)-set(pack.files) or int(pack["samples"])!=24:
            raise RuntimeError("Hourly threshold counts incomplete")
    manifest={
        "ready":True,"date":day_str,"analysis_time":"12:00 UTC",
        "source":"ERA5 hourly reanalysis","resolution":"0.5°",
        "hourly_samples":24,"products":result,
        "cin_policy":"Missing CIN is retained as missing; omit image if valid-grid coverage is below 5%.",
        "event_count_policy":"Hourly exceedances and per-grid valid-hour denominators are stored separately.",
        "hourly_counts_file":f"{day_str}-hourly-counts.npz",
        "thresholds":{key:{"label":v[3],"operator":v[1],"value":v[2]}
                       for key,v in THRESHOLDS.items()},
    }
    (folder/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,
        indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(f"Verified daily synoptic maps and 24-hour event counts: {day_str}",flush=True)


def monthly_stats(month: str, directory: Path, output: Path):
    yy,mm=map(int,month.split("-"))
    days=calendar.monthrange(yy,mm)[1]
    counts={}
    valid_hours={}
    lat=lon=None
    for dd in range(1,days+1):
        date_str=f"{yy:04d}-{mm:02d}-{dd:02d}"
        path=directory/f"{date_str}-hourly-counts.npz"
        if not path.is_file():
            raise FileNotFoundError(f"Missing actual hourly data for {date_str}")
        with np.load(path,allow_pickle=False) as pack:
            if str(pack["date"])!=date_str or int(pack["samples"])!=24:
                raise ValueError(f"Incomplete hourly day {date_str}")
            if lat is None:
                lat=np.asarray(pack["lat"])
                lon=np.asarray(pack["lon"])
                counts={key:np.zeros((len(lat),len(lon)),dtype="float64") for key in THRESHOLDS}
                valid_hours={key:np.zeros((len(lat),len(lon)),dtype="float64") for key in THRESHOLDS}
            else:
                valid_grid(lon,lat,pack["lon"],pack["lat"])
            for key in THRESHOLDS:
                arr=np.asarray(pack[key])
                if np.any(arr>24):raise ValueError(f"Bad counts for {date_str}/{key}")
                nvalid=np.asarray(pack["valid_"+key])
                if np.any(nvalid>24) or np.any(arr>nvalid):
                    raise ValueError(f"Invalid valid-hour counters: {date_str}/{key}")
                counts[key]+=arr
                valid_hours[key]+=nvalid
    output.mkdir(parents=True,exist_ok=True)
    products={}
    denominator=days*24
    for key,total in counts.items():
        grid_valid=valid_hours[key]
        field=np.full(total.shape,np.nan,dtype="float64")
        np.divide(total*100.,grid_valid,out=field,
                  where=grid_valid>=np.ceil(denominator*.95))
        if not np.isfinite(field).any():
            raise RuntimeError(f"No reliable grid cells for monthly frequency: {month}/{key}")
        target=output/f"{month}-{key}.png"
        render_field(field,lat,lon,title=THRESHOLDS[key][3],
                     subtitle=f"{MONTH_NAMES[mm]} {yy} · Anteil aller {denominator} Stunden",
                     unit="% aller Stunden",filename=target,cmap="YlOrRd",
                     vmin=0,vmax=max(10,float(np.percentile(field,99))))
        products[key]={"label":THRESHOLDS[key][3],"unit":"%",
            "file":f"https://github.com/{REPO}/releases/download/era5-synoptic-events-{yy}-v1/{target.name}",
            "denominator_hours":denominator}
    manifest={"ready":True,"month":month,"hours":denominator,
              "sample_coverage":"100% of expected hourly timestamps",
              "min_grid_hour_coverage":0.95,
              "grid":"0.5°","products":products}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,
        indent=2,allow_nan=False)+"\n",encoding="utf-8")


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("day")
    p.add_argument("--date",required=True)
    p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("month")
    p.add_argument("--month",required=True)
    p.add_argument("--counts",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.command=="day":build_day(args.date,args.output)
    else:monthly_stats(args.month,args.counts,args.output)


if __name__=="__main__":
    main()
