#!/usr/bin/env python3
"""Real daily polar-sector geopotential height (dam); independent resumable products."""
from __future__ import annotations
import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile
import numpy as np

REGIONS = {'polar': (0, 360), 'pacific': (120, 240), 'atlantic': (-90, 30), 'eurasia': (30, 120)}
ECMWF_LEVELS = [10,50,100,150,200,250,300,400,500,600,700,850,925,1000]
NOAA_LEVELS = [10,50,100,200,250,300,500,700,850,925,1000]
GRAVITY = 9.80665
REF_YEARS = range(1991,2021)

def sector_weights(lat, lon):
    lat, lon = np.asarray(lat,dtype=float).ravel(), np.asarray(lon,dtype=float).ravel()
    if lat.shape != lon.shape: raise ValueError('Latitude/longitude mismatch')
    cap = (lat >= 60.-.0001) & (lat <= 90.)
    out = {}
    for region,(west,east) in REGIONS.items():
        mask=cap & (((lon-west)%360) < east-west if east-west < 360 else True)
        ix=np.flatnonzero(mask)
        w=np.cos(np.deg2rad(lat[ix]))
        if not len(ix) or not w.sum()>0: raise ValueError(f'Empty sector {region}')
        out[region]=(ix,w/w.sum())
    return out

def weighted_means(values, weights):
    v=np.asarray(values,dtype=float).ravel()
    out={}
    for region,(ix,w) in weights.items():
        part=v[ix]
        if not np.isfinite(part).all() or np.any((part < -150.) | (part > 4000.)):
            raise ValueError(f'Invalid height values: {region}')
        out[region]=float(np.dot(part,w))
    return out

def sector_means(lat,lon,height): return weighted_means(height,sector_weights(lat,lon))

def reference_means(days):
    buckets={}
    for iso,row in days.items():
        d=date.fromisoformat(iso)
        if d.year in REF_YEARS: buckets.setdefault(iso[5:],{})[d.year]=row
    result={}
    for md,rows in buckets.items():
        if md=='02-29' or set(rows)!=set(REF_YEARS): continue
        try:
            levels=set(rows[1991]['polar'])
            if not levels or any(set(row)!=set(REGIONS) or any(set(row[region])!=levels for region in REGIONS) for row in rows.values()): continue
            mean={r:{p:round(float(np.mean([row[r][p] for row in rows.values()])),4) for p in sorted(levels,key=int)} for r in REGIONS}
            if all(math.isfinite(v) for r in mean.values() for v in r.values()): result[md]=mean
        except (KeyError,TypeError,ValueError): continue
    if '02-28' in result and '03-01' in result:
        result['02-29']={r:{p:round((v+result['03-01'][r][p])/2,4) for p,v in result['02-28'][r].items() if p in result['03-01'][r]} for r in REGIONS}
    return result

def validate_forecast(payload,model,now=None):
    now=now or datetime.now(timezone.utc)
    try:
        cycle=datetime.fromisoformat(payload['cycle'].replace('Z','+00:00'))
        levels=NOAA_LEVELS if model=='gefs' else ECMWF_LEVELS
        if payload['model']!=model or payload['levels']!=levels or cycle.hour!=0 or cycle.minute!=0 or cycle.second!=0 or not timedelta(0)<=now-cycle<=timedelta(hours=72): return False
        expected={(cycle+timedelta(days=d)).strftime('%Y-%m-%d') for d in range(16)}
        if set(payload['days'])!=expected: return False
        return all(set(row)==set(REGIONS) and all(set(v)=={str(p) for p in levels} and all(isinstance(x,(int,float)) and math.isfinite(x) and -150<x<4000 for x in v.values()) for v in row.values()) for row in payload['days'].values())
    except (KeyError,ValueError,TypeError): return False

def read_json(path,default=None):
    return json.loads(path.read_text()) if path.exists() else default

def write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(obj,separators=(',',':'),allow_nan=False)+'\n'); tmp.replace(path)

def download(url,target):
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':'ClimateDashboard-Height/1.0','Accept-Encoding':'identity'}),timeout=100) as res, target.open('wb') as f:
                while chunk:=res.read(1024*1024): f.write(chunk)
            with target.open('rb') as f:
                if f.read(4)!=b'GRIB': raise ValueError('Not a GRIB source')
            return
        except Exception:
            target.unlink(missing_ok=True)
            if attempt==2: raise
            time.sleep(5*(attempt+1))

