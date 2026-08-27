#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

try:
    from build_hyras_temperature_rank_shard import _build_year_cache, _source_module
    from hyras_temperature_rank import dequantize_temperature
except ModuleNotFoundError:
    from scripts.build_hyras_temperature_rank_shard import _build_year_cache, _source_module
    from scripts.hyras_temperature_rank import dequantize_temperature


REFERENCES = (
    ("1961-1990", 1961, 1990),
    ("1991-2020", 1991, 2020),
)
DEFAULT_DISPLAY_FACTOR = 5


def _reference_index(year: int) -> int | None:
    for index, (_label, start, end) in enumerate(REFERENCES):
        if start <= year <= end:
            return index
    return None


def build_contribution(
    *,
    parameter: str,
    start_year: int,
    end_year: int,
    display_factor: int,
    cache_root: Path,
    work: Path,
    output: Path,
) -> None:
    module = _source_module(parameter)
    years = np.arange(start_year, end_year + 1, dtype=int)

    sums = None
    counts = None
    codes_ref = None
    x_ref = None
    y_ref = None
    used_years: list[int] = []

    for year in years:
        reference_index = _reference_index(int(year))
        if reference_index is None:
            continue

        codes, packed, x, y = _build_year_cache(
            module,
            parameter,
            int(year),
            1,
            cache_root,
            work,
        )

        sampled_packed = np.asarray(
            packed[:, ::display_factor, ::display_factor],
            dtype=np.int16,
        )
        values = dequantize_temperature(sampled_packed)
        sx = np.asarray(x[::display_factor], dtype=np.float64)
        sy = np.asarray(y[::display_factor], dtype=np.float64)

        if codes_ref is None:
            codes_ref = np.asarray(codes, dtype=np.uint16)
            x_ref = sx
            y_ref = sy
            shape = (
                len(REFERENCES),
                codes_ref.size,
                sy.size,
                sx.size,
            )
            sums = np.zeros(shape, dtype=np.float32)
            counts = np.zeros(shape, dtype=np.uint8)
        else:
            if not np.array_equal(codes, codes_ref):
                raise RuntimeError(
                    f"HYRAS-{parameter}: abweichende Sommertage im Jahr {year}"
                )
            if (
                sx.shape != x_ref.shape
                or sy.shape != y_ref.shape
                or not np.allclose(sx, x_ref)
                or not np.allclose(sy, y_ref)
            ):
                raise RuntimeError(
                    f"HYRAS-{parameter}: Rasterabweichung im Jahr {year}"
                )

        valid = np.isfinite(values)
        sums[reference_index] += np.where(valid, values, 0.0).astype(np.float32)
        counts[reference_index] += valid.astype(np.uint8)
        used_years.append(int(year))
        print(
            f"Tagesanomalie-Referenz: {parameter} {year} "
            f"→ {REFERENCES[reference_index][0]}",
            flush=True,
        )

    if sums is None or counts is None or codes_ref is None or x_ref is None or y_ref is None:
        raise RuntimeError(
            f"HYRAS-{parameter}: Shard {start_year}-{end_year} enthält keine Referenzjahre"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        parameter=np.asarray(parameter),
        start_year=np.asarray(start_year, dtype=np.int16),
        end_year=np.asarray(end_year, dtype=np.int16),
        years=np.asarray(used_years, dtype=np.int16),
        references=np.asarray([item[0] for item in REFERENCES]),
        date_codes=codes_ref,
        x=x_ref,
        y=y_ref,
        display_factor=np.asarray(display_factor, dtype=np.int16),
        sums=sums,
        counts=counts,
    )
    print(
        f"Referenzbeitrag fertig: {parameter} {start_year}-{end_year} · "
        f"Darstellung ca. {display_factor} km · {output}",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parameter",
        choices=("tmean", "tmax", "tmin"),
        required=True,
    )
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument(
        "--display-factor",
        type=int,
        default=DEFAULT_DISPLAY_FACTOR,
    )
    parser.add_argument(
        "--cache-root",
        default="/tmp/hyras-temperature-rank-history",
    )
    parser.add_argument(
        "--work",
        default="/tmp/hyras-daily-anomaly-reference-work",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.display_factor < 1:
        raise SystemExit("--display-factor muss >= 1 sein")

    build_contribution(
        parameter=args.parameter,
        start_year=args.start_year,
        end_year=args.end_year,
        display_factor=args.display_factor,
        cache_root=Path(args.cache_root),
        work=Path(args.work) / args.parameter,
        output=Path(args.output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
