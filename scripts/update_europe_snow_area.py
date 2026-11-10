#!/usr/bin/env python3
"""Observed daily Europe snow-covered land area from original NOAA/USNIC IMS 24km grids.

Region: 25 W–70 E, 35–75 N (Iceland to the western Urals), not country
boundaries. Each native grid cell contributes its distortion-corrected
ground area only when IMS code 4 indicates snow-covered land. Sea/lake
ice (3), water (1) and snow-free land (2) never count as snow.

The North Polar Stereographic ASCII raster has row zero on its SOUTH edge.
This orientation is independently verified in update_snow_maps.py.
Neither RGB map images nor Eurasian aggregated areas are scientific inputs.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import json
import logging
import math
from pathlib import Path

import numpy as np

try:
    from scripts.update_snow_maps import Archive, SIZE, CELL, XLL, YLL, RADIUS, K0
    from scripts.update_eurasia_snow import (
        HISTORY_YEARS, WINTER_MONTHS, ALL_MONTHS, calculate_month_climatology,
    )
except ModuleNotFoundError:
    # python scripts/update_europe_snow_area.py from the repository root
    from update_snow_maps import Archive, SIZE, CELL, XLL, YLL, RADIUS, K0
    from update_eurasia_snow import (
        HISTORY_YEARS, WINTER_MONTHS, ALL_MONTHS, calculate_month_climatology,
    )

LOG = logging.getLogger("ims_europe_area")
REGION = {"lat_south": 35, "lat_north": 75, "lon_west": -25, "lon_east": 70}
METHOD = "24km IMS native polar stereographic; lower-left ASCII rows; area corrected by 1/k^2"
MIN_LAND_PIXELS = 3000


def geographic_mask_and_weights() -> tuple[np.ndarray, np.ndarray]:
    """Native 24km cell centres, correctly indexed from the SOUTH-WEST corner."""
    x = XLL + (np.arange(SIZE, dtype=np.float64) + .5) * CELL
    y = YLL + (np.arange(SIZE, dtype=np.float64) + .5) * CELL
    xx, yy = np.meshgrid(x, y)
    rho = np.hypot(xx, yy)
    lat = 90 - np.rad2deg(2 * np.arctan(rho / (2 * RADIUS * K0)))
    lon = (-80 + np.rad2deg(np.arctan2(xx, -yy)) + 180) % 360 - 180
    mask = ((lat >= REGION["lat_south"]) & (lat <= REGION["lat_north"]) &
            (lon >= REGION["lon_west"]) & (lon <= REGION["lon_east"]))
    scale = (1 + math.sin(math.radians(60))) / (1 + np.sin(np.deg2rad(lat)))
    # Ground km² -> million km². Polar stereographic scale is conformal.
    weights = ((CELL / 1000) ** 2 / scale ** 2) / 1_000_000
    if not 40000 < np.count_nonzero(mask) < 90000:
        raise ValueError("Europe IMS mask has an implausible size")
    return mask, weights


def snow_area_mkm2(grid: np.ndarray, mask: np.ndarray, weights: np.ndarray) -> float:
    if grid.shape != (SIZE, SIZE) or grid.dtype.kind not in "iu":
        raise ValueError("Invalid IMS grid shape or categorical type")
    if int(grid.min()) < 0 or int(grid.max()) > 4:
        raise ValueError("IMS categories outside documented 0–4 range")
    land = (grid == 2) | (grid == 4)
    count = int(np.count_nonzero(land & mask))
    if count < MIN_LAND_PIXELS:
        raise ValueError(f"Incomplete IMS Europe land grid: only {count} land pixels")
    snow = (grid == 4) & mask
    area = float(weights[snow].sum())
    land_area = float(weights[land & mask].sum())
    if not 0 <= area <= land_area <= 27:
        raise ValueError("IMS Europe snow area exceeds observed land area")
    return round(area, 5)


def date_priority(valid_dates: list[dt.date], existing: set[str], today: dt.date):
    """Current year first; historical winters next so useful comparisons grow early."""
    available = set(valid_dates)
    recent = sorted((d for d in available if d.year >= today.year - 1), reverse=True)
    leap = sorted((d for d in available if d.month == 2 and d.day == 29
                   and d.year in HISTORY_YEARS), reverse=True)
    reference_years = sorted((y for y in HISTORY_YEARS if y >= 2015), reverse=True)
    winters = [d for y in reference_years for d in sorted(available, reverse=True)
               if d.year == y and d.month in WINTER_MONTHS]
    summers = [d for y in reference_years for d in sorted(available, reverse=True)
               if d.year == y and d.month not in WINTER_MONTHS]
    all_dates = recent + leap + winters + summers + sorted(available, reverse=True)
    seen = set()
    for day in all_dates:
        key = day.isoformat()
        if day > today - dt.timedelta(days=1) or key in seen or key in existing:
            continue
        seen.add(key)
        yield day


def build_result(daily: dict[str, float], today: dt.date, new: int, errors: list[str]) -> dict:
    by_month = {f"{month:02d}": calculate_month_climatology(daily, month)
                for month in ALL_MONTHS}
    coverage = {key: sum(row["mean"] is not None for row in rows)
                for key, rows in by_month.items()}
    def season(date: str):
        return int(date[:4]) if int(date[5:7]) >= 10 else int(date[:4]) - 1
    return {
        "schema": 1, "product": "Europa: IMS schneebedeckte Landfläche",
        "source": {"name": "NOAA / USNIC IMS 24km via NSIDC G02156",
                   "url": "https://nsidc.org/data/g02156/versions/1",
                   "doi": "10.7265/N52R3PMC"},
        "analysis": {"region": REGION, "resolution_km_nominal": 24,
                     "snow_code": 4, "sea_ice_included": False,
                     "area_unit": "million km2", "area_method": METHOD,
                     "reference_region": "Europe geographic rectangle (not national boundaries)"},
        "winter_months": list(WINTER_MONTHS),
        "months": list(ALL_MONTHS),
        "seasons": sorted({season(d) for d in daily}, reverse=True),
        "calendar_years": sorted({int(d[:4]) for d in daily}, reverse=True),
        "climatology_period": {"start": 1999, "end": 2025, "excluded": [2014],
                               "min_years_per_day": 10, "feb29_min_years": 5},
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "observed_latest": max(daily, default=None),
        "daily": dict(sorted(daily.items())),
        "climatology": by_month["10"],
        "climatology_by_month": by_month,
        "forecast": None,
        "status": {"n_daily": len(daily), "n_new": new,
                   "n_failures": len(errors), "source_errors": errors[-12:],
                   "n_climatology_days_by_month": coverage,
                   "n_climatology_days_year": sum(coverage.values())}
    }


def update(output: Path, source_archive: Path, cache: Path,
           today: dt.date, max_new: int = 2600) -> dict:
    if max_new < 1:
        raise ValueError("max_new must be positive")
    source = json.loads(source_archive.read_text(encoding="utf-8"))
    if source.get("source", {}).get("doi") != "10.7265/N52R3PMC":
        raise ValueError("Unverified NOAA IMS date archive")
    confirmed = []
    for raw in source.get("daily", {}):
        try:
            confirmed.append(dt.date.fromisoformat(raw))
        except ValueError:
            continue
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    daily = {day: float(value) for day, value in previous.get("daily", {}).items()
             if isinstance(value, (float, int)) and math.isfinite(value) and 0 <= value <= 27}
    tasks = list(date_priority(confirmed, set(daily), today))
    mask, weights = geographic_mask_and_weights()
    archive = Archive(cache)
    found = 0
    errors = []

    def process(day):
        grid = archive.grid(day)
        return day.isoformat(), snow_area_mkm2(grid, mask, weights)

    # Date catalogues are fetched only for necessary years, but may be
    # reused by multiple workers. Do not parallelize unbounded 10k requests.
    for offset in range(0, len(tasks), 24):
        if found >= max_new:
            break
        batch = tasks[offset:offset + min(24, max_new - found)]
        for year in {day.year for day in batch}:
            if year not in archive.catalogs:
                try:
                    archive.inventory(year)
                except Exception as exc:
                    LOG.warning("IMS catalogue %s: %s", year, exc)
                    archive.catalogs[year] = {}
        ready = [day for day in batch if day in archive.catalogs.get(day.year, {})]
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(process, day): day for day in ready}
            for future in as_completed(futures):
                day = futures[future]
                try:
                    key, value = future.result()
                    daily[key] = value
                    found += 1
                except Exception as exc:
                    errors.append(f"{day}: {exc}")
        if found and found % 240 < 24:
            LOG.info("Europe IMS %d new, %d total", found, len(daily))

    if not daily:
        raise RuntimeError("No verified Europe IMS observations available")
    result = build_result(daily, today, found, errors)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n",
                         encoding="utf-8")
    temporary.replace(output)
    LOG.info("Europe: %d measured days; %d climatology days; %d new, %d errors",
             len(daily), result["status"]["n_climatology_days_year"], found, len(errors))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("eurasia_snow/europe_index.json"))
    parser.add_argument("--source", type=Path, default=Path("eurasia_snow/index.json"))
    parser.add_argument("--cache", type=Path, default=Path(".cache/ims-europe-snow"))
    parser.add_argument("--max-new", type=int, default=2600)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    update(args.output, args.source, args.cache, dt.datetime.now(dt.timezone.utc).date(), args.max_new)


if __name__ == "__main__":
    main()
