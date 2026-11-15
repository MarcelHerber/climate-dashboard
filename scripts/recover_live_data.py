"""Restart stale live imports, without interrupting or duplicating active runs."""
import json
import os
import subprocess
import argparse
from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from build_data_status import fetch_archive_json, MTG_PRODUCTS, finite


# Ordered by operational urgency. Cooldowns are minutes between starts.
SOURCES = (
    ('fast_live', 'fast-live/fast_state.json', 'update-fast-live.yml', 25),
    ('opera', 'opera-radar-data/data/opera/current.json', 'update-opera-europe-radar.yml', 25),
    ('satellite_mtg', 'main/data/satellite_wms_times.json', 'check-satellite-wms.yml', 45),
    ('icon_hazards', 'icon-hazards-data/data/icon-hazards/current.json', 'update-icon-eu-hazards.yml', 180),
    ('mosmix', 'mosmix-data/data/mosmix/manifest.json', 'update-mosmix.yml', 180),
    ('snow_eurasia', 'main/eurasia_snow/index.json', 'update-eurasia-snow.yml', 480),
    ('snow_europe', 'main/eurasia_snow/europe_index.json', 'update-europe-snow-area.yml', 480),
    ('snow_maps', 'main/eurasia_snow/maps/index.json', 'update-snow-maps.yml', 480),
    ('dmi_greenland', 'main/data/dmi_greenland_stations.json', 'update-dmi-greenland-stations.yml', 720),
    ('wind_reference', 'main/era5_stratosphere/backfill_status.json', 'update-era5-stratosphere.yml', 360),
)


def timestamp(value, now):
    if not isinstance(value, str) or 'T' not in value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt if dt.tzinfo and dt <= now else None
    except ValueError:
        return None


def needs_recovery(kind, manifest, now):
    def stale(value, hours):
        dt = timestamp(value, now)
        return dt is not None and (now - dt).total_seconds() > hours * 3600

    def day(value):
        try:
            d = date.fromisoformat(value)
            return d if d <= now.date() else None
        except (TypeError, ValueError):
            return None

    def stale_day(values, days):
        dates = [d for v in values if (d := day(v)) is not None]
        return bool(dates) and (now.date() - max(dates)).days > days

    if not isinstance(manifest, dict):
        return False
    if kind == 'fast_live':
        count = manifest.get('station_count')
        return type(count) is int and count > 0 and stale(manifest.get('latest_measurement_utc'), .75)
    if kind == 'opera':
        products = manifest.get('products')
        if not isinstance(products, dict):
            return False
        for key, limit in (('dbzh', .75), ('rate', 1)):
            product = products.get(key)
            frames = product.get('frames') if isinstance(product, dict) else None
            if not isinstance(frames, list):
                continue
            dates = [timestamp(frame.get('utc'), now) for frame in frames if isinstance(frame, dict)]
            dates = [date for date in dates if date is not None]
            if dates and (now - max(dates)).total_seconds() > limit * 3600:
                return True
    if kind == 'satellite_mtg':
        products = manifest.get('products')
        if not isinstance(products, dict):
            return False
        core = [products.get(key) for key in MTG_PRODUCTS]
        if not all(isinstance(p, dict) and p.get('map_ok') is True and timestamp(p.get('latest_verified_time'), now) for p in core):
            return False
        return any(stale(p['latest_verified_time'], 2) for p in core)
    if kind == 'icon_hazards':
        return bool(manifest.get('periods')) and stale(manifest.get('run_utc'), 12)
    if kind == 'mosmix':
        count = manifest.get('station_count')
        return type(count) is int and count >= 100 and stale(manifest.get('issue_time'), 12)
    if kind in ('snow_europe', 'snow_eurasia'):
        daily = manifest.get('daily')
        if not isinstance(daily, dict):
            return False
        dates = [key for key, value in daily.items() if finite(value) and day(key)]
        return bool(dates) and max(dates) == manifest.get('observed_latest') and stale_day(dates, 3)
    if kind == 'snow_maps':
        maps = manifest.get('maps')
        if not isinstance(maps, list):
            return False
        dates = [m['date'] for m in maps if isinstance(m, dict) and day(m.get('date'))
                 and all(isinstance(m.get(key), str) and m[key] for key in ('cover','anomaly','europe_cover','europe_anomaly'))]
        return bool(dates) and max(dates) == manifest.get('latest') and stale_day(dates, 3)
    if kind == 'dmi_greenland':
        stations, latest = manifest.get('stations'), manifest.get('latest')
        if not isinstance(stations, list) or not isinstance(latest, dict):
            return False
        active = {s['id'] for s in stations if isinstance(s, dict) and s.get('status') == 'Active' and isinstance(s.get('id'), str)}
        dates = [v.get('date') for sid, values in latest.items() if sid in active and isinstance(values, dict)
                 for v in values.values() if isinstance(v, dict) and finite(v.get('value'))]
        return stale_day(dates, 3)
    if kind == 'wind_reference':
        ref = manifest.get('reference_1991_2020')
        if manifest.get('schema_version') != 1 or not isinstance(ref, dict):
            return False
        years, days = ref.get('years_complete_four_winds'), ref.get('complete_wind_calendar_days')
        return (ref.get('years_complete_four_temperatures') == 30 and ref.get('complete_temperature_calendar_days') == 366
                and type(years) is int and 0 <= years <= 30 and type(days) is int and 0 <= days <= 366
                and (years < 30 or days < 366))
    return False


