#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, io, json, math, zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from update_station_records import (
    HISTORICAL_PATTERN, HISTORICAL_URL, METADATA_URL,
    RECENT_PATTERN, RECENT_URL, STATE_ORDER, STATION_ID_PATTERN,
    MetadataIndex, Observation, download, iter_downloaded_observations,
    list_station_files, parse_metadata,
)

VERSION = 2
START_YEAR = 1881
AREAS = ["Deutschland", *STATE_ORDER]
HOLIDAYS = ["easter", "christmas"]
MIN_GUST_KMH = 75.0

METRICS = {
    "tnn": {"label":"Kälteste Nacht · TNn","unit":"°C","direction":"asc","kind":"extreme","source":"DWD daily/kl · TNK"},
    "txx": {"label":"Wärmster Tag · TXx","unit":"°C","direction":"desc","kind":"extreme","source":"DWD daily/kl · TXK"},
    "txn": {"label":"Kältester Tag · TXn","unit":"°C","direction":"asc","kind":"extreme","source":"DWD daily/kl · TXK"},
    "rr24x": {"label":"Nassester Tag · RR24x","unit":"mm","direction":"desc","kind":"extreme","source":"DWD daily/kl · RSK"},
    "dry": {"label":"Gänzlich trocken","unit":"","direction":"desc","kind":"boolean","source":"DWD daily/kl · RSK"},
    "snow_high": {"label":"Max. Schneehöhe · höhere Lagen","unit":"cm","direction":"desc","kind":"extreme","source":"DWD daily/kl · SHK_TAG"},
    "snow_low": {"label":"Max. Schneehöhe · tiefere Lagen","unit":"cm","direction":"desc","kind":"extreme","source":"DWD daily/kl · SHK_TAG"},
    "gust": {"label":"Max. Windböe · ab 75 km/h","unit":"km/h","direction":"desc","kind":"extreme","source":"DWD daily/kl · FX"},
    "sun_sdn": {"label":"SDn","unit":"h","direction":"asc","kind":"supporting","source":"DWD daily/kl · SDK"},
    "sun_sdx": {"label":"SDx","unit":"h","direction":"desc","kind":"supporting","source":"DWD daily/kl · SDK"},
    "sun_sum": {"label":"Sonnenschein · SDn + SDx","unit":"h","direction":"both","kind":"derived","source":"DWD daily/kl · SDK"},
    "holiday_temp_mean": {"label":"Feiertagsmittel · TNn + TXx","unit":"°C","direction":"both","kind":"derived","source":"DWD daily/kl · TNK/TXK"},
    "rr_sum": {"label":"Niederschlagssumme · tägliches RR24x","unit":"mm","direction":"desc","kind":"derived","source":"DWD daily/kl · RSK"},
    "snow_high_present": {"label":"Schnee in höheren Lagen","unit":"","direction":"desc","kind":"boolean","source":"DWD daily/kl · SHK_TAG"},
    "snow_low_present": {"label":"Schnee in tieferen Lagen","unit":"","direction":"desc","kind":"boolean","source":"DWD daily/kl · SHK_TAG"},
}

HOLIDAY_META = {
    "easter": {
        "label":"Ostern", "rule":"Karfreitag bis Ostermontag", "days":4,
        "total_period":"easter_total", "snow_height_split_m":800,
        "periods":[
            {"id":"easter_total","label":"Ostern gesamt","kind":"total"},
            {"id":"good_friday","label":"Karfreitag","kind":"day"},
            {"id":"holy_saturday","label":"Karsamstag","kind":"day"},
            {"id":"easter_sunday","label":"Ostersonntag","kind":"day"},
            {"id":"easter_monday","label":"Ostermontag","kind":"day"},
        ],
        "day_metrics":["tnn","txx","txn","rr24x","dry","snow_high","snow_low","sun_sum","gust"],
        "total_metrics":["holiday_temp_mean","tnn","txx","txn","rr_sum","dry","snow_high","snow_low","sun_sum","gust"],
    },
    "christmas": {
        "label":"Weihnachten", "rule":"24. bis 26. Dezember", "days":3,
        "total_period":"christmas_total", "snow_height_split_m":400,
        "periods":[
            {"id":"christmas_total","label":"Weihnachten gesamt","kind":"total"},
            {"id":"christmas_eve","label":"Heiligabend","kind":"day"},
            {"id":"christmas_day","label":"1. Weihnachtstag","kind":"day"},
            {"id":"second_christmas_day","label":"2. Weihnachtstag","kind":"day"},
        ],
        "day_metrics":["tnn","txx","txn","snow_high","snow_low","gust","snow_high_present","snow_low_present"],
        "total_metrics":["holiday_temp_mean","tnn","txx","txn","snow_high","snow_low","gust","snow_high_present","snow_low_present"],
        "snow_probability_reference_periods":[{"from":1961,"to":1990},{"from":1981,"to":2010},{"from":1991,"to":2020}],
    },
}
DAY_PERIOD_IDS = {
    "easter":["good_friday","holy_saturday","easter_sunday","easter_monday"],
    "christmas":["christmas_eve","christmas_day","second_christmas_day"],
}


