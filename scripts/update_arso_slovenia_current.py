#!/usr/bin/env python3
"""Build the ARSO Slovenia current-year daily TMIN/TMAX cache.

This is the CURRENT step only. It does not modify the historical 1961-2025
baseline and does not integrate Slovenia into the unified Europe updater yet.

Requires:
  scripts/update_arso_slovenia_station_cache.py

The historical module already contains the tested official ARSO inventory,
monthly URL construction, parser and QC helpers.

For the requested current year this script:
- keeps only stations whose official ARSO period includes that year;
- downloads January through the current month (or all 12 months for a past year);
- accepts legitimate 404 / "Ni podatkov!" months;
- stores compact per-station record structures matching the historical cache;
- writes a separate current-year pickle + JSON status.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import pickle
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, UTC
from pathlib import Path
from typing import Any

import update_arso_slovenia_station_cache as core

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")


def atomic_pickle_gz(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as fh:
            pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
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


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / (
        f"arso_slovenia_current_{year}_v{FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"arso_slovenia_current_{year}_status.json"


def station_active_in_year(meta: dict[str, Any], year: int) -> bool:
    start = meta.get("start_year")
    end = meta.get("end_year")

    if isinstance(start, int) and year < start:
        return False
    if isinstance(end, int) and year > end:
        return False
    return True


def through_month_for_year(year: int, requested: int | None) -> int:
    if requested is not None:
        if not 1 <= requested <= 12:
            raise ValueError("--through-month muss zwischen 1 und 12 liegen.")
        return requested

    today = datetime.now(UTC).date()
    if year < today.year:
        return 12
    if year == today.year:
        return today.month
    raise ValueError(
        f"Jahr {year} liegt in der Zukunft; bitte ein aktuelles/vergangenes Jahr verwenden."
    )


def task_list(
    inventory: dict[str, dict[str, Any]],
    year: int,
    through_month: int,
) -> list[tuple[str, int, int]]:
    active = [
        sid
        for sid, meta in inventory.items()
        if station_active_in_year(meta, year)
    ]
    return [
        (sid, year, month)
        for sid in sorted(active)
        for month in range(1, through_month + 1)
    ]


def merge_month_into_record(
    rec: dict[str, Any],
    rows: list[tuple[date, float | None, float | None]],
    qc_totals: dict[str, int],
) -> int:
    used = 0
    for d, tmin, tmax in rows:
        tmin, tmax = core.qc_values(tmin, tmax, qc_totals)
        if core.consume_day(rec, d, tmin, tmax):
            used += 1
    return used


def build_current(
    cache_dir: Path,
    year: int,
    workers: int = 12,
    through_month: int | None = None,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)

    through_month = through_month_for_year(year, through_month)
    inventory, inventory_source = core.load_inventory()

    active_ids = [
        sid
        for sid, meta in inventory.items()
        if station_active_in_year(meta, year)
    ]
    tasks = task_list(inventory, year, through_month)

    print("=== ARSO SLOWENIEN CURRENT ===", flush=True)
    print(f"Jahr: {year}", flush=True)
    print(f"Bis einschließlich Monat: {through_month:02d}", flush=True)
    print(f"Offizielles Inventar gesamt: {len(inventory):,}", flush=True)
    print(
        f"Für {year} laut ARSO-Zeitraum aktive Stations-IDs: {len(active_ids):,}",
        flush=True,
    )
    print(f"Zu prüfende Stationsmonate: {len(tasks):,}", flush=True)
    print(f"Quelle: {inventory_source}", flush=True)

    records: dict[str, dict[str, Any]] = {
        sid: core.empty_record()
        for sid in active_ids
    }

    months_with_temperature = 0
    months_404 = 0
    months_no_data = 0
    errors: list[tuple[str, str]] = []

    qc_totals = {
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
    }

    workers = max(1, min(int(workers), 20))
    done = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(core.fetch_month, task): task
            for task in tasks
        }

        for fut in as_completed(futures):
            task = futures[fut]
            sid, _, month = task
            done += 1

            try:
                result = fut.result()
            except Exception as exc:
                errors.append(
                    (f"{sid}:{year:04d}{month:02d}", str(exc))
                )
                continue

            status = result.get("status")

            if status == "error":
                errors.append(
                    (
                        result.get("key", f"{sid}:{year:04d}{month:02d}"),
                        result.get("error", "unbekannter Fehler"),
                    )
                )
                continue

            if status == "missing_404":
                months_404 += 1
            elif status == "no_data":
                months_no_data += 1
            elif status == "ok":
                rows = result.get("rows", [])
                used = merge_month_into_record(
                    records[sid],
                    rows,
                    qc_totals,
                )
                if used > 0:
                    months_with_temperature += 1
                else:
                    months_no_data += 1
            else:
                errors.append(
                    (
                        result.get("key", f"{sid}:{year:04d}{month:02d}"),
                        f"unbekannter Status {status!r}",
                    )
                )

            if done % 100 == 0 or done == len(tasks):
                station_count_now = sum(
                    1
                    for rec in records.values()
                    if int(rec.get("observation_days", 0)) > 0
                )
                rows_now = sum(
                    int(rec.get("observation_days", 0))
                    for rec in records.values()
                )
                print(
                    f"Fortschritt: {done:,}/{len(tasks):,} Monate | "
                    f"{year}-Reihen: {station_count_now:,} | "
                    f"Temperatur-Tage: {rows_now:,} | "
                    f"Fehler: {len(errors):,}",
                    flush=True,
                )

    if errors:
        sample = "; ".join(
            f"{key}: {msg}"
            for key, msg in errors[:10]
        )
        raise RuntimeError(
            f"ARSO Current: {len(errors)} Stationsmonat/-monate mit "
            f"Download/Parser-Fehler. Beispiele: {sample}"
        )

    used_records = {
        sid: rec
        for sid, rec in records.items()
        if int(rec.get("observation_days", 0)) > 0
    }

    observation_days = sum(
        int(rec.get("observation_days", 0))
        for rec in used_records.values()
    )
    tmax_rows = sum(
        int(rec.get("tmax_days", 0))
        for rec in used_records.values()
    )
    tmin_rows = sum(
        int(rec.get("tmin_days", 0))
        for rec in used_records.values()
    )

    first_dates = [
        rec["first_date"]
        for rec in used_records.values()
        if rec.get("first_date")
    ]
    last_dates = [
        rec["last_date"]
        for rec in used_records.values()
        if rec.get("last_date")
    ]

    hottest = None
    coldest = None
    highest_tmin = None
    lowest_tmax = None

    for sid, rec in used_records.items():
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

        high_tn = rec.get("tmin_high_abs")
        if high_tn is not None:
            item = (float(high_tn[0]), high_tn[1], sid)
            if highest_tmin is None or item[0] > highest_tmin[0]:
                highest_tmin = item

        low_tx = rec.get("tmax_low_abs")
        if low_tx is not None:
            item = (float(low_tx[0]), low_tx[1], sid)
            if lowest_tmax is None or item[0] < lowest_tmax[0]:
                lowest_tmax = item

    def extreme_obj(item):
        if item is None:
            return None
        value, iso, sid = item
        return {
            "value": value,
            "date": iso,
            "station_id": sid,
            "station_name": inventory.get(sid, {}).get("name"),
        }

    payload = {
        "format_version": FORMAT_VERSION,
        "complete": True,
        "source": core.SOURCE,
        "country": core.COUNTRY,
        "country_code": core.COUNTRY_CODE,
        "year": year,
        "through_month": through_month,
        "inventory_source": inventory_source,
        "inventory": inventory,
        "eligible_station_ids": sorted(active_ids),
        "records": used_records,
        "inventory_count": len(inventory),
        "eligible_station_count": len(active_ids),
        "station_count": len(used_records),
        "month_task_count": len(tasks),
        "months_with_temperature": months_with_temperature,
        "months_404": months_404,
        "months_no_data": months_no_data,
        "observation_days": observation_days,
        "tmax_rows": tmax_rows,
        "tmin_rows": tmin_rows,
        "first_date": min(first_dates) if first_dates else None,
        "last_date": max(last_dates) if last_dates else None,
        **qc_totals,
        "parameters": {
            "TMAX": "tmax",
            "TMIN": "tmin",
            "date": "year/month from filename + dan",
            "unit": "degC",
        },
        "hottest_tmax": extreme_obj(hottest),
        "coldest_tmin": extreme_obj(coldest),
        "highest_tmin": extreme_obj(highest_tmin),
        "lowest_tmax": extreme_obj(lowest_tmax),
        "built_utc": datetime.now(UTC).isoformat(),
    }

    out = current_path(cache_dir, year)
    atomic_pickle_gz(out, payload)

    status = {
        "current_file": str(out),
        "complete": True,
        "source": core.SOURCE,
        "country": core.COUNTRY,
        "country_code": core.COUNTRY_CODE,
        "year": year,
        "through_month": through_month,
        "inventory_count": len(inventory),
        "eligible_station_count": len(active_ids),
        "station_count": len(used_records),
        "month_task_count": len(tasks),
        "months_with_temperature": months_with_temperature,
        "months_404": months_404,
        "months_no_data": months_no_data,
        "observation_days": observation_days,
        "tmax_rows": tmax_rows,
        "tmin_rows": tmin_rows,
        "first_date": payload["first_date"],
        "last_date": payload["last_date"],
        "qc_rejected_tmax": qc_totals["qc_rejected_tmax"],
        "qc_rejected_tmin": qc_totals["qc_rejected_tmin"],
        "qc_rejected_inconsistent_days": qc_totals[
            "qc_rejected_inconsistent_days"
        ],
        "hottest_tmax": payload["hottest_tmax"],
        "coldest_tmin": payload["coldest_tmin"],
        "highest_tmin": payload["highest_tmin"],
        "lowest_tmax": payload["lowest_tmax"],
        "updated_utc": datetime.now(UTC).isoformat(),
    }
    atomic_json(status_path(cache_dir, year), status)

    print()
    print("=" * 88)
    print("ARSO SLOWENIEN CURRENT · STATUS")
    print("=" * 88)
    print(json.dumps(status, indent=2, ensure_ascii=False))
    print()
    print(
        f"Stationsreihen mit {year}-Temperaturdaten: "
        f"{len(used_records):,}/{len(active_ids):,}"
    )
    print(f"Stationstage mit TMAX und/oder TMIN: {observation_days:,}")
    print(f"TMAX-Werte: {tmax_rows:,}")
    print(f"TMIN-Werte: {tmin_rows:,}")
    print(
        f"Datenzeitraum: {payload['first_date']} bis {payload['last_date']}"
    )
    print(
        f"Monate: {months_with_temperature:,} mit Temperatur | "
        f"{months_404:,} HTTP404 | {months_no_data:,} no-data/leer"
    )
    print(f"Höchstes TMAX: {payload['hottest_tmax']}")
    print(f"Niedrigstes TMIN: {payload['coldest_tmin']}")
    print(f"Höchstes TMIN: {payload['highest_tmin']}")
    print(f"Niedrigstes TMAX: {payload['lowest_tmax']}")
    print(f"Output: {out}")
    print("ARSO Slovenia Current-Cache vollständig OK.")

    return out


def self_test() -> None:
    inventory = {
        "001": {
            "start_year": 1961,
            "end_year": None,
        },
        "002": {
            "start_year": 2017,
            "end_year": None,
        },
        "003": {
            "start_year": 1961,
            "end_year": 2016,
        },
    }

    assert station_active_in_year(inventory["001"], 2026)
    assert station_active_in_year(inventory["002"], 2026)
    assert not station_active_in_year(inventory["003"], 2026)

    tasks = task_list(inventory, 2026, 8)
    assert len(tasks) == 16
    assert tasks[0] == ("001", 2026, 1)
    assert tasks[-1] == ("002", 2026, 8)

    sample = """Postaja: TEST
