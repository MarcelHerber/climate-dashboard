#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

from build_era5_running_temperature_rank_shard import (
    CORE_PATH,
    CURRENT_CACHE_DIR,
    RUNNING_INDEX,
    RUNNING_PATH,
    load_module,
    read_daily_years,
    read_monthly_temperature,
    request_monthly_temperature,
)
from build_era5_temperature_rank_maps import render_rank_map
from era5_running_temperature_rank import (
    HISTORY_START,
    combine_season_to_date,
    combine_year_to_date,
    historical_years,
    product_filename,
    products_for_month,
    season_for_month,
)
from era5_temperature_rank import area_weighted_fraction, temperature_rank_field

ROOT = Path(__file__).resolve().parents[1]
SHARD_DIR = ROOT / '.era5_running_rank_shards'
OUT_DIR = ROOT / 'era5_land_europe' / 'running' / 'temperature_ranks'
INDEX_PATH = OUT_DIR / 'index.json'
ARCHIVE_DIR = OUT_DIR / 'archive'


def default_target_date() -> date:
    payload = json.loads(RUNNING_INDEX.read_text(encoding='utf-8'))
    return date.fromisoformat(str(payload['data_through']))


def load_history_shards(shard_dir: Path, target: date):
    files = sorted(shard_dir.glob(f'temperature_rank_*_{target.isoformat()}.npz'))
    if not files:
        raise RuntimeError(f'Keine Rang-Shards für {target} in {shard_dir}')

    active_products = products_for_month(target.month)
    parts = []
    lat_ref = lon_ref = None
    for path in files:
        with np.load(path, allow_pickle=False) as data:
            missing_products = [product for product in active_products if product not in data.files]
            if missing_products:
                raise RuntimeError(f'{path.name}: Produkte fehlen: {missing_products}')
            part = {
                'years': np.asarray(data['years'], dtype=int),
                **{
                    product: np.asarray(data[product], dtype=np.float32)
                    for product in active_products
                },
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
    expected = historical_years(target.year)
    if not np.array_equal(years, expected):
        raise RuntimeError(f'Historienjahre unvollständig: {years.tolist()}')
    fields = {
        product: np.concatenate([p[product] for p in parts], axis=0)[order]
        for product in active_products
    }
    assert lat_ref is not None and lon_ref is not None
    return years, lat_ref, lon_ref, fields


def current_fields(target: date):
    running = load_module(RUNNING_PATH, 'era5_running_rank_current_daily')
    core = load_module(CORE_PATH, 'era5_running_rank_current_monthly')
    running.GRID = [0.1, 0.1]
    running.CACHE_DIR = CURRENT_CACHE_DIR
    core.CACHE_DIR = CURRENT_CACHE_DIR
    CURRENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    client = running.cds_client()

    daily_path = CURRENT_CACHE_DIR / f'rank_current_{target.isoformat()}.nc'
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

    complete_months = list(range(1, target.month))
    complete_fields = {}
    if complete_months:
        monthly_path = CURRENT_CACHE_DIR / (
            f'rank_current_monthly_{target.year}_01_{complete_months[-1]:02d}.nc'
        )
        if not monthly_path.exists():
            request_monthly_temperature(core, client, [target.year], complete_months, monthly_path)
        mlat, mlon, complete_fields = read_monthly_temperature(core, monthly_path, [target.year], complete_months)
        if not (np.allclose(lat, mlat) and np.allclose(lon, mlon)):
            raise RuntimeError('Aktuelles Tages- und Monatsraster stimmen nicht überein.')

    season_key, _, _ = season_for_month(target.month)
    previous_december = None
    if season_key == 'winter' and target.month in (1, 2):
        previous_year = target.year - 1
        december_path = CURRENT_CACHE_DIR / f'rank_current_monthly_{previous_year}_12_12.nc'
        if not december_path.exists():
            request_monthly_temperature(core, client, [previous_year], [12], december_path)
        dlat, dlon, december_fields = read_monthly_temperature(core, december_path, [previous_year], [12])
        if not (np.allclose(lat, dlat) and np.allclose(lon, dlon)):
            raise RuntimeError('Aktueller Vorjahres-Dezember liegt auf einem abweichenden Raster.')
        previous_december = december_fields[12]

    result = {
        'day': day_field,
        'month_to_date': mtd_field,
        'season_to_date': combine_season_to_date(
            complete_fields,
            np.asarray([target.year], dtype=int),
            target.month,
            target.day,
            mtd_field[None, ...],
            previous_december=previous_december,
        )[0].astype(np.float32),
        'year_to_date': combine_year_to_date(
            complete_fields,
            np.asarray([target.year], dtype=int),
            target.month,
            target.day,
            mtd_field[None, ...],
        )[0].astype(np.float32),
    }
    return lat, lon, result


def period_label(product: str, target: date) -> str:
    if product == 'day':
        return target.strftime('%d.%m.%Y')
    if product == 'month_to_date':
        return f'01.–{target.day:02d}.{target.month:02d}.{target.year}'
    if product == 'season_to_date':
        season_key, season_name, start_month = season_for_month(target.month)
        start_year = target.year - 1 if season_key == 'winter' and target.month in (1, 2) else target.year
        return f'{season_name} · 01.{start_month:02d}.{start_year}–{target.day:02d}.{target.month:02d}.{target.year}'
    if product == 'year_to_date':
        return f'01.01.–{target.day:02d}.{target.month:02d}.{target.year}'
    raise ValueError(product)


def period_note(product: str, target: date, history_start: int, history_end: int) -> str:
    if product == 'day':
        leap_note = ' Für den 29.02. werden nur historische Schaltjahre verwendet.' if target.month == 2 and target.day == 29 else ''
        return (
            f'Vergleich des {target.day:02d}.{target.month:02d}. mit demselben Kalendertag '
            f'{history_start}–{history_end}.{leap_note}'
        )
    if product == 'month_to_date':
        return (
            f'Vergleich 01.–{target.day:02d}.{target.month:02d}. mit demselben Monatsabschnitt '
            f'{history_start}–{history_end}.'
        )
    if product == 'season_to_date':
        season_key, season_name, start_month = season_for_month(target.month)
        if season_key == 'winter' and target.month in (1, 2):
            return (
                f'Vergleich des laufenden Winters ab 01.12. des Vorjahres bis {target.day:02d}.{target.month:02d}. '
                f'mit demselben Winterabschnitt {history_start}–{history_end}. '
                f'Für den Winter {history_start} fehlt Dezember {history_start - 1}; dieser Winter wird deshalb ausgelassen.'
            )
        return (
            f'Vergleich {season_name} ab 01.{start_month:02d}. bis {target.day:02d}.{target.month:02d}. '
            f'mit demselben Jahreszeitenabschnitt {history_start}–{history_end}.'
        )
    if product == 'year_to_date':
        return (
            f'Vergleich 01.01.–{target.day:02d}.{target.month:02d}. mit demselben Jahresabschnitt '
            f'{history_start}–{history_end}.'
        )
    raise ValueError(product)


def archive_rank_payload(target: date, payload: dict) -> list[str]:
    archive_dir = ARCHIVE_DIR / target.isoformat()
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_products = {}

    for product, item in payload['products'].items():
        source = ROOT / str(item['file'])
        if not source.exists():
            raise RuntimeError(f'Rangkarte für Archiv fehlt: {source}')
        destination = archive_dir / f'{source.stem}.webp'
        with Image.open(source) as image:
            image.convert('RGB').save(destination, 'WEBP', lossless=True, method=6)
        archived_item = dict(item)
        archived_item['file'] = destination.relative_to(ROOT).as_posix()
        archived_products[product] = archived_item

    archived_payload = dict(payload)
    archived_payload['products'] = archived_products
    archived_payload['archived'] = True
    archived_payload['archive_format'] = 'lossless-webp'
    archive_index = archive_dir / 'index.json'
    archive_index.write_text(
        json.dumps(archived_payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
        encoding='utf-8',
    )

    dates = sorted(
        path.parent.name
        for path in ARCHIVE_DIR.glob('????-??-??/index.json')
        if path.parent.name[:4].isdigit()
    )
    return dates


def build_maps(target: date, shard_dir: Path = SHARD_DIR) -> Path:
    if target.year <= HISTORY_START:
        raise ValueError(f'Zieljahr muss nach {HISTORY_START} liegen.')
    years, hlat, hlon, history = load_history_shards(shard_dir, target)
    clat, clon, current = current_fields(target)
    if not (np.allclose(hlat, clat) and np.allclose(hlon, clon)):
        raise RuntimeError('Historisches und aktuelles 0,1°-Raster stimmen nicht überein.')

    history_start = int(years[0])
    history_end = int(years[-1])
    active_products = products_for_month(target.month)
    core = load_module(CORE_PATH, 'era5_running_rank_renderer')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    products = {}
    for product in active_products:
        rank = temperature_rank_field(current[product], history[product])
        valid = np.isfinite(rank)
        rank1 = area_weighted_fraction(rank <= 1, valid, hlat)
        top3 = area_weighted_fraction(rank <= 3, valid, hlat)
        valid_history_count = np.sum(np.isfinite(history[product]), axis=0)
        comparison_years = int(np.max(valid_history_count)) if valid_history_count.size else 0
        total_rank_positions = comparison_years + 1
        filename = OUT_DIR / product_filename(product)
        render_rank_map(
            core,
            rank,
            hlat,
            hlon,
            label=period_label(product, target),
            year=target.year,
            history_start=history_start,
            history_end=history_end,
            filename=filename,
            total_rank_positions=total_rank_positions,
        )
        products[product] = {
            'file': filename.relative_to(ROOT).as_posix(),
            'label': period_label(product, target),
            'unit': 'Rang',
            **(
                {
                    'season_key': season_for_month(target.month)[0],
                    'season_name': season_for_month(target.month)[1],
                }
                if product == 'season_to_date'
                else {}
            ),
            'history_start': history_start,
            'history_end': history_end,
            'comparison_years': comparison_years,
            'total_rank_positions': total_rank_positions,
            'rank_direction': '1 = wärmster',
            'note': period_note(product, target, history_start, history_end),
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
        'history_start': history_start,
        'history_end': history_end,
        'historical_years': int(years.size),
        'total_rank_positions': int(years.size + 1),
        'grid': '0,1° ERA5-Land',
        'rank_direction': '1 = wärmster',
        'products': products,
    }
    available_dates = archive_rank_payload(target, payload)
    payload['available_dates'] = available_dates
    payload['archive_index_pattern'] = (
        'era5_land_europe/running/temperature_ranks/archive/{date}/index.json'
    )
    payload['archive_image_format'] = 'lossless-webp'
    INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(
        f'Fertig: {len(active_products)} laufende Temperatur-Rangkarten für {target} · '
        f'{len(available_dates)} Archivstände.'
    )
    return INDEX_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description='Ganzjährige laufende ERA5-Land-Temperatur-Rangkarten erzeugen.')
    parser.add_argument('--target-date')
    parser.add_argument('--shards-dir', type=Path, default=SHARD_DIR)
    args = parser.parse_args()
    target = date.fromisoformat(args.target_date) if args.target_date else default_target_date()
    build_maps(target, args.shards_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
