#!/usr/bin/env python3
"""Build ONLY the French Météo-France historical station baseline cache.

Successful source resources are cached individually. A failed French resource
therefore never causes DWD/GHCN/AEMET to run and never discards already-good
French resource shards.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import pickle
from pathlib import Path

import update_europe_station_records as core


def validate_total_cache(path: Path, cutoff_year: int) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Météo-France-Gesamtcache fehlt oder ist leer: {path}")
    with gzip.open(path, "rb") as handle:
        payload = pickle.load(handle)
    if payload.get("format_version") != core.MF_BASELINE_FORMAT_VERSION:
        raise RuntimeError(
            f"Météo-France-Cacheformat falsch: {payload.get('format_version')} statt {core.MF_BASELINE_FORMAT_VERSION}"
        )
    if payload.get("cutoff_year") != cutoff_year:
        raise RuntimeError(f"Météo-France-Cutoff falsch: {payload.get('cutoff_year')} statt {cutoff_year}")
    if not payload.get("states"):
        raise RuntimeError("Météo-France-Gesamtcache enthält keine Stationszustände.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--cache-dir", default=".cache/europe-stations")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--force", action="store_true", help="Gesamt- und Einzelressourcen vollständig neu laden")
    args = parser.parse_args()

    cutoff_year = args.year - 1
    cache_dir = Path(args.cache_dir)
    cache_file = cache_dir / (
        f"meteofrance_daily_baseline_through_{cutoff_year}_v{core.MF_BASELINE_FORMAT_VERSION}.pkl.gz"
    )
    shard_dir = cache_dir / (
        f"meteofrance_resources_through_{cutoff_year}_v{core.MF_RESOURCE_CACHE_FORMAT_VERSION}"
    )
    failure_report = cache_dir / f"meteofrance_failed_resources_through_{cutoff_year}.json"

    core.log("=== METEO-FRANCE-ONLY BASELINE ===")
    core.log(
        f"Ziel: Météo-France daily historical bis {cutoff_year}; "
        "DWD, GHCN und AEMET werden nicht aufgerufen."
    )
    if shard_dir.exists() and not args.force:
        cached_shards = len(list(shard_dir.glob("*.pkl.gz")))
        core.log(f"Vorhandene Frankreich-Einzelcaches: {cached_shards:,}")

    try:
        payload = core.load_or_build_mf_baseline(
            cache_file, cutoff_year, force=args.force, workers=max(1, args.workers)
        )
    except Exception:
        # Print a concise machine/human-readable status before propagating the error.
        cached_shards = len(list(shard_dir.glob("*.pkl.gz"))) if shard_dir.exists() else 0
        core.log(f"Frankreich-Zwischenstand dauerhaft gesichert: {cached_shards:,} Einzelressourcen im Cache.")
        if failure_report.exists():
            try:
                report = json.loads(failure_report.read_text(encoding="utf-8"))
                core.log(
                    f"Frankreich-Fehlerbericht: {len(report.get('failed', []))} endgültig fehlgeschlagene Ressourcen "
                    f"von {report.get('resource_count', '?')}."
                )
            except Exception:
                pass
        raise

    payload = validate_total_cache(cache_file, cutoff_year)
    states = payload.get("states", {})
    core.log(f"METEO-FRANCE-ONLY OK: {len(states):,} Stationen")
    core.log(f"Gesamtcache: {cache_file} ({cache_file.stat().st_size/1024/1024:.1f} MB)")
    core.log(f"Einzelressourcen-Cache: {shard_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
