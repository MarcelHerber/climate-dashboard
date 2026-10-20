#!/usr/bin/env python3
"""Public ICON-EU cloud fields -> small greyscale forecast frames for a private Worker UI.

Only genuine DWD CLCT, CLCL, CLCM, CLCH GRIB2 products are published.
An invalid/incomplete model run NEVER replaces current.json.
No AI clouds or made-up weather fields.
"""
from __future__ import annotations
import argparse
import bz2
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import json
import logging
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.request

import eccodes
import numpy as np
from PIL import Image

ROOT="https://opendata.dwd.de/weather/nwp/icon-eu/grib"
PREFIX="icon-eu_europe_regular-lat-lon_single-level"
PARAMS=("CLCL","CLCM","CLCH","CLCT")
HOURS=tuple(range(0,37,3))
WEST,EAST,SOUTH,NORTH,STEP=-25.0,45.0,32.0,73.0,.25
WIDTH=int(round((EAST-WEST)/STEP))+1
HEIGHT=int(round((NORTH-SOUTH)/STEP))+1
USER_AGENT="Climate-Dashboard-ICON-Wolkenlabor/1.0"
LOG=logging.getLogger("icon-cloud-lab")

def url_for(cycle,kind,hour):
    fn=f"{PREFIX}_{cycle:%Y%m%d%H}_{hour:03d}_{kind}.grib2.bz2"
    return f"{ROOT}/{cycle.hour:02d}/{kind.lower()}/{fn}"

def request_data(url,retries=3):
    for attempt in range(retries):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":USER_AGENT})
            with urllib.request.urlopen(req,timeout=55) as resp:
                raw=resp.read()
            if len(raw)<10000:
                raise RuntimeError("GRIB-Datei zu klein")
            return raw
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,RuntimeError) as exc:
            if attempt>=retries-1 or isinstance(exc,urllib.error.HTTPError) and exc.code==404:
                raise RuntimeError(f"Open Data fehlt/fehlerhaft: {url}: {exc}") from exc
            time.sleep(2**attempt*3)
    raise RuntimeError("unreachable")

def find_cycle(now):
    start=now.replace(minute=0,second=0,microsecond=0)
    start-=dt.timedelta(hours=start.hour%6)
    # Prefer a complete cycle rather than a newly started incomplete forecast.
    for lag in range(1,8):
        cycle=start-dt.timedelta(hours=6*lag)
        try:
            for kind in PARAMS:
                request_data(url_for(cycle,kind,HOURS[-1]),retries=1)
            LOG.info("Vollständigen ICON-EU-Lauf gefunden: %s",cycle.isoformat())
            return cycle
        except RuntimeError:
            continue
    raise RuntimeError("Kein vollständiger ICON-EU-CLCL/CLCM/CLCH/CLCT-Lauf bei +36h")

def decode_grib(raw):
    with tempfile.TemporaryFile() as file:
        file.write(bz2.decompress(raw))
        file.seek(0)
        handle=eccodes.codes_grib_new_from_file(file)
        if handle is None:
            raise RuntimeError("GRIB2 enthält keine Nachricht")
        try:
            lat=np.asarray(eccodes.codes_get_array(handle,"latitudes"),dtype=np.float32)
            lon=np.asarray(eccodes.codes_get_array(handle,"longitudes"),dtype=np.float32)
            val=np.asarray(eccodes.codes_get_values(handle),dtype=np.float32)
            name=str(eccodes.codes_get(handle,"shortName"))
            unit=str(eccodes.codes_get(handle,"units"))
            end=eccodes.codes_get(handle,"endStep")
            if val.size!=lat.size or val.size!=lon.size or val.size<10000:
                raise RuntimeError("GRIB-Gitter ungültig")
            return lat,lon,val,name,unit,end
        finally:
            eccodes.codes_release(handle)

