#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import json
import math
import os
import shutil
import tempfile
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import cdsapi
import numpy as np
import xarray as xr

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, TwoSlopeNorm

import cartopy
import cartopy.crs as ccrs
import cartopy.feature as cfeature

DATASET = "reanalysis-era5-land-monthly-means"
REFERENCE_START = 1991
REFERENCE_END = 2020
AREA = [72.0, -25.0, 34.0, 45.0]  # N, W, S, E
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "era5_land_europe"
MAP_DIR = OUT_DIR / "maps"
CACHE_DIR = ROOT / ".era5_cache"
CARTOPY_DIR = CACHE_DIR / "cartopy"
INDEX_PATH = OUT_DIR / "index.json"
ANALYSIS_PATH = OUT_DIR / "analysis.json"
ANALYSIS_GRID_STEP = 10  # 0.1° native CDS grid -> 1.0° click-analysis grid
HISTORY_START = 1950
MAP_CLICK_GEOMETRY = {"left": 0.07, "top": 0.16, "right": 0.96, "bottom": 0.82}

TEMP_ALIASES = ("t2m", "2m_temperature", "temperature_2m")
PRECIP_ALIASES = ("tp", "total_precipitation", "precipitation")
EVAP_ALIASES = ("e", "total_evaporation", "evaporation")
RUNOFF_ALIASES = ("ro", "runoff", "total_runoff")
SURFACE_RUNOFF_ALIASES = ("sro", "surface_runoff")
SUBSURFACE_RUNOFF_ALIASES = ("ssro", "sub_surface_runoff", "subsurface_runoff")
WATER_VARIABLES = {
    "evaporation": {"variable": "total_evaporation", "aliases": EVAP_ALIASES, "label": "Gesamtverdunstung", "description": "Gesamtverdunstung inkl. Transpiration"},
    "runoff": {"variable": "runoff", "aliases": RUNOFF_ALIASES, "label": "Gesamtabfluss", "description": "Oberflächen- plus unterirdischer Abfluss"},
    "surface_runoff": {"variable": "surface_runoff", "aliases": SURFACE_RUNOFF_ALIASES, "label": "Oberflächenabfluss", "description": "Abfluss über die Landoberfläche"},
    "subsurface_runoff": {"variable": "sub_surface_runoff", "aliases": SUBSURFACE_RUNOFF_ALIASES, "label": "Unterirdischer Abfluss", "description": "Abfluss im Untergrund"},
}
SOIL_LAYERS = {
    "layer1": {
        "variable": "volumetric_soil_water_layer_1",
        "aliases": ("swvl1", "volumetric_soil_water_layer_1", "soil_water_layer_1"),
        "label": "0–7 cm",
        "depth_cm": [0, 7],
    },
    "layer2": {
        "variable": "volumetric_soil_water_layer_2",
        "aliases": ("swvl2", "volumetric_soil_water_layer_2", "soil_water_layer_2"),
        "label": "7–28 cm",
        "depth_cm": [7, 28],
    },
    "layer3": {
        "variable": "volumetric_soil_water_layer_3",
        "aliases": ("swvl3", "volumetric_soil_water_layer_3", "soil_water_layer_3"),
        "label": "28–100 cm",
        "depth_cm": [28, 100],
    },
    "layer4": {
        "variable": "volumetric_soil_water_layer_4",
        "aliases": ("swvl4", "volumetric_soil_water_layer_4", "soil_water_layer_4"),
        "label": "100–289 cm",
        "depth_cm": [100, 289],
    },
}
LAT_ALIASES = ("latitude", "lat")
LON_ALIASES = ("longitude", "lon")

MONTH_NAMES = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}


def atomic_write_json(path: Path, payload: dict) -> None:
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


def previous_month(year: int, month: int, offset: int = 1) -> tuple[int, int]:
    value = year * 12 + (month - 1) - offset
    return value // 12, value % 12 + 1


def target_latest_complete_month(today: date) -> tuple[int, int]:
    # ERA5-Land monthly means are normally available about five days after month-end.
    # We use an extra safety margin so scheduled jobs do not hammer the CDS queue.
    offset = 1 if today.day >= 8 else 2
    return previous_month(today.year, today.month, offset)


def summer_selection(latest_year: int, latest_month: int) -> tuple[int, list[int]]:
    if latest_month < 6:
        return latest_year - 1, [6, 7, 8]
    if latest_month == 6:
        return latest_year, [6]
    if latest_month == 7:
        return latest_year, [6, 7]
    return latest_year, [6, 7, 8]


def month_range_label(months: Iterable[int]) -> str:
    months = list(months)
    if len(months) == 1:
        return MONTH_NAMES[months[0]]
    if months == [6, 7, 8]:
        return "Juni–August"
    return f"{MONTH_NAMES[months[0]]}–{MONTH_NAMES[months[-1]]}"


def cds_client() -> cdsapi.Client:
    # Authentication is normally provided through ~/.cdsapirc by the workflow.
    return cdsapi.Client(quiet=False, progress=False)


def retrieve_with_retry(client: cdsapi.Client, request: dict, target: Path, label: str, attempts: int = 3) -> None:
    """Submit a CDS request with bounded retries.

    A CDS job can occasionally fail after being accepted/running. Retrying is safe here
    because every retry writes to the same cache target and partial files are removed.
    """
    delays = (15, 45, 90)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            if target.exists():
                target.unlink()
            client.retrieve(DATASET, request, str(target))
            return
        except Exception as exc:
            last_exc = exc
            print(f"CDS-Fehler bei {label} (Versuch {attempt}/{attempts}): {exc}")
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            if attempt < attempts:
                delay = delays[min(attempt - 1, len(delays) - 1)]
                print(f"Neuer Versuch in {delay} Sekunden …")
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def request_monthly_file(client: cdsapi.Client, years: list[int], months: list[int], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": ["2m_temperature", "total_precipitation"],
        "year": [f"{year:04d}" for year in years],
        "month": [f"{month:02d}" for month in months],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA,
    }
    label = f"T/P years {years[0]}–{years[-1]}, months {months}"
    print(f"CDS request: years {years[0]}–{years[-1]}, months {months}")
    retrieve_with_retry(client, request, target, label)

def request_soil_monthly_file(client: cdsapi.Client, years: list[int], months: list[int], target: Path) -> None:
    """Download all four ERA5-Land soil-water layers in one CDS request."""
    target.parent.mkdir(parents=True, exist_ok=True)
    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": [meta["variable"] for meta in SOIL_LAYERS.values()],
        "year": [f"{year:04d}" for year in years],
        "month": [f"{month:02d}" for month in months],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA,
    }
    label = f"soil years {years[0]}–{years[-1]}, months {months}"
    print(f"CDS soil-moisture request (4 layers): years {years[0]}–{years[-1]}, months {months}")
    retrieve_with_retry(client, request, target, label)

def request_water_monthly_file(client: cdsapi.Client, years: list[int], months: list[int], target: Path, *, include_precip: bool = False) -> None:
    """Download ERA5-Land water-budget variables, optionally including precipitation."""
    target.parent.mkdir(parents=True, exist_ok=True)
    variables = [meta["variable"] for meta in WATER_VARIABLES.values()]
    if include_precip:
        variables = ["total_precipitation", *variables]
    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": variables,
        "year": [f"{year:04d}" for year in years],
        "month": [f"{month:02d}" for month in months],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA,
    }
    label = f"water years {years[0]}–{years[-1]}, months {months}"
    suffix = " + precipitation" if include_precip else ""
    print(f"CDS water-budget request{suffix}: years {years[0]}–{years[-1]}, months {months}")
    retrieve_with_retry(client, request, target, label)


def open_download(path: Path) -> xr.Dataset:
    if zipfile.is_zipfile(path):
        extract_dir = path.with_suffix("")
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(extract_dir)
        nc_files = sorted(extract_dir.rglob("*.nc"))
        if not nc_files:
            raise RuntimeError(f"CDS ZIP enthält keine NetCDF-Datei: {path}")
        datasets = [xr.open_dataset(item) for item in nc_files]
        return xr.merge(datasets, compat="override") if len(datasets) > 1 else datasets[0]
    return xr.open_dataset(path)


def find_name(container, aliases: tuple[str, ...]) -> str:
    names = list(container)
    lower = {name.lower(): name for name in names}
    for alias in aliases:
        if alias.lower() in lower:
            return lower[alias.lower()]
    for name in names:
        lname = name.lower()
        if any(alias.lower() in lname for alias in aliases):
            return name
    raise KeyError(f"Keine passende Variable gefunden. Vorhanden: {names}")


def spatial_names(ds: xr.Dataset) -> tuple[str, str]:
    lat = find_name(ds.coords, LAT_ALIASES)
    lon = find_name(ds.coords, LON_ALIASES)
    return lat, lon


def variable_name(ds: xr.Dataset, aliases: tuple[str, ...]) -> str:
    return find_name(ds.data_vars, aliases)


def normalize_lon(ds: xr.Dataset, lon_name: str) -> xr.Dataset:
    lon = ds[lon_name]
    if float(lon.max()) > 180:
        new_lon = ((lon + 180) % 360) - 180
        ds = ds.assign_coords({lon_name: new_lon}).sortby(lon_name)
    return ds


def time_dim(da: xr.DataArray, lat_name: str, lon_name: str) -> str | None:
    dims = [dim for dim in da.dims if dim not in {lat_name, lon_name}]
    if not dims:
        return None
    # ERA5-Land monthly files normally have one temporal dimension.
    return dims[0]


