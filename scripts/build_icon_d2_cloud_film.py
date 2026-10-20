#!/usr/bin/env python3
"""ICON-D2 Germany Wolkenfilm: real DWD GRIB2 cloud fractions, geographically regridded.

DWD's "regular-lat-lon" ICON-D2 product is in ROTATED coordinates. ecCodes
latitudes/longitudes are true geodetic positions; a single nearest-neighbour
lookup for the whole run is calculated against those true coordinates.
Avoid pretending the native 0.02-degree rotated grid is geographic.
"""
from __future__ import annotations
import argparse
import bz2
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import tempfile
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

import eccodes
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

LOG=logging.getLogger("icon-d2-germany-clouds")
ROOT="https://opendata.dwd.de/weather/nwp/icon-d2/grib"
PREFIX="icon-d2_germany_regular-lat-lon_single-level"
PARAMS=("CLCL","CLCM","CLCH","CLCT")
HOURS=tuple(range(0,37))
# Germany with a small geographic margin. 0.025° in ordinary coordinates;
# original ICON-D2 mesh is about 2.1km on a ROTATED 0.02° grid.
# Native cloud forecast output is hourly; no synthetic time steps.
WEST,EAST,SOUTH,NORTH,STEP=5.0,16.5,47.0,56.0,.025
WIDTH=round((EAST-WEST)/STEP)+1
HEIGHT=round((NORTH-SOUTH)/STEP)+1
HEADERS={"User-Agent":"ClimateDashboardPrivatesWolkenlabor-ICON-D2/1.0"}

def url_for(run,kind,hour):
    basename=f"{PREFIX}_{run:%Y%m%d%H}_{hour:03d}_2d_{kind.lower()}.grib2.bz2"
    return f"{ROOT}/{run.hour:02d}/{kind.lower()}/{basename}"

def retrieve(url,retries=3):
    for attempt in range(retries):
        try:
            with urlopen(Request(url,headers=HEADERS),timeout=75) as response:
                data=response.read()
            if len(data)<9000:
                raise ValueError(f"Keine vollständige DWD GRIB2-Datei ({len(data)} bytes)")
            return data
        except (HTTPError,URLError,TimeoutError,ValueError) as exc:
            if attempt==retries-1 or isinstance(exc,HTTPError) and exc.code in (400,403,404):
                raise RuntimeError(f"ICON-D2-Daten nicht lesbar: {url}: {exc}") from exc
            time.sleep(2**attempt * 3)
    raise AssertionError("unreachable")

def choose_cycle(now):
    aligned=now.replace(minute=0,second=0,microsecond=0)
    aligned-=timedelta(hours=aligned.hour%3)
    for lag in range(1,9):
        run=aligned-timedelta(hours=lag*3)
        try:
            for kind in PARAMS:
                retrieve(url_for(run,kind,HOURS[-1]),retries=1)
            LOG.info("Vollständiger ICON-D2-Lauf %s",run.isoformat())
            return run
        except RuntimeError:
            pass
    raise RuntimeError("Kein vollständiger ICON-D2-Lauf bis +36 h gefunden")

def decode(payload):
    with tempfile.TemporaryFile() as file:
        file.write(bz2.decompress(payload));file.seek(0)
        grib=eccodes.codes_grib_new_from_file(file)
        if grib is None:
            raise ValueError("GRIB2-Datei enthält kein auswertbares Feld")
        try:
            lat=np.asarray(eccodes.codes_get_array(grib,"latitudes"),dtype=np.float32)
            lon=np.asarray(eccodes.codes_get_array(grib,"longitudes"),dtype=np.float32)
            values=np.asarray(eccodes.codes_get_values(grib),dtype=np.float32)
            units=str(eccodes.codes_get(grib,"units"))
            grid=str(eccodes.codes_get(grib,"gridType"))
            if values.size<100000 or not (values.size==lat.size==lon.size):
                raise ValueError("ICON-D2-Gitter unerwartet klein/ungültig")
            if units not in ("%", "percent"):
                raise ValueError(f"CLCx ohne erwartete %-Einheit: {units}")
            return lat,lon,values,grid
        finally:
            eccodes.codes_release(grib)

def build_mapping(latitude,longitude):
    longitude=np.where(longitude>180,longitude-360,longitude)
    regular_lat=np.linspace(NORTH,SOUTH,HEIGHT)
    regular_lon=np.linspace(WEST,EAST,WIDTH)
    lon,lat=np.meshgrid(regular_lon,regular_lat)
    original=np.column_stack([latitude.ravel(),longitude.ravel()])
    targets=np.column_stack([lat.ravel(),lon.ravel()])
    # Geographic positions supplied by ecCodes (not the rotated coordinates).
    # Nearest sample distance >0.038° is outside the original model domain.
    tree=cKDTree(original)
    dist,idx=tree.query(targets,k=1,workers=2)
    valid=np.isfinite(dist)&(dist<.038)
    coverage=float(valid.mean())
    LOG.info("Georeferenzierter Deutschland-Ausschnitt: %.1f%% Deckung; %sx%s Pixel",coverage*100,WIDTH,HEIGHT)
    if coverage<.985:
        raise ValueError(f"Deutschland-Ausschnitt ist nicht ausreichend im ICON-D2-Gebiet: {coverage:.1%}")
    return idx,valid

