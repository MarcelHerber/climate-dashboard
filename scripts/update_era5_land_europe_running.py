#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
import time
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import cdsapi
import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "update_era5_land_europe.py"
OUT_DIR = ROOT / "era5_land_europe" / "running"
MAP_DIR = OUT_DIR / "maps"
INDEX_PATH = OUT_DIR / "index.json"
CACHE_DIR = ROOT / ".era5_running_cache"

DAILY_DATASET = "derived-era5-land-daily-statistics"
HOURLY_DATASET = "reanalysis-era5-land"
MONTHLY_DATASET = "reanalysis-era5-land-monthly-means"
REFERENCE_START = 1991
REFERENCE_END = 2020
AREA = [72.0, -25.0, 34.0, 45.0]
GRID = [0.5, 0.5]
PAYLOAD_VERSION = 1
MAX_LOOKBACK_DAYS = 14
REFERENCE_CHUNK_YEARS = 1

MONTH_NAMES = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}
TEMP_ALIASES = ("t2m", "2m_temperature", "temperature_2m")
PRECIP_ALIASES = ("tp", "total_precipitation", "precipitation")
LAT_ALIASES = ("latitude", "lat")
LON_ALIASES = ("longitude", "lon")
TIME_ALIASES = ("valid_time", "time", "date")


