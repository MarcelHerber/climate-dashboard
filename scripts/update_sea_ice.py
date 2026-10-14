#!/usr/bin/env python3
"""Daily Arctic & Antarctic sea-ice extent from NSIDC Sea Ice Index v4 (G02135).

Compute the 1991–2020 daily reference on *calendar dates* (MM-DD), NOT on
day-of-year numbers, to avoid non-leap-year March misalignment.
Extents are million square kilometres and have a 15% ice-concentration cutoff.
No observations are fabricated or interpolated. Standard deviation is sample
SD (ddof=1), calculated per calendar day. Feb 29 has only leap-year samples.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "sea_ice" / "index.json"
URLS = {
    "north": "https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v4.0.csv",
    "south": "https://noaadata.apps.nsidc.org/NOAA/G02135/south/daily/data/S_seaice_extent_daily_v4.0.csv",
}
START, END = 1991, 2020
DAYS = [
    (date(2000, 1, 1) + timedelta(days=i)).strftime("%m-%d")
    for i in range(366)
]
DAY_INDEX = {day: i for i, day in enumerate(DAYS)}
BAD_DATES = {"1984-09-14"}  # Known erroneous field, documented by NSIDC


def download(url: str) -> str:
    last = None
    for attempt in range(3):
        try:
            request = Request(url, headers={
                "User-Agent": "Climate-Dashboard/1.0 (scientific NSIDC G02135 extent)",
                "Accept": "text/csv,text/plain,*/*",
            })
            with urlopen(request, timeout=110) as f:
                body = f.read()
            if len(body) < 100_000:
                raise ValueError(f"download suspiciously short: {len(body)}")
            return body.decode("utf-8-sig")
        except (OSError, ValueError) as exc:
            last = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"NSIDC daily download failed: {url}: {last}")


def parse_daily(text: str) -> dict[date, float]:
    # NSIDC csv: Year, Month, Day, Extent, Missing, Source Data
    # The second row specifies units and must be skipped.
    reader = csv.DictReader(io.StringIO(text), skipinitialspace=True)
    if not reader.fieldnames:
        raise ValueError("NSIDC CSV has no header")
    reader.fieldnames = [field.strip().lstrip("\ufeff") for field in reader.fieldnames]
    required = {"Year", "Month", "Day", "Extent"}
    if not required.issubset(reader.fieldnames):
        raise ValueError(f"NSIDC CSV columns changed: {reader.fieldnames}")
    readings = {}
    for row in reader:
        try:
            day = date(int(row["Year"]), int(row["Month"]), int(row["Day"]))
            val = float(row["Extent"])
        except (ValueError, TypeError, OverflowError):
            continue
        if day.isoformat() in BAD_DATES:
            continue
        if (1978 <= day.year <= date.today().year + 1 and
                math.isfinite(val) and 0 <= val <= 25):
            readings[day] = round(val, 3)
    return readings


def build_hemisphere(observations: dict[date, float], name: str,
                     now: date | None = None) -> dict:
    now = now or date.today()
    if len(observations) < 15000:
        raise ValueError(f"{name}: insufficient NSIDC observations: {len(observations)}")
    last = max(observations)
    if last < now - timedelta(days=35):
        raise ValueError(f"{name}: source is stale, last date {last}")
    if min(observations).year > 1979:
        raise ValueError(f"{name}: missing historical observations")
    reference = defaultdict(list)
    for day, extent in observations.items():
        if START <= day.year <= END:
            reference[day.strftime("%m-%d")].append(extent)
    normal = []
    for calendar_day in DAYS:
        values = reference[calendar_day]
        expected = 7 if calendar_day == "02-29" else 25
        if len(values) < expected:
            raise ValueError(f"{name}: incomplete {START}–{END} baseline on {calendar_day}: {len(values)}")
        normal.append([round(statistics.mean(values), 4),
                       round(statistics.stdev(values), 4),
                       len(values)])
    by_year = {}
    for day, extent in sorted(observations.items()):
        by_year.setdefault(str(day.year), [None] * 366)[DAY_INDEX[day.strftime("%m-%d")]] = extent
    # Compact JSON: one aligned, 366-element calendar per year.
    # Keeping observed raw points avoids inventing 1979–1987 alternate-day data.
    return {
        "source_url": URLS[name],
        "first_date": min(observations).isoformat(),
        "latest_date": last.isoformat(),
        "count": len(observations),
        "normal": normal,
        "years": by_year,
    }


def construct(fetch=download, now: date | None = None) -> dict:
    north = build_hemisphere(parse_daily(fetch(URLS["north"])), "north", now)
    south = build_hemisphere(parse_daily(fetch(URLS["south"])), "south", now)
    return {
        "ready": True,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": "NOAA/NSIDC Sea Ice Index G02135 Version 4",
        "doi": "10.7265/a98x-0f50",
        "unit": "million km2",
        "threshold_concentration_percent": 15,
        "reference_period": [START, END],
        "normal_method": "Daily MM-DD arithmetic mean and sample SD (ddof=1), 1991–2020; Feb 29 only available leap-year observations. Original NSIDC daily raw extent, no smoothing/interpolation.",
        "calendar_days": DAYS,
        "north": north,
        "south": south,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEST)
    args = parser.parse_args()
    data = construct()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staging = args.output.with_suffix(".json.tmp")
    staging.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    staging.replace(args.output)
    print("NSIDC sea ice:", {
        h: {"last": data[h]["latest_date"], "years": len(data[h]["years"]),
            "obs": data[h]["count"]}
        for h in ("north", "south")
    })


if __name__ == "__main__":
    main()