def easter_sunday(year:int)->date:
    a=year%19; b=year//100; c=year%100; d=b//4; e=b%4; f=(b+8)//25
    g=(b-f+1)//3; h=(19*a+b-d-g+15)%30; i=c//4; k=c%4
    l=(32+2*e+2*i-h-k)%7; m=(a+11*h+22*l)//451
    month=(h+l-7*m+114)//31; day=((h+l-7*m+114)%31)+1
    return date(year,month,day)

@lru_cache(maxsize=None)
def holiday_day_lookup(year:int)->dict[date,tuple[str,str]]:
    es=easter_sunday(year)
    return {
        es-timedelta(days=2):("easter","good_friday"),
        es-timedelta(days=1):("easter","holy_saturday"),
        es:("easter","easter_sunday"),
        es+timedelta(days=1):("easter","easter_monday"),
        date(year,12,24):("christmas","christmas_eve"),
        date(year,12,25):("christmas","christmas_day"),
        date(year,12,26):("christmas","second_christmas_day"),
    }

@lru_cache(maxsize=None)
def holiday_stamp_lookup(start_year:int,end_year:int)->set[str]:
    return {d.strftime("%Y%m%d") for y in range(start_year,end_year+1) for d in holiday_day_lookup(y)}

def decode_product(data:bytes)->str:
    for enc in ("utf-8","cp1252","latin-1"):
        try: text=data.decode(enc)
        except UnicodeDecodeError: continue
        if "MESS_DATUM" in text: return text
    return data.decode("latin-1",errors="replace")

def parse_float(raw:Any)->float|None:
    if raw is None:return None
    try:v=float(str(raw).strip().replace(",","."))
    except ValueError:return None
    return v if math.isfinite(v) else None


def parse_holiday_kl_zip(content:bytes,station_id_hint:str,metadata:MetadataIndex,start_date:date,end_date:date,preliminary:bool)->list[Observation]:
    out:list[Observation]=[]; wanted=holiday_stamp_lookup(start_date.year,end_date.year)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        product=None
        for name in archive.namelist():
            if not name.lower().endswith(".txt") or "produkt" not in name.lower():continue
            try: header=archive.read(name).splitlines()[0].decode("latin-1",errors="replace")
            except (KeyError,IndexError):continue
            cols={x.strip().upper() for x in header.split(";")}
            if {"STATIONS_ID","MESS_DATUM","TXK","TNK"}.issubset(cols):product=name;break
        if product is None:return out
        for raw in csv.DictReader(io.StringIO(decode_product(archive.read(product))),delimiter=";"):
            row={(k or "").strip().upper():(v.strip() if isinstance(v,str) else v) for k,v in raw.items()}
            stamp=str(row.get("MESS_DATUM") or "").strip()
            if stamp not in wanted:continue
            try:day=datetime.strptime(stamp,"%Y%m%d").date()
            except ValueError:continue
            if not(start_date<=day<=end_date):continue
            sid=str(row.get("STATIONS_ID") or "").strip().zfill(5) or station_id_hint
            seg=metadata.segment_for(sid,day); values:dict[str,float]={}
            tx=parse_float(row.get("TXK")); tn=parse_float(row.get("TNK")); rr=parse_float(row.get("RSK"))
            snow=parse_float(row.get("SHK_TAG") if "SHK_TAG" in row else row.get("SHK")); sun=parse_float(row.get("SDK"))
            fx=parse_float(row.get("FX") if "FX" in row else row.get("FXK"))
            if tx is not None and -60<=tx<=60:values["txk"]=round(tx,1)
            if tn is not None and -60<=tn<=60:values["tnk"]=round(tn,1)
            if rr is not None and 0<=rr<=1000:values["rsk"]=round(rr,1)
            if snow is not None and 0<=snow<=2000:values["snow"]=round(snow,1)
            if sun is not None and 0<=sun<=24:values["sdk"]=round(sun,1)
            if fx is not None and 0<=fx<=120:values["fx_kmh"]=round(fx*3.6,1)
            if seg.height is not None:values["height_m"]=float(seg.height)
            if values:out.append(Observation(day,seg.key,seg.state,sid,values,preliminary))
    return out


