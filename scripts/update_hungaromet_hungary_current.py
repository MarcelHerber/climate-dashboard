#!/usr/bin/env python3
"""Build current-year Hungarian daily Tmin/Tmax records from HungaroMet HABP_1D recent ZIPs."""
from __future__ import annotations

import argparse
import json
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


def record_events(baseline: dict[str, Any], records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    old_records = baseline.get("records", {})
    events: list[dict[str, Any]] = []
    for sid, rec in records.items():
        old = old_records.get(sid)
        if not isinstance(old, dict):
            continue
        for mmdd, pair in rec.get("calendar_tmax", {}).items():
            prior = old.get("calendar_tmax", {}).get(mmdd)
            if prior is not None and float(pair[0]) > float(prior[0]):
                events.append({"station_id":sid,"date":pair[1],"element":"TMAX","value":float(pair[0]),"previous_value":float(prior[0]),"previous_date":str(prior[1])})
        for mmdd, pair in rec.get("calendar_tmin", {}).items():
            prior = old.get("calendar_tmin", {}).get(mmdd)
            if prior is not None and float(pair[0]) < float(prior[0]):
                events.append({"station_id":sid,"date":pair[1],"element":"TMIN","value":float(pair[0]),"previous_value":float(prior[0]),"previous_date":str(prior[1])})
    events.sort(key=lambda x:(x["date"],x["station_id"],x["element"]))
    return events


def fetch_station(url: str, year: int) -> tuple[str | None, list[tuple[date, float | None, float | None]]]:
    return hist.parse_obs_zip(hist.http_bytes(url), cutoff_year=year)


def build_current(cache_dir: Path, year: int, *, force: bool = False, workers: int = 14) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = current_path(cache_dir, year)
    if force:
        out.unlink(missing_ok=True); status_path(cache_dir, year).unlink(missing_ok=True)
    baseline = hist.load_baseline(cache_dir, year - 1)
    urls = hist.recent_inventory()
    inventory = dict(baseline.get("inventory", {}))
    inventory.update(hist.load_auto_metadata())
    log("=== HUNGAROMET UNGARN AKTUELLES JAHR ===")
    log(f"{year} | HABP_1D recent | Stations-ZIPs: {len(urls)}")

    records: dict[str, dict[str, Any]] = {}
    stats = {"qc_rejected_tmax":0,"qc_rejected_tmin":0,"qc_rejected_inconsistent_days":0}
    errors: list[tuple[str,str]] = []
    empty_files = 0
    workers = max(1, min(int(workers), 20))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch_station, url, year):(sid_hint,url) for sid_hint,url in urls.items()}
        done = 0
        for fut in as_completed(futs):
            sid_hint,url=futs[fut]; done += 1
            try:
                sid,rows=fut.result(); sid=sid or sid_hint
                if not rows:
                    empty_files += 1
                    continue
                rec=records.setdefault(sid,hist.empty_record())
                for d,tn0,tx0 in rows:
                    if d.year != year: continue
                    tn,tx=hist.qc_values(tn0,tx0,stats)
                    hist.consume_day(rec,d,tn,tx,"HUNGAROMET_HABP_CURRENT")
            except Exception as exc:
                errors.append((url,str(exc)))
            if done % 40 == 0 or done == len(futs):
                station_days=sum(int(r.get("observation_days",0)) for r in records.values())
                log(f"Current: {done}/{len(futs)} ZIPs | {len(records)} Stationen | {station_days:,} Stationstage | leer {empty_files} | Fehler {len(errors)}")

    if errors:
        sample="; ".join(f"{u.rsplit('/',1)[-1]}: {e}" for u,e in errors[:5])
        raise RuntimeError(f"HungaroMet Current: {len(errors)} ZIPs fehlgeschlagen. Beispiele: {sample}")
    records={sid:rec for sid,rec in records.items() if rec.get("tmax_abs") is not None or rec.get("tmin_abs") is not None}
    if not records:
        raise RuntimeError("HungaroMet Hungary Current enthält keine Temperatur-Stationen.")

    first_dates=[r["first_date"] for r in records.values() if r.get("first_date")]
    last_dates=[r["last_date"] for r in records.values() if r.get("last_date")]
    first_date=min(first_dates) if first_dates else None; last_date=max(last_dates) if last_dates else None
    station_days=sum(int(r.get("observation_days",0)) for r in records.values())
    latest_by_station={sid:r["last_date"] for sid,r in records.items() if r.get("last_date")}
    events=record_events(baseline,records)
    payload={
        "format_version":FORMAT_VERSION,"source":hist.SOURCE,"country":hist.COUNTRY,"country_code":hist.COUNTRY_CODE,
        "year":year,"complete":True,"parameters":{"TMIN":"tn","TMAX":"tx"},"inventory":inventory,"records":records,
        "latest_observation_by_station":latest_by_station,"data_first_date":first_date,"data_last_date":last_date,
        "rows_with_temperature":station_days,"record_events":events,"station_zip_count":len(urls),"empty_station_zip_count":empty_files,
        "qc_rejected_tmax":stats["qc_rejected_tmax"],"qc_rejected_tmin":stats["qc_rejected_tmin"],"qc_rejected_inconsistent_days":stats["qc_rejected_inconsistent_days"],
        "historical_cutoff_year":year-1,"historical_baseline_file":str(hist.baseline_path(cache_dir,year-1)),"public_url":hist.PUBLIC_URL,
    }
    hist.atomic_pickle_gzip(out,payload)
    hist.atomic_json(status_path(cache_dir,year),{
        "format_version":FORMAT_VERSION,"source":hist.SOURCE,"country":hist.COUNTRY,"year":year,"complete":True,
        "station_count":len(records),"inventory_count":len(inventory),"rows_with_temperature":station_days,
        "data_first_date":first_date,"data_last_date":last_date,"record_event_count":len(events),
        "station_zip_count":len(urls),"empty_station_zip_count":empty_files,"current_file":str(out),
    })
    log(); log("=== HUNGAROMET HUNGARY CURRENT SUMMARY ===")
    log(f"Stationsreihen mit {year}-Daten: {len(records):,}")
    log(f"Stationstage: {station_days:,}")
    log(f"Datenzeitraum: {first_date} bis {last_date}")
    log(f"Neue historische Tagesrekorde: {len(events):,}")
    log(f"ZIPs ohne Messdaten: {empty_files}")
    log(f"QC verworfen: TX={stats['qc_rejected_tmax']} | TN={stats['qc_rejected_tmin']} | TN>TX={stats['qc_rejected_inconsistent_days']}")
    log(f"Output: {out}")
    log("HungaroMet Hungary current OK.")
    return out


