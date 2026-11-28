"""Full-resolution MUR v4.1 via NOAA CoastWatch (same NASA JPL product)."""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import quote

import numpy as np
import requests
import xarray as xr

from .config import Region
from .sources import _write_response_atomic

BASE = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.nc"
VARIABLES = ("analysed_sst", "sea_ice_fraction")


def _tile_query(day, west, south, east, north):
    # ERDDAP coordinates are inclusive. No stride reduction.
    subset = (f"[({day.isoformat()}T09:00:00Z)]"
              f"[({south:.2f}):1:({north:.2f})]"
              f"[({west:.2f}):1:({east:.2f})]")
    return BASE + "?" + quote(",".join(var + subset for var in VARIABLES), safe="(),:")


def _validated_tile(raw, day, lat, lon):
    ds = raw.rename({k: v for k, v in (("latitude", "lat"), ("longitude", "lon"))
                     if k in raw.dims})
    if ds.sizes.get("time") != 1 or str(ds.time.values[0])[:10] != day.isoformat():
        raise RuntimeError("CoastWatch returned a different date.")
    if (ds.sizes.get("lat") != len(lat) or ds.sizes.get("lon") != len(lon)
            or not np.allclose(ds.lat.values, lat, atol=0.00005, rtol=0)
            or not np.allclose(ds.lon.values, lon, atol=0.00005, rtol=0)):
        raise RuntimeError("CoastWatch returned incomplete or non-native resolution grid.")
    if not all(v in ds for v in VARIABLES):
        raise RuntimeError("CoastWatch missing SST or ice fraction.")
    out = ds[list(VARIABLES)].assign_coords(lat=lat, lon=lon)
    for var in VARIABLES:
        attrs = dict(out[var].attrs)
        out[var] = out[var].astype("float32")
        out[var].attrs = attrs
    if str(out.analysed_sst.attrs.get("units", "")).lower() not in ("degree_c", "degrees_c", "celsius", "k", "kelvin"):
        raise RuntimeError("Unexpected CoastWatch SST units.")
    return out.load()


def download_mur_mirror(day: date, region: Region, destination: Path, session=requests) -> Path:
    west, south, east, north = region.download_bounds
    # Native 0.01-degree grid, nonoverlapping latitude strips, bounded response sizes.
    ilat = np.arange(round(south * 100), round(north * 100) + 1)
    lon = np.arange(round(west * 100), round(east * 100) + 1) / 100.
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".nc.part")
    parts = []
    try:
        with tempfile.TemporaryDirectory(prefix="mur-coastwatch-", dir=destination.parent) as tmp:
            for start in range(0, len(ilat), 500):
                lat = ilat[start:start + 500] / 100.
                url = _tile_query(day, lon[0], lat[0], lon[-1], lat[-1])
                path = Path(tmp) / f"tile-{start}.nc"
                response = session.get(url, stream=True, timeout=(20, 180))
                try:
                    _write_response_atomic(response, path)
                finally:
                    close = getattr(response, "close", None)
                    if callable(close):
                        close()
                with xr.open_dataset(path) as raw:
                    parts.append(_validated_tile(raw, day, lat, lon))
                path.unlink()
                print(f"{day} {region.id}: CoastWatch native MUR {lat[0]:.2f}–{lat[-1]:.2f} N", flush=True)
            result = xr.concat(parts, dim="lat", data_vars="all", coords="minimal", compat="override")
            if result.sizes.get("lat") != len(ilat):
                raise RuntimeError("Incomplete CoastWatch latitude coverage.")
            result.attrs["source"] = "NASA JPL MUR v4.1 via NOAA CoastWatch ERDDAP"
            result.drop_encoding().to_netcdf(temporary, engine="netcdf4",
                encoding={v: {"zlib": True, "complevel": 2} for v in VARIABLES})
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
