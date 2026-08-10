#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import pickle
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import update_frost_norway_station_cache as frost

SOURCE = frost.SOURCE
CURRENT_FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")


def log(msg: str = "") -> None:
    print(msg, flush=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"frost_norway_current_{year}_v{CURRENT_FORMAT_VERSION}.pkl.gz"


def current_status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"frost_norway_current_{year}_status.json"


def load_pickle_gzip(path: Path) -> Any:
    with gzip.open(path, "rb") as f:
        return pickle.load(f)


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
        tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def fetch_current_inventory(client_id: str, year: int, end_exclusive: date) -> dict[str, dict[str, Any]]:
    rows = frost.paged_data(
        "/sources/v0.jsonld",
        client_id,
        {
            "types": "SensorSystem",
            "country": "NO",
            "elements": frost.ELEMENTS,
            "validtime": f"{year}-01-01/{end_exclusive.isoformat()}",
        },
    )
    inventory: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = frost.canonical_station_id(row.get("id") or row.get("sourceId") or "")
        if not sid or not frost.is_metno_holder(row):
            continue
        inventory[sid] = frost.inventory_entry(row)

    if not inventory:
        raise RuntimeError(f"Keine MET.NO-Frost-Stationen für {year} gefunden.")

    log(f"Frost aktuelles Inventar {year}: {len(inventory)} MET.NO-Stationen mit täglichem Tmax+Tmin.")
    return inventory


def chunks(values: list[str], n: int) -> list[list[str]]:
    return [values[i:i+n] for i in range(0, len(values), n)]


def fetch_current_rows(client_id: str, station_ids: list[str], start: date, end_exclusive: date):
    result = []
    all_chunks = chunks(sorted(station_ids), frost.SOURCE_CHUNK_SIZE)
    for i, source_chunk in enumerate(all_chunks, 1):
        raw = frost.fetch_observations_resilient(client_id, source_chunk, start, end_exclusive)
        flat = frost.flatten_best_observations(raw, start, end_exclusive)
        result.extend(flat)
        log(f"Frost current: Chunk {i}/{len(all_chunks)} | {len(source_chunk)} Stationen | {len(flat):,} Stationstage.")
    return result


def detect_record_events(historical: dict[str, Any], rows) -> list[dict[str, Any]]:
    historical_records = historical.get("records", {})
    events: list[dict[str, Any]] = []

    for station_id, d, tn, tx in rows:
        hist = historical_records.get(station_id)
        if not isinstance(hist, dict):
            continue

        mmdd = d.strftime("%m-%d")
        iso = d.isoformat()

        if tx is not None:
            old = hist.get("calendar_tmax", {}).get(mmdd)
            if isinstance(old, (list, tuple)) and len(old) >= 2:
                old_value = float(old[0])
                if tx > old_value:
                    events.append({
                        "station_id": station_id,
                        "date": iso,
                        "kind": "TMAX",
                        "value": round(tx, 1),
                        "previous_value": round(old_value, 1),
                        "previous_date": str(old[1]),
                        "delta": round(tx - old_value, 1),
                        "source": SOURCE,
                    })

        if tn is not None:
            old = hist.get("calendar_tmin", {}).get(mmdd)
            if isinstance(old, (list, tuple)) and len(old) >= 2:
                old_value = float(old[0])
                if tn < old_value:
                    events.append({
                        "station_id": station_id,
                        "date": iso,
                        "kind": "TMIN",
                        "value": round(tn, 1),
                        "previous_value": round(old_value, 1),
                        "previous_date": str(old[1]),
                        "delta": round(tn - old_value, 1),
                        "source": SOURCE,
                    })

    events.sort(key=lambda x: (x["date"], x["station_id"], x["kind"]))
    return events


def build_current(client_id: str, cache_dir: Path, year: int) -> Path:
    cutoff_year = year - 1
    hist_path = frost.baseline_path(cache_dir, cutoff_year)

    if not frost.valid_final(hist_path, cutoff_year):
        raise RuntimeError(f"Fertige Frost-Historienbaseline fehlt oder ist ungültig: {hist_path}")

    historical = load_pickle_gzip(hist_path)
    today = date.today()

    if year != today.year:
        raise RuntimeError(f"Current-Workflow erwartet {today.year}, angefordert wurde {year}.")

    start = date(year, 1, 1)
    # Frost intervals are end-exclusive; tomorrow includes today's reference date
    # if the daily aggregate is already available.
    end_exclusive = today + timedelta(days=1)

    inventory = fetch_current_inventory(client_id, year, end_exclusive)
    rows = fetch_current_rows(client_id, list(inventory), start, end_exclusive)

    current_records: dict[str, dict[str, Any]] = {}
    consumed = frost.consume_rows(current_records, rows)
    events = detect_record_events(historical, rows)

    latest_by_station = {
        sid: rec.get("last_date")
        for sid, rec in current_records.items()
        if rec.get("last_date")
    }

    payload = {
        "format_version": CURRENT_FORMAT_VERSION,
        "source": SOURCE,
        "year": year,
        "historical_cutoff_year": cutoff_year,
        "historical_baseline_file": str(hist_path),
        "inventory": inventory,
        "records": current_records,
        "record_events": events,
        "latest_observation_by_station": latest_by_station,
        "rows_with_temperature": consumed,
        "station_count": len(current_records),
        "inventory_count": len(inventory),
        "data_first": min((rec["first_date"] for rec in current_records.values() if rec.get("first_date")), default=None),
        "data_last": max((rec["last_date"] for rec in current_records.values() if rec.get("last_date")), default=None),
        "complete_through_request_date": today.isoformat(),
    }

    out = current_path(cache_dir, year)
    atomic_pickle_gzip(out, payload)

    status = {
        "format_version": CURRENT_FORMAT_VERSION,
        "source": SOURCE,
        "year": year,
        "historical_cutoff_year": cutoff_year,
        "historical_baseline_file": str(hist_path),
        "current_file": str(out),
        "inventory_count": len(inventory),
        "station_count": len(current_records),
        "rows_with_temperature": consumed,
        "data_first": payload["data_first"],
        "data_last": payload["data_last"],
        "record_event_count": len(events),
        "request_date": today.isoformat(),
    }
    atomic_json(current_status_path(cache_dir, year), status)

    log("=== FROST NORWAY CURRENT SUMMARY ===")
    log(f"Jahr: {year}")
    log(f"Inventar MET.NO: {len(inventory)}")
    log(f"Stationsreihen mit Daten: {len(current_records)}")
    log(f"Temperatur-Zeilen: {consumed:,}")
    log(f"Datenzeitraum: {payload['data_first']} bis {payload['data_last']}")
    log(f"Neue historische Tagesrekorde: {len(events)}")
    log(f"Output: {out}")
    log("Frost Norway current OK.")
    return out


def self_test() -> None:
    historical = {
        "records": {
            "SN1": {
                "calendar_tmax": {"07-01": [30.0, "1990-07-01"]},
                "calendar_tmin": {"07-01": [5.0, "1980-07-01"]},
            }
        }
    }
    rows = [
        ("SN1", date(2026, 7, 1), 4.0, 31.0),
        ("SN2", date(2026, 7, 1), -10.0, 40.0),
    ]
    events = detect_record_events(historical, rows)
    assert len(events) == 2
    assert {e["kind"] for e in events} == {"TMAX", "TMIN"}
    assert all(e["station_id"] == "SN1" for e in events)

    recs: dict[str, dict[str, Any]] = {}
    frost.consume_rows(recs, rows)
    assert recs["SN1"]["last_date"] == "2026-07-01"
    assert recs["SN2"]["tmax_abs"] == [40.0, "2026-07-01"]
    print("Frost Norway current self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--year", type=int, default=date.today().year)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    client_id = os.environ.get("FROST_CLIENT_ID", "").strip()
    if not client_id:
        raise SystemExit("FROST_CLIENT_ID fehlt.")

    build_current(client_id, Path(args.cache_dir), args.year)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