def noaa_url(cycle,lead,levels,analysis=False):
    if analysis:
        params={'file':f'gfs.t{cycle.hour:02d}z.pgrb2full.0p50.f{lead:03d}','dir':f'/gfs.{cycle:%Y%m%d}/{cycle.hour:02d}/atmos'}
        name='filter_gfs_0p50.pl'
    else:
        params={'file':f'geavg.t{cycle.hour:02d}z.pgrb2a.0p50.f{lead:03d}','dir':f'/gefs.{cycle:%Y%m%d}/{cycle.hour:02d}/atmos/pgrb2ap5'}
        name='filter_gefs_atmos_0p50a.pl'
    params.update({'var_HGT':'on','subregion':'','leftlon':'0','rightlon':'359.5','toplat':'90','bottomlat':'60'})
    params.update({f'lev_{p}_mb':'on' for p in levels})
    return f'https://nomads.ncep.noaa.gov/cgi-bin/{name}?'+urlencode(params)

def decode_grib(path,cycle,lead,levels,members,resolution):
    import eccodes as ec
    found={}; weights={}
    with path.open('rb') as f:
        while (h:=ec.codes_grib_new_from_file(f)) is not None:
            try:
                short=str(ec.codes_get(h,'shortName')).lower(); p=int(ec.codes_get(h,'level'))
                if short not in ('gh','hgt','z') or ec.codes_get(h,'typeOfLevel')!='isobaricInhPa' or p not in levels: raise ValueError('Unexpected GRIB field')
                if int(ec.codes_get(h,'dataDate'))!=int(cycle.strftime('%Y%m%d')) or int(ec.codes_get(h,'dataTime'))!=cycle.hour*100 or int(ec.codes_get(h,'endStep'))!=lead: raise ValueError('GRIB run or lead mismatch')
                num=int(ec.codes_get(h,'perturbationNumber')) if len(members)>1 else members[0]
                if num not in members or (num,p) in found: raise ValueError('Unexpected or duplicate ensemble field')
                grid=ec.codes_get(h,'md5GridSection')
                if grid not in weights:
                    lat=np.asarray(ec.codes_get_array(h,'latitudes')); lon=np.asarray(ec.codes_get_array(h,'longitudes'))
                    cap=lat>=60.-.0001
                    ll=np.rint((lon[cap]%360)/resolution).astype(int) % round(360/resolution)
                    la=np.rint(lat[cap]/resolution).astype(int)
                    expect_lat=round(30/resolution)+1; expect_lon=round(360/resolution)
                    if (len(np.unique(la))!=expect_lat or len(np.unique(ll))!=expect_lon or len(ll)!=expect_lat*expect_lon or len(np.unique(la*expect_lon+ll))!=len(ll)):
                        raise ValueError('Incomplete polar grid')
                    weights[grid]=sector_weights(lat,lon)
                raw=np.asarray(ec.codes_get_values(h),dtype=float)
                if int(ec.codes_get(h,'bitmapPresent')):
                    bitmap=np.asarray(ec.codes_get_array(h,'bitmap'))
                    if np.any(bitmap[weights[grid]['polar'][0]]==0): raise ValueError('Missing values in polar cap')
                values=raw/(10*GRAVITY if short=='z' else 10)
                found[num,p]=weighted_means(values,weights[grid])
            finally: ec.codes_release(h)
    if set(found)!={(m,p) for m in members for p in levels}: raise ValueError(f'Incomplete GRIB: {len(found)}/{len(members)*len(levels)}')
    return {r:{str(p):round(float(np.mean([found[m,p][r] for m in members])),4) for p in levels} for r in REGIONS}

def archive_ranges(index,cycle,levels):
    """Select complete HGT GRIB messages for precisely the requested 00Z analysis."""
    records=[]
    for line in index.splitlines():
        fields=line.split(':')
        if len(fields)>=6 and fields[1].isdigit():
            records.append((int(fields[1]),fields))
    offsets=sorted({offset for offset,_ in records})
    ends={a:b-1 for a,b in zip(offsets,offsets[1:])}
    wanted={f'{p} mb':p for p in levels}; found={}
    for offset,fields in records:
        if fields[2]!=f'd={cycle:%Y%m%d%H}' or fields[3]!='HGT' or fields[4] not in wanted or fields[5]!='anl':
            continue
        p=wanted[fields[4]]
        if p in found or offset not in ends: raise ValueError(f'Ambiguous or unbounded HGT archive range at {p} hPa')
        found[p]=(offset,ends[offset])
    return found

