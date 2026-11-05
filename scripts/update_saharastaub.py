#!/usr/bin/env python3
"""Preprocess real DWD ICON-ART-EU Saharan dust GRIB into a fixed-palette JSON map."""
from __future__ import annotations
import argparse
import base64
import datetime as dt
import json
import logging
from pathlib import Path
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request, error
import numpy as np

try:
    import eccodes
except ImportError:
    eccodes = None

log = logging.getLogger("saharastaub")
BASE = "https://opendata.dwd.de/weather/nwp/v1/m/icon-art-eu/p"
PARAMS = {"taod": ("TAOD_DUST", 1.0), "column": ("DUST_TOTAL_MC_VI", 1e6), "surface": ("DUST_TOTAL_MC/lvt1/150/lv1/74", 1e9)}
COLORS = ["#f2f4f7", "#e3e7eb", "#d8cfb3", "#efe08a", "#f7c65a", "#f39a3c", "#ea6b2d", "#d63f2f", "#9c2f5f", "#5a2875"]
PALETTES = {
    "taod":{"breaks":[0.05,0.1,0.2,0.35,0.5,0.75,1,1.5,2.5],"colors":COLORS,"unit":"1"},
    "column":{"breaks":[25,50,100,200,400,800,1600,2500,4000],"colors":COLORS,"unit":"mg/m2"},
    "surface":{"breaks":[1,2,5,10,20,40,80,150,300],"colors":COLORS,"unit":"µg/m3"}
}
GRID = {"lon_min":-28.0,"lat_min":25.0,"step":0.2,"cols":440,"rows":245,
        "encoding":"rle-u8-base64"}
HOURS = tuple(range(0,121,6))
HEADERS = {"User-Agent":"ClimateDashboardSaharanDust/1.0"}

def url_for(cycle:dt.datetime,param:str,hour:int)->str:
    return (f"{BASE}/{param}/r/{cycle.strftime('%Y-%m-%dT%H:00')}"
            f"/s/PT{hour:03d}H00M.grib2")

def get(url:str,method:str="GET",retries:int=2)->bytes|None:
    for attempt in range(retries):
        try:
            req=request.Request(url,headers=HEADERS,method=method)
            with request.urlopen(req,timeout=60) as response:
                return response.read() if method=="GET" else b"OK"
        except (error.HTTPError,error.URLError,TimeoutError,ConnectionError) as exc:
            if isinstance(exc,error.HTTPError) and exc.code in (403,404):
                return None
            if attempt+1==retries:
                log.warning("Downloadfehler %s: %s",url,exc)
            else:
                time.sleep(2)
    return None

