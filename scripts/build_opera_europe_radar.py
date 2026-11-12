#!/usr/bin/env python3
"""Official EUMETNET OPERA pan-European radar composite from MeteoGate/ORD S3.

CIRRUS DBZH: instantaneous maximum reflectivity, 1km / 5min.
NIMBUS RATE: instantaneous precipitation intensity, 2km / 15min.
The public ODIM cloud-optimized GeoTIFFs contain actual physical floats.
No precipitation is NaN ('undetect' in COG metadata); -9999000 means
no radar coverage. Those are encoded separately in 8-bit PNGs.
License: EUMETNET OPERA CC BY 4.0.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from pathlib import Path
import argparse,io,json,logging,math,time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import quote

import numpy as np
from PIL import Image
import requests
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling

LOG=logging.getLogger("opera")
API="https://api.meteogate.eu/eu-eumetnet-weather-radar/collections/observations/locations/0-20010-0-OPERA"
S3="https://s3.waw3-1.cloudferro.com/openradar-24h"
WEST,EAST,SOUTH,NORTH=-27.,47.,29.,73.
WIDTH,HEIGHT=1480,880
MAX_AGE={"dbzh":45,"rate":55}
COUNT={"dbzh":16,"rate":8}
DBZH_RANGE=(-20.,75.)
RATE_MAX=120.
RATE_BASE=.05
NO_DATA=-9999000.0
PRODUCTS={"dbzh":{"name":"CIRRUS","unit":"dBZ","cadence_minutes":5,"native_km":1},
          "rate":{"name":"NIMBUS","unit":"mm/h","cadence_minutes":15,"native_km":2}}

def iso(ts:datetime)->str:
    return ts.isoformat().replace("+00:00","Z")

def discover(session:requests.Session,kind:str,now:datetime,count:int) -> list[datetime]:
    start=now-timedelta(minutes=200)
    resp=session.get(API,params={
        "datetime":f"{iso(start)}/{iso(now)}","f":"CoverageJSON",
        "standard_name":kind.upper(),"format":"ODIM"},timeout=45)
    resp.raise_for_status()
    d=resp.json()
    times=d.get("domain",{}).get("axes",{}).get("t",{}).get("values",[])
    stamps=set()
    for item in times:
        try:
            time=datetime.fromisoformat(item.replace("Z","+00:00")).astimezone(timezone.utc)
        except (ValueError,TypeError):continue
        time=time.replace(second=0,microsecond=0)
        if start<=time<=now+timedelta(minutes=3):stamps.add(time)
    ordered=sorted(stamps)
    if len(ordered)<4:
        raise ValueError(f"OPERA ORD returned only {len(ordered)} {kind.upper()} timestamps")
    if (now-ordered[-1]).total_seconds()>MAX_AGE[kind]*60:
        raise ValueError(f"Stale OPERA {kind} latest UTC {iso(ordered[-1])}")
    selected=ordered[-count:]
    interval=PRODUCTS[kind]["cadence_minutes"]
    # Warn, do not silently make or interpolate missing observed radar frames.
    gaps=[(selected[i]-selected[i-1]).total_seconds()/60 for i in range(1,len(selected))]
    if gaps and max(gaps)>interval*2:
        LOG.warning("OPERA %s has time gaps of up to %.0f min",kind,max(gaps))
    return selected

def s3url(stamp:datetime,kind:str)->str:
    return f"{S3}/{stamp:%Y/%m/%d}/OPERA/COMP/OPERA@{stamp:%Y%m%dT%H%M}@0@{kind.upper()}.tiff"

def decode_geotiff(blob:bytes,kind:str,instant:datetime) -> tuple[np.ndarray,dict]:
    with MemoryFile(blob) as mem,mem.open() as ds:
        tags=ds.tags()
        expect="MAX" if kind=="dbzh" else "PPI"
        if tags.get("product")!=expect:
            raise ValueError(f"Unexpected OPERA {kind} product {tags.get('product')}")
        valid_str=tags.get("enddate","")+tags.get("endtime","")
        if len(valid_str)!=14:
            raise ValueError("Missing OPERA observation end date/time")
        valid=datetime.strptime(valid_str,"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        if abs((instant-valid).total_seconds())>90:
            raise ValueError("OPERA image timestamp mismatches ORD index")
        if ds.count<1 or not ds.crs or ds.nodata is None or ds.width<1000:
            raise ValueError("Missing OPERA COG raster georeferencing / nodata")
        if abs(ds.nodata-NO_DATA)>10:
            raise ValueError("Unexpected OPERA no-data code")
        if abs(ds.scales[0]-1)>1e-6 or abs(ds.offsets[0])>.001:
            raise ValueError("Unexpected OPERA COG physical units")
        # Official 'undetect' (no echo) is NaN in the GeoTIFF.
        if ds.tags(1).get("undetect")!="nan":
            raise ValueError("Cannot distinguish rain-free and missing pixels")
        if kind=="dbzh" and ds.width!=3800:
            raise ValueError("Unexpected CIRRUS 1km resolution")
        if kind=="rate" and ds.width!=1900:
            raise ValueError("Unexpected NIMBUS 2km resolution")
        source=ds.read(1)
        target=np.full((HEIGHT,WIDTH),NO_DATA,dtype=np.float32)
        reproject(
            source,target,
            src_transform=ds.transform,src_crs=ds.crs,src_nodata=NO_DATA,
            dst_transform=from_bounds(WEST,SOUTH,EAST,NORTH,WIDTH,HEIGHT),
            dst_crs="EPSG:4326",dst_nodata=NO_DATA,
            resampling=Resampling.nearest,
            init_dest_nodata=True, num_threads=2,
        )
    missing=(target<=NO_DATA+100)|(np.isinf(target))
    # NaN is the official no-radar-echo value, not a missing observation.
    noecho=np.isnan(target)
    good=~missing&~noecho
    encoded=np.full(target.shape,255,np.uint8)
    encoded[noecho]=0
    if kind=="dbzh":
        lo,hi=DBZH_RANGE
        q=1+np.rint(253*np.clip((target[good]-lo)/(hi-lo),0,1))
        encoded[good]=q.astype(np.uint8)
        echo_fraction=float((good & (target>-10)).mean())
    else:
        wet=good&(target>0)
        encoded[good]=0
        q=1+np.rint(253*np.log1p(np.clip(target[wet],0,RATE_MAX)/RATE_BASE)/
                    np.log1p(RATE_MAX/RATE_BASE))
        encoded[wet]=np.clip(q,1,254).astype(np.uint8)
        echo_fraction=float(wet.mean())
    coverage=float((encoded!=255).mean())
    if coverage<.10 or coverage>.999:
        raise ValueError(f"Implausible OPERA {kind} radar coverage={coverage:.3f}")
    stats={
        "coverage":round(coverage,4),
        "echo_fraction":round(echo_fraction,4),
        "min_physical":round(float(np.min(target[good])),2) if good.any() else None,
        "max_physical":round(float(np.max(target[good])),2) if good.any() else None,
        "undetect_fraction":round(float(noecho.mean()),4)
    }
    return encoded,stats

def build(out:Path, counts:dict[str,int]|None=None)->dict:
    if counts is None:counts=COUNT
    out.mkdir(parents=True,exist_ok=True)
    (out/"frames").mkdir(exist_ok=True)
    now=datetime.now(timezone.utc)
    session=requests.Session()
    session.headers["User-Agent"]="ClimateDashboard-EUMETNET-OPERA-Radar-Lab/1.0 (meteorological education)"
    session.mount("https://",HTTPAdapter(max_retries=Retry(
        total=3,backoff_factor=2,status_forcelist=(429,500,502,503,504),
        allowed_methods=frozenset(["GET"]),respect_retry_after_header=True)))
    old={}
    try:old=json.loads((out/"current.json").read_text(encoding="utf-8"))
    except (ValueError,OSError):pass
    frames={}
    for kind in ("dbzh","rate"):
        stamps=discover(session,kind,now,counts[kind])
        previous={f["utc"]:f for f in old.get("products",{}).get(kind,{}).get("frames",[])}
        rows=[]
        for stamp in stamps:
            relative=f"frames/{kind}_{stamp:%Y%m%d%H%M}.png"
            target=out/relative
            prior=previous.get(iso(stamp))
            if prior and target.is_file() and target.stat().st_size>250 and "stats" in prior:
                rows.append(prior);continue
            url=s3url(stamp,kind)
            try:
                response=session.get(url,timeout=85)
                # MeteoGate ORD may advertise a timestamp before the COG is
                # present on S3. A 404 is missing data, never a zero-rain frame.
                if response.status_code==404:
                    LOG.warning("OPERA %s %s announced but COG not published (404)",
                                kind,iso(stamp))
                    continue
                response.raise_for_status()
                pixels,stats=decode_geotiff(response.content,kind,stamp)
            except requests.RequestException as exc:
                LOG.warning("OPERA %s %s temporarily unavailable: %s",
                            kind,iso(stamp),exc)
                continue
            Image.fromarray(pixels,mode="L").save(target,optimize=True)
            rows.append({"utc":iso(stamp),"image":relative,"stats":stats})
            LOG.info("OPERA %s %s coverage=%.3f min/max=%s/%s",kind,iso(stamp),
                     stats["coverage"],stats["min_physical"],stats["max_physical"])
        if len(rows)<min(4,counts[kind]):
            raise ValueError(f"Insufficient verified {kind} frames")
        last_verified=datetime.fromisoformat(rows[-1]["utc"].replace("Z","+00:00"))
        if now-last_verified>timedelta(minutes=MAX_AGE[kind]):
            raise RuntimeError(
                f"OPERA {kind} newest verified image {iso(last_verified)} is stale"
            )
        frames[kind]={**PRODUCTS[kind],"frames":rows}
    manifest={
        "schema":1,"source":"EUMETNET OPERA CIRRUS / NIMBUS (ORD via MeteoGate)",
        "license":"Creative Commons Attribution 4.0 International (CC BY 4.0)",
        "credit":"© EUMETNET OPERA; data: MeteoGate ORD / openradar-24h",
        "updated_utc":iso(datetime.now(timezone.utc)),
        "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,"width":WIDTH,"height":HEIGHT},
        "encoding":{
            "nodata":255,"undetect":0,"echo_min":1,"echo_max":254,
            "dbzh_range":list(DBZH_RANGE),"rate_max":RATE_MAX,"rate_log_base":RATE_BASE
        },
        "products":frames,
    }
    tmp=out/"current.json.tmp"
    tmp.write_text(json.dumps(manifest,separators=(",",":"),ensure_ascii=False),encoding="utf-8")
    tmp.replace(out/"current.json")
    wanted={f["image"] for p in frames.values() for f in p["frames"]}
    for file in (out/"frames").glob("*.png"):
        if file.relative_to(out).as_posix() not in wanted:file.unlink()
    return manifest

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--smoke",action="store_true")
    a=p.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    m=build(a.out,{"dbzh":2,"rate":2} if a.smoke else COUNT)
    print("Verified OPERA two composites",{k:len(v["frames"]) for k,v in m["products"].items()})
