#!/usr/bin/env python3
"""Supplemental annual DWD records. Separate from legacy 11-metric dataset."""
from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import math
import zipfile
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import update_station_records as dwd
import build_dwd_annual_tropical_nights as tu

AREAS = ["Deutschland", *dwd.STATE_ORDER]
START = date(1800, 1, 1)
METRICS = {}
RULES = defaultdict(list)

def metric(key, label, unit, group, source, kind="extreme", direction="desc", **extra):
    METRICS[key] = dict(label=label, description=extra.pop("description", label),
                        unit=unit, group=group, source=source, kind=kind,
                        direction=direction, **extra)

def threshold(field, key, label, op, limit, group, source, kind="count", suffix=""):
    metric(key, label, "Nächte" if field=="night" else "Tage", group, source,
           "station_year_count" if kind=="count" else "station_year_series",
           threshold=f"{field} {op} {limit}", description=label+"; "+field+" "+op+" "+str(limit))
    RULES[field].append((key, op, limit, kind, suffix))

KL="DWD daily/kl"
RR="DWD daily/more_precip · RS"
TU="DWD hourly/air_temperature · TT_TU (18–06 UTC, 13 Stundenwerte)"
for key,label,op,limit in [
    ("frost_days_max","Frosttage","<",0),("moderate_frost_days_max","Mind. mäßiger Frost","<=",-5),
    ("severe_frost_days_max","Mind. strenger Frost","<=",-10),("very_severe_frost_days_max","Frost ≤ −15 °C","<=",-15),
    ("extreme_frost_days_max","Frost ≤ −20 °C","<=",-20)]:
    threshold("TNK",key,label,op,limit,"cold",KL)
threshold("TXK","ice_days_max","Eistage","<",0,"cold",KL)
threshold("TXK","severe_ice_days_max","Eistage ≤ −5 °C","<=",-5,"cold",KL)
for limit in (1,10,20,50):
    threshold("RS",f"rain{limit}_days_max",f"Niederschlagstage ≥ {limit} mm",">=",limit,"rain",RR)
for suffix,level in (("ge_400","≥400 m"),("lt_400","<400 m")):
    for limit in (1,10,50):
        threshold("SHK",f"snow{limit}_days_{suffix}",f"Schneedeckentage ≥ {limit} cm · {level}",">=",limit,"snow",KL,suffix=suffix)
    threshold("SHK",f"snow_spell_{suffix}",f"Längste Schneedeckenperiode · {level}",">=",1,"spells",KL,"series",suffix)
    metric(f"snow_gain_{suffix}",f"Max. 24-h-Schneehöhenzuwachs · {level}","cm","snow",KL)
for field,key,label,op,limit,source in [
    ("TNK","frost_spell","Längste Frostserie","<",0,KL),("TXK","ice_spell","Längste Dauerfrostperiode","<",0,KL),
    ("TNK","severe_frost_spell","Längste strenge Frostserie","<=",-10,KL),
    ("TXK","summer_spell","Längste Sommerperiode",">=",25,KL),("TXK","heat_spell","Längste Hitzeperiode",">=",30,KL),
    ("night","tropical_spell","Längste Tropennachtserie",">=",20,TU),
    ("RS","wet_spell","Längste Niederschlagsperiode",">=",1,RR),("RS","dry_spell","Längste Trockenperiode","<",1,RR)]:
    threshold(field,key,label,op,limit,"spells",source,"series")
for key,label,field,direction in [
    ("tnx","TNx · höchstes Tagesminimum","TNK","desc"),("txn","TXn · niedrigstes Tagesmaximum","TXK","asc"),
    ("tgx","TGx · höchstes Tagesmittel","TMK","desc"),("tgn","TGn · niedrigstes Tagesmittel","TMK","asc"),
    ("dtrx","DTRx · größte Tagesspanne","DTR","desc")]:
    metric(key,label,"K" if key=="dtrx" else "°C","absolute",KL+" · "+field,direction=direction)
for n,h in [(3,72),(7,168),(30,720)]:
    metric(f"rr{h}x",f"RR{h}x · {n}-Tage-Summe","mm","rain",RR)
for limit,label in [(75,"Sturmtage"),(89,"Schwere Sturmtage"),(104,"Orkanartige Sturmtage"),(118,"Orkantage")]:
    threshold("FX",f"wind{limit}_days_max",f"{label} ≥ {limit} km/h",">=",limit,"wind",KL+" · FX")

def passes(v,op,t):
    return v<t if op=="<" else v<=t if op=="<=" else v>=t

def number(raw,lo,hi):
    try:
        v=float(raw.strip().replace(",","."))
        return v if math.isfinite(v) and lo<=v<=hi else None
    except (ValueError,AttributeError):
        return None

