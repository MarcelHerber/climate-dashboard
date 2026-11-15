#!/usr/bin/env python3
"""IFS Open Data 0.1° 7-day means, compared with ERA5 1991–2020.

The forecast is native 0.1°; only the independent ERA5 0.25° normals are
bilinearly remapped. Every valid UTC time has its own calendar-day/hour normal.
No extrapolation, missing-field substitution, or fabricated model climate.
"""
from __future__ import annotations

import argparse
import base64
import calendar
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from pathlib import Path
import tempfile

import numpy as np

LEADS = tuple(range(0, 169, 6))
HOURS = (0, 6, 12, 18)
YEARS = tuple(range(1991, 2021))
NORTH, SOUTH, WEST, EAST = 85., 25., -80., 100.
LAT = np.linspace(NORTH, SOUTH, 601)
LON = np.linspace(WEST, EAST, 1801)
REF_LAT = np.linspace(NORTH, SOUTH, 241)
REF_LON = np.linspace(WEST, EAST, 721)
VERSION = 'era5-t2m-calendar-hour-1991-2020-v1'


def valid_times(run):
    if run.tzinfo is None or run.utcoffset() != timedelta(0) or run.hour not in (0, 12) or run.minute or run.second or run.microsecond:
        raise ValueError('Expected a 00 or 12 UTC IFS initialization')
    return tuple(run + timedelta(hours=h) for h in LEADS)


def weekly_mean(fields):
    if set(fields) != set(LEADS):
        raise ValueError('All 29 original six-hourly fields are required')
    first = np.asarray(fields[0], dtype=np.float64)
    total = np.zeros_like(first)
    for h in LEADS:
        field = np.asarray(fields[h])
        if field.shape != first.shape or not np.isfinite(field).all():
            raise ValueError('Missing/nonfinite or inconsistent field')
        total += field * (0.5 if h in (0, 168) else 1.)
    return total / 28.


def era5_expected(year, month):
    first = np.datetime64(f'{year:04d}-{month:02d}-01T00', 'h')
    return first + np.arange(calendar.monthrange(year, month)[1]*4)*np.timedelta64(6, 'h')


def normals_from_year(year, month, times, values):
    actual = np.asarray(times).astype('datetime64[ns]')
    expected = era5_expected(year, month).astype('datetime64[ns]')
    order = np.argsort(actual)
    if not np.array_equal(actual[order], expected):
        raise ValueError('Incomplete, duplicate or wrong ERA5 UTC timestamps')
    values = np.asarray(values)[order]
    if values.ndim != 3 or len(values) != len(expected) or not np.isfinite(values).all() or np.any((values < 170) | (values > 340)):
        raise ValueError('Invalid ERA5 2m temperature values in Kelvin')
    return values.reshape(-1, 4, *values.shape[1:])


def interpolate_reference(field, old_lat, old_lon, lat, lon):
    from scipy.interpolate import RegularGridInterpolator
    field = np.asarray(field)
    old_lat, old_lon = np.asarray(old_lat), np.asarray(old_lon)
    if field.shape != (len(old_lat), len(old_lon)) or not np.isfinite(field).all():
        raise ValueError('Invalid reference array')
    interp = RegularGridInterpolator((old_lat[::-1], old_lon), field[::-1], method='linear', bounds_error=True)
    yy, xx = np.meshgrid(lat, lon, indexing='ij')
    result = interp((yy, xx))
    if not np.isfinite(result).all():
        raise ValueError('Reference interpolation produced missing cells')
    return result


def iso(dt):
    return dt.isoformat().replace('+00:00', 'Z')


def encode(field):
    q = np.rint(np.asarray(field)*10)
    if not np.isfinite(q).all() or np.any(np.abs(q) >= 32767):
        raise ValueError('Field cannot be encoded without losing data')
    return base64.b64encode(q.astype('<i2').tobytes()).decode('ascii')