def archive_read(url, byte_range=None):
    headers={'User-Agent':'ClimateDashboard-Height/1.0','Accept-Encoding':'identity'}
    if byte_range:
        start,end=byte_range; headers['Range']=f'bytes={start}-{end}'
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers=headers),timeout=60) as response:
                if byte_range:
                    if response.status!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {start}-{end}/'):
                        raise ValueError('Archive server did not return exact byte range')
                    data=response.read(end-start+2)
                    if len(data)!=end-start+1 or not data.startswith(b'GRIB') or not data.endswith(b'7777'):
                        raise ValueError('Incomplete GRIB archive field')
                    return data
                return response.read(2_000_000)
        except (OSError,ValueError):
            if attempt==2: raise
            time.sleep(3*(attempt+1))

def gfs_archive_step(cycle,levels=ECMWF_LEVELS):
    """NOAA's public AWS archive: range fetch only matching analysis fields."""
    remaining=set(levels); root=f'https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{cycle:%Y%m%d}/{cycle.hour:02d}/atmos'
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'gfs.grib2'
        with path.open('wb') as out:
            for product in ('pgrb2','pgrb2b'):
                if not remaining: break
                url=f'{root}/gfs.t{cycle.hour:02d}z.{product}.0p25.f000'
                ranges=archive_ranges(archive_read(url+'.idx').decode('utf-8'),cycle,remaining)
                for p,byte_range in ranges.items():
                    out.write(archive_read(url,byte_range))
                    remaining.remove(p)
        if remaining: raise ValueError(f'GFS archive missing analysis pressure levels: {sorted(remaining)}')
        return decode_grib(path,cycle,0,levels,[0],.25)

def gefs_step(cycle,lead,levels=NOAA_LEVELS,analysis=False):
    if analysis and lead!=0: raise ValueError('Analysis bridge requires lead zero')
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'data.grib2'
        try:
            download(noaa_url(cycle,lead,levels,analysis),path)
            return decode_grib(path,cycle,lead,levels,[0],.5)
        except Exception as exc:
            if not analysis: raise
            print('GFS NOMADS unavailable; trying NOAA AWS archive',cycle.isoformat(),str(exc)[:150],flush=True)
            return gfs_archive_step(cycle,levels)

def ecmwf_step(client,cycle,lead,levels=ECMWF_LEVELS):
    with tempfile.TemporaryDirectory() as td:
        all_rows=[]
        for perturbed in (False,True):
            path=Path(td)/'data.grib2'
            options=dict(date=cycle.strftime('%Y%m%d'),time=0,stream='enfo' if perturbed else 'oper',type='pf' if perturbed else 'fc',levtype='pl',levelist=levels,param='gh',step=lead,target=str(path))
            if perturbed: options['number']=list(range(1,51))
            client.retrieve(**options)
            all_rows.append(decode_grib(path,cycle,lead,levels,list(range(1,51)) if perturbed else [0],.25)); path.unlink()
        return {r:{str(p):round((all_rows[0][r][str(p)]+50*all_rows[1][r][str(p)])/51,4) for p in levels} for r in REGIONS}

def build_forecast(root,model,probe=False):
    now=datetime.now(timezone.utc); cycle=(now-timedelta(hours=9)).replace(hour=0,minute=0,second=0,microsecond=0)
    levels=NOAA_LEVELS if model=='gefs' else ECMWF_LEVELS
    path=root/'forecast.json'; old=read_json(path,{})
    if not probe and validate_forecast(old,model,now) and old['cycle']>=cycle.strftime('%Y-%m-%dT00:00:00Z'): return
    if model=='ecmwf':
        from ecmwf.opendata import Client
        client=Client(source='ecmwf',model='ifs',resol='0p25')
    stamp=cycle.strftime('%Y-%m-%dT00:00:00Z')
    partial=root/'partial.json'
    checkpoint=read_json(partial,{}) if not probe else {}
    days=checkpoint.get('days',{}) if checkpoint.get('cycle')==stamp and checkpoint.get('levels')==levels else {}
    for lead in ([0] if probe else range(0,361,24)):
        valid=(cycle+timedelta(hours=lead)).strftime('%Y-%m-%d')
        if valid in days: continue
        p=([10,500] if model=='ecmwf' else levels) if probe else levels
        row=gefs_step(cycle,lead,p) if model=='gefs' else ecmwf_step(client,cycle,lead,p)
        days[valid]=row
        print(model,cycle.isoformat(),lead,row['polar']['10'],flush=True)
        if not probe: write_json(partial,{'cycle':stamp,'levels':levels,'days':days})
    if probe: return
    payload={'schema':1,'model':model,'cycle':cycle.strftime('%Y-%m-%dT00:00:00Z'),'levels':levels,'days':days,'units':'dam','member_count':31 if model=='gefs' else 51}
    if not validate_forecast(payload,model,now): raise ValueError('Forecast validation failed')
    if old.get('cycle','')>payload['cycle']: raise ValueError('Refusing to overwrite newer run')
    write_json(path,payload)
    partial.unlink(missing_ok=True)