def product_rows(blob, required):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if "produkt" not in name.lower() or not name.lower().endswith(".txt"):
                continue
            with z.open(name) as raw:
                reader=csv.reader(io.TextIOWrapper(raw,encoding="latin-1"),delimiter=";")
                header=[x.strip().upper() for x in next(reader,[])]
                if not set(required)<=set(header):
                    continue
                for row in reader:
                    if len(row)>=len(header):
                        yield dict(zip(header,row))
                return

def read_station(files, sid, family, today):
    # Verified historical values win, recent fills missing fields, not duplicate days.
    daily=defaultdict(dict)
    hours=defaultdict(dict)
    for base,name,pre in files:
        blob=dwd.download_station_zip(base,name)
        if family=="TU":
            for r in product_rows(blob,("MESS_DATUM","TT_TU")):
                raw=r["MESS_DATUM"].strip()
                try:
                    day=date(int(raw[:4]),int(raw[4:6]),int(raw[6:8]));hour=int(raw[8:10])
                except (ValueError,IndexError):
                    continue
                if not 0<=hour<=23: continue
                end=day+timedelta(days=1) if hour>=18 else day
                if not START<=end<=today or 6<hour<18: continue
                v=number(r["TT_TU"],-60,60)
                if v is not None:
                    hours[end].setdefault(hour,(v,pre))
            continue
        for r in product_rows(blob,("MESS_DATUM",)):
            raw=r["MESS_DATUM"].strip()
            try: day=date(int(raw[:4]),int(raw[4:6]),int(raw[6:8]))
            except (ValueError,IndexError): continue
            if not START<=day<=today: continue
            if family=="RR":
                fields={"RS":(r.get("RS"),0,1000)}
            else:
                fields={k:(r.get(k),-60,60) for k in ("TNK","TXK","TMK")}
                fields["SHK"]=(r.get("SHK_TAG",r.get("SHK")),0,2000)
                fields["FX"]=(r.get("FX",r.get("FXK")),0,120)
            for key,(rawval,lo,hi) in fields.items():
                val=number(rawval,lo,hi)
                if val is not None:
                    daily[day].setdefault(key,(val*3.6 if key=="FX" else val,pre))
    if family=="TU":
        for day,h in hours.items():
            if len(h)==13:
                daily[day]["night"]=(min(v for v,_ in h.values()),any(p for _,p in h.values()))
    return daily

def longest(items,op,limit):
    best=run=0; first=end=prev=None; best_start=best_end=None
    for day,val,_,_ in items:
        if passes(val,op,limit):
            if prev is None or (day-prev).days!=1 or run==0:
                run=0;first=day
            run+=1
            if run>best: best=run;best_start=first;best_end=day
        else: run=0
        prev=day
    return best,best_start,best_end

def rolling(items,n):
    q=deque();best=None
    for item in items:
        day,val,key,pre=item
        if q and (day-q[-1][0]).days!=1:q.clear()
        q.append(item)
        if len(q)>n:q.popleft()
        if len(q)==n:
            total=sum(x[1] for x in q)
            candidate=[round(total,1),day.isoformat(),key,int(any(x[3] for x in q)),q[0][0].isoformat()]
            if best is None or candidate[0]>best[0]:best=candidate
    return best

def expected_days(year,today):
    return ((min(today,date(year,12,31))-date(year,1,1)).days+1)

def count_eligible(n,year,today):
    return n>=math.ceil(.90*expected_days(year,today))

def station_records(daily,sid,family,metadata,today):
    # Group station-year by region. Germany is evaluated independently;
    # a move across a state border never splices regional records.
    groups=defaultdict(lambda:defaultdict(list))
    for day,fields in sorted(daily.items()):
        seg=metadata.segment_for(sid,day)
        key=family+":"+seg.key
        areas=["Deutschland"]+([seg.state] if seg.state in dwd.STATE_ORDER else [])
        for field,(v,pre) in fields.items():
            if field=="SHK":
                suffix="ge_400" if seg.height is not None and seg.height>=400 else "lt_400" if seg.height is not None else None
            else:suffix=None
            for area in areas:
                groups[(area,day.year)][field].append((day,v,key,pre,suffix))
        if "TNK" in fields and "TXK" in fields:
            lo,lp=fields["TNK"];hi,hp=fields["TXK"]
            if hi>=lo:
                for area in areas:
                    groups[(area,day.year)]["DTR"].append((day,hi-lo,key,lp or hp,None))
    for (area,year),fields in groups.items():
        def emit(key,entry):
            return (area,year,key,entry)
        for field,rules in RULES.items():
            raw=fields.get(field,[])
            for key,op,limit,kind,suffix in rules:
                items=[r[:4] for r in raw if not suffix or r[4]==suffix]
                if not items or not count_eligible(len(items),year,today):continue
                pre=int(year==today.year or any(r[3] for r in items))
                if kind=="count":
                    entry=[sum(passes(r[1],op,limit) for r in items),items[-1][2],pre,len(items),expected_days(year,today)]
                else:
                    val,start,end=longest(items,op,limit)
                    entry=[val,items[-1][2],pre,start.isoformat() if start else None,end.isoformat() if end else None,len(items),expected_days(year,today)]
                yield emit(key,entry)
        for key,field,direction in [("tnx","TNK","desc"),("txn","TXK","asc"),("tgx","TMK","desc"),("tgn","TMK","asc"),("dtrx","DTR","desc")]:
            items=fields.get(field,[])
            if items:
                day,val,meta,pre,_=(max if direction=="desc" else min)(items,key=lambda x:x[1])
                yield emit(key,[round(val,1),day.isoformat(),meta,int(pre or year==today.year)])
        rain=[r[:4] for r in fields.get("RS",[])]
        for n in (3,7,30):
            r=rolling(rain,n)
            if r:
                r[3]=int(r[3] or year==today.year)
                yield emit(f"rr{n*24}x",r)
        for suffix in ("ge_400","lt_400"):
            snow=[r[:4] for r in fields.get("SHK",[]) if r[4]==suffix]
            best=None
            for a,b in zip(snow,snow[1:]):
                if (b[0]-a[0]).days!=1:continue
                gain=round(b[1]-a[1],1)
                if gain>0 and (best is None or gain>best[0]):
                    best=[gain,b[0].isoformat(),b[2],int(a[3] or b[3] or year==today.year),a[0].isoformat()]
            if best:yield emit("snow_gain_"+suffix,best)

