#!/usr/bin/env python3
"""Extract the DWD 2 m temperature at the nominal 00 MEZ New Year term.

Time basis is established per station and TT_TU metadata period. Ambiguous
plain MEZ, other bases, missing metadata and overlaps are deliberately omitted.
Historical hourly terms may have a measurement convention differing from the
nominal full hour; they must not be advertised as exact minute observations.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from zipfile import ZipFile
try:
    from .build_rekordlabor_hourly import URL, read_url, historical_inventory, parse_stations_description, numeric
except ImportError:
    from build_rekordlabor_hourly import URL, read_url, historical_inventory, parse_stations_description, numeric

BASE=URL+"air_temperature/"
# Independently documented non-MEZ periods inside the former MD archive.
# Keep only the affected January years (no temperature data from third parties).
# Source: earthobservations/wetterdienst, local_mean_time_blocks.csv, GH-3910.
# https://github.com/earthobservations/wetterdienst/blob/main/src/wetterdienst/provider/dwd/observation/local_mean_time_blocks.csv
MD_LOCAL_YEARS={
    "00722":((1952,1961),),"00853":((1958,1960),),"01358":((1958,1961),),
    "01544":((1954,1960),),"01957":((1954,1960),),"02503":((1952,1961),),
    "02925":((1957,1960),),"02928":((1955,1957),),"03126":((1955,1958),(1960,1961)),
    "03946":((1953,1960),),"03987":((1973,1975),),"04271":((1953,1961),),
    "04625":((1952,1952),(1954,1954),(1957,1960)),"04752":((1952,1960),),
    "05419":((1953,1958),),"05490":((1955,1960),),"05629":((1958,1960),),
}

def time_periods(pack, sid):
    periods=[]
    for filename in pack.namelist():
        if not re.search(r"Metadaten_Parameter_.*\.txt$",filename,re.I):continue
        for line in pack.read(filename).decode("latin1").splitlines()[1:]:
            p=[v.strip() for v in line.split(";")]
            if len(p)<9 or not p[0].isdigit() or p[0].zfill(5)!=sid or p[4].upper()!="TT_TU":continue
            try:
                start=dt.date.fromisoformat(p[1]);end=dt.date.fromisoformat(p[2]) if p[2] else dt.date.max
            except ValueError:continue
            zone={"Stundenwerte in UTC":"UTC","Stundenwerte in MEZ (MD)":"MEZ (MD)"}.get(p[8],"unknown")
            periods.append((start,end,zone))
    return periods

def extract_newyear(blob:bytes,sid:str):
    candidates={};conflicts=set()
    with ZipFile(io.BytesIO(blob)) as pack:
        periods=time_periods(pack,sid)
        for filename in pack.namelist():
            if not re.search(r"produkt.*\.txt$",filename,re.I):continue
            with pack.open(filename) as raw:
                stream=io.TextIOWrapper(raw,encoding="latin1",errors="replace")
                fields=[x.strip() for x in stream.readline().split(";")]
                indices=[fields.index(k) for k in ("STATIONS_ID","MESS_DATUM","TT_TU","QN_9")]
                for line in stream:
                    if "123123" not in line and "010100" not in line:continue
                    p=line.split(";")
                    if len(p)<=max(indices):continue
                    station,stamp,temp,qn=(p[i].strip() for i in indices)
                    if not station.isdigit() or station.zfill(5)!=sid or not re.fullmatch(r"\d{10}",stamp):continue
                    if stamp[4:] not in ("123123","010100"):continue
                    date=dt.datetime.strptime(stamp,"%Y%m%d%H").date()
                    zones={zone for first,last,zone in periods if first<=date<=last}
                    expected="UTC" if stamp.endswith("123123") else "MEZ (MD)"
                    if zones!={expected}:continue
                    year=date.year+(expected=="UTC")
                    if expected=="MEZ (MD)" and any(start<=year<=end for start,end in MD_LOCAL_YEARS.get(sid,())):continue
                    v=numeric(temp)
                    if v is None or not -70<=v<=65:continue
                    try:quality=int(qn)
                    except ValueError:continue
                    if quality not in (1,2,3,5,7,8,9,10):continue
                    row=[year,v,stamp,expected,quality]
                    if year in candidates and candidates[year]!=row:conflicts.add(year)
                    candidates[year]=row
    return [row for y,row in sorted(candidates.items()) if y not in conflicts]

def merge_records(hist,recent):
    by_year={r[0]:r+["recent"] for r in recent}
    by_year.update({r[0]:r+["historical"] for r in hist})
    return [by_year[y] for y in sorted(by_year)]

def collect(sid,station,hist_url,recent_url):
    historical=extract_newyear(read_url(hist_url),sid) if hist_url else []
    recent=extract_newyear(read_url(recent_url),sid) if recent_url else []
    records=merge_records(historical,recent)
    return {"id":sid,"name":station["name"],"state":station["state"],"lat":station["lat"],"lon":station["lon"],
            "historical_url":hist_url,"recent_url":recent_url,"records":records}

def build(out,limit=0,workers=8):
    hist=historical_inventory(read_url(BASE+"historical/").decode("utf8","replace"),"temperature")
    recent_ids=set(re.findall(r"stundenwerte_TU_(\d{5})_akt\.zip",read_url(BASE+"recent/").decode("utf8","replace")))
    catalog={}
    for folder in ("historical","recent"):
        catalog.update(parse_stations_description(read_url(BASE+folder+"/TU_Stundenwerte_Beschreibung_Stationen.txt").decode("latin1")))
    advertised=set(hist)|recent_ids
    ids=sorted(advertised&set(catalog))
    if limit:
        preferred=[s for s in ("01420","01048","00164","05792") if s in ids]
        ids=(preferred+[s for s in ids if s not in preferred])[:limit]
    stations=[];errors={};empty=[]
    with ThreadPoolExecutor(max_workers=max(1,min(workers,12))) as pool:
        jobs={pool.submit(collect,s,catalog[s],BASE+f"historical/stundenwerte_TU_{s}_{hist[s][0]}_{hist[s][1]}_hist.zip" if s in hist else None,BASE+f"recent/stundenwerte_TU_{s}_akt.zip" if s in recent_ids else None):s for s in ids}
        for job in as_completed(jobs):
            sid=jobs[job]
            try:
                row=job.result()
                if row["records"]:stations.append(row)
                else:empty.append(sid)
            except Exception as exc:errors[sid]=str(exc)[:300]
            if (len(stations)+len(empty)+len(errors))%25==0:print("DWD New Year",len(stations),"stations",len(empty),"without terms",len(errors),"errors of",len(ids),flush=True)
    if errors:raise RuntimeError(f"Incomplete station scan ({len(errors)} errors): {errors}")
    if len(stations)<(min(limit,2) if limit else 100):raise RuntimeError("Too few validated New Year series")
    result={"schema":1,"source":"DWD CDC hourly TT_TU","method":"nominal New Year reference 00 MEZ; explicit UTC or MEZ (MD) metadata only; no interpolation",
            "generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"complete":not bool(limit),"attempted":len(ids),"unmatched_metadata":len(advertised-set(catalog)),"without_terms":len(empty),"stations":sorted(stations,key=lambda r:r["id"])}
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf8")
    print("NEW YEAR VERIFIED",len(stations),"stations",sum(len(r["records"]) for r in stations),"measurements",flush=True)
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True);p.add_argument("--limit",type=int,default=0);p.add_argument("--workers",type=int,default=8)
    a=p.parse_args();build(a.out,a.limit,a.workers)
