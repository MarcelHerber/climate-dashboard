#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import json
from pathlib import Path

import numpy as np

from era5_running_temperature_rank import HISTORY_START, PRODUCTS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHARD_DIR = ROOT / '.era5_rank_reference_shards'
DEFAULT_OUTPUT_DIR = ROOT / '.era5_rank_reference_publish'


def finalize_month(
    *,
    shard_dir: Path,
    output_dir: Path,
    month: int,
    target_year: int,
    history_end: int,
) -> list[Path]:
    month = int(month)
    target_year = int(target_year)
    history_end = int(history_end)
    if month not in (9, 10, 11, 12):
        raise ValueError('Der Vorbau ist derzeit bewusst auf September bis Dezember begrenzt.')
    years = np.arange(HISTORY_START, history_end + 1, dtype=int)
    if years.size == 0:
        raise RuntimeError('Keine Historienjahre.')

    output_dir.mkdir(parents=True, exist_ok=True)
    end_day = calendar.monthrange(target_year, month)[1]
    created: list[Path] = []
    manifest_assets: list[dict] = []
    shard_index = {path.name: path for path in shard_dir.rglob('*.npz')}

    for day in range(1, end_day + 1):
        names = [
            f'temperature_rank_reference_{year}_{month:02d}_{day:02d}.npz'
            for year in years
        ]
        files = [shard_index.get(name) for name in names]
        missing = [name for name, path in zip(names, files) if path is None]
        if missing:
            raise RuntimeError(
                f'Referenz-Shards fehlen für {month:02d}-{day:02d}: '
                f'{missing[:8]}'
            )

        lat_ref = lon_ref = None
        product_parts = {product: [] for product in PRODUCTS}
        found_years: list[int] = []

        for path in files:
            assert path is not None
            with np.load(path, allow_pickle=False) as data:
                year = int(np.asarray(data['year']).item())
                file_month = int(np.asarray(data['month']).item())
                file_day = int(np.asarray(data['target_day']).item())
                lat = np.asarray(data['lat'], dtype=np.float32)
                lon = np.asarray(data['lon'], dtype=np.float32)
                if file_month != month or file_day != day:
                    raise RuntimeError(f'{path.name}: falsches Datum.')
                if lat_ref is None:
                    lat_ref, lon_ref = lat, lon
                elif not (
                    np.allclose(lat_ref, lat)
                    and np.allclose(lon_ref, lon)
                ):
                    raise RuntimeError(f'{path.name}: Rasterabweichung.')
                found_years.append(year)
                for product in PRODUCTS:
                    product_parts[product].append(
                        np.asarray(data[product], dtype=np.float32)
                    )

        if found_years != years.tolist():
            raise RuntimeError(
                f'Historienjahre für {month:02d}-{day:02d} unvollständig: '
                f'{found_years[:5]}…{found_years[-5:]}'
            )
        assert lat_ref is not None and lon_ref is not None

        asset = output_dir / (
            f'era5-rank-reference-{HISTORY_START}-{history_end}-'
            f'{month:02d}-{day:02d}.npz'
        )
        np.savez_compressed(
            asset,
            schema_version=np.asarray(1, dtype=np.int16),
            target_year=np.asarray(target_year, dtype=np.int16),
            target_month=np.asarray(month, dtype=np.int8),
            target_day=np.asarray(day, dtype=np.int8),
            years=years.astype(np.int16),
            lat=lat_ref.astype(np.float32),
            lon=lon_ref.astype(np.float32),
            **{
                product: np.stack(product_parts[product], axis=0).astype(np.float32)
                for product in PRODUCTS
            },
        )
        created.append(asset)
        manifest_assets.append(
            {
                'day': day,
                'file': asset.name,
                'bytes': asset.stat().st_size,
            }
        )
        print(
            f'Referenz fertig: {month:02d}-{day:02d} · '
            f'{years[0]}–{years[-1]} · {asset.stat().st_size/1024/1024:.1f} MiB',
            flush=True,
        )

    manifest = {
        'schema_version': 1,
        'target_year': target_year,
        'month': month,
        'history_start': int(years[0]),
        'history_end': int(years[-1]),
        'historical_years': int(years.size),
        'products': list(PRODUCTS),
        'assets': manifest_assets,
    }
    (output_dir / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    print(
        f'Monatsreferenz vollständig: {month:02d} · {len(created)} Tage · '
        f'{sum(p.stat().st_size for p in created)/1024/1024:.1f} MiB'
    )
    return created


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Historische ERA5-Land-Rangreferenzen 1950–2025 je Kalendertag zusammenführen.'
    )
    parser.add_argument('--month', type=int, required=True)
    parser.add_argument('--target-year', type=int, default=2026)
    parser.add_argument('--history-end', type=int, default=2025)
    parser.add_argument('--shard-dir', type=Path, default=DEFAULT_SHARD_DIR)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    finalize_month(
        shard_dir=args.shard_dir,
        output_dir=args.output_dir,
        month=args.month,
        target_year=args.target_year,
        history_end=args.history_end,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
