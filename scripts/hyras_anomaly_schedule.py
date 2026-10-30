#!/usr/bin/env python3
"""Plan HYRAS summer-anomaly updates using the published data-branch indices."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

PARAMETERS = ("tmean", "tmax", "tmin")


def summer_target(latest: date) -> date:
    """Anomaly reference grids cover 1 June–31 August, not the whole year."""
    year = latest.year if latest.month >= 6 else latest.year - 1
    return min(latest, date(year, 8, 31))


def plan(data_root: Path) -> tuple[date, bool]:
    dates = []
    for parameter in PARAMETERS:
        path = data_root / parameter / "regions" / "index.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        dates.append(date.fromisoformat(data["data_through"]))
    target = summer_target(min(dates))
    first = date(target.year, 6, 1)
    if target < first:
        raise ValueError("Noch keine Daten für den ausgewählten HYRAS-Sommer")

    needed = False
    for parameter in PARAMETERS:
        path = data_root / parameter / "regions" / "daily_anomaly_maps.json"
        if not path.exists():
            needed = True
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        days = manifest.get("available_dates") or []
        if (
            manifest.get("data_through", "") < target.isoformat()
            or not days
            or days[-1] < target.isoformat()
            or days[0] > first.isoformat()
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
