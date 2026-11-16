#!/usr/bin/env python3
"""Exact spatial DWD station temperature contrasts (tenths of a kelvin)."""
import argparse
import datetime as dt
import gzip
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen, Request
from zipfile import ZipFile
import numpy as np
try:
    from numba import njit
except ImportError:
    def njit(f): return f

MISSING = -32768
BASE = 'https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/'
STATES = ['Baden-Württemberg','Bayern','Berlin','Brandenburg','Bremen','Hamburg','Hessen','Mecklenburg-Vorpommern','Niedersachsen','Nordrhein-Westfalen','Rheinland-Pfalz','Saarland','Sachsen','Sachsen-Anhalt','Schleswig-Holstein','Thüringen']
RADII = np.array([9999.,25.,50.,100.,200.])
DELTAS = np.array([9999.,200.])
HEIGHTS = [9999,1000,500]
QUALITY = {1,2,3,5,7,8,9,10}

@njit
def scan(hot, cold, distances, differences, radii, heights, steps):
    """One winner/day/filter, with strictly distinct stations and simultaneous rows."""
    out = np.full((hot.shape[0]//steps,len(radii),len(heights),6),-1,np.int32)
    out[:,:,:,0]=MISSING
    possible=np.zeros((len(radii),len(heights)),np.bool_)
    for r in range(len(radii)):
        for h in range(len(heights)):
            for i in range(hot.shape[1]):
                for j in range(hot.shape[1]):
                    if i!=j and distances[i,j]<=radii[r] and differences[i,j]<=heights[h]: possible[r,h]=True; break
                if possible[r,h]: break
    for t in range(hot.shape[0]):
        a = np.argsort(hot[t]); b = np.argsort(cold[t]); day = t//steps
        if len(a)<2: continue
        first=0
        while first<len(b) and cold[t,b[first]]==MISSING: first+=1
        if first==len(b): continue
        for r in range(len(radii)):
            for h in range(len(heights)):
                if not possible[r,h]: continue
                best = out[day,r,h,0]
                for ii in range(len(a)-1,-1,-1):
                    i = a[ii]; v = int(hot[t,i])
                    if v==MISSING or v-int(cold[t,b[first]])<=best: break
                    for jj in range(first,len(b)):
                        j = b[jj]; w = int(cold[t,j])
                        if w==MISSING: continue
                        if v-w<=best: break
                        if i!=j and distances[i,j]<=radii[r] and differences[i,j]<=heights[h]:
                            best=v-w
                            out[day,r,h,0]=best; out[day,r,h,1]=i; out[day,r,h,2]=j
                            out[day,r,h,3]=t%steps; out[day,r,h,4]=v; out[day,r,h,5]=w
                            break
    return out

def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':'ClimateDashboard-DWD/1.0'}),timeout=100) as f: return f.read()
        except Exception:
            if attempt==2: raise

def catalogue(text):
    result={}
    pattern=r'^\s*(\d{5})\s+(\d{8})\s+(\d{8})\s+(-?[\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+)$'
    for line in text.splitlines():
        m=re.match(pattern,line)
        if not m: continue
        sid,first,last,elev,lat,lon,tail=m.groups()
        state=re.search(r'\s+('+'|'.join(STATES)+r')(?=\s|$)',tail)
        if not state: continue
        result[sid]=dict(id=sid,name=tail[:state.start()].strip(),state=state[1],height=float(elev),lat=float(lat),lon=float(lon))
    return result

def inventory(mode, start,end):
    hourly=mode=='hourly'; base=BASE+('hourly/air_temperature/' if hourly else 'daily/kl/')
    prefix='stundenwerte_TU' if hourly else 'tageswerte_KL'
    desc='TU_Stundenwerte_Beschreibung_Stationen.txt' if hourly else 'KL_Tageswerte_Beschreibung_Stationen.txt'
    cat={}; urls={}
    # CDC recent/ covers only the rolling last 500 days.
    folders=('recent','historical') if end>=(dt.date.today()-dt.timedelta(days=500)).strftime('%Y%m%d') else ('historical',)
    for folder in folders:
        directory=base+folder+'/'
        listing=fetch(directory).decode('utf8','replace')
        cat.update(catalogue(fetch(directory+desc).decode('latin1')))
        for match in re.finditer(prefix+r'_(\d{5})(?:_(\d{8})_(\d{8}))?_(?:hist|akt)\.zip',listing):
            sid,first,last=match.groups()
            if first and (last<start or first>end): continue
            urls.setdefault(sid,set()).add(directory+match[0])
    return [(cat[s],sorted(u,key=lambda x:('/historical/' in x,x))) for s,u in sorted(urls.items()) if s in cat]

def read_station(station, urls, days, hourly):
    steps=24 if hourly else 1; n=len(days)*steps
    hot=np.full(n,MISSING,np.int16); cold=hot.copy()
    exact=set()
    for url in urls: # Recent first, validated historical last.
        with ZipFile(io.BytesIO(fetch(url))) as z:
            periods=[]
            if hourly:
                for name in z.namelist():
                    if not re.search(r'Metadaten_Parameter_.*\.txt$',name,re.I): continue
                    for line in z.read(name).decode('latin1').splitlines()[1:]:
                        p=[v.strip() for v in line.split(';')]
                        if len(p)>=9 and p[0].zfill(5)==station['id'] and p[4].upper()=='TT_TU':
                            periods.append((p[1].replace('-',''),p[2].replace('-','') or '99999999',p[8]))
                next_day=(dt.datetime.strptime(max(days),'%Y%m%d')+dt.timedelta(days=1)).strftime('%Y%m%d')
                zone_days={}
                for d in (*days,next_day):
                    zones={zone for first,last,zone in periods if first<=d<=last}
                    if zones=={'Stundenwerte in UTC'}: zone_days[d]=0
                    # Documented eMD archive, fixed standard time UTC+1 (no DST).
                    # Plain MEZ is excluded: historical metadata can mislabel UTC stamps.
                    elif zones=={'Stundenwerte in MEZ (MD)'} and d<='19920101': zone_days[d]=1
            found=False
            for name in z.namelist():
                if not re.search(r'produkt.*\.txt$',name,re.I): continue
                found=True
                with io.TextIOWrapper(z.open(name),encoding='latin1') as f:
                    fields=[v.strip() for v in f.readline().split(';')]
                    indexes=[fields.index(k) for k in ('STATIONS_ID','MESS_DATUM','QN_9' if hourly else 'QN_4','TT_TU' if hourly else 'TXK','TT_TU' if hourly else 'TNK')]
                    for line in f:
                        p=line.split(';')
                        if len(p)<=max(indexes): continue
                        sid,stamp,q,a,b=(p[i].strip() for i in indexes); day=stamp[:8]
                        if sid.zfill(5)!=station['id'] or (hourly and day not in zone_days) or (not hourly and day not in days): continue
                        try:
                            if int(q) not in QUALITY: continue
                            hour=int(stamp[8:]) if hourly else 0
                            if len(stamp)!=(10 if hourly else 8) or not 0<=hour<steps: continue
                            va,vb=float(a),float(b)
                            offset=zone_days[day] if hourly else 0
                            if offset:
                                hour-=offset
                                if hour<0:
                                    day=(dt.datetime.strptime(day,'%Y%m%d')-dt.timedelta(days=1)).strftime('%Y%m%d')
                                    hour+=24
                        except ValueError: continue
                        if offset and day>'19911231': continue
                        if day not in days: continue
                        ix=days[day]*steps+hour
                        if hourly:
                            if offset and ix in exact: continue
                            if not offset and -70<=va<=65: exact.add(ix)
                        if -70<=va<=65: hot[ix]=round(va*10)
                        if -70<=vb<=65: cold[ix]=round(vb*10)
            if not found: raise ValueError(f'No product in {url}')
    return hot,cold

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))

def build(out,mode,first,last,limit=0):
    start=dt.date(first,1,1); end=min(dt.date(last,12,31),dt.date.today()-dt.timedelta(days=1))
    days={(start+dt.timedelta(days=i)).strftime('%Y%m%d'):i for i in range((end-start).days+1)}
    hourly=mode=='hourly'; steps=24 if hourly else 1
    early_hourly=hourly and last<=1991 and not limit
    early_daily=not hourly and last<1961 and not limit
    inv=inventory(mode,min(days),(end+dt.timedelta(days=1)).strftime('%Y%m%d') if hourly else max(days))
    if limit: inv=inv[:limit]
    if not inv or (len(inv)<2 and not early_hourly): raise ValueError('Too few stations')
    hot=np.full((len(days)*steps,len(inv)),MISSING,np.int16); cold=hot.copy()
    with ThreadPoolExecutor(max_workers=8) as pool:
        for j,(a,b) in enumerate(pool.map(lambda item:read_station(*item,days,hourly),inv)):
            hot[:,j]=a; cold[:,j]=b
            if j%50==0: print(mode,j+1,'/',len(inv),flush=True)
    stations=[s for s,_ in inv]; active=np.any(hot!=MISSING,axis=0)|np.any(cold!=MISSING,axis=0)
    if not early_hourly and active.sum()<(2 if limit or early_daily else 80): raise ValueError('Insufficient valid stations')
    lat=np.radians([s['lat'] for s in stations]); lon=np.radians([s['lon'] for s in stations]); height=np.array([s['height'] for s in stations])
    distances=6371*2*np.arcsin(np.sqrt(np.clip(np.sin((lat[:,None]-lat)/2)**2+np.cos(lat[:,None])*np.cos(lat)*np.sin((lon[:,None]-lon)/2)**2,0,1)))
    differences=np.abs(height[:,None]-height)
    for year in range(first,end.year+1):
        dates=[d for d in days if d.startswith(str(year))]; lo=days[dates[0]]*steps; hi=(days[dates[-1]]+1)*steps
        year_active=np.any(hot[lo:hi]!=MISSING,axis=0)|np.any(cold[lo:hi]!=MISSING,axis=0)
        # Older hourly records can have no documented overlapping UTC measurements.
        # Record this explicitly, without putting an empty year in the public index.
        if hourly and year<1991 and not limit and not np.any(np.sum(hot[lo:hi]!=MISSING,axis=1)>=2):
            p=out/mode/str(year)/'unavailable.json'
            if (p.parent/'ready.json').exists(): raise ValueError(f'Previously published data missing for {year}')
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps(dict(year=year,stations=int(year_active.sum()),reason='no_simultaneous_documented_utc_pair',time_reference='utc-md-v2')))
            print('No simultaneous documented UTC pairs in',year,flush=True)
            continue
        national_days=0
        for region in ['DE']+STATES:
            results={}; region_idx=np.array([i for i,s in enumerate(stations) if year_active[i] and (region=='DE' or region==s['state'])],dtype=int)
            for ceiling in HEIGHTS:
                ids=region_idx[height[region_idx]<=ceiling]
                result=scan(hot[lo:hi,ids],cold[lo:hi,ids],distances[np.ix_(ids,ids)],differences[np.ix_(ids,ids)],RADII,DELTAS,steps)
                for ri,r in enumerate(RADII):
                    for di,d in enumerate(DELTAS):
                        rows=[]
                        for day,row in enumerate(result[:,ri,di]):
                            if row[1]<0: continue
                            v,i,j,h,a,b=map(int,row); rows.append([day,v,int(ids[i]),int(ids[j]),h,a,b])
                        results[f'{ceiling}-{int(r)}-{int(d)}']=rows
            dump(out/mode/str(year)/(('DE' if region=='DE' else str(STATES.index(region)))+'.json.gz'),dict(start=dates[0],end=dates[-1],stations=stations,results=results))
            if region=='DE': national_days=len(results['9999-9999-9999'])
        # Hourly raw station values, separately compressed for detailed day analysis.
        if hourly:
            for month in range(1,13):
                md=[d for d in dates if d[4:6]==f'{month:02}']
                if not md: continue
                a=days[md[0]]*24; b=(days[md[-1]]+1)*24
                p=out/mode/str(year)/f'hour-{month:02}.bin.gz'; p.write_bytes(gzip.compress(hot[a:b].astype('<i2').tobytes(),mtime=0))
        print('Verified year',mode,year,national_days,'valid days of',len(dates),'stations',int(year_active.sum()),flush=True)
        if not national_days: raise ValueError(f'No valid national pairs for {mode} {year}')
        if not limit:
            p=out/mode/str(year)/'ready.json'; p.write_text(json.dumps(dict(start=dates[0],end=dates[-1],stations=int(year_active.sum()),days=national_days,year=year,**({'time_reference':'utc-md-v2'} if hourly else {}))))
            (p.parent/'unavailable.json').unlink(missing_ok=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--out',type=Path,required=True); p.add_argument('--mode',choices=['hourly','daily'],required=True); p.add_argument('--first',type=int,required=True); p.add_argument('--last',type=int,required=True); p.add_argument('--limit',type=int,default=0)
    a=p.parse_args(); build(a.out,a.mode,a.first,a.last,a.limit)