def load_current_months(client: cdsapi.Client, year: int, months: list[int], force: bool) -> dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    cache_file = CACHE_DIR / f"current_{year}_{'_'.join(f'{m:02d}' for m in months)}.nc"
    if force and cache_file.exists():
        cache_file.unlink()
    if not cache_file.exists():
        request_monthly_file(client, [year], months, cache_file)

    ds = open_download(cache_file)
    lat_name, lon_name = spatial_names(ds)
    ds = normalize_lon(ds, lon_name)
    temp_name = variable_name(ds, TEMP_ALIASES)
    precip_name = variable_name(ds, PRECIP_ALIASES)
    temp_da = ds[temp_name]
    precip_da = ds[precip_name]
    tdim = time_dim(temp_da, lat_name, lon_name)
    pdim = time_dim(precip_da, lat_name, lon_name)
    if tdim is None or pdim is None:
        if len(months) != 1:
            raise RuntimeError("Monatsdimension in ERA5-Land-Datei nicht erkannt.")
        temp_slices = [temp_da]
        precip_slices = [precip_da]
    else:
        if temp_da.sizes[tdim] != len(months):
            raise RuntimeError(f"Unerwartete Anzahl Temperaturfelder: {temp_da.sizes[tdim]} statt {len(months)}")
        temp_slices = [temp_da.isel({tdim: idx}) for idx in range(len(months))]
        precip_slices = [precip_da.isel({pdim: idx}) for idx in range(len(months))]

    lat = np.asarray(ds[lat_name].values, dtype=float)
    lon = np.asarray(ds[lon_name].values, dtype=float)
    result = {}
    for idx, month in enumerate(months):
        temp_c = np.asarray(temp_slices[idx].squeeze().values, dtype=float) - 273.15
        # ERA5-Land moda accumulated hydrological fields are effective metres/day.
        precip_mm = np.asarray(precip_slices[idx].squeeze().values, dtype=float) * 1000.0 * calendar.monthrange(year, month)[1]
        result[month] = (lat, lon, temp_c, precip_mm)
    ds.close()
    return result


def load_current_soil_months(client: cdsapi.Client, year: int, months: list[int], force: bool) -> dict[int, dict]:
    # V3 uses a new cache name because V2 files contained layer 1 only.
    cache_file = CACHE_DIR / f"current_soil_v3_{year}_{'_'.join(f'{m:02d}' for m in months)}.nc"
    if force and cache_file.exists():
        cache_file.unlink()
    if not cache_file.exists():
        request_soil_monthly_file(client, [year], months, cache_file)

    ds = open_download(cache_file)
    lat_name, lon_name = spatial_names(ds)
    ds = normalize_lon(ds, lon_name)
    lat = np.asarray(ds[lat_name].values, dtype=float)
    lon = np.asarray(ds[lon_name].values, dtype=float)

    layer_slices: dict[str, list[xr.DataArray]] = {}
    for layer_key, meta in SOIL_LAYERS.items():
        soil_name = variable_name(ds, meta["aliases"])
        soil_da = ds[soil_name]
        sdim = time_dim(soil_da, lat_name, lon_name)
        if sdim is None:
            if len(months) != 1:
                raise RuntimeError(f"Monatsdimension für {layer_key} nicht erkannt.")
            slices = [soil_da]
        else:
            if soil_da.sizes[sdim] != len(months):
                raise RuntimeError(
                    f"Unerwartete Anzahl Bodenfeuchtefelder für {layer_key}: "
                    f"{soil_da.sizes[sdim]} statt {len(months)}"
                )
            slices = [soil_da.isel({sdim: idx}) for idx in range(len(months))]
        layer_slices[layer_key] = slices

    result: dict[int, dict] = {}
    for idx, month in enumerate(months):
        result[month] = {
            "lat": lat,
            "lon": lon,
            "layers": {
                layer_key: np.asarray(layer_slices[layer_key][idx].squeeze().values, dtype=float)
                for layer_key in SOIL_LAYERS
            },
        }
    ds.close()
    return result


def year_chunks(years: Iterable[int], chunk_size: int) -> list[list[int]]:
    values = [int(y) for y in years]
    return [values[i:i + chunk_size] for i in range(0, len(values), chunk_size)]


def load_soil_reference_month(client: cdsapi.Client, month: int, force: bool) -> dict:
    """Return the 30 individual 1991–2020 monthly fields for every soil layer.

    The CDS reference retrieval is deliberately split into five-year jobs. ECMWF
    recommends smaller requests for reliable queue processing, and a failed chunk can
    then be retried without losing the already downloaded chunks.
    """
    ref_file = CACHE_DIR / f"soil_reference_v3_1991_2020_{month:02d}.nc"
    ref_years = np.arange(REFERENCE_START, REFERENCE_END + 1, dtype=int)
    chunks = year_chunks(ref_years.tolist(), 5)
    chunk_files = [
        CACHE_DIR / f"raw_soil_reference_v4_{month:02d}_{chunk[0]}_{chunk[-1]}.nc"
        for chunk in chunks
    ]

    if force:
        try:
            ref_file.unlink()
        except FileNotFoundError:
            pass
        for item in chunk_files:
            try:
                item.unlink()
            except FileNotFoundError:
                pass

    if ref_file.exists():
        ds = xr.open_dataset(ref_file)
        result = {
            "lat": np.asarray(ds["latitude"].values, dtype=float),
            "lon": np.asarray(ds["longitude"].values, dtype=float),
            "years": np.asarray(ds["year"].values, dtype=int),
            "layers": {
                layer_key: np.asarray(ds[layer_key].values, dtype=float)
                for layer_key in SOIL_LAYERS
            },
        }
        ds.close()
        return result

    all_years: list[int] = []
    layer_parts: dict[str, list[np.ndarray]] = {key: [] for key in SOIL_LAYERS}
    lat: np.ndarray | None = None
    lon: np.ndarray | None = None

    for chunk, raw_file in zip(chunks, chunk_files):
        if not raw_file.exists():
            request_soil_monthly_file(client, chunk, [month], raw_file)
        ds = open_download(raw_file)
        lat_name, lon_name = spatial_names(ds)
        ds = normalize_lon(ds, lon_name)
        lat_here = np.asarray(ds[lat_name].values, dtype=float)
        lon_here = np.asarray(ds[lon_name].values, dtype=float)
        if lat is None:
            lat, lon = lat_here, lon_here
        elif not (np.array_equal(lat, lat_here) and np.array_equal(lon, lon_here)):
            ds.close()
            raise RuntimeError(f"ERA5-Land-Gitter stimmt im Bodenfeuchte-Chunk {chunk[0]}–{chunk[-1]} nicht überein.")

        years_here_final: np.ndarray | None = None
        for layer_key, meta in SOIL_LAYERS.items():
            soil_name = variable_name(ds, meta["aliases"])
            soil_da = ds[soil_name]
            sdim = time_dim(soil_da, lat_name, lon_name)
            if sdim is None or soil_da.sizes[sdim] != len(chunk):
                ds.close()
                raise RuntimeError(
                    f"Zeitdimension der Referenz für {layer_key}, {chunk[0]}–{chunk[-1]} "
                    f"hat nicht {len(chunk)} Felder."
                )
            soil_da = soil_da.transpose(sdim, lat_name, lon_name)
            values = np.asarray(soil_da.values, dtype=np.float32)
            try:
                years_here = np.asarray(ds[sdim].dt.year.values, dtype=int)
            except Exception:
                years_here = np.asarray(chunk, dtype=int)
            expected = np.asarray(chunk, dtype=int)
            if years_here.size == expected.size and set(years_here.tolist()) == set(expected.tolist()):
                order = [int(np.where(years_here == y)[0][0]) for y in expected]
                values = values[order]
                years_here_final = expected
            else:
                years_here_final = expected
            layer_parts[layer_key].append(values)
        all_years.extend(int(y) for y in years_here_final)
        ds.close()

    assert lat is not None and lon is not None
    detected_years = np.asarray(all_years, dtype=int)
    if not np.array_equal(detected_years, ref_years):
        raise RuntimeError("Bodenfeuchte-Referenzjahre 1991–2020 sind nach dem Chunking nicht vollständig.")
    layer_arrays = {key: np.concatenate(parts, axis=0) for key, parts in layer_parts.items()}

    encoding = {layer_key: {"zlib": True, "complevel": 3, "dtype": "float32"} for layer_key in SOIL_LAYERS}
    out = xr.Dataset(
        {layer_key: (("year", "latitude", "longitude"), layer_arrays[layer_key]) for layer_key in SOIL_LAYERS},
        coords={"year": detected_years, "latitude": lat, "longitude": lon},
        attrs={
            "reference_period": "1991-2020",
            "month": month,
            "description": "ERA5-Land monthly volumetric soil water; all four model soil layers",
            "download_strategy": "5-year CDS chunks with retry",
        },
    )
    out.to_netcdf(ref_file, encoding=encoding)
    out.close()

    # Keep partial chunks while a run is incomplete; after the consolidated cache is
    # safely written they are no longer needed and can be removed to save cache space.
    for raw_file in chunk_files:
        try:
            raw_file.unlink()
        except FileNotFoundError:
            pass

    return {
        "lat": lat,
        "lon": lon,
        "years": detected_years,
        "layers": {layer_key: np.asarray(layer_arrays[layer_key], dtype=float) for layer_key in SOIL_LAYERS},
    }

def load_current_water_months(client: cdsapi.Client, year: int, months: list[int], force: bool) -> dict[int, dict]:
    cache_file = CACHE_DIR / f"current_water_v5_{year}_{'_'.join(f'{m:02d}' for m in months)}.nc"
    if force and cache_file.exists():
        cache_file.unlink()
    if not cache_file.exists():
        request_water_monthly_file(client, [year], months, cache_file)

    ds = open_download(cache_file)
    lat_name, lon_name = spatial_names(ds)
    ds = normalize_lon(ds, lon_name)
    lat = np.asarray(ds[lat_name].values, dtype=float)
    lon = np.asarray(ds[lon_name].values, dtype=float)
    variable_slices: dict[str, list[xr.DataArray]] = {}
    for key, meta in WATER_VARIABLES.items():
        name = variable_name(ds, meta["aliases"])
        da = ds[name]
        dim = time_dim(da, lat_name, lon_name)
        if dim is None:
            if len(months) != 1:
                ds.close()
                raise RuntimeError(f"Monatsdimension für Wasserhaushalt {key} nicht erkannt.")
            slices = [da]
        else:
            if da.sizes[dim] != len(months):
                ds.close()
                raise RuntimeError(f"Unerwartete Anzahl Wasserhaushaltsfelder für {key}: {da.sizes[dim]} statt {len(months)}")
            slices = [da.isel({dim: idx}) for idx in range(len(months))]
        variable_slices[key] = slices

    result: dict[int, dict] = {}
    for idx, month in enumerate(months):
        factor = 1000.0 * calendar.monthrange(year, month)[1]
        fields = {}
        for key in WATER_VARIABLES:
            values = np.asarray(variable_slices[key][idx].squeeze().values, dtype=float) * factor
            # ECMWF's accumulated-flux convention is positive downward. Total
            # evaporation is therefore normally negative; expose evaporation as
            # a positive water loss from the surface.
            if key == "evaporation":
                values = -values
            fields[key] = values
        result[month] = {"lat": lat, "lon": lon, "fields": fields}
    ds.close()
    return result


