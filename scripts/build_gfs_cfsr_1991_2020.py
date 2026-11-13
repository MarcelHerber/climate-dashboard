#!/usr/bin/env python3
"""Build genuine 1991–2020 0.5° GFS-compatible CFSR/CFSv2 daily normals.

Input: one *verified converted* annual 6-hour 2m-temperature NPZ per year.
Required year file keys:
  temp_c: (365, 4, 76, 140), at 00/06/12/18 UTC, Feb29 omitted
  dates: YYYY-MM-DD ISO dates, 365 strictly consecutive non-leap dates
  metadata_json: source product/version, original official source URL and
                 SHA256 of downloaded primary data.
Never uses climatologies from GFS forecasts, CPC or ERA5 as substitutes.
"""
from __future__ import annotations
import argparse
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "gfs_analysis_europe" / "reference_sources"
DEST = ROOT / "gfs_analysis_europe" / "climatology_1991_2020.npz"
H, W = 76, 140

def expected_days(year: int) -> list[str]:
    start = date(year, 1, 1)
    days = [start + timedelta(days=n) for n in range((date(year + 1, 1, 1) - start).days)]
    return [day.isoformat() for day in days if (day.month, day.day) != (2, 29)]

def check_source(year: int, path: Path) -> tuple[np.ndarray, dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing official CFSR/CFSv2 year {year}: {path}")
    with np.load(path, allow_pickle=False) as z:
        a = np.asarray(z["temp_c"], dtype=np.float32)
        days = z["dates"].tolist()
        meta = json.loads(str(z["metadata_json"]))
    if a.shape != (365, 4, H, W) or days != expected_days(year):
        raise ValueError(f"Wrong dates, four UTC cycles or grid in year {year}")
    product = "CFSR" if year <= 2010 else "CFSv2"
    if meta.get("product") != product or meta.get("year") != year:
        raise ValueError(f"Wrong historical analysis product in year {year}")
    url = meta.get("primary_source_url", "")
    if not url.startswith("https://") or not any(
        url.split("/")[2].endswith(host) for host in
        ("ncei.noaa.gov", "gdex.ucar.edu", "rda.ucar.edu")
    ):
        raise ValueError(f"Unverified source host in year {year}")
    if len(meta.get("primary_source_sha256", "")) != 64:
        raise ValueError(f"Missing source checksum in year {year}")
    if meta.get("forecast_hour") != 0 or meta.get("hours_utc") != [0,6,12,18]:
        raise ValueError(f"Not the four historical analysis cycles in year {year}")
    if not np.isfinite(a).all() or not np.all((-100 < a) & (a < 80)):
        raise ValueError(f"Missing or implausible historic 2m values in {year}")
    return a, meta

def make_normals(source: Path = SOURCE) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    total = np.zeros((365, H, W), dtype=np.float64)
    count = np.zeros((365, H, W), dtype=np.int16)
    origins = []
    for year in range(1991, 2021):
        sample, provenance = check_source(year, source / f"t2m_6h_{year}.npz")
        daily = sample.mean(axis=1)
        total += daily
        count += np.isfinite(daily).astype(np.int16)
        origins.append(provenance)
    if (count != 30).any():
        raise ValueError("Not all 30 years/365 days/4 cycles are available")
    base = total / count
    # Five-day smoothed daily climatology, preserving the annual cycle.
    smooth = sum(np.roll(base, delta, axis=0) for delta in (-2, -1, 0, 1, 2)) / 5
    return smooth.astype("float32"), count, origins

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=DEST)
    a = parser.parse_args()
    normals, count, origins = make_normals(a.source)
    meta = {
        "source": "CFSR 1991-2010 + CFSv2 2011-2020",
        "first_year": 1991, "last_year": 2020, "years": 30,
        "sample_hours_utc": [0,6,12,18],
        "grid": "CPC-aligned GFS 0.5 degree Europe",
        "reference": "1991-2020",
        "reference_smoothing": "circular five-day daily normal",
        "daily_source_files": len(origins),
        "sources": origins,
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.output, normal_t2m_c=normals,
                        year_count=count, metadata_json=json.dumps(meta))
    print("Built real 1991-2020 CFSR/CFSv2 normals",a.output,
          "shape",normals.shape,"30 years verified")

if __name__ == "__main__":
    main()
