#!/usr/bin/env python3
"""Publish station-record frontend data for Germany + France from EXISTING caches.

Purpose
-------
This is deliberately a publishing/assembly step, not a historical downloader.
It requires the already-built DWD historical cache and reuses every available
Météo-France per-resource shard. Missing French historical resources are
reported as partial coverage but do not block publication.

Optionally, current-year DWD/Météo-France data are refreshed from their small
current/recent feeds. Failure of a current-year refresh is non-fatal so that a
historical publication can still go online.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import pickle
import tempfile
from pathlib import Path
from typing import Dict, Tuple

import update_europe_station_records as core


def load_dwd_cache(cache_dir: Path, cutoff_year: int) -> dict:
    path = cache_dir / (
        f"dwd_germany_kl_baseline_through_{cutoff_year}_v{core.DWD_BASELINE_FORMAT_VERSION}.pkl.gz"
    )
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(
            "DWD-Historical-Cache fehlt. Erst 'Update DWD station cache' erfolgreich ausführen. "
            f"Erwartet: {path}"
        )
    with gzip.open(path, "rb") as handle:
        payload = pickle.load(handle)
    if payload.get("format_version") != core.DWD_BASELINE_FORMAT_VERSION:
        raise RuntimeError("DWD-Cache hat ein unerwartetes Format.")
    if payload.get("cutoff_year") != cutoff_year:
        raise RuntimeError(
            f"DWD-Cache endet {payload.get('cutoff_year')}, benötigt wird {cutoff_year}."
        )
    if not payload.get("states"):
        raise RuntimeError("DWD-Cache enthält keine Stationsdaten.")
    return payload


def load_mf_shards(cache_dir: Path, cutoff_year: int) -> Tuple[dict, dict, int, int]:
    shard_dir = cache_dir / (
        f"meteofrance_resources_through_{cutoff_year}_v{core.MF_RESOURCE_CACHE_FORMAT_VERSION}"
    )
    if not shard_dir.exists():
        raise RuntimeError(
            "Météo-France-Einzelcache fehlt. Erst 'Update Météo-France station cache' ausführen. "
            f"Erwartet: {shard_dir}"
        )

    partial: Dict[str, dict] = {}
    metas: Dict[str, tuple] = {}
    valid_shards = 0
    bad_shards = 0

    paths = sorted(shard_dir.glob("*.pkl.gz"))
    if not paths:
        raise RuntimeError(f"Keine Météo-France-Einzelcaches in {shard_dir} gefunden.")

    for path in paths:
        try:
            with gzip.open(path, "rb") as handle:
                payload = pickle.load(handle)
            if payload.get("format_version") != core.MF_RESOURCE_CACHE_FORMAT_VERSION:
                raise RuntimeError("falsche Formatversion")
            if payload.get("cutoff_year") != cutoff_year:
                raise RuntimeError("falsches Cutoff-Jahr")
            core.merge_mf_partial(partial, payload.get("partial", {}))
            core.merge_mf_meta(metas, payload.get("metas", {}))
            valid_shards += 1
        except Exception as exc:
            bad_shards += 1
            core.log(f"WARNUNG: Météo-France-Shard unlesbar und übersprungen: {path.name}: {exc}")

    if valid_shards == 0 or not partial:
        raise RuntimeError("Kein gültiger Météo-France-Zwischenstand konnte aus den Einzelcaches aufgebaut werden.")

    states = core.finalize_mf_states(partial)
    stations = {sid: item[0] for sid, item in metas.items() if sid in states}
    return states, stations, valid_shards, bad_shards


def read_mf_resource_total(cache_dir: Path, cutoff_year: int, available: int) -> int:
    report = cache_dir / f"meteofrance_failed_resources_through_{cutoff_year}.json"
    if report.exists():
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
            total = int(payload.get("resource_count", 0))
            if total >= available:
                return total
        except Exception:
            pass
    # The current official resource inventory used for this baseline had 423
    # resources. Keep this only as a conservative fallback for status metadata;
    # it is never used to decide which data to publish.
    return max(available, 423)


def patch_index_metadata(
    output_dir: Path,
    *,
    current_year: int,
    mf_available: int,
    mf_total: int,
    mf_bad_shards: int,
    current_dwd_ok: bool,
    current_mf_ok: bool,
) -> dict:
    path = output_dir / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    counts = {}
    for row in payload.get("stations", []):
        source = row.get("source")
        counts[source] = counts.get(source, 0) + 1

    missing = max(0, mf_total - mf_available)
    payload["source"] = "DWD CDC (Deutschland) + Météo-France (Frankreich)"
    payload["source_url"] = core.MF_PUBLIC_BASE
    payload["sources"] = [
        {
            "name": core.DWD_SOURCE,
            "scope": "Deutschland",
            "url": core.DWD_BASE,
            "stations": counts.get(core.DWD_SOURCE, 0),
            "historical_complete": True,
        },
        {
            "name": core.MF_SOURCE,
            "scope": "Frankreich",
            "url": core.MF_PUBLIC_BASE,
            "stations": counts.get(core.MF_SOURCE, 0),
            "historical_complete": missing == 0 and mf_bad_shards == 0,
            "resources_available": mf_available,
            "resources_total": mf_total,
            "resources_missing": missing,
        },
    ]
    payload["quality_rule"] = (
        "Deutschland: DWD CDC Tageswerte KL (TXK/TNK, Fehlwerte verworfen). "
        "Frankreich: Météo-France TX/TN aus den täglichen Klimadateien; Qualitätscodes "
        "0/1/9 bzw. ältere leere Codes akzeptiert, Code 2 verworfen."
    )
    payload["history_scope"] = (
        f"Deutschland vollständig aus dem DWD-KL-Historical-Cache bis {current_year - 1}. "
        f"Frankreich als veröffentlichter Zwischenstand aus {mf_available} von {mf_total} "
        "Météo-France-Historical-Ressourcen; fehlende Ressourcen werden separat repariert."
    )
    payload["publication_scope"] = "Deutschland + Frankreich (Zwischenveröffentlichung)"
    payload["publication_partial"] = missing > 0 or mf_bad_shards > 0
    payload["coverage"] = {
        "Deutschland": {
            "source": core.DWD_SOURCE,
            "historical_complete": True,
            "current_year_refresh_ok": current_dwd_ok,
        },
        "Frankreich": {
            "source": core.MF_SOURCE,
            "historical_complete": missing == 0 and mf_bad_shards == 0,
            "resources_available": mf_available,
            "resources_total": mf_total,
            "resources_missing": missing,
            "unreadable_cached_shards": mf_bad_shards,
            "current_year_refresh_ok": current_mf_ok,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmpname:
        tmp = Path(tmpname)
        cutoff = 2025

        dwd_path = tmp / f"dwd_germany_kl_baseline_through_{cutoff}_v{core.DWD_BASELINE_FORMAT_VERSION}.pkl.gz"
        dwd_payload = {
            "format_version": core.DWD_BASELINE_FORMAT_VERSION,
            "cutoff_year": cutoff,
            "states": {"DWD:00001": core.empty_state()},
        }
        dwd_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(dwd_path, "wb") as h:
            pickle.dump(dwd_payload, h)
        assert load_dwd_cache(tmp, cutoff)["cutoff_year"] == cutoff

        shard_dir = tmp / f"meteofrance_resources_through_{cutoff}_v{core.MF_RESOURCE_CACHE_FORMAT_VERSION}"
        shard_dir.mkdir(parents=True)
        sid = "MF:12345678"
        partial = {sid: core.mf_empty_partial_state()}
        partial[sid]["TMAX"]["abs"] = (321, 20250701, 1)
        partial[sid]["TMAX"]["cal"]["07-01"] = (321, 20250701, 1)
        partial[sid]["TMAX"]["start"] = 20250701
        partial[sid]["TMAX"]["end"] = 20250701
        partial[sid]["TMAX"]["year_set"].add(2025)
        meta = core.StationMeta(sid, 48.0, 2.0, 100.0, "TEST", "FR", "Frankreich", core.MF_SOURCE, "test")
        shard_payload = {
            "format_version": core.MF_RESOURCE_CACHE_FORMAT_VERSION,
            "url": "https://example.invalid/Q_00_previous-1950-2024_RR-T-Vent.csv.gz",
            "cutoff_year": cutoff,
            "partial": partial,
            "metas": {sid: (meta, 20250701)},
        }
        with gzip.open(shard_dir / "00_test.pkl.gz", "wb") as h:
            pickle.dump(shard_payload, h)
        states, stations, n, bad = load_mf_shards(tmp, cutoff)
        assert n == 1 and bad == 0 and sid in states and sid in stations
        assert states[sid]["TMAX"]["abs"][0] == 321
    print("Publish DE+FR self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--cache-dir", default=".cache/europe-stations")
    parser.add_argument("--output", default="europe_stations")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--no-current", action="store_true", help="Nur historische Caches veröffentlichen; laufendes Jahr nicht aktualisieren")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    current_year = args.year
    cutoff_year = current_year - 1
    cache_dir = Path(args.cache_dir)
    output_dir = Path(args.output)

    core.log("=== PUBLISH DEUTSCHLAND + FRANKREICH ===")
    core.log("Historische Daten werden NICHT neu heruntergeladen; es werden nur vorhandene Caches zusammengesetzt.")

    dwd_baseline = load_dwd_cache(cache_dir, cutoff_year)
    mf_states, mf_stations, mf_available, mf_bad = load_mf_shards(cache_dir, cutoff_year)
    mf_total = read_mf_resource_total(cache_dir, cutoff_year, mf_available)

    core.log(f"DWD-Historical aus Cache: {len(dwd_baseline['states']):,} Stationen.")
    core.log(
        f"Météo-France-Historical aus Einzelcache: {len(mf_states):,} Stationen | "
        f"{mf_available}/{mf_total} Ressourcen verfügbar | {max(0, mf_total-mf_available)} fehlen."
    )

    # DWD metadata are small and required to put cached states on the map.
    dwd_text = core.decode_text_smart(core.read_url_bytes(core.DWD_STATIONS_URL))
    dwd_all = core.parse_dwd_stations(dwd_text)
    dwd_stations = {sid: meta for sid, meta in dwd_all.items() if sid in dwd_baseline["states"]}
    if not dwd_stations:
        raise RuntimeError("DWD-Metadaten konnten den gecachten DWD-Zuständen nicht zugeordnet werden.")

    dwd_current = {}
    mf_current = {}
    dwd_current_ok = False
    mf_current_ok = False

    if not args.no_current:
        try:
            dwd_current = core.parse_current_dwd_year(current_year, dwd_all, workers=max(4, args.workers))
            dwd_current_ok = True
        except Exception as exc:
            core.log(f"WARNUNG: DWD {current_year} konnte nicht aktualisiert werden; Veröffentlichung nutzt Historical-Stand: {exc}")

        try:
            mf_current, mf_current_stations = core.parse_current_mf_year(current_year, workers=max(4, args.workers))
            mf_stations.update(mf_current_stations)
            mf_current_ok = True
        except Exception as exc:
            core.log(f"WARNUNG: Météo-France {current_year} konnte nicht vollständig aktualisiert werden; Historical-Zwischenstand wird trotzdem veröffentlicht: {exc}")
    else:
        core.log("Laufendes Jahr wurde per --no-current übersprungen.")

    stations = dict(dwd_stations)
    stations.update(mf_stations)
    states = dict(dwd_baseline["states"])
    states.update(mf_states)
    current = dict(dwd_current)
    current.update(mf_current)

    if output_dir.exists():
        import shutil
        shutil.rmtree(output_dir)

    core.merge_and_write(output_dir, stations, states, current, current_year)
    payload = patch_index_metadata(
        output_dir,
        current_year=current_year,
        mf_available=mf_available,
        mf_total=mf_total,
        mf_bad_shards=mf_bad,
        current_dwd_ok=dwd_current_ok,
        current_mf_ok=mf_current_ok,
    )

    countries = set(payload.get("countries", []))
    if not {"Deutschland", "Frankreich"}.issubset(countries):
        raise RuntimeError(f"Veröffentlichung unvollständig: Länder im Output = {sorted(countries)}")

    core.log(
        f"PUBLISH OK: {payload.get('station_count', 0):,} Stationen | "
        f"Deutschland + Frankreich | Frankreich {mf_available}/{mf_total} Historical-Ressourcen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
