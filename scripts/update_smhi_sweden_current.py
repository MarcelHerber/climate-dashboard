#!/usr/bin/env python3
"""
Build/update compact current-year Swedish daily Tmin/Tmax state from SMHI.

Policy:
- CORE stations only.
- Historical baseline is quality G only.
- Current-year corrected-archive values (G) are preferred.
- latest-months values with quality G or Y are accepted as current/provisional.
- On overlapping days a G value always overrides a Y value.
- Current cache is persistent and accumulates the year, so days that later
  fall out of latest-months are retained.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import pickle
import tempfile
import urllib.error
from datetime import date
from pathlib import Path
from typing import Any

import update_smhi_sweden_station_cache as hist

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
ACCEPTED_CURRENT_QUALITY = {"G", "Y"}


def log(msg: str = "") -> None:
    print(msg, flush=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"smhi_sweden_current_{year}_v{FORMAT_VERSION}.pkl.gz"


def progress_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"smhi_sweden_current_{year}_progress_v{FORMAT_VERSION}.pkl.gz"


def status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"smhi_sweden_current_{year}_status.json"


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


def load_pickle_gzip(path: Path) -> Any:
    with gzip.open(path, "rb") as f:
        return pickle.load(f)


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


def latest_months_url(parameter: int, station: str) -> str:
    return (
        f"{hist.BASE}/parameter/{parameter}/station/{station}/"
        "period/latest-months/data.json"
    )


def json_values(raw: bytes, *, year: int) -> list[tuple[date, float, str]]:
    payload = json.loads(raw.decode("utf-8"))
    values = payload.get("value") or []
    result = []

    if not isinstance(values, list):
        return result

    for item in values:
        if not isinstance(item, dict):
            continue

        d = None
        for key in ("ref", "date", "from"):
            d = hist.parse_time_date(item.get(key))
            if d is not None:
                break
        if d is None or d.year != year:
            continue

        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue

        if not math.isfinite(value) or value < -90 or value > 65:
            continue

        quality = str(item.get("quality") or "").strip()
        if quality not in ACCEPTED_CURRENT_QUALITY:
            continue

        result.append((d, value, quality))

    return result


def quality_rank(q: str) -> int:
    return {"G": 2, "Y": 1}.get(q, 0)


def merge_value(
    state: dict[str, dict[str, dict[str, Any]]],
    sid: str,
    d: date,
    element: str,
    value: float,
    quality: str,
) -> None:
    day_key = d.isoformat()
    station = state.setdefault(sid, {})
    day = station.setdefault(day_key, {})
    old = day.get(element)

    candidate = {
        "value": round(float(value), 1),
        "quality": quality,
    }

    # Corrected G always replaces provisional Y. For equal quality, the newer
    # run's value is used, allowing later SMHI corrections to propagate.
    if old is None or quality_rank(quality) >= quality_rank(str(old.get("quality", ""))):
        day[element] = candidate


def active_common_inventory() -> tuple[dict[str, dict[str, Any]], list[str]]:
    tmin = hist.station_map(hist.PARAM_TMIN)
    tmax = hist.station_map(hist.PARAM_TMAX)
    inventory, common = hist.merge_inventory(tmin, tmax)
    active = [sid for sid in common if inventory[sid].get("active")]
    return inventory, active


def rows_to_compact_records(
    raw_state: dict[str, dict[str, dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], dict[str, int], dict[str, str]]:
    records: dict[str, dict[str, Any]] = {}
    quality_counts: dict[str, int] = {}
    latest_by_station: dict[str, str] = {}

    for sid, days in raw_state.items():
        for iso in sorted(days):
            try:
                d = date.fromisoformat(iso)
            except ValueError:
                continue

            pair = days[iso]
            tn_obj = pair.get("TMIN")
            tx_obj = pair.get("TMAX")

            tn = float(tn_obj["value"]) if isinstance(tn_obj, dict) else None
            tx = float(tx_obj["value"]) if isinstance(tx_obj, dict) else None

            if tn_obj:
                q = str(tn_obj.get("quality") or "")
                quality_counts[q] = quality_counts.get(q, 0) + 1
            if tx_obj:
                q = str(tx_obj.get("quality") or "")
                quality_counts[q] = quality_counts.get(q, 0) + 1

            if hist.consume_day(records, sid, d, tn, tx):
                latest_by_station[sid] = iso

    return records, quality_counts, latest_by_station


def record_events(
    historical: dict[str, Any],
    raw_state: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    baseline = historical.get("records", {})
    events = []

    for sid, days in raw_state.items():
        old = baseline.get(sid)
        if not isinstance(old, dict):
            continue

        for iso, pair in days.items():
            try:
                d = date.fromisoformat(iso)
            except ValueError:
                continue
            mmdd = d.strftime("%m-%d")

            tx_obj = pair.get("TMAX")
            if isinstance(tx_obj, dict):
                prior = old.get("calendar_tmax", {}).get(mmdd)
                value = float(tx_obj["value"])
                if prior is not None and value > float(prior[0]):
                    events.append(
                        {
                            "station_id": sid,
                            "date": iso,
                            "element": "TMAX",
                            "value": round(value, 1),
                            "quality": tx_obj.get("quality"),
                            "provisional": tx_obj.get("quality") != "G",
                            "previous_value": round(float(prior[0]), 1),
                            "previous_date": str(prior[1]),
                        }
                    )

            tn_obj = pair.get("TMIN")
            if isinstance(tn_obj, dict):
                prior = old.get("calendar_tmin", {}).get(mmdd)
                value = float(tn_obj["value"])
                if prior is not None and value < float(prior[0]):
                    events.append(
                        {
                            "station_id": sid,
                            "date": iso,
                            "element": "TMIN",
                            "value": round(value, 1),
                            "quality": tn_obj.get("quality"),
                            "provisional": tn_obj.get("quality") != "G",
                            "previous_value": round(float(prior[0]), 1),
                            "previous_date": str(prior[1]),
                        }
                    )

    events.sort(key=lambda x: (x["date"], x["station_id"], x["element"]))
    return events


def make_progress(year: int, inventory: dict[str, Any], active_ids: list[str]) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "source": hist.SOURCE,
        "year": year,
        "inventory": inventory,
        "active_station_ids": active_ids,
        "processed_station_ids": [],
        "raw_state": {},
        "bootstrap_archive_station_count": 0,
        "latest_months_station_count": 0,
        "complete": False,
    }


def write_status(cache_dir: Path, year: int, payload: dict[str, Any]) -> None:
    status = {
        "format_version": FORMAT_VERSION,
        "source": hist.SOURCE,
        "year": year,
        "complete": bool(payload.get("complete")),
        "active_station_candidates": len(payload.get("active_station_ids", [])),
        "processed_stations": len(payload.get("processed_station_ids", [])),
        "station_count": len(payload.get("records", {})),
        "data_first_date": payload.get("data_first_date"),
        "data_last_date": payload.get("data_last_date"),
        "rows_with_temperature": payload.get("rows_with_temperature", 0),
        "quality_counts": payload.get("quality_counts", {}),
        "record_event_count": len(payload.get("record_events", [])),
        "provisional_record_event_count": sum(
            1 for e in payload.get("record_events", []) if e.get("provisional")
        ),
        "current_file": str(current_path(cache_dir, year)),
        "historical_baseline_file": str(
            hist.baseline_path(cache_dir, year - 1)
        ),
    }
    atomic_json(status_path(cache_dir, year), status)


def build_current(
    cache_dir: Path,
    year: int,
    *,
    force: bool = False,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = current_path(cache_dir, year)
    prog = progress_path(cache_dir, year)

    baseline = hist.load_baseline(cache_dir, year - 1)
    inventory, active_ids = active_common_inventory()

    previous_state: dict[str, Any] = {}
    if not force and out.exists():
        try:
            old = load_pickle_gzip(out)
            if old.get("year") == year:
                previous_state = dict(old.get("raw_state", {}))
        except Exception:
            previous_state = {}

    if not force and prog.exists():
        try:
            progress = load_pickle_gzip(prog)
            if progress.get("year") != year:
                progress = make_progress(year, inventory, active_ids)
        except Exception:
            progress = make_progress(year, inventory, active_ids)
    else:
        progress = make_progress(year, inventory, active_ids)

    progress["inventory"] = inventory
    progress["active_station_ids"] = active_ids

    # Retain already accumulated current-year days from previous successful runs.
    for sid, days in previous_state.items():
        progress["raw_state"].setdefault(sid, {}).update(days)

    done = set(progress.get("processed_station_ids", []))

    log("=== SMHI SCHWEDEN AKTUELLES JAHR ===")
    log(
        f"Jahr {year} | {len(active_ids)} aktive CORE-Stationen | "
        "corrected-archive bootstrap + latest-months"
    )

    for idx, sid in enumerate(active_ids, 1):
        if sid in done:
            continue

        # First ever run for this station/year: recover Jan..archive-last-date
        # from corrected archive. Later runs reuse accumulated raw_state and
        # therefore do not redownload the full historical CSV.
        needs_bootstrap = sid not in previous_state and sid not in progress["raw_state"]

        if needs_bootstrap:
            archive_ok = False
            for parameter, element in (
                (hist.PARAM_TMIN, "TMIN"),
                (hist.PARAM_TMAX, "TMAX"),
            ):
                raw = hist.request_bytes(
                    hist.archive_url(parameter, sid),
                    allow_404=True,
                )
                if not raw:
                    continue
                rows = hist.parse_corrected_archive(raw, cutoff_year=year)
                for d, value, quality in rows:
                    if d.year != year or quality not in ACCEPTED_CURRENT_QUALITY:
                        continue
                    merge_value(
                        progress["raw_state"],
                        sid,
                        d,
                        element,
                        value,
                        quality,
                    )
                    archive_ok = True

            if archive_ok:
                progress["bootstrap_archive_station_count"] += 1

        latest_ok = False
        for parameter, element in (
            (hist.PARAM_TMIN, "TMIN"),
            (hist.PARAM_TMAX, "TMAX"),
        ):
            try:
                raw = hist.request_bytes(
                    latest_months_url(parameter, sid),
                    allow_404=True,
                )
            except urllib.error.HTTPError:
                raw = None
            if not raw:
                continue

            for d, value, quality in json_values(raw, year=year):
                merge_value(
                    progress["raw_state"],
                    sid,
                    d,
                    element,
                    value,
                    quality,
                )
                latest_ok = True

        if latest_ok:
            progress["latest_months_station_count"] += 1

        progress["processed_station_ids"].append(sid)
        done.add(sid)
        atomic_pickle_gzip(prog, progress)

        if len(done) % 20 == 0 or len(done) == len(active_ids):
            log(
                f"SMHI current: {len(done)}/{len(active_ids)} Stationen | "
                f"{len(progress['raw_state'])} mit Jahresdaten."
            )

    records, quality_counts, latest_by_station = rows_to_compact_records(
        progress["raw_state"]
    )

    if not records:
        raise RuntimeError("SMHI current enthält keine Stationsreihen.")

    all_dates = [
        date.fromisoformat(iso)
        for days in progress["raw_state"].values()
        for iso in days
    ]
    first_date = min(all_dates)
    last_date = max(all_dates)
    events = record_events(baseline, progress["raw_state"])

    payload = {
        **progress,
        "complete": True,
        "records": records,
        "quality_counts": quality_counts,
        "latest_observation_by_station": latest_by_station,
        "data_first_date": first_date.isoformat(),
        "data_last_date": last_date.isoformat(),
        "rows_with_temperature": sum(
            int(rec.get("observation_days", 0)) for rec in records.values()
        ),
        "record_events": events,
        "historical_cutoff_year": year - 1,
        "historical_baseline_file": str(
            hist.baseline_path(cache_dir, year - 1)
        ),
        "quality_policy": (
            "Current-year G and Y are accepted. G is controlled/approved; "
            "Y is provisional/roughly controlled or uncontrolled real-time. "
            "On overlap, G overrides Y."
        ),
    }

    atomic_pickle_gzip(out, payload)
    write_status(cache_dir, year, payload)
    prog.unlink(missing_ok=True)

    log()
    log("=== SMHI SWEDEN CURRENT SUMMARY ===")
    log(f"Stationsreihen mit {year}-Daten: {len(records)}")
    log(f"Stationstage: {payload['rows_with_temperature']:,}")
    log(f"Datenzeitraum: {first_date} bis {last_date}")
    log(f"Qualitätscodes: {quality_counts}")
    log(f"Neue historische Tagesrekorde: {len(events):,}")
    log(
        "Davon vorläufig (Y): "
        f"{sum(1 for e in events if e.get('provisional')):,}"
    )
    log(f"Output: {out}")
    log("SMHI Sweden current OK.")
    return out


def self_test() -> None:
    sample = {
        "value": [
            {
                "from": "2026-04-01T18:00:00Z",
                "to": "2026-04-02T18:00:00Z",
                "ref": "2026-04-02",
                "value": "-5.1",
                "quality": "Y",
            }
        ]
    }
    raw = json.dumps(sample).encode("utf-8")
    assert json_values(raw, year=2026) == [
        (date(2026, 4, 2), -5.1, "Y")
    ]

    state: dict[str, dict[str, dict[str, Any]]] = {}
    merge_value(state, "83270", date(2026, 4, 2), "TMIN", -5.1, "Y")
    merge_value(state, "83270", date(2026, 4, 2), "TMIN", -5.0, "G")
    assert state["83270"]["2026-04-02"]["TMIN"] == {
        "value": -5.0,
        "quality": "G",
    }

    # A later Y may not replace an already corrected G.
    merge_value(state, "83270", date(2026, 4, 2), "TMIN", -5.2, "Y")
    assert state["83270"]["2026-04-02"]["TMIN"]["value"] == -5.0

    print("SMHI Sweden current-year self-test OK")


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
