#!/usr/bin/env python3
"""Build an independent current-year Hungarian Tmin/Tmax cache from HungaroMet HABP_1D recent ZIPs.

This step intentionally does NOT require the historical Hungarian baseline to be complete.
It reuses only parsing/QC helpers from update_hungaromet_hungary_station_cache.py.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import update_hungaromet_hungary_station_cache as hist

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")


def log(msg: str = "") -> None:
    print(msg, flush=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"hungaromet_hungary_current_{year}_v{FORMAT_VERSION}.pkl.gz"


def status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"hungaromet_hungary_current_{year}_status.json"


def fetch_station(url: str, year: int) -> tuple[str | None, list[tuple[date, float | None, float | None]]]:
    # cutoff_year keeps the parser future-proof if an archive unexpectedly contains later rows.
    return hist.parse_obs_zip(hist.http_bytes(url), cutoff_year=year)


def build_current(cache_dir: Path, year: int, *, force: bool = False, workers: int = 14) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = current_path(cache_dir, year)
    status = status_path(cache_dir, year)
    if force:
        out.unlink(missing_ok=True)
        status.unlink(missing_ok=True)

    urls = hist.recent_inventory()
    if not urls:
        raise RuntimeError("HungaroMet recent inventory enthält keine Stations-ZIPs.")

    inventory = hist.load_auto_metadata()
    log("=== HUNGAROMET UNGARN · AKTUELLES JAHR ===")
    log(f"Jahr: {year}")
    log(f"HABP_1D recent Stations-ZIPs: {len(urls):,}")
    log(f"Automaten-Metadaten: {len(inventory):,} Stationseinträge")

    records: dict[str, dict[str, Any]] = {}
    stats = {
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
    }
    errors: list[tuple[str, str]] = []
    empty_files = 0
    workers = max(1, min(int(workers), 20))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch_station, url, year): (sid_hint, url)
            for sid_hint, url in urls.items()
        }
        done = 0
        for future in as_completed(futures):
            sid_hint, url = futures[future]
            done += 1
            try:
                sid, rows = future.result()
                sid = sid or sid_hint
                if not rows:
                    empty_files += 1
                    continue

                rec = records.setdefault(sid, hist.empty_record())
                for d, tn0, tx0 in rows:
                    if d.year != year:
                        continue
                    tn, tx = hist.qc_values(tn0, tx0, stats)
                    hist.consume_day(rec, d, tn, tx, "HUNGAROMET_HABP_CURRENT")
            except Exception as exc:
                errors.append((url, str(exc)))

            if done % 40 == 0 or done == len(futures):
                station_days = sum(int(r.get("observation_days", 0)) for r in records.values())
                log(
                    f"Current: {done}/{len(futures)} ZIPs | "
                    f"{len(records)} Stationen | {station_days:,} Stationstage | "
                    f"leer {empty_files} | Fehler {len(errors)}"
                )

    # A broken live download should not silently produce a supposedly complete cache.
    if errors:
        sample = "; ".join(
            f"{url.rsplit('/', 1)[-1]}: {err}" for url, err in errors[:8]
        )
        raise RuntimeError(
            f"HungaroMet Current: {len(errors)} Stations-ZIPs fehlgeschlagen. "
            f"Beispiele: {sample}"
        )

    records = {
        sid: rec
        for sid, rec in records.items()
        if rec.get("tmax_abs") is not None or rec.get("tmin_abs") is not None
    }
    if not records:
        raise RuntimeError(f"HungaroMet Hungary Current {year} enthält keine Temperaturdaten.")

    first_dates = [r["first_date"] for r in records.values() if r.get("first_date")]
    last_dates = [r["last_date"] for r in records.values() if r.get("last_date")]
    first_date = min(first_dates) if first_dates else None
    last_date = max(last_dates) if last_dates else None
    station_days = sum(int(r.get("observation_days", 0)) for r in records.values())
    latest_by_station = {
        sid: r["last_date"] for sid, r in records.items() if r.get("last_date")
    }

    hottest = None
    coldest = None
    for sid, rec in records.items():
        tx = rec.get("tmax_abs")
        tn = rec.get("tmin_abs")
        if tx is not None and (hottest is None or float(tx[0]) > float(hottest[0])):
            hottest = [float(tx[0]), str(tx[1]), sid]
        if tn is not None and (coldest is None or float(tn[0]) < float(coldest[0])):
            coldest = [float(tn[0]), str(tn[1]), sid]

    payload = {
        "format_version": FORMAT_VERSION,
        "source": hist.SOURCE,
        "country": hist.COUNTRY,
        "country_code": hist.COUNTRY_CODE,
        "year": year,
        "complete": True,
        "parameters": {"TMIN": "tn", "TMAX": "tx"},
        "inventory": inventory,
        "records": records,
        "latest_observation_by_station": latest_by_station,
        "data_first_date": first_date,
        "data_last_date": last_date,
        "rows_with_temperature": station_days,
        "station_zip_count": len(urls),
        "empty_station_zip_count": empty_files,
        "qc_rejected_tmax": stats["qc_rejected_tmax"],
        "qc_rejected_tmin": stats["qc_rejected_tmin"],
        "qc_rejected_inconsistent_days": stats["qc_rejected_inconsistent_days"],
        "hottest_tmax": hottest,
        "coldest_tmin": coldest,
        "public_url": hist.PUBLIC_URL,
        "historical_baseline_required": False,
    }

    hist.atomic_pickle_gzip(out, payload)
    hist.atomic_json(
        status,
        {
            "format_version": FORMAT_VERSION,
            "source": hist.SOURCE,
            "country": hist.COUNTRY,
            "year": year,
            "complete": True,
            "station_count": len(records),
            "inventory_count": len(inventory),
            "rows_with_temperature": station_days,
            "data_first_date": first_date,
            "data_last_date": last_date,
            "station_zip_count": len(urls),
            "empty_station_zip_count": empty_files,
            "qc_rejected_tmax": stats["qc_rejected_tmax"],
            "qc_rejected_tmin": stats["qc_rejected_tmin"],
            "qc_rejected_inconsistent_days": stats["qc_rejected_inconsistent_days"],
            "hottest_tmax": hottest,
            "coldest_tmin": coldest,
            "current_file": str(out),
        },
    )

    log()
    log("=== HUNGAROMET HUNGARY CURRENT SUMMARY ===")
    log(f"Stationsreihen mit {year}-Daten: {len(records):,}")
    log(f"Stationstage: {station_days:,}")
    log(f"Datenzeitraum: {first_date} bis {last_date}")
    log(f"ZIPs ohne Messdaten: {empty_files}")
    log(
        "QC verworfen: "
        f"TX={stats['qc_rejected_tmax']} | "
        f"TN={stats['qc_rejected_tmin']} | "
        f"TN>TX={stats['qc_rejected_inconsistent_days']}"
    )
    if hottest:
        log(f"Höchstes TX {year}: {hottest[0]:.1f} °C | {hottest[1]} | Station {hottest[2]}")
    if coldest:
        log(f"Niedrigstes TN {year}: {coldest[0]:.1f} °C | {coldest[1]} | Station {coldest[2]}")
    log(f"Output: {out}")
    log(f"Status: {status}")
    log("HungaroMet Hungary current OK.")
    return out


def load_current(cache_dir: Path, year: int) -> dict[str, Any]:
    path = current_path(cache_dir, year)
    if not path.exists():
        raise RuntimeError(f"HungaroMet Current fehlt: {path}")
    obj = hist.load_pickle_gzip(path)
    if (
        not isinstance(obj, dict)
        or obj.get("complete") is not True
        or int(obj.get("year", -1)) != int(year)
    ):
        raise RuntimeError(f"HungaroMet Current unvollständig/falsches Jahr: {path}")
    return obj


def self_test() -> None:
    assert current_path(Path("x"), 2026).name == "hungaromet_hungary_current_2026_v1.pkl.gz"
    stats = {"qc_rejected_tmax": 0, "qc_rejected_tmin": 0, "qc_rejected_inconsistent_days": 0}
    tn, tx = hist.qc_values(-5.0, 12.3, stats)
    assert tn == -5.0 and tx == 12.3
    tn, tx = hist.qc_values(20.0, 10.0, stats)
    assert tn is None and tx is None
    rec = hist.empty_record()
    assert hist.consume_day(rec, date(2026, 1, 1), -5.0, 12.3, "TEST")
    assert rec["tmax_abs"] == [12.3, "2026-01-01"]
    assert rec["tmin_abs"] == [-5.0, "2026-01-01"]
    print("HungaroMet Hungary current-year self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=14)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_current(
        Path(args.cache_dir),
        args.year,
        force=args.force,
        workers=args.workers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