def load_water_reference_month(client: cdsapi.Client, month: int, force: bool) -> dict:
    """1991–2020 individual monthly water-budget fields on the native 0.1° CDS grid."""
    ref_file = CACHE_DIR / f"water_reference_v5_{REFERENCE_START}_{REFERENCE_END}_{month:02d}.nc"
    ref_years = np.arange(REFERENCE_START, REFERENCE_END + 1, dtype=int)
    chunks = year_chunks(ref_years.tolist(), 10)
    chunk_files = [CACHE_DIR / f"raw_water_reference_v5_{month:02d}_{c[0]}_{c[-1]}.nc" for c in chunks]
    if force:
        try: ref_file.unlink()
        except FileNotFoundError: pass
        for item in chunk_files:
            try: item.unlink()
            except FileNotFoundError: pass
    if ref_file.exists():
        ds = xr.open_dataset(ref_file)
        out = {
            "lat": np.asarray(ds["latitude"].values, dtype=float),
            "lon": np.asarray(ds["longitude"].values, dtype=float),
            "years": np.asarray(ds["year"].values, dtype=int),
            "fields": {key: np.asarray(ds[key].values, dtype=float) for key in ["precipitation", *WATER_VARIABLES.keys()]},
        }
        ds.close()
        return out

    keys = ["precipitation", *WATER_VARIABLES.keys()]
    aliases = {"precipitation": PRECIP_ALIASES, **{key: meta["aliases"] for key, meta in WATER_VARIABLES.items()}}
    parts: dict[str, list[np.ndarray]] = {key: [] for key in keys}
    years_parts: list[np.ndarray] = []
    lat = lon = None
    for chunk, raw_file in zip(chunks, chunk_files):
        if not raw_file.exists():
            request_water_monthly_file(client, chunk, [month], raw_file, include_precip=True)
        ds = open_download(raw_file)
        lat_name, lon_name = spatial_names(ds)
        ds = normalize_lon(ds, lon_name)
        lat_here = np.asarray(ds[lat_name].values, dtype=float)
        lon_here = np.asarray(ds[lon_name].values, dtype=float)
        if lat is None:
            lat, lon = lat_here, lon_here
        elif not (np.array_equal(lat, lat_here) and np.array_equal(lon, lon_here)):
            ds.close(); raise RuntimeError("ERA5-Land-Gitter der Wasserhaushalts-Referenz stimmt nicht überein.")
        expected = np.asarray(chunk, dtype=int)
        years_final = expected.copy()
        for key in keys:
            name = variable_name(ds, aliases[key])
            da = ds[name]
            dim = time_dim(da, lat_name, lon_name)
            if dim is None or da.sizes[dim] != len(chunk):
                ds.close(); raise RuntimeError(f"Zeitdimension Wasserhaushalt {key}, {chunk[0]}–{chunk[-1]} ist unvollständig.")
            da = da.transpose(dim, lat_name, lon_name)
            values = np.asarray(da.values, dtype=np.float32)
            try: detected = np.asarray(ds[dim].dt.year.values, dtype=int)
            except Exception: detected = expected.copy()
            if detected.size == expected.size and set(detected.tolist()) == set(expected.tolist()):
                order = [int(np.where(detected == y)[0][0]) for y in expected]
                values = values[order]
            days = np.asarray([calendar.monthrange(int(y), month)[1] for y in expected], dtype=np.float32)[:, None, None]
            values = values * days * 1000.0
            if key == "evaporation": values = -values
            parts[key].append(values.astype(np.float32))
        years_parts.append(years_final)
        ds.close()

    years_all = np.concatenate(years_parts)
    if not np.array_equal(years_all, ref_years):
        raise RuntimeError("Wasserhaushalts-Referenzjahre 1991–2020 sind nicht vollständig.")
    assert lat is not None and lon is not None
    arrays = {key: np.concatenate(values, axis=0) for key, values in parts.items()}
    out_ds = xr.Dataset(
        {key: (("year", "latitude", "longitude"), arrays[key]) for key in keys},
        coords={"year": years_all, "latitude": lat, "longitude": lon},
        attrs={"reference_period": "1991-2020", "month": month, "source": "ERA5-Land monthly means", "download_strategy": "10-year CDS chunks with retry"},
    )
    encoding = {key: {"zlib": True, "complevel": 3, "dtype": "float32"} for key in keys}
    out_ds.to_netcdf(ref_file, encoding=encoding)
    out_ds.close()
    for raw_file in chunk_files:
        try: raw_file.unlink()
        except FileNotFoundError: pass
    return {"lat": lat, "lon": lon, "years": years_all, "fields": {key: np.asarray(arrays[key], dtype=float) for key in keys}}


