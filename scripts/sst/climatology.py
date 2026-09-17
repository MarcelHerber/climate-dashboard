from __future__ import annotations

import calendar
from datetime import date

import numpy as np
import xarray as xr


def _lat_lon_names(array: xr.DataArray) -> tuple[str, str]:
    lat_name = next((name for name in ("lat", "latitude") if name in array.dims or name in array.coords), None)
    lon_name = next((name for name in ("lon", "longitude") if name in array.dims or name in array.coords), None)
    if not lat_name or not lon_name:
        raise RuntimeError(f"SST-Feld ohne erkennbare Breiten-/Längengrade: dims={array.dims}")
    return lat_name, lon_name


def _standardize_lat_lon(array: xr.DataArray) -> xr.DataArray:
    lat_name, lon_name = _lat_lon_names(array)
    rename = {}
    if lat_name != "lat":
        rename[lat_name] = "lat"
    if lon_name != "lon":
        rename[lon_name] = "lon"
    return array.rename(rename) if rename else array


def _sst_variable(normals: xr.Dataset) -> xr.DataArray:
    for name in ("sst_mean", "sst", "sea_surface_temperature"):
        if name in normals.data_vars:
            return _standardize_lat_lon(normals[name])

    excluded = ("std", "count", "min", "max", "extreme")
    candidates: list[xr.DataArray] = []
    for name, variable in normals.data_vars.items():
        lower = name.lower()
        if "sst" not in lower or any(token in lower for token in excluded):
            continue
        try:
            candidates.append(_standardize_lat_lon(variable))
        except RuntimeError:
            continue
    if len(candidates) != 1:
        raise RuntimeError(f"NOAA-SST-Variable nicht eindeutig: {[v.name for v in candidates]}")
    return candidates[0]


def select_daily_normal(normals: xr.Dataset, day: date) -> tuple[xr.DataArray, str]:
    field = _sst_variable(normals)
    non_spatial_dims = [dim for dim in field.dims if dim not in {"lat", "lon"}]
    if len(non_spatial_dims) != 1:
        raise RuntimeError(f"Tagesnormalfeld benötigt genau eine Zeitdimension: {field.dims}")
    time_dim = non_spatial_dims[0]
    count = int(field.sizes[time_dim])
    if count not in {365, 366}:
        raise RuntimeError(f"Unerwartete Zahl von Klimatologietagen: {count}")

    doy = day.timetuple().tm_yday
    if count == 366:
        return field.isel({time_dim: doy - 1}).drop_vars(time_dim, errors="ignore"), "daily_normal"

    if day.month == 2 and day.day == 29:
        feb28 = field.isel({time_dim: 58})
        mar1 = field.isel({time_dim: 59})
        selected = (feb28 + mar1) / 2.0
        return selected.drop_vars(time_dim, errors="ignore"), "feb29_interpolated"

    index = doy - 1
    if calendar.isleap(day.year) and (day.month, day.day) > (2, 29):
        index -= 1
    return field.isel({time_dim: index}).drop_vars(time_dim, errors="ignore"), "daily_normal"


def regrid_normal(normal: xr.DataArray, target_lat: xr.DataArray, target_lon: xr.DataArray) -> xr.DataArray:
    normal = _standardize_lat_lon(normal)
    normalized_lon = ((normal["lon"] + 180.0) % 360.0) - 180.0
    normal = normal.assign_coords(lon=normalized_lon).sortby("lon").sortby("lat")

    target_lat_values = np.asarray(target_lat.values, dtype=float)
    target_lon_values = ((np.asarray(target_lon.values, dtype=float) + 180.0) % 360.0) - 180.0
    lat_target = xr.DataArray(target_lat_values, dims="lat", coords={"lat": target_lat_values})
    lon_target = xr.DataArray(target_lon_values, dims="lon", coords={"lon": target_lon_values})
    return normal.interp(lat=lat_target, lon=lon_target, method="linear")