def entry(value:float|int,day:date,key:str|None,pre:bool,decimals:int=1)->list[Any]:
    val=int(value) if isinstance(value,int) else round(float(value),decimals)
    return [val,day.isoformat(),key,1 if pre else 0]

def better(metric:str,new:list[Any],old:list[Any])->bool:
    direction=METRICS[metric]["direction"]; nv=float(new[0]); ov=float(old[0])
    if nv!=ov:return nv>ov if direction=="desc" else nv<ov
    if str(new[1])!=str(old[1]):return str(new[1])<str(old[1])
    return str(new[2] or "")<str(old[2] or "")

def best(metric:str,items:list[list[Any]])->list[Any]|None:
    chosen=None
    for x in items:
        if chosen is None or better(metric,x,chosen):chosen=x
    return chosen


class HolidayAccumulator:
    def __init__(self)->None:
        self.daily=defaultdict(lambda:defaultdict(lambda:defaultdict(lambda:defaultdict(dict))))
        self.observations=0; self.first_day=None; self.last_day=None
    @staticmethod
    def areas(state:str)->list[str]:
        return ["Deutschland"]+([state] if state in STATE_ORDER else [])
    @staticmethod
    def update(bucket:dict[str,list[Any]],metric:str,e:list[Any])->None:
        if metric not in bucket or better(metric,e,bucket[metric]):bucket[metric]=e
    def add(self,o:Observation)->None:
        info=holiday_day_lookup(o.day.year).get(o.day)
        if o.day.year<START_YEAR or info is None:return
        holiday,period=info; split=int(HOLIDAY_META[holiday]["snow_height_split_m"]); v=o.values
        for area in self.areas(o.state):
            b=self.daily[area][holiday][o.day.year][period]
            if "tnk" in v:self.update(b,"tnn",entry(v["tnk"],o.day,o.metadata_key,o.preliminary))
            if "txk" in v:
                e=entry(v["txk"],o.day,o.metadata_key,o.preliminary); self.update(b,"txx",e); self.update(b,"txn",e)
            if "rsk" in v:self.update(b,"rr24x",entry(v["rsk"],o.day,o.metadata_key,o.preliminary))
            if "snow" in v and "height_m" in v:
                m="snow_high" if v["height_m"]>=split else "snow_low"; self.update(b,m,entry(v["snow"],o.day,o.metadata_key,o.preliminary))
            if v.get("fx_kmh",0)>=MIN_GUST_KMH:self.update(b,"gust",entry(v["fx_kmh"],o.day,o.metadata_key,o.preliminary))
            if holiday=="easter" and "sdk" in v:
                e=entry(v["sdk"],o.day,o.metadata_key,o.preliminary); self.update(b,"sun_sdn",e); self.update(b,"sun_sdx",e)
        self.observations+=1; self.first_day=o.day if self.first_day is None else min(self.first_day,o.day); self.last_day=o.day if self.last_day is None else max(self.last_day,o.day)
    @staticmethod
    def finish_day(raw:dict[str,list[Any]],holiday:str,day:date)->dict[str,Any]:
        row={m:raw.get(m) for m in METRICS}; rr=raw.get("rr24x")
        if rr is not None:row["dry"]=entry(1 if float(rr[0])==0 else 0,day,None,bool(rr[3]),0)
        for sm,pm in (("snow_high","snow_high_present"),("snow_low","snow_low_present")):
            s=raw.get(sm)
            if s is not None:row[pm]=entry(1 if float(s[0])>0 else 0,day,None,bool(s[3]),0)
        if holiday=="easter" and raw.get("sun_sdn") is not None and raw.get("sun_sdx") is not None:
            a,b=raw["sun_sdn"],raw["sun_sdx"]; row["sun_sum"]=entry(float(a[0])+float(b[0]),day,None,bool(a[3] or b[3]))
        return row
    @staticmethod
    def finish_total(holiday:str,rows:list[dict[str,Any]],day:date)->dict[str,Any]:
        out={m:None for m in METRICS}
        for m in ("tnn","txx","txn","snow_high","snow_low","gust"):
            xs=[r[m] for r in rows if r.get(m) is not None]
            if xs:out[m]=best(m,xs)
        if all(r.get("tnn") is not None and r.get("txx") is not None for r in rows):
            xs=[float(r[m][0]) for r in rows for m in ("tnn","txx")]; pre=any(bool(r[m][3]) for r in rows for m in ("tnn","txx")); out["holiday_temp_mean"]=entry(sum(xs)/len(xs),day,None,pre)
        if holiday=="easter":
            rrs=[r.get("rr24x") for r in rows]
            if all(x is not None for x in rrs):
                total=sum(float(x[0]) for x in rrs); pre=any(bool(x[3]) for x in rrs); out["rr_sum"]=entry(total,day,None,pre); out["dry"]=entry(1 if total==0 else 0,day,None,pre,0)
            suns=[r.get("sun_sum") for r in rows]
            if all(x is not None for x in suns):out["sun_sum"]=entry(sum(float(x[0]) for x in suns),day,None,any(bool(x[3]) for x in suns))
        for sm,pm in (("snow_high","snow_high_present"),("snow_low","snow_low_present")):
            xs=[r.get(sm) for r in rows]
            if any(x is not None and float(x[0])>0 for x in xs):out[pm]=entry(1,day,None,any(bool(x[3]) for x in xs if x is not None),0)
            elif all(x is not None for x in xs):out[pm]=entry(0,day,None,any(bool(x[3]) for x in xs),0)
        return out
    def period_records(self,end_year:int)->dict[str,Any]:
        result={}
        for area in AREAS:
            result[area]={}
            for holiday in HOLIDAYS:
                result[area][holiday]={p["id"]:{} for p in HOLIDAY_META[holiday]["periods"]}
                for year in range(START_YEAR,end_year+1):
                    day_rows={}; dates={}
                    for d,(h,p) in holiday_day_lookup(year).items():
                        if h!=holiday:continue
                        raw=self.daily.get(area,{}).get(holiday,{}).get(year,{}).get(p,{})
                        day_rows[p]=self.finish_day(raw,holiday,d); dates[p]=d; result[area][holiday][p][str(year)]=day_rows[p]
                    ids=DAY_PERIOD_IDS[holiday]; total=HOLIDAY_META[holiday]["total_period"]
                    result[area][holiday][total][str(year)]=self.finish_total(holiday,[day_rows[p] for p in ids],max(dates.values()))
        return result


