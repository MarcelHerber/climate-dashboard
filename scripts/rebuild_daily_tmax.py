from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

from dwd_common import atomic_write_json, download, read_json
from update_station_records import (
    HISTORICAL_PATTERN, HISTORICAL_URL, METADATA_URL, RECENT_PATTERN, RECENT_URL,
    STATION_ID_PATTERN, download_station_zip, list_station_files, parse_metadata, parse_station_zip,
)


def rebuild_daily_tmax(root: Path, max_workers: int = 8) -> dict[str, Any]:
    target=root/"daily_tmax_1881_2026.json"
    existing=read_json(target)
    earliest=date.fromisoformat(existing[0]["date"]) if existing else date(1881,1,1)
    today=date.today(); current_year=today.year
    metadata=parse_metadata(download(METADATA_URL,timeout=120))
    historical=list_station_files(HISTORICAL_URL,HISTORICAL_PATTERN,minimum=500)
    recent=list_station_files(RECENT_URL,RECENT_PATTERN,minimum=300)
    jobs=[(HISTORICAL_URL,name,earliest,date(current_year-1,12,31),False) for name in historical]
    jobs += [(RECENT_URL,name,date(current_year,1,1),today,True) for name in recent]
    maxima:dict[date,tuple[float,str,str,bool]]={}
    counts:dict[date,int]=defaultdict(int)
    failures=[]

    def process(job):
        base,name,start,end,preliminary=job
        match=STATION_ID_PATTERN.search(name); station_id=match.group(1) if match else "00000"
        content=download_station_zip(base,name)
        return parse_station_zip(content,station_id,metadata,start,end,preliminary)

    print(f"Vollständiger Tagesmaxima-Neuaufbau: {len(jobs)} Stationsarchive")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures={executor.submit(process,job):job[1] for job in jobs}
        for number,future in enumerate(as_completed(futures),start=1):
            name=futures[future]
            try:
                for observation in future.result():
                    value=observation.values.get("txk_high")
                    if value is None: continue
                    counts[observation.day]+=1
                    previous=maxima.get(observation.day)
                    candidate=(float(value),observation.station_id,observation.metadata_key,observation.preliminary)
                    if previous is None or candidate[0]>previous[0] or (candidate[0]==previous[0] and candidate[1]<previous[1]):
                        maxima[observation.day]=candidate
            except Exception as exc:
                failures.append(f"{name}: {exc}")
            if number%100==0 or number==len(futures): print(f"  verarbeitet: {number}/{len(futures)}")
    if failures:
        raise RuntimeError(f"{len(failures)} Archive konnten nicht verarbeitet werden; erster Fehler: {failures[0]}")

    existing_by_date={date.fromisoformat(item["date"]):item for item in existing}
    all_days=sorted(set(existing_by_date)|set(maxima))
    raw=[]
    for day in all_days:
        if day<earliest or day>today: continue
        if day in maxima:
            value,station_id,metadata_key,preliminary=maxima[day]
            segment=metadata.segment_for(station_id,day)
            raw.append({"date":day.isoformat(),"tmax":value,"station_id":station_id,"station_name":segment.name,
                        "station_state":None if segment.state=="__Unbekannt__" else segment.state,
                        "station_height":segment.height,"station_latitude":segment.latitude,"station_longitude":segment.longitude,
                        "station_count":counts.get(day),"preliminary":bool(preliminary)})
        else:
            raw.append({**existing_by_date[day]})
    normals:dict[str,list[float]]=defaultdict(list)
    for item in raw:
        year=int(item["date"][:4])
        if 1991<=year<=2020: normals[item["date"][5:]].append(float(item["tmax"]))
    means={key:sum(values)/len(values) for key,values in normals.items() if values}
    for item in raw:
        item["climate_mean"]=means.get(item["date"][5:],item.get("climate_mean"))
    atomic_write_json(target,raw)
    return {"records":len(raw),"latest_date":raw[-1]["date"],"archives":len(jobs),"days_with_station_metadata":sum(1 for item in raw if item.get("station_id"))}


def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument("--workers",type=int,default=8)
    args=parser.parse_args();print(json.dumps(rebuild_daily_tmax(args.root,args.workers),ensure_ascii=False,indent=2));return 0
if __name__=="__main__": raise SystemExit(main())
