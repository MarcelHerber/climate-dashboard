from __future__ import annotations

import os
import tempfile
import time
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
import requests
import xarray as xr

from .config import (
    MUR_COLLECTION_ID,
    MUR_HARMONY_BASE,
    NOAA_NORMALS_BASE,
    NOAA_NORMALS_FILENAME,
    REGIONS,
    Region,
)

CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"
NOAA_NORMALS_ERDDAP = (
    "https://comet.nefsc.noaa.gov/erddap/griddap/"
    "noaa_psl_4e02_3713_6583.nc?sst"
)
NOAA_ERDDAP_TIME_CHUNK_DAYS = 60
NOAA_GRID_TIME_COUNT = 365
NOAA_GRID_LAT_START = -89.875
NOAA_GRID_LON_START = 0.125
NOAA_GRID_STEP = 0.25
NOAA_GRID_LAT_COUNT = 720
NOAA_GRID_LON_COUNT = 1440


class _NcLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href)


def mur_date_available(day: date, session=requests) -> bool:
    start = f"{day.isoformat()}T00:00:00Z"
    stop = f"{day.isoformat()}T23:59:59Z"
    response = session.get(
        CMR_GRANULES,
        params={
            "collection_concept_id": MUR_COLLECTION_ID,
            "temporal": f"{start},{stop}",
            "page_size": 1,
        },
        timeout=30,
    )
    response.raise_for_status()
    return bool(response.json().get("feed", {}).get("entry"))


def latest_available_mur_date(today: date, lookback_days: int = 10, session=requests) -> date:
    for offset in range(lookback_days + 1):
        candidate = today - timedelta(days=offset)
        if mur_date_available(candidate, session=session):
            return candidate
    raise RuntimeError(
        f"Kein MUR-SST-Tag zwischen {today - timedelta(days=lookback_days)} und {today} gefunden."
    )


def _is_json_response(response) -> bool:
    return "json" in response.headers.get("content-type", "").lower()


def _write_response_atomic(response, destination: Path) -> Path:
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type or "json" in content_type:
        raise RuntimeError(f"Unerwarteter Antworttyp statt NetCDF: {content_type or 'unbekannt'}")

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
            raise RuntimeError("NetCDF-Download ist leer.")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def _harmony_data_response(initial_response, headers: dict[str, str], session=requests):
    if not _is_json_response(initial_response):
        return initial_response

    payload = initial_response.json()
    status = str(payload.get("status", "")).lower()
    job_url = next(
        (link.get("href") for link in payload.get("links", []) if link.get("rel") == "self"),
        None,
    )
    if not job_url and payload.get("jobID"):
        job_url = f"https://harmony.earthdata.nasa.gov/jobs/{payload['jobID']}"

    for _ in range(180):
        if status == "successful" and int(payload.get("progress", 100)) >= 100:
            data_links = [
                link.get("href")
                for link in payload.get("links", [])
                if link.get("rel") == "data" and link.get("href")
            ]
            if len(data_links) != 1:
                raise RuntimeError(f"Harmony lieferte {len(data_links)} Datendateien statt genau einer.")
            output = session.get(data_links[0], headers=headers, stream=True, timeout=180)
            output.raise_for_status()
            return output
        if status in {"failed", "canceled", "cancelled", "paused"}:
            raise RuntimeError(f"Harmony-Job {status}: {payload.get('message', 'ohne Meldung')}")
        if not job_url:
            raise RuntimeError("Harmony-Antwort enthält weder Daten noch eine Job-URL.")
        time.sleep(5)
        poll = session.get(job_url, headers=headers, timeout=60)
        poll.raise_for_status()
        payload = poll.json()
        status = str(payload.get("status", "")).lower()

    raise RuntimeError("Harmony-Job wurde innerhalb von 15 Minuten nicht fertig.")


def download_mur_subset(
    day: date,
    region: Region,
    destination: Path,
    token: str,
    session=requests,
) -> Path:
    if not token:
        raise ValueError("EARTHDATA_TOKEN fehlt.")
    headers = {"Authorization": f"Bearer {token}"}
    params = [
        ("subset", f"lat({region.south}:{region.north})"),
        ("subset", f"lon({region.west}:{region.east})"),
        ("subset", f"time({day.isoformat()}T00:00:00Z:{day.isoformat()}T23:59:59Z)"),
        ("format", "application/x-netcdf4"),
        ("maxResults", "1"),
        ("skipPreview", "true"),
    ]
    response = session.get(
        MUR_HARMONY_BASE,
        params=params,
        headers=headers,
        stream=True,
        timeout=180,
    )
    response.raise_for_status()
    data_response = _harmony_data_response(response, headers, session=session)
    return _write_response_atomic(data_response, destination)


def discover_oisst_daily_normals_url(session=requests) -> str:
    response = session.get(NOAA_NORMALS_BASE, timeout=60)
    response.raise_for_status()
    parser = _NcLinkParser()
    parser.feed(response.text)

    candidates: set[str] = set()
    for href in parser.hrefs:
        decoded = unquote(href)
        filename = Path(urlparse(decoded).path).name
        if not filename.endswith(".nc") and "dataset=" in decoded:
            filename = Path(decoded.split("dataset=", 1)[1]).name
        name = filename.lower()
        if (
            filename.endswith(".nc")
            and "day" in name
            and "1991" in name
            and "2020" in name
            and ("mean" in name or "normal" in name or "ltm" in name)
            and "mon" not in name
        ):
            candidates.add(filename)

    if NOAA_NORMALS_FILENAME in candidates:
        selected = NOAA_NORMALS_FILENAME
    elif len(candidates) == 1:
        selected = next(iter(candidates))
    else:
        raise RuntimeError(f"NOAA-Tagesnormaldatei nicht eindeutig: {sorted(candidates)}")

    return (
        "https://psl.noaa.gov/thredds/fileServer/Datasets/"
        f"noaa.oisst.v2.highres/{selected}"
    )