def family_files(base_hist,pat_hist,base_recent,pat_recent,station_pattern,minimum):
    by=defaultdict(list)
    for base,pat,pre in [(base_hist,pat_hist,False),(base_recent,pat_recent,True)]:
        for name in dwd.list_station_files(base,pat,minimum):
            match=station_pattern.search(name)
            if match:by[match.group(1)].append((base,name,pre))
    return by

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--family",choices=["KL","RR","TU"],required=True)
    p.add_argument("--workers",type=int,default=6)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    today=datetime.now(timezone.utc).date()-timedelta(days=1)
    family=args.family
    if family=="KL": module=dwd; prefix="";minimum=300
    elif family=="RR": module=dwd;prefix="RR_";minimum=500
    else:module=tu;prefix="";minimum=300
    get=lambda n:getattr(module,prefix+n)
    meta=dwd.parse_metadata(dwd.download(get("METADATA_URL"),timeout=90))
    files=family_files(get("HISTORICAL_URL"),get("HISTORICAL_PATTERN"),get("RECENT_URL"),get("RECENT_PATTERN"),get("STATION_ID_PATTERN"),minimum)
    records={a:{} for a in AREAS};used=set();maxday=None;minday=None;days=0;fail=[]
    def task(pair):
        sid,entries=pair
        daily=read_station(entries,sid,family,today)
        return list(station_records(daily,sid,family,meta,today)),min(daily,default=None),max(daily,default=None),len(daily)
    # Bounded batches prevent retaining all station-day records.
    pairs=sorted(files.items())
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for offset in range(0,len(pairs),args.workers*2):
            batch=pairs[offset:offset+args.workers*2]
            futures=[pool.submit(task,pair) for pair in batch]
            for pair,future in zip(batch,futures):
                try: result,first,last,n=future.result()
                except Exception as e:
                    fail.append(pair[0]);print("Station failed",pair[0],str(e),flush=True);continue
                if first:minday=min(minday or first,first);maxday=max(maxday or last,last);days+=n
                for area,year,key,entry in result:
                    row=records[area].setdefault(str(year),{})
                    old=row.get(key)
                    direction=METRICS[key]["direction"]
                    if old is None or (entry[0]>old[0] if direction=="desc" else entry[0]<old[0]):
                        row[key]=entry
            if offset% (args.workers*20)==0:print(f"{family}: {offset}/{len(pairs)} stations",flush=True)
    if fail or days<100000:
        raise RuntimeError(f"{family}: {len(fail)} failed stations; {days} station days; refusing incomplete publication")
    metrics={k:v for k,v in METRICS.items() if (v["source"].startswith("DWD hourly") if family=="TU" else v["source"].startswith(RR) if family=="RR" else v["source"].startswith(KL))}
    for years in records.values():
        for row in years.values():
            for key,entry in row.items():
                used.add(entry[2] if metrics[key]["kind"]=="extreme" else entry[1])
    if not all(any(k in row for row in records["Deutschland"].values()) for k in metrics):
        raise RuntimeError("Missing metric coverage")
    stations={family+":"+k:v for k,v in meta.public_dict().items() if family+":"+k in used}
    out=dict(version=1,family=family,areas=AREAS,metrics=metrics,records=records,stations=stations,
             data_start=minday.isoformat(),data_through=maxday.isoformat(),station_days=days,
             generated_at=datetime.now(timezone.utc).isoformat())
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(out,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