def build_bridge(root):
    path=root/'bridge.json'; rows=read_json(path,{'days':{}})['days']; today=datetime.now(timezone.utc).date()
    def valid_row(row):
        return isinstance(row,dict) and set(row)==set(REGIONS) and all(
            isinstance(sector,dict) and set(sector)=={str(p) for p in ECMWF_LEVELS}
            and all(isinstance(v,(int,float)) and math.isfinite(v) and -150<v<4000 for v in sector.values()) for sector in row.values())
    rows={k:v for k,v in rows.items() if valid_row(v)}
    def save():
        write_json(path,{'schema':1,'source':'GFS operational 00 UTC analysis','days':{k:v for k,v in rows.items() if k>=(today-timedelta(days=85)).isoformat()}})
    for d in range(1,11):
        day=today-timedelta(days=d); iso=day.isoformat()
        if iso in rows: continue
        try:
            row=gefs_step(datetime(day.year,day.month,day.day,tzinfo=timezone.utc),0,ECMWF_LEVELS,analysis=True)
            if not valid_row(row): raise ValueError('Incomplete GFS analysis bridge row')
            rows[iso]=row
            save()
            print('Verified GFS 00 UTC analysis',iso,len(ECMWF_LEVELS),'levels',flush=True)
        except Exception as exc: print('GFS analysis unavailable',iso,str(exc)[:150],flush=True)
    save()
    missing=[(today-timedelta(days=d)).isoformat() for d in range(1,8) if (today-timedelta(days=d)).isoformat() not in rows]
    if missing: raise ValueError('Missing required GFS analysis bridge dates: '+', '.join(missing))

def cds_client():
    import cdsapi
    return cdsapi.Client(url='https://cds.climate.copernicus.eu/api',key=os.environ['CDSAPI_KEY'],quiet=False,progress=False)

def era5_rows(path,expected_dates):
    import xarray as xr
    def process(ds):
        var=ds['z']; latname='latitude'; lonname='longitude'; time_dim='valid_time' if 'valid_time' in var.dims else 'time'; level_dim='pressure_level' if 'pressure_level' in var.dims else 'level'
        if set(var.dims)!={latname,lonname,time_dim,level_dim}: raise ValueError(f'Unexpected ERA5 dimensions {var.dims}')
        lat=np.asarray(ds[latname]); lon=np.asarray(ds[lonname]); ll,la=np.meshgrid(lon,lat)
        if len(lat)!=121 or len(lon)!=1440 or not np.allclose(np.abs(np.diff(lat)),.25) or not np.allclose(np.abs(np.diff(lon)),.25) or min(lat)<59.99 or max(lat)<89.99: raise ValueError('Incomplete ERA5 polar cap')
        weights=sector_weights(la,ll)
        result={}
        for stamp in ds[time_dim].values:
            ts=str(np.datetime_as_string(stamp,unit='h'))
            if not ts.endswith('T00'): raise ValueError('ERA5 not 00 UTC')
            iso=ts[:10]; row={r:{} for r in REGIONS}
            for p in ECMWF_LEVELS:
                f=var.sel({time_dim:stamp,level_dim:p}).transpose(latname,lonname).values/(GRAVITY*10)
                for r,v in weighted_means(f,weights).items(): row[r][str(p)]=round(v,4)
            result[iso]=row
        return result
    if zipfile.is_zipfile(path):
        # CDS sometimes wraps one NetCDF file into a ZIP.
        with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as td:
            names=[n for n in z.namelist() if n.endswith('.nc')]
            if len(names)!=1: raise ValueError('Expected one ERA5 NetCDF')
            dst=Path(td)/'era5.nc'; dst.write_bytes(z.read(names[0]))
            with xr.open_dataset(dst) as ds: rows=process(ds)
    else:
        with xr.open_dataset(path) as ds: rows=process(ds)
    if set(rows)!=set(expected_dates): raise ValueError('Incomplete ERA5 dates')
    return rows

