#!/usr/bin/env python3
"""DWD station records for daily TMK, SDK, FX and fully observed decade sums."""
from __future__ import annotations
import argparse
import calendar
import csv
import io
import json
import math
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from update_station_records import (
 HISTORICAL_PATTERN,HISTORICAL_URL,METADATA_URL,RECENT_PATTERN,RECENT_URL,
 RR_HISTORICAL_PATTERN,RR_HISTORICAL_URL,RR_METADATA_URL,RR_RECENT_PATTERN,
 RR_RECENT_URL,RR_STATION_ID_PATTERN,STATE_ORDER,STATION_ID_PATTERN,MetadataIndex,
 Observation,download,iter_downloaded_observations,list_station_files,
 parse_metadata,parse_rr_station_zip,
)

VERSION=1
TOP_K=50
AREAS=["Deutschland",*STATE_ORDER]
METRICS={
 "kl":{
  "tmk_high":dict(label="Höchstes Tagesmittel",unit="°C",direction="desc",key="tmk"),
  "tmk_low":dict(label="Niedrigstes Tagesmittel",unit="°C",direction="asc",key="tmk"),
  "sdk_high":dict(label="Sonnigster Tag",unit="h",direction="desc",key="sdk"),
  "sdk_sum_high":dict(label="Sonnigste vollständige Dekade",unit="h",direction="desc",key="sdk_sum"),
  "sdk_sum_low":dict(label="Sonnenärmste vollständige Dekade",unit="h",direction="asc",key="sdk_sum"),
  "fx_high":dict(label="Stärkste Tageswindböe",unit="km/h",direction="desc",key="fx_kmh"),
 },
 "rr":{
  "rs_sum_high":dict(label="Nasseste vollständige Dekade",unit="mm",direction="desc",key="rs_sum"),
  "rs_sum_low":dict(label="Trockenste vollständige Dekade",unit="mm",direction="asc",key="rs_sum"),
 }
}

def decade(day:date)->int:
 return 1 if day.day<=10 else (2 if day.day<=20 else 3)

def period_id(day:date)->str:
 return f"month-{day.month:02d}-d{decade(day)}"

def end_of_decade(year:int,month:int,dec:int)->date:
 return date(year,month,10 if dec==1 else 20 if dec==2 else calendar.monthrange(year,month)[1])

def expected_days(year:int,month:int,dec:int)->set[date]:
 return {date(year,month,d) for d in range(1 if dec==1 else 11 if dec==2 else 21,end_of_decade(year,month,dec).day+1)}

def parse_kl_station_zip(content:bytes,station_id_hint:str,metadata:MetadataIndex,
                         start_date:date,end_date:date,preliminary:bool)->list[Observation]:
 """DWD KL columns: TMK °C; SDK hours; FX m/s (converted to km/h)."""
 observations=[]
 with zipfile.ZipFile(io.BytesIO(content)) as archive:
  names=[name for name in archive.namelist() if name.lower().endswith(".txt") and "produkt_klima_tag" in name.lower()]
  if not names:
   names=[name for name in archive.namelist() if name.lower().endswith(".txt") and "produkt" in name.lower()]
  for name in names:
   with archive.open(name) as raw:
    reader=csv.DictReader(io.TextIOWrapper(raw,encoding="latin-1",newline=""),delimiter=";")
    cols={k.strip().upper():k for k in (reader.fieldnames or []) if k}
    if not {"STATIONS_ID","MESS_DATUM"}.issubset(cols) or not {"TMK","SDK","FX"}.intersection(cols):continue
    for row in reader:
     try:day=datetime.strptime(str(row[cols["MESS_DATUM"]]).strip(),"%Y%m%d").date()
     except (ValueError,KeyError,TypeError):continue
     if not start_date<=day<=end_date:continue
     values={}
     for name,lo,hi in (("TMK",-70,60),("SDK",0,24.1),("FX",0,100)):
      col=cols.get(name)
      if not col:continue
      try:v=float(str(row[col]).strip().replace(",","."))
      except (TypeError,ValueError,KeyError):continue
      if not math.isfinite(v) or not lo<=v<=hi:continue
      values[{"TMK":"tmk","SDK":"sdk","FX":"fx_kmh"}[name]]=round(v*3.6 if name=="FX" else v,1)
     if not values:continue
     sid=str(row[cols["STATIONS_ID"]] or station_id_hint).strip().zfill(5)
     segment=metadata.segment_for(sid,day)
     observations.append(Observation(day=day,station_id=sid,state=segment.state,
       metadata_key=segment.key,values=values,preliminary=preliminary))
   return observations
 return observations

def entry_for(o:Observation,value:float)->list[Any]:
 return [round(float(value),1),o.day.isoformat(),o.metadata_key,1 if o.preliminary else 0]

def order_key(metric:str,e:list[Any],config:dict[str,Any])->tuple:
 v=float(e[0]);return (-v if config[metric]["direction"]=="desc" else v,str(e[1]),str(e[2]))