def _selected_index_range(values: np.ndarray, minimum: float, maximum: float) -> tuple[int, int]:
    indices = np.flatnonzero((values >= minimum) & (values <= maximum))
    if indices.size == 0:
        raise RuntimeError(f"Kein OISST-Gitterpunkt im Bereich {minimum}…{maximum}.")
    return int(indices[0]), int(indices[-1])


def _split_contiguous_indices(indices: np.ndarray) -> list[tuple[int, int]]:
    if indices.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(indices) != 1) + 1
    groups = np.split(indices, breaks)
    return [(int(group[0]), int(group[-1])) for group in groups if group.size]


def _oisst_erddap_index_ranges() -> tuple[tuple[int, int], list[tuple[int, int]]]:
    union_west = min(region.west for region in REGIONS.values())
    union_south = min(region.south for region in REGIONS.values())
    union_east = max(region.east for region in REGIONS.values())
    union_north = max(region.north for region in REGIONS.values())

    latitudes = NOAA_GRID_LAT_START + np.arange(NOAA_GRID_LAT_COUNT, dtype=float) * NOAA_GRID_STEP
    longitudes = NOAA_GRID_LON_START + np.arange(NOAA_GRID_LON_COUNT, dtype=float) * NOAA_GRID_STEP
    normalized_longitudes = ((longitudes + 180.0) % 360.0) - 180.0

    lat_range = _selected_index_range(latitudes, union_south, union_north)
    lon_indices = np.flatnonzero(
        (normalized_longitudes >= union_west) & (normalized_longitudes <= union_east)
    )
    lon_ranges = _split_contiguous_indices(lon_indices)
    if not lon_ranges:
        raise RuntimeError("Keine OISST-Längengrade für die SST-Regionen gefunden.")
    return lat_range, lon_ranges


def _time_index_chunks() -> list[tuple[int, int]]:
    return [
        (start, min(start + NOAA_ERDDAP_TIME_CHUNK_DAYS - 1, NOAA_GRID_TIME_COUNT - 1))
        for start in range(0, NOAA_GRID_TIME_COUNT, NOAA_ERDDAP_TIME_CHUNK_DAYS)
    ]


def _standardize_oisst_dataset(dataset: xr.Dataset) -> xr.Dataset:
    rename: dict[str, str] = {}
    if "latitude" in dataset.dims or "latitude" in dataset.coords:
        rename["latitude"] = "lat"
    if "longitude" in dataset.dims or "longitude" in dataset.coords:
        rename["longitude"] = "lon"
    if rename:
        dataset = dataset.rename(rename)
    if "lat" not in dataset.coords or "lon" not in dataset.coords:
        raise RuntimeError(f"NOAA-ERDDAP-Subset ohne lat/lon: {dataset.dims}")
    normalized_lon = ((dataset["lon"] + 180.0) % 360.0) - 180.0
    return dataset.assign_coords(lon=normalized_lon).sortby("lon").sortby("lat")


def ensure_oisst_daily_normals(cache_dir: Path, session=requests) -> Path:
    destination = cache_dir / "oisst" / "oisst_daily_normals_1991_2020.nc"
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    lat_range, lon_ranges = _oisst_erddap_index_ranges()
    time_ranges = _time_index_chunks()

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with tempfile.TemporaryDirectory(prefix="oisst-erddap-", dir=destination.parent) as tmp:
            longitude_parts: list[xr.Dataset] = []
            for lon_number, (lon_start, lon_stop) in enumerate(lon_ranges):
                time_parts: list[xr.Dataset] = []
                for time_number, (time_start, time_stop) in enumerate(time_ranges):
                    query = (
                        f"{NOAA_NORMALS_ERDDAP}"
                        f"[{time_start}:1:{time_stop}]"
                        f"[{lat_range[0]}:1:{lat_range[1]}]"
                        f"[{lon_start}:1:{lon_stop}]"
                    )
                    response = session.get(query, stream=True, timeout=120)
                    chunk_path = Path(tmp) / f"lon-{lon_number:02d}-time-{time_number:02d}.nc"
                    _write_response_atomic(response, chunk_path)
                    with xr.open_dataset(chunk_path, decode_times=False) as chunk_dataset:
                        time_parts.append(_standardize_oisst_dataset(chunk_dataset.load()))

                longitude_part = xr.concat(
                    time_parts,
                    dim="time",
                    data_vars="minimal",
                    coords="minimal",
                    compat="override",
                )
                if int(longitude_part.sizes.get("time", 0)) != NOAA_GRID_TIME_COUNT:
                    raise RuntimeError(
                        f"NOAA-ERDDAP-Längengradteil enthält {longitude_part.sizes.get('time', 0)} "
                        f"statt {NOAA_GRID_TIME_COUNT} Klimatologietagen."
                    )
                longitude_parts.append(longitude_part)

            merged = xr.concat(
                longitude_parts,
                dim="lon",
                data_vars="minimal",
                coords="minimal",
                compat="override",
            ).sortby("lon")
            rounded_lon = np.round(np.asarray(merged["lon"].values, dtype=float), 6)
            _, unique_indices = np.unique(rounded_lon, return_index=True)
            merged = merged.isel(lon=np.sort(unique_indices))
            merged = merged.drop_encoding()
            merged.to_netcdf(
                temporary,
                engine="netcdf4",
                encoding={"sst": {"zlib": True, "complevel": 4}},
            )
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination
