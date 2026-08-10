#!/usr/bin/env python3
"""
Build the current-year KNMI Netherlands TN/TX station snapshot and compare it
with the completed historical KNMI baseline.

This is intentionally lightweight: the whole current year is fetched in one
official KNMI Daggegevens POST request using stns=ALL and vars=TN:TX.

Output:
  .cache/europe-stations/knmi_netherlands_current_<YEAR>_v1.pkl.gz
  .cache/europe-stations/knmi_netherlands_current_<YEAR>_status.json

The current cache contains compact per-station calendar values and explicit
2026-vs-history record events. Raw daily rows are not retained.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import pickle
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import update_knmi_netherlands_station_cache as hist


CURRENT_FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")


def log(msg: str = "") -> None:
    print(msg, flush=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"knmi_netherlands_current_{year}_v{CURRENT_FORMAT_VERSION}.pkl.gz"


def status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"knmi_netherlands_current_{year}_status.json"


def historical_path(cache_dir: Path, year: int) -> Path:
    return hist.baseline_path(cache_dir, year - 1)


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(
            json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_historical(cache_dir: Path, year: int) -> dict[str, Any]:
    path = historical_path(cache_dir, year)
    if not path.exists():
        raise RuntimeError(
            f"Historischer KNMI-Baselinecache fehlt: {path}. "
            "Zuerst 'Build KNMI Netherlands station cache' erfolgreich ausführen."
        )

    obj = hist.load_pickle_gzip(path)
    if not isinstance(obj, dict) or not obj.get("complete") or not obj.get("records"):
        raise RuntimeError(f"Historischer KNMI-Baselinecache ist ungültig/unvollständig: {path}")
    return obj


def record_events(
    historical: dict[str, Any],
    rows: list[tuple[str, date, float | None, float | None]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    historical_records = historical.get("records", {})

    for station_id, d, tn, tx in rows:
        old = historical_records.get(station_id)
        if not old:
            continue

        mmdd = d.strftime("%m-%d")
        iso = d.isoformat()

        if tx is not None:
            prior = old.get("calendar_tmax", {}).get(mmdd)
            if prior is not None and tx > float(prior[0]):
                events.append(
                    {
                        "station_id": station_id,
                        "date": iso,
                        "element": "TMAX",
                        "value": round(float(tx), 1),
                        "previous_value": round(float(prior[0]), 1),
                        "previous_date": str(prior[1]),
                    }
                )

        if tn is not None:
            prior = old.get("calendar_tmin", {}).get(mmdd)
            if prior is not None and tn < float(prior[0]):
                events.append(
                    {
                        "station_id": station_id,
                        "date": iso,
                        "element": "TMIN",
                        "value": round(float(tn), 1),
                        "previous_value": round(float(prior[0]), 1),
                        "previous_date": str(prior[1]),
                    }
                )

    events.sort(key=lambda x: (x["date"], x["station_id"], x["element"]))
    return events


def build_current(cache_dir: Path, year: int, end_date: date | None = None) -> Path:
    today = date.today()
    if year > today.year:
        raise RuntimeError(f"Jahr {year} liegt in der Zukunft.")

    if end_date is None:
        end_date = today if year == today.year else date(year, 12, 31)

    if end_date.year != year:
        raise RuntimeError("--end-date muss im angeforderten Jahr liegen.")

    start_date = date(year, 1, 1)
    if end_date < start_date:
        raise RuntimeError("Enddatum liegt vor Jahresbeginn.")

    cache_dir.mkdir(parents=True, exist_ok=True)
    historical = load_historical(cache_dir, year)

    log("=== KNMI NIEDERLANDE AKTUELLES JAHR ===")
    log(f"Abruf {start_date.isoformat()} bis {end_date.isoformat()} | stns=ALL | vars=TN:TX")

    text = hist.request_knmi(start_date, end_date)
    inventory = hist.parse_station_metadata(text)
    rows = hist.parse_daily_rows(text)

    if not rows:
        raise RuntimeError("KNMI aktuelles Jahr enthält keine TN/TX-Zeilen.")

    # Defensive range check.
    rows = [r for r in rows if start_date <= r[1] <= end_date]
    if not rows:
        raise RuntimeError("KNMI lieferte keine TN/TX-Zeilen innerhalb des angeforderten Zeitraums.")

    records: dict[str, dict[str, Any]] = {}
    consumed = hist.consume_rows(records, rows)
    events = record_events(historical, rows)

    data_last_date = max(r[1] for r in rows)
    data_first_date = min(r[1] for r in rows)

    # Add historical station metadata for stations that are present in the
    # daily rows but omitted from the response metadata for any reason.
    hist_inventory = historical.get("inventory", {})
    for station_id in records:
        if station_id not in inventory and station_id in hist_inventory:
            inventory[station_id] = hist_inventory[station_id]

    result = {
        "format_version": CURRENT_FORMAT_VERSION,
        "source": hist.SOURCE,
        "public_url": hist.PUBLIC_URL,
        "year": year,
        "requested_start_date": start_date.isoformat(),
        "requested_end_date": end_date.isoformat(),
        "data_first_date": data_first_date.isoformat(),
        "data_last_date": data_last_date.isoformat(),
        "rows_with_temperature": consumed,
        "station_count": len(records),
        "inventory": inventory,
        "records": records,
        "record_events": events,
        "record_event_count": len(events),
        "historical_cutoff_year": year - 1,
        "historical_baseline_file": str(historical_path(cache_dir, year)),
        "complete": True,
    }

    out = current_path(cache_dir, year)
    atomic_pickle_gzip(out, result)

    status = {
        "format_version": CURRENT_FORMAT_VERSION,
        "source": hist.SOURCE,
        "year": year,
        "requested_end_date": end_date.isoformat(),
        "data_first_date": data_first_date.isoformat(),
        "data_last_date": data_last_date.isoformat(),
        "rows_with_temperature": consumed,
        "station_count": len(records),
        "record_event_count": len(events),
        "complete": True,
        "current_file": str(out),
        "historical_baseline_file": str(historical_path(cache_dir, year)),
    }
    atomic_json(status_path(cache_dir, year), status)

    log(
        f"KNMI CURRENT OK: {len(records)} Stationsreihen | "
        f"{consumed:,} Temperatur-Zeilen | Daten bis {data_last_date.isoformat()} | "
        f"{len(events)} neue Kalenderrekord-Ereignisse ggü. bis {year-1}."
    )
    return out


def self_test() -> None:
    historical = {
        "records": {
            "260": {
                "calendar_tmax": {"01-01": [10.0, "2000-01-01"]},
                "calendar_tmin": {"01-01": [-5.0, "1990-01-01"]},
            }
        }
    }
    rows = [
        ("260", date(2026, 1, 1), -6.0, 11.0),
        ("999", date(2026, 1, 1), -20.0, 40.0),
    ]
    events = record_events(historical, rows)
    assert len(events) == 2
    assert {e["element"] for e in events} == {"TMAX", "TMIN"}
    assert all(e["station_id"] == "260" for e in events)
    print("KNMI Netherlands current-year self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--end-date", default="")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    end_date = date.fromisoformat(args.end_date) if args.end_date else None
    build_current(Path(args.cache_dir), args.year, end_date=end_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
