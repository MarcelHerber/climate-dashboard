#!/usr/bin/env python3
"""CHMI Czechia current-year TMAX/TMIN cache."""
from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import update_chmi_czechia_station_cache as hist

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")


def log(msg=""):
    print(msg, flush=True)


def current_path(cache_dir, year):
    return Path(cache_dir) / f"chmi_czechia_current_{int(year)}_v{FORMAT_VERSION}.pkl.gz"


def baseline_calendar_extremes(baseline):
    out = {}
    for sid, st in baseline.get("stations", {}).items():
        mx = {}; mn = {}
        for ordv, tx, tn in zip(st.get("ordinals", []), st.get("tmax_tenths", []), st.get("tmin_tenths", [])):
            d = date.fromordinal(int(ordv)); key = f"{d.month:02d}-{d.day:02d}"
            if int(tx) != hist.MISSING_I16:
                x = int(tx) / 10.0
                if key not in mx or x > mx[key]: mx[key] = x
            if int(tn) != hist.MISSING_I16:
                x = int(tn) / 10.0
                if key not in mn or x < mn[key]: mn[key] = x
        out[sid] = {"tmax": mx, "tmin": mn}
    return out


def build_current(cache_dir, year, *, workers=12, force=False):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    output = current_path(cache_dir, year)
    if force:
        output.unlink(missing_ok=True)

    baseline = hist.load_baseline(cache_dir, int(year) - 1)
    hist_ids = set(baseline.get("stations", {}))
    current_meta = hist.latest_recent_meta()
    merged_meta = {sid: st.get("meta", {}) for sid, st in baseline.get("stations", {}).items()}
    merged_meta.update(current_meta)

    now = datetime.now(timezone.utc)
    months = range(1, now.month + 1) if int(year) == now.year else range(1, 13)
    jobs = []
    for month in months:
        urls = hist.index_month_urls(int(year), month)
        for sid, url in urls.items():
            if sid in merged_meta:
                jobs.append((month, sid, url))
        log(f"CHMI {year}-{month:02d}: {len(urls)} Dateien im Index")

    station_rows = defaultdict(dict); qrej = Counter(); invalid = Counter(); errors = []
    workers = max(1, min(int(workers), 20))
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(hist.parse_current_file, url, int(year)): (month, sid) for month, sid, url in jobs}
        done = 0
        for fut in as_completed(futs):
            month, sid = futs[fut]; done += 1
            try:
                rows, qr, iv = fut.result()
                for ds, vals in rows.items(): station_rows[sid][ds] = vals
                qrej.update(qr); invalid.update(iv)
            except Exception as exc:
                errors.append((sid, month, str(exc)))
            if done % 100 == 0 or done == len(futs):
                log(f"Current: {done}/{len(futs)} Dateien | Fehler {len(errors)}")

    cal = baseline_calendar_extremes(baseline)
    stations = {}; total_days = 0; first = None; last = None; record_events = 0
    for sid, rows in station_rows.items():
        dates = sorted(ds for ds, v in rows.items() if "TMA" in v or "TMI" in v)
        if not dates: continue
        ords = array("i"); tx = array("h"); tn = array("h")
        for ds in dates:
            v = rows[ds]; a = v.get("TMA"); b = v.get("TMI")
            if a is not None and b is not None and b > a:
                invalid["TMIN_GT_TMAX"] += 1; continue
            d = date.fromisoformat(ds); ords.append(d.toordinal())
            tx.append(hist.tenths(a) if a is not None else hist.MISSING_I16)
            tn.append(hist.tenths(b) if b is not None else hist.MISSING_I16)
            key = f"{d.month:02d}-{d.day:02d}"; old = cal.get(sid, {})
            if a is not None and key in old.get("tmax", {}) and a > old["tmax"][key]: record_events += 1
            if b is not None and key in old.get("tmin", {}) and b < old["tmin"][key]: record_events += 1
        if not ords: continue
        st = {
            "station_id": sid, "meta": merged_meta.get(sid, {}), "ordinals": ords,
            "tmax_tenths": tx, "tmin_tenths": tn,
            "start_date": date.fromordinal(ords[0]).isoformat(),
            "end_date": date.fromordinal(ords[-1]).isoformat(),
            "station_days": len(ords), "has_historical_baseline": sid in hist_ids,
        }
        stations[sid] = st; total_days += len(ords)
        if first is None or st["start_date"] < first: first = st["start_date"]
        if last is None or st["end_date"] > last: last = st["end_date"]

    if not stations:
        raise RuntimeError(f"CHMI Czechia current {year} enthält keine Stationsreihen.")

    out = {
        "source": hist.SOURCE, "public_url": hist.PUBLIC_URL,
        "country": hist.COUNTRY, "country_code": hist.COUNTRY_CODE,
        "format_version": FORMAT_VERSION, "year": int(year), "complete": True,
        "station_count": len(stations), "station_days": total_days,
        "start_date": first, "end_date": last, "stations": stations,
        "new_historical_daily_record_events": record_events,
        "quality_policy": "Only QUALITY=0 (Good) is accepted; 1/2/3/4/5 are excluded.",
        "quality_rejected": dict(qrej), "invalid_rejected": dict(invalid), "errors": errors,
    }
    hist.save_gz_pickle(output, out)
    log("=== CHMI CZECHIA CURRENT SUMMARY ===")
    log(f"Stationsreihen mit {year}-Daten: {len(stations):,}")
    log(f"Stationstage: {total_days:,}")
    log(f"Datenzeitraum: {first} bis {last}")
    log(f"Neue historische Tagesrekord-Ereignisse: {record_events:,}")
    log(f"QUALITY verworfen: {dict(qrej)}")
    log(f"QC verworfen: {dict(invalid)}")
    log(f"Download-/Parse-Fehler: {len(errors)}")
    log(f"Output: {output}")
    log("CHMI Czechia current OK.")
    return output


def load_current(cache_dir, year):
    path = current_path(cache_dir, year)
    if not path.exists():
        raise RuntimeError(f"CHMI Czechia Current fehlt: {path}")
    obj = hist.load_gz_pickle(path)
    if not isinstance(obj, dict) or not obj.get("complete") or int(obj.get("year", -1)) != int(year):
        raise RuntimeError(f"CHMI Czechia Current unvollständig/falsches Jahr: {path}")
    return obj


def self_test():
    assert current_path(Path("x"), 2026).name == "chmi_czechia_current_2026_v1.pkl.gz"
    baseline = {"stations": {"X": {"ordinals": array("i", [date(2025,1,1).toordinal()]), "tmax_tenths": array("h", [100]), "tmin_tenths": array("h", [-50])}}}
    cal = baseline_calendar_extremes(baseline)
    assert cal["X"]["tmax"]["01-01"] == 10.0
    assert cal["X"]["tmin"]["01-01"] == -5.0
    print("CHMI Czechia current self-test OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test(); return 0
    build_current(Path(args.cache_dir), args.year, workers=args.workers, force=args.force)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