def can_dispatch(runs, now, cooldown_minutes=45):
    if not isinstance(runs, list) or not runs:
        return False
    if any(not isinstance(run, dict) or run.get('status') != 'completed' for run in runs):
        return False
    dates = [timestamp(run.get('createdAt'), now) for run in runs]
    if not all(d is not None for d in dates):
        return False
    i = max(range(len(dates)), key=lambda i: dates[i])
    age = (now - dates[i]).total_seconds()
    if age < cooldown_minutes * 60:
        return False
    if runs[i].get('conclusion') not in (None, 'success'):
        updated = timestamp(runs[i].get('updatedAt'), now)
        return updated is not None and (now - updated).total_seconds() >= max(60, cooldown_minutes) * 60
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Read real manifests without dispatching workflows')
    args = parser.parse_args()
    repo = os.environ['GITHUB_REPOSITORY']
    base = f'https://raw.githubusercontent.com/{repo}/'
    failures = 0
    def fetch(source):
        try:
            return fetch_archive_json(base + source[1]), None
        except Exception as exc:
            return None, type(exc).__name__

    with ThreadPoolExecutor(max_workers=4) as pool:
        manifests = list(pool.map(fetch, SOURCES))
    for (kind, path, workflow, cooldown), (manifest, error) in zip(SOURCES, manifests):
        try:
            now = datetime.now(timezone.utc)
            if error:
                print(f'{kind}: manifest unavailable ({error})')
                failures += 1
                continue
            if not needs_recovery(kind, manifest, now):
                print(f'{kind}: no verified stale timestamp')
                continue
            if args.dry_run:
                print(f'{kind}: recovery candidate (no dispatch)')
                continue
            runs = subprocess.run(['gh', 'run', 'list', '-R', repo, '-w', workflow,
                                   '--limit', '20', '--json', 'status,createdAt,updatedAt,conclusion'],
                                  check=True, capture_output=True, text=True, timeout=30)
            if not can_dispatch(json.loads(runs.stdout), now, cooldown):
                print(f'{kind}: active/recent/unknown run, skip')
                continue
            subprocess.run(['gh', 'workflow', 'run', workflow, '-R', repo, '--ref', 'main'],
                           check=True, capture_output=True, text=True, timeout=30)
            print(f'{kind}: recovery dispatched')
        except Exception as exc:
            print(f'{kind}: recovery unavailable ({type(exc).__name__})')
            failures += 1
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