def load_climatology_month(client: cdsapi.Client, month: int, force: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """1991–2020 monthly climatology, downloaded in ten-year CDS chunks."""
    clim_file = CACHE_DIR / f"climatology_1991_2020_{month:02d}.nc"
    ref_years = list(range(REFERENCE_START, REFERENCE_END + 1))
    chunks = year_chunks(ref_years, 10)
    chunk_files = [CACHE_DIR / f"raw_climatology_v4_{month:02d}_{c[0]}_{c[-1]}.nc" for c in chunks]
    if force:
        try:
            clim_file.unlink()
        except FileNotFoundError:
            pass
        for item in chunk_files:
            try:
                item.unlink()
            except FileNotFoundError:
                pass
    if clim_file.exists():
        ds = xr.open_dataset(clim_file)
        lat = np.asarray(ds["latitude"].values, dtype=float)
        lon = np.asarray(ds["longitude"].values, dtype=float)
        temp = np.asarray(ds["temperature_c"].values, dtype=float)
        precip = np.asarray(ds["precipitation_mm"].values, dtype=float)
        ds.close()
        return lat, lon, temp, precip

    temp_sum = temp_count = precip_sum = precip_count = None
    lat = lon = None
    for chunk, raw_file in zip(chunks, chunk_files):
        if not raw_file.exists():
            request_monthly_file(client, chunk, [month], raw_file)
        ds = open_download(raw_file)
        lat_name, lon_name = spatial_names(ds)
        ds = normalize_lon(ds, lon_name)
        lat_here = np.asarray(ds[lat_name].values, dtype=float)
        lon_here = np.asarray(ds[lon_name].values, dtype=float)
        if lat is None:
            lat, lon = lat_here, lon_here
        elif not (np.array_equal(lat, lat_here) and np.array_equal(lon, lon_here)):
            ds.close()
            raise RuntimeError("ERA5-Land-Gitter der Klimatologie-Chunks stimmt nicht überein.")
        tname = variable_name(ds, TEMP_ALIASES)
        pname = variable_name(ds, PRECIP_ALIASES)
        tda, pda = ds[tname], ds[pname]
        tdim, pdim = time_dim(tda, lat_name, lon_name), time_dim(pda, lat_name, lon_name)
        if tdim is None or pdim is None:
            ds.close()
            raise RuntimeError("Zeitdimension für die Klimatologie fehlt.")
        tda = tda.transpose(tdim, lat_name, lon_name)
        pda = pda.transpose(pdim, lat_name, lon_name)
        temp = np.asarray(tda.values, dtype=float) - 273.15
        precip = np.asarray(pda.values, dtype=float)
        try:
            years_t = np.asarray(ds[tdim].dt.year.values, dtype=int)
        except Exception:
            years_t = np.asarray(chunk, dtype=int)
        try:
            years_p = np.asarray(ds[pdim].dt.year.values, dtype=int)
        except Exception:
            years_p = np.asarray(chunk, dtype=int)
        expected = np.asarray(chunk, dtype=int)
        if set(years_t.tolist()) == set(expected.tolist()):
            order = [int(np.where(years_t == y)[0][0]) for y in expected]
            temp = temp[order]
        if set(years_p.tolist()) == set(expected.tolist()):
            order = [int(np.where(years_p == y)[0][0]) for y in expected]
            precip = precip[order]
        days = np.asarray([calendar.monthrange(int(y), month)[1] for y in expected], dtype=float)[:, None, None]
        precip = precip * days * 1000.0
        valid_t = np.isfinite(temp)
        valid_p = np.isfinite(precip)
        if temp_sum is None:
            shape = temp.shape[1:]
            temp_sum = np.zeros(shape, dtype=float)
            temp_count = np.zeros(shape, dtype=np.int16)
            precip_sum = np.zeros(shape, dtype=float)
            precip_count = np.zeros(shape, dtype=np.int16)
        temp_sum += np.nansum(temp, axis=0)
        temp_count += np.sum(valid_t, axis=0).astype(np.int16)
        precip_sum += np.nansum(precip, axis=0)
        precip_count += np.sum(valid_p, axis=0).astype(np.int16)
        ds.close()

    assert lat is not None and lon is not None
    with np.errstate(invalid="ignore", divide="ignore"):
        temp_clim = temp_sum / temp_count
        precip_clim = precip_sum / precip_count
    temp_clim[temp_count == 0] = np.nan
    precip_clim[precip_count == 0] = np.nan
    out = xr.Dataset(
        {
            "temperature_c": (("latitude", "longitude"), temp_clim.astype(np.float32)),
            "precipitation_mm": (("latitude", "longitude"), precip_clim.astype(np.float32)),
        },
        coords={"latitude": lat, "longitude": lon},
        attrs={"reference_period": "1991-2020", "month": month, "download_strategy": "10-year CDS chunks with retry"},
    )
    out.to_netcdf(clim_file)
    out.close()
    for raw_file in chunk_files:
        try:
            raw_file.unlink()
        except FileNotFoundError:
            pass
    return lat, lon, temp_clim, precip_clim

def weighted_mean(field: np.ndarray, lat: np.ndarray) -> float | None:
    arr = np.asarray(field, dtype=float)
    weights = np.cos(np.deg2rad(np.asarray(lat, dtype=float)))[:, None]
    mask = np.isfinite(arr)
    if not np.any(mask):
        return None
    w = np.broadcast_to(weights, arr.shape)
    return float(np.sum(arr[mask] * w[mask]) / np.sum(w[mask]))


def weighted_fraction(mask: np.ndarray, valid: np.ndarray, lat: np.ndarray) -> float | None:
    mask = np.asarray(mask, dtype=bool)
    valid = np.asarray(valid, dtype=bool)
    if not np.any(valid):
        return None
    weights = np.cos(np.deg2rad(np.asarray(lat, dtype=float)))[:, None]
    w = np.broadcast_to(weights, valid.shape)
    denominator = np.sum(w[valid])
    if denominator <= 0:
        return None
    return float(np.sum(w[valid & mask]) / denominator * 100.0)


def soil_percentile_field(current: np.ndarray, reference_samples: np.ndarray) -> np.ndarray:
    """Empirical percentile rank of the current field against 30 reference years."""
    current = np.asarray(current, dtype=float)
    reference = np.asarray(reference_samples, dtype=float)
    valid_ref = np.isfinite(reference)
    valid_count = valid_ref.sum(axis=0)
    current3 = current[None, :, :]
    less = ((reference < current3) & valid_ref).sum(axis=0)
    equal = ((reference == current3) & valid_ref).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        percentile = (less + 0.5 * equal) / valid_count * 100.0
    percentile[(valid_count == 0) | ~np.isfinite(current)] = np.nan
    return percentile


def combine_reference_soil(reference_by_month: dict[int, dict], layer_key: str, months: list[int]) -> np.ndarray:
    """Build one reference-period field per year for the selected month/season."""
    years = np.asarray(reference_by_month[months[0]]["years"], dtype=int)
    first = np.asarray(reference_by_month[months[0]]["layers"][layer_key], dtype=float)
    numerator = np.zeros_like(first, dtype=float)
    denominator = np.zeros_like(first, dtype=float)

    for month in months:
        item = reference_by_month[month]
        item_years = np.asarray(item["years"], dtype=int)
        if not np.array_equal(item_years, years):
            raise RuntimeError(f"Referenzjahre für Bodenfeuchte-Monat {month} sind nicht deckungsgleich.")
        values = np.asarray(item["layers"][layer_key], dtype=float)
        day_weights = np.asarray([calendar.monthrange(int(y), month)[1] for y in years], dtype=float)[:, None, None]
        valid = np.isfinite(values)
        numerator += np.where(valid, values * day_weights, 0.0)
        denominator += np.where(valid, day_weights, 0.0)

    with np.errstate(invalid="ignore", divide="ignore"):
        combined = numerator / denominator
    combined[denominator == 0] = np.nan
    return combined


def combine_reference_water(reference_by_month: dict[int, dict], field_key: str, months: list[int]) -> np.ndarray:
    years = np.asarray(reference_by_month[months[0]]["years"], dtype=int)
    pieces = []
    for month in months:
        item = reference_by_month[month]
        if not np.array_equal(np.asarray(item["years"], dtype=int), years):
            raise RuntimeError(f"Referenzjahre Wasserhaushalt Monat {month} sind nicht deckungsgleich.")
        if field_key == "water_balance":
            values = np.asarray(item["fields"]["precipitation"], dtype=float) - np.asarray(item["fields"]["evaporation"], dtype=float)
        else:
            values = np.asarray(item["fields"][field_key], dtype=float)
        pieces.append(values)
    stack = np.stack(pieces, axis=0)
    valid = np.all(np.isfinite(stack), axis=0)
    combined = np.sum(np.where(np.isfinite(stack), stack, 0.0), axis=0)
    combined[~valid] = np.nan
    return combined


def combine_current_water(current_by_month: dict[int, dict], field_key: str, months: list[int], current_precip: dict[int, np.ndarray] | None = None) -> np.ndarray:
    pieces = []
    for month in months:
        if field_key == "water_balance":
            if current_precip is None:
                raise RuntimeError("Niederschlag fehlt für die Wasserbilanz.")
            values = np.asarray(current_precip[month], dtype=float) - np.asarray(current_by_month[month]["fields"]["evaporation"], dtype=float)
        else:
            values = np.asarray(current_by_month[month]["fields"][field_key], dtype=float)
        pieces.append(values)
    stack = np.stack(pieces, axis=0)
    valid = np.all(np.isfinite(stack), axis=0)
    combined = np.sum(np.where(np.isfinite(stack), stack, 0.0), axis=0)
    combined[~valid] = np.nan
    return combined


def finite_quantile(field: np.ndarray, q: float) -> float:
    vals = np.asarray(field, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return 1.0
    return float(np.quantile(vals, q))


def render_map(field: np.ndarray, lat: np.ndarray, lon: np.ndarray, *, title: str, subtitle: str,
               unit: str, filename: Path, kind: str) -> None:
    filename.parent.mkdir(parents=True, exist_ok=True)
    cartopy.config["data_dir"] = str(CARTOPY_DIR)
    CARTOPY_DIR.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(13.2, 8.1), dpi=150)
    # Fixed axes geometry makes the PNG a reliable geographic click target in the dashboard.
    ax = fig.add_axes([0.07, 0.18, 0.89, 0.66], projection=ccrs.PlateCarree())
    ax.set_extent([AREA[1], AREA[3], AREA[2], AREA[0]], crs=ccrs.PlateCarree())

    data = np.ma.masked_invalid(np.asarray(field, dtype=float))
    kwargs = {}
    percentile_boundaries = None
    percentile_ticks = None
    percentile_ticklabels = None
    if kind == "temp_absolute":
        cmap = "turbo"
        lo = math.floor(finite_quantile(data, 0.02) / 2) * 2
        hi = math.ceil(finite_quantile(data, 0.98) / 2) * 2
        if hi <= lo:
            hi = lo + 2
        kwargs.update(vmin=lo, vmax=hi)
    elif kind == "temp_anomaly":
        cmap = "RdBu_r"
        vmax = max(1.0, math.ceil(finite_quantile(np.abs(data), 0.98) * 2) / 2)
        kwargs.update(norm=TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax))
    elif kind == "precip_absolute":
        cmap = "YlGnBu"
        lo = 0.0
        hi = max(10.0, math.ceil(finite_quantile(data, 0.98) / 10) * 10)
        kwargs.update(vmin=lo, vmax=hi)
    elif kind == "precip_percent":
        cmap = "BrBG"
        vmax = max(150.0, math.ceil(finite_quantile(data, 0.98) / 25) * 25)
        kwargs.update(norm=TwoSlopeNorm(vmin=0, vcenter=100, vmax=vmax))
    elif kind == "soil_absolute":
        cmap = "YlGnBu"
        lo = max(0.0, math.floor(finite_quantile(data, 0.02) * 20) / 20)
        hi = min(0.7, math.ceil(finite_quantile(data, 0.98) * 20) / 20)
        if hi <= lo:
            hi = lo + 0.05
        kwargs.update(vmin=lo, vmax=hi)
    elif kind == "soil_anomaly":
        cmap = "BrBG"
        vmax = max(0.02, math.ceil(finite_quantile(np.abs(data), 0.98) * 100) / 100)
        kwargs.update(norm=TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax))
    elif kind in {"soil_percentile", "water_percentile", "balance_percentile"}:
        percentile_boundaries = [0, 5, 10, 20, 30, 70, 80, 90, 95, 100.0001]
        percentile_ticks = [2.5, 7.5, 15, 25, 50, 75, 85, 92.5, 97.5]
        percentile_ticklabels = ["≤5", "5–10", "10–20", "20–30", "30–70", "70–80", "80–90", "90–95", ">95"]
        cmap = plt.get_cmap("BrBG", len(percentile_boundaries) - 1)
        kwargs.update(norm=BoundaryNorm(percentile_boundaries, cmap.N, clip=True))
    elif kind == "water_absolute":
        cmap = "YlGnBu"
        lo = min(0.0, math.floor(finite_quantile(data, 0.02) / 5) * 5)
        hi = max(5.0, math.ceil(finite_quantile(data, 0.98) / 5) * 5)
        if hi <= lo: hi = lo + 5
        kwargs.update(vmin=lo, vmax=hi)
    elif kind == "water_anomaly":
        cmap = "BrBG"
        vmax = max(5.0, math.ceil(finite_quantile(np.abs(data), 0.98) / 5) * 5)
        kwargs.update(norm=TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax))
    elif kind in {"balance_absolute", "balance_anomaly"}:
        cmap = "BrBG"
        vmax = max(10.0, math.ceil(finite_quantile(np.abs(data), 0.98) / 10) * 10)
        kwargs.update(norm=TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax))
    else:
        cmap = "viridis"

    mesh = ax.pcolormesh(lon, lat, data, transform=ccrs.PlateCarree(), cmap=cmap, shading="auto", **kwargs)
    ax.add_feature(cfeature.COASTLINE.with_scale("50m"), linewidth=0.55, edgecolor="#39434a")
    ax.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.4, edgecolor="#66727a")
    ax.add_feature(cfeature.LAKES.with_scale("50m"), facecolor="#f4f7f8", edgecolor="#89949a", linewidth=0.25, zorder=3)
    ax.set_facecolor("#eef3f5")
    gl = ax.gridlines(draw_labels=True, linewidth=0.25, color="#7f8c92", alpha=0.45, linestyle="--")
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"size": 8, "color": "#59656c"}
    gl.ylabel_style = {"size": 8, "color": "#59656c"}

    cax = fig.add_axes([0.14, 0.085, 0.75, 0.032])
    cbar_kwargs = {"orientation": "horizontal"}
    if percentile_boundaries is not None:
        cbar_kwargs.update(boundaries=percentile_boundaries, ticks=percentile_ticks, spacing="proportional")
    cbar = plt.colorbar(mesh, cax=cax, **cbar_kwargs)
    cbar.set_label(unit, fontsize=10)
    cbar.ax.tick_params(labelsize=8)
    if percentile_ticklabels is not None:
        cbar.ax.set_xticklabels(percentile_ticklabels)

    fig.suptitle(title, x=0.075, y=0.97, ha="left", va="top", fontsize=17, fontweight="bold")
    fig.text(0.075, 0.925, subtitle, ha="left", va="top", fontsize=10, color="#56636a")
    fig.text(0.075, 0.025, "Quelle: Copernicus Climate Change Service / ECMWF · ERA5-Land · 0,1° · Landflächen",
             ha="left", va="bottom", fontsize=8, color="#68757c")
    plt.savefig(filename, facecolor="white")
    plt.close(fig)


