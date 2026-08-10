#!/usr/bin/env python3
"""
MeteoSwiss Switzerland current-year daily Tmin/Tmax.

Source:
  MeteoSwiss SwissMetNet (SMN)
  daily recent STAC assets
  Tmin tre200dn / Tmax tre200dx

No NBCN homogeneous data are mixed in.
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

import update_meteoswiss_switzerland_station_cache as hist

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")


def log(msg: str = "") -> None:
    print(msg, flush=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / (
        f"meteoswiss_switzerland_current_{year}_v{FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / (
        f"meteoswiss_switzerland_current_{year}_status.json"
    )


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


def record_events(
    baseline: dict[str, Any],
    records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    old_records = baseline.get("records", {})
    events = []

    for sid, rec in records.items():
        old = old_records.get(sid)
        if not isinstance(old, dict):
            continue

        for mmdd, pair in rec.get("calendar_tmax", {}).items():
            prior = old.get("calendar_tmax", {}).get(mmdd)
            if prior is not None and float(pair[0]) > float(prior[0]):
                events.append({
                    "station_id": sid,
                    "date": pair[1],
                    "element": "TMAX",
                    "value": float(pair[0]),
                    "previous_value": float(prior[0]),
                    "previous_date": str(prior[1]),
                })

        for mmdd, pair in rec.get("calendar_tmin", {}).items():
            prior = old.get("calendar_tmin", {}).get(mmdd)
            if prior is not None and float(pair[0]) < float(prior[0]):
                events.append({
                    "station_id": sid,
                    "date": pair[1],
                    "element": "TMIN",
                    "value": float(pair[0]),
                    "previous_value": float(prior[0]),
                    "previous_date": str(prior[1]),
                })

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
    inventory = hist.load_station_metadata()

    log("=== METEOSWISS SCHWEIZ AKTUELLES JAHR ===")
    log(
        f"{year} | SwissMetNet daily recent | "
        f"{hist.TMIN_PARAM}/{hist.TMAX_PARAM}"
    )

    items = hist.get_all_stac_items()
    records: dict[str, dict[str, Any]] = {}
    assets_used = 0

    for item in items:
        sid = hist.station_id_from_item(item)
        if not sid:
            continue

        urls = hist.recent_daily_assets(item)
        if not urls:
            continue

        rec = hist.empty_record()
        for href in urls:
            raw = hist.request_bytes(href, accept="text/csv,*/*")
            rows = hist.parse_daily_asset(raw, only_year=year)
            if rows:
                assets_used += 1
            for d, tn, tx in rows:
                hist.consume_day(rec, d, tn, tx)

        if rec["observation_days"] > 0:
            records[sid] = rec

    if not records:
        raise RuntimeError("MeteoSwiss Current enthält keine Stationsreihen.")

    dates = [
        rec["first_date"] for rec in records.values() if rec.get("first_date")
    ]
    last_dates = [
        rec["last_date"] for rec in records.values() if rec.get("last_date")
    ]
    first_date = min(dates) if dates else None
    last_date = max(last_dates) if last_dates else None

    latest_by_station = {
        sid: rec["last_date"]
        for sid, rec in records.items()
        if rec.get("last_date")
    }

    station_days = sum(
        int(rec.get("observation_days", 0))
        for rec in records.values()
    )
    events = record_events(baseline, records)

    payload = {
        "format_version": FORMAT_VERSION,
        "source": hist.SOURCE,
        "network": hist.NETWORK,
        "collection_id": hist.COLLECTION_ID,
        "year": year,
        "complete": True,
        "parameters": {
            "TMIN": hist.TMIN_PARAM,
            "TMAX": hist.TMAX_PARAM,
        },
        "inventory": inventory,
        "records": records,
        "latest_observation_by_station": latest_by_station,
        "data_first_date": first_date,
        "data_last_date": last_date,
        "rows_with_temperature": station_days,
        "asset_count": assets_used,
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
        "network": hist.NETWORK,
        "year": year,
        "complete": True,
        "station_count": len(records),
        "rows_with_temperature": station_days,
        "asset_count": assets_used,
        "data_first_date": first_date,
        "data_last_date": last_date,
        "record_event_count": len(events),
        "current_file": str(out),
    }
    atomic_json(status_path(cache_dir, year), status)

    log()
    log("=== METEOSWISS SWITZERLAND CURRENT SUMMARY ===")
    log(f"Stationsreihen mit {year}-Daten: {len(records)}")
    log(f"Recent-Tagesdateien: {assets_used}")
    log(f"Stationstage: {station_days:,}")
    log(f"Datenzeitraum: {first_date} bis {last_date}")
    log(f"Neue historische Tagesrekorde: {len(events):,}")
    log(f"Output: {out}")
    log("MeteoSwiss Switzerland current OK.")
    return out


def self_test() -> None:
    baseline = {
        "records": {
            "BER": {
                "calendar_tmax": {"08-09": [30.0, "2003-08-09"]},
                "calendar_tmin": {"08-09": [5.0, "1970-08-09"]},
            }
        }
    }
    current = {
        "BER": {
            "calendar_tmax": {"08-09": [31.0, "2026-08-09"]},
            "calendar_tmin": {"08-09": [4.0, "2026-08-09"]},
        }
    }
    events = record_events(baseline, current)
    assert len(events) == 2
    assert {x["element"] for x in events} == {"TMIN", "TMAX"}
    print("MeteoSwiss Switzerland current-year self-test OK")


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
