#!/usr/bin/env python3
"""Exact spatial DWD station temperature contrasts (tenths of a kelvin)."""
import argparse
import datetime as dt
import gzip
import io
import json
import math
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
QC_VERSION = 'contrast-qc-v2'

@njit
def series_flags(values, neighbors, hourly):
    """Conservative flags, in tenths of a degree; no temperature replacement."""
    flags=np.zeros(values.shape,np.uint8)
    residuals=np.zeros(values.shape,np.int16)
    span=6 if hourly else 2
    for t in range(values.shape[0]):
        for s in range(values.shape[1]):
            v=int(values[t,s])
            if v==MISSING: continue
            if v>500 or v<-500:
                flags[t,s]=1; continue
            low=10000; high=-10000; n=0
            for j in neighbors[s]:
                if j<0: break
                w=int(values[t,j])
                if w==MISSING or w>500 or w<-500: continue
                low=min(low,w); high=max(high,w); n+=1
                if n>=16: break
            residual=max(0,low-v,v-high) if n>=3 else 0
            residuals[t,s]=residual
            if residual>=300: flags[t,s]=2
    # Never use an already strongly implausible reading as evidence against
    # its valid neighboring hours (e.g. valid recovery between sensor faults).
    baseline=flags.copy()
    for t in range(values.shape[0]):
        for s in range(values.shape[1]):
            v=int(values[t,s]); residual=int(residuals[t,s])
            if v==MISSING or flags[t,s]: continue
            # Search both time directions, including short missing intervals.
            before=False; after=False
            threshold=200 if hourly else 250
            same=1
            for k in range(1,span+1):
                if t-k>=0:
                    w=int(values[t-k,s])
                    if w!=MISSING and not baseline[t-k,s] and abs(v-w)>=threshold: before=True
                    if w==v: same+=1
                if t+k<values.shape[0]:
                    w=int(values[t+k,s])
                    if w!=MISSING and not baseline[t+k,s] and abs(v-w)>=threshold: after=True
                    if w==v: same+=1
            if residual>=250 and (before or after or (hourly and same>=8)):
                flags[t,s]=2
            elif hourly and before and after:
                # Require a return to the same level and a very large jump
                # when there is no spatial evidence (sparse old networks).
                if t>0 and t+1<values.shape[0]:
                    a=int(values[t-1,s]); b=int(values[t+1,s])
                    if a!=MISSING and b!=MISSING and not baseline[t-1,s] and not baseline[t+1,s] and abs(a-b)<=50:
                        jump=min(abs(v-a),abs(v-b))
                        if residual>=160 and jump>=200: flags[t,s]=3
                        elif jump>=250: flags[t,s]=4
    return flags

@njit
def combined_flags(values, flags, neighbors, distances, daily_hi, daily_lo, decade_hi, decade_lo, hourly):
    """Independent temporal, spatial and climatological evidence; tenths of °C."""
    baseline=flags.copy()
    steps=24 if hourly else 1
    for t in range(values.shape[0]):
        day=t//steps
        for s in range(values.shape[1]):
            v=int(values[t,s])
            if v==MISSING or baseline[t,s]: continue
            # A documented daily extreme is allowed a full adjacent-day buffer
            # because the historical climate day is not necessarily UTC.
            excess=0; national=0; daily_confirmed=False
            if hourly and 0<day<daily_hi.shape[0]-1:
                for col in (s,values.shape[1]):
                    if col>=daily_hi.shape[1]: continue
                    hi=-10000; lo=10000; nh=0; nl=0
                    for d in range(day-1,day+2):
                        a=int(daily_hi[d,col]); b=int(daily_lo[d,col])
                        if a!=MISSING: hi=max(hi,a); nh+=1
                        if b!=MISSING: lo=min(lo,b); nl+=1
                    e=max(0,v-hi if nh==3 else 0,lo-v if nl==3 else 0)
                    if col==s:
                        excess=e
                        daily_confirmed=nh==3 and nl==3 and lo-20<=v<=hi+20
                    else: national=e
            # A large inconsistency with the same station's own max/min is
            # sufficient even where the old hourly network is sparse.
            if excess>=80:
                flags[t,s]=6; continue
            clim=0
            if day<decade_hi.shape[0]:
                a=int(decade_hi[day,s]); b=int(decade_lo[day,s])
                clim=max(0,v-a if a!=MISSING else 0,b-v if b!=MISSING else 0)
            # Use the nearest radius with at least three comparable stations.
            # Require disagreement with the entire envelope, not merely its mean.
            n=0; lo=10000; hi=-10000; radius=25.
            for j in neighbors[s]:
                if j<0: break
                w=int(values[t,j]); dist=distances[s,j]
                if dist>radius:
                    if n>=3: break
                    while dist>radius:
                        if radius==25.: radius=50.
                        elif radius==50.: radius=100.
                        else: radius=150.
                if w==MISSING or baseline[t,j]: continue
                lo=min(lo,w); hi=max(hi,w); n+=1
                if n>=16: break
            # A sparse network can still corroborate a very large independent
            # nationwide daily contradiction using two close stations.
            if n<3 and not (n>=2 and national>=80): continue
            spatial=max(lo-v,v-hi,0)
            if spatial>=60 and (excess>=30 or national>=50):
                flags[t,s]=6; continue
            if spatial>=100 and clim>=40 and not daily_confirmed:
                flags[t,s]=7; continue
            if not hourly or spatial<120 or daily_confirmed: continue
            # A single-hour spike returning to the previous level is stronger
            # evidence than a real multi-hour cold pool or frontal passage.
            if 0<t<values.shape[0]-1:
                a=int(values[t-1,s]); b=int(values[t+1,s]); direction=1 if v>hi else -1
                if a!=MISSING and b!=MISSING and not baseline[t-1,s] and not baseline[t+1,s] and abs(a-b)<=50 and min(direction*(v-a),direction*(v-b))>=120:
                    flags[t,s]=8
    return flags

