#!/usr/bin/env python3
"""Initial historical TXK/TNK/TMK archive for configurable DWD station streaks.

Uses already selected DWD climate-day stations. Runs separately from regular
dashboard publishing so first-time population need not recalculate other data.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from station_threshold_history import build_temperature_history
from update_station_climate_days import (
    HISTORICAL_PATTERN,
    HISTORICAL_URL,
    atomic_write_json_compact,
    parse_recent_kl_temperatures,
    station_id_from_filename,
)
from update_station_records import download_station_zip, list_station_files


def build(root: Path, workers: int, min_stations: int) -> dict:
    index = json.loads((root / "station_climate_days_index.json").read_text(encoding="utf-8"))
    current_year = int(index.get("current_year") or date.today().year)
    ids = {str(row["id"]) for row in index.get("stations", [])}
    files = list_station_files(HISTORICAL_URL, HISTORICAL_PATTERN, minimum=500)
    selected = [name for name in files if station_id_from_filename(name) in ids]
    if len(selected) < min_stations:
        raise RuntimeError(f"Nur {len(selected)} DWD-Archivdateien für {len(ids)} Stationen gefunden.")
    dest = root / "station_threshold_daily"
    dest.mkdir(parents=True, exist_ok=True)
    stop = date(current_year - 1, 12, 31)

    def process(filename: str) -> tuple[str, dict | None, str | None]:
        sid = station_id_from_filename(filename)
        try:
            content = download_station_zip(HISTORICAL_URL, filename)
            values = parse_recent_kl_temperatures(content, date(1800, 1, 1), stop)
            packed = build_temperature_history(sid, values)
            if not packed["years"]:
                return sid, None, "Keine historischen Temperaturwerte"
            return sid, packed, None
        except Exception as exc:
            return sid, None, str(exc)

    good: set[str] = set()
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(process, name): name for name in selected}
        for number, done in enumerate(as_completed(pending), 1):
            sid, record, error = done.result()
            if record is not None:
                atomic_write_json_compact(dest / (sid + ".json"), record)
                good.add(sid)
            else:
                failures.append(f"{sid}: {error}")
            if number % 50 == 0 or number == len(pending):
                print(f"Stationstemperaturen {number}/{len(selected)} · erfolgreich: {len(good)}", flush=True)

    if len(good) < min_stations:
        raise RuntimeError(f"Nur {len(good)} Stationsarchive; benötigt mindestens {min_stations}. Fehler: {failures[:5]}")
    for old in dest.glob("*.json"):
        if old.stem not in good:
            old.unlink()

    print("Fertig:", len(good), "Stationen mit historischen TX/TN/TM-Tageswerten.")
    if failures:
        print("Nicht verfügbare Stationen (Auszug):", failures[:15])
    return {"stations":len(good), "source_files":len(selected), "errors":len(failures)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--min-stations", type=int, default=150)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.workers, args.min_stations), ensure_ascii=False))


if __name__ == "__main__":
    main()
