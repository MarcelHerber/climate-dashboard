#!/usr/bin/env python3
"""Archive-only DWD hourly weather changes, with exact time steps and source QC.

Uses official DWD CDC hourly /historical/ ZIP archives. Does not confuse
hourly means with instantaneous maxima, or hourly wind direction with gusts.
Only available station/parameter combinations are published.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import datetime as dt
import heapq
import io
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile

URL="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/"
SOURCES={
 "temperature":("air_temperature","TU","TT_TU","°C"),
 "pressure":("pressure","P0","P0","hPa"),
 "wind_direction":("wind","FF","D","°")
}
STATIONS={
 "00164":("Angermünde","Brandenburg",53.031,13.991),
 "00198":("Artern","Thüringen",51.375,11.292),
 "00102":("Leuchtturm Alte Weser","Niedersachsen",53.863,8.128)
}
HOURS=(1,3,6,12,24)
LIMIT=20
MISSING={"-999","-999.0","-999.00","","NaN","nan"}
now=dt.datetime.now(dt.timezone.utc)

def read_url(url:str,timeout:int=70)->bytes:
    last=None
    for n in range(3):
        try:
            req=Request(url,headers={"User-Agent":"ClimateDashboardDWDStationRecordLab/1.0 (open-data research)"})
            with urlopen(req,timeout=timeout) as response:
                value=response.read(20_000_000)
            if not value:raise ValueError("Empty response")
            return value
        except Exception as error:
            last=error;time.sleep(n+1)
    raise RuntimeError(f"DWD download failed: {url} -> {last}")

def archive_url(parameter:str,sid:str,listing=None):
    category,prefix,*_=SOURCES[parameter]
    directory=URL+category+"/historical/"
    body=listing if listing is not None else read_url(directory).decode("utf-8","replace")
    rx=re.compile(r"stundenwerte_"+prefix+r"_"+sid+r"_(\d{8})_(\d{8})_hist\.zip")
    matches=[(m.group(2),m.group(0)) for m in rx.finditer(body)]
    if not matches:return None
    return directory+max(matches)[1]

def numeric(v):
    v=(v or "").strip().replace(",",".")
    if v in MISSING:return None
    try:n=float(v)
    except ValueError:return None
    return n if -998<n<2000 else None

def rows_from_zip(blob:bytes,parameter:str)->dict[str,object]:
    _,prefix,column,_=SOURCES[parameter]
    data={}
    with ZipFile(io.BytesIO(blob)) as pack:
        files=[k for k in pack.namelist()
            if k.lower().endswith(".txt") and ("produkt_" in k.lower() or "produkt" in k.lower())]
        if not files:
            raise ValueError(f"No DWD product TXT in historical {prefix} ZIP")
        for filename in sorted(files):
            with pack.open(filename) as f:
                with io.TextIOWrapper(f,encoding="latin1",errors="replace",newline="") as stream:
                    reader=csv.DictReader(stream,delimiter=";")
                    headers={k.strip():k for k in (reader.fieldnames or [])}
                    if column not in headers or "MESS_DATUM" not in headers:
                        raise ValueError(f"DWD field {column} absent in {filename}: {list(headers)}")
                    for row in reader:
                        stamp=(row.get(headers["MESS_DATUM"]) or "").strip()
                        if not re.fullmatch(r"\d{10}",stamp):continue
                        v=numeric(row.get(headers[column]))
                        if v is None:continue
                        if parameter=="temperature" and not -70<=v<=65:continue
                        if parameter=="pressure" and not 800<=v<=1100:continue
                        if parameter=="wind_direction" and not 0<=v<=360:continue
                        if parameter=="wind_direction":
                            speed=numeric(row.get(headers.get("F","F")))
                            if speed is None or not 0<=speed<=90:continue
                            data[stamp]={"direction":v%360,"speed":speed}
                        else:data[stamp]=v
    return data

def iso(stamp:str)->str:
    return stamp[:4]+"-"+stamp[4:6]+"-"+stamp[6:8]+"T"+stamp[8:10]+":00Z"

def step(stamp:str,hours:int)->str:
    date=dt.datetime.strptime(stamp,"%Y%m%d%H")+dt.timedelta(hours=hours)
    return date.strftime("%Y%m%d%H")

def delta(parameter,before,after):
    if parameter=="wind_direction":
        if before["speed"]<3 or after["speed"]<3:return None
        return abs(((after["direction"]-before["direction"]+540)%360)-180)
    return round(after-before,3)

def plot_value(parameter,value):
    return value["direction"] if parameter=="wind_direction" else value

def is_significant(parameter,direction,change):
    return change is not None and (direction!="down" or parameter!="wind_direction")

def top_events(data:dict,parameter:str,hours:int,direction:str):
    counters=0;queue=[]
    for end,after in data.items():
        before=data.get(step(end,-hours))
        if before is None:continue
        change=delta(parameter,before,after)
        if not is_significant(parameter,direction,change):continue
        counters+=1
        score=change if direction=="up" else -change
        # Keep 120 strongest, then drop overlapping, effectively identical episodes.
        item=(score,end,change,before,after)
        if len(queue)<120:heapq.heappush(queue,item)
        elif score>queue[0][0]:heapq.heapreplace(queue,item)
    sorted_list=sorted(queue,key=lambda x:(-x[0],x[1]))
    selected=[]
    for _,end,change,before,after in sorted_list:
        td=dt.datetime.strptime(end,"%Y%m%d%H")
        if any(abs((td-dt.datetime.strptime(x[1],"%Y%m%d%H")).total_seconds())<
               max(3,hours)*3600 for x in selected):continue
        selected.append((change,end,before,after))
        if len(selected)==LIMIT:break
    return counters,selected

def make_trace(data,parameter,start,end):
    t0=dt.datetime.strptime(start,"%Y%m%d%H")-dt.timedelta(hours=12)
    t1=dt.datetime.strptime(end,"%Y%m%d%H")+dt.timedelta(hours=12)
    t=t0;trace=[]
    while t<=t1:
        stamp=t.strftime("%Y%m%d%H");v=data.get(stamp)
        trace.append([iso(stamp),None if v is None else round(plot_value(parameter,v),2)])
        t+=dt.timedelta(hours=1)
    return trace

def record_events(data,parameter,hours,direction):
    count,records=top_events(data,parameter,hours,direction)
    output=[]
    for change,end,before,after in records:
        start=step(end,-hours)
        output.append({"start":iso(start),"end":iso(end),
            "delta":round(change,2),
            "before":round(plot_value(parameter,before),2),
            "after":round(plot_value(parameter,after),2),
            "trace":make_trace(data,parameter,start,end)})
    return {"coverage":{"pairs":count},"events":output}

def build_station(sid,listing):
    name,state,lat,lon=STATIONS[sid]
    metrics={};failures={}
    for parameter in SOURCES:
        url=archive_url(parameter,sid,listing.get(parameter))
        if not url:
            failures[parameter]="No official historical hourly archive"
            continue
        try:
            data=rows_from_zip(read_url(url),parameter)
            if len(data)<24*30:raise ValueError("Too few valid hourly values")
            dates=sorted(data)
            years={"start":iso(dates[0]),"end":iso(dates[-1])}
            d={"source":"DWD CDC · "+SOURCES[parameter][0]+" · "+SOURCES[parameter][2],
                "source_url":url,"unit":SOURCES[parameter][3],"period":years,
                "observed_hours":len(data),"windows":{}}
            for hours in HOURS:
                up=record_events(data,parameter,hours,"up")
                down=record_events(data,parameter,hours,"down") if parameter!="wind_direction" else {"coverage":{"pairs":up["coverage"]["pairs"]},"events":[]}
                if up["coverage"]["pairs"]>0:
                    d["windows"][str(hours)]={
                      "coverage":{"pairs":up["coverage"]["pairs"]},
                      "up":up["events"],"down":down["events"]}
            if d["windows"]:metrics[parameter]=d
            else:failures[parameter]="No valid exact pairs"
            print(sid,parameter,len(data),"hourly measures, periods",list(d["windows"]),flush=True)
        except Exception as error:
            failures[parameter]=str(error)[:400]
            print("SOURCE FAILED",sid,parameter,failures[parameter],flush=True)
    return {"schema":1,"station_id":sid,"name":name,"state":state,"lat":lat,"lon":lon,
        "generated_at":now.isoformat(),"metrics":metrics,
        "unavailable_sources":failures}

def build(out:Path):
    out.mkdir(parents=True,exist_ok=True)
    listing={}
    for name,(category,_,_,_) in SOURCES.items():
        try:listing[name]=read_url(URL+category+"/historical/").decode("utf-8","replace")
        except Exception as e:listing[name]="";print("DWD INDEX ERROR",name,e,flush=True)
    records=[]
    for sid in STATIONS:
        row=build_station(sid,listing)
        if row["metrics"]:
            (out/f"{sid}.json").write_text(json.dumps(row,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
            records.append({"id":sid,"name":row["name"],"state":row["state"],
                "lat":row["lat"],"lon":row["lon"],
                "metrics":list(row["metrics"]),
                "periods":{key:value["period"] for key,value in row["metrics"].items()}})
    if not records:raise RuntimeError("Zero verified DWD hourly stations; do not publish empty archive")
    result={"schema":1,"ready":True,"publisher":"Deutscher Wetterdienst (DWD) CDC",
       "method":"Exact original hourly time pairs, nonoverlapping top events, gap-safe",
       "generated_at":now.isoformat(),"stations":records,
       "note":"Pilot stations only, not a Germany-wide maximum. Official historical, QC-complete files."}
    (out/"index.json").write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print("DWD HOURLY RECORDS",json.dumps(result,ensure_ascii=False),flush=True)

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,default=Path("data/rekordlabor/weather_turns"))
    args=ap.parse_args()
    build(args.out)
