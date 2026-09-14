#!/usr/bin/env python3
"""Choose the next ERA5 temperature-rank backfill month without leaving gaps."""

from __future__ import annotations

import argparse
import calendar
import json
from datetime import date
from pathlib import Path
from typing import Iterable


def expected_dates(target_year: int, month: int, source: date) -> list[str]:
    month_start = date(target_year, month, 1)
    if source < month_start:
        return []

    if source.year == target_year and source.month == month:
        end_day = source.day
    else:
        end_day = calendar.monthrange(target_year, month)[1]

    return [date(target_year, month, day).isoformat() for day in range(1, end_day + 1)]


def choose_successor(
    *,
    target_year: int,
    target_month: int,
    source: date,
    available: Iterable[str],
) -> tuple[str, int | None, str]:
    """Return (action, month, reason) for the next chained backfill."""

    available_set = set(available)

    # Repair the earliest gap first, including months before the one just finished.
    for candidate in range(3, target_month + 1):
        expected = expected_dates(target_year, candidate, source)
        if expected and any(day not in available_set for day in expected):
            return "dispatch", candidate, "gap"

    if target_month == 12:
        return "done", None, "complete"

    next_month = target_month + 1
    if not expected_dates(target_year, next_month, source):
        return "wait", next_month, "source"

    return "dispatch", next_month, "next"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--target-month", type=int, required=True)
    parser.add_argument(
        "--source-index",
        type=Path,
        default=Path("era5_land_europe/running/index.json"),
    )
    parser.add_argument(
        "--rank-index",
        type=Path,
        default=Path("era5_land_europe/running/temperature_ranks/index.json"),
    )
    args = parser.parse_args()

    source_manifest = json.loads(args.source_index.read_text(encoding="utf-8"))
    rank_manifest = json.loads(args.rank_index.read_text(encoding="utf-8"))
    source = date.fromisoformat(str(source_manifest["data_through"]))
    available = rank_manifest.get("available_dates", [])

    action, month, reason = choose_successor(
        target_year=args.target_year,
        target_month=args.target_month,
        source=source,
        available=available,
    )
    print(
        json.dumps(
            {
                "action": action,
                "month": f"{month:02d}" if month is not None else None,
                "reason": reason,
                "source": source.isoformat(),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