def retrieve_era5(client,year,month,days):
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'era5.nc'; dates=[date(year,month,d).isoformat() for d in days]
        request={'product_type':['reanalysis'],'variable':['geopotential'],'year':[str(year)],'month':[f'{month:02d}'],'day':[f'{d:02d}' for d in days],'time':['00:00'],'pressure_level':[str(p) for p in ECMWF_LEVELS],'area':[90,-180,60,179.75],'data_format':'netcdf','download_format':'unarchived'}
        print('ERA5',year,month,days[0],days[-1],flush=True)
        client.retrieve('reanalysis-era5-pressure-levels',request,str(path))
        return era5_rows(path,dates)

def month_priority(today):
    return list(dict.fromkeys([today.month, today.month%12+1, (today.month-2)%12+1,(today.month-3)%12+1]+[(today.month+i-1)%12+1 for i in range(12)]))

def pending_reference(root):
    for month in month_priority(date.today()):
        for year in REF_YEARS:
            if not (root/'reference_parts'/f'{year}-{month:02d}.json').is_file(): yield f'{year}-{month:02d}'

def build_reference(root,key):
    year,month=map(int,key.split('-')); days=list(range(1,calendar.monthrange(year,month)[1]+1))
    rows=retrieve_era5(cds_client(),year,month,days)
    write_json(root/'reference_parts'/f'{key}.json',rows)
    aggregate_reference(root)

def aggregate_reference(root):
    parts=list((root/'reference_parts').glob('*.json'))
    if not parts: return
    old=read_json(root/'reference.json',{})
    if old.get('months_complete')==len(parts): return
    combined={}
    for path in parts: combined.update(read_json(path,{}))
    values=reference_means(combined)
    expected={str(p) for p in ECMWF_LEVELS}
    values={md:row for md,row in values.items() if all(set(row[r])==expected for r in REGIONS)}
    write_json(root/'reference.json',{'schema':1,'source':'ERA5 00 UTC 1991–2020','period':[1991,2020],'units':'dam','levels':ECMWF_LEVELS,'days':values,'months_complete':len(parts),'months_total':360})

def build_analysis(root):
    path=root/'analysis.json'; rows=read_json(path,{'days':{}})['days']; today=datetime.now(timezone.utc).date(); last=today-timedelta(days=7); start=today-timedelta(days=90)
    wanted={}
    for i in range((last-start).days+1):
        day=start+timedelta(days=i)
        if day.isoformat() not in rows or (today.weekday()==0 and day>=last-timedelta(days=10)): wanted.setdefault((day.year,day.month),[]).append(day.day)
    client=cds_client()
    for (year,month),days in sorted(wanted.items(),reverse=True):
        rows.update(retrieve_era5(client,year,month,days))
        write_json(path,{'schema':1,'source':'ERA5 00 UTC','units':'dam','days':{k:v for k,v in rows.items() if k>=start.isoformat()}})

def main():
    cli=argparse.ArgumentParser(); cli.add_argument('--root',required=True,type=Path); actions=cli.add_mutually_exclusive_group(required=True)
    actions.add_argument('--forecast',choices=['gefs','ecmwf']); actions.add_argument('--bridge',action='store_true'); actions.add_argument('--analysis',action='store_true'); actions.add_argument('--reference'); actions.add_argument('--list-reference',action='store_true'); actions.add_argument('--probe',choices=['gefs','ecmwf','bridge'])
    a=cli.parse_args()
    if a.forecast: build_forecast(a.root,a.forecast)
    elif a.probe=='bridge':
        build_bridge(a.root)
        day=(datetime.now(timezone.utc)-timedelta(days=2)).replace(hour=0,minute=0,second=0,microsecond=0)
        row=gfs_archive_step(day)
        print('Verified independent NOAA archive',day.isoformat(),row['polar']['10'],flush=True)
    elif a.probe: build_forecast(a.root,a.probe,True)
    elif a.bridge: build_bridge(a.root)
    elif a.analysis: build_analysis(a.root)
    elif a.reference: build_reference(a.root,a.reference)
    else:
        aggregate_reference(a.root)
        print('\n'.join(pending_reference(a.root)))

if __name__=='__main__': main()

