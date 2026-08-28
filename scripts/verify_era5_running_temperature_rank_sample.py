#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import xarray as xr

TEMP_ALIASES = ("t2m", "2m_temperature", "temperature_2m")
LAT_ALIASES = ("latitude", "lat")
LON_ALIASES = ("longitude", "lon")
TIME_ALIASES = ("valid_time", "time", "date")


def find_name(names, aliases: tuple[str, ...]) -> str:
    names = [str(name) for name in names]
    lower = {name.lower(): name for name in names}
    for alias in aliases:
        if alias.lower() in lower:
            return lower[alias.lower()]
    for name in names:
        lname = name.lower()
        if any(alias.lower() in lname for alias in aliases):
            return name
    raise KeyError(f"Kein Alias {aliases} in {names}")


def open_download(path: Path) -> xr.Dataset:
    if not path.exists():
        raise FileNotFoundError(path)
    if not zipfile.is_zipfile(path):
        return xr.open_dataset(path)
    tmp = Path(tempfile.mkdtemp(prefix="verify-era5-rank-"))
    with zipfile.ZipFile(path) as archive:
        archive.extractall(tmp)
    nc_files = sorted(tmp.rglob("*.nc"))
    if not nc_files:
        raise RuntimeError(f"ZIP enthält kein NetCDF: {path}")
    datasets = [xr.open_dataset(item) for item in nc_files]
    if len(datasets) == 1:
        return datasets[0]
    return xr.merge(datasets, compat="override")