def compatibility_records(pr:dict[str,Any],end_year:int)->dict[str,Any]:
    out={}
    for area in AREAS:
        out[area]={}
        for holiday in HOLIDAYS:
            total=HOLIDAY_META[holiday]["total_period"]; out[area][holiday]={}
            for y in range(START_YEAR,end_year+1):
                r=pr[area][holiday][total][str(y)]; out[area][holiday][str(y)]={"tnn":r.get("tnn"),"txx":r.get("txx")}
    return out

def consume(acc:HolidayAccumulator,meta:MetadataIndex,names:list[str],url:str,start:date,end:date,pre:bool,workers:int)->int:
    before=acc.observations
    for observations in iter_downloaded_observations(names,url,meta,start,end,pre,workers,station_pattern=STATION_ID_PATTERN,parser=parse_holiday_kl_zip,failure_tolerance=0.02):
        for o in observations:acc.add(o)
    return acc.observations-before

def referenced_keys(part:Any,target:set[str])->None:
    if isinstance(part,dict):
        for v in part.values():referenced_keys(v,target)
    elif isinstance(part,list):
        if len(part)==4 and isinstance(part[2],str) and ":" in part[2]:target.add(part[2])
        else:
            for v in part:referenced_keys(v,target)

def selected_stations(meta:MetadataIndex,*parts:dict[str,Any])->dict[str,Any]:
    keys:set[str]=set()
    for p in parts:referenced_keys(p,keys)
    public=meta.public_dict(); return {k:public[k] for k in sorted(keys) if k in public}

def first_year(years:dict[str,Any])->int|None:
    found=[]
    for y,row in years.items():
        if isinstance(row,dict) and any(v is not None for v in row.values()):
            try:found.append(int(y))
            except ValueError:pass
    return min(found) if found else None

def area_starts(records:dict[str,Any])->dict[str,Any]:
    return {a:{h:first_year(records.get(a,{}).get(h,{})) for h in HOLIDAYS} for a in AREAS}

def period_starts(pr:dict[str,Any])->dict[str,Any]:
    return {a:{h:{p["id"]:first_year(pr.get(a,{}).get(h,{}).get(p["id"],{})) for p in HOLIDAY_META[h]["periods"]} for h in HOLIDAYS} for a in AREAS}

