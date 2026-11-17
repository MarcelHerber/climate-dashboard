"""Horizontal pressure-level temperature advection from genuine IFS grids.

Advection is the instantaneous tendency scaled to K/6 h, not an observed
six-hour temperature change. Mask pressure levels underground before taking
derivatives; interpolate T/U/V/surface pressure before calculating advection.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter
from satellite_disk_model import crop_grid, disk_candidate_visible

LEVELS = (925, 850, 700)
METHOD = "ifs_temperature_advection_v1"
RADIUS_M = 6371000.
LEADS = (0, 3, 6, 9, 12, 15, 18)
BBOX = (-75., 12., 55., 80.)


def advection_field(x, y, t, u, v, sp, level):
    t = np.where(np.asarray(sp) >= level*100., t, np.nan)
    dy = np.deg2rad(y)*RADIUS_M
    dlon = np.deg2rad(x)*RADIUS_M
    dtdy = np.gradient(t, dy, axis=0)
    dtdx = np.gradient(t, dlon, axis=1)/np.cos(np.deg2rad(y))[:, None]
    a = -(u*dtdx+v*dtdy)*21600.
    return np.where(np.isfinite(t), a, np.nan)


def select_markers(x, y, a, u, v, *, disk=False):
    """Rank coherent local advection, then suppress neighboring samples."""
    good = np.isfinite(a) & np.isfinite(u) & np.isfinite(v)
    sigma = (.75/abs(float(np.median(np.diff(y)))), .75/abs(float(np.median(np.diff(x)))))
    weight = gaussian_filter(good.astype(float), sigma)
    smooth = gaussian_filter(np.where(good, a, 0.), sigma)/np.maximum(weight, 1e-6)
    mask = good & (weight >= .8) & (np.abs(smooth) >= 2) & (np.hypot(u,v) >= 2) & (np.hypot(np.round(u,1),np.round(v,1)) >= 2) & (a*smooth > 0)
    # Around 1 degree sampling, retaining weaker local features on small maps.
    sy = max(1, round(.75/abs(float(np.median(np.diff(y))))))
    sx = max(1, round(.75/abs(float(np.median(np.diff(x))))))
    sampled = np.zeros_like(mask)
    sampled[::sy, ::sx] = True
    rows, cols = np.where(mask & sampled)
    if disk:
        visible = disk_candidate_visible(x[cols], y[rows])
        rows, cols = rows[visible], cols[visible]
    scores = np.abs(smooth[rows, cols])
    # Unit-sphere vectors provide latitude-correct geodesic separation.
    lat, lon = np.deg2rad(y[rows]), np.deg2rad(x[cols])
    xyz = np.column_stack((np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)))
    order = np.argsort(-scores, kind="stable")
    if disk:
        # Interleave the strongest significant candidate in each ~40 degree
        # sector. A northern storm track must not consume all 220 slots.
        sectors = (np.floor((y[rows]+90)/40).astype(int)*5
                   + np.floor((x[cols]+90)/40).astype(int))
        pools = [order[sectors[order] == s] for s in np.unique(sectors)]
        order = [p[k] for k in range(max(map(len, pools), default=0))
                 for p in pools if len(p) > k]
    available = np.ones(len(rows), dtype=bool)
    markers = []
    for k in order:
        if not available[k]:
            continue
        i, j = rows[k], cols[k]
        markers.append(dict(lon=round(float(x[j]),3), lat=round(float(y[i]),3),
                            advection=round(float(smooth[i,j]),1),
                            u=round(float(u[i,j]),1), v=round(float(v[i,j]),1)))
        available &= ((xyz-xyz[k])**2).sum(axis=1) > (175000/RADIUS_M)**2
        if len(markers) >= 220:
            break
    return markers


def interpolate_fields(grids, minute, level=850):
    if minute < 0 or minute > max(grids)*60 or minute % 10:
        raise ValueError("Advection outside verified ten-minute interval")
    low, high = minute//180*3, min(max(grids), minute//180*3+3)
    a = grids[low]
    if low == high or minute == low*60:
        return a
    b = grids[high]
    if not all(np.array_equal(p,q) for p,q in zip(a[:2],b[:2])):
        raise ValueError("IFS advection grids are incompatible")
    f = (minute-low*60)/((high-low)*60)
    above = (a[-1]>=level*100.) & (b[-1]>=level*100.)
    return (*a[:2], *(np.where(above,p*(1-f)+q*f,np.nan) for p,q in zip(a[2:5],b[2:5])),
            a[-1]*(1-f)+b[-1]*f)


def frame_markers(grids, minute, *, disk=False):
    result = {}
    for level in LEVELS:
        x,y,t,u,v,sp = interpolate_fields(grids[level],minute,level)
        result[str(level)] = select_markers(x,y,advection_field(x,y,t,u,v,sp,level),u,v,disk=disk)
    return result


def crop_grids(grids):
    return {level: {step: crop_grid(value, BBOX) for step, value in steps.items()}
            for level, steps in grids.items()}


def retrieve(run, path, leads=LEADS, *, bbox=BBOX):
    """Get pressure-level winds, temperature and surface pressure separately."""
    from ecmwf.opendata import Client
    path = Path(path)
    surface = path.with_name(path.stem+'-surface.grib2')
    errors = []
    for source in ('ecmwf','aws'):
        try:
            path.unlink(missing_ok=True)
            surface.unlink(missing_ok=True)
            c = Client(source=source, model='ifs', resol='0p25', maximum_retries=2,
                       retry_after=3, use_server_retry_after=False)
            kwargs = dict(date=run.strftime('%Y-%m-%d'), time=run.hour,
                          stream='oper', type='fc', step=list(leads))
            c.retrieve(**kwargs, levtype='pl', param=['t','u','v'],
                       levelist=list(LEVELS), target=str(path))
            c.retrieve(**kwargs, levtype='sfc', param='sp', target=str(surface))
            return decode((path,surface),run,leads,bbox=bbox)
        except Exception as exc:
            logging.warning('Advection %s unavailable: %s',source,exc)
            errors.append(str(exc))
    raise RuntimeError('IFS advection unavailable: '+'; '.join(errors))


def decode(paths,run,leads=LEADS, *, bbox=BBOX):
    from eccodes import codes_get, codes_get_array, codes_grib_new_from_file, codes_release
    fields = {}
    axes = None
    for path in paths:
        with Path(path).open('rb') as fp:
            while (msg := codes_grib_new_from_file(fp)) is not None:
                try:
                    param = str(codes_get(msg,'shortName'))
                    level = 0 if param=='sp' else int(codes_get(msg,'level'))
                    step = int(codes_get(msg,'endStep'))
                    if step not in leads or (param!='sp' and (param not in ('t','u','v') or level not in LEVELS)):
                        continue
                    origin = dt.datetime.strptime(f'{int(codes_get(msg,"dataDate")):08d}{int(codes_get(msg,"dataTime")):04d}', '%Y%m%d%H%M').replace(tzinfo=dt.timezone.utc)
                    if origin != run:
                        raise ValueError('IFS advection GRIB run mismatch')
                    ni,nj = int(codes_get(msg,'Ni')),int(codes_get(msg,'Nj'))
                    lat = np.asarray(codes_get_array(msg,'latitudes')).reshape(nj,ni)[:,0]
                    lon = (np.asarray(codes_get_array(msg,'longitudes')).reshape(nj,ni)[0,:]+180)%360-180
                    rows = np.flatnonzero((lat>=bbox[1])&(lat<=bbox[3]))
                    cols = np.flatnonzero((lon>=bbox[0])&(lon<=bbox[2]))
                    rows,cols = rows[np.argsort(lat[rows])],cols[np.argsort(lon[cols])]
                    x,y = lon[cols],lat[rows]
                    if (len(x)<500 or len(y)<260 or not np.allclose(np.diff(x),.25)
                            or not np.allclose(np.diff(y),.25)
                            or not np.allclose((x[0],y[0],x[-1],y[-1]),bbox,atol=.001)):
                        raise ValueError('Incomplete IFS 0.25-degree advection grid')
                    if axes is not None and (not np.array_equal(axes[0],x) or not np.array_equal(axes[1],y)):
                        raise ValueError('Inconsistent IFS advection coordinates')
                    axes = (x,y)
                    field = np.asarray(codes_get_array(msg,'values')).reshape(nj,ni)[np.ix_(rows,cols)]
                    limits = {'t':(180,340),'u':(-150,150),'v':(-150,150),'sp':(30000,110000)}[param]
                    if not np.isfinite(field).all() or field.min()<limits[0] or field.max()>limits[1]:
                        raise ValueError('Invalid IFS values for '+param)
                    fields[step,level,param] = field
                finally:
                    codes_release(msg)
    if axes is None:
        raise ValueError('No IFS advection fields')
    return {level:{step:(*axes, *(fields[step,level,p] for p in ('t','u','v')),fields[step,0,'sp'])
                   for step in leads} for level in LEVELS}
