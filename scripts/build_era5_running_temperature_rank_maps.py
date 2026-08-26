#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from build_era5_running_temperature_rank_shard import (
    CACHE_DIR,
    CORE_PATH,
    RUNNING_INDEX,
    RUNNING_PATH,
    load_module,
    read_daily_years,
    read_monthly_temperature,
)
from build_era5_temperature_rank_maps import render_rank_map
from era5_running_temperature_rank import (
    HISTORY_END,
    HISTORY_START,
    PRODUCTS,
    combine_summer_to_date,
    historical_years,
    product_filename,
)
from era5_temperature_rank import area_weighted_fraction, temperature_rank_field

ROOT = Path(__file__).resolve().parents[1]
SHARD_DIR = ROOT / '.era5_running_rank_shards'
OUT_DIR = ROOT / 'era5_land_europe' / 'running' / 'temperature_ranks'
INDEX_PATH = OUT_DIR / 'index.json'


def default_target_date() -> date:
    payload = json.loads(RUNNING_INDEX.read_text(encoding='utf-8'))
    return date.fromisoformat(str(payload['data_through']))


def load_history_shards(shard_dir: Path, target: date):
    files = sorted(shard_dir.glob(f'temperature_rank_*_{target.isoformat()}.npz'))
    if not files:
        raise RuntimeError(f'Keine Rang-Shards für {target} in {shard_dir}')

    parts = []
    lat_ref = lon_ref = None
    for path in files:
        with np.load(path, allow_pickle=False) as data:
            part = {
                'years': np.asarray(data['years'], dtype=int),
                'day': np.asarray(data['day'], dtype=np.float32),
                'month_to_date': np.asarray(data['month_to_date'], dtype=np.float32),
                'summer_to_date': np.asarray(data['summer_to_date'], dtype=np.float32),
            }
            lat = np.asarray(data['lat'], dtype=float)
            lon = np.asarray(data['lon'], dtype=float)
        if lat_ref is None:
            lat_ref, lon_ref = lat, lon
        elif not (np.allclose(lat_ref, lat) and np.allclose(lon_ref, lon)):
            raise RuntimeError(f'Rasterabweichung in {path.name}')
        parts.append(part)

    order = np.argsort(np.concatenate([p['years'] for p in parts]))
    years = np.concatenate([p['years'] for p in parts])[order]
    expected = historical_years()
    if not np.array_equal(years, expected):
        raise RuntimeError(f'Historienjahre unvollständig: {years.tolist()}')
    fields = {
        product: np.concatenate([p[product] for p in parts], axis=0)[order]
        for product in PRODUCTS
    }
    assert lat_ref is not None and lon_ref is not None
    return years, lat_ref, lon_ref, fields


def current_fields(target: date):
    if target.month not in (6, 7, 8):
        raise ValueError('Sommer-Rangkarten werden nur für Juni bis August erzeugt.')
    running = load_module(RUNNING_PATH, 'era5_running_rank_current_daily')
    core = load_module(CORE_PATH, 'era5_running_rank_current_monthly')
    running.GRID = [0.1, 0.1]
    running.CACHE_DIR = CACHE_DIR
    core.CACHE_DIR = CACHE_DIR
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    client = running.cds_client()

    daily_path = CACHE_DIR / f'rank_current_{target.isoformat()}.nc'
    if not daily_path.exists():
        running.request_daily_temperature(
            client,
            [target.year],
            target.month,
            list(range(1, target.day + 1)),
            daily_path,
            f'Aktuelle Temperatur-Ränge bis {target.isoformat()}',
        )
    lat, lon, day_stack, mtd_stack = read_daily_years(running, daily_path, [target.year], target.day)
    day_field, mtd_field = day_stack[0], mtd_stack[0]

    complete_months = list(range(6, target.month))
    complete_fields = {}
    if complete_months:
        monthly_path = CACHE_DIR / (
            f'rank_current_monthly_{target.year}_' + '_'.join(f'{m:02d}' for m in complete_months) + '.nc'
        )
        if not monthly_path.exists():
            core.request_monthly_file(client, [target.year], complete_months, monthly_path)
        mlat, mlon, complete_fields = read_monthly_temperature(core, monthly_path, [target.year], complete_months)
        if not (np.allclose(lat, mlat) and np.allclose(lon, mlon)):
            raise RuntimeError('Aktuelles Tages- und Monatsraster stimmen nicht überein.')

    summer = combine_summer_to_date(
        complete_fields,
        np.asarray([target.year], dtype=int),
        target.month,
        target.day,
        mtd_field[None, ...],
    )[0].astype(np.float32)
    return lat, lon, {
        'day': day_field,
        'month_to_date': mtd_field,
        'summer_to_date': summer,
    }