def holiday_dates(end_year:int)->dict[str,Any]:
    out={}
    for y in range(START_YEAR,end_year+1):
        es=easter_sunday(y); out[str(y)]={
            "easter":{"from":(es-timedelta(days=2)).isoformat(),"to":(es+timedelta(days=1)).isoformat(),"good_friday":(es-timedelta(days=2)).isoformat(),"holy_saturday":(es-timedelta(days=1)).isoformat(),"easter_sunday":es.isoformat(),"easter_monday":(es+timedelta(days=1)).isoformat()},
            "christmas":{"from":date(y,12,24).isoformat(),"to":date(y,12,26).isoformat(),"christmas_eve":date(y,12,24).isoformat(),"christmas_day":date(y,12,25).isoformat(),"second_christmas_day":date(y,12,26).isoformat()},
        }
    return out


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output",default="data/dwd_holiday_extremes.json"); ap.add_argument("--max-workers",type=int,default=10); args=ap.parse_args()
    output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True); today=datetime.now(timezone.utc).date(); start=date(START_YEAR,1,1)
    print("=== DWD FEIERTAGS-EXTREMWERTE · DATENBASIS V2 ===",flush=True)
    print("Gebiete: Deutschland + 16 Bundesländer",flush=True); print(f"Jahre: {START_YEAR} bis {today.year}",flush=True)
    print("Ostern: gesamt + Karfreitag + Karsamstag + Ostersonntag + Ostermontag",flush=True)
    print("Weihnachten: gesamt + Heiligabend + 1. + 2. Weihnachtstag",flush=True)
    print("Vorlagen-Parameter: TNn, TXx, TXn, RR/trocken, Schnee, Sonnenschein, Windböe + Gesamtwerte",flush=True)
    print("Schneehöhen-Grenzen wie Vorlage: Ostern 800 m · Weihnachten 400 m",flush=True)
    meta=parse_metadata(download(METADATA_URL,timeout=90)); hist=list_station_files(HISTORICAL_URL,HISTORICAL_PATTERN,minimum=500); recent=list_station_files(RECENT_URL,RECENT_PATTERN,minimum=300)
    print(f"KL historical: {len(hist):,}",flush=True); print(f"KL recent:     {len(recent):,}",flush=True)
    acc=HolidayAccumulator(); n=consume(acc,meta,hist,HISTORICAL_URL,start,today,False,args.max_workers); print(f"Feiertags-Beobachtungen historical: {n:,}",flush=True)
    n=consume(acc,meta,recent,RECENT_URL,date(max(START_YEAR,today.year-2),1,1),today,True,args.max_workers); print(f"Feiertags-Beobachtungen recent:     {n:,}",flush=True)
    pr=acc.period_records(today.year); records=compatibility_records(pr,today.year); stations=selected_stations(meta,records,pr)
    payload={
        "version":VERSION,"generated_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"project":"Feiertags-Extremwerte","source":"DWD CDC observations_germany/climate/daily/kl","template_reference":"Extremwerte_Baden-Württemberg.xlsx · Blätter Ostern und Weihnachten","areas":AREAS,"start_year":START_YEAR,"end_year":today.year,"run_date":today.isoformat(),"holidays":HOLIDAY_META,"metrics":METRICS,"entry_schema":["value","date","metadata_key","preliminary"],"area_start_years":area_starts(records),"period_start_years":period_starts(pr),"holiday_dates":holiday_dates(today.year),"stations":stations,"records":records,"period_records":pr,
        "stats":{"holiday_observations":acc.observations,"referenced_stations":len(stations),"first_holiday_observation":acc.first_day.isoformat() if acc.first_day else None,"last_holiday_observation":acc.last_day.isoformat() if acc.last_day else None},
        "method_note":"Parameter nach der bereitgestellten Feiertags-Vorlage. Ostern wird jetzt inklusive Karsamstag als Karfreitag bis Ostermontag sowie für alle vier Einzeltage gespeichert; Weihnachten gesamt plus 24., 25. und 26. Dezember. Ostern nutzt die Schneehöhen-Grenze 800 m, Weihnachten 400 m. Der Gesamt-Temperaturwert ist das Mittel aus Gebiet-TNn und Gebiet-TXx aller enthaltenen Tage; der Oster-Niederschlagswert ist die Summe der täglichen gebietsweiten RR24x-Werte."
    }
    output.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    assert len(AREAS)==17 and set(HOLIDAYS)=={"easter","christmas"}; assert easter_sunday(2026)==date(2026,4,5); assert payload["holiday_dates"]["2026"]["easter"]["holy_saturday"]=="2026-04-04"; assert acc.observations>0
    print("Feiertags-Datenbasis V2 erfolgreich gebaut.",flush=True); print(f"Feiertags-Beobachtungen: {acc.observations:,}",flush=True); print(f"Referenzierte Stationen: {len(stations):,}",flush=True); print(f"Ausgabe: {output} ({output.stat().st_size/1024/1024:.2f} MB)",flush=True); return 0

if __name__=="__main__":raise SystemExit(main())