class Accumulator:
 def __init__(self,network:str)->None:
  self.network=network
  self.config=METRICS[network]
  self.records=defaultdict(lambda:defaultdict(lambda:defaultdict(dict)))
  self.first_day=None;self.last_day=None
  self.complete_decades=0
  self.counts=defaultdict(int)
 def add_metric(self,o:Observation,metric:str,value:float)->None:
  e=entry_for(o,value)
  for area in ("Deutschland",o.state):
   if area not in AREAS:continue
   bucket=self.records[metric][area][period_id(o.day)]
   old=bucket.get(o.station_id)
   if old is None or order_key(metric,e,self.config)<order_key(metric,old,self.config):
    bucket[o.station_id]=e
  self.counts[metric]+=1
 def add_archive(self,observations:list[Observation])->None:
  # Group by station + year + calendar decade within ONE archive, so no
  # invalid sums from cross-station or historical/recent stitching.
  field="sdk" if self.network=="kl" else "rsk_high"
  groups=defaultdict(dict)
  for o in observations:
   self.first_day=o.day if self.first_day is None else min(self.first_day,o.day)
   self.last_day=o.day if self.last_day is None else max(self.last_day,o.day)
   for metric,spec in self.config.items():
    if "_sum_" in metric:continue
    value=o.values.get(spec["key"])
    if value is not None:self.add_metric(o,metric,value)
   if field in o.values:
    groups[(o.station_id,o.day.year,o.day.month,decade(o.day))][o.day]=o
  for (_,year,month,dec),days in groups.items():
   required=expected_days(year,month,dec)
   if days.keys()!=required:continue
   v=round(sum(days[day].values[field] for day in required),1)
   record=days[end_of_decade(year,month,dec)]
   key="sdk_sum" if self.network=="kl" else "rs_sum"
   for metric,spec in self.config.items():
    if spec["key"]==key:self.add_metric(record,metric,v)
   self.complete_decades+=1
 def output(self,metadata:MetadataIndex)->dict[str,Any]:
  periods=[dict(id=f"month-{month:02d}-d{dec}",month=month,decade=dec)
            for month in range(1,13) for dec in (1,2,3)]
  records={};leaders={};metadata_keys=set()
  for metric in self.config:
   records[metric]={};leaders[metric]={}
   for area in AREAS:
    records[metric][area]={};leaders[metric][area]={}
    for period in periods:
     pid=period["id"];bucket=self.records.get(metric,{}).get(area,{}).get(pid,{})
     records[metric][area][pid]={sid:bucket[sid] for sid in sorted(bucket)}
     leaders[metric][area][pid]=sorted(bucket.values(),key=lambda e:order_key(metric,e,self.config))[:TOP_K]
     metadata_keys.update(e[2] for e in bucket.values())
  public_meta=metadata.public_dict()
  return dict(version=VERSION,network=self.network,
   generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
   source="DWD CDC daily/kl · TMK SDK FX" if self.network=="kl" else "DWD CDC daily/more_precip · RS",
   data_start=self.first_day.isoformat() if self.first_day else None,
   data_through=self.last_day.isoformat() if self.last_day else None,
   areas=AREAS,periods=periods,metrics=self.config,top_k=TOP_K,
   stations={key:public_meta[key] for key in sorted(metadata_keys) if key in public_meta},
   station_records=records,leaders=leaders,complete_station_decades=self.complete_decades,
   record_counts=dict(self.counts),
   method_note="Summen nur für komplett gemessene meteorologische Dekaden (01.–10., 11.–20., 21.–Monatsende). Keine Lückenfüllung. Datum bei Summen = Dekadenende. FX in km/h."
  )

def build(network:str,max_workers:int,limit_files:int|None=None)->dict:
 if network=="kl":
  historical_url,historical_pattern,recent_url,recent_pattern=(HISTORICAL_URL,HISTORICAL_PATTERN,RECENT_URL,RECENT_PATTERN)
  meta_url,pattern,parser,min_h,min_r=METADATA_URL,STATION_ID_PATTERN,parse_kl_station_zip,500,300
 else:
  historical_url,historical_pattern,recent_url,recent_pattern=(RR_HISTORICAL_URL,RR_HISTORICAL_PATTERN,RR_RECENT_URL,RR_RECENT_PATTERN)
  meta_url,pattern,parser,min_h,min_r=RR_METADATA_URL,RR_STATION_ID_PATTERN,parse_rr_station_zip,4000,1500
 metadata=parse_metadata(download(meta_url,timeout=180))
 historical=list_station_files(historical_url,historical_pattern,minimum=min_h)
 recent=list_station_files(recent_url,recent_pattern,minimum=min_r)
 if limit_files is not None:historical=historical[:limit_files];recent=recent[:limit_files]
 print(network,"historical",len(historical),"recent",len(recent),flush=True)
 accumulator=Accumulator(network);today=datetime.now(timezone.utc).date()
 for url,names,start,preliminary,tolerance in (
  (historical_url,historical,date(1750,1,1),False,.015),
  (recent_url,recent,date(today.year-2,1,1),True,.025)):
  for observations in iter_downloaded_observations(
   names,url,metadata,start,today,preliminary,max_workers,
   station_pattern=pattern,parser=parser,failure_tolerance=tolerance
  ):
   accumulator.add_archive(observations)
 result=accumulator.output(metadata)
 print(network,"complete decades",result["complete_station_decades"],
       "stations",len(result["stations"]),flush=True)
 return result

def main()->int:
 ap=argparse.ArgumentParser()
 ap.add_argument("--network",required=True,choices=("kl","rr"))
 ap.add_argument("--output")
 ap.add_argument("--max-workers",type=int,default=12)
 ap.add_argument("--limit-files",type=int,help="diagnostic only")
 args=ap.parse_args()
 result=build(args.network,args.max_workers,args.limit_files)
 if len(result["areas"])!=17 or len(result["periods"])!=36:raise RuntimeError("Invalid region/period structure")
 if result["complete_station_decades"]<1:raise RuntimeError("No complete decades")
 for metric in METRICS[args.network]:
  if not any(result["leaders"][metric]["Deutschland"].values()):
   raise RuntimeError("No observed records for "+metric)
 path=Path(args.output or f"data/dwd_decade_extra_{args.network}.json")
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
 print("Wrote",path,path.stat().st_size,"bytes",flush=True)
 return 0

if __name__=="__main__":
 raise SystemExit(main())
