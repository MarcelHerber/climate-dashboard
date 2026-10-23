#!/usr/bin/env python3
"""Daily observed Eurasian snow-covered land from NOAA/USNIC IMS 24-km maps.

No data are inferred from illustration pixels. Historical climatology uses the
same geographical mask and area calculation as the current year. The result is
observational snow-covered area, NOT snowfall or snow water equivalent.

NSIDC G02156: https://doi.org/10.7265/N52R3PMC
Source files: https://noaadata.apps.nsidc.org/NOAA/G02156/24km/YYYY/
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import html
import json
import logging
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

LOG = logging.getLogger("eurasia_snow")
SOURCE = "https://noaadata.apps.nsidc.org/NOAA/G02156/24km/"
COLUMNS = ROWS = 1024
CELL_M = 23684.977
XLL_M = -12126597.0
YLL_M = -12126480.0
RADIUS_M = 6371200.0
LON_0 = -80.0
LAT_TS = 60.0
REGION = {"lat_south": 20, "lat_north": 60, "lon_west": -10, "lon_east": 180}
HISTORY_YEARS = [year for year in range(1999, 2026) if year != 2014]
AGENT = "ClimateDashboardEurasianSnow/1.0 (academic/visualization; IMS G02156)"
ROW = re.compile(rb"^[0-4]{1024}$")
FILENAME = re.compile(r"ims(\d{4})(\d{3})(?:_00UTC)?_24km_v([\d.]+)\.asc\.gz", re.I)


def url_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=35) as resp:
        return resp.read()


def inventory(year: int) -> dict[str, str]:
    """Use NSIDC's real directory listing, not guessed version numbers."""
    base = f"{SOURCE}{year}/"
    listing = url_bytes(base).decode("utf-8", "replace")
    found = {}
    for link in re.findall(r'href=["\x27]([^"\x27]+)', listing, re.I):
        filename = urllib.parse.unquote(html.unescape(link)).rsplit("/", 1)[-1]
        match = FILENAME.fullmatch(filename)
        if not match or int(match.group(1)) != year:
            continue
        when = dt.date(year, 1, 1) + dt.timedelta(days=int(match.group(2))-1)
        date_key = when.isoformat()
        path = urllib.parse.urljoin(base, link)
        if date_key not in found or ("_00UTC" in filename and "_00UTC" not in found[date_key]):
            found[date_key] = path
    LOG.info("IMS %s: %d verfügbare 24-km-Tagesdateien", year, len(found))
    return found


def parse_ascii(gzip_bytes: bytes) -> np.ndarray:
    raw = gzip.decompress(gzip_bytes)
    data = []
    # Packed ASCII = 1024 strings of 1024 surface codes. Never accept
    # anything resembling HTML, unlabelled text or a partial grid.
    for raw_line in raw.splitlines():
        line = raw_line.strip().replace(b"\r", b"")
        if ROW.fullmatch(line):
            data.append(line)
    if len(data) != ROWS:
        raise ValueError(f"IMS-Raster unvollständig: {len(data)} statt 1024 Zeilen")
    a = np.frombuffer(b"".join(data), dtype=np.uint8).reshape(ROWS, COLUMNS)
    return a - np.uint8(ord("0"))


def geographic_mask_and_weights() -> tuple[np.ndarray, np.ndarray]:
    """Spherical inverse polar-stereographic projection; pixel areas corrected.

    Native IMS 24-km projection: north polar stereographic, true latitude 60N,
    central meridian 80W and spherical earth radius 6371200 m. The grid starts
    at its south-west corner, and ASCII row 0 is the northernmost raster row.
    For conformal polar stereographic the local scale is
    k=(1+sin(lat_ts))/(1+sin(lat)). Ground area = projected area / k^2.
    """
    x = XLL_M + (np.arange(COLUMNS, dtype="float64") + 0.5) * CELL_M
    y = YLL_M + (ROWS - np.arange(ROWS, dtype="float64") - 0.5) * CELL_M
    xx, yy = np.meshgrid(x, y)
    k0 = (1.0 + math.sin(math.radians(LAT_TS))) / 2.0
    rho = np.hypot(xx, yy)
    latitude = 90.0 - np.degrees(2.0 * np.arctan(rho / (2.0 * RADIUS_M * k0)))
    longitude = (LON_0 + np.degrees(np.arctan2(xx, -yy)) + 180.0) % 360.0 - 180.0
    valid = ((latitude >= REGION["lat_south"]) & (latitude <= REGION["lat_north"]) &
             (longitude >= REGION["lon_west"]) & (longitude <= REGION["lon_east"]))
    scale = (1.0 + math.sin(math.radians(LAT_TS))) / (1.0 + np.sin(np.deg2rad(latitude)))
    area_mkm2 = ((CELL_M / 1e3)**2 / (scale**2)) / 1_000_000.0
    return valid, area_mkm2


