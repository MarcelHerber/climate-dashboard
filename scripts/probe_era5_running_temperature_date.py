#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUNNING_PATH = ROOT / 'scripts' / 'update_era5_land_europe_running.py'
PROBE_CACHE_DIR = ROOT / '.era5_running_rank_temperature_probe'
PROBE_AREA = [50.0, 10.0, 49.5, 10.5]
MIN_LAG_DAYS = 4
MAX_LOOKBACK_DAYS = 14


def temperature_probe_candidates(
    today: date,
    *,
    min_lag_days: int = MIN_LAG_DAYS,
    max_lookback_days: int = MAX_LOOKBACK_DAYS,
) -> list[date]:
    min_lag_days = int(min_lag_days)
    max_lookback_days = int(max_lookback_days)
    if min_lag_days < 0:
        raise ValueError('min_lag_days darf nicht negativ sein')
    if max_lookback_days < min_lag_days:
        raise ValueError('max_lookback_days muss >= min_lag_days sein')
    return [
        today - timedelta(days=lag)
        for lag in range(min_lag_days, max_lookback_days + 1)
    ]


def load_running_module():
    spec = importlib.util.spec_from_file_location(
        'era5_temperature_rank_availability_probe',
        RUNNING_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Running-Modul konnte nicht geladen werden: {RUNNING_PATH}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def request_probe_day(running, client, candidate: date, target: Path) -> None:
    request = {
        'variable': ['2m_temperature'],
        'year': [f'{candidate.year:04d}'],
        'month': f'{candidate.month:02d}',
        'day': [f'{candidate.day:02d}'],
        'daily_statistic': 'daily_mean',
        'time_zone': 'utc+00:00',
        'frequency': '1_hourly',
        'area': PROBE_AREA,
        'grid': [0.1, 0.1],
    }
    running.retrieve(
        client,
        running.DAILY_DATASET,
        request,
        target,
        f'Verfügbarkeitsprobe Temperatur-Rang {candidate.isoformat()}',
        attempts=1,
    )


def validate_probe_day(running, path: Path, candidate: date) -> bool:
    ds = running.open_download(path)
    try:
        _, _, times, cube = running.normalize_cube(ds, running.TEMP_ALIASES)
        dates = np.asarray(times).astype('datetime64[D]').astype(str)
        match = dates == candidate.isoformat()
        if not np.any(match):
            return False
        values = np.asarray(cube, dtype=float)[match]
        return bool(np.isfinite(values).any())
    finally:
        ds.close()


def probe_latest_temperature_day(
    *,
    today: date | None = None,
    min_lag_days: int = MIN_LAG_DAYS,
    max_lookback_days: int = MAX_LOOKBACK_DAYS,
) -> date:
    running = load_running_module()
    running.GRID = [0.1, 0.1]
    PROBE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    client = running.cds_client()
    today = today or date.today()

    errors: list[str] = []
    for candidate in temperature_probe_candidates(
        today,
        min_lag_days=min_lag_days,
        max_lookback_days=max_lookback_days,
    ):
        target = PROBE_CACHE_DIR / f'temperature_{candidate.isoformat()}.nc'
        try:
            if not target.exists():
                request_probe_day(running, client, candidate, target)
            if validate_probe_day(running, target, candidate):
                print(
                    f'Neuester verfügbarer ERA5-Land-Temperaturtag: {candidate.isoformat()}',
                    flush=True,
                )
                return candidate
            errors.append(f'{candidate}: Datei enthält keinen gültigen Zieltag')
        except Exception as exc:
            target.unlink(missing_ok=True)
            errors.append(f'{candidate}: {exc}')
            print(
                f'{candidate}: Temperatur noch nicht verfügbar ({exc})',
                flush=True,
            )

    raise RuntimeError(
        'Kein ERA5-Land-Temperaturtag im Probezeitraum gefunden. '
        + ' | '.join(errors[-4:])
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Jüngsten verfügbaren ERA5-Land-T-Temperaturtag für die Rangkarten bestimmen.'
    )
    parser.add_argument('--min-lag-days', type=int, default=MIN_LAG_DAYS)
    parser.add_argument('--max-lookback-days', type=int, default=MAX_LOOKBACK_DAYS)
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args()

    target = probe_latest_temperature_day(
        min_lag_days=args.min_lag_days,
        max_lookback_days=args.max_lookback_days,
    )
    if args.github_output:
        with args.github_output.open('a', encoding='utf-8') as fh:
            fh.write(f'target_date={target.isoformat()}\n')
    else:
        print(target.isoformat())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
