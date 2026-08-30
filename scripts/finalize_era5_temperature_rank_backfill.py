#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

from build_era5_running_temperature_rank_maps import period_label, period_note
from build_era5_running_temperature_rank_shard import CORE_PATH, load_module
from build_era5_temperature_rank_maps import render_rank_map
from era5_running_temperature_rank import (
    HISTORY_START,
    PRODUCTS,
    product_filename,
    season_for_month,
)
from era5_temperature_rank import area_weighted_fraction

ROOT = Path(__file__).resolve().parents[1]


def load_current(current_dir: Path):
    files = sorted(current_dir.glob('current_*.npz'))
    if len(files) != 1:
        raise RuntimeError(
            f'Genau ein aktueller Monatsstack erwartet, gefunden: {[p.name for p in files]}'
        )
    with np.load(files[0], allow_pickle=False) as data:
        return {
            'year': int(np.asarray(data['year']).item()),
            'month': int(np.asarray(data['month']).item()),
            'target_dates': np.asarray(data['target_dates']).astype(str),
            'lat': np.asarray(data['lat'], dtype=np.float64),
            'lon': np.asarray(data['lon'], dtype=np.float64),
            'products': {
                product: np.asarray(data[product], dtype=np.float32)
                for product in PRODUCTS
            },
        }


def load_contributions(shard_dir: Path, current: dict):
    files = sorted(shard_dir.glob('contrib_*.npz'))
    if not files:
        raise RuntimeError('Keine historischen Backfill-Beiträge gefunden.')

    greater_sum = None
    valid_sum = None
    years: list[int] = []
    for path in files:
        with np.load(path, allow_pickle=False) as data:
            year = int(np.asarray(data['year']).item())
            target_dates = np.asarray(data['target_dates']).astype(str)
            lat = np.asarray(data['lat'], dtype=np.float64)
            lon = np.asarray(data['lon'], dtype=np.float64)
            greater = np.asarray(data['greater'], dtype=np.uint8)
            valid = np.asarray(data['valid_count'], dtype=np.uint8)

        if not np.array_equal(target_dates, current['target_dates']):
            raise RuntimeError(f'{path.name}: abweichende Zieldaten')
        if not (
            np.allclose(lat, current['lat'])
            and np.allclose(lon, current['lon'])
        ):
            raise RuntimeError(f'{path.name}: abweichendes Raster')
        expected_shape = (
            current['target_dates'].size,
            len(PRODUCTS),
            current['lat'].size,
            current['lon'].size,
        )
        if greater.shape != expected_shape or valid.shape != expected_shape:
            raise RuntimeError(
                f'{path.name}: Beitragsform {greater.shape}/{valid.shape} statt {expected_shape}'
            )

        if greater_sum is None:
            greater_sum = np.zeros(greater.shape, dtype=np.uint16)
            valid_sum = np.zeros(valid.shape, dtype=np.uint16)
        greater_sum += greater
        valid_sum += valid
        years.append(year)

    expected_years = list(range(HISTORY_START, current['year']))
    if sorted(years) != expected_years:
        missing = sorted(set(expected_years) - set(years))
        extra = sorted(set(years) - set(expected_years))
        raise RuntimeError(
            f'Historische Jahre unvollständig: {len(years)} statt {len(expected_years)} · '
            f'fehlend {missing[:8]} · zusätzlich {extra[:8]}'
        )
    assert greater_sum is not None and valid_sum is not None
    return np.asarray(sorted(years), dtype=int), greater_sum, valid_sum


