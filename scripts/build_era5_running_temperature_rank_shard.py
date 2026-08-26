#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

from era5_running_temperature_rank import (
    HISTORY_END,
    HISTORY_START,
    combine_summer_to_date,
    daily_request_year_groups,
    extract_day_and_mtd,
    extract_year_day_mtd,
)

ROOT = Path(__file__).resolve().parents[1]
RUNNING_PATH = ROOT / 'scripts' / 'update_era5_land_europe_running.py'
CORE_PATH = ROOT / 'scripts' / 'update_era5_land_europe.py'
RUNNING_INDEX = ROOT / 'era5_land_europe' / 'running' / 'index.json'
CACHE_DIR = ROOT / '.era5_running_rank_cache'
SHARD_DIR = ROOT / '.era5_running_rank_shards'


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Modul konnte nicht geladen werden: {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_modules():
    running = load_module(RUNNING_PATH, 'era5_running_rank_daily_core')
    core = load_module(CORE_PATH, 'era5_running_rank_monthly_core')
    running.GRID = [0.1, 0.1]
    running.CACHE_DIR = CACHE_DIR
    core.CACHE_DIR = CACHE_DIR
    return running, core


def default_target_date() -> date:
    payload = json.loads(RUNNING_INDEX.read_text(encoding='utf-8'))
    value = str(payload.get('data_through') or '')
    if not value:
        raise RuntimeError(f'data_through fehlt in {RUNNING_INDEX}')
    return date.fromisoformat(value)


def _drop_extra_dims(da, keep: set[str]):
    for dim in list(da.dims):
        if dim not in keep:
            if da.sizes.get(dim, 0) == 1:
                da = da.isel({dim: 0}, drop=True)
            else:
                raise RuntimeError(f'Unerwartete Dimension {dim}={da.sizes.get(dim)}')
    return da


def read_monthly_temperature(core, path: Path, years: list[int], months: list[int]):
    ds = core.open_download(path)
    try:
        lat_name, lon_name = core.spatial_names(ds)
        ds = core.normalize_lon(ds, lon_name)
        temp_name = core.variable_name(ds, core.TEMP_ALIASES)
        da = ds[temp_name]
        tdim = core.time_dim(da, lat_name, lon_name)
        if tdim is None:
            if len(years) * len(months) != 1:
                raise RuntimeError('Zeitdimension der Monatsdaten fehlt.')
            values = np.asarray(da.squeeze().values, dtype=float)[None, ...] - 273.15
            stamps = None
        else:
            da = _drop_extra_dims(da, {tdim, lat_name, lon_name}).transpose(tdim, lat_name, lon_name)
            values = np.asarray(da.values, dtype=float) - 273.15
            coord = da.coords.get(tdim)
            stamps = np.asarray(coord.values) if coord is not None else None
        lat = np.asarray(ds[lat_name].values, dtype=float)
        lon = np.asarray(ds[lon_name].values, dtype=float)

        expected = len(years) * len(months)
        if values.shape[0] != expected:
            raise RuntimeError(f'Unerwartete Zahl Monatsfelder: {values.shape[0]} statt {expected}')

        by_key: dict[tuple[int, int], np.ndarray] = {}
        if stamps is not None and np.issubdtype(stamps.dtype, np.datetime64):
            for idx, stamp in enumerate(stamps.astype('datetime64[M]').astype(str)):
                y, m = map(int, stamp.split('-'))
                by_key[(y, m)] = values[idx]
        else:
            idx = 0
            for year in years:
                for month in months:
                    by_key[(year, month)] = values[idx]
                    idx += 1

        fields = {
            month: np.stack([by_key[(year, month)] for year in years], axis=0).astype(np.float32)
            for month in months
        }
        return lat, lon, fields
    finally:
        ds.close()


def read_daily_years(running, path: Path, years: list[int], target_day: int):
    ds = running.open_download(path)
    try:
        lat, lon, times, cube = running.normalize_cube(ds, running.TEMP_ALIASES)
        cube = running.kelvin_to_celsius(cube)
        day, mtd = extract_year_day_mtd(times, cube, np.asarray(years, dtype=int), target_day)
        return lat, lon, day.astype(np.float32), mtd.astype(np.float32)
    finally:
        ds.close()


def build_shard(target: date, start_year: int, end_year: int) -> Path:
    if target.year != 2026:
        raise ValueError(f'Diese erste Rangserie ist für 2026 gebaut, nicht für {target.year}.')
    if target.month not in (6, 7, 8):
        raise ValueError('Sommer-Rangkarten werden nur für Juni bis August erzeugt.')
    if start_year < HISTORY_START or end_year > HISTORY_END or start_year > end_year:
        raise ValueError(f'Ungültiger Historienbereich: {start_year}–{end_year}')

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    running, core = load_modules()
    client = running.cds_client()
    years = list(range(start_year, end_year + 1))
    month = target.month
    target_day = target.day

    month_days = calendar.monthrange(2024, month)[1]
    day_parts = []
    mtd_parts = []
    lat_ref = lon_ref = None
    for year_group in daily_request_year_groups(years):
        year = year_group[0]
        daily_path = CACHE_DIR / f'rank_daily_{year}_{month:02d}_full.nc'
        if not daily_path.exists():
            running.request_daily_temperature(
                client, list(year_group), month, list(range(1, month_days + 1)), daily_path,
                f'Temperatur-Rang {year} · vollständiger {month:02d}. Monat',
            )
        lat, lon, day_stack, mtd_stack = read_daily_years(running, daily_path, list(year_group), target_day)
        if lat_ref is None:
            lat_ref, lon_ref = lat, lon
        elif not (np.allclose(lat_ref, lat) and np.allclose(lon_ref, lon)):
            raise RuntimeError('Tagesraster der Jahresabrufe stimmen nicht überein.')
        day_parts.append(day_stack)
        mtd_parts.append(mtd_stack)

    day_stack = np.concatenate(day_parts, axis=0)
    mtd_stack = np.concatenate(mtd_parts, axis=0)

    complete_months = list(range(6, month))
    complete_fields: dict[int, np.ndarray] = {}
    if complete_months:
        monthly_path = CACHE_DIR / (
            f'rank_monthly_{start_year}_{end_year}_' + '_'.join(f'{m:02d}' for m in complete_months) + '.nc'
        )
        if not monthly_path.exists():
            core.request_monthly_file(client, years, complete_months, monthly_path)
        mlat, mlon, complete_fields = read_monthly_temperature(core, monthly_path, years, complete_months)
        if not (np.allclose(lat_ref, mlat) and np.allclose(lon_ref, mlon)):
            raise RuntimeError('Tages- und Monatsraster stimmen nicht überein.')

    summer_stack = combine_summer_to_date(
        complete_fields,
        np.asarray(years, dtype=int),
        month,
        target_day,
        mtd_stack,
    ).astype(np.float32)

    out = SHARD_DIR / f'temperature_rank_{start_year}_{end_year}_{target.isoformat()}.npz'
    np.savez_compressed(
        out,
        target_date=np.asarray(target.isoformat()),
        years=np.asarray(years, dtype=np.int16),
        lat=np.asarray(lat_ref, dtype=np.float32),
        lon=np.asarray(lon_ref, dtype=np.float32),
        day=day_stack,
        month_to_date=mtd_stack,
        summer_to_date=summer_stack,
    )
    print(f'Rang-Shard fertig: {start_year}–{end_year} · {target} · {out.stat().st_size/1024/1024:.1f} MiB')
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description='Historischen ERA5-Land-Temperatur-Rangshard erzeugen.')
    parser.add_argument('--target-date')
    parser.add_argument('--start-year', type=int, required=True)
    parser.add_argument('--end-year', type=int, required=True)
    args = parser.parse_args()
    target = date.fromisoformat(args.target_date) if args.target_date else default_target_date()
    build_shard(target, args.start_year, args.end_year)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
