#!/usr/bin/env python3
"""DWD DUETT 1-km hourly sunshine -> observed daily regional totals (hours).

Uses the current 1-km EPSG:3035 product SDU (unit: minutes per synoptic
hour ending at HH:50 UTC). Only 24-hour-complete days are accepted; an
incomplete day is never silently treated as overcast. Previously processed
days can be reused from the dedicated data branch.
"""
from __future__ import annotations

import argparse
import calendar
import io
import json
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
import xarray as xr

from build_hyras_tmean_regions import EXPECTED_STATES, build_masks, load_states

BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/hourly/duett/sunshine_duration/recent/"
REGIONS = ("Deutschland", *EXPECTED_STATES)
PATTERN = re.compile(r'href="(SDU_duett_1km_DE_60min_(\d{12})_([A-Za-z0-9]+)\.nc)"')
USER_AGENT = "climate-dashboard-duett-sunshine/1.0 (+GitHub Actions)"
MIN_COVERAGE = .90


def source_index(html: str, year_month: str) -> dict[str, str]:
    """Newest revision for each UTC synoptic hourly timestamp."""
    latest: dict[str, tuple[str, str]] = {}
    for filename, timestamp, revision in PATTERN.findall(html):
        if not timestamp.startswith(year_month):
            continue
        if timestamp[-2:] != "50":
            continue
        if timestamp not in latest or revision > latest[timestamp][0]:
            latest[timestamp] = (revision, filename)
    return {stamp: value[1] for stamp, value in latest.items()}


def hour_keys(day: date) -> list[str]:
    return [day.strftime("%Y%m%d") + f"{hour:02d}50" for hour in range(24)]


def consecutive_days(index: dict[str, str], through: date) -> list[str]:
    current = through.replace(day=1)
    days = []
    while current <= through:
        if not all(stamp in index for stamp in hour_keys(current)):
            break
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def get(url: str, *, timeout: int = 80, retries: int = 3) -> bytes:
    error = None
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            return response.content
        except (requests.RequestException, OSError) as exc:
            error = exc
            if attempt + 1 < retries:
                time.sleep(attempt + 1)
    raise RuntimeError(f"DUETT request failed: {url}: {error}")


