from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dwd_common import atomic_write_json, read_json
from update_daily import update_daily
from update_monthly import update_monthly

ROOT = Path(__file__).resolve().parents[1]


def validate_files(root: Path) -> dict:
    monthly = read_json(root / "data.json")
    daily = read_json(root / "daily_tmax_1881_2026.json")

    if not isinstance(monthly, list) or len(monthly) < 1700:
        raise RuntimeError("data.json enthält unerwartet wenige Datensätze.")
    if not isinstance(daily, list) or len(daily) < 53000:
        raise RuntimeError("daily_tmax_1881_2026.json enthält unerwartet wenige Datensätze.")

    monthly_keys = [
        (item.get("area", "Deutschland"), item["date"])
        for item in monthly
    ]
    if len(monthly_keys) != len(set(monthly_keys)):
        raise RuntimeError("data.json enthält doppelte Kombinationen aus Gebiet und Monat.")

    monthly_by_area: dict[str, list[str]] = defaultdict(list)
    for area, date_value in monthly_keys:
        monthly_by_area[area].append(date_value)
    for area, dates in monthly_by_area.items():
        if dates != sorted(dates):
            raise RuntimeError(f"Monatsdaten für {area} sind nicht chronologisch sortiert.")

    daily_dates = [item["date"] for item in daily]
    if daily_dates != sorted(daily_dates) or len(daily_dates) != len(set(daily_dates)):
        raise RuntimeError("Tagesdatei ist nicht eindeutig chronologisch sortiert.")

    return {
        "monthly_records": len(monthly),
        "monthly_area_count": len(monthly_by_area),
        "monthly_areas": sorted(monthly_by_area),
        "monthly_last_record": max(date_value for _, date_value in monthly_keys),
        "daily_records": len(daily),
        "daily_latest_date": daily_dates[-1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aktualisiert das Climate Dashboard mit DWD-Daten.")
    parser.add_argument("--monthly-only", action="store_true")
    parser.add_argument("--daily-only", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    if args.monthly_only and args.daily_only:
        parser.error("--monthly-only und --daily-only können nicht kombiniert werden.")

    if args.validate_only:
        print(json.dumps(validate_files(ROOT), ensure_ascii=False, indent=2))
        return 0

    previous_status = {}
    status_path = ROOT / "update_status.json"
    if status_path.exists():
        try:
            previous_status = read_json(status_path)
        except (OSError, json.JSONDecodeError):
            previous_status = {}

    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Deutscher Wetterdienst (DWD), Climate Data Center",
        "monthly": previous_status.get("monthly"),
        "daily": previous_status.get("daily"),
    }

    if not args.daily_only:
        status["monthly"] = update_monthly(ROOT)
    if not args.monthly_only:
        status["daily"] = update_daily(ROOT, max_workers=args.workers)

    status["validation"] = validate_files(ROOT)
    atomic_write_json(status_path, status)

    print("\nAktualisierung erfolgreich:")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"FEHLER: {exc}", file=sys.stderr)
        raise
