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


def build(output,workers):
    output.mkdir(parents=True,exist_ok=True)
    run,days=choose_cycle()
    hours=tuple(range(0,days*24+1,24))
    manifest_path=output/"gefs_current.json"
    history_dir=output/"runs"
    history_dir.mkdir(parents=True,exist_ok=True)
    if manifest_path.is_file():
        try:
            existing=json.loads(manifest_path.read_text())
            if existing.get("cycle_utc")==run.isoformat().replace("+00:00","Z") and existing.get("forecast_horizon_days",0)>=days:
                if len(existing.get("valid_dates",[]))==existing["forecast_horizon_days"]+1 and len(existing.get("members",{}))==31:
                    LOG.info("Already published complete 60N GEFS ensemble");return
        except (OSError,ValueError,KeyError):
            pass
    results={member:{} for member in MEMBERS}
    tasks=[(member,lead) for lead in hours for member in MEMBERS]
    # Limit parallel calls to respect NOAA NOMADS fair-use expectations.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(fetch_wind,run,member,lead):(member,lead)
                 for member,lead in tasks}
        for completed,future in enumerate(as_completed(futures),start=1):
            member,lead,value=future.result()
            results[member][lead]=value
            if completed%31==0 or completed==len(tasks):
                LOG.info("GEFS 60N/10hPa: %d/%d genuine members×days downloaded",completed,len(tasks))
    for member in MEMBERS:
        if set(results[member])!=set(hours):
            raise RuntimeError(f"GEFS member {member} incomplete: cannot publish")
    daily={member:[results[member][lead] for lead in hours] for member in MEMBERS}
    dates=[(run+timedelta(hours=h)).strftime("%Y-%m-%d") for h in hours]
    # Real member-derived quantiles; no smooth synthetic traces.
    values=np.array([daily[member] for member in MEMBERS],dtype=np.float64)
    mean=np.mean(values,axis=0)
    percentiles=np.percentile(values,[5,25,75,95],axis=0)
    data={
        "schema_version":1,
        "provider":"NOAA GEFS","model":"GEFS 0.5°","level_hpa":LEVEL_HPA,
        "latitude_deg":LATITUDE,"parameter":"zonal_mean_u_wind",
        "units":"m/s","native_resolution_degrees":0.5,
        "cycle_utc":run.isoformat().replace("+00:00","Z"),
        "generated_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "forecast_horizon_days":days,"forecast_interval_hours":24,
        "valid_dates":dates,"members":daily,"member_count":len(MEMBERS),
        "quantiles":{
            "mean":np.round(mean,3).tolist(),
            "p05":np.round(percentiles[0],3).tolist(),
            "p25":np.round(percentiles[1],3).tolist(),
            "p75":np.round(percentiles[2],3).tolist(),
            "p95":np.round(percentiles[3],3).tolist(),
        },
        "method":"Arithmetic mean of the zonal U wind component at 60.0°N, 10 hPa over 720 longitudes (0.5°). Not wind speed.",
        "source":"NOAA NOMADS GEFS 0.5-degree pgrb2a, UGRD 10mb, c00 and p01-p30",
        "climatology_source":"NASA Ozone Watch 1991-2020, separately retrieved by client",
    }
    if len(data["valid_dates"])<17 or len(data["members"])!=31:
        raise RuntimeError("GEFS publication blocked by incomplete dataset")
    # Keep a small rolling archive; never combine values from distinct cycles.
    previous=None
    if manifest_path.is_file():
        try: previous=json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError,ValueError): pass
    if previous and previous.get("cycle_utc") and previous["cycle_utc"]>data["cycle_utc"]:
        LOG.warning("Skipping outdated fallback %s, newer %s is already published",
                    data["cycle_utc"],previous["cycle_utc"])
        return
    if previous and previous.get("cycle_utc") and len(previous.get("members",{}))==31:
        oldkey=previous["cycle_utc"].replace("-","").replace(":","").replace("T","_").replace("Z","")
        oldfile=history_dir/(oldkey+".json")
        if not oldfile.exists():
            oldfile.write_text(json.dumps(previous,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    newkey=run.strftime("%Y%m%d_%H%M%S")
    archived=history_dir/(newkey+".json")
    archived.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    target=manifest_path.with_suffix(".json.tmp")
    target.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    target.replace(manifest_path)
    records=[]
    for item in history_dir.glob("*.json"):
        try:
            payload=json.loads(item.read_text(encoding="utf-8"))
            if payload.get("provider")=="NOAA GEFS" and len(payload.get("members",{}))==31:
                records.append(dict(cycle_utc=payload["cycle_utc"],
                    path="runs/"+item.name,forecast_horizon_days=payload["forecast_horizon_days"]))
        except (ValueError,OSError,KeyError):continue
    records.sort(key=lambda obj:obj["cycle_utc"],reverse=True)
    for stale in records[12:]:
        (history_dir/Path(stale["path"]).name).unlink(missing_ok=True)
    index={"schema_version":1,"provider":"NOAA GEFS","runs":records[:12],
           "latest_cycle_utc":records[0]["cycle_utc"]}
    (output/"gefs_index.json").write_text(json.dumps(index,separators=(",",":"))+"\n",encoding="utf-8")
    LOG.info("PUBLISHED real GEFS ensemble %s, %d members, %d days",run,len(MEMBERS),days)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--max-workers",type=int,default=2)
    a=p.parse_args()
    if not 1<=a.max_workers<=3:raise SystemExit("--max-workers must be between 1 and 3")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    build(a.out,a.max_workers)


if __name__=="__main__":
    main()
