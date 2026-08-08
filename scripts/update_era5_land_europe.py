#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import json
import math
import os
import shutil
import tempfile
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

TEMP_ALIASES = ("t2m", "2m_temperature", "temperature_2m")
PRECIP_ALIASES = ("tp", "total_precipitation", "precipitation")
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
    print(f"CDS request: years {years[0]}–{years[-1]}, months {months}")
    client.retrieve(DATASET, request, str(target))


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
    print(f"CDS soil-moisture request (4 layers): years {years[0]}–{years[-1]}, months {months}")
    client.retrieve(DATASET, request, str(target))


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


def load_soil_reference_month(client: cdsapi.Client, month: int, force: bool) -> dict:
    """Return the 30 individual 1991–2020 monthly fields for every soil layer.

    Keeping the individual years allows true grid-cell percentiles and also permits
    incomplete-season percentiles (e.g. June–July) to be built year by year.
    """
    ref_file = CACHE_DIR / f"soil_reference_v3_1991_2020_{month:02d}.nc"
    if force and ref_file.exists():
        ref_file.unlink()

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

    raw_file = CACHE_DIR / f"raw_soil_reference_v3_{month:02d}.nc"
    if raw_file.exists():
        raw_file.unlink()
    ref_years = np.arange(REFERENCE_START, REFERENCE_END + 1, dtype=int)
    request_soil_monthly_file(client, ref_years.tolist(), [month], raw_file)

    ds = open_download(raw_file)
    lat_name, lon_name = spatial_names(ds)
    ds = normalize_lon(ds, lon_name)
    lat = np.asarray(ds[lat_name].values, dtype=float)
    lon = np.asarray(ds[lon_name].values, dtype=float)

    layer_arrays: dict[str, np.ndarray] = {}
    detected_years: np.ndarray | None = None
    for layer_key, meta in SOIL_LAYERS.items():
        soil_name = variable_name(ds, meta["aliases"])
        soil_da = ds[soil_name]
        sdim = time_dim(soil_da, lat_name, lon_name)
        if sdim is None or soil_da.sizes[sdim] != len(ref_years):
            raise RuntimeError(
                f"Zeitdimension der Referenz für {layer_key} hat nicht {len(ref_years)} Felder."
            )

        # Put the time axis first, regardless of the NetCDF dimension order.
        soil_da = soil_da.transpose(sdim, lat_name, lon_name)
        values = np.asarray(soil_da.values, dtype=np.float32)

        # CDS normally returns the request chronologically. If a datetime coordinate
        # exists, use it to explicitly sort/reindex to 1991…2020.
        years_here = None
        try:
            coord = ds[sdim]
            years_here = np.asarray(coord.dt.year.values, dtype=int)
        except Exception:
            years_here = None
        if years_here is not None and years_here.size == ref_years.size and set(years_here.tolist()) == set(ref_years.tolist()):
            index = [int(np.where(years_here == target_year)[0][0]) for target_year in ref_years]
            values = values[index, :, :]
            detected_years = ref_years
        else:
            detected_years = ref_years
        layer_arrays[layer_key] = values

    encoding = {layer_key: {"zlib": True, "complevel": 3, "dtype": "float32"} for layer_key in SOIL_LAYERS}
    out = xr.Dataset(
        {layer_key: (("year", "latitude", "longitude"), layer_arrays[layer_key]) for layer_key in SOIL_LAYERS},
        coords={"year": detected_years, "latitude": lat, "longitude": lon},
        attrs={
            "reference_period": "1991-2020",
            "month": month,
            "description": "ERA5-Land monthly volumetric soil water; all four model soil layers",
        },
    )
    out.to_netcdf(ref_file, encoding=encoding)
    ds.close()
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