def sample(values,mapping):
    idx,valid=mapping
    arr=np.full(WIDTH*HEIGHT,255,np.uint8)
    sampled=values[idx]
    good=valid & np.isfinite(sampled) & (sampled>=0) & (sampled<=100.0001)
    if np.count_nonzero(good)<int(valid.sum()*.98):
        raise ValueError("Zu viele ungültige CLCH/CLCM/CLCL Werte; kein Ersatz durch synthetische Daten")
    arr[good]=np.round(np.clip(sampled[good],0,100)*2.54).astype(np.uint8)
    return arr.reshape((HEIGHT,WIDTH))

def render(args):
    run,kind,hour,out,mapping,reference=args
    raw=retrieve(url_for(run,kind,hour))
    lat,lon,values,grid=decode(raw)
    check=reference
    for k in (0,101,1001,20001):
        if k>=lat.size:
            continue
        if abs(float(lat[k])-float(check[0][k]))>.0001 or abs(float(lon[k])-float(check[1][k]))>.0001:
            raise ValueError("ICON-D2-GRIB-Gitter zwischen Feldern inkonsistent")
    image=Image.fromarray(sample(values,mapping),mode="L")
    folder=out/"frames"/run.strftime("%Y%m%d%H")
    folder.mkdir(parents=True,exist_ok=True)
    name=f"{kind.lower()}_{hour:03d}.png"
    image.save(folder/name,optimize=True)
    return hour,kind.lower(),f"frames/{run:%Y%m%d%H}/{name}"

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--max-workers",type=int,default=4)
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    out=args.out;out.mkdir(parents=True,exist_ok=True)
    run=choose_cycle(datetime.now(timezone.utc))
    old=out/"current.json"
    if old.is_file():
        try:
            saved=json.loads(old.read_text(encoding="utf-8"))
            if saved.get("model")=="DWD ICON-D2" and saved.get("cycle")==f"{run:%Y%m%d%H}" and [frame.get("hour") for frame in saved.get("frames",[])]==list(HOURS):
                LOG.info("ICON-D2-Wolkenfilm %s bereits vollständig veröffentlicht.",run)
                return
        except (OSError,ValueError):
            pass
    # Decode first genuine DWD field to establish the actual rotated-grid mapping.
    start_kind=PARAMS[0]
    raw=retrieve(url_for(run,start_kind,HOURS[0]))
    lat,lon,values,grid=decode(raw)
    if grid not in ("rotated_ll","regular_ll"):
        raise ValueError(f"Unbekanntes ICON-D2-Gitter: {grid}")
    mapping=build_mapping(lat,lon)
    reference=(lat,lon)
    records={(HOURS[0],start_kind.lower()):""}
    directory=out/"frames"/f"{run:%Y%m%d%H}"
    directory.mkdir(parents=True,exist_ok=True)
    first=f"frames/{run:%Y%m%d%H}/{start_kind.lower()}_{HOURS[0]:03d}.png"
    Image.fromarray(sample(values,mapping),mode="L").save(out/first,optimize=True)
    records[(HOURS[0],start_kind.lower())]=first
    tasks=[(run,k,h,out,mapping,reference) for h in HOURS for k in PARAMS if (h,k)!=(HOURS[0],start_kind)]
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures={pool.submit(render,task):task for task in tasks}
        for future in as_completed(futures):
            hour,kind,path=future.result()
            records[(hour,kind)]=path
            LOG.info("ICON-D2 Wolkenbild +%02dh %s",hour,kind)
    frames=[]
    for hour in HOURS:
        frame={"hour":hour,"valid_utc":(run+timedelta(hours=hour)).isoformat().replace("+00:00","Z"),
               "layers":{kind.lower():records[hour,kind.lower()] for kind in PARAMS}}
        for filename in frame["layers"].values():
            if not (out/filename).is_file():
                raise RuntimeError("ICON-D2-Karte fehlt: "+filename)
        frames.append(frame)
    manifest={
        "schema":1,"model":"DWD ICON-D2","cycle":f"{run:%Y%m%d%H}",
        "initialized_utc":run.isoformat().replace("+00:00","Z"),
        "built_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,"step":STEP,
                "width":WIDTH,"height":HEIGHT,"source_projection":grid,
                "source_mesh":"ICON-D2 0.02° rotated (~2.1km); regridded geographically at 0.025°"},
        "unit":"cloud_cover_percent",
        "encoding":"PNG greyscale 0-254 = 0-100 percent; 255 = missing",
        "hours":list(HOURS),
        "layers":{"clcl":"Tiefe Wolken","clcm":"Mittelhohe Wolken","clch":"Hohe Wolken","clct":"Gesamtbewölkung"},
        "frames":frames,"source":"DWD Open Data ICON-D2 regular-lat-lon (rotated) GRIB2"
    }
    tmp=out/"current.json.tmp"
    tmp.write_text(json.dumps(manifest,separators=(",",":"),ensure_ascii=False),encoding="utf-8")
    tmp.replace(out/"current.json")
    LOG.info("ICON-D2 Deutschland fertig: %s, %d Frames, %d verifizierte Felder",run,len(frames),len(records))

if __name__=="__main__":
    main()