def choose_cycle(now:dt.datetime)->dt.datetime:
    now=now.astimezone(dt.timezone.utc)
    current=now.replace(hour=now.hour//6*6,minute=0,second=0,microsecond=0)
    for n in range(5):
        cycle=current-dt.timedelta(hours=6*n)
        if (now-cycle).total_seconds()<2.5*3600:
            continue
        # Only publish a run that has reached at least +72 h for both fields.
        if all(get(url_for(cycle,param,h),"HEAD",1) is not None
               for param,_ in PARAMS.values() for h in (0,72)):
            return cycle
    raise RuntimeError("Kein vollständiger ICON-ART-EU-Lauf bis mindestens +72 h")

def quantize(values,breaks):
    """Classes 0..9, using invariant absolute limits, not auto-min/max."""
    return np.searchsorted(breaks,values,side="right").astype(np.uint8)

def rle_encode(array):
    values=np.asarray(array,dtype=np.uint8).ravel()
    if not len(values):
        raise ValueError("Leeres Raster")
    out=bytearray()
    i=0
    while i<len(values):
        j=i+1
        while j<len(values) and j-i<65535 and values[j]==values[i]:
            j+=1
        n=j-i
        out.extend((int(values[i]),n&255,n>>8))
        i=j
    return base64.b64encode(out).decode("ascii")

def rle_decode(encoded,expected):
    data=base64.b64decode(encoded,validate=True)
    if len(data)%3:
        raise ValueError("Ungültige RLE-Länge")
    array=np.empty(expected,dtype=np.uint8)
    pos=0
    for i in range(0,len(data),3):
        val=data[i];n=data[i+1]+256*data[i+2]
        if not n or pos+n>expected or (val>9 and val!=255):
            raise ValueError("Ungültige RLE-Klasse")
        array[pos:pos+n]=val
        pos+=n
    if pos!=expected:
        raise ValueError("Unvollständiges RLE-Raster")
    return array

def decode_grib(raw):
    """Unstructured ICON data do not embed latitudes/longitudes per cell."""
    if eccodes is None:
        raise RuntimeError("ecCodes ist nicht installiert")
    with tempfile.TemporaryFile() as file:
        file.write(raw);file.seek(0)
        handle=eccodes.codes_grib_new_from_file(file)
        if handle is None:
            raise RuntimeError("Leere GRIB2-Datei")
        try:
            values=np.asarray(eccodes.codes_get_values(handle),dtype=np.float64)
            kind=str(eccodes.codes_get(handle,"gridType"))
            grid_number=int(eccodes.codes_get(handle,"numberOfGridUsed"))
            if len(values)<10000 or grid_number!=61:
                raise RuntimeError(f"Unerwartetes ICON-ART-Gitter: {grid_number}, {len(values)} Werte")
            return values,kind
        finally:
            eccodes.codes_release(handle)


def download_coordinates(run):
    """Official DWD native cell centers CLAT/CLON at forecast step +0 h."""
    coords={}
    for key in ("CLAT","CLON"):
        url=url_for(run,key,0)
        raw=get(url)
        if not raw or not raw.startswith(b"GRIB"):
            raise RuntimeError("ICON-ART-Geokoordinaten "+key+
                               " fehlen im DWD-Lauf; veröffentliche keine falschen Karten")
        values,kind=decode_grib(raw)
        if kind!="unstructured_grid":
            raise RuntimeError(f"Unerwartete Koordinatengeometrie: {kind}")
        coords[key]=values
    lat=coords["CLAT"];lon=coords["CLON"]
    # DWD CLAT/CLON GRIB fields are in degrees, not the radians of ICON NetCDF.
    if len(lat)!=len(lon) or len(lat)!=1013404:
        raise RuntimeError("DWD-Koordinaten haben falsche Rasterlänge")
    if not (np.nanmin(lat)>=-90 and np.nanmax(lat)<=90 and
            np.nanmin(lon)>=-180 and np.nanmax(lon)<=360 and
            np.nanmax(lat)>70 and np.nanmax(lon)>50):
        raise RuntimeError("DWD-Koordinaten nicht in plausiblen Gradwerten")
    log.info("Koordinaten geladen: %s Gitterzellen",len(lat))
    return lat,lon

class Aggregator:
    def __init__(self):
        self.mask=None;self.index=None;self.grid_type=None;self.points=None
    def convert(self,values,lat,lon,kind,key):
        if self.mask is None:
            self.grid_type=kind;self.points=len(values)
            lat=np.asarray(lat);lon=np.asarray(lon)
            lon=np.where(lon>180,lon-360,lon)
            col=np.floor((lon-GRID["lon_min"])/GRID["step"]).astype(np.int32)
            row=np.floor((lat-GRID["lat_min"])/GRID["step"]).astype(np.int32)
            self.mask=(np.isfinite(lat)&np.isfinite(lon)&(col>=0)&(col<GRID["cols"])&
                       (row>=0)&(row<GRID["rows"]))
            self.index=row[self.mask]*GRID["cols"]+col[self.mask]
            if self.mask.sum()<10000:
                raise RuntimeError("Zu wenig ICON-ART-Modellgebiet auf der Karte")
        if len(values)!=self.points or kind!=self.grid_type:
            raise RuntimeError("Geometrie des Modellgitters wechselt")
        field=np.asarray(values,dtype=float)[self.mask]
        valid=np.isfinite(field)&(field>=-1e-10)&(field<1e12)
        idx=self.index[valid]
        n=GRID["rows"]*GRID["cols"]
        counts=np.bincount(idx,minlength=n)
        sums=np.bincount(idx,weights=np.maximum(field[valid],0),minlength=n)
        coverage=counts>0
        if coverage.sum()<30000:
            raise RuntimeError("Modellgebietsabdeckung unplausibel")
        result=np.full(n,255,dtype=np.uint8)
        mean=(sums[coverage]/counts[coverage])*PARAMS[key][1]
        result[coverage]=quantize(mean,PALETTES[key]["breaks"])
        return result

def build(now):
    run=choose_cycle(now)
    log.info("ICON-ART-EU %s",run)
    tasks={(key,h):url_for(run,param,h) for key,(param,_) in PARAMS.items() for h in HOURS}
    blobs={}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(get,url):k for k,url in tasks.items()}
        for future in as_completed(futures):
            key=futures[future]
            try:
                blob=future.result()
                if blob and blob.startswith(b"GRIB") and blob.endswith(b"7777"):
                    blobs[key]=blob
                else:
                    log.warning("Unvollständiges GRIB %s",key)
            except Exception as exc:
                log.warning("GRIB-Download %s: %s",key,exc)
    # Surface is optional: an unavailable three-dimensional level must not suppress
    # the reliable two-dimensional dust fields.
    hours=[h for h in HOURS if all((key,h) in blobs for key in ("taod","column"))]
    if len(hours)<13 or hours[0]!=0 or hours[-1]<72:
        raise RuntimeError("Zu wenige vollständige gemeinsame Vorhersagezeiten")
    # Latitude and longitude are separate invariant GRIB2 fields on native grid #61.
    lat,lon=download_coordinates(run)
    aggregator=Aggregator()
    frames=[]
    for h in hours:
        frame={"hour":h,"valid_utc":(run+dt.timedelta(hours=h)).isoformat().replace("+00:00","Z")}
        for key in PARAMS:
            if (key,h) not in blobs:
                continue
            field,kind=decode_grib(blobs[(key,h)])
            if len(field)!=len(lat):
                raise RuntimeError("Vorhersagefeld passt nicht zu CLAT/CLON-Gitter #61")
            classes=aggregator.convert(field,lat,lon,kind,key)
            frame[key]=rle_encode(classes)
            if not np.array_equal(rle_decode(frame[key],len(classes)),classes):
                raise RuntimeError("Verlust bei Rasterkomprimierung")
        frames.append(frame)
    return {"schema":1,"source":"DWD ICON-ART-EU","run_utc":run.isoformat().replace("+00:00","Z"),
            "generated_utc":now.astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z"),
            "grid":GRID,"palettes":PALETTES,"frames":frames,
            "note":"Arithmetisches Zellmittel im 0.2-Grad-Raster; feste Farbklassen. Surface = unterstes ICON-Modellniveau 74, kein PM10."}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result=build(dt.datetime.now(dt.timezone.utc))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(".tmp")
    temp.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    temp.replace(args.output)
    log.info("Gespeichert: %s, %s Prognosezeiten",args.output,len(result["frames"]))

if __name__=="__main__":
    main()