def validate_forecast_metadata(info, run):
    times=valid_times(run)
    if (info.get('schema')!=1 or info.get('type')!='ifs_0p1_seven_day_forecast'
            or (info.get('grid_degrees'),info.get('width'),info.get('height')) != (.1,1801,601)
            or tuple(info.get(k) for k in ('lat_north','lat_south','lon_west','lon_east'))!=(85.,25.,-80.,100.)
            or info.get('period_days')!=7 or info.get('sample_count')!=29 or info.get('lead_hours')!=list(LEADS)
            or info.get('run_utc')!=iso(run) or info.get('valid_from_utc')!=iso(times[0]) or info.get('valid_to_utc')!=iso(times[-1])
            or len(info.get('sources',[]))!=29):
        raise ValueError('Forecast metadata does not match native IFS 0.1° seven-day grid')
    for row,h,t in zip(info['sources'],LEADS,times):
        if row.get('forecast_hour')!=h or row.get('valid_utc')!=iso(t) or not re.fullmatch(r'[a-f0-9]{64}',row.get('sha256','')) or row.get('bytes',0)<1000:
            raise ValueError('Incomplete or inconsistent original-field provenance')


def decode_ifs(gid, ec, run, lead):
    get = lambda key: ec.codes_get(gid, key)
    if (get('edition') != 2 or get('typeOfLevel') != 'heightAboveGround' or get('level') != 2
            or get('discipline') != 0 or get('parameterCategory') != 0 or get('parameterNumber') != 0
            or get('stepType') != 'instant' or int(get('endStep')) != lead):
        raise ValueError('Not the requested instantaneous 2m forecast')
    valid = run + timedelta(hours=lead)
    for key, expected in [('dataDate', int(run.strftime('%Y%m%d'))), ('dataTime', run.hour*100),
                          ('validityDate', int(valid.strftime('%Y%m%d'))), ('validityTime', valid.hour*100)]:
        if int(get(key)) != expected:
            raise ValueError(f'IFS metadata mismatch: {key}')
    if (get('gridType') != 'regular_ll' or (int(get('Ni')), int(get('Nj'))) != (3600, 1801)
            or abs(float(get('iDirectionIncrementInDegrees'))-.1) > 1e-6
            or abs(float(get('jDirectionIncrementInDegrees'))-.1) > 1e-6
            or abs(float(get('latitudeOfFirstGridPointInDegrees'))-90.) > 1e-6
            or any(int(get(k)) != 0 for k in ('iScansNegatively','jScansPositively','jPointsAreConsecutive','alternativeRowScanning'))):
        raise ValueError('Not a native 0.1° global regular IFS grid')
    origin = float(get('longitudeOfFirstGridPointInDegrees'))
    ix_float = ((LON-origin) % 360.)*10.
    idx = np.rint(ix_float).astype(int) % 3600
    if not np.allclose(ix_float, np.rint(ix_float), atol=1e-5, rtol=0):
        raise ValueError('Non-aligned native longitudes')
    vals = np.asarray(ec.codes_get_values(gid), dtype=np.float32).reshape(1801, 3600)
    crop = vals[50:651, :][:, idx]
    if crop.shape != (601, 1801) or not np.isfinite(crop).all() or np.any((crop < 170) | (crop > 340)):
        raise ValueError('Invalid IFS European crop')
    return crop


