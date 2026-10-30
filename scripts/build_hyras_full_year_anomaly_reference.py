#!/usr/bin/env python3
"""Calendar-year HYRAS daily climatology from 1961–1990 and 1991–2020."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

try:
    from build_hyras_temperature_rank_shard import _source_module, _unpack_prepared
except ModuleNotFoundError:
    from scripts.build_hyras_temperature_rank_shard import _source_module, _unpack_prepared

REFERENCES = (("1961-1990", 1961, 1990), ("1991-2020", 1991, 2020))


def calendar_codes() -> np.ndarray:
    """366 calendar codes, including 29 February, in a fixed leap-year axis."""
    start = date(2000, 1, 1)
    return np.asarray(
        [(start + timedelta(days=offset)).month * 100
         + (start + timedelta(days=offset)).day for offset in range(366)],
        dtype=np.uint16,
    )


def reference_index(year: int) -> int:
    for index, (_, beginning, end) in enumerate(REFERENCES):
        if beginning <= year <= end:
            return index
    raise ValueError(f"Year outside climatology: {year}")


def day_codes(times: np.ndarray) -> np.ndarray:
    values = np.asarray(times).astype("datetime64[D]").astype(str)
    return np.asarray([int(v[5:7]) * 100 + int(v[8:10]) for v in values], dtype=np.uint16)


def build_contribution(*, parameter: str, start_year: int, end_year: int,
                       display_factor: int, cache_root: Path, work: Path,
                       output: Path) -> None:
    if display_factor < 1:
        raise ValueError("display_factor must be positive")
    module = _source_module(parameter)
    all_files = module.latest_daily_files(module.daily_listing())
    codes = calendar_codes()
    lookup = {int(code): i for i, code in enumerate(codes)}
    ref_x = ref_y = sums = counts = None
    used_years = []

    for year in range(start_year, end_year + 1):
        which = reference_index(year)
        filename = all_files.get(year)
        if not filename:
            raise RuntimeError(f"HYRAS {parameter} {year}: annual NetCDF not available")
        work.mkdir(parents=True, exist_ok=True)
        nc_file = work / filename
        if not nc_file.exists():
            module.download(f"{module.DAILY_BASE}/{filename}", nc_file)
        try:
            with xr.open_dataset(nc_file, decode_times=True) as dataset:
                da, td, ydim, xdim, x, y = _unpack_prepared(module, dataset)
                times = np.asarray(da[td].values).astype("datetime64[D]")
                first = np.datetime64(f"{year}-01-01")
                last = np.datetime64(f"{year + 1}-01-01")
                indices = np.flatnonzero((times >= first) & (times < last))
                expected = np.arange(first, last, dtype="datetime64[D]")
                if not np.array_equal(times[indices], expected):
                    raise RuntimeError(f"HYRAS {parameter} {year}: missing or duplicate daily data")
                small = da.isel({
                    td: indices,
                    ydim: slice(None, None, display_factor),
                    xdim: slice(None, None, display_factor),
                })
                values = np.asarray(small.values, dtype=np.float32)
                values[~np.isfinite(values)] = np.nan
                sx = np.asarray(x[::display_factor], dtype=np.float64)
                sy = np.asarray(y[::display_factor], dtype=np.float64)
                dates = day_codes(times[indices])
                if sums is None:
                    ref_x, ref_y = sx, sy
                    shape = (2, len(codes), len(sy), len(sx))
                    sums = np.zeros(shape, dtype=np.float64)
                    counts = np.zeros(shape, dtype=np.uint8)
                elif (sx.shape != ref_x.shape or sy.shape != ref_y.shape
                      or not np.allclose(sx, ref_x) or not np.allclose(sy, ref_y)):
                    raise RuntimeError(f"HYRAS {parameter} {year}: grid changed")
                for i, code in enumerate(dates):
                    pos = lookup[int(code)]
                    layer = values[i]
                    valid = np.isfinite(layer)
                    sums[which, pos] += np.where(valid, layer, 0.0)
                    counts[which, pos] += valid.astype(np.uint8)
            used_years.append(year)
        finally:
            # Source files are large. The compact shard is cached separately.
            nc_file.unlink(missing_ok=True)
        print(f"{parameter}: calendar climatology {year} done", flush=True)

    if sums is None or counts is None or ref_x is None or ref_y is None:
        raise RuntimeError("Empty daily reference shard")
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        parameter=np.asarray(parameter),
        years=np.asarray(used_years, dtype=np.int16),
        references=np.asarray([item[0] for item in REFERENCES]),
        date_codes=codes,
        x=ref_x,
        y=ref_y,
        display_factor=np.asarray(display_factor, dtype=np.int16),
        sums=sums.astype(np.float32),
        counts=counts,
        calendar_version=np.asarray(2, dtype=np.int16),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parameter", required=True, choices=("tmean", "tmax", "tmin"))
    parser.add_argument("--start-year", required=True, type=int)
    parser.add_argument("--end-year", required=True, type=int)
    parser.add_argument("--display-factor", type=int, default=5)
    parser.add_argument("--cache-root", type=Path, default=Path("/tmp/hyras-full-year-cache"))
    parser.add_argument("--work", type=Path, default=Path("/tmp/hyras-full-year-work"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_contribution(
        parameter=args.parameter, start_year=args.start_year,
        end_year=args.end_year, display_factor=args.display_factor,
        cache_root=args.cache_root, work=args.work / args.parameter,
        output=args.output,
    )


if __name__ == "__main__":
    main()
