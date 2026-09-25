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
from era5_temperature_rank_backfill import build_single_year_month_products

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / '.era5_rank_reference_shards'


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


def build_reference_shard(year: int, month: int, target_year: int, output_dir: Path) -> list[Path]:
    year = int(year)
    month = int(month)
    target_year = int(target_year)
    if year < HISTORY_START or year >= target_year:
        raise ValueError(f'Historisches Jahr muss zwischen {HISTORY_START} und {target_year - 1} liegen.')
    if month not in (9, 10, 11, 12):
        raise ValueError('Der Vorbau ist derzeit bewusst auf September bis Dezember begrenzt.')

    output_dir.mkdir(parents=True, exist_ok=True)
    DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MONTHLY_CACHE_DIR.mkdir(parents=True, exist_ok=True)

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
            f'ERA5 Rang-Referenz {year} · Monat {month:02d}',
        )
    lat, lon, times, cube = read_daily_cube(running, daily_path)

    all_months = list(range(1, 13))
    annual_path = MONTHLY_CACHE_DIR / f'rank_monthly_{year}_{year}_01_12.nc'
    if not annual_path.exists():
        request_monthly_temperature(core, client, [year], all_months, annual_path)
    mlat, mlon, complete_fields = read_monthly_temperature(
        core, annual_path, [year], all_months
    )
    if not (np.allclose(lat, mlat) and np.allclose(lon, mlon)):
        raise RuntimeError('Historisches Tages- und Monatsraster stimmen nicht überein.')

    end_day = calendar.monthrange(target_year, month)[1]
    season_key, _, _ = season_for_month(month)
    previous_december = None
    if season_key == 'winter' and month in (1, 2):
        raise RuntimeError('Januar/Februar sind in diesem Vorbau nicht aktiviert.')

    _, products = build_single_year_month_products(
        times=times,
        cube=cube,
        year=year,
        month=month,
        end_day=end_day,
        complete_month_fields=complete_fields,
        previous_december=previous_december,
    )

    created: list[Path] = []
    for day in range(1, end_day + 1):
        path = output_dir / (
            f'temperature_rank_reference_{year}_{month:02d}_{day:02d}.npz'
        )
        np.savez_compressed(
            path,
            schema_version=np.asarray(1, dtype=np.int16),
            year=np.asarray(year, dtype=np.int16),
            target_year=np.asarray(target_year, dtype=np.int16),
            month=np.asarray(month, dtype=np.int8),
            target_day=np.asarray(day, dtype=np.int8),
            lat=np.asarray(lat, dtype=np.float32),
            lon=np.asarray(lon, dtype=np.float32),
            **{
                product: np.asarray(products[product][day - 1], dtype=np.float32)
                for product in PRODUCTS
            },
        )
        created.append(path)

    total_mib = sum(path.stat().st_size for path in created) / 1024 / 1024
    print(
        f'Historische Rang-Referenz vorbereitet: {year} · Monat {month:02d} · '
        f'{len(created)} Tage · {total_mib:.1f} MiB'
    )
    return created


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Statische historische ERA5-Land-Rangreferenz eines Jahres für einen Monat vorbereiten.'
    )
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--month', type=int, required=True)
    parser.add_argument('--target-year', type=int, default=2026)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()

    output_dir = args.output_dir or (DEFAULT_OUTPUT_DIR / f'{args.year:04d}')
    build_reference_shard(args.year, args.month, args.target_year, output_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
