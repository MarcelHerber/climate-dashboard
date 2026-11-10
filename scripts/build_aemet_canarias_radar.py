#!/usr/bin/env python3
"""AEMET Canaries georeferenced radar reflectivity; real 0.5-degree PPI.

Source: https://www.aemet.es/es/api-eltiempo/radar/download/regional/LPA
The official tar.gz contains the three latest GeoTIFFs plus other products.
Only LPA PPI.Z_005_240 at verified current timestamps is accepted.

Output 0: no decoded echo / coverage unknown; 1..11: discrete AEMET
dBZ classes 12-18,...,>=72; 255: outside actual GeoTIFF extent.
These are categories from the ORIGINAL AEMET embedded 'ESCALA' RGBA,
not guessed dBZ values. Areas without echoes cannot be conclusively
distinguished from locations outside the effective radar coverage.
"""
from __future__ import annotations
import argparse,ast,io,json,logging,re,tarfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
from PIL import Image
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import Resampling,reproject
import requests

LOG=logging.getLogger("aemet-canarias")
URL="https://www.aemet.es/es/api-eltiempo/radar/download/regional/LPA"
WEST,EAST,SOUTH,NORTH=-19.5,-12.2,27.0,30.6
WIDTH,HEIGHT=1460,720
FILE_RE=re.compile(r"(?:^|/)down_LPA(\d{12})\.PPI\.Z_005_240\.tif$",re.I)
LABELS=("12–18","18–24","24–30","30–36","36–42","42–48",
        "48–54","54–60","60–66","66–72","≥72")
MAX_AGE_MIN=60
RETENTION_HOURS=4
MAX_FRAMES=24

