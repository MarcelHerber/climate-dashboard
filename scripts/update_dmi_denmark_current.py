#!/usr/bin/env python3
"""
Build current-year DMI Denmark daily TMAX/TMIN compact cache and compare it
against the completed historical DMI Denmark baseline.
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

import update_dmi_denmark_station_cache as hist

CURRENT_FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")


def log(msg: str = "") -> None:
    print(msg, flush=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"dmi_denmark_current_{year}_v{CURRENT_FORMAT_VERSION}.pkl.gz"


def status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"dmi_denmark_current_{year}_status.json"


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as handle:
            pickle.dump(obj, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def record_events(
    historical: dict[str, Any],
    rows: list[tuple[str, date, float | None, float | None]],
) -> list[dict[str, Any]]:
    old_records = historical.get("records", {})
    events: list[dict[str, Any]] = []

    for sid, d, tn, tx in rows:
        old = old_records.get(sid)
        if not isinstance(old, dict):
            continue

        mmdd = d.strftime("%m-%d")
        iso = d.isoformat()

        if tx is not None:
            prior = old.get("calendar_tmax", {}).get(mmdd)
            if prior is not None and float(tx) > float(prior[0]):
                events.append(
                    {
                        "station_id": sid,
                        "date": iso,
                        "element": "TMAX",
                        "value": round(float(tx), 1),
                        "previous_value": round(float(prior[0]), 1),
                        "previous_date": str(prior[1]),
                    }
                )

        if tn is not None:
            prior = old.get("calendar_tmin", {}).get(mmdd)
            if prior is not None and float(tn) < float(prior[0]):
                events.append(
                    {
                        "station_id": sid,
                        "date": iso,
                        "element": "TMIN",
                        "value": round(float(tn), 1),
                        "previous_value": round(float(prior[0]), 1),
                        "previous_date": str(prior[1]),
                    }
                )

    events.sort(key=lambda x: (x["date"], x["station_id"], x["element"]))
    return events


def build_current(
    cache_dir: Path,
    year: int,
    *,
    end_date: date | None = None,
) -> Path:
    today = date.today()
    if year > today.year:
        raise RuntimeError(f"Jahr {year} liegt in der Zukunft.")

    if end_date is None:
        end_date = today if year == today.year else date(year, 12, 31)
    if end_date.year != year:
        raise RuntimeError("--end-date muss im Zieljahr liegen.")

    baseline = hist.load_baseline(cache_dir, year - 1)
    inventory = hist.fetch_dmi_inventory()
    if not inventory:
        # Historical cache inventory is a safe fallback for metadata.
        inventory = dict(baseline.get("inventory", {}))

    log("=== DMI DÄNEMARK AKTUELLES JAHR ===")
    log(
        f"Abruf tägliches {hist.CLIMATE_TMAX} + {hist.CLIMATE_TMIN} "
        f"für {year} bis {end_date.isoformat()}."
    )

    rows = hist.climate_year_rows(year, inventory)
    rows = [row for row in rows if row[1] <= end_date]

    if not rows:
        raise RuntimeError("DMI climateData aktuelles Jahr enthält keine TMAX/TMIN-Werte.")

    records: dict[str, dict[str, Any]] = {}
    consumed = 0
    for sid, d, tn, tx in rows:
        if hist.consume_row(
            records,
            sid,
            d,
            tn,
            tx,
            provenance="DMI_CLIMATE_CURRENT",
        ):
            consumed += 1

    if not records:
        raise RuntimeError("DMI current cache enthält keine Stationsreihen.")

    data_first = min(row[1] for row in rows)
    data_last = max(row[1] for row in rows)
    events = record_events(baseline, rows)

    # Keep only metadata for stations that occur in current records, while
    # falling back to the historical inventory if necessary.
    baseline_inventory = baseline.get("inventory", {})
    current_inventory = {}
    for sid in records:
        meta = inventory.get(sid) or baseline_inventory.get(sid)
        if isinstance(meta, dict):
            current_inventory[sid] = meta

    latest_by_station = {
        sid: rec.get("last_date")
        for sid, rec in records.items()
        if rec.get("last_date")
    }

    payload = {
        "format_version": CURRENT_FORMAT_VERSION,
        "source": hist.SOURCE,
        "public_url": hist.PUBLIC_URL,
        "year": year,
        "requested_end_date": end_date.isoformat(),
        "data_first_date": data_first.isoformat(),
        "data_last_date": data_last.isoformat(),
        "rows_with_temperature": consumed,
        "station_count": len(records),
        "inventory": current_inventory,
        "records": records,
        "latest_observation_by_station": latest_by_station,
        "record_events": events,
        "record_event_count": len(events),
        "historical_cutoff_year": year - 1,
        "historical_baseline_file": str(hist.baseline_path(cache_dir, year - 1)),
        "complete": True,
    }

    out = current_path(cache_dir, year)
    atomic_pickle_gzip(out, payload)

    status = {
        "format_version": CURRENT_FORMAT_VERSION,
        "source": hist.SOURCE,
        "year": year,
        "requested_end_date": end_date.isoformat(),
        "data_first_date": data_first.isoformat(),
        "data_last_date": data_last.isoformat(),
        "rows_with_temperature": consumed,
        "station_count": len(records),
        "record_event_count": len(events),
        "complete": True,
        "current_file": str(out),
        "historical_baseline_file": str(hist.baseline_path(cache_dir, year - 1)),
    }
    atomic_json(status_path(cache_dir, year), status)

    log()
    log("=== DMI DENMARK CURRENT SUMMARY ===")
    log(f"Stationsreihen mit {year}-Daten: {len(records)}")
    log(f"Temperaturtage: {consumed:,}")
    log(f"Datenzeitraum: {data_first.isoformat()} bis {data_last.isoformat()}")
    log(f"Neue historische Tagesrekorde: {len(events):,}")
    log(f"Output: {out}")
    log("DMI Denmark current OK.")
    return out


def self_test() -> None:
    historical = {
        "records": {
            "06030": {
                "calendar_tmax": {"01-01": [10.0, "2000-01-01"]},
                "calendar_tmin": {"01-01": [-5.0, "1990-01-01"]},
            }
        }
    }
    rows = [
        ("06030", date(2026, 1, 1), -6.0, 11.0),
        ("99999", date(2026, 1, 1), -20.0, 40.0),
    ]
    events = record_events(historical, rows)
    assert len(events) == 2
    assert {x["element"] for x in events} == {"TMAX", "TMIN"}
    assert all(x["station_id"] == "06030" for x in events)
    print("DMI Denmark current-year self-test OK")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    p.add_argument("--year", type=int, default=date.today().year)
    p.add_argument("--end-date", default="")
    args = p.parse_args()

    if args.self_test:
        self_test()
        return 0

    end_date = date.fromisoformat(args.end_date) if args.end_date else None
    build_current(
        Path(args.cache_dir),
        args.year,
        end_date=end_date,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
