"""Native-grid NOAA OISST daily area means for the existing rectangular SST maps.

Data snapshots contain only annual and region CSVs, never downloaded grids.
Valid SST (including NOAA's sea-ice SST estimate) is weighted by cos(latitude).
"""
from __future__ import annotations

import argparse
import calendar
import csv
from datetime import date, timedelta
from pathlib import Path
import tempfile
import time
from urllib.request import Request, urlopen

import numpy as np

from .config import ALL_REGIONS

START_YEAR = 1982
BASE = 'https://psl.noaa.gov/thredds/fileServer/Datasets/noaa.oisst.v2.highres/'
MIRROR = 'https://downloads.psl.noaa.gov/Datasets/noaa.oisst.v2.highres/'


def region_bounds():
    return {key: region.bounds for key, region in ALL_REGIONS.items() if key != 'nino34'}


def regional_mean(field, lat, lon, bounds):
    west, south, east, north = bounds
    lat_mask = (lat >= south) & (lat <= north)
    lon_mask = ((lon - west) % 360) <= (east - west)
    sub = np.ma.asarray(field, dtype=float)[np.ix_(lat_mask, lon_mask)].filled(np.nan)
    valid = np.isfinite(sub) & (sub >= -3.) & (sub <= 45.)
    weights = np.cos(np.deg2rad(lat[lat_mask]))[:, None]
    denominator = np.sum(np.where(valid, weights, 0.))
    if denominator <= 0:
        raise ValueError(f'No valid SST in {bounds}')
    return float(np.sum(np.where(valid, sub, 0.) * weights) / denominator)


def complete_year(year, dates):
    start = date(year, 1, 1)
    return dates == {(start + timedelta(days=i)).isoformat() for i in range(366 if calendar.isleap(year) else 365)}


def download_year(year, destination):
    filename = f'sst.day.mean.{year}.nc'
    for attempt in range(4):
        try:
            url = (BASE if attempt % 2 == 0 else MIRROR) + filename
            print(f'Downloading {url}', flush=True)
            with urlopen(Request(url, headers={'User-Agent': 'ClimateDashboard-SST-Regional/1.0'}), timeout=120) as response, destination.open('wb') as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            return
        except OSError:
            destination.unlink(missing_ok=True)
            if attempt == 3:
                raise
            time.sleep(15 * (attempt + 1))


def read_grid(path, year):
    # NetCDF4 decodes the scale/offset and masks land/fill values automatically.
    from netCDF4 import Dataset, num2date
    regions = region_bounds()
    with Dataset(path) as dataset:
        lat = np.asarray(dataset.variables['lat'][:], dtype=float)
        lon = np.asarray(dataset.variables['lon'][:], dtype=float)
        if len(lat) != 720 or len(lon) != 1440 or not np.allclose(np.abs(np.diff(lat)), .25) or not np.allclose(np.abs(np.diff(lon)), .25):
            raise ValueError('Expected 0.25-degree global NOAA OISST grid')
        temp = dataset.variables['sst']
        t = dataset.variables['time']
        times = num2date(t[:], t.units, getattr(t, 'calendar', 'standard'))
        if temp.dimensions != ('time', 'lat', 'lon'):
            raise ValueError(f'Unexpected SST dimensions: {temp.dimensions}')
        rows = {}
        for i, moment in enumerate(times):
            day = date(moment.year, moment.month, moment.day)
            if day.year != year or day > date.today():
                raise ValueError(f'Unexpected SST date {day} in {year}')
            field = temp[i]
            rows[day.isoformat()] = {key: regional_mean(field, lat, lon, bounds) for key, bounds in regions.items()}
        return rows


def read_annual(path):
    keys = list(region_bounds())
    if not path.is_file():
        return {}
    with path.open(newline='', encoding='utf-8') as fh:
        rows = csv.DictReader(fh)
        if rows.fieldnames != ['date', *keys]:
            raise ValueError(f'Unexpected regional CSV header in {path}')
        result = {row['date']: {key: float(row[key]) for key in keys} for row in rows}
    if any(not -2.5 <= value <= 36. for row in result.values() for value in row.values()):
        raise ValueError(f'Invalid SST in {path}')
    return result


def atomic_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh, lineterminator='\n')
        writer.writerow(header)
        writer.writerows(rows)
    temporary.replace(path)


def build_year(year, root):
    target = root / 'annual' / f'{year}.csv'
    with tempfile.TemporaryDirectory(prefix='sst-annual-') as tmp:
        path = Path(tmp) / 'sst.nc'
        download_year(year, path)
        rows = read_grid(path, year)
    if year < date.today().year and not complete_year(year, set(rows)):
        raise ValueError(f'Incomplete historical year {year}')
    if not rows:
        raise ValueError(f'Empty annual SST file {year}')
    days = sorted(rows)
    if days[0] != f'{year}-01-01' or (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days + 1 != len(days):
        raise ValueError(f'Gaps in annual SST file {year}')
    if year == date.today().year and (date.today() - date.fromisoformat(days[-1])).days > 30:
        raise ValueError(f'Current NOAA file is stale: {days[-1]}')
    old = read_annual(target)
    if old and max(old) > days[-1]:
        raise ValueError(f'New SST data ends before previous snapshot: {days[-1]}')
    keys = list(region_bounds())
    atomic_csv(target, ['date', *keys], ([day, *(f'{rows[day][key]:.4f}' for key in keys)] for day in days))
    print(f'{year}: {len(days)} days; {days[-1]}', flush=True)


def pending_years(root, today):
    # Current year refreshed every run; prior year refreshed for preliminary
    # values at the turn of the year. Older complete years never downloaded again.
    todo = [today.year]
    if today.month == 1:
        todo.append(today.year - 1)
    for year in range(today.year - 1, START_YEAR - 1, -1):
        if year not in todo and not complete_year(year, set(read_annual(root / 'annual' / f'{year}.csv'))):
            todo.append(year)
    return todo


def publish_series(root):
    current = date.today().year
    records = {}
    for year in range(START_YEAR, current + 1):
        rows = read_annual(root / 'annual' / f'{year}.csv')
        if (year < current and not complete_year(year, set(rows))) or not rows:
            print(f'Regional archive still building: missing/incomplete {year}', flush=True)
            return False
        records.update(rows)
    for key in region_bounds():
        atomic_csv(root / f'{key}_daily_sst.csv', ['date', 'sst'], ([day, f'{records[day][key]:.4f}'] for day in sorted(records)))
    print(f'Published {len(records)} dates from {min(records)} through {max(records)}', flush=True)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--list-years', action='store_true')
    action.add_argument('--year', type=int)
    action.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if args.list_years:
        print('\n'.join(map(str, pending_years(args.root, date.today()))))
    elif args.publish:
        publish_series(args.root)
    else:
        if not START_YEAR <= args.year <= date.today().year:
            parser.error('SST year is outside the archive')
        build_year(args.year, args.root)


if __name__ == '__main__':
    main()