def to_grid(lat,lon,values,unit):
    lon=np.where(lon>180,lon-360,lon)
    y=np.rint((NORTH-lat)/STEP).astype(np.int32)
    x=np.rint((lon-WEST)/STEP).astype(np.int32)
    valid=(y>=0)&(y<HEIGHT)&(x>=0)&(x<WIDTH)&np.isfinite(values)&(values>=0)&(values<=100.01)
    if np.count_nonzero(valid)<1000:
        raise RuntimeError("ICON-Gitter ohne verwertbare europäische Wolkendaten")
    a=y[valid]*WIDTH+x[valid]
    n=np.bincount(a,minlength=WIDTH*HEIGHT)
    total=np.bincount(a,weights=values[valid],minlength=WIDTH*HEIGHT)
    result=np.full(WIDTH*HEIGHT,255,dtype=np.uint8)
    present=n>0
    percent=np.clip(total[present]/n[present],0,100)
    result[present]=np.round(percent*2.54).astype(np.uint8)
    coverage=np.count_nonzero(present)/(WIDTH*HEIGHT)
    # ICON-EU's geographic footprint is not rectangular. Preserve genuine
    # missing cells with the PNG sentinel 255 instead of inventing cloud cover.
    if coverage<.80:
        raise RuntimeError(f"GRIB deckt nur {coverage:.1%} des Ausschnitts")
    if coverage<.99:
        LOG.info("Echte ICON-EU-Modellmaske: %.1f%% Abdeckung (fehlende Pixel bleiben transparent)",coverage*100)
    return result.reshape(HEIGHT,WIDTH),coverage

def process(args):
    kind,hour,cycle,out=args
    raw=request_data(url_for(cycle,kind,hour))
    lat,lon,values,name,units,end=decode_grib(raw)
    if np.nanmax(values)>101 or np.nanmin(values)<-.001:
        raise RuntimeError(f"{kind}+{hour}: unplausible Wolkenwerte")
    if str(units).lower() not in ("%", "percent"):
        raise RuntimeError(f"{kind}+{hour}: unerwartete Einheit {units!r}, keine Umrechnung geraten")
    arr,coverage=to_grid(lat,lon,values,units)
    folder=out/"frames"/cycle.strftime("%Y%m%d%H")
    folder.mkdir(parents=True,exist_ok=True)
    fn=f"{kind.lower()}_{hour:03d}.png"
    target=folder/fn
    Image.fromarray(arr,mode="L").save(target,optimize=True)
    return {"kind":kind.lower(),"hour":hour,"path":f"frames/{cycle:%Y%m%d%H}/{fn}","coverage":round(coverage,4),
            "min":float(np.nanmin(values)),"max":float(np.nanmax(values))}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=Path("icon-cloud-film-public"))
    parser.add_argument("--max-workers",type=int,default=5)
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    out=args.out;out.mkdir(parents=True,exist_ok=True)
    cycle=find_cycle(dt.datetime.now(dt.timezone.utc))
    current=out/"current.json"
    if current.is_file():
        try:
            d=json.loads(current.read_text(encoding="utf-8"))
            if d.get("cycle")==cycle.strftime("%Y%m%d%H") and d.get("schema")==1:
                LOG.info("Aktueller kompletter ICON-EU-Wolkenlauf bereits veröffentlicht")
                return
        except ValueError:
            pass
    tasks=[(kind,hour,cycle,out)for hour in HOURS for kind in PARAMS]
    records=[]
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        results={executor.submit(process,task):task for task in tasks}
        for future in as_completed(results):
            rec=future.result()
            records.append(rec)
            LOG.info("Echter Wolkenfilm: %s +%02dh fertig",rec["kind"],rec["hour"])
    frames=[]
    files={(x["kind"],x["hour"]):x for x in records}
    for hour in HOURS:
        item={"hour":hour,"valid_utc":(cycle+dt.timedelta(hours=hour)).isoformat().replace("+00:00","Z"),
              "layers":{kind.lower():files[kind.lower(),hour]["path"] for kind in PARAMS}}
        frames.append(item)
    manifest={"schema":1,"model":"DWD ICON-EU","cycle":cycle.strftime("%Y%m%d%H"),
              "initialized_utc":cycle.isoformat().replace("+00:00","Z"),
              "built_utc":dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00","Z"),
              "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,
                      "step":STEP,"width":WIDTH,"height":HEIGHT},
              "unit":"cloud_cover_percent","encoding":"PNG greyscale 0-254=0-100 percent;255=missing",
              "hours":list(HOURS),"layers":{"clcl":"Tiefe Wolken","clcm":"Mittelhohe Wolken",
                 "clch":"Hohe Wolken","clct":"Gesamtbewölkung"},"frames":frames,
              "source":"DWD Open Data: ICON-EU regular lat-lon GRIB2"}
    # Atomic publication: current.json is touched only after all 52 files exist.
    for row in frames:
        for path in row["layers"].values():
            if not (out/path).is_file():
                raise RuntimeError(f"Fehlendes Wolkenbild: {path}")
    (out/"current.json").write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    LOG.info("ICON-EU Wolkenfilm fertig: %s, %d Frames, %d GRIB2-Felder",cycle,len(frames),len(records))

if __name__=="__main__":
    main()
