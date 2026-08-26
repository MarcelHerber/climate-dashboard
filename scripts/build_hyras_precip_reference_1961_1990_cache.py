#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import scripts.build_hyras_reference_1961_1990 as refs


def full_year_dates() -> list[str]:
    day = date(2000, 1, 1)
    end = date(2000, 12, 31)
    dates: list[str] = []
    while day <= end:
        dates.append(day.isoformat())
        day += timedelta(days=1)
    return dates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="/tmp/hyras-data")
    parser.add_argument("--cache-root", default="/tmp/hyras-reference-1961-1990-cache/precipitation")
    parser.add_argument("--work", default="/tmp/hyras-reference-1961-1990-work/precipitation")
    args = parser.parse_args()

    root = Path(args.data_root)
    manifest = refs.json.loads((root / "hyras_web_manifest.json").read_text(encoding="utf-8"))
    refs._build_precip_daily_reference(
        cache_root=Path(args.cache_root),
        work=Path(args.work),
        factor=int(manifest.get("web_sampling_km") or 2),
        needed_dates=full_year_dates(),
        reference=refs.TARGET_REFERENCE,
        expected_width=int(manifest["width"]),
        expected_height=int(manifest["height"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
