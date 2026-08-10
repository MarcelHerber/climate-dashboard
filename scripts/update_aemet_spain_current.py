#!/usr/bin/env python3
"""
Load current-year Spain daily Tmax/Tmin from AEMET OpenData and compare
against the completed historical baseline through the previous year.

The output remains compact:
- current-year station records
- latest observation date per station
- new calendar-day Tmax/Tmin records versus the historical baseline

Required environment variable:
    AEMET_API_KEY
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import update_aemet_spain_station_cache as aemet


CURRENT_FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")


def log(message: str) -> None:
    print(message, flush=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"aemet_spain_current_{year}_v{CURRENT_FORMAT_VERSION}.pkl.gz"


def current_status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"aemet_spain_current_{year}_status.json"


def detect_record_events(
    historical: dict[str, Any],
    current_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    hist_records = historical.get("records", {})
    events: list[dict[str, Any]] = []

    for station_id, current in current_records.items():
        hist = hist_records.get(station_id)
        if not isinstance(hist, dict):
            # A station with no pre-2026 history cannot establish a
            # historical station record against our baseline.
            continue

        for mmdd, value_date in current.get("calendar_tmax", {}).items():
            old = hist.get("calendar_tmax", {}).get(mmdd)
            if not (
                isinstance(value_date, (list, tuple))
                and len(value_date) >= 2
                and isinstance(old, (list, tuple))
                and len(old) >= 2
            ):
                continue
            value = float(value_date[0])
            old_value = float(old[0])
            if value > old_value:
                events.append(
                    {
                        "station_id": station_id,
                        "date": str(value_date[1]),
                        "kind": "TMAX",
                        "value": round(value, 1),
                        "previous_value": round(old_value, 1),
                        "previous_date": str(old[1]),
                        "delta": round(value - old_value, 1),
                        "source": aemet.SOURCE,
                    }
                )

        for mmdd, value_date in current.get("calendar_tmin", {}).items():
            old = hist.get("calendar_tmin", {}).get(mmdd)
            if not (
                isinstance(value_date, (list, tuple))
                and len(value_date) >= 2
                and isinstance(old, (list, tuple))
                and len(old) >= 2
            ):
                continue
            value = float(value_date[0])
            old_value = float(old[0])
            if value < old_value:
                events.append(
                    {
                        "station_id": station_id,
                        "date": str(value_date[1]),
                        "kind": "TMIN",
                        "value": round(value, 1),
                        "previous_value": round(old_value, 1),
                        "previous_date": str(old[1]),
                        "delta": round(value - old_value, 1),
                        "source": aemet.SOURCE,
                    }
                )

    events.sort(key=lambda x: (x["date"], x["station_id"], x["kind"]))
    return events


def build_current(
    *,
    api_key: str,
    year: int,
    cache_dir: Path,
) -> Path:
    today = date.today()
    if year != today.year:
        raise RuntimeError(
            f"Current-Workflow erwartet das laufende Jahr {today.year}; "
            f"angefordert wurde {year}."
        )

    cutoff_year = year - 1
    historical = aemet.load_baseline(cache_dir, cutoff_year)

    # Start from the official historical inventory; consume_daily_payload may
    # add a station if AEMET returns a new identifier not yet in that inventory.
    inventory = {
        sid: dict(meta)
        for sid, meta in historical.get("inventory", {}).items()
    }
    current_records: dict[str, dict[str, Any]] = {}

    start = date(year, 1, 1)
    end = today
    total_windows = sum(1 for _ in aemet.windows(start, end))

    log("=== AEMET SPANIEN CURRENT ===")
    log(
        f"Zeitraum {start.isoformat()} bis {end.isoformat()} | "
        f"{total_windows} Fenster à maximal {aemet.WINDOW_DAYS} Tage."
    )

    rows_total = 0
    data_windows = 0
    empty_windows = 0

    for index, (window_start, window_end) in enumerate(
        aemet.windows(start, end),
        1,
    ):
        start_api = f"{window_start.isoformat()}T00:00:00UTC"
        end_api = f"{window_end.isoformat()}T23:59:59UTC"
        api_path = aemet.DAILY_ALL_PATH.format(
            start=start_api,
            end=end_api,
        )
        label = f"AEMET current {window_start}–{window_end}"

        payload = aemet.fetch_api_payload(
            api_path,
            api_key,
            label=label,
            no_data_is_empty=True,
        )

        rows, station_count = aemet.consume_daily_payload(
            payload,
            window_start=window_start,
            window_end=window_end,
            inventory=inventory,
            records=current_records,
        )
        rows_total += rows
        if rows:
            data_windows += 1
        else:
            empty_windows += 1

        log(
            f"AEMET current: {index}/{total_windows} Fenster | "
            f"{station_count} Stationen im Fenster | "
            f"{rows:,} Temperatur-Zeilen | "
            f"kumuliert {rows_total:,}."
        )

    if not current_records or rows_total <= 0:
        raise RuntimeError("AEMET current enthält keine Temperaturdaten.")

    events = detect_record_events(historical, current_records)

    latest_by_station = {
        sid: rec.get("last_date")
        for sid, rec in current_records.items()
        if rec.get("last_date")
    }

    first_date = min(
        (
            rec["first_date"]
            for rec in current_records.values()
            if rec.get("first_date")
        ),
        default=None,
    )
    last_date = max(
        (
            rec["last_date"]
            for rec in current_records.values()
            if rec.get("last_date")
        ),
        default=None,
    )

    payload = {
        "format_version": CURRENT_FORMAT_VERSION,
        "source": aemet.SOURCE,
        "year": year,
        "historical_cutoff_year": cutoff_year,
        "historical_baseline_file": str(aemet.baseline_path(cache_dir, cutoff_year)),
        "inventory": inventory,
        "records": current_records,
        "latest_observation_by_station": latest_by_station,
        "record_events": events,
        "rows_with_temperature": rows_total,
        "station_count": len(current_records),
        "inventory_count": len(inventory),
        "data_first": first_date,
        "data_last": last_date,
        "data_windows": data_windows,
        "empty_windows": empty_windows,
        "request_date": today.isoformat(),
    }

    out = current_path(cache_dir, year)
    aemet._atomic_pickle_gz(out, payload)

    status = {
        "format_version": CURRENT_FORMAT_VERSION,
        "source": aemet.SOURCE,
        "year": year,
        "historical_cutoff_year": cutoff_year,
        "historical_baseline_file": str(aemet.baseline_path(cache_dir, cutoff_year)),
        "current_file": str(out),
        "inventory_count": len(inventory),
        "station_count": len(current_records),
        "rows_with_temperature": rows_total,
        "data_first": first_date,
        "data_last": last_date,
        "data_windows": data_windows,
        "empty_windows": empty_windows,
        "record_event_count": len(events),
        "request_date": today.isoformat(),
    }
    aemet._atomic_json(current_status_path(cache_dir, year), status)

    log("=== AEMET CURRENT SUMMARY ===")
    log(f"Stationsreihen mit 2026-Daten: {len(current_records):,}")
    log(f"Temperatur-Zeilen: {rows_total:,}")
    log(f"Datenzeitraum: {first_date} bis {last_date}")
    log(f"Neue historische Tagesrekorde: {len(events):,}")
    log(f"Output: {out}")
    log("AEMET Spain current OK.")
    return out


def self_test() -> None:
    historical = {
        "records": {
            "X": {
                "calendar_tmax": {"07-01": [40.0, "1994-07-01"]},
                "calendar_tmin": {"07-01": [10.0, "1980-07-01"]},
            }
        }
    }
    current = {
        "X": {
            "calendar_tmax": {"07-01": [41.2, "2026-07-01"]},
            "calendar_tmin": {"07-01": [8.9, "2026-07-01"]},
        },
        "NEW": {
            "calendar_tmax": {"07-01": [45.0, "2026-07-01"]},
            "calendar_tmin": {"07-01": [1.0, "2026-07-01"]},
        },
    }
    events = detect_record_events(historical, current)
    assert len(events) == 2
    assert {x["kind"] for x in events} == {"TMAX", "TMIN"}
    assert all(x["station_id"] == "X" for x in events)
    print("AEMET Spain current self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR_DEFAULT)
    parser.add_argument("--year", type=int, default=date.today().year)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    api_key = __import__("os").environ.get("AEMET_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("AEMET_API_KEY fehlt.")

    build_current(
        api_key=api_key,
        year=args.year,
        cache_dir=args.cache_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