def load_sdu(blob: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read decoded SDU minutes, preserving CF missing-value masking."""
    with tempfile.NamedTemporaryFile(suffix=".nc") as file:
        file.write(blob)
        file.flush()
        with xr.open_dataset(file.name, mask_and_scale=True, decode_times=False) as ds:
            if "SDU" not in ds.data_vars:
                raise ValueError(f"DUETT SDU missing: {list(ds.data_vars)}")
            da = ds["SDU"].squeeze(drop=True)
            if da.ndim != 2:
                raise ValueError(f"DUETT SDU has unexpected dimensions {da.dims}")
            units = str(da.attrs.get("units", "")).lower().strip()
            if units not in ("min", "minutes", "minute"):
                raise ValueError(f"Unexpected DUETT SDU units: {units!r}")
            ydim = next((d for d in da.dims if d.lower() == "y"), None)
            xdim = next((d for d in da.dims if d.lower() == "x"), None)
            if not xdim or not ydim:
                raise ValueError(f"DUETT grid coordinates missing: {da.dims}")
            da = da.transpose(ydim, xdim)
            x = np.asarray(da[xdim].values, dtype=np.float64)
            y = np.asarray(da[ydim].values, dtype=np.float64)
            arr = np.asarray(da.values, dtype=np.float32)
            if arr.shape != (len(y), len(x)):
                raise ValueError("DUETT grid mismatch")
            # Physically impossible positive values and missing codes are invalid.
            arr[~np.isfinite(arr) | (arr < 0) | (arr > 60.01)] = np.nan
            return x, y, arr


def area_hourly_minutes(field: np.ndarray, masks: dict[str, np.ndarray], coverage: float = MIN_COVERAGE) -> dict[str, float]:
    result: dict[str, float] = {}
    valid = np.isfinite(field)
    for region, mask in masks.items():
        if field.shape != mask.shape:
            raise ValueError(f"DUETT mask mismatch: {region}")
        spatial = mask & valid
        fraction = int(spatial.sum()) / max(1, int(mask.sum()))
        if fraction < coverage:
            raise ValueError(f"DUETT {region} spatial coverage {fraction:.1%} < {coverage:.0%}")
        result[region] = float(np.mean(field[spatial]))
    return result


def validate_previous(previous: dict, month: str) -> tuple[list[str], dict[str, list[float]]]:
    if not previous or previous.get("month") != month:
        return [], {name: [] for name in REGIONS}
    if previous.get("schema_version") != 1 or previous.get("forecast") is not False:
        raise ValueError("Unexpected cached DUETT schema")
    days = previous.get("dates", [])
    if not isinstance(days, list) or any(not isinstance(d, str) for d in days):
        raise ValueError("Invalid cached DUETT dates")
    start = date.fromisoformat(month + "-01")
    expected = [(start + timedelta(days=i)).isoformat() for i in range(len(days))]
    if days != expected or previous.get("data_through") != (days[-1] if days else None):
        raise ValueError("Non-contiguous cached DUETT sunshine observations")
    results = {}
    for region in REGIONS:
        d = previous.get("regions", {}).get(region, {}).get("daily", [])
        if len(d) != len(days) or any(v is None or not 0 <= float(v) <= 24 for v in d):
            raise ValueError(f"Invalid cached DUETT region {region}")
        results[region] = [float(v) for v in d]
    return days, results


def build(*, today: date, previous: dict | None, work: Path, workers: int = 8) -> dict:
    target_day = today - timedelta(days=1)
    month = target_day.strftime("%Y-%m")
    index = source_index(get(BASE, timeout=120).decode("utf-8", errors="replace"), target_day.strftime("%Y%m"))
    available = consecutive_days(index, target_day)
    if not available:
        raise RuntimeError(f"No complete DUETT daily sunshine files in {month}")
    existing_days, daily = validate_previous(previous or {}, month)
    # Only reuse prior days fully within the currently complete contiguous range.
    keep = 0
    while keep < len(existing_days) and keep < len(available) and existing_days[keep] == available[keep]:
        keep += 1
    for name in REGIONS:
        daily[name] = daily[name][:keep]

    process_days = available[keep:]
    masks = None
    expected_x = expected_y = None
    for day in process_days:
        stamps = hour_keys(date.fromisoformat(day))
        with ThreadPoolExecutor(max_workers=min(workers, 12)) as pool:
            futures = {pool.submit(get, BASE + index[stamp]): stamp for stamp in stamps}
            grids = {}
            for future in as_completed(futures):
                stamp = futures[future]
                x, y, field = load_sdu(future.result())
                if expected_x is None:
                    expected_x, expected_y = x, y
                    masks = build_masks(load_states(work), x, y)
                elif (x.shape != expected_x.shape or y.shape != expected_y.shape
                      or not np.array_equal(x, expected_x) or not np.array_equal(y, expected_y)):
                    raise ValueError(f"DUETT spatial grid changed for {stamp}")
                grids[stamp] = area_hourly_minutes(field, masks)
        if len(grids) != 24:
            raise ValueError(f"Not all DUETT hours available for {day}")
        for name in REGIONS:
            # SDU is minutes per hour, not hours, and each day has 24 UTC hours.
            daily[name].append(round(sum(grids[stamp][name] for stamp in stamps) / 60, 4))
        print(f"DUETT day complete: {day}", flush=True)

    dates = available[:keep + len(process_days)]
    return {
        "schema_version": 1,
        "product": "state_monthly_duett_sunshine_observations",
        "source": "DWD DUETT SDU 1km synoptic 60min (satellite + stations)",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "month": month,
        "data_through": dates[-1],
        "dates": dates,
        "days_in_month": calendar.monthrange(target_day.year, target_day.month)[1],
        "regions_order": list(REGIONS),
        "regions": {
            name: {
                "daily": daily[name],
                "running": [round(sum(daily[name][:i+1]), 3) for i in range(len(dates))],
            }
            for name in REGIONS
        },
        "unit": "h",
        "forecast": False,
        "complete": len(dates) == calendar.monthrange(target_day.year, target_day.month)[1],
        "method": "24 UTC synoptic hours (00:50-23:50) per day; DUETT SDU minutes/60; area mean EPSG:3035, min 90% coverage each hour, no zero-filled missing hours",
        "station_note": "DUETT already blends stations and satellite; independent station checks should not be added again to the area mean.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--work", type=Path, default=Path("/tmp/duett-work"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error("--workers must be between 1 and 12")
    previous = json.loads(args.previous.read_text()) if args.previous and args.previous.is_file() else None
    args.work.mkdir(parents=True, exist_ok=True)
    payload = build(today=datetime.now(timezone.utc).date(), previous=previous, work=args.work, workers=args.workers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("DUETT current-month sunshine hours:", payload["month"], payload["data_through"], "regions:", len(payload["regions"]))


if __name__ == "__main__":
    main()
