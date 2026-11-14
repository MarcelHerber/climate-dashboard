#!/usr/bin/env python3
"""Archive-only DWD hourly weather changes, with exact time steps and source QC.

Uses official DWD CDC hourly /historical/ ZIP archives. Does not confuse
hourly means with instantaneous maxima, or hourly wind direction with gusts.
Only available station/parameter combinations are published.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import datetime as dt
import heapq
import io
import json
import hashlib
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
                        if parameter=="pressure" and not 930<=v<=1065:continue
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

def physically_continuous_pressure(data,start,end,hours):
    """Pressure changes must have fully observed, physically plausible hours.
    This rejects one-hour instrument spikes and isolated bad 1990s P0 values.
    We conservatively exclude unverified candidates, never interpolate them.
    """
    previous=data.get(start)
    if previous is None:return False
    for h in range(1,hours+1):
        current=data.get(step(start,h))
        if current is None or abs(current-previous)>8.0:return False
        previous=current
    return True

# Integer hour keys avoid repeatedly parsing millions of DWD timestamps. They
# preserve exact UTC distances across midnight and leap days.
def hour_key(stamp:str)->int:
    return dt.date(int(stamp[:4]),int(stamp[4:6]),int(stamp[6:8])).toordinal()*24+int(stamp[8:10])

def hour_stamp(hour:int)->str:
    return dt.date.fromordinal(hour//24).strftime("%Y%m%d")+f"{hour%24:02d}"

def hourly_data(data:dict):
    if not data:return {}
    return {hour_key(k):v for k,v in data.items()} if isinstance(next(iter(data)),str) else data

def pressure_runs(data:dict[int,float])->dict[int,int]:
    """Number of consecutive, present, <=8 hPa hourly steps ending at t."""
    runs={}
    for t in sorted(data):
        previous=data.get(t-1)
        runs[t]=(runs.get(t-1,0)+1) if previous is not None and abs(data[t]-previous)<=8 else 0
    return runs

def top_events(data:dict,parameter:str,hours:int,direction:str,validated_pressure=None):
    index=hourly_data(data)
    runs=(validated_pressure if validated_pressure is not None else pressure_runs(index)) if parameter=="pressure" else None
    counters=0;queue=[]
    for end,after in index.items():
        before=index.get(end-hours)
        if before is None:continue
        change=delta(parameter,before,after)
        if parameter=="pressure":
            # A change is valid only with every intermediate hour measured,
            # no hourly jump >8 hPa, and a plausible total difference.
            if abs(change)>55 or runs.get(end,0)<hours:continue
        if not is_significant(parameter,direction,change):continue
        counters+=1
        score=change if direction=="up" else -change
        item=(score,end,change,before,after)
        if len(queue)<300:heapq.heappush(queue,item)
        elif score>queue[0][0]:heapq.heapreplace(queue,item)
    ordered=sorted(queue,key=lambda x:(-x[0],x[1]))
    selected=[]
    for _,end,change,before,after in ordered:
        if any(abs(end-item[1])<max(3,hours) for item in selected):continue
        selected.append((change,end,before,after))
        if len(selected)==LIMIT:break
    return counters,selected

def make_trace(data,parameter,start:int,end:int):
    index=hourly_data(data)
    trace=[]
    for t in range(start-12,end+13):
        v=index.get(t)
        trace.append([iso(hour_stamp(t)),None if v is None else round(plot_value(parameter,v),2)])
    return trace

def record_events(data,parameter,hours,direction,validated_pressure=None):
    count,records=top_events(data,parameter,hours,direction,validated_pressure)
    output=[]
    for change,end,before,after in records:
        start=end-hours
        output.append({"start":iso(hour_stamp(start)),"end":iso(hour_stamp(end)),
            "delta":round(change,2),
            "before":round(plot_value(parameter,before),2),
            "after":round(plot_value(parameter,after),2),
            "trace":make_trace(data,parameter,start,end)})
    return {"coverage":{"pairs":count},"events":output}

LANDS=tuple(sorted((
    "Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg",
    "Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen",
    "Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt",
    "Schleswig-Holstein","Thüringen"
),key=len,reverse=True))

def historical_inventory(listing,parameter):
    prefix=SOURCES[parameter][1]
    rx=re.compile(r"stundenwerte_"+prefix+r"_(\d{5})_(\d{8})_(\d{8})_hist\.zip")
    inventory={}
    for sid,first,last in rx.findall(listing):
        if sid not in inventory or last>inventory[sid][1]:
            inventory[sid]=(first,last)
    return inventory

def parse_stations_description(body):
    """Official DWD fixed-width station catalogue, with original geo coordinates."""
    stations={}
    rx=re.compile(r"^\s*(\d{5})\s+(\d{8})\s+(\d{8})\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(.+?)\s*$")
    for line in body.splitlines():
        match=rx.match(line)
        if not match:continue
        sid,first,last,height,latitude,longitude,tail=match.groups()
        # The official file has a further "Abgabe" field ("Frei")
        # after Bundesland; never assume the state is at line end.
        found=re.search(r"\s+("+"|".join(re.escape(land) for land in LANDS)+r")(?=\s|$)",tail)
        if found is None:continue
        state=found.group(1)
        name=tail[:found.start()].strip()
        lat,lon=float(latitude),float(longitude)
        if not name or not (47<=lat<=56 and 5<=lon<=16):continue
        stations[sid]={"name":name,"state":state,"lat":lat,"lon":lon,
            "first":first,"last":last}
    return stations

def discover_stations(listing,target=0,pinned=None):
    """Deterministic regional expansion; index records are never inferred."""
    catalogue={}
    for parameter,(category,prefix,_,_) in SOURCES.items():
        description=URL+category+"/historical/"+prefix+"_Stundenwerte_Beschreibung_Stationen.txt"
        try:
            body=read_url(description)
            parsed=parse_stations_description(body.decode("latin1","replace"))
            # TU takes precedence for overlapping station IDs.
            for sid,row in parsed.items():
                catalogue.setdefault(sid,row)
            print("DWD STATION METADATA",parameter,len(parsed),"total",len(catalogue),flush=True)
        except Exception as error:
            print("DWD STATION METADATA UNAVAILABLE",parameter,str(error)[:200],flush=True)
    if not catalogue:
        raise RuntimeError("No official DWD hourly station descriptions available")
    inv={name:historical_inventory(html,name) for name,html in listing.items()}
    print("DWD PARAMETER INDEX COUNTS", {name:len(entries) for name,entries in inv.items()},flush=True)
    candidates=[]
    all_ids=set().union(*(set(item) for item in inv.values()))
    for sid in sorted(all_ids):
        if sid in STATIONS:continue
        station=catalogue.get(sid)
        if station is None:continue
        archives=[inv[p][sid] for p in SOURCES if sid in inv[p]]
        if not archives:continue
        first=min(x[0] for x in archives)
        last=max(x[1] for x in archives)
        measured=len(archives)
        recent=sum(sid in inv[name] and inv[name][sid][1]>="20241231" for name in SOURCES)
        # Eligibility is decided from genuinely measured hourly pairs after
        # download. Do not exclude closed, short-lived, or single-variable
        # stations at the directory-discovery stage.
        candidates.append((sid,station,measured,int(first[:4]),recent,int(last[:4])))
    selected=dict(STATIONS)
    for sid,row in (pinned or {}).items():
        # Never silently remove previously validated locations.
        if sid not in selected and sid in catalogue:
            st=catalogue[sid]
            selected[sid]=(st["name"],st["state"],st["lat"],st["lon"])
    if target<=0:
        for sid,station,_,_,_,_ in candidates:
            selected.setdefault(sid,(station["name"],station["state"],station["lat"],station["lon"]))
        print("DWD HOURLY STATION DISCOVERY",len(catalogue),"geolocated,",
              len(candidates),"archive candidates, all selected",len(selected),
              "pinned",len(pinned or {}),flush=True)
        return selected
    counts=defaultdict(int)
    for _,land,_,_ in selected.values():counts[land]+=1
    def distance(station):
        return min((((station["lat"]-row[2])*1.1)**2+
                     ((station["lon"]-row[3])*.65)**2)**.5 for row in selected.values())
    # Balanced across all 16 Länder before filling larger states densely.
    for quota in (3,5,8,12,16,22,30,40,60,120,240):
        if len(selected)>=target:break
        for land in sorted(LANDS):
            while counts[land]<quota and len(selected)<target:
                pool=[c for c in candidates if c[1]["state"]==land and c[0] not in selected]
                if not pool:break
                sid,st,measured,first,recent,last=max(pool,key=lambda c:(
                    c[4]>=2,c[2]>=2,c[4]>0,round(distance(c[1]),2),c[5],-c[3],c[0]))
                selected[sid]=(st["name"],land,st["lat"],st["lon"])
                counts[land]+=1
    print("DWD HOURLY STATION DISCOVERY",len(catalogue),"catalogue locations,",
          len(candidates),"available hourly candidates, selected",len(selected),
          "previously verified",len(pinned or {}),flush=True)
    return selected

def build_station(sid,listing,stations=None,cache_dir=None):
    name,state,lat,lon=(stations or STATIONS)[sid]
    # Reuse audited output only while the official historical ZIP names
    # remain unchanged and the snapshot is recent. Avoid redownloading
    # identical 50-year hourly archives on every branch or retry.
    if cache_dir:
        cached_path=Path(cache_dir)/(sid+".json")
        if cached_path.is_file():
            try:
                old=json.loads(cached_path.read_text(encoding="utf-8"))
                checked=dt.datetime.fromisoformat(old["generated_at"].replace("Z","+00:00"))
                fresh=(now-checked).total_seconds()<14*86400
                complete=all(
                    (old.get("metrics",{}).get(param,{}).get("source_url")==archive_url(param,sid,listing.get(param)))
                    if param in old.get("metrics",{})
                    else (param in old.get("unavailable_sources",{}) and
                          ("No official historical hourly archive" not in old["unavailable_sources"][param] or
                           archive_url(param,sid,listing.get(param)) is None))
                    for param in SOURCES
                )
                if fresh and complete and old.get("station_id")==sid and old.get("metrics"):
                    print("DWD HOURLY CACHE VALID",sid,flush=True)
                    return old
            except (OSError,ValueError,KeyError,TypeError):
                pass
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
            indexed=hourly_data(data)
            pressure_valid=pressure_runs(indexed) if parameter=="pressure" else None
            d={"source":"DWD CDC · "+SOURCES[parameter][0]+" · "+SOURCES[parameter][2],
                "source_url":url,"unit":SOURCES[parameter][3],"period":years,
                "observed_hours":len(data),"windows":{},
                "quality_notes":("Sea-level pressure: 930–1065 hPa plus <=8 hPa/hour continuous hourly validation, <=55 hPa per window" if parameter=="pressure" else
                   "Wind directions require both hourly mean speeds >=3 m/s; no gusts" if parameter=="wind_direction" else
                   "Temperature valid only at measured UTC hours; no filled gaps")}
            for hours in HOURS:
                up=record_events(indexed,parameter,hours,"up",pressure_valid)
                down=record_events(indexed,parameter,hours,"down",pressure_valid) if parameter!="wind_direction" else {"coverage":{"pairs":up["coverage"]["pairs"]},"events":[]}
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

def build(out:Path,target:int=0,min_stations:int=0,workers:int=3,
          shard_index:int|None=None,shard_count:int=1,cache_dir:Path|None=None):
    out.mkdir(parents=True,exist_ok=True)
    if shard_count<1 or (shard_index is not None and not 0<=shard_index<shard_count):
        raise ValueError("Invalid DWD shard configuration")
    listing={}
    for name,(category,_,_,_) in SOURCES.items():
        listing[name]=read_url(URL+category+"/historical/").decode("utf-8","replace")
    archive=Path(cache_dir) if cache_dir is not None else out
    pinned={}
    previous=archive/"index.json"
    if previous.is_file():
        try:
            idx=json.loads(previous.read_text(encoding="utf-8"))
            pinned={str(s["id"]):s for s in idx.get("stations",[])}
        except (ValueError,KeyError,TypeError):pass
    stations=discover_stations(listing,target,pinned)
    all_ids=sorted(stations)
    if shard_index is not None:
        selected=[sid for n,sid in enumerate(all_ids) if n%shard_count==shard_index]
    else:selected=all_ids
    if shard_index is None and len(selected)<min_stations:
        raise RuntimeError(f"Only {len(selected)} eligible DWD stations discovered, minimum {min_stations}")
    records=[];failures={}
    with ProcessPoolExecutor(max_workers=max(1,min(workers,4))) as pool:
        jobs={pool.submit(build_station,sid,listing,stations,archive):sid for sid in selected}
        for task in as_completed(jobs):
            sid=jobs[task]
            try:row=task.result()
            except Exception as error:
                failures[sid]="Processing error: "+str(error)[:300]
                print("DWD STATION FAILED",sid,repr(error),flush=True)
                continue
            if row.get("metrics"):
                (out/f"{sid}.json").write_text(json.dumps(row,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
                records.append({"id":sid,"name":row["name"],"state":row["state"],
                    "lat":row["lat"],"lon":row["lon"],
                    "metrics":list(row["metrics"]),
                    "periods":{key:value["period"] for key,value in row["metrics"].items()}})
            else:
                failures[sid]=row.get("unavailable_sources",{})
            print("DWD VERIFIED STATION PROGRESS",len(records),"/",len(selected),flush=True)
    records.sort(key=lambda x:(x["state"],x["name"],x["id"]))
    if shard_index is not None:
        manifest={"schema":1,"shard_index":shard_index,"shard_count":shard_count,
             "candidate_hash":hashlib.sha256(",".join(all_ids).encode()).hexdigest(),
             "candidate_count":len(all_ids),"attempted":selected,
             "accepted":[r["id"] for r in records],"excluded":failures}
        (out/"_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
        print("DWD HOURLY SHARD VERIFIED",shard_index,len(records),"of",len(selected),flush=True)
        return manifest
    if len(records)<min_stations or not set(pinned).issubset({x["id"] for x in records}):
        raise RuntimeError(f"Only {len(records)} verified DWD hourly stations or prior validated stations lost; publication blocked")
    result={"schema":1,"ready":True,"publisher":"Deutscher Wetterdienst (DWD) CDC",
       "method":"Exact original hourly time pairs, nonoverlapping top events, gap-safe",
       "generated_at":now.isoformat(),"stations":records,
       "note":"Every eligible DWD hourly station with original measured pairs: archived, active and variable-specific. Station-specific coverage and missing data apply; no nationwide-record claim."}
    (out/"index.json").write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print("DWD HOURLY RECORDS",len(records),"verified stations",flush=True)
    return result

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,default=Path("data/rekordlabor/weather_turns"))
    ap.add_argument("--target-stations",type=int,default=0,help="0 = every archived DWD station")
    ap.add_argument("--min-stations",type=int,default=0)
    ap.add_argument("--workers",type=int,default=3)
    ap.add_argument("--shard-index",type=int)
    ap.add_argument("--shard-count",type=int,default=1)
    ap.add_argument("--cache-dir",type=Path)
    args=ap.parse_args()
    build(args.out,args.target_stations,args.min_stations,args.workers,
          args.shard_index,args.shard_count,args.cache_dir)