def combine_temperature(fields: dict[int, np.ndarray], year: int, months: list[int]) -> np.ndarray:
    weights = np.array([calendar.monthrange(year, month)[1] for month in months], dtype=float)
    stack = np.stack([fields[month] for month in months], axis=0)
    return np.average(stack, axis=0, weights=weights)


def combine_precipitation(fields: dict[int, np.ndarray], months: list[int]) -> np.ndarray:
    return np.nansum(np.stack([fields[month] for month in months], axis=0), axis=0)


def combine_soil_moisture(fields: dict[int, np.ndarray], year: int, months: list[int]) -> np.ndarray:
    weights = np.array([calendar.monthrange(year, month)[1] for month in months], dtype=float)
    stack = np.stack([fields[month] for month in months], axis=0)
    return np.average(stack, axis=0, weights=weights)


def make_period_maps(period_id: str, period_label: str, year: int, months: list[int], current: dict,
                     climate: dict, current_soil: dict, reference_soil: dict,
                     current_water: dict, reference_water: dict) -> dict:
    lat, lon = current[months[0]][0], current[months[0]][1]
    current_temp = combine_temperature({m: current[m][2] for m in months}, year, months)
    climate_temp = combine_temperature({m: climate[m][2] for m in months}, 2001, months)
    current_precip = combine_precipitation({m: current[m][3] for m in months}, months)
    climate_precip = combine_precipitation({m: climate[m][3] for m in months}, months)

    temp_anom = current_temp - climate_temp
    with np.errstate(invalid="ignore", divide="ignore"):
        precip_pct = np.where(climate_precip > 1.0, current_precip / climate_precip * 100.0, np.nan)

    files = {
        "temp_absolute": MAP_DIR / f"temperature_{period_id}_absolute.png",
        "temp_anomaly": MAP_DIR / f"temperature_{period_id}_anomaly.png",
        "precip_absolute": MAP_DIR / f"precipitation_{period_id}_absolute.png",
        "precip_percent": MAP_DIR / f"precipitation_{period_id}_percent.png",
    }

    render_map(current_temp, lat, lon, title=f"ERA5-Land Europa · 2-m-Temperatur · {period_label}", subtitle="Absolutwert · Landflächen", unit="°C", filename=files["temp_absolute"], kind="temp_absolute")
    render_map(temp_anom, lat, lon, title=f"ERA5-Land Europa · Temperaturabweichung · {period_label}", subtitle="gegenüber 1991–2020 · Landflächen", unit="K", filename=files["temp_anomaly"], kind="temp_anomaly")
    render_map(current_precip, lat, lon, title=f"ERA5-Land Europa · Niederschlag · {period_label}", subtitle="Niederschlagssumme · Landflächen", unit="mm", filename=files["precip_absolute"], kind="precip_absolute")
    render_map(precip_pct, lat, lon, title=f"ERA5-Land Europa · Niederschlag · {period_label}", subtitle="Prozent vom Mittel 1991–2020 · Landflächen", unit="% vom Mittel", filename=files["precip_percent"], kind="precip_percent")

    def rel(path: Path) -> str:
        return path.relative_to(ROOT).as_posix()

    stats_temp_current = weighted_mean(current_temp, lat)
    stats_temp_ref = weighted_mean(climate_temp, lat)
    stats_precip_current = weighted_mean(current_precip, lat)
    stats_precip_ref = weighted_mean(climate_precip, lat)

    soil_layers_payload: dict[str, dict] = {}
    for layer_key, meta in SOIL_LAYERS.items():
        current_soil_field = combine_soil_moisture({m: current_soil[m]["layers"][layer_key] for m in months}, year, months)
        reference_samples = combine_reference_soil(reference_soil, layer_key, months)
        with np.errstate(invalid="ignore"):
            climate_soil_field = np.nanmean(reference_samples, axis=0)
        soil_anom = current_soil_field - climate_soil_field
        soil_percentile = soil_percentile_field(current_soil_field, reference_samples)
        layer_files = {
            "absolute": MAP_DIR / f"soil_moisture_{layer_key}_{period_id}_absolute.png",
            "anomaly": MAP_DIR / f"soil_moisture_{layer_key}_{period_id}_anomaly.png",
            "percentile": MAP_DIR / f"soil_moisture_{layer_key}_{period_id}_percentile.png",
        }
        render_map(current_soil_field, lat, lon, title=f"ERA5-Land Europa · Bodenfeuchte {meta['label']} · {period_label}", subtitle="Volumetrischer Bodenwassergehalt · Landflächen", unit="m³/m³", filename=layer_files["absolute"], kind="soil_absolute")
        render_map(soil_anom, lat, lon, title=f"ERA5-Land Europa · Bodenfeuchteabweichung {meta['label']} · {period_label}", subtitle="gegenüber 1991–2020 · Landflächen", unit="m³/m³", filename=layer_files["anomaly"], kind="soil_anomaly")
        render_map(soil_percentile, lat, lon, title=f"ERA5-Land Europa · Bodenfeuchte-Perzentil {meta['label']} · {period_label}", subtitle="empirischer Rang gegenüber 1991–2020 · Landflächen", unit="Perzentil", filename=layer_files["percentile"], kind="soil_percentile")
        stats_current = weighted_mean(current_soil_field, lat)
        stats_reference = weighted_mean(climate_soil_field, lat)
        valid_pct = np.isfinite(soil_percentile)
        soil_layers_payload[layer_key] = {
            "absolute": {"file": rel(layer_files["absolute"]), "unit": "m³/m³", "label": "Bodenfeuchte"},
            "anomaly": {"file": rel(layer_files["anomaly"]), "unit": "m³/m³", "label": "Abweichung 1991–2020"},
            "percentile": {"file": rel(layer_files["percentile"]), "unit": "Perzentil", "label": "Perzentil / Dürreklasse 1991–2020"},
            "stats": {
                "current": stats_current, "reference": stats_reference,
                "difference": None if stats_current is None or stats_reference is None else stats_current - stats_reference,
                "dry_area_percent": weighted_fraction(soil_percentile <= 20.0, valid_pct, lat),
                "very_dry_area_percent": weighted_fraction(soil_percentile <= 10.0, valid_pct, lat),
                "wet_area_percent": weighted_fraction(soil_percentile >= 80.0, valid_pct, lat),
                "very_wet_area_percent": weighted_fraction(soil_percentile >= 90.0, valid_pct, lat),
            },
        }
    soil_payload = {"layers": soil_layers_payload, **soil_layers_payload["layer1"]}

    water_payload: dict[str, dict] = {}
    current_precip_by_month = {m: current[m][3] for m in months}
    water_metas = {
        **{key: {"label": meta["label"], "description": meta["description"]} for key, meta in WATER_VARIABLES.items()},
        "water_balance": {"label": "Wasserbilanz P−E", "description": "Niederschlag minus Gesamtverdunstung"},
    }
    for key, meta in water_metas.items():
        current_field = combine_current_water(current_water, key, months, current_precip_by_month)
        reference_samples = combine_reference_water(reference_water, key, months)
        with np.errstate(invalid="ignore"):
            reference_field = np.nanmean(reference_samples, axis=0)
        anomaly = current_field - reference_field
        percentile = soil_percentile_field(current_field, reference_samples)
        prefix = key
        wf = {
            "absolute": MAP_DIR / f"{prefix}_{period_id}_absolute.png",
            "anomaly": MAP_DIR / f"{prefix}_{period_id}_anomaly.png",
            "percentile": MAP_DIR / f"{prefix}_{period_id}_percentile.png",
        }
        balance = key == "water_balance"
        render_map(current_field, lat, lon, title=f"ERA5-Land Europa · {meta['label']} · {period_label}", subtitle=f"{meta['description']} · Landflächen", unit="mm", filename=wf["absolute"], kind="balance_absolute" if balance else "water_absolute")
        render_map(anomaly, lat, lon, title=f"ERA5-Land Europa · {meta['label']} · Abweichung · {period_label}", subtitle="gegenüber 1991–2020 · Landflächen", unit="mm", filename=wf["anomaly"], kind="balance_anomaly" if balance else "water_anomaly")
        render_map(percentile, lat, lon, title=f"ERA5-Land Europa · {meta['label']} · Perzentil · {period_label}", subtitle="empirischer Rang gegenüber 1991–2020 · Landflächen", unit="Perzentil", filename=wf["percentile"], kind="balance_percentile" if balance else "water_percentile")
        stats_current = weighted_mean(current_field, lat)
        stats_reference = weighted_mean(reference_field, lat)
        valid_pct = np.isfinite(percentile)
        water_payload[key] = {
            "absolute": {"file": rel(wf["absolute"]), "unit": "mm", "label": meta["label"]},
            "anomaly": {"file": rel(wf["anomaly"]), "unit": "mm", "label": "Abweichung 1991–2020"},
            "percentile": {"file": rel(wf["percentile"]), "unit": "Perzentil", "label": "Perzentil 1991–2020"},
            "stats": {
                "current": stats_current, "reference": stats_reference,
                "difference": None if stats_current is None or stats_reference is None else stats_current - stats_reference,
                "low20_area_percent": weighted_fraction(percentile <= 20.0, valid_pct, lat),
                "low10_area_percent": weighted_fraction(percentile <= 10.0, valid_pct, lat),
                "high80_area_percent": weighted_fraction(percentile >= 80.0, valid_pct, lat),
                "high90_area_percent": weighted_fraction(percentile >= 90.0, valid_pct, lat),
            },
        }

    return {
        "id": period_id, "label": period_label, "year": year, "months": months,
        "temperature": {
            "absolute": {"file": rel(files["temp_absolute"]), "unit": "°C", "label": "Temperatur"},
            "anomaly": {"file": rel(files["temp_anomaly"]), "unit": "K", "label": "Abweichung 1991–2020"},
            "stats": {"current": stats_temp_current, "reference": stats_temp_ref, "difference": None if stats_temp_current is None or stats_temp_ref is None else stats_temp_current - stats_temp_ref},
        },
        "precipitation": {
            "absolute": {"file": rel(files["precip_absolute"]), "unit": "mm", "label": "Niederschlag"},
            "percent": {"file": rel(files["precip_percent"]), "unit": "%", "label": "Prozent vom Mittel 1991–2020"},
            "stats": {"current": stats_precip_current, "reference": stats_precip_ref, "percent": None if not stats_precip_ref else stats_precip_current / stats_precip_ref * 100.0},
        },
        "soil_moisture": soil_payload,
        **water_payload,
    }