def quality_flags(hot,cold,distances,differences,hourly,daily=None,decade=None,cold_decade=None):
    """Use nearby, comparable-height stations; preserve isolated mountain sites."""
    active=np.any(hot!=MISSING,axis=0)|np.any(cold!=MISSING,axis=0)
    lists=[]
    for i in range(hot.shape[1]):
        eligible=np.flatnonzero(active&(distances[i]<=150)&(differences[i]<=400)&(np.arange(hot.shape[1])!=i))
        lists.append(eligible[np.argsort(distances[i,eligible],kind='stable')])
    neighbors=np.full((hot.shape[1],max(1,max(map(len,lists),default=0))),-1,np.int32)
    for i,order in enumerate(lists): neighbors[i,:len(order)]=order
    h=series_flags(hot,neighbors,hourly)
    empty=np.empty((0,hot.shape[1]),np.int16)
    h=combined_flags(hot,h,neighbors,distances,*(daily or (empty,empty)),*(decade or (empty,empty)),hourly)
    if hourly: return h,h
    c=series_flags(cold,neighbors,False)
    c=combined_flags(cold,c,neighbors,distances,empty,empty,*(cold_decade or (empty,empty)),False)
    impossible=(hot!=MISSING)&(cold!=MISSING)&(hot<cold)
    h[impossible]=5; c[impossible]=5
    return h,c

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
                        # Retain even implausible finite numeric readings for
                        # the separate QC audit. -999 is the DWD missing code.
                        good_a=math.isfinite(va) and va!=-999 and -3276.7<=va<=3276.7
                        good_b=math.isfinite(vb) and vb!=-999 and -3276.7<=vb<=3276.7
                        if hourly:
                            if offset and ix in exact: continue
                            if not offset and good_a: exact.add(ix)
                        if good_a: hot[ix]=round(va*10)
                        if good_b: cold[ix]=round(vb*10)
            if not found: raise ValueError(f'No product in {url}')
    return hot,cold

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))

def decade_bounds(path, days, stations, hourly):
    """Read the independent DWD Dekadenrekorde product, aligned by station ID."""
    source=json.loads(path.read_text()); records=source['station_records']; meta=source['stations']
    metrics=('txk_high','tnk_low') if hourly else ('txk_high','txk_low','tnk_high','tnk_low')
    sid_to_col={str(s['id']).zfill(5):i for i,s in enumerate(stations)}
    periods=[f'month-{d[4:6]}-d{min(3,(int(d[6:])-1)//10+1)}' for d in days]
    result=[]
    for metric in metrics:
        raw=records[metric]['Deutschland']; lookup={}
        for period in set(periods):
            row=np.full(len(stations),MISSING,np.int16); rr=raw.get(period,{}); national=[]
            for entry in (rr.values() if isinstance(rr,dict) else rr):
                if not entry or len(entry)<3: continue
                key=entry[2]
                st=meta.get(str(key)) if isinstance(meta,dict) else meta[key] if isinstance(key,int) and 0<=key<len(meta) else None
                sid=str((st or {}).get('id',str(key).split(':')[0])).zfill(5)
                col=sid_to_col.get(sid)
                try: val=round(float(entry[0])*10)
                except (ValueError,TypeError,OverflowError): continue
                if not -500<=val<=500: continue
                national.append(val)
                if col is None: continue
                old=int(row[col]); row[col]=val if old==MISSING else (max(old,val) if metric.endswith('_high') else min(old,val))
            if national: row[row==MISSING]=max(national) if metric.endswith('_high') else min(national)
            lookup[period]=row
        result.append(np.stack([lookup[p] for p in periods]))
    if not any(np.any(a!=MISSING) for a in result):
        print('No station-specific decade matches for this archive batch',flush=True)
    else: print('Decade reference:',sum(np.count_nonzero(a!=MISSING) for a in result),'matched station-days',flush=True)
    return result

