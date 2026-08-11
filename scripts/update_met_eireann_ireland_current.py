#!/usr/bin/env python3
"""Build Met Éireann current-year daily TMIN/TMAX cache for Ireland.

Uses the same official Met Éireann daily station files as the historical builder.
Only rows from the requested year are retained.

Requires:
  scripts/update_met_eireann_ireland_station_cache.py

That module provides the already-tested StationDetails and daily-file parsing
helpers. This current-year cache is independent of whether the historical
baseline has already finished building.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import pickle
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import update_met_eireann_ireland_station_cache as core

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")


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
            json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"met_eireann_ireland_current_{year}_v{FORMAT_VERSION}.pkl.gz"


def status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"met_eireann_ireland_current_{year}_status.json"


def parse_current_year(raw: bytes, year: int) -> dict[str, Any]:
    text = core.decode(raw)
    lines = text.splitlines()
    header_i = core.find_daily_header(lines)
    if header_i is None:
        raise RuntimeError("Messdaten-Header 'date,...' nicht gefunden.")

    import csv, io
    csv_text = "\n".join(lines[header_i:])
    first_line = lines[header_i]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    rows = list(csv.reader(io.StringIO(csv_text), delimiter=delimiter))
    if not rows:
        raise RuntimeError("Messdatenblock leer.")

    header = [c.strip().lstrip("\ufeff") for c in rows[0]]
    hn = [core.norm(x) for x in header]

    def col(name: str):
        n = core.norm(name)
        for i, h in enumerate(hn):
            if h == n:
                return i
        return None

    date_i = col("date")
    tx_i = col("maxtp")
    tn_i = col("mintp")

    if date_i is None:
        raise RuntimeError(f"Datumsspalte fehlt. Header: {' | '.join(header)}")
    if tx_i is None and tn_i is None:
        return {
            "record": None,
            "has_temperature_columns": False,
            "qc": {
                "qc_rejected_tmax": 0,
                "qc_rejected_tmin": 0,
                "qc_rejected_inconsistent_days": 0,
            },
        }

    tx_ind_i = core.indicator_before(header, tx_i) if tx_i is not None else None
    tn_ind_i = core.indicator_before(header, tn_i) if tn_i is not None else None

    rec = core.empty_record()
    qc = {
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
    }

    def cell(row, i):
        return row[i].strip() if i is not None and i < len(row) else ""

    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue

        d = core.parse_date(cell(row, date_i))
        if d is None or d.year != year:
            continue

        tx = core.parse_float(cell(row, tx_i))
        tn = core.parse_float(cell(row, tn_i))
        tn, tx = core.qc_values(tn, tx, qc)

        if tn is None and tx is None:
            continue

        if tx is not None and tx_ind_i is not None:
            code = cell(row, tx_ind_i) or "(blank)"
            rec["tmax_indicator_counts"][code] = rec["tmax_indicator_counts"].get(code, 0) + 1
        if tn is not None and tn_ind_i is not None:
            code = cell(row, tn_ind_i) or "(blank)"
            rec["tmin_indicator_counts"][code] = rec["tmin_indicator_counts"].get(code, 0) + 1

        core.consume_day(rec, d, tn, tx)

    return {
        "record": rec if rec["observation_days"] > 0 else None,
        "has_temperature_columns": True,
        "qc": qc,
    }


def fetch_station_current(sid: str, year: int) -> dict[str, Any]:
    urls = core.daily_urls(sid)
    errors = []
    seen_404 = 0

    for url in urls:
        try:
            raw = core.http_bytes(url, allow_404=True)
            if raw is None:
                seen_404 += 1
                continue
            parsed = parse_current_year(raw, year)
            return {
                "sid": sid,
                "status": "ok",
                "url": url,
                "record": parsed["record"],
                "has_temperature_columns": parsed["has_temperature_columns"],
                "qc": parsed["qc"],
            }
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    if seen_404 == len(urls):
        return {"sid": sid, "status": "missing"}

    if errors:
        raise RuntimeError("; ".join(errors))

    return {"sid": sid, "status": "missing"}


def build_current(cache_dir: Path, year: int, workers: int = 12) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)

    inventory, excluded_ni, station_details_url = core.load_inventory()

    print("=== MET ÉIREANN IRLAND CURRENT ===", flush=True)
    print(f"Jahr: {year}", flush=True)
    print(f"Inventar Republik Irland: {len(inventory):,}", flush=True)
    print(f"Ausgeschlossene Nordirland-Zeilen: {excluded_ni:,}", flush=True)
    print("Verwendet: maxtp=TMAX, mintp=TMIN; gmin/igmin ignoriert.", flush=True)

    records = {}
    missing = []
    no_temp = []
    errors = []
    qc_totals = {
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
    }

    workers = max(1, min(int(workers), 20))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch_station_current, sid, year): sid
            for sid in sorted(inventory, key=lambda x: int(x))
        }

        done = 0
        for fut in as_completed(futures):
            sid = futures[fut]
            done += 1
            try:
                result = fut.result()
                if result["status"] == "missing":
                    missing.append(sid)
                else:
                    if not result.get("has_temperature_columns"):
                        no_temp.append(sid)
                    rec = result.get("record")
                    if rec is not None:
                        records[sid] = rec

                    for key in qc_totals:
                        qc_totals[key] += int(result.get("qc", {}).get(key, 0))
            except Exception as exc:
                errors.append((sid, str(exc)))

            if done % 100 == 0 or done == len(inventory):
                print(
                    f"Fortschritt: {done:,}/{len(inventory):,} | "
                    f"2026-Reihen: {len(records):,} | "
                    f"fehlend: {len(missing):,} | Fehler: {len(errors):,}",
                    flush=True,
                )

    if errors:
        sample = "; ".join(f"{sid}: {msg}" for sid, msg in errors[:8])
        raise RuntimeError(
            f"Met Éireann Current: {len(errors)} Station(en) mit Download/Parser-Fehler. "
            f"Beispiele: {sample}"
        )

    observation_days = sum(int(r.get("observation_days", 0)) for r in records.values())
    first_dates = [r.get("first_date") for r in records.values() if r.get("first_date")]
    last_dates = [r.get("last_date") for r in records.values() if r.get("last_date")]

    hottest = None
    coldest = None
    for sid, rec in records.items():
        tx = rec.get("tmax_abs")
        if tx is not None:
            item = (float(tx[0]), tx[1], sid)
            if hottest is None or item[0] > hottest[0]:
                hottest = item
        tn = rec.get("tmin_abs")
        if tn is not None:
            item = (float(tn[0]), tn[1], sid)
            if coldest is None or item[0] < coldest[0]:
                coldest = item

    payload = {
        "format_version": FORMAT_VERSION,
        "complete": True,
        "source": core.SOURCE,
        "country": core.COUNTRY,
        "country_code": core.COUNTRY_CODE,
        "year": year,
        "station_details_url": station_details_url,
        "inventory": inventory,
        "records": records,
        "station_count": len(records),
        "inventory_count": len(inventory),
        "observation_days": observation_days,
        "first_date": min(first_dates) if first_dates else None,
        "last_date": max(last_dates) if last_dates else None,
        "missing_daily_station_ids": sorted(missing, key=lambda x: int(x)),
        "daily_without_temperature_ids": sorted(no_temp, key=lambda x: int(x)),
        "excluded_northern_ireland_inventory_rows": excluded_ni,
        **qc_totals,
        "parameters": {
            "TMAX": "maxtp",
            "TMIN": "mintp",
        },
        "ignored_temperature_like_fields": ["gmin", "igmin"],
        "hottest_tmax": {
            "value": hottest[0],
            "date": hottest[1],
            "station_id": hottest[2],
            "station_name": inventory.get(hottest[2], {}).get("name"),
        } if hottest else None,
        "coldest_tmin": {
            "value": coldest[0],
            "date": coldest[1],
            "station_id": coldest[2],
            "station_name": inventory.get(coldest[2], {}).get("name"),
        } if coldest else None,
    }

    out = current_path(cache_dir, year)
    atomic_pickle_gzip(out, payload)

    status = {
        "current_file": str(out),
        "complete": True,
        "source": core.SOURCE,
        "country": core.COUNTRY,
        "country_code": core.COUNTRY_CODE,
        "year": year,
        "inventory_count": len(inventory),
        "station_count": len(records),
        "observation_days": observation_days,
        "first_date": payload["first_date"],
        "last_date": payload["last_date"],
        "missing_daily_files": len(missing),
        "daily_files_without_temperature": len(no_temp),
        "qc_rejected_tmax": qc_totals["qc_rejected_tmax"],
        "qc_rejected_tmin": qc_totals["qc_rejected_tmin"],
        "qc_rejected_inconsistent_days": qc_totals["qc_rejected_inconsistent_days"],
        "hottest_tmax": payload["hottest_tmax"],
        "coldest_tmin": payload["coldest_tmin"],
    }
    atomic_json(status_path(cache_dir, year), status)

    print()
    print("=== MET ÉIREANN IRELAND CURRENT SUMMARY ===")
    print(f"Jahr: {year}")
    print(f"Stationsinventar: {len(inventory):,}")
    print(f"Stationen mit {year}-Temperaturdaten: {len(records):,}")
    print(f"Stationstage mit TMAX und/oder TMIN: {observation_days:,}")
    print(f"Datenzeitraum: {payload['first_date']} bis {payload['last_date']}")
    print(f"Fehlende Daily-Dateien: {len(missing):,}")
    print(f"Daily-Dateien ohne Temperatur: {len(no_temp):,}")
    print(
        "QC verworfen: "
        f"TMAX={qc_totals['qc_rejected_tmax']:,} | "
        f"TMIN={qc_totals['qc_rejected_tmin']:,} | "
        f"TMIN>TMAX={qc_totals['qc_rejected_inconsistent_days']:,}"
    )
    print(f"Höchstes TMAX: {payload['hottest_tmax']}")
    print(f"Niedrigstes TMIN: {payload['coldest_tmin']}")
    print(f"Output: {out}")
    print("Met Éireann Ireland Current-Cache vollständig OK.")
    return out


def self_test() -> None:
    fixture = """Station Name: TEST
date,ind,maxtp,ind,mintp,igmin,gmin,ind,rain
31-dec-2025,0,8.0,0,3.0,0,-1.0,0,0
01-jan-2026,0,9.5,0,2.1,0,-5.0,0,0
02-jan-2026,0,10.1,0,1.2,0,-8.0,0,0
01-jan-2027,0,99.0,0,-99.0,0,-99.0,0,0
"""
    parsed = parse_current_year(fixture.encode("utf-8"), 2026)
    rec = parsed["record"]
    assert rec is not None
    assert rec["observation_days"] == 2
    assert rec["first_date"] == "2026-01-01"
    assert rec["last_date"] == "2026-01-02"
    assert rec["tmax_abs"] == [10.1, "2026-01-02"]
    assert rec["tmin_abs"] == [1.2, "2026-01-02"]
    assert rec["tmin_abs"][0] != -8.0  # gmin must be ignored
    print("Met Éireann Ireland current-year self-test OK")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    p.add_argument("--year", type=int, default=date.today().year)
    p.add_argument("--workers", type=int, default=12)
    args = p.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_current(Path(args.cache_dir), args.year, workers=args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
