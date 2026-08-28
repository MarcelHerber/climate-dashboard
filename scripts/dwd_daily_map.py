#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, gzip, json, math, re, tempfile
from pathlib import Path
from typing import Any, Mapping

REFERENCE_START=1991
REFERENCE_END=2020
REFERENCE_LABEL="1991–2020"
MIN_REFERENCE_YEARS=20
CACHE_VERSION=2
PAYLOAD_VERSION=1
STATES=("Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen")

def add_climatology_value(block:dict,mmdd:str,value:int)->None:
    slot=block.setdefault("clim_1991_2020",{}).setdefault(mmdd,[0,0])
    slot[0]+=int(value); slot[1]+=1

def climate_normal_tenths(block:Mapping[str,Any],mmdd:str):
    raw=(block.get("clim_1991_2020") or {}).get(mmdd)
    if not isinstance(raw,(list,tuple)) or len(raw)<2:return None,0
    total,count=int(raw[0]),int(raw[1])
    return (int(round(total/count)),count) if count>=MIN_REFERENCE_YEARS else (None,count)

def record_status(element,current,record):
    if current is None or not record:return 0
    previous=int(record[0])
    if element=="TMAX":return 1 if current>previous else 2 if current==previous else 0
    return 1 if current<previous else 2 if current==previous else 0

def parse_dwd_state_names(text:str):
    out={}
    for raw in text.splitlines():
        m=re.match(r"^\s*(\d{1,5})\s+\d{8}\s+\d{8}\s+-?\d+(?:[.,]\d+)?\s+-?\d+(?:[.,]\d+)?\s+-?\d+(?:[.,]\d+)?\s+(.+?)\s*$",raw)
        if not m:continue
        tail=m.group(2)
        for state in sorted(STATES,key=len,reverse=True):
            if re.search(rf"(?:^|\s){re.escape(state)}(?:\s|$)",tail):
                out[f"DWD:{m.group(1).zfill(5)}"]=state;break
    return out

def _finite(v):
    try:
        n=float(v); return n if math.isfinite(n) else None
    except (TypeError,ValueError): return None

def _gzip_json(path,payload):
    raw=json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("wb") as fh:
        with gzip.GzipFile(fileobj=fh,mode="wb",compresslevel=7,mtime=0) as gz:gz.write(raw)

