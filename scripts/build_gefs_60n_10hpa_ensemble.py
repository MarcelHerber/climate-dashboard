#!/usr/bin/env python3
"""NOAA GEFS 0.5 degree: 60N zonal-mean U-wind at 10 hPa, 31 real members.

The GEFS 00 UTC run can extend to 840 hours (35 days). Download the
10-hPa UGRD field cropped to the 59.5-60.5N latitude band, all longitudes,
then average only the exact 60.0N parallel. Averages across latitude or
from wind speed sqrt(u^2+v^2) would be scientifically incorrect.

No forecast member, time step, or ensemble quantile is manufactured.
If the full 35d cycle is unavailable, a complete 16d cycle can be published
and is explicitly labelled by its shorter horizon.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from http.client import HTTPException, RemoteDisconnected, IncompleteRead
import json
import logging
import random
from pathlib import Path
import socket
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import eccodes
import numpy as np

LOG=logging.getLogger("GEFS-60N-10hPa")
URL="https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p50a.pl"
MEMBERS=("c00",)+tuple(f"p{x:02d}" for x in range(1,31))
LATITUDE=60.0
LEVEL_HPA=10


def url_for(run, member, lead):
    prefix="gec00" if member=="c00" else "ge"+member
    filename=f"{prefix}.t{run.hour:02d}z.pgrb2a.0p50.f{lead:03d}"
    query={
      "file":filename,"lev_10_mb":"on","var_UGRD":"on",
      "subregion":"","leftlon":"0","rightlon":"359.5",
      "toplat":"60.5","bottomlat":"59.5",
      "dir":f"/gefs.{run:%Y%m%d}/{run.hour:02d}/atmos/pgrb2ap5",
    }
    return URL+"?"+urlencode(query)


def download(url, retries=5):
    for attempt in range(1,retries+1):
        try:
            req=Request(url,headers={
                "User-Agent":"ClimateDashboard-GEFS-Stratosphere/1.0",
                "Accept-Encoding":"identity","Connection":"close",
            })
            with urlopen(req,timeout=75) as response:
                payload=response.read()
            if not payload.startswith(b"GRIB") or len(payload)<300:
                raise ValueError("NOAA did not return a complete 10hPa GRIB2")
            return payload
        except HTTPError as ex:
            if ex.code in (400,403,404):
                raise RuntimeError(f"GEFS file unavailable or access denied: HTTP {ex.code}, {url}") from ex
            cause=ex
        except (URLError,RemoteDisconnected,IncompleteRead,HTTPException,
                TimeoutError,socket.timeout,ConnectionError,OSError,ValueError) as ex:
            cause=ex
        if attempt==retries:
            raise RuntimeError(f"GEFS download failed after {retries} attempts: {cause}; {url}") from cause
        pause=min(5*2**(attempt-1),60)+random.random()*.8
        LOG.warning("GEFS retry %s/%s in %.1fs: %s",attempt,retries,pause,cause)
        time.sleep(pause)
    raise AssertionError("unreachable")


def zonal_mean_from_grid(latitude, longitude, velocity):
    """Pure numerical testable 60°N zonal arithmetic mean of U (not speed)."""
    if not (len(latitude)==len(longitude)==len(velocity)):
        raise ValueError("Invalid GEFS GRIB geometry")
    row=np.abs(latitude-LATITUDE)<.015
    lon=np.mod(longitude[row],360)
    values=velocity[row]
    if len(values)!=720 or len(np.unique(np.round(lon*2)))!=720:
        raise ValueError(f"GEFS 60N longitude circle incomplete: {len(values)}/720")
    valid=np.isfinite(values)&(values>-150)&(values<170)
    if valid.sum()!=720:
        raise ValueError(f"Missing/invalid 60N UGRD values: {valid.sum()}/720")
    return round(float(np.mean(values,dtype=np.float64)),3)


def zonal_wind(raw):
    with tempfile.TemporaryFile() as source:
        source.write(raw);source.seek(0)
        handle=eccodes.codes_grib_new_from_file(source)
        if handle is None:raise ValueError("Empty NOAA GEFS GRIB2")
        try:
            kind=str(eccodes.codes_get(handle,"shortName")).lower()
            level=int(eccodes.codes_get(handle,"level"))
            vertical=str(eccodes.codes_get(handle,"typeOfLevel"))
            unit=str(eccodes.codes_get(handle,"units"))
            if kind not in ("u","ugrd") or level!=LEVEL_HPA or vertical not in ("isobaricInhPa","isobaricInPa"):
                raise ValueError(f"GEFS pressure/parameter mismatch: {kind} {level} {vertical}")
            if unit.replace(" ","") not in ("ms**-1","ms-1","m/s","ms^-1"):
                raise ValueError(f"Unexpected GEFS U-wind units: {unit}")
            latitude=np.asarray(eccodes.codes_get_array(handle,"latitudes"),dtype=np.float32)
            longitude=np.asarray(eccodes.codes_get_array(handle,"longitudes"),dtype=np.float32)
            velocity=np.asarray(eccodes.codes_get_values(handle),dtype=np.float32)
            return zonal_mean_from_grid(latitude,longitude,velocity)
        finally:
            eccodes.codes_release(handle)


def fetch_wind(run,member,lead):
    wind=zonal_wind(download(url_for(run,member,lead)))
    # A modest delay between small NOMADS GRIB-filter downloads avoids
    # hammering the public service (also with 2 parallel workers).
    time.sleep(.4)
    return member,lead,wind


def candidates(now=None):
    """Newly published cycles first, respecting typical release delay."""
    now=now or datetime.now(timezone.utc)
    ready=now-timedelta(hours=5)
    latest=ready.replace(hour=(ready.hour//6)*6,minute=0,second=0,microsecond=0)
    return [latest-timedelta(hours=6*i) for i in range(12)]


def choose_cycle():
    # A fresh 16-day run is preferred to an *older* 35-day run.
    # Previously the horizon-first loop silently kept yesterday's 35-day
    # forecast even when a current, fully available 16-day run existed.
    # Never mix members/validity dates from different model cycles.
    for candidate in candidates():
        for days in ((35,16) if candidate.hour==0 else (16,)):
            last=days*24
            try:
                fetch_wind(candidate,"c00",last)
                fetch_wind(candidate,"p30",last)
                LOG.info("GEFS newest complete-cycle candidate %s, horizon %d days",
                         candidate,days)
                return candidate,days
            except Exception as error:
                LOG.warning("GEFS %s +%d unavailable: %s",candidate,last,error)
    raise RuntimeError("No verifiable NOAA GEFS 10 hPa cycle reaching 16 days")


def verified(data):
    """Check every original member, date and quantile before reusing archived bytes."""
    try:
        if (data.get("provider")!="NOAA GEFS" or data.get("level_hpa")!=10 or
            data.get("latitude_deg")!=60 or data.get("units")!="m/s"):
            return False
        run=datetime.fromisoformat(data["cycle_utc"].replace("Z","+00:00"))
        if run.hour not in (0,6,12,18) or run.minute:
            return False
        horizon=data["forecast_horizon_days"]
        if horizon not in (16,35) or (horizon==35 and run.hour!=0):
            return False
        dates=data["valid_dates"]
        expected=[(run+timedelta(days=i)).strftime("%Y-%m-%d") for i in range(horizon+1)]
        if dates!=expected or data.get("member_count")!=31:
            return False
        members=data["members"]
        if set(members)!=set(MEMBERS):
            return False
        if not all(isinstance(v,list) and len(v)==len(dates) and
                   all(isinstance(x,(int,float)) and np.isfinite(x) and -150<x<170 for x in v)
                   for v in members.values()):
            return False
        expected_quantiles=("mean","p05","p25","p75","p95")
        if any(len(data.get("quantiles",{}).get(k,[]))!=len(dates) for k in expected_quantiles):
            return False
        return True
    except (TypeError,KeyError,ValueError,OverflowError):
        return False


def load_valid(path):
    if path.is_file():
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            if verified(data):
                return data
        except (OSError,ValueError): pass
    return None


def archive_name(cycle):
    return cycle.strftime("%Y%m%d_%H%M%S")+".json"


def publish(output,data):
    """Atomic publication; an older 35-day enhancement never replaces today's forecast."""
    if not verified(data):
        raise RuntimeError("Refusing incomplete GEFS ensemble")
    output.mkdir(parents=True,exist_ok=True)
    history_dir=output/"runs"
    history_dir.mkdir(parents=True,exist_ok=True)
    current=output/"gefs_current.json"
    old=load_valid(current)
    if old and old["cycle_utc"]!=data["cycle_utc"]:
        previous=history_dir/archive_name(datetime.fromisoformat(old["cycle_utc"].replace("Z","+00:00")))
        if not previous.is_file():
            previous.write_text(json.dumps(old,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n",encoding="utf-8")
    cycle=datetime.fromisoformat(data["cycle_utc"].replace("Z","+00:00"))
    target=history_dir/archive_name(cycle)
    staged=target.with_suffix(".tmp")
    staged.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n",encoding="utf-8")
    staged.replace(target)
    if old is None or data["cycle_utc"]>=old["cycle_utc"]:
        staged=current.with_suffix(".tmp")
        staged.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n",encoding="utf-8")
        staged.replace(current)
    records=[]
    for file in history_dir.glob("*.json"):
        saved=load_valid(file)
        if saved:
            records.append({"cycle_utc":saved["cycle_utc"],"path":"runs/"+file.name,
                            "forecast_horizon_days":saved["forecast_horizon_days"]})
    records.sort(key=lambda r:r["cycle_utc"],reverse=True)
    for item in records[12:]:
        (history_dir/Path(item["path"]).name).unlink(missing_ok=True)
    if not records:
        raise RuntimeError("GEFS archive was not published")
    manifest={"schema_version":1,"provider":"NOAA GEFS",
              "latest_cycle_utc":load_valid(current)["cycle_utc"],"runs":records[:12]}
    idx=output/"gefs_index.json"
    tmp=idx.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    tmp.replace(idx)
    LOG.info("GEFS archive %d verified runs; newest=%s; current=%s",
             len(records),records[0]["cycle_utc"],manifest["latest_cycle_utc"])
    return manifest


def build_cycle(output,workers,run,days):
    output.mkdir(parents=True,exist_ok=True)
    hours=tuple(range(0,days*24+1,24))
    history=output/"runs"/archive_name(run)
    stored=load_valid(history)
    latest=load_valid(output/"gefs_current.json")
    if not stored and latest and latest["cycle_utc"]==run.isoformat().replace("+00:00","Z"):
        stored=latest
    if stored and stored["forecast_horizon_days"]>=days:
        LOG.info("Complete %d-day GEFS run already archived: %s",days,run)
        return publish(output,stored)
    # When the slow 35-day extension becomes available, reuse the exact
    # already verified same-cycle 16-day original member values.
    old_days=stored["forecast_horizon_days"] if stored else -1
    required=hours if not stored else tuple(h for h in hours if h>old_days*24)
    results={member:{} for member in MEMBERS}
    if stored:
        for member in MEMBERS:
            for i,value in enumerate(stored["members"][member]):
                results[member][i*24]=value
    LOG.info("GEFS %s: %d new genuine GRIB downloads (existing %d days reused)",
             run,len(required)*len(MEMBERS),max(0,old_days))
    tasks=[(member,lead) for lead in required for member in MEMBERS]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(fetch_wind,run,member,lead):(member,lead) for lead in required for member in MEMBERS}
        for completed,future in enumerate(as_completed(futures),start=1):
            member,lead,value=future.result()
            results[member][lead]=value
            if completed%31==0 or completed==len(tasks):
                LOG.info("GEFS %s: %d/%d member×day original fields",run,completed,len(tasks))
    for member in MEMBERS:
        if set(results[member])!=set(hours):
            raise RuntimeError(f"Incomplete GEFS member {member}: refusing publish")
    daily={member:[results[member][h] for h in hours] for member in MEMBERS}
    values=np.array([daily[key] for key in MEMBERS],dtype=np.float64)
    percentiles=np.percentile(values,[5,25,75,95],axis=0)
    data={
        "schema_version":1,"provider":"NOAA GEFS","model":"GEFS 0.5°",
        "level_hpa":LEVEL_HPA,"latitude_deg":LATITUDE,
        "parameter":"zonal_mean_u_wind","units":"m/s",
        "native_resolution_degrees":0.5,
        "cycle_utc":run.isoformat().replace("+00:00","Z"),
        "generated_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "forecast_horizon_days":days,"forecast_interval_hours":24,
        "valid_dates":[(run+timedelta(hours=h)).strftime("%Y-%m-%d") for h in hours],
        "members":daily,"member_count":len(MEMBERS),
        "quantiles":{
          "mean":np.round(np.mean(values,axis=0),3).tolist(),
          "p05":np.round(percentiles[0],3).tolist(),
          "p25":np.round(percentiles[1],3).tolist(),
          "p75":np.round(percentiles[2],3).tolist(),
          "p95":np.round(percentiles[3],3).tolist(),
        },
        "method":"Arithmetic mean of signed U component on 60N / 10hPa, all 720 longitudes",
        "source":"NOAA NOMADS GEFS 0.5 degree pgrb2a UGRD 10mb c00,p01-p30",
        "climatology_source":"NASA Ozone Watch 1991-2020"
    }
    if not verified(data):
        raise RuntimeError("Inconsistent GEFS 31-member forecast, not publishing")
    return publish(output,data)


def extended_cycle(now=None):
    """The 00z f840 product may need 21+ hours beyond f384 (NOAA SCN20-75).
    Use the most recently completed *previous-day* 00z cycle for stability.
    """
    now=now or datetime.now(timezone.utc)
    return (now-timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)


def build(output,workers,mode="current"):
    if mode=="extended":
        run=extended_cycle()
        # Early test avoids creating partial archived member files.
        fetch_wind(run,"c00",840)
        fetch_wind(run,"p30",840)
        return build_cycle(output,workers,run,35)
    if mode!="current":
        raise ValueError("Unrecognized GEFS build mode")
    run,days=choose_cycle()
    return build_cycle(output,workers,run,days)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--max-workers",type=int,default=2)
    p.add_argument("--mode",choices=("current","extended"),default="current")
    a=p.parse_args()
    if not 1<=a.max_workers<=3:raise SystemExit("--max-workers must be between 1 and 3")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    build(a.out,a.max_workers,a.mode)


if __name__=="__main__":
    main()