def utc(dt:datetime)->str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def parse_members(tar:tarfile.TarFile,now:datetime):
    result=[]
    for item in tar.getmembers():
        match=FILE_RE.search(item.name)
        if not match or not item.isfile() or item.size<5000 or item.size>10_000_000:continue
        try:stamp=datetime.strptime(match.group(1),"%y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:continue
        if now-timedelta(hours=RETENTION_HOURS)<=stamp<=now+timedelta(minutes=5):
            result.append((stamp,item))
    result.sort(key=lambda pair:pair[0])
    if not result or (now-result[-1][0])>timedelta(minutes=MAX_AGE_MIN):
        raise RuntimeError("AEMET Canary radar GeoTIFFs are stale or missing")
    return result

def read_palette(ds):
    if ds.tags().get("DATA_TYPE_UNITS")!="dBZ":
        raise ValueError("AEMET radar is not reflectivity in dBZ")
    if "PPI" not in ds.tags().get("ESCALA",""):
        raise ValueError("No AEMET PPI color scale in GeoTIFF")
    info=ast.literal_eval(ds.tags()["ESCALA"])
    if info.get("Producto")!="PPI" or len(info.get("Lista RGBA",[]))!=11:
        raise ValueError("Unexpected AEMET reflectivity legend")
    entries=list(reversed(info["Lista RGBA"]))
    colors=np.array([[int(n) for n in e["RGBA"][:3]] for e in entries],dtype=np.int16)
    for j,(entry,label) in enumerate(zip(entries,LABELS)):
        lower=entry["Valores"][0]
        expected=[12,18,24,30,36,42,48,54,60,66,72][j]
        if lower!=expected:raise ValueError(f"Changed AEMET reflectivity threshold: {lower}")
    return colors

def process_geotiff(data:bytes):
    """Returns 8-bit ordinal intensity image plus a QA summary."""
    with MemoryFile(data) as mem,mem.open() as ds:
        if ds.crs is None or ds.crs.to_epsg()!=4326 or ds.count!=4:
            raise ValueError("Missing WGS84 georeferencing or RGBA bands")
        if not ds.width>2500 or not ds.height>2500:
            raise ValueError("Unexpected AEMET PPI spatial dimensions")
        if not (ds.bounds.left<-19 and ds.bounds.right>-13 and
                ds.bounds.bottom<27 and ds.bounds.top>30):
            raise ValueError("Canary radar image does not cover requested archipelago")
        colors=read_palette(ds)
        transform=from_bounds(WEST,SOUTH,EAST,NORTH,WIDTH,HEIGHT)
        rgba=np.zeros((4,HEIGHT,WIDTH),dtype=np.uint8)
        for i in range(4):
            reproject(source=rasterio.band(ds,i+1),destination=rgba[i],
                src_transform=ds.transform,src_crs=ds.crs,
                dst_transform=transform,dst_crs="EPSG:4326",
                src_nodata=None,dst_nodata=0,
                resampling=Resampling.nearest,num_threads=2)
        r,g,b,alpha=[v.astype(np.int16) for v in rgba]
        # Only pixels close to the 11 authoritative legend swatches qualify
        # as actual radar echoes. Ignore base-map backgrounds and text.
        out=np.zeros((HEIGHT,WIDTH),dtype=np.uint8)
        match_best=np.full((HEIGHT,WIDTH),32767,dtype=np.int16)
        for index,(cr,cg,cb) in enumerate(colors,start=1):
            distance=np.maximum.reduce((np.abs(r-cr),np.abs(g-cg),np.abs(b-cb)))
            mask=(distance<15)&(alpha>=190)&(distance<match_best)
            out[mask]=index
            match_best[mask]=distance[mask]
        # The original GeoTIFF does not explicitly distinguish all
        # no-echo areas from missing radar coverage. Never call zero "dry".
        echo_count=int(np.count_nonzero(out))
        result={
            "echo_pixel_fraction":round(echo_count/out.size,5),
            "classes_present":sorted(int(v) for v in np.unique(out) if v>0),
            "geo_bounds":[WEST,SOUTH,EAST,NORTH],
            "full_coverage_not_guaranteed":True
        }
        return out,result,colors.tolist()

def build(out:Path,count:int=MAX_FRAMES):
    out.mkdir(parents=True,exist_ok=True)
    now=datetime.now(timezone.utc)
    r=requests.get(URL,timeout=110,headers={
        "User-Agent":"ClimateDashboard-Canary-Radar-Test/1.0",
        "Accept":"application/tar+gzip"})
    r.raise_for_status()
    if len(r.content)<1_000_000 or len(r.content)>90_000_000:
        raise ValueError("Invalid AEMET regional radar archive size")
    previous={}
    if (out/"current.json").exists():
        try:previous=json.loads((out/"current.json").read_text(encoding="utf-8"))
        except (ValueError,OSError):pass
    retained=[]
    for row in previous.get("frames",[]):
        try:
            moment=datetime.fromisoformat(row["utc"].replace("Z","+00:00"))
            if now-timedelta(hours=RETENTION_HOURS)<=moment<=now and (out/row["image"]).is_file():
                retained.append(row)
        except (ValueError,KeyError,TypeError):continue
    rows={row["utc"]:row for row in retained}
    palette=None
    with tarfile.open(fileobj=io.BytesIO(r.content),mode="r:gz") as tf:
        for instant,item in parse_members(tf,now):
            key=utc(instant)
            relative="frames/"+instant.strftime("%Y%m%d%H%M")+".png"
            if key in rows and (out/relative).is_file():
                continue
            content=tf.extractfile(item)
            if content is None:raise ValueError("Missing AEMET GeoTIFF archive member")
            raster,stats,colors=process_geotiff(content.read())
            palette=colors
            path=out/relative
            path.parent.mkdir(parents=True,exist_ok=True)
            Image.fromarray(raster,mode="L").save(path,optimize=True)
            rows[key]={"utc":key,"image":relative,"stats":stats}
            LOG.info("LPA %s: radar echoes=%.4f; levels=%s",key,stats["echo_pixel_fraction"],stats["classes_present"])
    sequence=sorted(rows.values(),key=lambda row:row["utc"])[-count:]
    if len(sequence)<1:raise RuntimeError("No verified actual Canary radar frames")
    newest=datetime.fromisoformat(sequence[-1]["utc"].replace("Z","+00:00"))
    if now-newest>timedelta(minutes=MAX_AGE_MIN):
        raise RuntimeError("Canary radar is stale; refuse to publish current status")
    manifest={
        "schema":1,"source":"AEMET Canarias / regional LPA reflectivity GeoTIFF",
        "source_url":URL,"license":"© AEMET; reproducible with attribution",
        "built_utc":utc(datetime.now(timezone.utc)),
        "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,"width":WIDTH,"height":HEIGHT},
        "unit":"dBZ","radar_product":"PPI 0.5 degree",
        "cadence_minutes":10,"max_history_hours":RETENTION_HOURS,
        "palette":{"labels":LABELS,"colors":[
            "#0000fc","#0094fc","#00fcfc","#438323","#00c000","#00ff00",
            "#ffff00","#ffbb00","#ff7f00","#ff0000","#c8005a"
        ],"no_radar_echo_or_coverage_unknown":0},
        "coverage_note":"Only recognized AEMET PPI reflectivity colors are mapped. No echo and missing radar coverage cannot always be distinguished. No interpolation or invented precipitation.",
        "frames":sequence
    }
    path=out/"current.json"
    temp=out/"current.json.tmp"
    temp.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    temp.replace(path)
    wanted={row["image"] for row in sequence}
    for image in (out/"frames").glob("*.png"):
        if image.relative_to(out).as_posix() not in wanted:image.unlink()
    return manifest

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--smoke",action="store_true")
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    m=build(args.out,count=3 if args.smoke else MAX_FRAMES)
    print("AEMET LPA radar from actual GeoTIFFs:",len(m["frames"]),"latest",m["frames"][-1]["utc"])