def area_for_day(data: np.ndarray, region_mask: np.ndarray, weights: np.ndarray) -> float:
    if data.shape != (ROWS, COLUMNS) or data.min() < 0 or data.max() > 4:
        raise ValueError("IMS-Kategorien ausserhalb der dokumentierten Codes 0..4")
    selected = data[region_mask]
    if int(np.count_nonzero(selected == 2) + np.count_nonzero(selected == 4)) < 30000:
        raise ValueError("Keine plausible IMS-Landabdeckung im Eurasien-Gebiet")
    # IMS: 4=snow-covered land, 2=snow-free land, 3=sea ice (excluded).
    return round(float(weights[(data == 4) & region_mask].sum()), 5)


def calculate_climatology(archive: dict[str, float]) -> list[dict]:
    climatology = []
    for day in range(1, 32):
        samples = [archive[f"{year}-10-{day:02d}"] for year in HISTORY_YEARS
                   if f"{year}-10-{day:02d}" in archive]
        if len(samples) >= 10:
            climatology.append({"day": day, "mean": round(float(np.mean(samples)), 5),
                                "stddev": round(float(np.std(samples, ddof=1)), 5),
                                "years": len(samples)})
        else:
            climatology.append({"day": day, "mean": None, "stddev": None,
                                "years": len(samples)})
    return climatology


def update(output: Path, max_new: int, today: dt.date) -> dict:
    existing = json.loads(output.read_text()) if output.exists() else {}
    archive = {key: val for key, val in existing.get("daily", {}).items()
               if isinstance(val, (int, float)) and re.fullmatch(r"\d{4}-10-\d{2}", key)}
    mask, weights = geographic_mask_and_weights()
    if today.month >= 10:
        current = [dt.date(today.year, 10, day) for day in range(
            1, min(31, ((today - dt.date(today.year, 10, 1)).days)) + 1)]
    else:
        current = []
    years = sorted(HISTORY_YEARS, reverse=True)
    historic = [dt.date(y, 10, day) for y in years for day in range(1, 32)]
    # Prioritize current month every day; fill the full 1999–2025 Oct archive
    # incrementally rather than downloading hundreds of files on every run.
    tasks = [day for day in current + historic if day.isoformat() not in archive]
    found = 0
    failed = 0
    catalogs = {}
    for date in tasks:
        if found >= max_new:
            break
        if date.year not in catalogs:
            try:
                catalogs[date.year] = inventory(date.year)
            except Exception as exc:
                LOG.warning("IMS-Verzeichnis %d: %s", date.year, exc)
                catalogs[date.year] = {}
        link = catalogs[date.year].get(date.isoformat())
        if not link:
            continue
        try:
            grid = parse_ascii(url_bytes(link))
            archive[date.isoformat()] = area_for_day(grid, mask, weights)
            found += 1
            if found < 4 or found % 20 == 0:
                LOG.info("NOAA IMS %s: %.4f Mio. km²", date, archive[date.isoformat()])
        except (ValueError, urllib.error.URLError, OSError) as exc:
            failed += 1
            LOG.warning("IMS %s nicht verarbeitet: %s", date, exc)
    if not archive:
        raise RuntimeError("Kein echter NOAA IMS-24-km-Tagesdatensatz eingelesen")
    # The machine-readable result contains NO model lines until independently
    # calculated. This makes accidental fabrication impossible.
    result = {
        "schema": 1,
        "product": "Eurasien: tägliche Schneebedeckung im Oktober",
        "source": {"name": "NOAA/USNIC IMS 24km / NSIDC G02156",
                   "url": "https://nsidc.org/data/g02156/versions/1",
                   "doi": "10.7265/N52R3PMC"},
        "analysis": {"region": REGION, "resolution_km_nominal": 24,
                     "snow_code": 4, "sea_ice_included": False,
                     "area_unit": "million km2",
                     "area_method": "spherical polar stereographic distortion-corrected"},
        "climatology_period": {"start": 1999, "end": 2025, "excluded": [2014],
                               "min_years_per_day": 10},
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "observed_latest": max((d for d in archive if d.startswith(f"{today.year}-")),
                               default=None),
        "daily": dict(sorted(archive.items())),
        "climatology": calculate_climatology(archive),
        "forecast": None,
        "status": {"n_daily": len(archive), "n_new": found, "n_errors": failed,
                   "n_oct_2026": sum(d.startswith("2026-10-") for d in archive),
                   "n_climatology_days": sum(x["mean"] is not None for x in calculate_climatology(archive))},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    LOG.info("Archiv gespeichert: %d echte Tageswerte (%d neu), %d Klima-Tage",
             len(archive), found, result["status"]["n_climatology_days"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="eurasia_snow/index.json", type=Path)
    parser.add_argument("--max-new", default=100, type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    update(args.output, args.max_new, dt.datetime.now(dt.timezone.utc).date())


if __name__ == "__main__":
    main()