def period_label(product: str, target: date) -> str:
    if product == 'day':
        return target.strftime('%d.%m.%Y')
    if product == 'month_to_date':
        return f'01.–{target.day:02d}.{target.month:02d}.{target.year}'
    if product == 'summer_to_date':
        return f'01.06.–{target.day:02d}.{target.month:02d}.{target.year}'
    raise ValueError(product)


def period_note(product: str, target: date) -> str:
    if product == 'day':
        return f'Vergleich des {target.day:02d}.{target.month:02d}. mit demselben Kalendertag 1950–2025.'
    if product == 'month_to_date':
        return f'Vergleich 01.–{target.day:02d}.{target.month:02d}. mit demselben Monatsabschnitt 1950–2025.'
    return f'Vergleich 01.06.–{target.day:02d}.{target.month:02d}. mit demselben Sommerabschnitt 1950–2025.'


def build_maps(target: date, shard_dir: Path = SHARD_DIR) -> Path:
    if target.year != 2026:
        raise ValueError(f'Diese erste Rangserie ist für 2026 gebaut, nicht für {target.year}.')
    years, hlat, hlon, history = load_history_shards(shard_dir, target)
    clat, clon, current = current_fields(target)
    if not (np.allclose(hlat, clat) and np.allclose(hlon, clon)):
        raise RuntimeError('Historisches und aktuelles 0,1°-Raster stimmen nicht überein.')

    core = load_module(CORE_PATH, 'era5_running_rank_renderer')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    products = {}
    for product in PRODUCTS:
        rank = temperature_rank_field(current[product], history[product])
        valid = np.isfinite(rank)
        rank1 = area_weighted_fraction(rank <= 1, valid, hlat)
        top3 = area_weighted_fraction(rank <= 3, valid, hlat)
        filename = OUT_DIR / product_filename(product)
        render_rank_map(
            core,
            rank,
            hlat,
            hlon,
            label=period_label(product, target),
            year=target.year,
            history_start=HISTORY_START,
            history_end=HISTORY_END,
            filename=filename,
        )
        products[product] = {
            'file': filename.relative_to(ROOT).as_posix(),
            'label': period_label(product, target),
            'unit': 'Rang',
            'history_start': HISTORY_START,
            'history_end': HISTORY_END,
            'comparison_years': HISTORY_END - HISTORY_START + 1,
            'total_rank_positions': HISTORY_END - HISTORY_START + 2,
            'rank_direction': '1 = wärmster',
            'note': period_note(product, target),
            'stats': {
                'rank1_area_percent': rank1,
                'top3_area_percent': top3,
                'valid_gridpoints': int(valid.sum()),
                'min_rank': int(np.nanmin(rank)) if valid.any() else None,
                'max_rank': int(np.nanmax(rank)) if valid.any() else None,
            },
        }
        print(f'{product}: Rang-1-Fläche {rank1:.2f}% · Top-3 {top3:.2f}%')

    payload = {
        'ready': True,
        'data_through': target.isoformat(),
        'current_year': target.year,
        'history_start': HISTORY_START,
        'history_end': HISTORY_END,
        'historical_years': int(years.size),
        'total_rank_positions': int(years.size + 1),
        'grid': '0,1° ERA5-Land',
        'rank_direction': '1 = wärmster',
        'products': products,
    }
    INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(f'Fertig: 3 laufende Temperatur-Rangkarten für {target}.')
    return INDEX_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description='Drei laufende ERA5-Land-Temperatur-Rangkarten erzeugen.')
    parser.add_argument('--target-date')
    parser.add_argument('--shards-dir', type=Path, default=SHARD_DIR)
    args = parser.parse_args()
    target = date.fromisoformat(args.target_date) if args.target_date else default_target_date()
    build_maps(target, args.shards_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