def _write_json(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")

def _current(state,element,mmdd):
    raw=(state.get(element) or {}).get(mmdd)
    if not raw:return None,None
    return int(raw[0]),int(raw[1])

def _record(state,element,mmdd):
    raw=((state.get(element) or {}).get("cal") or {}).get(mmdd)
    return int(raw[0]) if raw else None

def _dates(current,year):
    out=set()
    for state in current.values():
        for element in ("TMAX","TMIN","TMEAN"):
            for raw in (state.get(element) or {}).values():
                if raw:
                    d=int(raw[1])
                    if d//10000==year:
                        s=f"{d:08d}"; out.add(f"{s[:4]}-{s[4:6]}-{s[6:]}")
    return sorted(out)

def write_daily_map(output_dir:Path,*,stations,baseline,current,current_year:int,station_listing_text:str="",generated_at:str|None=None):
    output_dir=Path(output_dir); caldir=output_dir/"calendar"; caldir.mkdir(parents=True,exist_ok=True)
    state_names=parse_dwd_state_names(station_listing_text)
    hist_states=baseline.get("states") or {}
    dates=_dates(current,current_year)
    ids=sorted((sid for sid in current if sid in stations and (current[sid].get("TMAX") or current[sid].get("TMIN") or current[sid].get("TMEAN"))),key=lambda sid:(str(getattr(stations[sid],"name","")).casefold(),sid))
    pos={sid:i for i,sid in enumerate(ids)}
    station_rows=[]
    for sid in ids:
        m=stations[sid]; raw=sid.rsplit(":",1)[-1]
        station_rows.append([sid,re.sub(r"\D","",raw).zfill(5),getattr(m,"name",sid),_finite(getattr(m,"lat",None)),_finite(getattr(m,"lon",None)),_finite(getattr(m,"elev",None)),state_names.get(sid,"")])
    day_counts={}; anom_counts={}; rec_counts={}
    for iso in dates:
        date=dt.date.fromisoformat(iso); mmdd=date.strftime("%m-%d"); dateint=int(date.strftime("%Y%m%d"))
        rows=[]; anoms=0; recs=0
        for sid in ids:
            cur=current[sid]; hist=hist_states.get(sid) or {}
            tx,txd=_current(cur,"TMAX",mmdd); tn,tnd=_current(cur,"TMIN",mmdd); tm,tmd=_current(cur,"TMEAN",mmdd)
            if tx is None and tn is None and tm is None:continue
            if any(v!=dateint for v in (txd,tnd,tmd) if v is not None):continue
            txn,txc=climate_normal_tenths(hist.get("TMAX") or {},mmdd)
            tnn,tnc=climate_normal_tenths(hist.get("TMIN") or {},mmdd)
            tmn,tmc=climate_normal_tenths(hist.get("TMEAN") or {},mmdd)
            txa=tx-txn if tx is not None and txn is not None else None
            tna=tn-tnn if tn is not None and tnn is not None else None
            tma=tm-tmn if tm is not None and tmn is not None else None
            if txa is not None or tna is not None or tma is not None:anoms+=1
            txr=((hist.get("TMAX") or {}).get("cal") or {}).get(mmdd)
            tnr=((hist.get("TMIN") or {}).get("cal") or {}).get(mmdd)
            txs=record_status("TMAX",tx,txr); tns=record_status("TMIN",tn,tnr)
            if txs or tns:recs+=1
            rows.append([pos[sid],tx,tn,txa,tna,txs,tns,_record(hist,"TMAX",mmdd),_record(hist,"TMIN",mmdd),txc,tnc,tm,tma,tmc])
        _gzip_json(caldir/f"{mmdd}.json.gz",{"version":PAYLOAD_VERSION,"date":iso,"reference_period":REFERENCE_LABEL,"rows":rows})
        day_counts[iso]=len(rows); anom_counts[iso]=anoms; rec_counts[iso]=recs
    keep={dt.date.fromisoformat(v).strftime("%m-%d")+".json.gz" for v in dates}
    for p in caldir.glob("*.json.gz"):
        if p.name not in keep:p.unlink()
    through=dates[-1] if dates else None
    index={"version":PAYLOAD_VERSION,"ready":bool(dates and station_rows),"generated_at":generated_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),"year":current_year,"reference_period":REFERENCE_LABEL,"reference_start_year":REFERENCE_START,"reference_end_year":REFERENCE_END,"minimum_reference_years":MIN_REFERENCE_YEARS,"station_fields":["id","dwd_id","name","lat","lon","height_m","state"],"stations":station_rows,"station_count":len(station_rows),"dates":dates,"date_count":len(dates),"data_through":through,"latest_station_count":day_counts.get(through,0) if through else 0,"latest_anomaly_count":anom_counts.get(through,0) if through else 0,"latest_record_count":rec_counts.get(through,0) if through else 0,"calendar_pattern":"calendar/{mm-dd}.json.gz","source":"DWD Climate Data Center (CDC), Tageswerte KL, TXK/TNK/TMK","note":"Stationsabweichungen von Tmax, Tmin und Tmean (TMK) vom jeweiligen Kalendertagsmittel 1991–2020; Ausgabe ab 20 gültigen Referenzjahren. Rekordflags beziehen sich auf Tmax/Tmin und vergleichen mit der historischen Reihe bis zum Vorjahr."}
    _write_json(output_dir/"index.json",index); return index

def self_test():
    block={}
    for v in range(20):add_climatology_value(block,"08-28",200+v)
    assert climate_normal_tenths(block,"08-28")== (210,20)
    assert record_status("TMAX",301,(300,20200828,1))==1
    assert record_status("TMIN",-20,(-20,19930828,1))==2
    class M:
        name="Test";lat=50.;lon=8.;elev=100.
    hist={"DWD:00001":{"TMAX":{"cal":{"08-28":(300,20200828,1)},"clim_1991_2020":{"08-28":[4000,20]}},"TMIN":{"cal":{"08-28":(50,19930828,1)},"clim_1991_2020":{"08-28":[2000,20]}},"TMEAN":{"clim_1991_2020":{"08-28":[3000,20]}}}}
    cur={"DWD:00001":{"TMAX":{"08-28":(310,20260828)},"TMIN":{"08-28":(90,20260828)},"TMEAN":{"08-28":(200,20260828)}}}
    with tempfile.TemporaryDirectory() as tmp:
        idx=write_daily_map(Path(tmp),stations={"DWD:00001":M()},baseline={"states":hist},current=cur,current_year=2026,station_listing_text="00001 19900101 20261231 100 50.0 8.0 Test Hessen")
        assert idx["data_through"]=="2026-08-28" and idx["latest_record_count"]==1
        with gzip.open(Path(tmp)/"calendar"/"08-28.json.gz","rt",encoding="utf-8") as f:row=json.load(f)["rows"][0]
        assert row[3:7]==[110,-10,1,0]
        assert row[11:14]==[200,50,20]
    print("dwd_daily_map.py self-test OK")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--self-test",action="store_true");a=p.parse_args()
    if a.self_test:self_test()
