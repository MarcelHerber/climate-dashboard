#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
from datetime import date
from pathlib import Path

import numpy as np

from build_era5_running_temperature_rank_shard import (
    DAILY_CACHE_DIR,
    HISTORY_START,
    load_modules,
    maybe_restore_legacy_daily,
)

HISTORY_END = 2025


def expected_dates(year: int, month: int) -> list[str]:
    year = int(year)
    month = int(month)
    if not 1 <= month <= 12:
        raise ValueError('month muss zwischen 1 und 12 liegen')
    last_day = calendar.monthrange(year, month)[1]
    return [date(year, month, day).isoformat() for day in range(1, last_day + 1)]


def daily_cache_path(year: int, month: int) -> Path:
    return DAILY_CACHE_DIR / f'rank_daily_{int(year)}_{int(month):02d}_full.nc'


def validate_daily_cache(running, path: Path, year: int, month: int) -> None:
    ds = running.open_download(path)
    try:
        lat, lon, times, cube = running.normalize_cube(ds, running.TEMP_ALIASES)
        lat = np.asarray(lat)
        lon = np.asarray(lon)
        times = np.asarray(times)
        cube = np.asarray(cube)

        if lat.ndim != 1 or lon.ndim != 1:
            raise RuntimeError('ERA5-Tagescache hat kein eindimensionales 0,1°-Raster.')
        if cube.shape[0] != times.size:
            raise RuntimeError('Zeitachse und Tagesfelder stimmen nicht überein.')
        if not np.issubdtype(times.dtype, np.datetime64):
            raise RuntimeError('ERA5-Tagescache enthält keine datetime64-Zeitachse.')

        actual = np.unique(times.astype('datetime64[D]').astype(str)).tolist()
        expected = expected_dates(year, month)
        if actual != expected:
            raise RuntimeError(
                f'Tagescache {year}-{month:02d} unvollständig: '
                f'{len(actual)} statt {len(expected)} Tage.'
            )
    finally:
        ds.close()


def warm_daily_cache(year: int, month: int) -> Path:
    year = int(year)
    month = int(month)
    if not HISTORY_START <= year <= HISTORY_END:
        raise ValueError(f'year muss zwischen {HISTORY_START} und {HISTORY_END} liegen')
    if not 1 <= month <= 12:
        raise ValueError('month muss zwischen 1 und 12 liegen')

    DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    running, _ = load_modules()
    target = daily_cache_path(year, month)
    maybe_restore_legacy_daily(year, month, target)

    if target.exists():
        try:
            validate_daily_cache(running, target, year, month)
            print(
                f'Tagescache bereits vollständig: {year}-{month:02d} · '
                f'{target.stat().st_size / 1024 / 1024:.1f} MiB'
            )
            return target
        except Exception as exc:
            print(f'Vorhandener Tagescache ist ungültig und wird neu geladen: {exc}')
            target.unlink(missing_ok=True)

    client = running.cds_client()
    month_days = calendar.monthrange(year, month)[1]
    running.request_daily_temperature(
        client,
        [year],
        month,
        list(range(1, month_days + 1)),
        target,
        f'ERA5 Rang-Historie vorwärmen {year} · Monat {month:02d}',
    )
    validate_daily_cache(running, target, year, month)
    print(
        f'Tagescache vorgewärmt: {year}-{month:02d} · '
        f'{target.stat().st_size / 1024 / 1024:.1f} MiB'
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Historischen ERA5-Land-Tagescache für spätere Temperatur-Rangarchive vorwärmen.'
    )
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--month', type=int, required=True)
    args = parser.parse_args()
    warm_daily_cache(args.year, args.month)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
