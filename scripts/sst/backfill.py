from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path

from .build_daily import build_date
from .config import ARCHIVE_START, REGIONS
from .manifest import VIEWS, archive_relpath


def iter_dates(start: date, end: date):
    if end < start:
        raise ValueError("Backfill-Enddatum liegt vor dem Startdatum.")
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def storage_report(archive_root: Path, dates) -> dict:
    dates = list(dates)
    total_bytes = 0
    file_count = 0
    for day in dates:
        for region_id in REGIONS:
            for view in VIEWS:
                path = Path(archive_root) / archive_relpath(day, region_id, view)
                if path.exists() and path.is_file():
                    total_bytes += path.stat().st_size
                    file_count += 1
    date_count = len(dates)
    mean_bytes_per_day = total_bytes / date_count if date_count else 0.0
    projected_days = max(0, (date.today() - ARCHIVE_START).days + 1)
    projected_bytes = mean_bytes_per_day * projected_days
    return {
        "date_count": date_count,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "mean_bytes_per_day": mean_bytes_per_day,
        "projected_archive_gib_from_2020": projected_bytes / (1024 ** 3),
    }


def _write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def backfill(
    start: date,
    end: date,
    archive_root: Path,
    cache_root: Path,
    token: str,
) -> dict:
    if start < ARCHIVE_START:
        raise ValueError(f"SST-Backfill beginnt frühestens {ARCHIVE_START.isoformat()}.")
    days = list(iter_dates(start, end))
    built = 0
    skipped = 0
    for day in days:
        result = build_date(day, Path(archive_root), Path(cache_root), token)
        if result.already_present:
            skipped += 1
        else:
            built += 1

    report = storage_report(Path(archive_root), days)
    _write_report(Path(archive_root) / "storage_report.json", report)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "built": built,
        "skipped": skipped,
        "storage": report,
    }


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Ungültiges Datum: {value}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="SST Europa Tageskarten rückwirkend aufbauen.")
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument("--archive-root", required=True, type=Path)
    parser.add_argument("--cache-root", default=Path(".sst_cache"), type=Path)
    args = parser.parse_args()
    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        parser.error("EARTHDATA_TOKEN fehlt.")
    result = backfill(args.start, args.end, args.archive_root, args.cache_root, token)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