def round_json(value, digits: int):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return round(value, digits)


def sample_1deg(field: np.ndarray) -> np.ndarray:
    arr = np.asarray(field)
    return arr[..., ::ANALYSIS_GRID_STEP, ::ANALYSIS_GRID_STEP]


def load_history_tp_month(client: cdsapi.Client, month: int, end_year: int, force: bool) -> dict:
    """Temperature/precipitation history since 1950 sampled to 1° for browser analysis.

    Historical retrievals are split into ten-year jobs so a single heavy CDS job does
    not make the complete V4 workflow fail.
    """
    sampled_file = CACHE_DIR / f"history_tp_v4_{HISTORY_START}_{end_year}_{month:02d}_1deg.nc"
    years = np.arange(HISTORY_START, end_year + 1, dtype=int)
    chunks = year_chunks(years.tolist(), 10)
    chunk_files = [CACHE_DIR / f"raw_history_tp_v4_{month:02d}_{c[0]}_{c[-1]}.nc" for c in chunks]
    if force:
        try:
            sampled_file.unlink()
        except FileNotFoundError:
            pass
        for item in chunk_files:
            try:
                item.unlink()
            except FileNotFoundError:
                pass
    if sampled_file.exists():
        ds = xr.open_dataset(sampled_file)
        out = {
            "years": np.asarray(ds["year"].values, dtype=int),
            "lat": np.asarray(ds["latitude"].values, dtype=float),
            "lon": np.asarray(ds["longitude"].values, dtype=float),
            "temperature": np.asarray(ds["temperature_c"].values, dtype=float),
            "precipitation": np.asarray(ds["precipitation_mm"].values, dtype=float),
        }
        ds.close()
        return out

    years_parts: list[np.ndarray] = []
    temp_parts: list[np.ndarray] = []
    precip_parts: list[np.ndarray] = []
    lat = lon = None
    for chunk, raw_file in zip(chunks, chunk_files):
        if not raw_file.exists():
            request_monthly_file(client, chunk, [month], raw_file)
        ds = open_download(raw_file)
        lat_name, lon_name = spatial_names(ds)
        ds = normalize_lon(ds, lon_name)
        tname = variable_name(ds, TEMP_ALIASES)
        pname = variable_name(ds, PRECIP_ALIASES)
        tda, pda = ds[tname], ds[pname]
        tdim, pdim = time_dim(tda, lat_name, lon_name), time_dim(pda, lat_name, lon_name)
        if tdim is None or pdim is None:
            ds.close()
            raise RuntimeError("Zeitdimension für ERA5-Land-Historie fehlt.")
        tda = tda.transpose(tdim, lat_name, lon_name)
        pda = pda.transpose(pdim, lat_name, lon_name)
        temp = np.asarray(tda.values, dtype=np.float32)
        precip = np.asarray(pda.values, dtype=np.float32)
        expected = np.asarray(chunk, dtype=int)
        try:
            years_t = np.asarray(ds[tdim].dt.year.values, dtype=int)
        except Exception:
            years_t = expected.copy()
        try:
            years_p = np.asarray(ds[pdim].dt.year.values, dtype=int)
        except Exception:
            years_p = expected.copy()
        if set(years_t.tolist()) == set(expected.tolist()):
            idx = [int(np.where(years_t == y)[0][0]) for y in expected]
            temp = temp[idx]
            years_t = expected.copy()
        if set(years_p.tolist()) == set(expected.tolist()):
            idx = [int(np.where(years_p == y)[0][0]) for y in expected]
            precip = precip[idx]
            years_p = expected.copy()
        if not np.array_equal(years_t, years_p):
            ds.close()
            raise RuntimeError("Temperatur- und Niederschlagsjahre sind im Historien-Chunk nicht deckungsgleich.")
        temp = temp - 273.15
        days = np.asarray([calendar.monthrange(int(y), month)[1] for y in years_t], dtype=np.float32)[:, None, None]
        precip = precip * days * 1000.0
        lat_here = np.asarray(ds[lat_name].values, dtype=float)[::ANALYSIS_GRID_STEP]
        lon_here = np.asarray(ds[lon_name].values, dtype=float)[::ANALYSIS_GRID_STEP]
        if lat is None:
            lat, lon = lat_here, lon_here
        elif not (np.array_equal(lat, lat_here) and np.array_equal(lon, lon_here)):
            ds.close()
            raise RuntimeError("ERA5-Land-Gitter der Historien-Chunks stimmt nicht überein.")
        years_parts.append(years_t)
        temp_parts.append(sample_1deg(temp).astype(np.float32))
        precip_parts.append(sample_1deg(precip).astype(np.float32))
        ds.close()

    years_all = np.concatenate(years_parts)
    temp_all = np.concatenate(temp_parts, axis=0)
    precip_all = np.concatenate(precip_parts, axis=0)
    if not np.array_equal(years_all, years):
        raise RuntimeError("Historienjahre seit 1950 sind nach dem Chunking nicht vollständig.")
    assert lat is not None and lon is not None
    out_ds = xr.Dataset(
        {
            "temperature_c": (("year", "latitude", "longitude"), temp_all),
            "precipitation_mm": (("year", "latitude", "longitude"), precip_all),
        },
        coords={"year": years_all, "latitude": lat, "longitude": lon},
        attrs={"source": "ERA5-Land monthly means", "analysis_grid": "1 degree", "month": month, "download_strategy": "10-year CDS chunks with retry"},
    )
    encoding = {name: {"zlib": True, "complevel": 3, "dtype": "float32"} for name in out_ds.data_vars}
    out_ds.to_netcdf(sampled_file, encoding=encoding)
    out_ds.close()
    for raw_file in chunk_files:
        try:
            raw_file.unlink()
        except FileNotFoundError:
            pass
    return {"years": years_all, "lat": lat, "lon": lon, "temperature": temp_all, "precipitation": precip_all}

