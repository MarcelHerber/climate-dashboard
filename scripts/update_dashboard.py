from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dwd_common import atomic_write_json, read_json
from update_daily import update_daily
from rebuild_daily_tmax import rebuild_daily_tmax
from update_monthly import update_monthly
from update_station_precip import update_station_precip
from update_station_climate_days import update_station_climate_days
from update_station_records import update_station_records
from update_station_heatwaves import update_station_heatwaves

ROOT = Path(__file__).resolve().parents[1]


def validate_files(root: Path) -> dict:
    monthly = read_json(root / "data.json")
    daily = read_json(root / "daily_tmax_1881_2026.json")
    station_records = read_json(root / "station_records.json")
    station_precip = read_json(root / "station_precip_index.json")
    station_climate_days = read_json(root / "station_climate_days_index.json")
    station_heatwaves = read_json(root / "station_heatwaves_index.json")

    if not isinstance(monthly, list) or len(monthly) < 1700:
        raise RuntimeError("data.json enthält unerwartet wenige Datensätze.")
    if not isinstance(daily, list) or len(daily) < 53000:
        raise RuntimeError("daily_tmax_1881_2026.json enthält unerwartet wenige Datensätze.")

    monthly_keys = [(item.get("area", "Deutschland"), item["date"]) for item in monthly]
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

    if not isinstance(station_records, dict) or not station_records.get("ready"):
        raise RuntimeError("station_records.json wurde noch nicht vollständig aufgebaut.")
    if not station_records.get("top_lists") or not station_records.get("stations"):
        raise RuntimeError("station_records.json enthält keine Rekordlisten oder Stationsmetadaten.")
    current_year = station_records.get("current_year")
    year_file = root / "station_records_years" / f"{current_year}.json"
    if not year_file.exists():
        raise RuntimeError(f"Jahresdatei für Stationsrekorde fehlt: {year_file.name}")

    if not isinstance(station_precip, dict) or not station_precip.get("ready"):
        raise RuntimeError("station_precip_index.json wurde noch nicht vollständig aufgebaut.")
    precip_stations = station_precip.get("stations") or []
    if len(precip_stations) < 100:
        raise RuntimeError(
            f"station_precip_index.json enthält unerwartet wenige Stationen: {len(precip_stations)}."
        )
    climate_dir = root / "station_precip_climate"
    missing_profiles = [
        item["id"] for item in precip_stations[:100]
        if not (climate_dir / f"{item['id']}.json").exists()
    ]
    if missing_profiles:
        raise RuntimeError(
            "Niederschlags-Klimadateien fehlen, z. B.: " + ", ".join(missing_profiles[:5])
        )
    current_files = station_precip.get("current_files") or []
    if not current_files:
        raise RuntimeError("Keine Monatsdateien für den laufenden Stationsniederschlag vorhanden.")
    for relative_path in current_files:
        if not (root / relative_path).exists():
            raise RuntimeError(f"Aktuelle Niederschlagsdatei fehlt: {relative_path}")

    if not isinstance(station_climate_days, dict) or not station_climate_days.get("ready"):
        raise RuntimeError("station_climate_days_index.json wurde noch nicht vollständig aufgebaut.")
    climate_day_stations = station_climate_days.get("stations") or []
    if len(climate_day_stations) < 100:
        raise RuntimeError(
            "station_climate_days_index.json enthält unerwartet wenige Stationen: "
            f"{len(climate_day_stations)}."
        )
    climate_day_profile_dir = root / "station_climate_days_profiles"
    missing_climate_day_profiles = [
        item["id"] for item in climate_day_stations[:100]
        if not (climate_day_profile_dir / f"{item['id']}.json").exists()
    ]
    if missing_climate_day_profiles:
        raise RuntimeError(
            "Kenntage-Profildateien fehlen, z. B.: "
            + ", ".join(missing_climate_day_profiles[:5])
        )
    climate_day_current_files = station_climate_days.get("current_files") or []
    if not climate_day_current_files:
        raise RuntimeError("Keine aktuellen Monatsdateien für Stations-Kenntage vorhanden.")
    for relative_path in climate_day_current_files:
        if not (root / relative_path).exists():
            raise RuntimeError(f"Aktuelle Kenntage-Datei fehlt: {relative_path}")

    if not isinstance(station_heatwaves, dict) or not station_heatwaves.get("ready"):
        raise RuntimeError("station_heatwaves_index.json wurde noch nicht vollständig aufgebaut.")
    heatwave_stations = station_heatwaves.get("stations") or []
    if len(heatwave_stations) < 100:
        raise RuntimeError(
            "station_heatwaves_index.json enthält unerwartet wenige Stationen: "
            f"{len(heatwave_stations)}."
        )
    heatwave_profile_dir = root / "station_heatwaves_profiles"
    missing_heatwave_profiles = [
        item["id"] for item in heatwave_stations[:100]
        if not (heatwave_profile_dir / f"{item['id']}.json").exists()
    ]
    if missing_heatwave_profiles:
        raise RuntimeError(
            "Hitzewellen-Profildateien fehlen, z. B.: "
            + ", ".join(missing_heatwave_profiles[:5])
        )
    heatwave_current_file = root / str(station_heatwaves.get("current_file", "station_heatwaves_current.json"))
    if not heatwave_current_file.exists():
        raise RuntimeError(f"Aktuelle Hitzewellen-Datei fehlt: {heatwave_current_file.name}")

    return {
        "monthly_records": len(monthly),
        "monthly_area_count": len(monthly_by_area),
        "monthly_areas": sorted(monthly_by_area),
        "monthly_last_record": max(date_value for _, date_value in monthly_keys),
        "daily_records": len(daily),
        "daily_latest_date": daily_dates[-1],
        "station_records_data_through": station_records.get("data_through"),
        "station_records_areas": len(station_records.get("areas", [])),
        "station_records_years": len(station_records.get("available_years", [])),
        "station_precip_data_through": station_precip.get("data_through"),
        "station_precip_stations": len(precip_stations),
        "station_precip_current_files": len(current_files),
        "station_climate_days_data_through": station_climate_days.get("data_through"),
        "station_climate_days_stations": len(climate_day_stations),
        "station_climate_days_current_files": len(climate_day_current_files),
        "station_heatwaves_data_through": station_heatwaves.get("data_through"),
        "station_heatwaves_stations": len(heatwave_stations),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aktualisiert das Climate Dashboard mit DWD-Daten.")
    parser.add_argument("--monthly-only", action="store_true")
    parser.add_argument("--daily-only", action="store_true")
    parser.add_argument("--daily-full-rebuild", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--skip-station-records", action="store_true")
    parser.add_argument("--station-records-full", action="store_true")
    parser.add_argument("--skip-station-precip", action="store_true")
    parser.add_argument("--station-precip-full", action="store_true")
    parser.add_argument("--skip-station-climate-days", action="store_true")
    parser.add_argument("--station-climate-days-full", action="store_true")
    parser.add_argument("--skip-station-heatwaves", action="store_true")
    parser.add_argument("--station-heatwaves-full", action="store_true")
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
        "station_records": previous_status.get("station_records"),
        "station_precip": previous_status.get("station_precip"),
        "station_climate_days": previous_status.get("station_climate_days"),
        "station_heatwaves": previous_status.get("station_heatwaves"),
    }

    if not args.daily_only:
        status["monthly"] = update_monthly(ROOT)
    if not args.monthly_only:
        status["daily"] = (
            rebuild_daily_tmax(ROOT, max_workers=args.workers)
            if args.daily_full_rebuild
            else update_daily(ROOT, max_workers=args.workers)
        )
    if not args.skip_station_records and not args.monthly_only:
        status["station_records"] = update_station_records(
            ROOT,
            max_workers=args.workers,
            force_full=args.station_records_full,
        )
    if not args.skip_station_precip and not args.monthly_only:
        status["station_precip"] = update_station_precip(
            ROOT,
            max_workers=args.workers,
            force_full=args.station_precip_full,
        )
    if not args.skip_station_climate_days and not args.monthly_only:
        status["station_climate_days"] = update_station_climate_days(
            ROOT,
            max_workers=args.workers,
            force_full=args.station_climate_days_full,
        )
    if not args.skip_station_heatwaves and not args.monthly_only:
        status["station_heatwaves"] = update_station_heatwaves(
            ROOT,
            max_workers=args.workers,
            force_full=args.station_heatwaves_full,
        )

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