def load_current(cache_dir: Path, year: int) -> dict[str, Any]:
    path=current_path(cache_dir,year)
    if not path.exists(): raise RuntimeError(f"HungaroMet Current fehlt: {path}")
    obj=hist.load_pickle_gzip(path)
    if not isinstance(obj,dict) or obj.get("complete") is not True or int(obj.get("year",-1)) != int(year):
        raise RuntimeError(f"HungaroMet Current unvollständig/falsches Jahr: {path}")
    return obj


def self_test() -> None:
    baseline={"records":{"13704":{"calendar_tmax":{"07-28":[36.0,"2005-07-28"]},"calendar_tmin":{"07-28":[5.0,"2010-07-28"]}}}}
    current={"13704":{"calendar_tmax":{"07-28":[37.0,"2026-07-28"]},"calendar_tmin":{"07-28":[4.0,"2026-07-28"]}}}
    events=record_events(baseline,current)
    assert len(events)==2 and {x["element"] for x in events}=={"TMAX","TMIN"}
    assert current_path(Path("x"),2026).name == "hungaromet_hungary_current_2026_v1.pkl.gz"
    print("HungaroMet Hungary current-year self-test OK")


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--self-test",action="store_true"); parser.add_argument("--cache-dir",default=str(CACHE_DIR_DEFAULT)); parser.add_argument("--year",type=int,default=date.today().year); parser.add_argument("--force",action="store_true"); parser.add_argument("--workers",type=int,default=14); args=parser.parse_args()
    if args.self_test: self_test(); return 0
    build_current(Path(args.cache_dir),args.year,force=args.force,workers=args.workers); return 0

if __name__ == "__main__":
    raise SystemExit(main())