def load_history_water_month(client: cdsapi.Client, month: int, end_year: int, force: bool) -> dict:
    sampled_file = CACHE_DIR / f"history_water_v5_{HISTORY_START}_{end_year}_{month:02d}_1deg.nc"
    years = np.arange(HISTORY_START, end_year + 1, dtype=int)
    chunks = year_chunks(years.tolist(), 10)
    chunk_files = [CACHE_DIR / f"raw_history_water_v5_{month:02d}_{c[0]}_{c[-1]}.nc" for c in chunks]
    if force:
        try: sampled_file.unlink()
        except FileNotFoundError: pass
        for item in chunk_files:
            try: item.unlink()
            except FileNotFoundError: pass
    if sampled_file.exists():
        ds = xr.open_dataset(sampled_file)
        out = {"years": np.asarray(ds["year"].values, dtype=int), "lat": np.asarray(ds["latitude"].values, dtype=float), "lon": np.asarray(ds["longitude"].values, dtype=float), "fields": {key: np.asarray(ds[key].values, dtype=float) for key in WATER_VARIABLES}}
        ds.close(); return out

    years_parts: list[np.ndarray] = []
    parts: dict[str, list[np.ndarray]] = {key: [] for key in WATER_VARIABLES}
    lat = lon = None
    for chunk, raw_file in zip(chunks, chunk_files):
        if not raw_file.exists(): request_water_monthly_file(client, chunk, [month], raw_file)
        ds = open_download(raw_file)
        lat_name, lon_name = spatial_names(ds); ds = normalize_lon(ds, lon_name)
        expected = np.asarray(chunk, dtype=int)
        lat_here = np.asarray(ds[lat_name].values, dtype=float)[::ANALYSIS_GRID_STEP]
        lon_here = np.asarray(ds[lon_name].values, dtype=float)[::ANALYSIS_GRID_STEP]
        if lat is None: lat, lon = lat_here, lon_here
        elif not (np.array_equal(lat, lat_here) and np.array_equal(lon, lon_here)):
            ds.close(); raise RuntimeError("ERA5-Land-Gitter der Wasserhaushalts-Historie stimmt nicht überein.")
        for key, meta in WATER_VARIABLES.items():
            name = variable_name(ds, meta["aliases"]); da = ds[name]
            dim = time_dim(da, lat_name, lon_name)
            if dim is None or da.sizes[dim] != len(chunk):
                ds.close(); raise RuntimeError(f"Zeitdimension Wasserhistorie {key} fehlt.")
            da = da.transpose(dim, lat_name, lon_name)
            values = np.asarray(da.values, dtype=np.float32)
            try: detected = np.asarray(ds[dim].dt.year.values, dtype=int)
            except Exception: detected = expected.copy()
            if detected.size == expected.size and set(detected.tolist()) == set(expected.tolist()):
                order = [int(np.where(detected == y)[0][0]) for y in expected]; values = values[order]
            days = np.asarray([calendar.monthrange(int(y), month)[1] for y in expected], dtype=np.float32)[:, None, None]
            values = values * days * 1000.0
            if key == "evaporation": values = -values
            parts[key].append(sample_1deg(values).astype(np.float32))
        years_parts.append(expected); ds.close()
    years_all = np.concatenate(years_parts)
    if not np.array_equal(years_all, years): raise RuntimeError("Wasserhaushalts-Historienjahre seit 1950 sind unvollständig.")
    assert lat is not None and lon is not None
    arrays = {key: np.concatenate(v, axis=0) for key, v in parts.items()}
    out_ds = xr.Dataset({key: (("year", "latitude", "longitude"), arrays[key]) for key in WATER_VARIABLES}, coords={"year": years_all, "latitude": lat, "longitude": lon}, attrs={"source": "ERA5-Land monthly means", "analysis_grid": "1 degree", "month": month, "download_strategy": "10-year CDS chunks with retry"})
    encoding = {key: {"zlib": True, "complevel": 3, "dtype": "float32"} for key in WATER_VARIABLES}
    out_ds.to_netcdf(sampled_file, encoding=encoding); out_ds.close()
    for raw_file in chunk_files:
        try: raw_file.unlink()
        except FileNotFoundError: pass
    return {"years": years_all, "lat": lat, "lon": lon, "fields": {key: np.asarray(arrays[key], dtype=float) for key in WATER_VARIABLES}}


def combine_history_water(history_by_month: dict[int, dict], history_tp_by_month: dict[int, dict], months: list[int]) -> dict:
    years = np.asarray(history_by_month[months[0]]["years"], dtype=int)
    lat = np.asarray(history_by_month[months[0]]["lat"], dtype=float)
    lon = np.asarray(history_by_month[months[0]]["lon"], dtype=float)
    combined: dict[str, np.ndarray] = {}
    for key in WATER_VARIABLES:
        stack = np.stack([np.asarray(history_by_month[m]["fields"][key], dtype=float) for m in months], axis=0)
        valid = np.all(np.isfinite(stack), axis=0)
        values = np.sum(np.where(np.isfinite(stack), stack, 0.0), axis=0); values[~valid] = np.nan
        combined[key] = values
    tp = combine_history_tp(history_tp_by_month, months)
    if not np.array_equal(np.asarray(tp["years"], dtype=int), years): raise RuntimeError("T/P- und Wasserhaushalts-Historienjahre sind nicht deckungsgleich.")
    combined["water_balance"] = np.asarray(tp["precipitation"], dtype=float) - combined["evaporation"]
    return {"years": years, "lat": lat, "lon": lon, **combined}


