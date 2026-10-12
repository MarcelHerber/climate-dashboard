#!/usr/bin/env python3
"""Mirror NASA Ozone Watch wind-at-60N text files into a static GitHub data branch.

File series are July-June (e.g. 2017 = July 2017 to June 2018).
The NASA text's last column is forecast lead in hours: 0 for analysis,
positive for forecast, -1 for unavailable. The climatology generated
here is based on winters starting 1990..2019 (DJF 1991..2020).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import logging
import os
from pathlib import Path
import random
import re
import time
from urllib.request import Request, urlopen

BASE = "https://ozonewatch.gsfc.nasa.gov/meteorology/figures/annual/merra2/wind"
LEVELS = (10, 30, 50, 70, 100)
FIRST = 1978
MISSING = -9999.0
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def url(level: int, year: int) -> str:
    return f"{BASE}/u60n_{level}_{year}_merra2.txt"


def read_values(content: str) -> dict[str, tuple[float, int]]:
    found = {}
    for line in content.splitlines():
        cols = line.split()
        # NASA historical MERRA-2 seasons have 9 columns (no Fcst field).
        # Current GEOS-FP season has a 10th column: forecast lead in hours.
        if len(cols) < 9 or not DATE_RE.fullmatch(cols[0]):
            continue
        try:
            value = float(cols[1])
            forecast = int(cols[9]) if len(cols) >= 10 else 0
        except ValueError:
            continue
        if value <= -9000:
            continue
        found[cols[0][5:]] = (value, forecast)
    return found


def fetch_one(args: tuple[Path, int, int, bool]) -> tuple[int, int, bool, str]:
    dest, level, year, refresh = args
    file = dest / f"u60n_{level}_{year}_merra2.txt"
    if file.exists() and file.stat().st_size > 900 and not refresh:
        return level, year, True, "cached"
    for attempt in range(3):
        try:
            request = Request(url(level, year), headers={
                "User-Agent": "ClimateDashboard-Research/1.0 (GitHub public non-commercial mirror)",
                "Accept": "text/plain,*/*"
            })
            with urlopen(request, timeout=22) as reply:
                content = reply.read(100_000).decode("utf-8")
            if "60N Zonal Mean Zonal Wind" not in content or "Level:" not in content:
                raise ValueError("wrong response or unknown NASA file format")
            values = read_values(content)
            if len(values) < 5:
                raise ValueError("too few daily observations/forecasts")
            temp = file.with_suffix(".tmp")
            temp.write_text(content, encoding="utf-8")
            temp.replace(file)
            return level, year, True, "downloaded"
        except Exception as exc:
            if attempt == 2:
                return level, year, False, str(exc)
            time.sleep(1.5 * (attempt + 1) + random.random() * 0.2)
    return level, year, False, "unreachable"


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    low, high = int(k), min(len(ordered) - 1, int(k) + 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (k - low), 2)


def build_baseline(dest: Path, level: int) -> bool:
    records: dict[str, list[float]] = {}
    for year in range(1990, 2020):
        file = dest / f"u60n_{level}_{year}_merra2.txt"
        if not file.exists():
            continue
        for day, (value, forecast) in read_values(file.read_text(encoding="utf-8")).items():
            if forecast == 0:
                records.setdefault(day, []).append(value)
    # Require a substantial historical sample for a reliable 30-winter reference.
    if len(records) < 350 or any(len(v) < 20 for k, v in records.items() if k != "02-29"):
        return False
    result = {
        "source": "NASA Ozone Watch, MERRA-2",
        "parameter": "60N zonal-mean zonal wind",
        "level_hpa": level,
        "unit": "m/s",
        "reference": "Winter 1990/91–2019/20 (January–June: years 1991–2020)",
        "start_years": [1990, 2019],
        "daily": {
            day: {
                "n": len(values),
                "min": round(min(values), 2),
                "p10": percentile(values, 0.10),
                "p30": percentile(values, 0.30),
                "mean": round(sum(values) / len(values), 2),
                "p70": percentile(values, 0.70),
                "p90": percentile(values, 0.90),
                "max": round(max(values), 2)
            }
            for day, values in sorted(records.items())
        }
    }
    (dest / f"climatology_{level}hpa.json").write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("data/stratosphere"))
    parser.add_argument("--year", type=int)
    opts = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    season_year = opts.year or (now.year if now.month >= 7 else now.year - 1)
    dest = opts.out
    dest.mkdir(parents=True, exist_ok=True)
    work = [
        (dest, level, year, year >= season_year - 1)
        for level in LEVELS
        for year in range(FIRST, season_year + 1)
    ]
    ok = 0
    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for level, year, success, msg in executor.map(fetch_one, work):
            if success:
                ok += 1
            else:
                logging.warning("NASA %d hPa %d: %s", level, year, msg)
                failed.append({"level": level, "year": year, "error": msg[:170]})
    baseline = {str(level): build_baseline(dest, level) for level in LEVELS}
    manifest = {
        "updated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "NASA Ozone Watch MERRA-2 / GEOS FP",
        "winter_start_year": season_year,
        "available_files": ok,
        "expected_files": len(work),
        "climatology_1991_2020": baseline,
        "missing_count": len(failed),
        "missing_examples": failed[:12]
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    # A partial archive is okay, but today's series must be present to publish.
    if not (dest / f"u60n_10_{season_year}_merra2.txt").is_file():
        raise SystemExit("10 hPa current series unavailable: preserving existing data branch")


if __name__ == "__main__":
    main()