def fetch_ifs(out, source='ecmwf'):
    import eccodes as ec
    from ecmwf.opendata import Client
    client = Client(source=source, model='ifs', resol='0p1')
    now = datetime.now(timezone.utc)
    latest = now.replace(hour=(now.hour//12)*12, minute=0, second=0, microsecond=0)
    fields, sources = {}, []
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/'2t.grib2'
        def retrieve(run, h):
            path.unlink(missing_ok=True)
            client.retrieve(date=run.strftime('%Y%m%d'), time=run.hour, stream='oper', type='fc',
                            levtype='sfc', param='2t', step=h, target=str(path))
            raw = path.read_bytes()
            with path.open('rb') as f:
                gid = ec.codes_grib_new_from_file(f)
                if gid is None:
                    raise ValueError('No GRIB message received')
                try:
                    field = decode_ifs(gid, ec, run, h)
                finally:
                    ec.codes_release(gid)
                other = ec.codes_grib_new_from_file(f)
                if other is not None:
                    ec.codes_release(other)
                    raise ValueError('Unexpected extra GRIB message')
            return field, {'forecast_hour':h,'valid_utc':iso(run+timedelta(hours=h)),
                           'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
        for lag in (0,1,2,3,4):
            run = latest - timedelta(hours=12*lag)
            try:
                last, provenance = retrieve(run, 168)
                break
            except Exception as err:
                print(f'IFS {run} +168 unavailable: {err}', flush=True)
        else:
            raise RuntimeError('No complete native 0.1° IFS run available')
        for h in LEADS:
            field, record = (last, provenance) if h == 168 else retrieve(run, h)
            fields[h] = field; sources.append(record)
            print(f'Verified IFS 0.1° {iso(run)} +{h:03d} h', flush=True)
    mean_c = (weekly_mean(fields) - 273.15).astype(np.float32)
    info = {'schema':1,'type':'ifs_0p1_seven_day_forecast','provider':'ECMWF IFS Open Data 0.1° (CC BY 4.0)',
            'grid_degrees':.1,'width':len(LON),'height':len(LAT),'lat_north':NORTH,'lat_south':SOUTH,'lon_west':WEST,'lon_east':EAST,
            'period_days':7,'sample_count':len(LEADS),'lead_hours':list(LEADS),'run_utc':iso(run),
            'valid_from_utc':iso(run),'valid_to_utc':iso(run+timedelta(hours=168)),
            'sources':sources,'forecast_mean_q10_b64':encode(mean_c),'reference_ready':False}
    validate_forecast_metadata(info,run)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out/'forecast.npz', mean_c=mean_c.astype(np.float32), run_utc=iso(run))
    (out/'forecast.json').write_text(json.dumps(info, separators=(',',':'),ensure_ascii=False),encoding='utf-8')


def build_month(month, output):
    import cdsapi
    import xarray as xr
    client = cdsapi.Client()
    max_days = calendar.monthrange(2000,month)[1]
    sums = np.zeros((max_days,4,len(REF_LAT),len(REF_LON)), dtype=np.float64)
    counts = np.zeros(max_days,dtype=np.int16)
    sources = []
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/'era5.nc'
        for year in YEARS:
            path.unlink(missing_ok=True)
            days = calendar.monthrange(year, month)[1]
            request = {'product_type':['reanalysis'],'variable':['2m_temperature'],'year':[str(year)],'month':[f'{month:02d}'],
                       'day':[f'{d:02d}' for d in range(1,days+1)],'time':[f'{h:02d}:00' for h in HOURS],
                       'area':[NORTH,WEST,SOUTH,EAST],'data_format':'netcdf','download_format':'unarchived'}
            client.retrieve('reanalysis-era5-single-levels',request,str(path))
            with xr.open_dataset(path) as ds:
                da = ds['t2m']
                time_name = 'valid_time' if 'valid_time' in da.dims else 'time'
                da = da.transpose(time_name,'latitude','longitude').sortby('latitude',ascending=False)
                da = da.assign_coords(longitude=((da.longitude+180)%360)-180).sortby('longitude')
                if da.shape[1:] != (len(REF_LAT),len(REF_LON)) or not np.allclose(da.latitude,REF_LAT) or not np.allclose(da.longitude,REF_LON) or da.attrs.get('units') not in ('K','kelvin'):
                    raise ValueError('ERA5 original 0.25° grid/unit mismatch')
                normalized = normals_from_year(year,month,da[time_name].values,da.values)
                sums[:days] += normalized
            counts[:days] += 1
            with path.open('rb') as f:
                digest = hashlib.file_digest(f,'sha256').hexdigest()
            sources.append({'year':year,'hours':days*4,'sha256':digest})
            print(f'ERA5 verified {year}-{month:02d}: {days*4} original fields',flush=True)
    expected = np.array([sum(calendar.monthrange(y,month)[1]>=d for y in YEARS) for d in range(1,max_days+1)])
    if not np.array_equal(counts,expected):
        raise ValueError('Incomplete 30-year calendar reference')
    normal = (sums/counts[:,None,None,None]).astype(np.float32)
    output.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(output, normal=normal, counts=counts, lat=REF_LAT, lon=REF_LON,
                        metadata=json.dumps({'version':VERSION,'month':month,'years':list(YEARS),'sources':sources,'hours_utc':list(HOURS)}))


def reference_week(run, refs):
    grid = {}
    loaded = {}
    provenance = []
    for lead, valid in zip(LEADS,valid_times(run)):
        m = valid.month
        if m not in loaded:
            path = refs/f'era5_{m:02d}.npz'
            with np.load(path,allow_pickle=False) as r:
                meta = json.loads(r['metadata'].item()); counts=r['counts']; normal=r['normal']
                days = calendar.monthrange(2000,m)[1]
                expected = [sum(calendar.monthrange(y,m)[1]>=d for y in YEARS) for d in range(1,days+1)]
                if (meta['version']!=VERSION or meta['month']!=m or meta['years']!=list(YEARS) or meta['hours_utc']!=list(HOURS)
                        or [s['year'] for s in meta['sources']]!=list(YEARS) or any(len(s['sha256'])!=64 or s['hours']!=calendar.monthrange(s['year'],m)[1]*4 for s in meta['sources'])
                        or not np.array_equal(counts,expected) or normal.shape!=(days,4,len(REF_LAT),len(REF_LON))
                        or not np.allclose(r['lat'],REF_LAT) or not np.allclose(r['lon'],REF_LON)
                        or not np.isfinite(normal).all() or np.any((normal<170)|(normal>340))):
                    raise ValueError('Unverified ERA5 monthly reference')
                loaded[m]=normal
                provenance.append({'month':m,'years':30,'source_fields':sum(s['hours'] for s in meta['sources'])})
        grid[lead] = loaded[m][valid.day-1,HOURS.index(valid.hour)]
    native_mean = weekly_mean(grid)
    return interpolate_reference(native_mean,REF_LAT,REF_LON,LAT,LON)-273.15,provenance


def combine(forecast, refs, output):
    info = json.loads((forecast/'forecast.json').read_text())
    with np.load(forecast/'forecast.npz',allow_pickle=False) as f:
        run = datetime.fromisoformat(f['run_utc'].item().replace('Z','+00:00'))
        mean = f['mean_c']
    validate_forecast_metadata(info,run)
    if mean.shape!=(len(LAT),len(LON)) or info['forecast_mean_q10_b64']!=encode(mean):
        raise ValueError('Inconsistent 0.1° IFS seven-day input')
    reference, provenance = reference_week(run,refs)
    info.update(reference_ready=True,reference_version=VERSION,
                reference_metadata={'period':'1991–2020','years':30,'native_grid_degrees':.25,'interpolation':'bilinear','months':provenance},
                anomaly_mean_q10_b64=encode(mean-reference))
    output.parent.mkdir(parents=True,exist_ok=True)
    tmp=output.with_suffix('.tmp')
    tmp.write_text(json.dumps(info,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    tmp.replace(output)


if __name__ == '__main__':
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    f=sub.add_parser('forecast'); f.add_argument('--out',type=Path,required=True); f.add_argument('--source',default='ecmwf')
    m=sub.add_parser('reference'); m.add_argument('--month',type=int,choices=range(1,13),required=True); m.add_argument('--out',type=Path,required=True)
    c=sub.add_parser('combine'); c.add_argument('--forecast',type=Path,required=True); c.add_argument('--references',type=Path,required=True); c.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.command=='forecast': fetch_ifs(a.out,a.source)
    elif a.command=='reference': build_month(a.month,a.out)
    else: combine(a.forecast,a.references,a.out)
