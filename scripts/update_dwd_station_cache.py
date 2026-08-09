#!/usr/bin/env python3
"""Build ONLY the German DWD CDC historical station baseline cache.

This intentionally does not touch GHCN, Météo-France, AEMET or frontend files.
It exists so a later failure in another national source can never invalidate
or force a repeat of the DWD historical ZIP processing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import pickle
from pathlib import Path

import update_europe_station_records as core


def validate_cache(path: Path, cutoff_year: int) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"DWD-Cache fehlt oder ist leer: {path}")
    with gzip.open(path, "rb") as handle:
        payload = pickle.load(handle)
    if payload.get("format_version") != core.DWD_BASELINE_FORMAT_VERSION:
        raise RuntimeError(
            f"DWD-Cacheformat falsch: {payload.get('format_version')} statt {core.DWD_BASELINE_FORMAT_VERSION}"
        )
    if payload.get("cutoff_year") != cutoff_year:
        raise RuntimeError(f"DWD-Cutoff falsch: {payload.get('cutoff_year')} statt {cutoff_year}")
    states = payload.get("states", {})
    if not states:
        raise RuntimeError("DWD-Cache enthält keine Stationszustände.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--cache-dir", default=".cache/europe-stations")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cutoff_year = args.year - 1
    cache_dir = Path(args.cache_dir)
    cache_file = cache_dir / (
        f"dwd_germany_kl_baseline_through_{cutoff_year}_v{core.DWD_BASELINE_FORMAT_VERSION}.pkl.gz"
    )

    core.log("=== DWD-ONLY BASELINE ===")
    core.log(f"Ziel: DWD CDC KL historical bis {cutoff_year}; keine andere Datenquelle wird aufgerufen.")

    dwd_text = core.decode_text_smart(core.read_url_bytes(core.DWD_STATIONS_URL))
    stations = core.parse_dwd_stations(dwd_text)
    core.log(f"DWD-KL-Stationsmetadaten Deutschland: {len(stations):,}")
    if not stations:
        raise RuntimeError("Keine DWD-KL-Stationsmetadaten gefunden.")

    payload = core.load_or_build_dwd_baseline(
        cache_file, stations, cutoff_year, force=args.force, workers=max(1, args.workers)
    )
    payload = validate_cache(cache_file, cutoff_year)
    states = payload.get("states", {})
    tmax = sum(1 for s in states.values() if s.get("TMAX", {}).get("abs") is not None)
    tmin = sum(1 for s in states.values() if s.get("TMIN", {}).get("abs") is not None)
    core.log(f"DWD-ONLY OK: {len(states):,} Stationen | TMAX {tmax:,} | TMIN {tmin:,}")
    core.log(f"Persistenter Cache: {cache_file} ({cache_file.stat().st_size/1024/1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
