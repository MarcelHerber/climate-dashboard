"""Permanent calendar-day NOAA PSL 1991–2020 reference archive for MUR maps."""
from __future__ import annotations

import os
import tempfile
import time
from datetime import date
from pathlib import Path

import numpy as np
import requests
import xarray as xr

from .ocean_sources import download_oisst_normal_subset
from .sources import _oisst_erddap_index_ranges, _standardize_oisst_dataset


def _crop_and_validate(field: xr.DataArray) -> xr.DataArray:
    lat_range, lon_ranges = _oisst_erddap_index_ranges()
    expected_lat = -89.875 + np.arange(lat_range[0], lat_range[1] + 1) * .25
    indices = np.concatenate([np.arange(a, b + 1) for a, b in lon_ranges])
    expected_lon = np.sort((.125 + indices * .25 + 180.) % 360. - 180.)
    dataset = _standardize_oisst_dataset(field.to_dataset(name="sst"))
    field = dataset.sst.sel(lat=slice(expected_lat[0], expected_lat[-1]),
                            lon=slice(expected_lon[0], expected_lon[-1]))
    if set(field.dims) != {"lat", "lon"}:
        raise RuntimeError("NOAA Tagesnormalfeld hat unerwartete Dimensionen.")
    if (field.sizes["lat"] != len(expected_lat) or field.sizes["lon"] != len(expected_lon)
            or not np.allclose(field.lat.values, expected_lat)
            or not np.allclose(field.lon.values, expected_lon)):
        raise RuntimeError("NOAA Tagesnormalfeld: unvollständiges Europa-Gitter.")
    field = field.transpose("lat", "lon").load()
    finite = field.values[np.isfinite(field.values)]
    if not finite.size or np.min(finite) < -5 or np.max(finite) > 45:
        raise RuntimeError("NOAA Tagesnormalfeld: unplausible SST-Werte.")
    return field


def _valid(path: Path, key: str, method: str) -> bool:
    if not path.is_file():
        return False
    try:
        with xr.open_dataset(path, decode_times=False) as ds:
            if (ds.attrs.get("normal_month_day") != key
                    or ds.attrs.get("reference_period") != "1991-2020"
                    or ds.attrs.get("reference_method") != method):
                return False
            _crop_and_validate(ds.sst)
        return True
    except (OSError, ValueError, KeyError, RuntimeError):
        return False


def ensure_daily_normal(day: date, root: Path, session=requests) -> Path:
    key = day.strftime("%m-%d")
    leap = key == "02-29"
    method = "feb29_interpolated" if leap else "daily_normal"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{key}.nc"
    if _valid(target, key, method):
        print(f"NOAA Referenz {key}: dauerhaft archiviert, kein Download.", flush=True)
        return target
    temporary = target.with_suffix(".nc.part")
    try:
        if leap:
            # Preserve the historic strict arithmetic interpolation (NaN propagates).
            feb = ensure_daily_normal(date(2001, 2, 28), root, session=session)
            mar = ensure_daily_normal(date(2001, 3, 1), root, session=session)
            with xr.open_dataset(feb, decode_times=False) as a, xr.open_dataset(mar, decode_times=False) as b:
                field = ((a.sst + b.sst) / 2.).load()
        else:
            with tempfile.TemporaryDirectory(prefix="sst-normal-day-") as tmp:
                raw = Path(tmp) / "normal.nc"
                for attempt in range(2):
                    try:
                        download_oisst_normal_subset(day, raw, session=session, include_europe=True)
                        with xr.open_dataset(raw, decode_times=False) as ds:
                            field = _crop_and_validate(ds.sst)
                        break
                    except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError, OSError):
                        raw.unlink(missing_ok=True)
                        if attempt:
                            raise
                        time.sleep(30)
        ds = field.drop_encoding().to_dataset(name="sst")
        ds.attrs.update(normal_month_day=key, reference_period="1991-2020",
                        reference_method=method, source="NOAA PSL OISST daily climatology")
        ds.to_netcdf(temporary, engine="netcdf4",
                     encoding={"sst": {"zlib": True, "complevel": 4}})
        if not _valid(temporary, key, method):
            raise RuntimeError("NOAA Tagesnormalfeld: Archivvalidierung fehlgeschlagen.")
        os.replace(temporary, target)
        print(f"NOAA Referenz {key}: geprüft und dauerhaft gespeichert.", flush=True)
    finally:
        temporary.unlink(missing_ok=True)
    return target
