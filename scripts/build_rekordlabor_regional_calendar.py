#!/usr/bin/env python3
"""Calendar-day DWD record candidates, with provenance and bounded memory.

KL and RR are kept distinct. A disk-backed store deduplicates station/dates
before ranking and keeps the full historical archive out of Python heap memory.
"""
from __future__ import annotations

import csv
import gzip
import heapq
import io
import json
import math
import sqlite3
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from update_station_records import (
    AREAS, MetadataIndex, Observation, NoUsableProductFileError,
)

QC_VERSION = 'regional-calendar-qc-v1'
QUALITY = {1, 2, 3, 5, 7, 8, 9, 10}
METRICS = {
    'tnk_high': {'label':'Höchstes Tmin','unit':'°C','direction':'desc'},
    'txk_low': {'label':'Niedrigstes Tmax','unit':'°C','direction':'asc'},
    'tmk_high': {'label':'Höchstes Tagesmittel','unit':'°C','direction':'desc'},
    'tmk_low': {'label':'Niedrigstes Tagesmittel','unit':'°C','direction':'asc'},
    'amplitude_high': {'label':'Größte Tagesamplitude','unit':'K','direction':'desc'},
    'rs_high': {'label':'Höchster Tagesniederschlag','unit':'mm','direction':'desc'},
    'fx_high': {'label':'Stärkste Tageswindböe','unit':'km/h','direction':'desc'},
    'sdk_high': {'label':'Längste Sonnenscheindauer','unit':'h','direction':'desc'},
}
LIMITS = {'txk_high':(-50,50), 'tnk_low':(-50,50), 'tmk':(-50,50),
          'sdk':(0,24), 'fx_kmh':(0,360), 'rs':(0,500)}
TOP_K = 50
SOURCE_FIELDS = {'tnk_high':('tnk_low',),'txk_low':('txk_high',),
                 'tmk_high':('tmk',),'tmk_low':('tmk',),
                 'amplitude_high':('txk_high','tnk_low'),
                 'rs_high':('rs',),'sdk_high':('sdk',),'fx_high':('fx_kmh',)}


