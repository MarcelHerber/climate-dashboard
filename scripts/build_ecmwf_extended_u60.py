#!/usr/bin/env python3
"""Daily 00 UTC ECMWF S2S 101-member, 46-day zonal wind archive (CC BY 4.0)."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile

import numpy as np

PROVIDER = 'ECMWF IFS Sub-seasonal S2S'
STEPS = list(range(0, 1105, 24))
MEMBERS = ['c00'] + [f'p{i:03d}' for i in range(1, 101)]


def mean_u60(lat, lon, wind):
    lat, lon, wind = (np.asarray(a, dtype=float) for a in (lat, lon, wind))
    if not (lat.shape == lon.shape == wind.shape):
        raise ValueError('Unmatched GRIB coordinate shapes')
    ring = np.isclose(lat, 60, atol=0.002)
    x, y = lon[ring], wind[ring]
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.any((y <= -160) | (y >= 170)):
        raise ValueError('Invalid 60N wind')
    bins = np.rint(np.mod(x, 360) / 1.5).astype(int) % 240
    if not np.allclose(np.mod(x, 360), bins * 1.5, atol=0.002):
        raise ValueError('Unexpected S2S grid')
    unique = {}
    for k, v in zip(bins, y):
        if k in unique and not np.isclose(unique[k], v, atol=0.001):
            raise ValueError('Conflicting repeated longitude')
        unique[k] = v
    if len(unique) != 240:
        raise ValueError(f'Incomplete 60N ring: {len(unique)}/240')
    return float(np.mean(list(unique.values())))


def retrieval_request(cycle, perturbed):
    return dict(origin='ecmwf', year=cycle.strftime('%Y'), month=cycle.strftime('%m'),
                day=cycle.strftime('%d'), time='00:00', level_type='pressure',
                level_value=['10_hpa'], variable=['u_component_of_wind'],
                forecast_type='perturbed_forecast' if perturbed else 'control_forecast',
                leadtime_hour=[str(h) for h in STEPS], data_format='grib',
                area=[61.5, -180, 58.5, 180])


def decode(path, cycle, perturbed):
    import eccodes
    expected = set(MEMBERS[1:] if perturbed else MEMBERS[:1])
    found = {m: {} for m in expected}
    with Path(path).open('rb') as stream:
        while (gid := eccodes.codes_grib_new_from_file(stream)) is not None:
            try:
                get = lambda k: eccodes.codes_get(gid, k)
                if get('shortName') != 'u' or get('typeOfLevel') != 'isobaricInhPa' or int(get('level')) != 10:
                    raise ValueError('Unexpected S2S parameter or level')
                if int(get('dataDate')) != int(cycle.strftime('%Y%m%d')) or int(get('dataTime')) != 0:
                    raise ValueError('Wrong initialization')
                step = int(get('endStep'))
                if step not in STEPS or get('stepType') != 'instant':
                    raise ValueError('Wrong lead time/statistic')
                number = int(get('number')) if perturbed else 0
                key = f'p{number:03d}' if perturbed else 'c00'
                if key not in found or step in found[key]:
                    raise ValueError('Unexpected/duplicate ensemble field')
                found[key][step] = mean_u60(eccodes.codes_get_array(gid, 'latitudes'),
                                            eccodes.codes_get_array(gid, 'longitudes'),
                                            eccodes.codes_get_values(gid))
            finally:
                eccodes.codes_release(gid)
    if any(set(values) != set(STEPS) for values in found.values()):
        raise ValueError('Incomplete S2S run; will not publish')
    return {key: [values[h] for h in STEPS] for key, values in found.items()}


def payload(cycle, members):
    result = dict(schema_version=1, provider=PROVIDER, cycle_utc=cycle.strftime('%Y-%m-%dT00:00:00Z'),
                  generated_utc=datetime.now(timezone.utc).isoformat(), latitude_deg=60, level_hpa=10,
                  units='m/s', resolution_degrees=1.5, member_count=101, perturbed_count=100,
                  forecast_step_hours=STEPS, valid_dates=[(cycle+timedelta(hours=h)).strftime('%Y-%m-%d') for h in STEPS],
                  source_url='https://ecds.ecmwf.int/datasets/s2s-forecasts', license='CC BY 4.0', members=members)
    if not validate(result):
        raise ValueError('Incomplete or invalid 101-member run')
    return result


def validate(data):
    try:
        cycle = datetime.strptime(data['cycle_utc'], '%Y-%m-%dT00:00:00Z')
        dates = [(cycle+timedelta(hours=h)).strftime('%Y-%m-%d') for h in STEPS]
        return (data['schema_version'] == 1 and data['provider'] == PROVIDER and
                data['latitude_deg'] == 60 and data['level_hpa'] == 10 and data['units'] == 'm/s' and
                data['member_count'] == 101 and data['forecast_step_hours'] == STEPS and data['valid_dates'] == dates and
                set(data['members']) == set(MEMBERS) and all(len(v) == 47 and all(isinstance(n, (int, float)) and
                    np.isfinite(n) and -160 < n < 170 for n in v) for v in data['members'].values()))
    except (TypeError, ValueError, KeyError):
        return False


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    temp.replace(path)


def read_valid(path):
    try:
        result = json.loads(path.read_text())
        return result if validate(result) else None
    except (OSError, ValueError):
        return None


def next_cycle(directory, newest):
    for day in range(8):
        cycle = newest-timedelta(days=day)
        old = read_valid(directory/'runs'/f'{cycle:%Y%m%d}.json')
        if not old or old['cycle_utc'] != cycle.strftime('%Y-%m-%dT00:00:00Z'):
            return cycle
    return None


def publish(directory, result):
    if not validate(result):
        raise ValueError('Invalid run; not publishing')
    stamp = result['cycle_utc'][:10].replace('-', '')
    write_json(directory/'runs'/f'{stamp}.json', result)
    runs = []
    for path in sorted((directory/'runs').glob('*.json'), reverse=True):
        data = read_valid(path)
        if data and path.name == data['cycle_utc'][:10].replace('-', '')+'.json':
            runs.append(dict(cycle_utc=data['cycle_utc'], path=f'runs/{path.name}'))
            if len(runs) == 8:
                break
    if not runs:
        raise ValueError('No validated archive data')
    write_json(directory/'current.json', read_valid(directory/runs[0]['path']))
    write_json(directory/'index.json', dict(provider=PROVIDER, runs=runs[:8]))


def build(directory, cycle):
    if read_valid(directory/'runs'/f'{cycle:%Y%m%d}.json'):
        print('Complete scheduled run already available; no repeat retrieval')
        return
    import cdsapi
    client = cdsapi.Client(url='https://ecds.ecmwf.int/api', key=os.environ['CDSAPI_KEY'], timeout=120, quiet=False)
    members = {}
    with tempfile.TemporaryDirectory(prefix='ecmwf-s2s-') as temp:
        for perturbed in (False, True):
            target = Path(temp) / ('pf.grib' if perturbed else 'cf.grib')
            client.retrieve('s2s-forecasts', retrieval_request(cycle, perturbed), str(target))
            members.update(decode(target, cycle, perturbed))
    result = payload(cycle, members)
    publish(directory, result)
    print(f'Verified {result["member_count"]} members × {len(STEPS)} dates: {result["cycle_utc"]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--date', help='Optional cycle date YYYY-MM-DD (must be at least 48 h old)')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    cycle = (datetime.strptime(args.date, '%Y-%m-%d').replace(tzinfo=timezone.utc) if args.date else
             (now-timedelta(hours=48)).replace(hour=0, minute=0, second=0, microsecond=0))
    if now-cycle < timedelta(hours=48):
        parser.error('S2S release delay is at least 48 hours')
    cycle = cycle if args.date else next_cycle(args.directory, cycle)
    if cycle is not None:
        build(args.directory, cycle)
    else:
        print('Current run and seven previous daily archives complete')
