#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import importlib.util
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import numpy as np

from era5_running_temperature_rank import (
    HISTORY_START,
    combine_season_to_date,
    combine_year_to_date,
    daily_request_year_groups,
    extract_year_day_mtd,
    products_for_month,
    season_for_month,
)

ROOT = Path(__file__).resolve().parents[1]
RUNNING_PATH = ROOT / 'scripts' / 'update_era5_land_europe_running.py'
CORE_PATH = ROOT / 'scripts' / 'update_era5_land_europe.py'
RUNNING_INDEX = ROOT / 'era5_land_europe' / 'running' / 'index.json'
LEGACY_CACHE_DIR = ROOT / '.era5_running_rank_cache'
DAILY_CACHE_DIR = ROOT / '.era5_running_rank_daily_cache'
MONTHLY_CACHE_DIR = ROOT / '.era5_running_rank_monthly_cache'
CURRENT_CACHE_DIR = ROOT / '.era5_running_rank_current_cache'
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
    running.CACHE_DIR = DAILY_CACHE_DIR
    core.CACHE_DIR = MONTHLY_CACHE_DIR
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


def request_monthly_temperature(core, client, years: list[int], months: list[int], target: Path) -> None:
    if not years or not months:
        raise ValueError('years und months dürfen nicht leer sein')
    target.parent.mkdir(parents=True, exist_ok=True)
    request = {
        'product_type': ['monthly_averaged_reanalysis'],
        'variable': ['2m_temperature'],
        'year': [f'{year:04d}' for year in years],
        'month': [f'{month:02d}' for month in months],
        'time': ['00:00'],
        'data_format': 'netcdf',
        'download_format': 'unarchived',
        'area': core.AREA,
    }
    label = f'Temperatur-Monatsmittel {years[0]}–{years[-1]} · Monate {months[0]:02d}–{months[-1]:02d}'
    print(f'CDS Monatsmittel Temperatur: Jahre {years[0]}–{years[-1]}, Monate {months[0]:02d}–{months[-1]:02d}')
    core.retrieve_with_retry(client, request, target, label)


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

        missing = [(year, month) for year in years for month in months if (year, month) not in by_key]
        if missing:
            raise RuntimeError(f'Monatsfelder fehlen: {missing[:8]}')

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


def maybe_restore_legacy_daily(year: int, month: int, target: Path) -> bool:
    if target.exists():
        return True
    legacy = LEGACY_CACHE_DIR / f'rank_daily_{year}_{month:02d}_full.nc'
    if not legacy.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, target)
    print(f'Übernehme vorhandenen Tagescache: {legacy.name}')
    return True


def previous_december_fields(core, client, years: list[int], lat_ref: np.ndarray, lon_ref: np.ndarray) -> np.ndarray:
    fields = []
    for year in years:
        if year <= HISTORY_START:
            fields.append(np.full((lat_ref.size, lon_ref.size), np.nan, dtype=np.float32))
            continue
        previous_year = year - 1
        annual_path = MONTHLY_CACHE_DIR / f'rank_monthly_{previous_year}_{previous_year}_01_12.nc'
        if annual_path.exists():
            mlat, mlon, annual = read_monthly_temperature(core, annual_path, [previous_year], list(range(1, 13)))
            december = annual[12][0]
        else:
            december_path = MONTHLY_CACHE_DIR / f'rank_monthly_{previous_year}_{previous_year}_12_12.nc'
            if not december_path.exists():
                request_monthly_temperature(core, client, [previous_year], [12], december_path)
            mlat, mlon, month_fields = read_monthly_temperature(core, december_path, [previous_year], [12])
            december = month_fields[12][0]
        if not (np.allclose(lat_ref, mlat) and np.allclose(lon_ref, mlon)):
            raise RuntimeError(f'Vorjahres-Dezember {previous_year} liegt auf einem abweichenden Raster.')
        fields.append(np.asarray(december, dtype=np.float32))
    return np.stack(fields, axis=0)


def build_shard(target: date, start_year: int, end_year: int) -> Path:
    history_end = target.year - 1
    if target.year <= HISTORY_START:
        raise ValueError(f'Zieljahr muss nach {HISTORY_START} liegen.')
    if start_year < HISTORY_START or end_year > history_end or start_year > end_year:
        raise ValueError(f'Ungültiger Historienbereich: {start_year}–{end_year}; erwartet {HISTORY_START}–{history_end}')

    DAILY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MONTHLY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SHARD_DIR.mkdir(parents=True, exist_ok=True)
    running, core = load_modules()
    client = running.cds_client()
    years = list(range(start_year, end_year + 1))
    month = target.month
    target_day = target.day

    day_parts = []
    mtd_parts = []
    lat_ref = lon_ref = None
    for year_group in daily_request_year_groups(years):
        year = year_group[0]
        daily_path = DAILY_CACHE_DIR / f'rank_daily_{year}_{month:02d}_full.nc'
        maybe_restore_legacy_daily(year, month, daily_path)
        if not daily_path.exists():
            month_days = calendar.monthrange(year, month)[1]
            running.request_daily_temperature(
                client,
                list(year_group),
                month,
                list(range(1, month_days + 1)),
                daily_path,
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

    all_months = list(range(1, 13))
    monthly_path = MONTHLY_CACHE_DIR / f'rank_monthly_{start_year}_{end_year}_01_12.nc'
    if not monthly_path.exists():
        request_monthly_temperature(core, client, years, all_months, monthly_path)
    mlat, mlon, complete_fields = read_monthly_temperature(core, monthly_path, years, all_months)
    if not (np.allclose(lat_ref, mlat) and np.allclose(lon_ref, mlon)):
        raise RuntimeError('Tages- und Monatsraster stimmen nicht überein.')

    year_stack = combine_year_to_date(
        complete_fields,
        np.asarray(years, dtype=int),
        month,
        target_day,
        mtd_stack,
    ).astype(np.float32)

    season_key, season_name, _ = season_for_month(month)
    previous_december = None
    if season_key == 'winter' and month in (1, 2):
        previous_december = previous_december_fields(core, client, years, lat_ref, lon_ref)
    season_stack = combine_season_to_date(
        complete_fields,
        np.asarray(years, dtype=int),
        month,
        target_day,
        mtd_stack,
        previous_december=previous_december,
    ).astype(np.float32)

    payload = {
        'target_date': np.asarray(target.isoformat()),
        'years': np.asarray(years, dtype=np.int16),
        'lat': np.asarray(lat_ref, dtype=np.float32),
        'lon': np.asarray(lon_ref, dtype=np.float32),
        'day': day_stack,
        'month_to_date': mtd_stack,
        'season_to_date': season_stack,
        'year_to_date': year_stack,
        'season_key': np.asarray(season_key),
        'season_name': np.asarray(season_name),
    }

    out = SHARD_DIR / f'temperature_rank_{start_year}_{end_year}_{target.isoformat()}.npz'
    np.savez_compressed(out, **payload)
    print(
        f'Rang-Shard fertig: {start_year}–{end_year} · {target} · '
        f'{", ".join(products_for_month(month))} · {out.stat().st_size/1024/1024:.1f} MiB'
    )
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