def combine_history_tp(history_by_month: dict[int, dict], months: list[int]) -> dict:
    years = np.asarray(history_by_month[months[0]]["years"], dtype=int)
    lat = np.asarray(history_by_month[months[0]]["lat"], dtype=float)
    lon = np.asarray(history_by_month[months[0]]["lon"], dtype=float)
    temp_num = None
    temp_den = None
    precip_total = None
    for month in months:
        item = history_by_month[month]
        if not np.array_equal(np.asarray(item["years"], dtype=int), years):
            raise RuntimeError(f"Historienjahre für Monat {month} sind nicht deckungsgleich.")
        t = np.asarray(item["temperature"], dtype=float)
        p = np.asarray(item["precipitation"], dtype=float)
        day_weights = np.asarray([calendar.monthrange(int(y), month)[1] for y in years], dtype=float)[:, None, None]
        valid_t = np.isfinite(t)
        if temp_num is None:
            temp_num = np.zeros_like(t, dtype=float)
            temp_den = np.zeros_like(t, dtype=float)
            precip_total = np.zeros_like(p, dtype=float)
        temp_num += np.where(valid_t, t * day_weights, 0.0)
        temp_den += np.where(valid_t, day_weights, 0.0)
        precip_total += np.where(np.isfinite(p), p, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        temp = temp_num / temp_den
    temp[temp_den == 0] = np.nan
    return {"years": years, "lat": lat, "lon": lon, "temperature": temp, "precipitation": precip_total}


def build_analysis_payload(*, latest_year: int, latest_month: int, summer_year: int, summer_months: list[int],
                           current_all: dict, current_soil_all: dict, current_water_all: dict,
                           climate: dict, soil_reference: dict, water_reference: dict,
                           history_tp: dict[int, dict], history_water: dict[int, dict]) -> dict:
    months = list(range(1, latest_month + 1))
    lat = np.asarray(current_all[(latest_year, latest_month)][0], dtype=float)[::ANALYSIS_GRID_STEP]
    lon = np.asarray(current_all[(latest_year, latest_month)][1], dtype=float)[::ANALYSIS_GRID_STEP]
    temp_current = np.stack([sample_1deg(current_all[(latest_year, m)][2]) for m in months])
    precip_current = np.stack([sample_1deg(current_all[(latest_year, m)][3]) for m in months])
    temp_ref = np.stack([sample_1deg(climate[m][2]) for m in months])
    precip_ref = np.stack([sample_1deg(climate[m][3]) for m in months])

    soil_monthly = {}
    for layer_key in SOIL_LAYERS:
        cur = np.stack([sample_1deg(current_soil_all[(latest_year, m)]["layers"][layer_key]) for m in months])
        ref_mean, pct = [], []
        for m in months:
            samples = sample_1deg(soil_reference[m]["layers"][layer_key])
            with np.errstate(invalid="ignore"): ref_mean.append(np.nanmean(samples, axis=0))
            pct.append(soil_percentile_field(cur[months.index(m)], samples))
        soil_monthly[layer_key] = {"current": cur, "reference": np.stack(ref_mean), "percentile": np.stack(pct)}

    water_monthly: dict[str, dict] = {}
    for key in [*WATER_VARIABLES.keys(), "water_balance"]:
        cur_list, ref_list, pct_list = [], [], []
        for m in months:
            if key == "water_balance":
                cur_field = sample_1deg(current_all[(latest_year, m)][3] - current_water_all[(latest_year, m)]["fields"]["evaporation"])
                samples = sample_1deg(water_reference[m]["fields"]["precipitation"] - water_reference[m]["fields"]["evaporation"])
            else:
                cur_field = sample_1deg(current_water_all[(latest_year, m)]["fields"][key])
                samples = sample_1deg(water_reference[m]["fields"][key])
            with np.errstate(invalid="ignore"): ref_field = np.nanmean(samples, axis=0)
            cur_list.append(cur_field); ref_list.append(ref_field); pct_list.append(soil_percentile_field(cur_field, samples))
        water_monthly[key] = {"current": np.stack(cur_list), "reference": np.stack(ref_list), "percentile": np.stack(pct_list)}

    hist_latest = combine_history_tp(history_tp, [latest_month])
    hist_summer = combine_history_tp(history_tp, summer_months)
    water_hist_latest = combine_history_water(history_water, history_tp, [latest_month])
    water_hist_summer = combine_history_water(history_water, history_tp, summer_months)

    soil_hist_periods = {}
    for period_id, period_year, period_months in (("latest_month", latest_year, [latest_month]), ("summer", summer_year, summer_months)):
        layers = {}
        for layer_key in SOIL_LAYERS:
            reference_values = sample_1deg(combine_reference_soil(soil_reference, layer_key, period_months))
            current_values = sample_1deg(combine_soil_moisture({m: current_soil_all[(period_year, m)]["layers"][layer_key] for m in period_months}, period_year, period_months))
            layers[layer_key] = {"reference": reference_values, "current": current_values}
        soil_hist_periods[period_id] = layers

    land_mask = np.isfinite(temp_current[-1]) & np.isfinite(soil_monthly["layer1"]["current"][-1])
    points = []
    reference_years = list(range(REFERENCE_START, REFERENCE_END + 1))
    hist_periods = {"latest_month": hist_latest, "summer": hist_summer}
    water_hist_periods = {"latest_month": water_hist_latest, "summer": water_hist_summer}
    for iy, ix in zip(*np.where(land_mask)):
        point = {
            "lat": round(float(lat[iy]), 2), "lon": round(float(lon[ix]), 2),
            "monthly": {
                "temperature": {"current": [round_json(v, 2) for v in temp_current[:, iy, ix]], "reference": [round_json(v, 2) for v in temp_ref[:, iy, ix]]},
                "precipitation": {"current": [round_json(v, 1) for v in precip_current[:, iy, ix]], "reference": [round_json(v, 1) for v in precip_ref[:, iy, ix]]},
                "soil_moisture": {"layers": {}},
            },
            "history": {},
        }
        for layer_key in SOIL_LAYERS:
            sm = soil_monthly[layer_key]
            point["monthly"]["soil_moisture"]["layers"][layer_key] = {"current": [round_json(v, 4) for v in sm["current"][:, iy, ix]], "reference": [round_json(v, 4) for v in sm["reference"][:, iy, ix]], "percentile": [round_json(v, 1) for v in sm["percentile"][:, iy, ix]]}
        for key, wm in water_monthly.items():
            point["monthly"][key] = {"current": [round_json(v, 1) for v in wm["current"][:, iy, ix]], "reference": [round_json(v, 1) for v in wm["reference"][:, iy, ix]], "percentile": [round_json(v, 1) for v in wm["percentile"][:, iy, ix]]}
        for period_id, hist in hist_periods.items():
            point["history"][period_id] = {
                "temperature": [round_json(v, 2) for v in hist["temperature"][:, iy, ix]],
                "precipitation": [round_json(v, 1) for v in hist["precipitation"][:, iy, ix]],
                "soil_moisture": {"layers": {}},
            }
            wh = water_hist_periods[period_id]
            for key in [*WATER_VARIABLES.keys(), "water_balance"]:
                point["history"][period_id][key] = [round_json(v, 1) for v in wh[key][:, iy, ix]]
            for layer_key in SOIL_LAYERS:
                soil_hist = soil_hist_periods[period_id][layer_key]
                vals = [round_json(v, 4) for v in soil_hist["reference"][:, iy, ix]]
                vals.append(round_json(soil_hist["current"][iy, ix], 4))
                point["history"][period_id]["soil_moisture"]["layers"][layer_key] = vals
        points.append(point)

    payload = {
        "ready": True, "payload_version": 2, "analysis_grid": "1,0° (nächster verfügbarer Landpunkt)", "analysis_year": latest_year,
        "months": months, "month_labels": [MONTH_NAMES[m] for m in months],
        "history_years": {"latest_month": [int(y) for y in hist_latest["years"]], "summer": [int(y) for y in hist_summer["years"]]},
        "soil_history_years": {"latest_month": reference_years + [latest_year], "summer": reference_years + [summer_year]},
        "history_note": "Temperatur, Niederschlag und Wasserhaushaltsgrößen: historische Einordnung seit 1950. Bodenfeuchte: Einzeljahre 1991–2020 plus aktuelles Jahr.",
        "points": points,
    }
    atomic_write_json(ANALYSIS_PATH, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="ERA5-Land Europakarten für das Climate Dashboard erzeugen.")
    parser.add_argument("--force", action="store_true", help="CDS-Daten und Karten auch für denselben Zielmonat neu erzeugen")
    parser.add_argument("--today", help="Testdatum YYYY-MM-DD")
    args = parser.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    latest_year, latest_month = target_latest_complete_month(today)
    summer_year, summer_months = summer_selection(latest_year, latest_month)
    OUT_DIR.mkdir(parents=True, exist_ok=True); MAP_DIR.mkdir(parents=True, exist_ok=True); CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target_key = f"{latest_year:04d}-{latest_month:02d}"
    required = [
        MAP_DIR / "temperature_latest_month_absolute.png", MAP_DIR / "temperature_latest_month_anomaly.png",
        MAP_DIR / "precipitation_latest_month_absolute.png", MAP_DIR / "precipitation_latest_month_percent.png",
        MAP_DIR / "temperature_summer_absolute.png", MAP_DIR / "temperature_summer_anomaly.png",
        MAP_DIR / "precipitation_summer_absolute.png", MAP_DIR / "precipitation_summer_percent.png",
    ]
    for layer_key in SOIL_LAYERS:
        for period_id in ("latest_month", "summer"):
            for view in ("absolute", "anomaly", "percentile"):
                required.append(MAP_DIR / f"soil_moisture_{layer_key}_{period_id}_{view}.png")
    for key in [*WATER_VARIABLES.keys(), "water_balance"]:
        for period_id in ("latest_month", "summer"):
            for view in ("absolute", "anomaly", "percentile"):
                required.append(MAP_DIR / f"{key}_{period_id}_{view}.png")
    if INDEX_PATH.exists() and not args.force:
        try:
            existing = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            if existing.get("ready") and int(existing.get("payload_version", 0)) >= 5 and existing.get("latest_month_key") == target_key and all(path.exists() for path in required) and ANALYSIS_PATH.exists():
                print(f"ERA5-Land Europa V5 ist bereits aktuell für {target_key}."); return 0
        except Exception: pass

    needed_by_year: dict[int, set[int]] = {}
    needed_by_year.setdefault(latest_year, set()).update(range(1, latest_month + 1))
    needed_by_year.setdefault(summer_year, set()).update(summer_months)
    client = cds_client()
    current_all: dict[tuple[int, int], tuple] = {}
    current_soil_all: dict[tuple[int, int], dict] = {}
    current_water_all: dict[tuple[int, int], dict] = {}
    for year, month_set in sorted(needed_by_year.items()):
        month_list = sorted(month_set)
        data = load_current_months(client, year, month_list, args.force)
        soil_data = load_current_soil_months(client, year, month_list, args.force)
        water_data = load_current_water_months(client, year, month_list, args.force)
        for month, values in data.items(): current_all[(year, month)] = values
        for month, values in soil_data.items(): current_soil_all[(year, month)] = values
        for month, values in water_data.items(): current_water_all[(year, month)] = values

    climate: dict[int, tuple] = {}; soil_reference: dict[int, dict] = {}; water_reference: dict[int, dict] = {}
    all_needed_months = sorted(set(range(1, latest_month + 1)) | set(summer_months))
    for month in all_needed_months:
        climate[month] = load_climatology_month(client, month, args.force)
        soil_reference[month] = load_soil_reference_month(client, month, args.force)
        water_reference[month] = load_water_reference_month(client, month, args.force)

    latest_current = {latest_month: current_all[(latest_year, latest_month)]}
    latest_climate = {latest_month: climate[latest_month]}
    latest_current_soil = {latest_month: current_soil_all[(latest_year, latest_month)]}
    latest_reference_soil = {latest_month: soil_reference[latest_month]}
    latest_current_water = {latest_month: current_water_all[(latest_year, latest_month)]}
    latest_reference_water = {latest_month: water_reference[latest_month]}
    latest_label = f"{MONTH_NAMES[latest_month]} {latest_year}"
    latest_payload = make_period_maps("latest_month", latest_label, latest_year, [latest_month], latest_current, latest_climate, latest_current_soil, latest_reference_soil, latest_current_water, latest_reference_water)

    summer_current = {month: current_all[(summer_year, month)] for month in summer_months}
    summer_climate = {month: climate[month] for month in summer_months}
    summer_current_soil = {month: current_soil_all[(summer_year, month)] for month in summer_months}
    summer_reference_soil = {month: soil_reference[month] for month in summer_months}
    summer_current_water = {month: current_water_all[(summer_year, month)] for month in summer_months}
    summer_reference_water = {month: water_reference[month] for month in summer_months}
    summer_suffix = "" if summer_months == [6, 7, 8] else " bisher"
    summer_label = f"Sommer {summer_year}{summer_suffix} ({month_range_label(summer_months)})"
    summer_payload = make_period_maps("summer", summer_label, summer_year, summer_months, summer_current, summer_climate, summer_current_soil, summer_reference_soil, summer_current_water, summer_reference_water)

    history_months = sorted({latest_month, *summer_months})
    history_tp = {month: load_history_tp_month(client, month, latest_year, args.force) for month in history_months}
    history_water = {month: load_history_water_month(client, month, latest_year, args.force) for month in history_months}
    analysis_payload = build_analysis_payload(latest_year=latest_year, latest_month=latest_month, summer_year=summer_year, summer_months=summer_months, current_all=current_all, current_soil_all=current_soil_all, current_water_all=current_water_all, climate=climate, soil_reference=soil_reference, water_reference=water_reference, history_tp=history_tp, history_water=history_water)

    payload = {
        "ready": True, "payload_version": 5, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "latest_month_key": target_key,
        "data_through": f"{latest_year:04d}-{latest_month:02d}-{calendar.monthrange(latest_year, latest_month)[1]:02d}", "reference_period": "1991–2020", "dataset": DATASET,
        "source": "Copernicus Climate Change Service / ECMWF · ERA5-Land monthly averaged data", "spatial_resolution": "0,1° (ERA5-Land im CDS; native Modellauflösung ca. 9 km)",
        "coverage": {"north": AREA[0], "west": AREA[1], "south": AREA[2], "east": AREA[3]},
        "availability_note": "V5 verwendet den jüngsten sicher verfügbaren vollständigen Monatsmittel-Datensatz. Ein laufender Sommer umfasst daher nur vollständig verfügbare Monate.",
        "precipitation_note": "ERA5-Land Monatsmittel akkumulierte hydrologische Größen werden als effektive m/Tag bereitgestellt; für Kartensummen wird mit Kalendertagen multipliziert und in mm umgerechnet.",
        "soil_moisture_note": "Bodenfeuchte ist volumetrischer Bodenwassergehalt in m³/m³. Verfügbar sind die vier ERA5-Land-Modellschichten 0–7, 7–28, 28–100 und 100–289 cm.",
        "water_budget_note": "Gesamtverdunstung wird aus ERA5-Land total evaporation mit umgekehrtem Vorzeichen als positive Wasserabgabe dargestellt. Die Wasserbilanz ist Niederschlag minus Gesamtverdunstung (P−E).",
        "analysis": {"file": "era5_land_europe/analysis.json", "grid": analysis_payload["analysis_grid"], "history_start": 1950}, "click_geometry": MAP_CLICK_GEOMETRY,
        "percentile_note": "Perzentile sind empirische Gitterpunkt-Ränge gegenüber den 30 Einzeljahren 1991–2020 für denselben Monat bzw. dieselben Sommermonate.",
        "soil_layers": {key: {"label": meta["label"], "depth_cm": meta["depth_cm"]} for key, meta in SOIL_LAYERS.items()},
        "water_parameters": {key: {"label": meta["label"], "description": meta["description"], "unit": "mm"} for key, meta in WATER_VARIABLES.items()} | {"water_balance": {"label": "Wasserbilanz P−E", "description": "Niederschlag minus Gesamtverdunstung", "unit": "mm"}},
        "periods": {"latest_month": latest_payload, "summer": summer_payload},
    }
    atomic_write_json(INDEX_PATH, payload)
    print(f"ERA5-Land Europa V5 erzeugt: {INDEX_PATH}")
    print(f"Datenstand: {payload['data_through']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
