#!/usr/bin/env python3
"""Independent monthly ERA5 Greenland Blocking Index, not an EOF index.

Z500 over 60–80°N, 80–20°W, cosine latitude weighting; calendar-month
sample standard deviation and climatology 1991–2020. NOAA is not spliced in.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from math import isfinite
from pathlib import Path
from statistics import mean, stdev

DATASET = 'reanalysis-era5-pressure-levels-monthly-means'
SOURCE_URL = 'https://cds.climate.copernicus.eu/datasets/' + DATASET
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'climate_indices/gbi_era5.json'
CACHE = ROOT / '.era5_gbi_cache'
METHOD = ('ERA5 monatliches 500-hPa-Geopotential, geteilt durch g=9,80665 m/s²; '
          'flächengewichtetes Gebietsmittel 60–80°N, 80–20°W (cos Breite), '
          'Monatsanomalie / Stichproben-Standardabweichung 1991–2020')


def area_mean(values, lat, lon):
    import numpy as np

    lat, lon = np.asarray(lat), ((np.asarray(lon) + 180) % 360) - 180
    values = np.asarray(values, dtype=np.float64)
    if (lat.shape != (81,) or lon.shape != (241,) or values.ndim != 3
            or values.shape[1:] != (81, 241)
            or not np.allclose(np.sort(lat), np.arange(60, 80.25, .25), rtol=0, atol=1e-6)
            or not np.allclose(np.sort(lon), np.arange(-80, -19.75, .25), rtol=0, atol=1e-6)
            or not np.isfinite(values).all()):
        raise ValueError('ERA5 Z500 grid must be complete at 0.25°')
    heights = np.average(values.mean(axis=2), weights=np.cos(np.deg2rad(lat)), axis=1) / 9.80665
    if not ((4300 < heights) & (heights < 6100)).all():
        raise ValueError('ERA5 Z500 outside plausible geopotential-height range')
    return heights


def month_range(first: str, last: str):
    year, month = map(int, first.split('-'))
    finish = date.fromisoformat(last + '-01')
    while date(year, month, 1) <= finish:
        yield f'{year:04d}-{month:02d}'
        year, month = year + (month == 12), month % 12 + 1


def validate_archive(archive, *, expected_latest=None):
    if (not isinstance(archive, dict) or archive.get('source') != 'ERA5'
            or archive.get('source_url') != SOURCE_URL or archive.get('reference') != '1991–2020'
            or archive.get('reference_years') != 30 or archive.get('reference_months') != 360
            or archive.get('first_month') != '1940-01'):
        raise ValueError('ERA5 GBI source/reference metadata invalid')
    rows = archive.get('monthly')
    if (not isinstance(rows, list) or not rows or not all(
            isinstance(row, list) and len(row) == 2 and isinstance(row[0], str)
            and isinstance(row[1], (int, float)) and not isinstance(row[1], bool)
            and isfinite(row[1]) for row in rows)):
        raise ValueError('ERA5 GBI monthly rows invalid')
    latest = archive.get('latest_month')
    if (not isinstance(latest, str) or latest < '2020-12' or latest >= date.today().strftime('%Y-%m')
            or (expected_latest is not None and latest != expected_latest)
            or [r[0] for r in rows] != list(month_range('1940-01', latest))):
        raise ValueError('ERA5 GBI month coverage incomplete')
    for month in range(1, 13):
        vals = [v for ym, v in rows if '1991-01' <= ym <= '2020-12' and int(ym[5:]) == month]
        if len(vals) != 30 or abs(mean(vals)) > .001 or abs(stdev(vals) - 1) > .001:
            raise ValueError('ERA5 GBI calendar-month reference normalization invalid')
    return archive


def build_archive(heights: dict[str, float]):
    latest = max(heights)
    expected = list(month_range('1940-01', latest))
    if sorted(heights) != expected or not all(isfinite(v) and 4300 < v < 6100 for v in heights.values()):
        raise ValueError('ERA5 GBI heights archive has incomplete or invalid monthly values')
    reference = {m: [heights[f'{y}-{m:02d}'] for y in range(1991, 2021)
                     if f'{y}-{m:02d}' in heights] for m in range(1, 13)}
    if any(len(vals) != 30 or stdev(vals) <= 0 for vals in reference.values()):
        raise ValueError('ERA5 GBI reference requires 30 complete years with finite variability')
    means = {m: mean(vals) for m, vals in reference.items()}
    deviations = {m: stdev(vals) for m, vals in reference.items()}
    rows = [[ym, round((heights[ym] - means[int(ym[5:])]) / deviations[int(ym[5:])], 3)]
            for ym in expected]
    return validate_archive({'schema': 1, 'ready': True, 'source': 'ERA5', 'source_url': SOURCE_URL,
        'label': 'Grönland-Blocking (GBI · ERA5)', 'unit': 'σ', 'method': METHOD,
        'reference': '1991–2020', 'reference_years': 30, 'reference_months': 360,
        'reference_metadata': {'start_year': 1991, 'end_year': 2020, 'months': 360},
        'first_month': expected[0], 'latest_month': latest, 'monthly': rows})


def read_netcdf(path, expected):
    import numpy as np
    import xarray as xr

    with xr.open_dataset(path) as ds:
        if 'z' not in ds:
            raise ValueError('ERA5 geopotential variable z missing')
        da = ds['z']
        if ''.join(da.attrs.get('units', '').split()) not in ('m**2s**-2', 'm2s-2', 'm^2s^-2'):
            raise ValueError('ERA5 geopotential units invalid')
        level_name = next((name for name in ('pressure_level', 'level') if name in da.coords), None)
        if level_name is None or list(np.asarray(da[level_name].values).reshape(-1)) != [500]:
            raise ValueError('ERA5 requires exactly 500 hPa')
        time = next((name for name in ('valid_time', 'time') if name in da.dims), None)
        if time is None:
            raise ValueError('ERA5 time coordinate missing')
        for dim in tuple(da.dims):
            if dim in (time, 'latitude', 'longitude'):
                continue
            if da.sizes[dim] != 1:
                raise ValueError('Unexpected ERA5 dimension ' + dim)
            da = da.isel({dim: 0}, drop=True)
        da = da.transpose(time, 'latitude', 'longitude')
        months = [np.datetime_as_string(np.datetime64(t), unit='M') for t in da[time].values]
        if sorted(months) != expected or len(set(months)) != len(months):
            raise ValueError('ERA5 NetCDF missing/duplicate month')
        means = area_mean(da.values, da.latitude.values, da.longitude.values)
        return {month: float(v) for month, v in zip(months, means)}


def write_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def retrieve_chunk(client, years, months, *, cache):
    expected = [f'{y:04d}-{m:02d}' for y in years for m in months]
    name = f'{expected[0]}_{expected[-1]}'
    data_path = CACHE / (name + '.json')
    if cache and data_path.exists():
        values = json.loads(data_path.read_text(encoding='utf-8'))
        if sorted(values) == expected and all(isinstance(v, (float, int)) and 4300 < v < 6100 for v in values.values()):
            return values
    CACHE.mkdir(parents=True, exist_ok=True)
    netcdf = CACHE / (name + '.nc')
    try:
        client.retrieve(DATASET, {'product_type': ['monthly_averaged_reanalysis'],
            'variable': ['geopotential'], 'pressure_level': ['500'], 'year': [str(y) for y in years],
            'month': [f'{m:02d}' for m in months], 'time': ['00:00'],
            'data_format': 'netcdf', 'download_format': 'unarchived', 'area': [80, -80, 60, -20]}, str(netcdf))
        values = read_netcdf(netcdf, expected)
        if cache:
            write_atomic(data_path, values)
        return values
    finally:
        netcdf.unlink(missing_ok=True)


def main():
    import cdsapi

    now = datetime.now(timezone.utc).date()
    offset = 1 if now.day >= 7 else 2
    y, m = divmod(now.year * 12 + now.month - 1 - offset, 12)
    latest = f'{y:04d}-{m + 1:02d}'
    client = cdsapi.Client(timeout=180)
    values = {}
    for start in range(1940, y, 10):
        end = min(start + 10, y)
        print(f'ERA5 GBI: {start}–{end - 1}', flush=True)
        values.update(retrieve_chunk(client, list(range(start, end)), list(range(1, 13)), cache=True))
    values.update(retrieve_chunk(client, [y], list(range(1, m + 2)), cache=False))
    archive = build_archive(values)
    validate_archive(archive, expected_latest=latest)
    write_atomic(OUTPUT, archive)
    print(f'ERA5 GBI ready: {archive["first_month"]}–{latest}, {len(values)} Monate', flush=True)


if __name__ == '__main__':
    main()