def bounded(key, value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    lo, hi = LIMITS[key]
    return round(value,1) if math.isfinite(value) and lo <= value <= hi else None


def calendar_metrics(values: dict) -> dict:
    valid = {key: v for key in LIMITS if (v := bounded(key, values.get(key))) is not None}
    hi, lo, mean = (valid.get(key) for key in ('txk_high', 'tnk_low', 'tmk'))
    if hi is not None and lo is not None and hi < lo:
        hi = lo = None
    result = {}
    if hi is not None: result['txk_low'] = hi
    if lo is not None: result['tnk_high'] = lo
    if hi is not None and lo is not None:
        result['amplitude_high'] = round(hi-lo,1)
    # Historical observation windows can differ; reject only substantial
    # contradictions with the observed extrema, not rounding differences.
    if mean is not None and (hi is None or mean <= hi+2) and (lo is None or mean >= lo-2):
        result['tmk_high'] = result['tmk_low'] = mean
    for src, dst in [('rs','rs_high'),('sdk','sdk_high'),('fx_kmh','fx_high')]:
        if src in valid: result[dst] = valid[src]
    return result


def calendar_key(day: date) -> str:
    return day.strftime('%m-%d')


def _parse(content, station_id_hint, metadata, start_date, end_date, preliminary, network):
    columns = [('TXK','QN_4','txk_high',1),('TNK','QN_4','tnk_low',1),
               ('TMK','QN_4','tmk',1),('SDK','QN_4','sdk',1),('FX','QN_3','fx_kmh',3.6)] if network=='kl' else [('RS','QN_6','rs',1)]
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith('.txt') or 'produkt' not in name.lower(): continue
            with archive.open(name) as raw:
                reader=csv.DictReader(io.TextIOWrapper(raw,encoding='latin-1',newline=''),delimiter=';')
                headers={h.strip().upper():h for h in (reader.fieldnames or []) if h}
                if not {'STATIONS_ID','MESS_DATUM'}.issubset(headers): continue
                use=[(c,q,key,factor) for c,q,key,factor in columns if c in headers and q in headers]
                if not use: continue
                result=[]
                for row in reader:
                    try: day=datetime.strptime(row[headers['MESS_DATUM']].strip(),'%Y%m%d').date()
                    except (AttributeError,ValueError,TypeError): continue
                    if not start_date<=day<=end_date: continue
                    sid=(row.get(headers['STATIONS_ID']) or station_id_hint).strip().zfill(5)
                    if not sid.isdigit() or len(sid)!=5: continue
                    segment=metadata.segment_for(sid,day)
                    values={}
                    for c,q,key,factor in use:
                        try:
                            if int(row[headers[q]]) not in QUALITY: continue
                            value=float(row[headers[c]].strip().replace(',','.'))
                        except (ValueError,TypeError,AttributeError): continue
                        # Sentinel values cannot become valid after conversion.
                        v=bounded(key,value*factor)
                        if v is not None: values[key]=v
                    if values: result.append(Observation(day,segment.key,segment.state,sid,values,preliminary))
                return result
    raise NoUsableProductFileError(f'keine auswertbare {network.upper()}-Produktdatei mit Qualitätskennzeichen')


def parse_kl_zip(content: bytes, station_id_hint: str, metadata: MetadataIndex,
                 start_date: date, end_date: date, preliminary: bool) -> list[Observation]:
    return _parse(content,station_id_hint,metadata,start_date,end_date,preliminary,'kl')


def parse_rr_zip(content: bytes, station_id_hint: str, metadata: MetadataIndex,
                 start_date: date, end_date: date, preliminary: bool) -> list[Observation]:
    return _parse(content,station_id_hint,metadata,start_date,end_date,preliminary,'rr')


def load_temperature_exclusions(root: Path, first: int, last: int) -> set[tuple[str,str,str]]:
    excluded=set()
    for year in range(first,last+1):
        p=root/str(year)/'quality.json.gz'
        if not p.exists(): continue
        doc=json.loads(gzip.decompress(p.read_bytes()))
        if doc.get('version')!='contrast-qc-v2': raise ValueError(f'Ungeprüfte Temperaturdaten {year}')
        for raw_date,hour,sid,metric,_value,_reason in doc['excluded']:
            if hour is None and metric in ('TXK','TNK'):
                day=datetime.strptime(raw_date,'%Y%m%d').date()
                if day.year!=year: raise ValueError(f'QC-Datum außerhalb von {year}')
                excluded.add((day.isoformat(),str(sid).zfill(5),metric))
    return excluded


class RegionalAccumulator:
    """One row/station/day/network; historical priority per parameter."""
    def __init__(self, db_path: Path, excluded=None):
        self.db=sqlite3.connect(db_path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS observations (
          year INTEGER, day TEXT, sid TEXT, network TEXT, state TEXT, metadata_key TEXT,
          preliminary INTEGER, vals TEXT, PRIMARY KEY (year,day,sid,network)) WITHOUT ROWID''')
        self.excluded=excluded or set()

    def add(self, observation: Observation, network: str):
        self.add_many([observation],network)

    def add_many(self, observations, network: str):
        if network not in ('kl','rr'): raise ValueError(network)
        def inputs():
            for o in observations:
                values={k:v for k,v in o.values.items() if k in LIMITS and ((network=='rr')==(k=='rs'))}
                d=o.day.isoformat()
                for metric,key in [('TXK','txk_high'),('TNK','tnk_low')]:
                    if (d,o.station_id,metric) in self.excluded: values.pop(key,None)
                if values:
                    tagged={k:[v,int(o.preliminary)] for k,v in values.items()}
                    yield (o.day.year,d,o.station_id,network,o.state,o.metadata_key,int(o.preliminary),json.dumps(tagged,sort_keys=True,separators=(',',':')))
        with self.db:
            self.db.executemany('''INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT (year,day,sid,network) DO UPDATE SET
                state=CASE WHEN excluded.preliminary < observations.preliminary THEN excluded.state ELSE observations.state END,
                metadata_key=CASE WHEN excluded.preliminary < observations.preliminary THEN excluded.metadata_key ELSE observations.metadata_key END,
                preliminary=min(excluded.preliminary,observations.preliminary),
                vals=CASE WHEN excluded.preliminary=0 THEN json_patch(observations.vals,excluded.vals)
                          ELSE json_patch(excluded.vals,observations.vals) END''',inputs())

    def records(self, year: int) -> dict:
        # Query one year at a time and keep only the current day in memory;
        # emit at most 50 candidates per metric/area/day.
        out={}; buckets=defaultdict(list); last=None
        def flush(day):
            if day is None: return
            entry={}
            for (metric,area),heap in buckets.items():
                direction=METRICS[metric]['direction']
                rows=[item[2] for item in heap]
                rows.sort(key=lambda r:(-r[0] if direction=='desc' else r[0],r[1],r[2]))
                entry.setdefault(metric,{})[area]=rows
            if entry: out[day[5:]]=entry
            buckets.clear()
        for day,sid,state,key,prelim,raw in self.db.execute('SELECT day,sid,state,metadata_key,preliminary,vals FROM observations WHERE year=? ORDER BY day,sid,network',(year,)):
            if day!=last: flush(last); last=day
            tagged=json.loads(raw)
            for metric,value in calendar_metrics({k:v[0] for k,v in tagged.items()}).items():
                prelim=max(tagged[k][1] for k in SOURCE_FIELDS[metric])
                score=value if METRICS[metric]['direction']=='desc' else -value
                item=(score,-int(sid),[value,day,key,prelim])
                for area in ['Deutschland']+([state] if state in AREAS and state!='Deutschland' else []):
                    heap=buckets[metric,area]
                    if len(heap)<TOP_K: heapq.heappush(heap,item)
                    elif item>heap[0]: heapq.heapreplace(heap,item)
        flush(last)
        return out

    def close(self):
        self.db.close()