def load_core():
    spec = importlib.util.spec_from_file_location("era5_running_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"ERA5-Hauptskript konnte nicht importiert werden: {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def cds_client() -> cdsapi.Client:
    return cdsapi.Client(quiet=False, progress=False)


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, allow_nan=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def retrieve(client: cdsapi.Client, dataset: str, request: dict, target: Path, label: str, attempts: int = 3) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    delays = (10, 30, 60)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            if target.exists():
                target.unlink()
            print(f"CDS: {label} · Versuch {attempt}/{attempts}")
            client.retrieve(dataset, request, str(target))
            return
        except Exception as exc:
            last = exc
            print(f"CDS-Fehler bei {label}: {exc}")
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            if attempt < attempts:
                time.sleep(delays[min(attempt - 1, len(delays) - 1)])
    assert last is not None
    raise last


def open_download(path: Path) -> xr.Dataset:
    if zipfile.is_zipfile(path):
        extract_dir = path.with_suffix(path.suffix + ".files")
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(extract_dir)
        nc_files = sorted(extract_dir.rglob("*.nc"))
        if not nc_files:
            raise RuntimeError(f"CDS-Archiv enthält keine NetCDF-Datei: {path}")
        datasets = [xr.open_dataset(item) for item in nc_files]
        return xr.merge(datasets, compat="override") if len(datasets) > 1 else datasets[0]
    return xr.open_dataset(path)


def find_name(names, aliases: tuple[str, ...]) -> str:
    names = list(names)
    lower = {str(name).lower(): str(name) for name in names}
    for alias in aliases:
        if alias.lower() in lower:
            return lower[alias.lower()]
    for name in names:
        lname = str(name).lower()
        for alias in aliases:
            if alias.lower() in lname:
                return str(name)
    raise KeyError(f"Keine passende Variable gefunden. Vorhanden: {names}")


def coordinates(ds: xr.Dataset) -> tuple[np.ndarray, np.ndarray]:
    lat_name = find_name(ds.coords, LAT_ALIASES)
    lon_name = find_name(ds.coords, LON_ALIASES)
    return np.asarray(ds[lat_name].values, dtype=float), np.asarray(ds[lon_name].values, dtype=float)


def time_name(ds: xr.Dataset, da: xr.DataArray) -> str | None:
    for alias in TIME_ALIASES:
        if alias in da.dims or alias in da.coords:
            return alias
        if alias in ds.coords:
            return alias
    lat_name = find_name(ds.coords, LAT_ALIASES)
    lon_name = find_name(ds.coords, LON_ALIASES)
    for dim in da.dims:
        if dim not in {lat_name, lon_name}:
            coord = ds.coords.get(dim)
            if coord is not None and np.issubdtype(coord.dtype, np.datetime64):
                return dim
    return None


def normalize_cube(ds: xr.Dataset, aliases: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    var_name = find_name(ds.data_vars, aliases)
    da = ds[var_name]
    lat_name = find_name(ds.coords, LAT_ALIASES)
    lon_name = find_name(ds.coords, LON_ALIASES)
    tname = time_name(ds, da)

    keep = {lat_name, lon_name}
    if tname:
        keep.add(tname)
    for dim in list(da.dims):
        if dim not in keep:
            if da.sizes.get(dim, 0) == 1:
                da = da.isel({dim: 0}, drop=True)
            else:
                raise RuntimeError(f"Unerwartete Dimension {dim}={da.sizes.get(dim)} in {var_name}")

    order = ([tname] if tname and tname in da.dims else []) + [lat_name, lon_name]
    da = da.transpose(*order)
    values = np.asarray(da.values, dtype=float)
    if values.ndim == 2:
        values = values[None, ...]
    lat = np.asarray(ds[lat_name].values, dtype=float)
    lon = np.asarray(ds[lon_name].values, dtype=float)
    if tname and tname in ds.coords:
        times = np.asarray(ds[tname].values).astype("datetime64[ns]")
    elif tname and tname in da.coords:
        times = np.asarray(da[tname].values).astype("datetime64[ns]")
    else:
        times = np.arange(values.shape[0])
    return lat, lon, times, values


def kelvin_to_celsius(values: np.ndarray) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if finite.size and float(np.nanmedian(finite)) > 100.0:
        return values - 273.15
    return values


def metres_to_mm(values: np.ndarray) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if not finite.size:
        return values
    if float(np.nanpercentile(np.abs(finite), 99)) < 20.0:
        return values * 1000.0
    return values


def finite_sum(cube: np.ndarray, divisor: float = 1.0) -> np.ndarray:
    valid = np.isfinite(cube)
    summed = np.nansum(cube, axis=0) / divisor
    summed[np.sum(valid, axis=0) == 0] = np.nan
    return summed


def finite_mean(cube: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.nanmean(cube, axis=0)


def request_daily_temperature(client: cdsapi.Client, years: list[int], month: int, days: list[int], target: Path, label: str, *, area=AREA) -> None:
    request = {
        "variable": ["2m_temperature"],
        "year": [f"{year:04d}" for year in years],
        "month": f"{month:02d}",
        "day": [f"{day:02d}" for day in days],
        "daily_statistic": "daily_mean",
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": area,
        "grid": GRID,
    }
    retrieve(client, DAILY_DATASET, request, target, label)


def chunk_years(years: list[int], size: int = REFERENCE_CHUNK_YEARS) -> list[list[int]]:
    return [years[i:i + size] for i in range(0, len(years), size)]


def request_daily_temperature_period(client: cdsapi.Client, years: list[int], month: int, days: list[int], prefix: Path, label: str, *, area=AREA) -> list[Path]:
    files: list[Path] = []
    for years_part in chunk_years(years):
        path = prefix.with_name(f"{prefix.stem}_{years_part[0]}_{years_part[-1]}{prefix.suffix}")
        if not path.exists():
            request_daily_temperature(
                client, years_part, month, days, path,
                f"{label} · {years_part[0]}–{years_part[-1]}", area=area,
            )
        files.append(path)
    return files


def request_precip_group(client: cdsapi.Client, years: list[int], month: int, days: list[int], target: Path, label: str, *, area=AREA) -> None:
    request = {
        "variable": ["total_precipitation"],
        "year": [f"{year:04d}" for year in years],
        "month": f"{month:02d}",
        "day": [f"{day:02d}" for day in days],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": area,
        "grid": GRID,
    }
    retrieve(client, HOURLY_DATASET, request, target, label)


def precip_source_groups(years: list[int], month: int, end_day: int) -> list[tuple[list[int], int, list[int]]]:
    by_year_month: dict[tuple[int, int], set[int]] = defaultdict(set)
    for year in years:
        for day in range(1, end_day + 1):
            source = date(year, month, day) + timedelta(days=1)
            by_year_month[(source.year, source.month)].add(source.day)
    signature: dict[tuple[int, tuple[int, ...]], list[int]] = defaultdict(list)
    for (year, src_month), days in sorted(by_year_month.items()):
        signature[(src_month, tuple(sorted(days)))].append(year)
    return [(src_years, src_month, list(days)) for (src_month, days), src_years in signature.items()]


def request_precip_period(client: cdsapi.Client, years: list[int], month: int, end_day: int, prefix: Path, label: str, *, area=AREA) -> list[Path]:
    files: list[Path] = []
    for idx, (src_years, src_month, src_days) in enumerate(precip_source_groups(years, month, end_day), 1):
        for years_part in chunk_years(src_years):
            path = prefix.with_name(
                f"{prefix.stem}_{idx:02d}_{years_part[0]}_{years_part[-1]}{prefix.suffix}"
            )
            if not path.exists():
                request_precip_group(
                    client, years_part, src_month, src_days, path,
                    f"{label} · Quellmonat {src_month:02d} · {years_part[0]}–{years_part[-1]}", area=area,
                )
            files.append(path)
    return files


def read_temperature(paths: Path | list[Path], max_day: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    path_list = [paths] if isinstance(paths, Path) else list(paths)
    cubes: list[np.ndarray] = []
    out_lat: np.ndarray | None = None
    out_lon: np.ndarray | None = None
    for path in path_list:
        ds = open_download(path)
        try:
            lat, lon, times, cube = normalize_cube(ds, TEMP_ALIASES)
            cube = kelvin_to_celsius(cube)
            if max_day is not None and np.issubdtype(times.dtype, np.datetime64):
                day_values = np.array([int(str(t.astype("datetime64[D]"))[-2:]) for t in times])
                cube = cube[day_values <= max_day]
            if out_lat is None:
                out_lat, out_lon = lat, lon
            elif not (np.allclose(out_lat, lat) and np.allclose(out_lon, lon)):
                raise RuntimeError("Temperaturdateien besitzen unterschiedliche Raster.")
            cubes.append(cube)
        finally:
            ds.close()
    if out_lat is None or out_lon is None or not cubes:
        raise RuntimeError("Keine Temperaturdaten gelesen.")
    return out_lat, out_lon, finite_mean(np.concatenate(cubes, axis=0))


def read_precip(paths: list[Path], target_month: int, max_day: int, reference_years: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cubes: list[np.ndarray] = []
    out_lat: np.ndarray | None = None
    out_lon: np.ndarray | None = None
    for path in paths:
        ds = open_download(path)
        try:
            lat, lon, times, cube = normalize_cube(ds, PRECIP_ALIASES)
            cube = metres_to_mm(cube)
            if np.issubdtype(times.dtype, np.datetime64):
                target_dates = times.astype("datetime64[D]") - np.timedelta64(1, "D")
                keep = []
                for i, stamp in enumerate(target_dates):
                    text = str(stamp)
                    mm = int(text[5:7])
                    dd = int(text[8:10])
                    if mm == target_month and dd <= max_day:
                        keep.append(i)
                cube = cube[keep]
            if out_lat is None:
                out_lat, out_lon = lat, lon
            elif not (np.allclose(out_lat, lat) and np.allclose(out_lon, lon)):
                raise RuntimeError("Niederschlagsdateien besitzen unterschiedliche Raster.")
            cubes.append(cube)
        finally:
            ds.close()
    if out_lat is None or out_lon is None or not cubes:
        raise RuntimeError("Keine Niederschlagsdaten gelesen.")
    all_cube = np.concatenate(cubes, axis=0)
    divisor = float(reference_years) if reference_years else 1.0
    return out_lat, out_lon, finite_sum(all_cube, divisor=divisor)


def request_monthly_tp(client: cdsapi.Client, years: list[int], months: list[int], target: Path, label: str) -> None:
    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": ["2m_temperature", "total_precipitation"],
        "year": [f"{year:04d}" for year in years],
        "month": [f"{month:02d}" for month in months],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA,
        "grid": GRID,
    }
    retrieve(client, MONTHLY_DATASET, request, target, label)


def read_monthly_fields(path: Path) -> tuple[np.ndarray, np.ndarray, dict[tuple[int, int], tuple[np.ndarray, np.ndarray]]]:
    ds = open_download(path)
    try:
        lat_t, lon_t, times_t, temp_cube = normalize_cube(ds, TEMP_ALIASES)
        lat_p, lon_p, times_p, precip_cube = normalize_cube(ds, PRECIP_ALIASES)
        if not (np.allclose(lat_t, lat_p) and np.allclose(lon_t, lon_p)):
            raise RuntimeError("Monatliche T/P-Raster stimmen nicht überein.")
        temp_cube = kelvin_to_celsius(temp_cube)
        precip_cube = metres_to_mm(precip_cube)
        fields: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        if not np.issubdtype(times_t.dtype, np.datetime64) or not np.issubdtype(times_p.dtype, np.datetime64):
            raise RuntimeError("Monatliche ERA5-Datei enthält keine Datumsachse.")
        p_index = {str(t.astype("datetime64[M]")): i for i, t in enumerate(times_p)}
        for i, stamp in enumerate(times_t):
            key_text = str(stamp.astype("datetime64[M]"))
            year, month = map(int, key_text.split("-"))
            j = p_index.get(key_text)
            if j is None:
                continue
            days = calendar.monthrange(year, month)[1]
            precip_sum = precip_cube[j] * days
            fields[(year, month)] = (temp_cube[i], precip_sum)
        return lat_t, lon_t, fields
    finally:
        ds.close()


def climatology_monthly(fields: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]], month: int) -> tuple[np.ndarray, np.ndarray]:
    temp = [value[0] for (year, mm), value in fields.items() if mm == month and REFERENCE_START <= year <= REFERENCE_END]
    precip = [value[1] for (year, mm), value in fields.items() if mm == month and REFERENCE_START <= year <= REFERENCE_END]
    if not temp or not precip:
        raise RuntimeError(f"Monatsklimatologie {month:02d} fehlt.")
    return finite_mean(np.stack(temp)), finite_mean(np.stack(precip))


def weighted_mean(core, field: np.ndarray, lat: np.ndarray) -> float | None:
    value = core.weighted_mean(np.asarray(field, dtype=float), np.asarray(lat, dtype=float))
    return float(value) if value is not None and math.isfinite(float(value)) else None


def map_record(path: Path, unit: str, label: str) -> dict:
    return {"file": path.relative_to(ROOT).as_posix(), "unit": unit, "label": label}


def render_period(core, period_id: str, label: str, start: date, end: date,
                  lat: np.ndarray, lon: np.ndarray,
                  temp: np.ndarray, temp_ref: np.ndarray,
                  precip: np.ndarray, precip_ref: np.ndarray) -> dict:
    MAP_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "ta": MAP_DIR / f"temperature_{period_id}_absolute.png",
        "td": MAP_DIR / f"temperature_{period_id}_anomaly.png",
        "pa": MAP_DIR / f"precipitation_{period_id}_absolute.png",
        "pp": MAP_DIR / f"precipitation_{period_id}_percent.png",
    }
    temp_anom = temp - temp_ref
    with np.errstate(invalid="ignore", divide="ignore"):
        precip_pct = np.where(precip_ref > 1.0, precip / precip_ref * 100.0, np.nan)

    subtitle_dates = f"{start.strftime('%d.%m.')}–{end.strftime('%d.%m.%Y')} · bis aktuell verfügbarer ERA5-Land-T-Tag"
    core.render_map(temp, lat, lon, title=f"ERA5-Land Europa · 2-m-Temperatur · {label}", subtitle=subtitle_dates, unit="°C", filename=paths["ta"], kind="temp_absolute")
    core.render_map(temp_anom, lat, lon, title=f"ERA5-Land Europa · Temperaturabweichung · {label}", subtitle=f"gegenüber denselben Kalendertagen 1991–2020 · {subtitle_dates}", unit="K", filename=paths["td"], kind="temp_anomaly")
    core.render_map(precip, lat, lon, title=f"ERA5-Land Europa · Niederschlag · {label}", subtitle=subtitle_dates, unit="mm", filename=paths["pa"], kind="precip_absolute")
    core.render_map(precip_pct, lat, lon, title=f"ERA5-Land Europa · Niederschlag · {label}", subtitle=f"Prozent vom Mittel derselben Kalendertage 1991–2020 · {subtitle_dates}", unit="% vom Mittel", filename=paths["pp"], kind="precip_percent")

    tcur = weighted_mean(core, temp, lat)
    tref = weighted_mean(core, temp_ref, lat)
    pcur = weighted_mean(core, precip, lat)
    pref = weighted_mean(core, precip_ref, lat)
    return {
        "id": period_id,
        "label": label,
        "date_start": start.isoformat(),
        "date_end": end.isoformat(),
        "year": end.year,
        "partial_daily": True,
        "temperature": {
            "absolute": map_record(paths["ta"], "°C", "Temperatur"),
            "anomaly": map_record(paths["td"], "K", "Abweichung 1991–2020"),
            "stats": {"current": tcur, "reference": tref, "difference": None if tcur is None or tref is None else tcur - tref},
        },
        "precipitation": {
            "absolute": map_record(paths["pa"], "mm", "Niederschlag"),
            "percent": map_record(paths["pp"], "%", "Prozent vom Mittel 1991–2020"),
            "stats": {"current": pcur, "reference": pref, "percent": None if pcur is None or pref in (None, 0) else pcur / pref * 100.0},
        },
    }


def probe_available_day(client: cdsapi.Client, today: date, force: bool = False) -> date:
    probe_dir = CACHE_DIR / "probe"
    probe_area = [50.0, 10.0, 49.5, 10.5]
    start = today - timedelta(days=6)
    for offset in range(MAX_LOOKBACK_DAYS - 5):
        candidate = start - timedelta(days=offset)
        temp_file = probe_dir / f"temp_{candidate.isoformat()}.nc"
        precip_file = probe_dir / f"precip_{candidate.isoformat()}.nc"
        source = candidate + timedelta(days=1)
        try:
            if force or not temp_file.exists():
                request_daily_temperature(client, [candidate.year], candidate.month, [candidate.day], temp_file, f"Verfügbarkeitsprobe Temperatur {candidate}", area=probe_area)
            if force or not precip_file.exists():
                request_precip_group(client, [source.year], source.month, [source.day], precip_file, f"Verfügbarkeitsprobe Niederschlag {candidate}", area=probe_area)
            lat, lon, t = read_temperature(temp_file)
            plat, plon, p = read_precip([precip_file], candidate.month, candidate.day)
            if np.isfinite(t).any() and np.isfinite(p).any() and np.allclose(lat, plat) and np.allclose(lon, plon):
                return candidate
        except Exception as exc:
            print(f"{candidate}: noch nicht vollständig verfügbar ({exc})")
    raise RuntimeError(f"Kein gemeinsamer ERA5-Land-T-Datenstand innerhalb der letzten {MAX_LOOKBACK_DAYS} Tage gefunden.")


def combine_summer(current_year: int, current_month: int, end_day: int,
                   daily_temp: np.ndarray, daily_temp_ref: np.ndarray,
                   daily_precip: np.ndarray, daily_precip_ref: np.ndarray,
                   current_monthly: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]],
                   ref_monthly: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[int]]:
    completed = [m for m in (6, 7, 8) if m < current_month]
    if current_month not in (6, 7, 8):
        raise RuntimeError("Laufender Sommer ist nur von Juni bis August definiert.")

    temp_sum = daily_temp * end_day
    temp_ref_sum = daily_temp_ref * end_day
    temp_days = end_day
    precip_sum = np.array(daily_precip, dtype=float, copy=True)
    precip_ref_sum = np.array(daily_precip_ref, dtype=float, copy=True)

    for month in completed:
        current = current_monthly.get((current_year, month))
        if current is None:
            raise RuntimeError(f"Aktuelles Monatsfeld {current_year}-{month:02d} fehlt für Sommer-bis-aktuell.")
        ref_t, ref_p = climatology_monthly(ref_monthly, month)
        days = calendar.monthrange(current_year, month)[1]
        temp_sum = temp_sum + current[0] * days
        temp_ref_sum = temp_ref_sum + ref_t * days
        temp_days += days
        precip_sum = precip_sum + current[1]
        precip_ref_sum = precip_ref_sum + ref_p

    return temp_sum / temp_days, temp_ref_sum / temp_days, precip_sum, precip_ref_sum, completed


