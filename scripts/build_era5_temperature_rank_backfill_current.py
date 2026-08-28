#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from build_era5_running_temperature_rank_shard import (
    CORE_PATH,
    RUNNING_PATH,
    load_module,
    read_monthly_temperature,
    request_monthly_temperature,
)
from era5_running_temperature_rank import PRODUCTS, season_for_month
from era5_temperature_rank_backfill import build_single_year_month_products

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / '.era5_running_rank_backfill_current_cache'
DEFAULT_OUTPUT_DIR = ROOT / '.era5_running_rank_backfill_current'


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


def build_current_month(year: int, month: int, end_day: int, output: Path) -> Path:
    year = int(year)
    month = int(month)
    end_day = int(end_day)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    running = load_module(RUNNING_PATH, 'era5_rank_backfill_current_daily')
    core = load_module(CORE_PATH, 'era5_rank_backfill_current_monthly')
    running.GRID = [0.1, 0.1]
    running.CACHE_DIR = CACHE_DIR
    core.CACHE_DIR = CACHE_DIR
    client = running.cds_client()

    daily_path = CACHE_DIR / f'current_daily_{year}_{month:02d}_through_{end_day:02d}.nc'
    if not daily_path.exists():
        running.request_daily_temperature(
            client,
            [year],
            month,
            list(range(1, end_day + 1)),
            daily_path,
            f'ERA5 Rang-Backfill aktuell {year}-{month:02d} bis Tag {end_day:02d}',
        )
    lat, lon, times, cube = read_daily_cube(running, daily_path)

    complete_months = list(range(1, month))
    complete_fields: dict[int, np.ndarray] = {}
    if complete_months:
        monthly_path = CACHE_DIR / f'current_monthly_{year}_01_{complete_months[-1]:02d}.nc'
        if not monthly_path.exists():
            request_monthly_temperature(core, client, [year], complete_months, monthly_path)
        mlat, mlon, complete_fields = read_monthly_temperature(
            core, monthly_path, [year], complete_months
        )
        if not (np.allclose(lat, mlat) and np.allclose(lon, mlon)):
            raise RuntimeError('Aktuelle Tages- und Monatsraster stimmen nicht überein.')

    season_key, season_name, _ = season_for_month(month)
    previous_december = None
    if season_key == 'winter' and month in (1, 2):
        previous_year = year - 1
        december_path = CACHE_DIR / f'current_monthly_{previous_year}_12_12.nc'
        if not december_path.exists():
            request_monthly_temperature(core, client, [previous_year], [12], december_path)
        dlat, dlon, december_fields = read_monthly_temperature(
            core, december_path, [previous_year], [12]
        )
        if not (np.allclose(lat, dlat) and np.allclose(lon, dlon)):
            raise RuntimeError('Vorjahres-Dezember liegt auf einem abweichenden Raster.')
        previous_december = december_fields[12]

    target_dates, products = build_single_year_month_products(
        times=times,
        cube=cube,
        year=year,
        month=month,
        end_day=end_day,
        complete_month_fields=complete_fields,
        previous_december=previous_december,
    )
    payload = {
        'year': np.asarray(year, dtype=np.int16),
        'month': np.asarray(month, dtype=np.int8),
        'end_day': np.asarray(end_day, dtype=np.int8),
        'target_dates': target_dates,
        'lat': lat.astype(np.float32),
        'lon': lon.astype(np.float32),
        'season_key': np.asarray(season_key),
        'season_name': np.asarray(season_name),
        **{product: products[product].astype(np.float32) for product in PRODUCTS},
    }
    np.savez_compressed(output, **payload)
    print(
        f'Aktueller Monatsstack fertig: {target_dates[0]}–{target_dates[-1]} · '
        f'{len(target_dates)} Tage · {season_name} · {output.stat().st_size/1024/1024:.1f} MiB'
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description='Aktuellen ERA5-Rangstack für einen Backfill-Monat bauen.')
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--month', type=int, required=True)
    parser.add_argument('--end-day', type=int, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or (
        DEFAULT_OUTPUT_DIR / f'current_{args.year}_{args.month:02d}.npz'
    )
    build_current_month(args.year, args.month, args.end_day, output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
