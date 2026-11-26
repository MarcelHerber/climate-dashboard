#!/usr/bin/env python3
"""Annual within-station temperature range from original DWD KL observations."""
from __future__ import annotations
import argparse, calendar, json, math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from update_station_records import (
    HISTORICAL_URL,HISTORICAL_PATTERN,RECENT_URL,RECENT_PATTERN,METADATA_URL,
    STATION_ID_PATTERN,STATE_ORDER,download,list_station_files,download_station_zip,
    parse_metadata,parse_station_zip,atomic_write_json_compact,NoUsableProductFileError,
)
OUT=Path("data/dwd_annual_temperature_range.json")

def summarize(sid, days, cutoff, metadata):
    by_year=defaultdict(list)
    for day,(tn,tx,pre) in sorted(days.items()):
        if day<=cutoff and tn is not None and tx is not None and tn<=tx:
            by_year[day.year].append((day,tn,tx,pre))
    rows=[]
    for year, values in sorted(by_year.items()):
        start=date(year,1,1)
        end=min(date(year,12,31),cutoff)
        expected=(end-start).days+1
        counts=defaultdict(int)
        for day,*_ in values: counts[day.month]+=1
        good=len(values)>=math.ceil(.95*expected) and all(
            counts[m]>=math.ceil(.8*(end.day if m==end.month else calendar.monthrange(year,m)[1]))
            for m in range(1,end.month+1))
        low=min(values,key=lambda v:(v[1],v[0]))
        high=min(values,key=lambda v:(-v[2],v[0]))
        seg=metadata.segment_for(sid,high[0])
        lowseg=metadata.segment_for(sid,low[0])
        state=seg.state if seg.state in STATE_ORDER and seg.state==lowseg.state else None
        rows.append([year,sid,round(high[2]-low[1],1),low[1],high[2],low[0].isoformat(),high[0].isoformat(),len(values),expected,good,year==datetime.now(timezone.utc).year or any(v[3] for v in values),state,seg.name,seg.latitude,seg.longitude,seg.height])
    return rows

def build(out, workers, recent_only):
    today=datetime.now(timezone.utc).date()
    prev=json.loads(out.read_text()) if recent_only and out.exists() else None
    if prev and (prev.get("version")!=1 or prev.get("year")!=today.year): prev=None
    meta=parse_metadata(download(METADATA_URL,timeout=90))
    sources=[(RECENT_URL,RECENT_PATTERN,300,True)]
    if not prev: sources.insert(0,(HISTORICAL_URL,HISTORICAL_PATTERN,500,False))
    files=defaultdict(list)
    for url,pattern,minimum,pre in sources:
        for name in list_station_files(url,pattern,minimum=minimum):
            match=STATION_ID_PATTERN.search(name)
            if match: files[match.group(1)].append((url,name,pre))
    start=date(today.year,1,1) if prev else date(1700,1,1)
    def load(item):
        sid,entries=item
        days={}
        for url,name,pre in entries:
            try:
                obs=parse_station_zip(download_station_zip(url,name),sid,meta,start,today,pre)
            except NoUsableProductFileError:
                continue
            for o in obs:
                tn=o.values.get("tnk_low"); tx=o.values.get("txk_high")
                # Prefer historical observations on overlapping dates, fill missing fields from recent.
                old=days.get(o.day)
                if old:
                    tn=old[0] if old[0] is not None else tn
                    tx=old[1] if old[1] is not None else tx
                    preflag=old[2] or (pre and (old[0] is None or old[1] is None))
                else: preflag=pre
                days[o.day]=(tn,tx,preflag)
        return sid,days
    # Keep only compact summaries in memory; current-year observations are held
    # until the common data cutoff is known.
    oldrows=[] if not prev else [r for r in prev["rows"] if r[0]<today.year]
    current={}; errors=[]; latest=None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending={pool.submit(load,item):item[0] for item in files.items()}
        for i,f in enumerate(as_completed(pending),1):
            try:
                sid,days=f.result()
                historic={d:v for d,v in days.items() if d.year<today.year}
                oldrows.extend(summarize(sid,historic,date(today.year-1,12,31),meta))
                now={d:v for d,v in days.items() if d.year==today.year and v[0] is not None and v[1] is not None and v[0]<=v[1]}
                if now:
                    current[sid]=now
                    latest=max(latest or min(now),max(now))
            except Exception as exc: errors.append(f"{pending[f]}: {exc}")
            if i%100==0: print(f"{i}/{len(files)} Stationen, {len(errors)} Fehler",flush=True)
    if errors: raise RuntimeError(f"{len(errors)} Stationsdownloads fehlgeschlagen; bisheriges Archiv bleibt unverändert: {errors[:10]}")
    if not latest or len(current)<100: raise RuntimeError("Zu wenige aktuelle Stationen")
    rows=oldrows
    for sid,days in current.items(): rows.extend(summarize(sid,days,latest,meta))
    rows.sort(key=lambda r:(r[0],r[1]))
    if not rows or not any(r[9] and r[0]<today.year for r in rows): raise RuntimeError("Historische Daten fehlen")
    if len({(r[0],r[1]) for r in rows})!=len(rows): raise RuntimeError("Doppelte Stationsjahre")
    atomic_write_json_compact(out,{"version":1,"year":today.year,"through":latest.isoformat(),"states":STATE_ORDER,"columns":["year","id","range","tmin","tmax","min_date","max_date","valid","expected","eligible","preliminary","state","name","lat","lon","height"],"rows":rows,"source":"DWD CDC KL TXK/TNK historical + recent"})
    print(f"{len(rows)} Stationsjahre, {len(files)} Stations-IDs, Stand {latest}",flush=True)

def selftest():
    from types import SimpleNamespace
    class Meta:
        def segment_for(self,sid,day): return SimpleNamespace(state="Hessen",name="Test",latitude=50,longitude=8,height=100)
    days={date(2024,1,1)+timedelta(days=i):(-2,10,False) for i in range(366)}
    days[date(2024,1,11)]=(-11.2,0,False);days[date(2024,6,26)]=(15,38.8,False)
    r=summarize("00001",days,date(2024,12,31),Meta())[0]
    assert r[2]==50 and r[5]=="2024-01-11" and r[6]=="2024-06-26" and r[9] and r[7]==366
    assert not summarize("00001",{date(2024,1,1):(-10,30,False)},date(2024,12,31),Meta())[0][9]
    print("Selftest OK")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=OUT);p.add_argument("--workers",type=int,default=8);p.add_argument("--recent-only",action="store_true");p.add_argument("--selftest",action="store_true");a=p.parse_args()
    if a.selftest: selftest()
    else: build(a.output,a.workers,a.recent_only)