def main() -> int:
    parser = argparse.ArgumentParser(description="Laufende ERA5-Land-T Karten für Temperatur und Niederschlag in Europa erzeugen.")
    parser.add_argument("--today", help="Testdatum YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Aktuelle Downloads und Karten neu erzeugen")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    core = load_core()
    client = cds_client()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== ERA5-LAND EUROPA · LAUFENDE ZEITRÄUME ===")
    data_through = probe_available_day(client, today, args.force)
    month = data_through.month
    year = data_through.year
    end_day = data_through.day
    month_days = calendar.monthrange(year, month)[1]
    print(f"Gemeinsamer aktueller Datenstand T/P: {data_through}")

    cur_temp_file = CACHE_DIR / f"current_temp_{year}_{month:02d}_01_{end_day:02d}.nc"
    if args.force or not cur_temp_file.exists():
        request_daily_temperature(client, [year], month, list(range(1, end_day + 1)), cur_temp_file, f"Temperatur {year}-{month:02d}-01 bis {data_through}")
    lat, lon, cur_temp = read_temperature(cur_temp_file, max_day=end_day)

    ref_temp_prefix = CACHE_DIR / f"reference_temp_{REFERENCE_START}_{REFERENCE_END}_{month:02d}_full.nc"
    ref_temp_files = request_daily_temperature_period(
        client, list(range(REFERENCE_START, REFERENCE_END + 1)), month,
        list(range(1, month_days + 1)), ref_temp_prefix,
        f"Temperatur-Referenz {MONTH_NAMES[month]} {REFERENCE_START}–{REFERENCE_END}",
    )
    rlat, rlon, ref_temp = read_temperature(ref_temp_files, max_day=end_day)
    if not (np.allclose(lat, rlat) and np.allclose(lon, rlon)):
        raise RuntimeError("Aktuelles Temperaturfeld und Referenz besitzen unterschiedliche Raster.")

    cur_precip_prefix = CACHE_DIR / f"current_precip_{year}_{month:02d}_01_{end_day:02d}.nc"
    cur_precip_files = request_precip_period(client, [year], month, end_day, cur_precip_prefix, f"Niederschlag {year}-{month:02d}-01 bis {data_through}")
    plat, plon, cur_precip = read_precip(cur_precip_files, month, end_day)

    ref_precip_prefix = CACHE_DIR / f"reference_precip_{REFERENCE_START}_{REFERENCE_END}_{month:02d}_full.nc"
    ref_precip_files = request_precip_period(client, list(range(REFERENCE_START, REFERENCE_END + 1)), month, month_days, ref_precip_prefix, f"Niederschlags-Referenz {MONTH_NAMES[month]} {REFERENCE_START}–{REFERENCE_END}")
    prlat, prlon, ref_precip = read_precip(ref_precip_files, month, end_day, reference_years=REFERENCE_END - REFERENCE_START + 1)
    if not (np.allclose(lat, plat) and np.allclose(lon, plon) and np.allclose(lat, prlat) and np.allclose(lon, prlon)):
        raise RuntimeError("Temperatur- und Niederschlagsraster stimmen nicht überein.")

    running_month_label = f"{MONTH_NAMES[month]} {year} bis {data_through.strftime('%d.%m.')}"
    periods = {
        "running_month": render_period(
            core, "running_month", running_month_label, date(year, month, 1), data_through,
            lat, lon, cur_temp, ref_temp, cur_precip, ref_precip,
        )
    }

    if month in (6, 7, 8):
        completed_months = [m for m in (6, 7, 8) if m < month]
        current_monthly_fields: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        ref_monthly_fields: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        if completed_months:
            current_monthly_file = CACHE_DIR / f"summer_completed_current_{year}_{'_'.join(f'{m:02d}' for m in completed_months)}.nc"
            if args.force or not current_monthly_file.exists():
                request_monthly_tp(client, [year], completed_months, current_monthly_file, f"Vollständige Sommermonate {year}: {completed_months}")
            mlat, mlon, current_monthly_fields = read_monthly_fields(current_monthly_file)

            ref_monthly_file = CACHE_DIR / f"summer_completed_reference_{REFERENCE_START}_{REFERENCE_END}_{'_'.join(f'{m:02d}' for m in completed_months)}.nc"
            if not ref_monthly_file.exists():
                request_monthly_tp(client, list(range(REFERENCE_START, REFERENCE_END + 1)), completed_months, ref_monthly_file, f"Sommer-Monatsreferenz {REFERENCE_START}–{REFERENCE_END}: {completed_months}")
            rmlat, rmlon, ref_monthly_fields = read_monthly_fields(ref_monthly_file)
            if not (np.allclose(lat, mlat) and np.allclose(lon, mlon) and np.allclose(lat, rmlat) and np.allclose(lon, rmlon)):
                raise RuntimeError("Tages- und Monatsraster für Sommer-bis-aktuell stimmen nicht überein.")

        summer_temp, summer_temp_ref, summer_precip, summer_precip_ref, completed = combine_summer(
            year, month, end_day, cur_temp, ref_temp, cur_precip, ref_precip,
            current_monthly_fields, ref_monthly_fields,
        )
        summer_label = f"Sommer {year} bis {data_through.strftime('%d.%m.')}"
        periods["running_summer"] = render_period(
            core, "running_summer", summer_label, date(year, 6, 1), data_through,
            lat, lon, summer_temp, summer_temp_ref, summer_precip, summer_precip_ref,
        )
        periods["running_summer"]["completed_months"] = completed
        periods["running_summer"]["partial_month"] = month

    payload = {
        "ready": True,
        "payload_version": PAYLOAD_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_through": data_through.isoformat(),
        "reference_period": f"{REFERENCE_START}–{REFERENCE_END}",
        "coverage": {"north": AREA[0], "west": AREA[1], "south": AREA[2], "east": AREA[3]},
        "grid": "0,5° (CDS-Regridding aus ERA5-Land 0,1°)",
        "source": "Copernicus Climate Change Service / ECMWF · ERA5-Land / ERA5-Land-T",
        "datasets": {
            "temperature_daily": DAILY_DATASET,
            "precipitation_hourly": HOURLY_DATASET,
            "completed_months": MONTHLY_DATASET,
        },
        "preliminary": True,
        "availability_note": "Laufende Zeiträume verwenden ERA5-Land-T und enden am jüngsten gemeinsam verfügbaren vollständigen UTC-Tag für Temperatur und Niederschlag.",
        "reference_note": "Abweichungen und Niederschlagsprozente werden gegen exakt dieselben Kalendertage 1991–2020 berechnet.",
        "precipitation_note": "Für ERA5-Land entspricht der Wert um 00 UTC der 24-Stunden-Akkumulation des vorherigen UTC-Tages.",
        "periods": periods,
    }
    atomic_json(INDEX_PATH, payload)

    print("=== SUMMARY ===")
    print(f"Datenstand: {data_through}")
    print(f"Raster: {payload['grid']}")
    print("Perioden:", ", ".join(periods))
    print("Ausgabe:", INDEX_PATH.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
