#!/usr/bin/env python3
"""Plan year-round HYRAS daily anomalies from the published data-branch indices."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

PARAMETERS = ("tmean", "tmax", "tmin")


def full_year_target(latest: date) -> date:
    """Build from 1 January to the common latest data date."""
    return latest


def plan(data_root: Path) -> tuple[date, bool]:
    dates = []
    for parameter in PARAMETERS:
        path = data_root / parameter / "regions" / "index.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        dates.append(date.fromisoformat(data["data_through"]))
    target = full_year_target(min(dates))
    first = date(target.year, 1, 1)
    required_days = (target - first).days + 1

    needed = False
    for parameter in PARAMETERS:
        path = data_root / parameter / "regions" / "daily_anomaly_maps.json"
        if not path.exists():
            needed = True
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            needed = True
            continue
        days = manifest.get("available_dates") or []
        if (
            manifest.get("calendar_version") != 2
            or manifest.get("data_through") != target.isoformat()
            or len(days) != required_days
            or not days
            or days[0] != first.isoformat()
            or days[-1] != target.isoformat()
            or manifest.get("references") != ["1991-2020", "1961-1990"]
        ):
            needed = True
    return target, needed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    target, needed = plan(args.data_root)
    # Ready for direct appending to GITHUB_OUTPUT.
    print(f"target_date={target.isoformat()}")
    print(f"needed={str(needed).lower()}")


if __name__ == "__main__":
    main()
