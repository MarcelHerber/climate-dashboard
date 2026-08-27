#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

try:
    from build_hyras_temperature_rank_shard import _source_module, _unpack_prepared
    from hyras_temperature_rank import PRODUCTS
except ModuleNotFoundError:
    from scripts.build_hyras_temperature_rank_shard import _source_module, _unpack_prepared
    from scripts.hyras_temperature_rank import PRODUCTS


def target_dates_until(target: date) -> list[date]:
    if target.year != 2026 or target.month not in (6, 7, 8):
        raise ValueError("Der Sommer-Backfill ist nur für Juni bis August 2026 definiert")
    out: list[date] = []
    cursor = date(2026, 6, 1)
    while cursor <= target:
        out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _means_stack(times: np.ndarray, cube: np.ndarray, targets: list[date]) -> dict[str, np.ndarray]:
    times = np.asarray(times).astype("datetime64[D]")
    cube = np.asarray(cube, dtype=np.float32)
    if cube.ndim != 3 or cube.shape[0] != times.size:
        raise ValueError("Tagesdaten müssen Zeit x Y x X sein")

    ny, nx = cube.shape[1:]
    n = len(targets)
    output = {
        product: np.full((n, ny, nx), np.nan, dtype=np.float32)
        for product in PRODUCTS
    }
    target_index = {item.isoformat(): idx for idx, item in enumerate(targets)}

    summer_sum = np.zeros((ny, nx), dtype=np.float64)
    summer_count = np.zeros((ny, nx), dtype=np.uint16)
    month_sum = np.zeros((ny, nx), dtype=np.float64)
    month_count = np.zeros((ny, nx), dtype=np.uint16)
    active_month = None

    for i, t64 in enumerate(times):
        text = str(t64)
        if text < targets[0].isoformat() or text > targets[-1].isoformat():
            continue
        month = int(text[5:7])
        if month != active_month:
            month_sum.fill(0.0)
            month_count.fill(0)
            active_month = month

        arr = np.asarray(cube[i], dtype=np.float64)
        valid = np.isfinite(arr)
        safe = np.where(valid, arr, 0.0)
        summer_sum += safe
        summer_count += valid
        month_sum += safe
        month_count += valid

        idx = target_index.get(text)
        if idx is None:
            continue

        day = arr.astype(np.float32)
        month_mean = np.full((ny, nx), np.nan, dtype=np.float64)
        summer_mean = np.full((ny, nx), np.nan, dtype=np.float64)
        np.divide(month_sum, month_count, out=month_mean, where=month_count > 0)
        np.divide(summer_sum, summer_count, out=summer_mean, where=summer_count > 0)

        output["day"][idx] = day
        output["month_to_date"][idx] = month_mean.astype(np.float32)
        output["summer_to_date"][idx] = summer_mean.astype(np.float32)

    return output


def build_current(*, parameter: str, target: date, factor: int, work: Path, output: Path) -> None:
    module = _source_module(parameter)
    files = module.latest_daily_files(module.daily_listing())
    filename = files.get(target.year)
    if not filename:
        raise RuntimeError(f"HYRAS-{parameter}: Tagesdatei für {target.year} fehlt")

    work.mkdir(parents=True, exist_ok=True)
    nc_path = work / filename
    if not nc_path.exists():
        module.download(f"{module.DAILY_BASE}/{filename}", nc_path)

    targets = target_dates_until(target)
    with xr.open_dataset(nc_path, decode_times=True) as ds:
        da, td, ydim, xdim, x, y = _unpack_prepared(module, ds)
        times = np.asarray(da[td].values).astype("datetime64[D]")
        start = np.datetime64(targets[0].isoformat())
        stop = np.datetime64(target.isoformat())
        keep = np.flatnonzero((times >= start) & (times <= stop))
        if keep.size != len(targets):
            raise RuntimeError(
                f"HYRAS-{parameter}: erwartet {len(targets)} Sommertage, gefunden {keep.size}"
            )
        sampled = da.isel({
            td: keep,
            ydim: slice(None, None, factor),
            xdim: slice(None, None, factor),
        })
        cube = np.asarray(sampled.values, dtype=np.float32)
        cube[~np.isfinite(cube)] = np.nan
        sx = np.asarray(x[::factor], dtype=np.float64)
        sy = np.asarray(y[::factor], dtype=np.float64)
        products = _means_stack(times[keep], cube, targets)

    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        parameter=np.asarray(parameter),
        target_date=np.asarray(target.isoformat()),
        target_dates=np.asarray([item.isoformat() for item in targets]),
        x=sx,
        y=sy,
        **products,
    )
    print(
        f"Aktueller HYRAS-Backfill-Stack: {parameter} · "
        f"{targets[0].isoformat()}–{targets[-1].isoformat()} · "
        f"{sx.size}×{sy.size} · {output}",
        flush=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parameter", choices=("tmean", "tmax", "tmin"), required=True)
    ap.add_argument("--target-date", required=True)
    ap.add_argument("--factor", type=int, default=1)
    ap.add_argument("--work", default="/tmp/hyras-rank-backfill-current-work")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    build_current(
        parameter=args.parameter,
        target=date.fromisoformat(args.target_date),
        factor=args.factor,
        work=Path(args.work) / args.parameter,
        output=Path(args.output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
