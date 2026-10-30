from __future__ import annotations

import calendar
import os
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import requests
import xarray as xr

from .config import OCEAN_REGIONS, NOAA_NORMALS_NCSS

# Kleine, einzeln archivierte OISST-v2.1-Tagesdateien direkt von NOAA NCEI.
# Entlastet den PSL-THREDDS/NCSS-Server, der bei zwei parallelen
# historischen Tagesjobs mit HTTP 429 / HTTP 500 reagiert hat.
NOAA_OISST_DAILY_NCEI = (
    "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/"
    "v2.1/access/avhrr/{yearmonth}/oisst-avhrr-v02r01.{day}.nc"
)
# Separate NOAA-ERDDAP-Instanz für die tägliche Klimatologie 1991–2020;
# keine wiederholten OPeNDAP-Abfragen gegen den überlasteten PSL-Server.
# Verified NOAA/PSL 0.25-degree 1991-2020 daily climatology (365 days).
# The old NEFSC ERDDAP dataset ID now responds HTTP 404.
NOAA_NORMALS_OPENDAP = (
    "https://psl.noaa.gov/thredds/dodsC/Datasets/"
    "noaa.oisst.v2.highres/sst.day.mean.ltm.1991-2020.nc"
)
NOAA_NORMALS_ERDDAP = (
    "https://comet.nefsc.noaa.gov/erddap/griddap/"
    "noaa_psl_4e02_3713_6583.nc?sst"
)
OISST_GRID_LAT_START = -89.875
OISST_GRID_LON_START = 0.125
OISST_GRID_STEP = 0.25
OISST_GRID_LAT_COUNT = 720
OISST_GRID_LON_COUNT = 1440
OISST_MAX_ATTEMPTS = 5
OISST_RETRY_DELAYS = (5, 15, 30, 60)
OISST_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def ocean_union_bounds() -> tuple[float, float, float, float]:
    bounds = [region.download_bounds for region in OCEAN_REGIONS.values()]
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def _write_response_atomic(response, destination: Path) -> Path:
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type or "json" in content_type:
        raise RuntimeError(f"Unerwarteter NOAA-Antworttyp statt NetCDF: {content_type or 'unbekannt'}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with temporary.open("wb") as handle:
            wrote = 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                wrote += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if wrote == 0:
            raise RuntimeError("NOAA-OISST-Download ist leer.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _get_with_retry(session, url: str, **kwargs):
    for attempt in range(OISST_MAX_ATTEMPTS):
        try:
            response = session.get(url, **kwargs)
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = status is None or status in OISST_RETRYABLE_STATUS
            if attempt >= OISST_MAX_ATTEMPTS - 1 or not retryable:
                raise
            time.sleep(OISST_RETRY_DELAYS[attempt])
            continue

        status = int(getattr(response, "status_code", 200))
        if status in OISST_RETRYABLE_STATUS and attempt < OISST_MAX_ATTEMPTS - 1:
            # 429 ist eine explizite Server-Drosselung: nicht im Sekundentakt
            # erneut anfragen. Wenn NOAA Retry-After setzt, respektieren.
            retry_after = response.headers.get("Retry-After", "")
            close = getattr(response, "close", None)
            if callable(close):
                close()
            if status == 429:
                try:
                    wait = max(60, min(300, int(retry_after)))
                except (ValueError, TypeError):
                    wait = (60, 120, 180, 240)[attempt]
                print(f"NOAA Rate-Limit HTTP 429; neuer Versuch nach {wait} Sekunden.", flush=True)
            else:
                wait = OISST_RETRY_DELAYS[attempt]
            time.sleep(wait)
            continue
        return response
    raise RuntimeError("NOAA-OISST-Anfrage blieb nach allen Wiederholungen erfolglos.")


def _ncei_daily_url(day: date, *, preliminary: bool = False) -> str:
    url = NOAA_OISST_DAILY_NCEI.format(
        yearmonth=f"{day:%Y%m}",
        day=f"{day:%Y%m%d}",
    )
    # Replace only the filename suffix: replacing every ".nc" also corrupts www.ncei.noaa.gov.
    return url[:-3] + "_preliminary.nc" if preliminary else url


def _ncei_daily_response(day: date, session=requests, *, timeout: int = 90):
    # NOAA liefert die jüngsten etwa zwei Wochen mit _preliminary.nc;
    # ältere Tage als endgültige .nc. Während des Übergangs beide prüfen.
    recent = day >= date.today() - timedelta(days=21)
    variants = (True, False) if recent else (False, True)
    for preliminary in variants:
        response = _get_with_retry(
            session,
            _ncei_daily_url(day, preliminary=preliminary),
            stream=True,
            timeout=timeout,
        )
        if response.status_code == 404:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            continue
        return response
    return None


def oisst_date_available(day: date, session=requests) -> bool:
    response = _ncei_daily_response(day, session=session, timeout=90)
    if response is None:
        return False
    try:
        if response.status_code == 400:
            return False
        response.raise_for_status()
        return True
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def latest_available_oisst_date(today: date, lookback_days: int = 14, session=requests) -> date:
    from datetime import timedelta

    for offset in range(lookback_days + 1):
        candidate = today - timedelta(days=offset)
        if oisst_date_available(candidate, session=session):
            return candidate
    raise RuntimeError(
        f"Kein NOAA-OISST-Tag zwischen {today - timedelta(days=lookback_days)} und {today} gefunden."
    )


def download_oisst_daily_subset(
    day: date,
    destination: Path,
    session=requests,
) -> Path:
    response = _ncei_daily_response(day, session=session, timeout=180)
    if response is None:
        raise FileNotFoundError(f"NOAA-OISST-Datei für {day.isoformat()} nicht verfügbar.")
    try:
        return _write_response_atomic(response, destination)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _normal_time_indices(day: date) -> tuple[int, int]:
    if day.month == 2 and day.day == 29:
        return 58, 59
    index = day.timetuple().tm_yday - 1
    if calendar.isleap(day.year) and (day.month, day.day) > (2, 29):
        index -= 1
    return index, index


def _standardize_subset(dataset: xr.Dataset) -> xr.Dataset:
    rename = {}
    if "latitude" in dataset.dims or "latitude" in dataset.coords:
        rename["latitude"] = "lat"
    if "longitude" in dataset.dims or "longitude" in dataset.coords:
        rename["longitude"] = "lon"
    if rename:
        dataset = dataset.rename(rename)
    if "lat" not in dataset.coords or "lon" not in dataset.coords:
        raise RuntimeError(f"OISST-Subset ohne lat/lon: {dataset.dims}")
    lon = np.mod(np.asarray(dataset["lon"].values, dtype=float), 360.0)
    dataset = dataset.assign_coords(lon=lon).sortby("lon").sortby("lat")
    return dataset


def download_oisst_normal_subset(
    day: date,
    destination: Path,
    session=requests,
) -> Path:
    west, south, east, north = ocean_union_bounds()
    time_start, time_stop = _normal_time_indices(day)
    latitudes = OISST_GRID_LAT_START + np.arange(OISST_GRID_LAT_COUNT) * OISST_GRID_STEP
    longitudes = OISST_GRID_LON_START + np.arange(OISST_GRID_LON_COUNT) * OISST_GRID_STEP
    lat_indices = np.flatnonzero((latitudes >= south) & (latitudes <= north))
    lon_indices = np.flatnonzero((longitudes >= west) & (longitudes <= east))
    if not len(lat_indices) or not len(lon_indices):
        raise RuntimeError("NOAA-OISST-Klimamittel: Region liegt außerhalb des Gitters.")
    # NOAA PSL also exposes the original 0.25-degree 1991-2020
    # climatology via THREDDS NetCDF Subset Service (NCSS). Avoid the retired
    # ERDDAP ID (404) and remote DAP access (-77) on GitHub runners.
    from datetime import timedelta
    base_date = date(1, 1, 1)
    params = {
        "var": "sst",
        "north": north, "south": south, "west": west, "east": east,
        "time_start": (base_date + timedelta(days=time_start)).isoformat() + "T00:00:00Z",
        "time_end": (base_date + timedelta(days=time_stop)).isoformat() + "T00:00:00Z",
        "timeStride": 1,
        "accept": "netcdf4",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oisst-ocean-normal-", dir=destination.parent) as tmp:
        path = Path(tmp) / "normal.nc"
        response = _get_with_retry(session, NOAA_NORMALS_NCSS, params=params,
                                   stream=True, timeout=180)
        try:
            _write_response_atomic(response, path)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        with xr.open_dataset(path, decode_times=False) as raw:
            standardized = _standardize_subset(raw.load())
        field = standardized["sst"]
        if int(field.sizes.get("time", 1)) == 2:
            field = field.mean("time", skipna=True, keep_attrs=True)
            reference_method = "feb29_interpolated"
        else:
            for dim in list(field.dims):
                if dim not in {"lat", "lon"} and field.sizes.get(dim) == 1:
                    field = field.isel({dim: 0}, drop=True)
            reference_method = "daily_normal"

        out = xr.Dataset({"sst": field})
        out.attrs["reference_method"] = reference_method
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            out.to_netcdf(
                temporary,
                engine="netcdf4",
                encoding={"sst": {"zlib": True, "complevel": 4}},
            )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination
