#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
from pathlib import Path

import numpy as np

from build_era5_running_temperature_rank_shard import (
    DAILY_CACHE_DIR,
    HISTORY_START,
    MONTHLY_CACHE_DIR,
    load_modules,
    maybe_restore_legacy_daily,
    read_monthly_temperature,
    request_monthly_temperature,
)
from era5_running_temperature_rank import PRODUCTS, season_for_month
from era5_temperature_rank_backfill import (
    build_single_year_month_products,
    rank_contribution,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / '.era5_running_rank_backfill_shards'


def read_daily_cube(running, path: Path):
    ds = running.open_download(path)
    try:
        lat, lon, times, cube = running.normalize_cube(ds, running.TEMP_ALIASES)
        cube = running.kelvin_to_celsius(cube)
        return (
            np.asarray(lat, dtype=np.float64),
            np.asarray(lon, dtype=np.float64),
            np.asarray(times),
            np.asarray(cube, dtype=np.float32),
        )
    finally:
        ds.close()


def load_current(path: Path):
    with np.load(path, allow_pickle=False) as data:
        return {
            'target_dates': np.asarray(data['target_dates']).astype(str),
            'lat': np.asarray(data['lat'], dtype=np.float64),
            'lon': np.asarray(data['lon'], dtype=np.float64),
            'products': {
                product: np.asarray(data[product], dtype=np.float32)
                for product in PRODUCTS
            },
        }


def build_contribution(year: int, current_file: Path, output: Path) -> Path:
    year = int(year)
    if year < HISTORY_START:
        raise ValueError(f'Historisches Jahr muss >= {HISTORY_START} sein.')

    current = load_current(current_file)
    target_dates = current['target_dates']
    if target_dates.size == 0:
        raise RuntimeError('Aktueller Backfill-Stack enthält keine Zieldaten.')
    first = str(target_dates[0])
    target_year = int(first[:4])
    month = int(first[5:7])
    end_day = int(str(target_dates[-1])[-2:])
    if target_year <= year:
        raise ValueError(f'Historisches Jahr {year} muss vor Zieljahr {target_year} liegen.')

    DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MONTHLY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    running, core = load_modules()
    client = running.cds_client()

    daily_path = DAILY_CACHE_DIR / f'rank_daily_{year}_{month:02d}_full.nc'
    maybe_restore_legacy_daily(year, month, daily_path)
    if not daily_path.exists():
        month_days = calendar.monthrange(year, month)[1]
        running.request_daily_temperature(
            client,
            [year],
            month,
            list(range(1, month_days + 1)),
            daily_path,
            f'ERA5 Rang-Backfill {year} · vollständiger Monat {month:02d}',
        )
    lat, lon, times, cube = read_daily_cube(running, daily_path)
    if not (
        np.allclose(lat, current['lat'])
        and np.allclose(lon, current['lon'])
    ):
        raise RuntimeError('Historisches Tagesraster weicht vom aktuellen Raster ab.')

    all_months = list(range(1, 13))
    annual_path = MONTHLY_CACHE_DIR / f'rank_monthly_{year}_{year}_01_12.nc'
    if not annual_path.exists():
        request_monthly_temperature(core, client, [year], all_months, annual_path)
    mlat, mlon, complete_fields = read_monthly_temperature(
        core, annual_path, [year], all_months
    )
    if not (np.allclose(lat, mlat) and np.allclose(lon, mlon)):
        raise RuntimeError('Historisches Monatsraster weicht vom Tagesraster ab.')

    season_key, _, _ = season_for_month(month)
    previous_december = None
    if season_key == 'winter' and month in (1, 2):
        if year == HISTORY_START:
            previous_december = np.full(
                (1, lat.size, lon.size), np.nan, dtype=np.float32
            )
        else:
            previous_year = year - 1
            previous_annual = (
                MONTHLY_CACHE_DIR
                / f'rank_monthly_{previous_year}_{previous_year}_01_12.nc'
            )
            if previous_annual.exists():
                plat, plon, previous_fields = read_monthly_temperature(
                    core, previous_annual, [previous_year], all_months
                )
            else:
                previous_annual = (
                    MONTHLY_CACHE_DIR
                    / f'rank_monthly_{previous_year}_{previous_year}_12_12.nc'
                )
                if not previous_annual.exists():
                    request_monthly_temperature(
                        core, client, [previous_year], [12], previous_annual
                    )
                plat, plon, previous_fields = read_monthly_temperature(
                    core, previous_annual, [previous_year], [12]
                )
            if not (np.allclose(lat, plat) and np.allclose(lon, plon)):
                raise RuntimeError('Vorjahres-Dezember liegt auf einem anderen Raster.')
            previous_december = previous_fields[12]

    historical_dates, historical_products = build_single_year_month_products(
        times=times,
        cube=cube,
        year=year,
        month=month,
        end_day=end_day,
        complete_month_fields=complete_fields,
        previous_december=previous_december,
    )
    if not np.array_equal(
        np.asarray([value[5:] for value in historical_dates]),
        np.asarray([value[5:] for value in target_dates]),
    ):
        raise RuntimeError('Historische und aktuelle Zieltage stimmen nicht überein.')

    greater, valid = rank_contribution(
        current['products'],
        historical_products,
    )
    payload = {
        'year': np.asarray(year, dtype=np.int16),
        'target_year': np.asarray(target_year, dtype=np.int16),
        'month': np.asarray(month, dtype=np.int8),
        'target_dates': target_dates,
        'lat': lat.astype(np.float32),
        'lon': lon.astype(np.float32),
        'greater': greater,
        'valid_count': valid,
    }
    np.savez_compressed(output, **payload)
    print(
        f'Backfill-Beitrag fertig: {year} · {target_dates[0]}–{target_dates[-1]} · '
        f'{output.stat().st_size/1024/1024:.1f} MiB'
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description='Historischen ERA5-Rangbeitrag für einen Backfill-Monat bauen.')
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--current-file', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or (
        DEFAULT_OUTPUT_DIR / f'contrib_{args.year}.npz'
    )
    build_contribution(args.year, args.current_file, output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