def render_entry(
    *,
    product: str,
    target: date,
    rank: np.ndarray,
    valid_history_count: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    history_start: int,
    history_end: int,
    destination: Path,
    core,
    work_dir: Path,
) -> dict:
    valid = np.isfinite(rank)
    comparison_years = int(np.max(valid_history_count)) if valid_history_count.size else 0
    total_rank_positions = comparison_years + 1
    temp_png = work_dir / f'{target.isoformat()}_{product}.png'
    render_rank_map(
        core,
        rank,
        lat,
        lon,
        label=period_label(product, target),
        year=target.year,
        history_start=history_start,
        history_end=history_end,
        filename=temp_png,
        total_rank_positions=total_rank_positions,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(temp_png) as image:
        image.convert('RGB').save(destination, 'WEBP', lossless=True, method=6)
    temp_png.unlink(missing_ok=True)

    rank1 = area_weighted_fraction(rank <= 1, valid, lat)
    top3 = area_weighted_fraction(rank <= 3, valid, lat)
    item = {
        'file': destination.resolve().relative_to(ROOT.resolve()).as_posix(),
        'label': period_label(product, target),
        'unit': 'Rang',
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
    if product == 'season_to_date':
        season_key, season_name, _ = season_for_month(target.month)
        item['season_key'] = season_key
        item['season_name'] = season_name
    return item



def save_month_data_archive(
    *,
    current: dict,
    greater: np.ndarray,
    valid_count: np.ndarray,
    years: np.ndarray,
    rank_root: Path,
) -> tuple[Path, dict]:
    year = int(current['year'])
    month = int(current['month'])
    history_start = int(years[0])
    history_end = int(years[-1])
    archive_dir = rank_root / 'data_archive'
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f'{year}-{month:02d}.npz'

    encoded: dict[str, np.ndarray] = {}
    for product_index, product in enumerate(PRODUCTS):
        current_stack = np.asarray(current['products'][product], dtype=np.float32)
        valid = (
            (valid_count[:, product_index] > 0)
            & np.isfinite(current_stack)
        )
        rank = 1 + greater[:, product_index]
        encoded[product] = np.where(valid, rank, 0).astype(np.uint8)

    np.savez_compressed(
        archive_path,
        schema_version=np.asarray(1, dtype=np.int16),
        year=np.asarray(year, dtype=np.int16),
        month=np.asarray(month, dtype=np.int8),
        target_dates=np.asarray(current['target_dates']),
        lat=np.asarray(current['lat'], dtype=np.float32),
        lon=np.asarray(current['lon'], dtype=np.float32),
        history_start=np.asarray(history_start, dtype=np.int16),
        history_end=np.asarray(history_end, dtype=np.int16),
        historical_years=np.asarray(years.size, dtype=np.int16),
        missing_value=np.asarray(0, dtype=np.uint8),
        rank_direction=np.asarray('1 = wärmster'),
        **encoded,
    )
    meta = {
        'file': archive_path.resolve().relative_to(ROOT.resolve()).as_posix(),
        'format': 'npz-uint8-ranks',
        'missing_value': 0,
        'grid': '0,1° ERA5-Land',
        'history_start': history_start,
        'history_end': history_end,
        'historical_years': int(years.size),
        'products': list(PRODUCTS),
        'first_date': str(current['target_dates'][0]),
        'last_date': str(current['target_dates'][-1]),
        'days': int(current['target_dates'].size),
        'bytes': int(archive_path.stat().st_size),
    }
    print(
        f'Datenarchiv gespeichert: {archive_path.name} · '
        f'{meta["days"]} Tage · {meta["bytes"]/1024/1024:.1f} MiB',
        flush=True,
    )
    return archive_path, meta



def finalize_month(current_dir: Path, shard_dir: Path, data_root: Path) -> list[str]:
    current = load_current(current_dir)
    years, greater, valid_count = load_contributions(shard_dir, current)
    rank_root = data_root / 'era5_land_europe' / 'running' / 'temperature_ranks'
    index_path = rank_root / 'index.json'
    if not index_path.exists():
        raise RuntimeError(f'Aktueller Rangindex fehlt: {index_path}')

    main_manifest = json.loads(index_path.read_text(encoding='utf-8'))
    history_start = int(years[0])
    history_end = int(years[-1])
    core = load_module(CORE_PATH, 'era5_rank_backfill_renderer')
    data_archive_path, data_archive_meta = save_month_data_archive(
        current=current,
        greater=greater,
        valid_count=valid_count,
        years=years,
        rank_root=rank_root,
    )
    created_dates: list[str] = []

    with tempfile.TemporaryDirectory(prefix='era5-rank-backfill-render-') as tmp:
        work_dir = Path(tmp)
        for date_index, target_text in enumerate(current['target_dates']):
            target = date.fromisoformat(str(target_text))
            archive_dir = rank_root / 'archive' / target_text
            products = {}
            for product_index, product in enumerate(PRODUCTS):
                current_field = current['products'][product][date_index]
                history_valid = valid_count[date_index, product_index]
                rank = 1.0 + greater[date_index, product_index].astype(np.float32)
                rank[(history_valid == 0) | ~np.isfinite(current_field)] = np.nan

                destination = (
                    archive_dir
                    / product_filename(product).replace('.png', '.webp')
                )
                products[product] = render_entry(
                    product=product,
                    target=target,
                    rank=rank,
                    valid_history_count=history_valid,
                    lat=current['lat'],
                    lon=current['lon'],
                    history_start=history_start,
                    history_end=history_end,
                    destination=destination,
                    core=core,
                    work_dir=work_dir,
                )

            payload = {
                'ready': True,
                'archived': True,
                'archive_format': 'lossless-webp',
                'data_through': target.isoformat(),
                'current_year': target.year,
                'history_start': history_start,
                'history_end': history_end,
                'historical_years': int(years.size),
                'total_rank_positions': int(years.size + 1),
                'grid': '0,1° ERA5-Land',
                'rank_direction': '1 = wärmster',
                'data_archive': {
                    'file': data_archive_meta['file'],
                    'format': data_archive_meta['format'],
                    'missing_value': 0,
                    'day_index': int(date_index),
                },
                'products': products,
            }
            (archive_dir / 'index.json').write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                encoding='utf-8',
            )
            created_dates.append(target_text)
            print(
                f'Archivtag fertig: {target_text} · {len(PRODUCTS)} Karten',
                flush=True,
            )

    available = sorted(
        set(main_manifest.get('available_dates', []))
        | set(created_dates)
    )
    main_manifest['available_dates'] = available
    main_manifest['archive_index_pattern'] = (
        'era5_land_europe/running/temperature_ranks/archive/{date}/index.json'
    )
    main_manifest['archive_image_format'] = 'lossless-webp'
    main_manifest['data_archive_pattern'] = (
        'era5_land_europe/running/temperature_ranks/data_archive/{year}-{month}.npz'
    )
    data_archives = dict(main_manifest.get('data_archives') or {})
    data_archives[f"{current['year']}-{current['month']:02d}"] = data_archive_meta
    main_manifest['data_archives'] = data_archives
    index_path.write_text(
        json.dumps(main_manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
        encoding='utf-8',
    )

    if not data_archive_path.exists() or data_archive_path.stat().st_size <= 0:
        raise RuntimeError(f'Datenarchiv fehlt oder ist leer: {data_archive_path}')

    for target_text in created_dates:
        archive_dir = rank_root / 'archive' / target_text
        if not (archive_dir / 'index.json').exists():
            raise RuntimeError(f'Archivindex fehlt: {target_text}')
        for product in PRODUCTS:
            path = archive_dir / product_filename(product).replace('.png', '.webp')
            if not path.exists():
                raise RuntimeError(f'Archivkarte fehlt: {path}')

    print(
        f'Monats-Backfill vollständig: {created_dates[0]}–{created_dates[-1]} · '
        f'{len(created_dates)} Tage · insgesamt {len(available)} Archivtage.',
        flush=True,
    )
    return created_dates


def main() -> int:
    parser = argparse.ArgumentParser(description='ERA5-Temperatur-Rangarchiv für einen Monat finalisieren.')
    parser.add_argument('--current-dir', type=Path, required=True)
    parser.add_argument('--shard-dir', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=ROOT)
    args = parser.parse_args()
    finalize_month(args.current_dir, args.shard_dir, args.data_root)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
