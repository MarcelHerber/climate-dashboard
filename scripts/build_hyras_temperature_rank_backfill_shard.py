#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

try:
    from build_hyras_temperature_rank_shard import (
        _build_year_cache,
        _source_module,
        DEFAULT_FACTOR,
    )
    from hyras_temperature_rank import PRODUCTS, dequantize_temperature
except ModuleNotFoundError:
    from scripts.build_hyras_temperature_rank_shard import (
        _build_year_cache,
        _source_module,
        DEFAULT_FACTOR,
    )
    from scripts.hyras_temperature_rank import PRODUCTS, dequantize_temperature


def _target_codes(target_dates: np.ndarray) -> np.ndarray:
    return np.asarray(
        [int(str(value)[5:7]) * 100 + int(str(value)[8:10]) for value in target_dates],
        dtype=np.uint16,
    )


def build_contribution(
    *,
    parameter: str,
    start_year: int,
    end_year: int,
    current_file: Path,
    factor: int,
    cache_root: Path,
    work: Path,
    output: Path,
) -> None:
    module = _source_module(parameter)
    with np.load(current_file, allow_pickle=False) as current:
        current_parameter = str(np.asarray(current["parameter"]).item())
        if current_parameter != parameter:
            raise RuntimeError(
                f"Aktueller Stack ist {current_parameter}, erwartet {parameter}"
            )
        target_dates = np.asarray(current["target_dates"]).astype(str)
        x_ref = np.asarray(current["x"], dtype=np.float64)
        y_ref = np.asarray(current["y"], dtype=np.float64)
        current_products = {
            product: np.asarray(current[product], dtype=np.float32)
            for product in PRODUCTS
        }

    n_targets = target_dates.size
    ny, nx = y_ref.size, x_ref.size
    greater = np.zeros((n_targets, len(PRODUCTS), ny, nx), dtype=np.uint8)
    valid_count = np.zeros_like(greater)
    code_to_index = {
        int(code): idx for idx, code in enumerate(_target_codes(target_dates))
    }

    for year in range(start_year, end_year + 1):
        codes, packed, x, y = _build_year_cache(
            module, parameter, year, factor, cache_root, work
        )
        if (
            x.shape != x_ref.shape
            or y.shape != y_ref.shape
            or not np.allclose(x, x_ref)
            or not np.allclose(y, y_ref)
        ):
            raise RuntimeError(f"HYRAS-{parameter}: Rasterabweichung im Jahr {year}")

        values = dequantize_temperature(packed)
        summer_sum = np.zeros((ny, nx), dtype=np.float64)
        summer_n = np.zeros((ny, nx), dtype=np.uint16)
        month_sum = np.zeros((ny, nx), dtype=np.float64)
        month_n = np.zeros((ny, nx), dtype=np.uint16)
        active_month = None

        for day_index, code_raw in enumerate(codes):
            code = int(code_raw)
            month = code // 100
            if month != active_month:
                month_sum.fill(0.0)
                month_n.fill(0)
                active_month = month

            arr = np.asarray(values[day_index], dtype=np.float64)
            valid = np.isfinite(arr)
            safe = np.where(valid, arr, 0.0)
            summer_sum += safe
            summer_n += valid
            month_sum += safe
            month_n += valid

            target_index = code_to_index.get(code)
            if target_index is None:
                continue

            month_mean = np.full((ny, nx), np.nan, dtype=np.float64)
            summer_mean = np.full((ny, nx), np.nan, dtype=np.float64)
            np.divide(month_sum, month_n, out=month_mean, where=month_n > 0)
            np.divide(summer_sum, summer_n, out=summer_mean, where=summer_n > 0)

            history_fields = (
                arr.astype(np.float32),
                month_mean.astype(np.float32),
                summer_mean.astype(np.float32),
            )
            for product_index, product in enumerate(PRODUCTS):
                hist = history_fields[product_index]
                cur = current_products[product][target_index]
                valid_hist = np.isfinite(hist)
                valid_count[target_index, product_index] += valid_hist
                greater[target_index, product_index] += (
                    valid_hist & (hist > cur)
                )

        del values, packed

    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        parameter=np.asarray(parameter),
        start_year=np.asarray(start_year, dtype=np.int16),
        end_year=np.asarray(end_year, dtype=np.int16),
        target_dates=target_dates,
        x=x_ref,
        y=y_ref,
        greater=greater,
        valid_count=valid_count,
    )
    print(
        f"Backfill-Beitrag fertig: {parameter} {start_year}–{end_year} · "
        f"{n_targets} Tage · {output}",
        flush=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parameter", choices=("tmean", "tmax", "tmin"), required=True)
    ap.add_argument("--start-year", type=int, required=True)
    ap.add_argument("--end-year", type=int, required=True)
    ap.add_argument("--current-file", required=True)
    ap.add_argument("--factor", type=int, default=DEFAULT_FACTOR)
    ap.add_argument("--cache-root", default="/tmp/hyras-temperature-rank-history")
    ap.add_argument("--work", default="/tmp/hyras-temperature-rank-backfill-work")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    build_contribution(
        parameter=args.parameter,
        start_year=args.start_year,
        end_year=args.end_year,
        current_file=Path(args.current_file),
        factor=args.factor,
        cache_root=Path(args.cache_root),
        work=Path(args.work) / args.parameter,
        output=Path(args.output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
