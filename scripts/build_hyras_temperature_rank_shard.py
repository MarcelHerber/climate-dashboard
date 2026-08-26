#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

try:
    from hyras_temperature_rank import (
        PRODUCTS, date_codes, dequantize_temperature, extract_products, quantize_temperature,
    )
except ModuleNotFoundError:
    from scripts.hyras_temperature_rank import (
        PRODUCTS, date_codes, dequantize_temperature, extract_products, quantize_temperature,
    )

PARAM_MODULES = {
    "tmean": "build_hyras_tmean_regions",
    "tmax": "build_hyras_tmax_regions",
    "tmin": "build_hyras_tmin_regions",
}
DEFAULT_FACTOR = 1


def historical_dates_for_target(year: int, target: date) -> np.ndarray:
    if target.month not in (6, 7, 8):
        raise ValueError("Sommer-Rangkarten sind nur für Juni bis August definiert")
    start = np.datetime64(f"{year:04d}-06-01")
    end = np.datetime64(f"{year:04d}-{target.month:02d}-{target.day:02d}") + np.timedelta64(1, "D")
    return np.arange(start, end, dtype="datetime64[D]")


def _source_module(parameter: str):
    if parameter not in PARAM_MODULES:
        raise ValueError(f"Unbekannter HYRAS-Temperaturparameter: {parameter}")
    return importlib.import_module(PARAM_MODULES[parameter])


def _unpack_prepared(module: Any, ds: xr.Dataset):
    prepared = module.prepare_da(ds)
    if len(prepared) == 6:
        da, td, ydim, xdim, x, y = prepared
    elif len(prepared) == 4:
        da, td, x, y = prepared
        dims = [d for d in da.dims if d != td]
        if len(dims) != 2:
            raise RuntimeError(f"Unerwartete Raumdimensionen: {da.dims}")
        ydim, xdim = dims
    else:
        raise RuntimeError(f"Unerwartete prepare_da-Rückgabe ({len(prepared)} Elemente)")
    return da, td, ydim, xdim, np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def _year_cache_path(cache_root: Path, parameter: str, factor: int, year: int) -> Path:
    return cache_root / parameter / f"factor{factor}" / f"summer_{year}.npz"


def _load_year_cache(path: Path, *, year: int, factor: int):
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            cached_year = int(np.asarray(data["year"]).item())
            cached_factor = int(np.asarray(data["factor"]).item())
            codes = np.asarray(data["date_codes"], dtype=np.uint16)
            values = np.asarray(data["values"], dtype=np.int16)
            x = np.asarray(data["x"], dtype=float)
            y = np.asarray(data["y"], dtype=float)
    except Exception:
        return None
    if cached_year != year or cached_factor != factor or values.ndim != 3:
        return None
    if values.shape[0] != codes.size or values.shape[1:] != (y.size, x.size):
        return None
    if codes.size < 90 or int(codes[0]) != 601 or int(codes[-1]) != 831:
        return None
    return codes, values, x, y


def _save_year_cache(path: Path, *, year: int, factor: int, codes, values, x, y) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        year=np.asarray(year, dtype=np.int16),
        factor=np.asarray(factor, dtype=np.int16),
        date_codes=np.asarray(codes, dtype=np.uint16),
        values=np.asarray(values, dtype=np.int16),
        x=np.asarray(x, dtype=np.float64),
        y=np.asarray(y, dtype=np.float64),
    )


