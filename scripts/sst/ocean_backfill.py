from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from .config import ARCHIVE_START, OCEAN_REGIONS
from .ocean_build import build_ocean_date


def iter_dates(start: date, end: date):
    if end < start:
        raise ValueError("Backfill-Enddatum liegt vor dem Startdatum.")
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Ungültiges Datum: {value}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="NOAA-OISST-Karten für Pazifik, Niño 3.4 und Indischen Ozean rückwirkend ergänzen."
    )
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument("--archive-root", required=True, type=Path)
    parser.add_argument("--cache-root", default=Path(".sst_cache"), type=Path)
    parser.add_argument(
        "--regions",
        default=",".join(OCEAN_REGIONS),
        help="Kommagetrennte Regions-IDs; Standard: alle neuen Ozeanregionen.",
    )
    args = parser.parse_args()

    if args.start < ARCHIVE_START:
        parser.error(f"SST-Backfill beginnt frühestens {ARCHIVE_START.isoformat()}.")

    region_ids = tuple(item.strip() for item in args.regions.split(",") if item.strip())
    unknown = [item for item in region_ids if item not in OCEAN_REGIONS]
    if unknown:
        parser.error(f"Unbekannte Ozeanregionen: {unknown}")

    built = 0
    skipped = 0
    files = 0
    for day in iter_dates(args.start, args.end):
        result = build_ocean_date(
            day,
            args.archive_root,
            args.cache_root,
            region_ids=region_ids,
        )
        if result.already_present:
            skipped += 1
        else:
            built += 1
            files += result.file_count

    print(
        json.dumps(
            {
                "start": args.start.isoformat(),
                "end": args.end.isoformat(),
                "regions": list(region_ids),
                "built": built,
                "skipped": skipped,
                "files": files,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