def temperature_cube(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    ds = open_download(path)
    try:
        temp_name = find_name(ds.data_vars, TEMP_ALIASES)
        lat_name = find_name(ds.coords, LAT_ALIASES)
        lon_name = find_name(ds.coords, LON_ALIASES)
        da = ds[temp_name]

        tdim = None
        for alias in TIME_ALIASES:
            if alias in da.dims:
                tdim = alias
                break
        if tdim is None:
            for dim in da.dims:
                if dim in {lat_name, lon_name}:
                    continue
                coord = da.coords.get(dim)
                if coord is not None and np.issubdtype(coord.dtype, np.datetime64):
                    tdim = dim
                    break
        if tdim is None:
            raise RuntimeError(f"Keine Zeitdimension in {path.name}: {da.dims}")

        for dim in list(da.dims):
            if dim not in {tdim, lat_name, lon_name}:
                if da.sizes.get(dim) != 1:
                    raise RuntimeError(f"Unerwartete Dimension {dim}={da.sizes.get(dim)}")
                da = da.isel({dim: 0}, drop=True)
        da = da.transpose(tdim, lat_name, lon_name)
        values = np.asarray(da.values, dtype=np.float64)
        finite = values[np.isfinite(values)]
        if finite.size and float(np.nanmedian(finite)) > 100.0:
            values -= 273.15
        times = np.asarray(da[tdim].values).astype("datetime64[ns]")
        lat = np.asarray(da[lat_name].values, dtype=np.float64)
        lon = np.asarray(da[lon_name].values, dtype=np.float64)
        return lat, lon, times, values
    finally:
        ds.close()


def compare_field(name: str, raw: np.ndarray, stored: np.ndarray, tolerance: float = 1e-4) -> dict:
    raw = np.asarray(raw, dtype=np.float64)
    stored = np.asarray(stored, dtype=np.float64)
    if raw.shape != stored.shape:
        raise AssertionError(f"{name}: Form {raw.shape} != {stored.shape}")
    raw_finite = np.isfinite(raw)
    stored_finite = np.isfinite(stored)
    if not np.array_equal(raw_finite, stored_finite):
        mismatch = int(np.count_nonzero(raw_finite != stored_finite))
        raise AssertionError(f"{name}: {mismatch} Rasterpunkte mit abweichender NaN-Maske")
    diff = np.abs(raw[raw_finite] - stored[stored_finite])
    max_error = float(diff.max()) if diff.size else 0.0
    mean_error = float(diff.mean()) if diff.size else 0.0
    if max_error > tolerance:
        raise AssertionError(f"{name}: max. Abweichung {max_error:.8f} °C > {tolerance}")
    return {
        "finite_gridpoints": int(raw_finite.sum()),
        "max_abs_error_c": max_error,
        "mean_abs_error_c": mean_error,
        "min_c": float(np.nanmin(raw)),
        "max_c": float(np.nanmax(raw)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Unabhängige ERA5-Rangshard-Stichprobe aus Roh-NetCDFs.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--artifact-dir", type=Path, default=Path(".verify_rank_artifact"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".era5_running_rank_cache"))
    args = parser.parse_args()

    npz_files = sorted(args.artifact_dir.glob("*.npz"))
    if len(npz_files) != 1:
        raise RuntimeError(f"Genau ein NPZ erwartet, gefunden: {[p.name for p in npz_files]}")
    with np.load(npz_files[0], allow_pickle=False) as stored:
        target = str(np.asarray(stored["target_date"]).item())
        years = np.asarray(stored["years"], dtype=int)
        if not np.array_equal(years, np.asarray([args.year])):
            raise AssertionError(f"Falsches Jahr im Shard: {years.tolist()}")
        stored_lat = np.asarray(stored["lat"], dtype=np.float64)
        stored_lon = np.asarray(stored["lon"], dtype=np.float64)
        stored_fields = {
            key: np.asarray(stored[key][0], dtype=np.float64)
            for key in ("day", "month_to_date", "summer_to_date")
        }

    target_date = np.datetime64(target, "D")
    target_text = str(target_date)
    target_year, target_month, target_day = map(int, target_text.split("-"))
    if target_year != 2026 or target_month != 8:
        raise AssertionError(f"Prüfskript erwartet August 2026, erhalten {target}")

    daily_path = args.cache_dir / f"rank_daily_{args.year}_08_full.nc"
    monthly_path = args.cache_dir / f"rank_monthly_{args.year}_{args.year}_06_07.nc"
    dlat, dlon, dtimes, daily = temperature_cube(daily_path)
    mlat, mlon, mtimes, monthly = temperature_cube(monthly_path)

    if np.max(np.abs(dlat - stored_lat)) > 1e-4 or np.max(np.abs(dlon - stored_lon)) > 1e-4:
        raise AssertionError("Tagesraster stimmt nicht mit dem Shard überein")
    if np.max(np.abs(mlat - stored_lat)) > 1e-4 or np.max(np.abs(mlon - stored_lon)) > 1e-4:
        raise AssertionError("Monatsraster stimmt nicht mit dem Shard überein")

    dates = dtimes.astype("datetime64[D]")
    date_strings = dates.astype(str)
    daily_years = np.asarray([int(s[:4]) for s in date_strings])
    daily_months = np.asarray([int(s[5:7]) for s in date_strings])
    daily_days = np.asarray([int(s[8:10]) for s in date_strings])
    source_mask = (daily_years == args.year) & (daily_months == 8)
    present_days = sorted(set(daily_days[source_mask].tolist()))
    if present_days != list(range(1, 32)):
        raise AssertionError(f"August-Tagescache unvollständig: {present_days}")
    if np.count_nonzero(source_mask & (daily_days == target_day)) != 1:
        raise AssertionError(f"Zieltag {target_day} nicht genau einmal vorhanden")

    raw_day = daily[source_mask & (daily_days == target_day)][0]
    raw_mtd = np.nanmean(daily[source_mask & (daily_days <= target_day)], axis=0)

    month_strings = mtimes.astype("datetime64[M]").astype(str)
    month_keys = [(int(s[:4]), int(s[5:7])) for s in month_strings]
    if month_keys.count((args.year, 6)) != 1 or month_keys.count((args.year, 7)) != 1:
        raise AssertionError(f"Juni/Juli nicht eindeutig in Monatscache: {month_keys}")
    june = monthly[month_keys.index((args.year, 6))]
    july = monthly[month_keys.index((args.year, 7))]
    raw_summer = (june * 30.0 + july * 31.0 + raw_mtd * float(target_day)) / float(61 + target_day)

    checks = {
        "day": compare_field("day", raw_day, stored_fields["day"]),
        "month_to_date": compare_field("month_to_date", raw_mtd, stored_fields["month_to_date"]),
        "summer_to_date": compare_field("summer_to_date", raw_summer, stored_fields["summer_to_date"]),
    }
    finite_counts = {value["finite_gridpoints"] for value in checks.values()}
    if len(finite_counts) != 1 or next(iter(finite_counts)) < 100_000:
        raise AssertionError(f"Unplausible Zahl gültiger Rasterpunkte: {finite_counts}")

    result = {
        "year": args.year,
        "target_date": target,
        "daily_source_days": len(present_days),
        "grid": [int(stored_lat.size), int(stored_lon.size)],
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"OK: {args.year} · Roh-NetCDFs stimmen mit allen drei Shard-Produkten überein.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