def _build_year_cache(module: Any, parameter: str, year: int, factor: int, cache_root: Path, work: Path):
    path = _year_cache_path(cache_root, parameter, factor, year)
    cached = _load_year_cache(path, year=year, factor=factor)
    if cached is not None:
        print(f"Cache: {parameter} {year}", flush=True)
        return cached

    files = module.latest_daily_files(module.daily_listing())
    filename = files.get(year)
    if not filename:
        raise RuntimeError(f"HYRAS-{parameter}: Tagesdatei für {year} fehlt")
    work.mkdir(parents=True, exist_ok=True)
    nc_path = work / filename
    if not nc_path.exists():
        module.download(f"{module.DAILY_BASE}/{filename}", nc_path)

    with xr.open_dataset(nc_path, decode_times=True) as ds:
        da, td, ydim, xdim, x, y = _unpack_prepared(module, ds)
        times = np.asarray(da[td].values).astype("datetime64[D]")
        codes_all = date_codes(times)
        keep = (codes_all >= 601) & (codes_all <= 831)
        indices = np.flatnonzero(keep)
        if indices.size < 90:
            raise RuntimeError(f"HYRAS-{parameter} {year}: Sommerdaten unvollständig ({indices.size} Tage)")
        sampled = da.isel({td: indices, ydim: slice(None, None, factor), xdim: slice(None, None, factor)})
        arr = np.asarray(sampled.values, dtype=np.float32)
        arr[~np.isfinite(arr)] = np.nan
        sx = x[::factor]
        sy = y[::factor]
        codes = codes_all[keep]

    packed = quantize_temperature(arr)
    _save_year_cache(path, year=year, factor=factor, codes=codes, values=packed, x=sx, y=sy)
    nc_path.unlink(missing_ok=True)
    print(f"Neu gecacht: {parameter} {year} · {arr.shape[1]}×{arr.shape[2]} · {path.stat().st_size/1024/1024:.1f} MB", flush=True)
    return codes, packed, sx, sy


def _times_from_codes(year: int, codes: np.ndarray) -> np.ndarray:
    return np.asarray(
        [f"{year:04d}-{int(code)//100:02d}-{int(code)%100:02d}" for code in codes],
        dtype="datetime64[D]",
    )


def build_shard(*, parameter: str, start_year: int, end_year: int, target: date, factor: int,
                cache_root: Path, work: Path, output: Path) -> None:
    module = _source_module(parameter)
    years = np.arange(start_year, end_year + 1, dtype=int)
    product_fields = {key: [] for key in PRODUCTS}
    x_ref = y_ref = None

    for year in years:
        codes, packed, x, y = _build_year_cache(module, parameter, int(year), factor, cache_root, work)
        if x_ref is None:
            x_ref, y_ref = x, y
        elif x.shape != x_ref.shape or y.shape != y_ref.shape or not np.allclose(x, x_ref) or not np.allclose(y, y_ref):
            raise RuntimeError(f"HYRAS-{parameter}: Rasterabweichung im Jahr {year}")
        values = dequantize_temperature(packed)
        times = _times_from_codes(int(year), codes)
        hist_target = date(int(year), target.month, target.day)
        products = extract_products(times, values, hist_target)
        for key in PRODUCTS:
            product_fields[key].append(np.asarray(products[key], dtype=np.float32))

    assert x_ref is not None and y_ref is not None
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        parameter=np.asarray(parameter),
        target_date=np.asarray(target.isoformat()),
        years=years,
        x=np.asarray(x_ref, dtype=np.float64),
        y=np.asarray(y_ref, dtype=np.float64),
        **{key: np.stack(product_fields[key], axis=0).astype(np.float32) for key in PRODUCTS},
    )
    print(f"Shard fertig: {parameter} {start_year}–{end_year} · {output}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parameter", choices=sorted(PARAM_MODULES), required=True)
    ap.add_argument("--start-year", type=int, required=True)
    ap.add_argument("--end-year", type=int, required=True)
    ap.add_argument("--target-date", required=True)
    ap.add_argument("--factor", type=int, default=DEFAULT_FACTOR)
    ap.add_argument("--cache-root", default="/tmp/hyras-temperature-rank-history")
    ap.add_argument("--work", default="/tmp/hyras-temperature-rank-work")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    if args.factor < 1:
        raise SystemExit("--factor muss >= 1 sein")
    target = date.fromisoformat(args.target_date)
    build_shard(
        parameter=args.parameter,
        start_year=args.start_year,
        end_year=args.end_year,
        target=target,
        factor=args.factor,
        cache_root=Path(args.cache_root),
        work=Path(args.work) / args.parameter,
        output=Path(args.output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