Avgust 2026

dan\tetp\trr\ttmin\ttmax\ttpov\ttmin5
1\t4.0\t0\t18.2\t31.5\t24.0\t15.0
2\t4.0\t0\t19.4\t33.1\t25.1\t16.0
3\t4.0\t0\t\t32.0\t25.0\t15.5
4\t4.0\t0\t17.0\t\t23.0\t14.5
"""
    rows = core.parse_month_text(sample, "001", 2026, 8)
    rec = core.empty_record()
    qc = {
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
    }
    used = merge_month_into_record(rec, rows, qc)

    assert used == 4
    assert rec["observation_days"] == 4
    assert rec["tmax_days"] == 3
    assert rec["tmin_days"] == 3
    assert rec["tmax_abs"] == [33.1, "2026-08-02"]
    assert rec["tmin_abs"] == [17.0, "2026-08-04"]
    assert rec["tmin_high_abs"] == [19.4, "2026-08-02"]
    assert rec["tmax_low_abs"] == [31.5, "2026-08-01"]

    print("ARSO Slovenia current-year self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=CACHE_DIR_DEFAULT,
    )
    parser.add_argument(
        "--year",
        type=int,
        default=datetime.now(UTC).year,
    )
    parser.add_argument(
        "--through-month",
        type=int,
        default=None,
        help=(
            "Optional letzter Monat 1-12. Standard: aktueller Monat "
            "für das laufende Jahr, sonst Dezember."
        ),
    )
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_current(
        cache_dir=args.cache_dir,
        year=args.year,
        workers=args.workers,
        through_month=args.through_month,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