def load_climatology_month(client: cdsapi.Client, month: int, force: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    clim_file = CACHE_DIR / f"climatology_1991_2020_{month:02d}.nc"
    if force and clim_file.exists():
        clim_file.unlink()
    if clim_file.exists():
        ds = xr.open_dataset(clim_file)
        lat = np.asarray(ds["latitude"].values, dtype=float)
        lon = np.asarray(ds["longitude"].values, dtype=float)
        temp = np.asarray(ds["temperature_c"].values, dtype=float)
        precip = np.asarray(ds["precipitation_mm"].values, dtype=float)
        ds.close()
        return lat, lon, temp, precip

    raw_file = CACHE_DIR / f"raw_climatology_{month:02d}.nc"
    if raw_file.exists():
        raw_file.unlink()
    request_monthly_file(client, list(range(REFERENCE_START, REFERENCE_END + 1)), [month], raw_file)
    ds = open_download(raw_file)
    lat_name, lon_name = spatial_names(ds)
    ds = normalize_lon(ds, lon_name)
    temp_name = variable_name(ds, TEMP_ALIASES)
    precip_name = variable_name(ds, PRECIP_ALIASES)
    temp_da = ds[temp_name]
    precip_da = ds[precip_name]
    tdim = time_dim(temp_da, lat_name, lon_name)
    pdim = time_dim(precip_da, lat_name, lon_name)
    if tdim is None or pdim is None:
        raise RuntimeError("Zeitdimension für die 30-jährige Klimatologie fehlt.")

    temp_c = temp_da - 273.15
    temp_clim = temp_c.mean(tdim, skipna=True)

    # Convert every year's effective daily accumulation to the actual monthly total before averaging.
    # February varies by leap year, all other months use a fixed number of days.
    if month == 2:
        years = list(range(REFERENCE_START, REFERENCE_END + 1))
        days = xr.DataArray([calendar.monthrange(y, month)[1] for y in years], dims=[pdim])
        precip_monthly = precip_da * days * 1000.0
    else:
        precip_monthly = precip_da * calendar.monthrange(2001, month)[1] * 1000.0
    precip_clim = precip_monthly.mean(pdim, skipna=True)

    lat = np.asarray(ds[lat_name].values, dtype=float)
    lon = np.asarray(ds[lon_name].values, dtype=float)
    out = xr.Dataset(
        {
            "temperature_c": (("latitude", "longitude"), np.asarray(temp_clim.squeeze().values, dtype=np.float32)),
            "precipitation_mm": (("latitude", "longitude"), np.asarray(precip_clim.squeeze().values, dtype=np.float32)),
        },
        coords={"latitude": lat, "longitude": lon},
        attrs={"reference_period": "1991-2020", "month": month},
    )
    out.to_netcdf(clim_file)
    ds.close()
    try:
        raw_file.unlink()
    except FileNotFoundError:
        pass
    return lat, lon, np.asarray(out["temperature_c"].values, dtype=float), np.asarray(out["precipitation_mm"].values, dtype=float)


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
    ax = plt.axes(projection=ccrs.PlateCarree())
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
    elif kind == "soil_percentile":
        # Dry classes on the low-percentile side, wet classes on the high side.
        percentile_boundaries = [0, 5, 10, 20, 30, 70, 80, 90, 95, 100.0001]
        percentile_ticks = [2.5, 7.5, 15, 25, 50, 75, 85, 92.5, 97.5]
        percentile_ticklabels = ["≤5", "5–10", "10–20", "20–30", "30–70", "70–80", "80–90", "90–95", ">95"]
        cmap = plt.get_cmap("BrBG", len(percentile_boundaries) - 1)
        kwargs.update(norm=BoundaryNorm(percentile_boundaries, cmap.N, clip=True))
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

    cbar_kwargs = {"orientation": "horizontal", "fraction": 0.047, "pad": 0.075, "aspect": 42}
    if percentile_boundaries is not None:
        cbar_kwargs.update(boundaries=percentile_boundaries, ticks=percentile_ticks, spacing="proportional")
    cbar = plt.colorbar(mesh, ax=ax, **cbar_kwargs)
    cbar.set_label(unit, fontsize=10)
    cbar.ax.tick_params(labelsize=8)
    if percentile_ticklabels is not None:
        cbar.ax.set_xticklabels(percentile_ticklabels)

    fig.suptitle(title, x=0.075, y=0.97, ha="left", va="top", fontsize=17, fontweight="bold")
    fig.text(0.075, 0.925, subtitle, ha="left", va="top", fontsize=10, color="#56636a")
    fig.text(0.075, 0.025, "Quelle: Copernicus Climate Change Service / ECMWF · ERA5-Land · 0,1° · Landflächen",
             ha="left", va="bottom", fontsize=8, color="#68757c")
    plt.savefig(filename, bbox_inches="tight", facecolor="white")
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
                     climate: dict, current_soil: dict, reference_soil: dict) -> dict:
    lat, lon = current[months[0]][0], current[months[0]][1]
    current_temp = combine_temperature({m: current[m][2] for m in months}, year, months)
    climate_temp = combine_temperature({m: climate[m][2] for m in months}, 2001, months)
    current_precip = combine_precipitation({m: current[m][3] for m in months}, months)
    climate_precip = combine_precipitation({m: climate[m][3] for m in months}, months)

    temp_anom = current_temp - climate_temp
    precip_pct = np.where(climate_precip > 1.0, current_precip / climate_precip * 100.0, np.nan)

    files = {
        "temp_absolute": MAP_DIR / f"temperature_{period_id}_absolute.png",
        "temp_anomaly": MAP_DIR / f"temperature_{period_id}_anomaly.png",
        "precip_absolute": MAP_DIR / f"precipitation_{period_id}_absolute.png",
        "precip_percent": MAP_DIR / f"precipitation_{period_id}_percent.png",
    }

    render_map(current_temp, lat, lon,
               title=f"ERA5-Land Europa · 2-m-Temperatur · {period_label}",
               subtitle="Absolutwert · Landflächen", unit="°C", filename=files["temp_absolute"], kind="temp_absolute")
    render_map(temp_anom, lat, lon,
               title=f"ERA5-Land Europa · Temperaturabweichung · {period_label}",
               subtitle="gegenüber 1991–2020 · Landflächen", unit="K", filename=files["temp_anomaly"], kind="temp_anomaly")
    render_map(current_precip, lat, lon,
               title=f"ERA5-Land Europa · Niederschlag · {period_label}",
               subtitle="Niederschlagssumme · Landflächen", unit="mm", filename=files["precip_absolute"], kind="precip_absolute")
    render_map(precip_pct, lat, lon,
               title=f"ERA5-Land Europa · Niederschlag · {period_label}",
               subtitle="Prozent vom Mittel 1991–2020 · Landflächen", unit="% vom Mittel", filename=files["precip_percent"], kind="precip_percent")

    def rel(path: Path) -> str:
        return path.relative_to(ROOT).as_posix()

    stats_temp_current = weighted_mean(current_temp, lat)
    stats_temp_ref = weighted_mean(climate_temp, lat)
    stats_precip_current = weighted_mean(current_precip, lat)
    stats_precip_ref = weighted_mean(climate_precip, lat)

    soil_layers_payload: dict[str, dict] = {}
    for layer_key, meta in SOIL_LAYERS.items():
        current_soil_field = combine_soil_moisture(
            {m: current_soil[m]["layers"][layer_key] for m in months}, year, months
        )
        reference_samples = combine_reference_soil(reference_soil, layer_key, months)
        climate_soil_field = np.nanmean(reference_samples, axis=0)
        soil_anom = current_soil_field - climate_soil_field
        soil_percentile = soil_percentile_field(current_soil_field, reference_samples)

        layer_files = {
            "absolute": MAP_DIR / f"soil_moisture_{layer_key}_{period_id}_absolute.png",
            "anomaly": MAP_DIR / f"soil_moisture_{layer_key}_{period_id}_anomaly.png",
            "percentile": MAP_DIR / f"soil_moisture_{layer_key}_{period_id}_percentile.png",
        }
        render_map(current_soil_field, lat, lon,
                   title=f"ERA5-Land Europa · Bodenfeuchte {meta['label']} · {period_label}",
                   subtitle="Volumetrischer Bodenwassergehalt · Landflächen", unit="m³/m³",
                   filename=layer_files["absolute"], kind="soil_absolute")
        render_map(soil_anom, lat, lon,
                   title=f"ERA5-Land Europa · Bodenfeuchteabweichung {meta['label']} · {period_label}",
                   subtitle="gegenüber 1991–2020 · Landflächen", unit="m³/m³",
                   filename=layer_files["anomaly"], kind="soil_anomaly")
        render_map(soil_percentile, lat, lon,
                   title=f"ERA5-Land Europa · Bodenfeuchte-Perzentil {meta['label']} · {period_label}",
                   subtitle="Einordnung 1991–2020 · P≤20 trocken · P≥80 feucht", unit="Perzentilklasse 1991–2020",
                   filename=layer_files["percentile"], kind="soil_percentile")

        stats_current = weighted_mean(current_soil_field, lat)
        stats_reference = weighted_mean(climate_soil_field, lat)
        valid_pct = np.isfinite(soil_percentile)
        soil_layers_payload[layer_key] = {
            "label": meta["label"],
            "depth_cm": meta["depth_cm"],
            "absolute": {"file": rel(layer_files["absolute"]), "unit": "m³/m³", "label": f"Bodenfeuchte {meta['label']}"},
            "anomaly": {"file": rel(layer_files["anomaly"]), "unit": "m³/m³", "label": "Abweichung 1991–2020"},
            "percentile": {"file": rel(layer_files["percentile"]), "unit": "Perzentil", "label": "Perzentil / Dürreklasse 1991–2020"},
            "stats": {
                "current": stats_current,
                "reference": stats_reference,
                "difference": None if stats_current is None or stats_reference is None else stats_current - stats_reference,
                "dry_area_percent": weighted_fraction(soil_percentile <= 20.0, valid_pct, lat),
                "very_dry_area_percent": weighted_fraction(soil_percentile <= 10.0, valid_pct, lat),
                "wet_area_percent": weighted_fraction(soil_percentile >= 80.0, valid_pct, lat),
                "very_wet_area_percent": weighted_fraction(soil_percentile >= 90.0, valid_pct, lat),
            },
        }

    # Keep layer-1 fields at the old V2 location so a still-cached V2 frontend
    # continues to display the surface-soil maps during deployment.
    soil_payload = {"layers": soil_layers_payload, **soil_layers_payload["layer1"]}

    return {
        "id": period_id,
        "label": period_label,
        "year": year,
        "months": months,
        "temperature": {
            "absolute": {"file": rel(files["temp_absolute"]), "unit": "°C", "label": "Temperatur"},
            "anomaly": {"file": rel(files["temp_anomaly"]), "unit": "K", "label": "Abweichung 1991–2020"},
            "stats": {
                "current": stats_temp_current,
                "reference": stats_temp_ref,
                "difference": None if stats_temp_current is None or stats_temp_ref is None else stats_temp_current - stats_temp_ref,
            },
        },
        "precipitation": {
            "absolute": {"file": rel(files["precip_absolute"]), "unit": "mm", "label": "Niederschlag"},
            "percent": {"file": rel(files["precip_percent"]), "unit": "%", "label": "Prozent vom Mittel 1991–2020"},
            "stats": {
                "current": stats_precip_current,
                "reference": stats_precip_ref,
                "percent": None if not stats_precip_ref else stats_precip_current / stats_precip_ref * 100.0,
            },
        },
        "soil_moisture": soil_payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ERA5-Land Europakarten für das Climate Dashboard erzeugen.")
    parser.add_argument("--force", action="store_true", help="CDS-Daten und Karten auch für denselben Zielmonat neu erzeugen")
    parser.add_argument("--today", help="Testdatum YYYY-MM-DD")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    latest_year, latest_month = target_latest_complete_month(today)
    summer_year, summer_months = summer_selection(latest_year, latest_month)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MAP_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    target_key = f"{latest_year:04d}-{latest_month:02d}"
    required = [
        MAP_DIR / "temperature_latest_month_absolute.png",
        MAP_DIR / "temperature_latest_month_anomaly.png",
        MAP_DIR / "precipitation_latest_month_absolute.png",
        MAP_DIR / "precipitation_latest_month_percent.png",
        MAP_DIR / "temperature_summer_absolute.png",
        MAP_DIR / "temperature_summer_anomaly.png",
        MAP_DIR / "precipitation_summer_absolute.png",
        MAP_DIR / "precipitation_summer_percent.png",
    ]
    for layer_key in SOIL_LAYERS:
        for period_id in ("latest_month", "summer"):
            for view in ("absolute", "anomaly", "percentile"):
                required.append(MAP_DIR / f"soil_moisture_{layer_key}_{period_id}_{view}.png")

    if INDEX_PATH.exists() and not args.force:
        try:
            existing = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            if (
                existing.get("ready")
                and int(existing.get("payload_version", 0)) >= 3
                and existing.get("latest_month_key") == target_key
                and all(path.exists() for path in required)
            ):
                print(f"ERA5-Land Europa V3 ist bereits aktuell für {target_key}.")
                return 0
        except Exception:
            pass

    needed_by_year: dict[int, set[int]] = {}
    needed_by_year.setdefault(latest_year, set()).add(latest_month)
    needed_by_year.setdefault(summer_year, set()).update(summer_months)

    client = cds_client()
    current_all: dict[tuple[int, int], tuple] = {}
    current_soil_all: dict[tuple[int, int], dict] = {}
    for year, month_set in sorted(needed_by_year.items()):
        month_list = sorted(month_set)
        data = load_current_months(client, year, month_list, args.force)
        soil_data = load_current_soil_months(client, year, month_list, args.force)
        for month, values in data.items():
            current_all[(year, month)] = values
        for month, values in soil_data.items():
            current_soil_all[(year, month)] = values

    climate: dict[int, tuple] = {}
    soil_reference: dict[int, dict] = {}
    all_needed_months = sorted({latest_month, *summer_months})
    for month in all_needed_months:
        climate[month] = load_climatology_month(client, month, args.force)
        soil_reference[month] = load_soil_reference_month(client, month, args.force)

    latest_current = {latest_month: current_all[(latest_year, latest_month)]}
    latest_climate = {latest_month: climate[latest_month]}
    latest_current_soil = {latest_month: current_soil_all[(latest_year, latest_month)]}
    latest_reference_soil = {latest_month: soil_reference[latest_month]}
    latest_label = f"{MONTH_NAMES[latest_month]} {latest_year}"
    latest_payload = make_period_maps(
        "latest_month", latest_label, latest_year, [latest_month],
        latest_current, latest_climate, latest_current_soil, latest_reference_soil,
    )

    summer_current = {month: current_all[(summer_year, month)] for month in summer_months}
    summer_climate = {month: climate[month] for month in summer_months}
    summer_current_soil = {month: current_soil_all[(summer_year, month)] for month in summer_months}
    summer_reference_soil = {month: soil_reference[month] for month in summer_months}
    summer_suffix = "" if summer_months == [6, 7, 8] else " bisher"
    summer_label = f"Sommer {summer_year}{summer_suffix} ({month_range_label(summer_months)})"
    summer_payload = make_period_maps(
        "summer", summer_label, summer_year, summer_months,
        summer_current, summer_climate, summer_current_soil, summer_reference_soil,
    )

    payload = {
        "ready": True,
        "payload_version": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest_month_key": target_key,
        "data_through": f"{latest_year:04d}-{latest_month:02d}-{calendar.monthrange(latest_year, latest_month)[1]:02d}",
        "reference_period": "1991–2020",
        "dataset": DATASET,
        "source": "Copernicus Climate Change Service / ECMWF · ERA5-Land monthly averaged data",
        "spatial_resolution": "0,1° (ERA5-Land im CDS; native Modellauflösung ca. 9 km)",
        "coverage": {"north": AREA[0], "west": AREA[1], "south": AREA[2], "east": AREA[3]},
        "availability_note": "V3 verwendet den jüngsten sicher verfügbaren vollständigen Monatsmittel-Datensatz. Ein laufender Sommer umfasst daher nur vollständig verfügbare Monate.",
        "precipitation_note": "ERA5-Land Monatsmittel akkumulierte hydrologische Größen werden als effektive m/Tag bereitgestellt; für die Kartensummen wurde mit der Zahl der Kalendertage multipliziert und in mm umgerechnet.",
        "soil_moisture_note": "Bodenfeuchte ist volumetrischer Bodenwassergehalt in m³/m³. Verfügbar sind die vier ERA5-Land-Modellschichten 0–7, 7–28, 28–100 und 100–289 cm.",
        "percentile_note": "Bodenfeuchte-Perzentile sind empirische Gitterpunkt-Ränge gegenüber den 30 Einzeljahren 1991–2020 für denselben Monat bzw. dieselben Sommermonate. P≤20 wird als trocken, P≤10 als sehr trocken, P≥80 als feucht eingeordnet.",
        "soil_layers": {key: {"label": meta["label"], "depth_cm": meta["depth_cm"]} for key, meta in SOIL_LAYERS.items()},
        "periods": {
            "latest_month": latest_payload,
            "summer": summer_payload,
        },
    }
    atomic_write_json(INDEX_PATH, payload)
    print(f"ERA5-Land Europa V3 erzeugt: {INDEX_PATH}")
    print(f"Datenstand: {payload['data_through']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
