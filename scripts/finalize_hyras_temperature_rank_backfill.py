#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

try:
    from build_hyras_temperature_rank_maps import _render
    from hyras_temperature_rank import PRODUCTS
    from update_hyras_maps import guess_crs_from_xy, load_boundaries
except ModuleNotFoundError:
    from scripts.build_hyras_temperature_rank_maps import _render
    from scripts.hyras_temperature_rank import PRODUCTS
    from scripts.update_hyras_maps import guess_crs_from_xy, load_boundaries


PARAMETERS = ("tmean", "tmax", "tmin")


def _all_dates(target: date) -> list[str]:
    values: list[str] = []
    cursor = date(2026, 6, 1)
    while cursor <= target:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return values


def _load_counts(shard_dir: Path, parameter: str):
    files = sorted(shard_dir.glob(f"contrib_{parameter}_*.npz"))
    if not files:
        raise RuntimeError(f"Keine Backfill-Beiträge für {parameter} gefunden")

    dates_ref = x_ref = y_ref = None
    greater_sum = valid_sum = None
    years: list[int] = []

    for path in files:
        with np.load(path, allow_pickle=False) as data:
            p = str(np.asarray(data["parameter"]).item())
            if p != parameter:
                raise RuntimeError(f"{path}: Parameter {p} statt {parameter}")
            target_dates = np.asarray(data["target_dates"]).astype(str)
            x = np.asarray(data["x"], dtype=np.float64)
            y = np.asarray(data["y"], dtype=np.float64)
            greater = np.asarray(data["greater"], dtype=np.uint8)
            valid = np.asarray(data["valid_count"], dtype=np.uint8)
            start_year = int(np.asarray(data["start_year"]).item())
            end_year = int(np.asarray(data["end_year"]).item())

        if dates_ref is None:
            dates_ref = target_dates
            x_ref = x
            y_ref = y
            greater_sum = np.zeros(greater.shape, dtype=np.uint16)
            valid_sum = np.zeros(valid.shape, dtype=np.uint16)
        else:
            if not np.array_equal(target_dates, dates_ref):
                raise RuntimeError(f"{path}: abweichende Zieldaten")
            if not np.allclose(x, x_ref) or not np.allclose(y, y_ref):
                raise RuntimeError(f"{path}: abweichendes Raster")

        greater_sum += greater
        valid_sum += valid
        years.extend(range(start_year, end_year + 1))

    expected = list(range(1951, 2026))
    if sorted(years) != expected:
        raise RuntimeError(
            f"Historische Jahre unvollständig für {parameter}: "
            f"{min(years)}–{max(years)} · {len(years)} Jahre"
        )
    assert dates_ref is not None and x_ref is not None and y_ref is not None
    assert greater_sum is not None and valid_sum is not None
    return dates_ref, x_ref, y_ref, greater_sum, valid_sum


def build_archive(
    *,
    data_root: Path,
    shard_dir: Path,
    current_dir: Path,
    target: date,
    factor: int,
) -> None:
    out_root = data_root / "temperature_ranks"
    index_path = out_root / "index.json"
    if not index_path.exists():
        raise RuntimeError("temperature_ranks/index.json fehlt im hyras-data-Branch")

    manifest = json.loads(index_path.read_text(encoding="utf-8"))
    expected_dates = _all_dates(target)
    geojson = load_boundaries()
    if not geojson:
        raise RuntimeError("Bundeslandgrenzen konnten nicht geladen werden")

    for parameter in PARAMETERS:
        current_files = sorted(current_dir.glob(f"current_{parameter}_*.npz"))
        if len(current_files) != 1:
            raise RuntimeError(
                f"Erwartet genau einen aktuellen Stack für {parameter}, gefunden {len(current_files)}"
            )
        with np.load(current_files[0], allow_pickle=False) as current:
            current_dates = np.asarray(current["target_dates"]).astype(str)
            current_x = np.asarray(current["x"], dtype=np.float64)
            current_y = np.asarray(current["y"], dtype=np.float64)
            current_products = {
                product: np.asarray(current[product], dtype=np.float32)
                for product in PRODUCTS
            }

        dates, x, y, greater, valid = _load_counts(shard_dir, parameter)
        if not np.array_equal(dates, current_dates):
            raise RuntimeError(f"{parameter}: aktuelle und historische Zieldaten weichen ab")
        if not np.allclose(x, current_x) or not np.allclose(y, current_y):
            raise RuntimeError(f"{parameter}: aktuelle und historische Raster weichen ab")

        data_crs = guess_crs_from_xy(x, y)
        for product_index, product in enumerate(PRODUCTS):
            current_stack = current_products[product]
            for target_index, target_text in enumerate(dates):
                archive = (
                    out_root / "archive" / target_text / parameter / f"{product}_rank.png"
                )
                if archive.exists():
                    continue

                rank = 1.0 + greater[target_index, product_index].astype(np.float32)
                current_valid = np.isfinite(current_stack[target_index])
                rank[(valid[target_index, product_index] == 0) | ~current_valid] = np.nan
                _render(
                    rank,
                    x,
                    y,
                    geojson,
                    data_crs,
                    archive,
                    parameter,
                    product,
                    date.fromisoformat(str(target_text)),
                    factor,
                )
                print(
                    f"Archivkarte: {target_text} · {parameter} · {product}",
                    flush=True,
                )

    complete: list[str] = []
    for target_text in expected_dates:
        ok = all(
            (
                out_root / "archive" / target_text / parameter / f"{product}_rank.png"
            ).exists()
            for parameter in PARAMETERS
            for product in PRODUCTS
        )
        if ok:
            complete.append(target_text)

    if complete != expected_dates:
        missing = sorted(set(expected_dates) - set(complete))
        raise RuntimeError(f"Backfill unvollständig; fehlende Tage: {missing[:10]}")

    manifest["schema_version"] = max(2, int(manifest.get("schema_version", 1)))
    manifest["archive_pattern"] = (
        "temperature_ranks/archive/{date}/{parameter}/{product}_rank.png"
    )
    manifest["available_dates"] = complete
    index_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"HYRAS-Rangkarten-Sommerarchiv vollständig: "
        f"{complete[0]}–{complete[-1]} · {len(complete)} Tage",
        flush=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--shard-dir", required=True)
    ap.add_argument("--current-dir", required=True)
    ap.add_argument("--target-date", required=True)
    ap.add_argument("--factor", type=int, default=1)
    args = ap.parse_args()
    build_archive(
        data_root=Path(args.data_root),
        shard_dir=Path(args.shard_dir),
        current_dir=Path(args.current_dir),
        target=date.fromisoformat(args.target_date),
        factor=args.factor,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
