"""Restart stale live imports, without interrupting or duplicating active runs."""
import json
import os
import subprocess
from datetime import datetime, timezone

from build_data_status import fetch_archive_json


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

    if not isinstance(manifest, dict):
        return False
    if kind == 'fast_live':
        count = manifest.get('station_count')
        return type(count) is int and count > 0 and stale(manifest.get('latest_measurement_utc'), 3)
    if kind == 'opera':
        products = manifest.get('products')
        if not isinstance(products, dict):
            return False
        for key, limit in (('dbzh', 1), ('rate', 1.25)):
            product = products.get(key)
            frames = product.get('frames') if isinstance(product, dict) else None
            if not isinstance(frames, list):
                continue
            dates = [timestamp(frame.get('utc'), now) for frame in frames if isinstance(frame, dict)]
            dates = [date for date in dates if date is not None]
            if dates and (now - max(dates)).total_seconds() > limit * 3600:
                return True
    return False


def can_dispatch(runs, now):
    if not isinstance(runs, list) or not runs:
        return False
    if any(not isinstance(run, dict) or run.get('status') != 'completed' for run in runs):
        return False
    dates = [timestamp(run.get('createdAt'), now) for run in runs]
    return all(d is not None for d in dates) and (now - max(dates)).total_seconds() >= 45 * 60


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    base = f'https://raw.githubusercontent.com/{repo}/'
    sources = (
        ('fast_live', 'fast-live/fast_state.json', 'update-fast-live.yml'),
        ('opera', 'opera-radar-data/data/opera/current.json', 'update-opera-europe-radar.yml'),
    )
    failures = 0
    for kind, path, workflow in sources:
        try:
            now = datetime.now(timezone.utc)
            if not needs_recovery(kind, fetch_archive_json(base + path), now):
                print(f'{kind}: no verified stale timestamp')
                continue
            runs = subprocess.run(['gh', 'run', 'list', '-R', repo, '-w', workflow,
                                   '--limit', '20', '--json', 'status,createdAt'],
                                  check=True, capture_output=True, text=True, timeout=30)
            if not can_dispatch(json.loads(runs.stdout), now):
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
