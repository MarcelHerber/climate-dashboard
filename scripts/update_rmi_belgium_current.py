#!/usr/bin/env python3
"""
Belgium current-year daily Tmin/Tmax from KMI/RMI aws:aws_1day.

Current year is KMI/RMI AWS-only for every Belgian station, including Uccle.
The historical hybrid (Uccle GHCN / others SYNOP) exists only before 2000.
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

import update_rmi_belgium_station_cache as hist

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")


def log(msg: str = "") -> None:
    print(msg, flush=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"rmi_belgium_current_{year}_v{FORMAT_VERSION}.pkl.gz"


def status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"rmi_belgium_current_{year}_status.json"


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
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


def build_records(
    rows: list[dict[str, Any]],
    year: int,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}

    for row in rows:
        sid = hist.station_code(row)
        d = hist.parse_iso_day(row.get("timestamp"))
        if not sid or d is None or d.year != year:
            continue

        tn = hist.valid_temp(row.get("temp_min"))
        tx = hist.valid_temp(row.get("temp_max"))

        hist.consume_day(
            records,
            sid,
            d,
            tn,
            tx,
            "RMI_AWS",
        )

    return records


def record_events(
    baseline: dict[str, Any],
    current_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    historical_records = baseline.get("records", {})
    events: list[dict[str, Any]] = []

    for sid, rec in current_records.items():
        old = historical_records.get(sid)
        if not isinstance(old, dict):
            continue

        for mmdd, pair in rec.get("calendar_tmax", {}).items():
            prior = old.get("calendar_tmax", {}).get(mmdd)
            if prior is None:
                continue
            if float(pair[0]) > float(prior[0]):
                events.append(
                    {
                        "station_id": sid,
                        "date": pair[1],
                        "element": "TMAX",
                        "value": round(float(pair[0]), 2),
                        "previous_value": round(float(prior[0]), 2),
                        "previous_date": str(prior[1]),
                    }
                )

        for mmdd, pair in rec.get("calendar_tmin", {}).items():
            prior = old.get("calendar_tmin", {}).get(mmdd)
            if prior is None:
                continue
            if float(pair[0]) < float(prior[0]):
                events.append(
                    {
                        "station_id": sid,
                        "date": pair[1],
                        "element": "TMIN",
                        "value": round(float(pair[0]), 2),
                        "previous_value": round(float(prior[0]), 2),
                        "previous_date": str(prior[1]),
                    }
                )

    events.sort(key=lambda x: (x["date"], x["station_id"], x["element"]))
    return events


def build_current(
    cache_dir: Path,
    year: int,
    *,
    force: bool = False,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = current_path(cache_dir, year)

    if force:
        out.unlink(missing_ok=True)
        status_path(cache_dir, year).unlink(missing_ok=True)

    baseline = hist.load_baseline(cache_dir, year - 1)

    log("=== KMI/RMI BELGIEN AKTUELLES JAHR ===")
    log(f"Jahr {year} | ausschließlich aws:aws_1day")

    rows = hist.aws_year_rows(year)
    records = build_records(rows, year)

    if not records:
        raise RuntimeError("KMI/RMI Belgium current enthält keine Stationsreihen.")

    inventory = dict(baseline.get("inventory", {}))
    # Refresh modern AWS inventory to keep geometry/names current.
    fresh_aws = hist.station_layer_inventory(hist.AWS_STATION, "AWS")
    for sid, meta in fresh_aws.items():
        if sid in inventory:
            old = inventory[sid]
            for key in ("name", "lat", "lon", "elevation_m"):
                if meta.get(key) not in (None, ""):
                    old[key] = meta[key]
            old["network"] = "AWS"
        else:
            inventory[sid] = meta

    dates = [
        rec.get("first_date")
        for rec in records.values()
        if rec.get("first_date")
    ]
    last_dates = [
        rec.get("last_date")
        for rec in records.values()
        if rec.get("last_date")
    ]

    first_date = min(dates) if dates else None
    last_date = max(last_dates) if last_dates else None
    latest_by_station = {
        sid: rec["last_date"]
        for sid, rec in records.items()
        if rec.get("last_date")
    }

    events = record_events(baseline, records)

    payload = {
        "format_version": FORMAT_VERSION,
        "source": hist.SOURCE,
        "year": year,
        "complete": True,
        "dataset": hist.AWS_DAY,
        "inventory": inventory,
        "records": records,
        "latest_observation_by_station": latest_by_station,
        "data_first_date": first_date,
        "data_last_date": last_date,
        "rows_with_temperature": sum(
            int(rec.get("observation_days", 0))
            for rec in records.values()
        ),
        "record_events": events,
        "historical_cutoff_year": year - 1,
        "historical_baseline_file": str(
            hist.baseline_path(cache_dir, year - 1)
        ),
    }

    atomic_pickle_gzip(out, payload)

    status = {
        "format_version": FORMAT_VERSION,
        "source": hist.SOURCE,
        "year": year,
        "complete": True,
        "station_count": len(records),
        "rows_with_temperature": payload["rows_with_temperature"],
        "data_first_date": first_date,
        "data_last_date": last_date,
        "record_event_count": len(events),
        "current_file": str(out),
    }
    atomic_json(status_path(cache_dir, year), status)

    log()
    log("=== KMI/RMI BELGIUM CURRENT SUMMARY ===")
    log(f"Stationsreihen mit {year}-Daten: {len(records)}")
    log(f"Stationstage: {payload['rows_with_temperature']:,}")
    log(f"Datenzeitraum: {first_date} bis {last_date}")
    log(f"Neue historische Tagesrekorde: {len(events):,}")
    log(f"Output: {out}")
    log("KMI/RMI Belgium current OK.")
    return out


def self_test() -> None:
    rows = [
        {
            "code": 6447,
            "timestamp": "2026-08-09T00:00:00Z",
            "temp_min": 12.3,
            "temp_max": 29.4,
        },
        {
            "code": 6455,
            "timestamp": "2026-08-09T00:00:00Z",
            "temp_min": 11.8,
            "temp_max": 28.7,
        },
    ]
    records = build_records(rows, 2026)
    assert set(records) == {"6447", "6455"}
    assert records["6447"]["tmax_abs"] == [29.4, "2026-08-09"]
    assert records["6447"]["provenance_days"]["RMI_AWS"] == 1
    print("KMI/RMI Belgium current-year self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_current(
        Path(args.cache_dir),
        args.year,
        force=args.force,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