def daily_reference(path,days,stations):
    """Align the QC-clean daily arrays to hourly station IDs and add DE bounds."""
    with np.load(path,allow_pickle=False) as ref:
        dates={str(d):i for i,d in enumerate(ref['dates'])}; ids={str(s):i for i,s in enumerate(ref['ids'])}
        source_hi=ref['hot']; source_lo=ref['cold']
        out_hi=np.full((len(days),len(stations)+1),MISSING,np.int16); out_lo=out_hi.copy()
        sel=[dates[d] for d in days]
        for i,s in enumerate(stations):
            j=ids.get(str(s['id']))
            if j is not None: out_hi[:,i]=source_hi[sel,j]; out_lo[:,i]=source_lo[sel,j]
        a=source_hi[sel]; b=source_lo[sel]
        ok=np.count_nonzero(a!=MISSING,axis=1)>=20; out_hi[ok,-1]=a[ok].max(axis=1)
        ok=np.count_nonzero(b!=MISSING,axis=1)>=20; out_lo[ok,-1]=np.where(b[ok]==MISSING,32767,b[ok]).min(axis=1)
    print('Daily reference:',np.count_nonzero(out_hi[:,:-1]!=MISSING),'matching Tmax station-days',flush=True)
    return out_hi,out_lo

def build(out,mode,first,last,limit=0,reference=None,decade_path=None):
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
    # Audit raw observations before selecting any winner, including the hourly
    # drill-down. Unflagged readings are left bit-identical.
    bounds=decade_bounds(decade_path,days,stations,hourly) if decade_path else None
    daily=daily_reference(reference,days,stations) if hourly and reference else None
    hf,cf=quality_flags(hot,cold,distances,differences,hourly,daily=daily,decade=tuple(bounds[:2]) if bounds else None,cold_decade=tuple(bounds[2:]) if bounds and not hourly else None)
    if not hourly and reference:
        np.savez_compressed(reference,dates=np.array(list(days)),ids=np.array([s['id'] for s in stations]),hot=np.where(hf==0,hot,MISSING).astype(np.int16),cold=np.where(cf==0,cold,MISSING).astype(np.int16))
    for year in range(first,end.year+1):
        dates=[d for d in days if d.startswith(str(year))]; lo=days[dates[0]]*steps; hi=(days[dates[-1]]+1)*steps
        audit=[]
        for label,values,flags in [('TT_TU' if hourly else 'TXK',hot,hf)]+([] if hourly else [('TNK',cold,cf)]):
            for t,i in zip(*np.nonzero(flags[lo:hi])):
                audit.append([dates[t//steps],int(t%steps) if hourly else None,stations[i]['id'],label,int(values[lo+t,i]),int(flags[lo+t,i])])
        dump(out/mode/str(year)/'quality.json.gz',dict(version=QC_VERSION,unit='0.1 °C',columns=['date','hour_utc','station_id','parameter','original','reason'],reasons={'1':'physical range','2':'strong spatial inconsistency','3':'spatial and temporal inconsistency','4':'isolated extreme spike','5':'TXK below TNK','6':'contradiction with daily extremes','7':'spatial and decade inconsistency','8':'local and temporal inconsistency'},excluded=audit))
        hot[lo:hi][hf[lo:hi]!=0]=MISSING
        cold[lo:hi][cf[lo:hi]!=0]=MISSING
        year_active=np.any(hot[lo:hi]!=MISSING,axis=0)|np.any(cold[lo:hi]!=MISSING,axis=0)
        # Older hourly records can have no documented overlapping UTC measurements.
        # Record this explicitly, without putting an empty year in the public index.
        if hourly and year<1991 and not limit and not np.any(np.sum(hot[lo:hi]!=MISSING,axis=1)>=2):
            p=out/mode/str(year)/'unavailable.json'
            if (p.parent/'ready.json').exists(): raise ValueError(f'Previously published data missing for {year}')
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps(dict(year=year,stations=int(year_active.sum()),reason='no_simultaneous_documented_utc_pair',time_reference='utc-md-v2',quality_version=QC_VERSION,excluded=len(audit))))
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
            dump(out/mode/str(year)/(('DE' if region=='DE' else str(STATES.index(region)))+'.json.gz'),dict(start=dates[0],end=dates[-1],quality_version=QC_VERSION,stations=stations,results=results))
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
            p=out/mode/str(year)/'ready.json'; p.write_text(json.dumps(dict(start=dates[0],end=dates[-1],stations=int(year_active.sum()),days=national_days,year=year,quality_version=QC_VERSION,excluded=len(audit),**({'time_reference':'utc-md-v2'} if hourly else {}))))
            (p.parent/'unavailable.json').unlink(missing_ok=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--out',type=Path,required=True); p.add_argument('--mode',choices=['hourly','daily'],required=True); p.add_argument('--first',type=int,required=True); p.add_argument('--last',type=int,required=True); p.add_argument('--limit',type=int,default=0); p.add_argument('--reference',type=Path); p.add_argument('--decade-records',type=Path)
    a=p.parse_args(); build(a.out,a.mode,a.first,a.last,a.limit,a.reference,a.decade_records)

