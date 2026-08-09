#!/usr/bin/env python3
"""Unified Europe station-record updater.

National authoritative sources:
- Germany: DWD CDC
- France: Météo-France
- Spain: AEMET OpenData
- Austria: GeoSphere Austria
- Poland: IMGW-PIB
- remaining Europe: GHCN-Daily

Historical national baselines are cached. The running year is refreshed on every run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import pickle
import shutil
import time
from pathlib import Path

import update_europe_station_records as core
import update_geosphere_austria_station_cache as austria
import update_imgw_poland_station_cache as poland


def log(message: str) -> None:
    core.log(message)




# AEMET OpenData daily climatology requests must stay small.  The all-stations
# daily endpoint is handled in 14-day windows (below the 15-calendar-day
# ceiling used by our validated AEMET tooling).  Historical windows are cached
# individually so a long bootstrap survives timeouts/network interruptions.
AEMET_SAFE_START_YEAR = 1920
AEMET_WINDOW_DAYS = 14
AEMET_RESOURCE_FORMAT_VERSION = 2
AEMET_BASELINE_FORMAT_VERSION = 2
AEMET_REQUEST_PAUSE_SECONDS = 3.3


def _aemet_windows(start: dt.date, end: dt.date, days: int = AEMET_WINDOW_DAYS):
    if days < 1 or days > 15:
        raise ValueError("AEMET-Zeitfenster muss zwischen 1 und 15 Kalendertagen liegen.")
    if end < start:
        return []
    result = []
    cursor = start
    delta = dt.timedelta(days=days - 1)
    while cursor <= end:
        stop = min(end, cursor + delta)
        result.append((cursor, stop))
        cursor = stop + dt.timedelta(days=1)
    return result


def _aemet_resource_dir(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"aemet_spain_resources_through_{cutoff_year}_v{AEMET_RESOURCE_FORMAT_VERSION}"
    )


def _aemet_resource_path(resource_dir: Path, start: dt.date, end: dt.date) -> Path:
    return resource_dir / f"{start:%Y%m%d}_{end:%Y%m%d}.pkl.gz"


def _read_pickle_gz(path: Path):
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


def _write_pickle_gz(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=5) as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def _fetch_aemet_partial(
    api_key: str,
    stations: dict,
    start: dt.date,
    end: dt.date,
    *,
    cutoff_year: int,
):
    start_dt = dt.datetime.combine(start, dt.time.min)
    end_dt = dt.datetime.combine(end, dt.time(23, 59, 59))
    rows = core.aemet_api_dataset(
        core.aemet_daily_path(start_dt, end_dt),
        api_key,
        allow_empty=True,
    )
    part, _current = core.parse_aemet_rows(
        rows, stations, cutoff_year=cutoff_year
    )
    return part


def load_or_build_aemet_baseline_safe(
    cache_dir: Path,
    api_key: str,
    stations: dict,
    cutoff_year: int,
    *,
    force: bool = False,
) -> dict:
    cache_file = cache_dir / (
        f"aemet_spain_daily_baseline_through_{cutoff_year}_v"
        f"{AEMET_BASELINE_FORMAT_VERSION}.pkl.gz"
    )
    if cache_file.exists() and not force:
        try:
            payload = _read_pickle_gz(cache_file)
            if (
                payload.get("format_version") == AEMET_BASELINE_FORMAT_VERSION
                and payload.get("cutoff_year") == cutoff_year
            ):
                log(f"Verwende historischen AEMET-Cache: {cache_file}")
                return payload
        except Exception as exc:
            log(f"AEMET-Gesamtcache konnte nicht gelesen werden ({exc}); Neuaufbau aus Einzelcache.")

    start_year = max(AEMET_SAFE_START_YEAR, min(core.AEMET_BASELINE_START_YEAR, cutoff_year))
    start_date = dt.date(start_year, 1, 1)
    end_date = dt.date(cutoff_year, 12, 31)
    windows = _aemet_windows(start_date, end_date)
    resource_dir = _aemet_resource_dir(cache_dir, cutoff_year)
    if force and resource_dir.exists():
        shutil.rmtree(resource_dir)
    resource_dir.mkdir(parents=True, exist_ok=True)

    log(
        f"AEMET Spanien Baseline {start_year}–{cutoff_year}: {len(windows):,} "
        f"Zeitfenster à maximal {AEMET_WINDOW_DAYS} Tage; Einzelcache aktiv."
    )
    partial = {}
    cached = 0
    downloaded = 0
    failures = []

    for i, (start, end) in enumerate(windows, start=1):
        path = _aemet_resource_path(resource_dir, start, end)
        part = None
        if path.exists() and not force:
            try:
                saved = _read_pickle_gz(path)
                if (
                    saved.get("format_version") == AEMET_RESOURCE_FORMAT_VERSION
                    and saved.get("start") == start.isoformat()
                    and saved.get("end") == end.isoformat()
                ):
                    part = saved.get("partial", {})
                    cached += 1
            except Exception as exc:
                log(f"WARNUNG AEMET Einzelcache {path.name} unlesbar ({exc}); lade neu.")

        if part is None:
            try:
                part = _fetch_aemet_partial(
                    api_key, stations, start, end, cutoff_year=cutoff_year
                )
                _write_pickle_gz(
                    path,
                    {
                        "format_version": AEMET_RESOURCE_FORMAT_VERSION,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "partial": part,
                    },
                )
                downloaded += 1
            except Exception as exc:
                failures.append((start, end, str(exc)))
                log(f"FEHLER AEMET {start}–{end}: {exc}")
                continue
            finally:
                # A dataset call means two HTTP connections (envelope + datos).
                # Stay deliberately gentle to AEMET OpenData.
                time.sleep(AEMET_REQUEST_PAUSE_SECONDS)

        core.merge_mf_partial(partial, part)
        if i == 1 or i % 100 == 0 or i == len(windows):
            log(
                f"  AEMET historical: {i:,}/{len(windows):,} Fenster | "
                f"Cache {cached:,} | neu {downloaded:,} | Fehler {len(failures):,} | "
                f"{len(partial):,} Stationscodes …"
            )

    if failures:
        status = {
            "source": core.AEMET_SOURCE,
            "cutoff_year": cutoff_year,
            "start_year": start_year,
            "window_days": AEMET_WINDOW_DAYS,
            "resource_count": len(windows),
            "cached": cached,
            "downloaded": downloaded,
            "missing": len(failures),
            "complete": False,
            "failures": [
                {"start": a.isoformat(), "end": b.isoformat(), "error": err}
                for a, b, err in failures[:50]
            ],
        }
        status_path = cache_dir / f"aemet_spain_status_through_{cutoff_year}.json"
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(
            f"AEMET-Baseline noch unvollständig: {len(failures)} von {len(windows)} "
            "14-Tage-Fenstern fehlen. Erfolgreiche Fenster sind einzeln gecacht; "
            "mit force=false erneut starten."
        )

    states = core.finalize_mf_states(partial)
    if not states:
        raise RuntimeError("AEMET-Basisbestand enthält trotz gültiger 14-Tage-Abfragen keine TMAX/TMIN-Daten.")

    payload = {
        "format_version": AEMET_BASELINE_FORMAT_VERSION,
        "cutoff_year": cutoff_year,
        "start_year": start_year,
        "window_days": AEMET_WINDOW_DAYS,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "states": states,
    }
    _write_pickle_gz(cache_file, payload)
    status_path = cache_dir / f"aemet_spain_status_through_{cutoff_year}.json"
    status_path.write_text(
        json.dumps(
            {
                "source": core.AEMET_SOURCE,
                "cutoff_year": cutoff_year,
                "start_year": start_year,
                "window_days": AEMET_WINDOW_DAYS,
                "resource_count": len(windows),
                "cached": cached,
                "downloaded": downloaded,
                "missing": 0,
                "complete": True,
                "station_count": len(states),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log(
        f"AEMET Spanien Baseline OK: {len(states):,} Stationen bis {cutoff_year}; "
        f"{len(windows):,}/{len(windows):,} Zeitfenster vollständig."
    )
    return payload


def parse_current_aemet_year_safe(year: int, api_key: str, stations: dict) -> dict:
    today = dt.datetime.now(dt.timezone.utc).date()
    start = dt.date(year, 1, 1)
    end = min(today, dt.date(year, 12, 31))
    if end < start:
        return {}
    windows = _aemet_windows(start, end)
    log(
        f"Lade AEMET Spanien {year}: {len(windows)} Zeitfenster à maximal "
        f"{AEMET_WINDOW_DAYS} Tage …"
    )
    current = {}
    failures = []
    for i, (a, b) in enumerate(windows, start=1):
        a_dt = dt.datetime.combine(a, dt.time.min)
        b_dt = dt.datetime.combine(b, dt.time(23, 59, 59))
        try:
            rows = core.aemet_api_dataset(
                core.aemet_daily_path(a_dt, b_dt), api_key, allow_empty=True
            )
            _partial, part = core.parse_aemet_rows(rows, stations, exact_year=year)
            for sid, state in part.items():
                dst = current.setdefault(sid, {"TMAX": {}, "TMIN": {}})
                dst["TMAX"].update(state.get("TMAX", {}))
                dst["TMIN"].update(state.get("TMIN", {}))
        except Exception as exc:
            failures.append((a, b, str(exc)))
            log(f"WARNUNG AEMET current {a}–{b}: {exc}")
        finally:
            time.sleep(AEMET_REQUEST_PAUSE_SECONDS)
        if i % 10 == 0 or i == len(windows):
            log(
                f"  AEMET {year}: {i}/{len(windows)} Fenster, "
                f"{len(current):,} Stationen, Fehler {len(failures)} …"
            )
    if failures and len(failures) > max(2, int(len(windows) * 0.15)):
        raise RuntimeError(
            f"Zu viele AEMET-Current-Fehler: {len(failures)} von {len(windows)} Zeitfenstern."
        )
    if not current:
        raise RuntimeError(f"AEMET lieferte für {year} keine aktuellen TMAX/TMIN-Daten.")
    log(f"AEMET {year}: {len(current):,} Stationen mit TMAX/TMIN-Daten.")
    return current


def _load_or_build_poland(cache_dir: Path, current_year: int, force: bool, workers: int) -> dict:
    cutoff_year = current_year - 1
    path = poland.baseline_path(cache_dir, cutoff_year)
    if path.exists() and not force:
        payload = poland.load_baseline(cache_dir, cutoff_year)
        log(f"Verwende IMGW-Polen-Baseline: {path}")
        return payload

    poland.build_baseline(
        current_year=current_year,
        cache_dir=cache_dir,
        workers=workers,
        force=force,
    )
    if not path.exists():
        status_path = cache_dir / f"imgw_poland_status_through_{cutoff_year}.json"
        detail = ""
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
                detail = (
                    f" ({status.get('available', 0)}/{status.get('resource_count', 0)} "
                    f"Ressourcen verfügbar, {status.get('missing', 0)} fehlen)"
                )
            except Exception:
                pass
        raise RuntimeError(f"IMGW-Polen-Baseline blieb unvollständig{detail}.")
    return poland.load_baseline(cache_dir, cutoff_year)


def _source_counts(index_payload: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in index_payload.get("stations", []):
        source = row.get("source")
        if source:
            counts[source] = counts.get(source, 0) + 1
    return counts


def patch_index_metadata(
    output_dir: Path,
    *,
    current_year: int,
    austria_current_count: int,
    poland_current_count: int,
    poland_latest_month: int | None,
) -> dict:
    path = output_dir / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    counts = _source_counts(payload)

    payload["source"] = (
        "DWD CDC (Deutschland) + Météo-France (Frankreich) + "
        "AEMET OpenData (Spanien) + GeoSphere Austria (Österreich) + "
        "IMGW-PIB (Polen) + GHCN-Daily (übriges Europa)"
    )
    payload["sources"] = [
        {
            "name": core.DWD_SOURCE,
            "scope": "Deutschland",
            "url": core.DWD_BASE,
            "stations": counts.get(core.DWD_SOURCE, 0),
        },
        {
            "name": core.MF_SOURCE,
            "scope": "Frankreich",
            "url": core.MF_PUBLIC_BASE,
            "stations": counts.get(core.MF_SOURCE, 0),
        },
        {
            "name": core.AEMET_SOURCE,
            "scope": "Spanien",
            "url": core.AEMET_PUBLIC_URL,
            "stations": counts.get(core.AEMET_SOURCE, 0),
        },
        {
            "name": austria.SOURCE,
            "scope": "Österreich",
            "url": austria.PUBLIC_URL,
            "stations": counts.get(austria.SOURCE, 0),
        },
        {
            "name": poland.SOURCE,
            "scope": "Polen",
            "url": poland.PUBLIC_URL,
            "stations": counts.get(poland.SOURCE, 0),
        },
        {
            "name": core.GHCN_SOURCE,
            "scope": "übriges Europa",
            "url": core.GHCN_BASE,
            "stations": counts.get(core.GHCN_SOURCE, 0),
        },
    ]
    payload["quality_rule"] = (
        "Deutschland: DWD CDC Tageswerte KL (TXK/TNK, Fehlwerte verworfen). "
        "Frankreich: Météo-France TX/TN aus täglichen Klimadateien; "
        "Qualitätscodes 0/1/9 bzw. ältere leere Codes akzeptiert, Code 2 verworfen. "
        "Spanien: AEMET OpenData Tagesklimatologie tmax/tmin wie veröffentlicht; "
        "fehlende oder nichtnumerische Werte verworfen. "
        "Österreich: GeoSphere Austria klima-v2-1d, tägliche tlmax/tlmin. "
        "Polen: IMGW-PIB tägliche Klimadaten k_d mit TMAX/TMIN. "
        "Übriges Europa: GHCN-Daily TMAX/TMIN nur mit leerem Q-FLAG."
    )
    payload["history_scope"] = (
        f"Historische Baselines bis {current_year - 1}: DWD Deutschland, "
        f"Météo-France Frankreich, AEMET Spanien ab {AEMET_SAFE_START_YEAR}, "
        "GeoSphere Austria Österreich, "
        "IMGW-PIB Polen und GHCN-Daily für das übrige Europa. "
        f"Das laufende Jahr {current_year} wird bei jedem täglichen Workflow-Lauf separat aktualisiert."
    )
    payload["publication_scope"] = (
        "Europa vollständig: DWD Deutschland + Météo-France Frankreich + "
        "AEMET Spanien + GeoSphere Austria Österreich + IMGW-PIB Polen + "
        "GHCN-Daily Rest-Europa"
    )
    payload["coverage"] = {
        "Deutschland": {"source": core.DWD_SOURCE, "historical_complete": True},
        "Frankreich": {"source": core.MF_SOURCE, "historical_complete": True},
        "Spanien": {
            "source": core.AEMET_SOURCE,
            "historical_complete": True,
            "historical_start_year": AEMET_SAFE_START_YEAR,
        },
        "Österreich": {
            "source": austria.SOURCE,
            "historical_complete": True,
            "current_year_station_count": austria_current_count,
        },
        "Polen": {
            "source": poland.SOURCE,
            "historical_complete": True,
            "current_year_station_count": poland_current_count,
            "current_year_latest_published_month": poland_latest_month,
        },
        "Rest-Europa": {"source": core.GHCN_SOURCE, "historical_complete": True},
    }

    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return payload


def validate_payload(payload: dict) -> None:
    rows = payload.get("stations", [])
    expected = {
        "Deutschland": core.DWD_SOURCE,
        "Frankreich": core.MF_SOURCE,
        "Spanien": core.AEMET_SOURCE,
        "Österreich": austria.SOURCE,
        "Polen": poland.SOURCE,
    }

    for country, source in expected.items():
        country_rows = [row for row in rows if row.get("country") == country]
        if not country_rows:
            raise RuntimeError(f"Keine Stationen für {country} erzeugt.")
        wrong = [row for row in country_rows if row.get("source") != source]
        if wrong:
            wrong_sources = sorted({row.get("source") for row in wrong})
            raise RuntimeError(
                f"{country} enthält falsche/gemischte Quellen: {wrong_sources}; erwartet {source}."
            )

    ghcn_rows = [row for row in rows if row.get("source") == core.GHCN_SOURCE]
    if not ghcn_rows:
        raise RuntimeError("Keine GHCN-Daily-Stationen für Rest-Europa erzeugt.")

    if len({row.get("country") for row in rows}) < 10:
        raise RuntimeError("Zu wenige Länder in der Europa-Ausgabe.")

    counts = _source_counts(payload)
    for source in (
        core.DWD_SOURCE,
        core.MF_SOURCE,
        core.AEMET_SOURCE,
        austria.SOURCE,
        poland.SOURCE,
        core.GHCN_SOURCE,
    ):
        if counts.get(source, 0) <= 0:
            raise RuntimeError(f"Quelle {source} hat 0 Stationen.")

    log(
        "Europa-Quellenprüfung OK: "
        + ", ".join(f"{name}={count:,}" for name, count in sorted(counts.items()))
    )


def self_test() -> None:
    # Keep this test completely offline.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        sample = {
            "stations": [
                {"country": "Deutschland", "source": core.DWD_SOURCE},
                {"country": "Frankreich", "source": core.MF_SOURCE},
                {"country": "Spanien", "source": core.AEMET_SOURCE},
                {"country": "Österreich", "source": austria.SOURCE},
                {"country": "Polen", "source": poland.SOURCE},
                {"country": "Italien", "source": core.GHCN_SOURCE},
            ]
        }
        (out / "index.json").write_text(json.dumps(sample), encoding="utf-8")
        patched = patch_index_metadata(
            out,
            current_year=2026,
            austria_current_count=10,
            poland_current_count=20,
            poland_latest_month=8,
        )
        sources = {item["name"] for item in patched["sources"]}
        assert austria.SOURCE in sources
        assert poland.SOURCE in sources
        assert core.AEMET_SOURCE in sources
        assert patched["coverage"]["Polen"]["current_year_latest_published_month"] == 8
        test_windows = _aemet_windows(dt.date(2026, 1, 1), dt.date(2026, 2, 1))
        assert test_windows[0] == (dt.date(2026, 1, 1), dt.date(2026, 1, 14))
        assert test_windows[-1][1] == dt.date(2026, 2, 1)
        assert all((b - a).days + 1 <= 14 for a, b in test_windows)
    print("Unified Europe updater self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="europe_stations")
    parser.add_argument("--cache-dir", default=".cache/europe-stations")
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--dwd-workers", type=int, default=6)
    parser.add_argument("--mf-workers", type=int, default=6)
    parser.add_argument("--poland-workers", type=int, default=8)
    parser.add_argument("--force-baseline", action="store_true")
    parser.add_argument("--force-dwd-baseline", action="store_true")
    parser.add_argument("--force-mf-baseline", action="store_true")
    parser.add_argument("--force-aemet-baseline", action="store_true")
    parser.add_argument("--force-austria-baseline", action="store_true")
    parser.add_argument("--force-poland-baseline", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    current_year = args.year
    cutoff_year = current_year - 1
    cache_dir = Path(args.cache_dir)
    output_dir = Path(args.output)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if not os.environ.get("AEMET_API_KEY", "").strip():
        raise RuntimeError("AEMET_API_KEY fehlt.")

    log("=== EUROPA-STATIONSREKORDE · VOLL AUTOMATISCH ===")
    log(
        "DWD Deutschland + Météo-France Frankreich + AEMET Spanien + "
        "GeoSphere Austria + IMGW Polen + GHCN-Daily Rest-Europa."
    )

    aemet_key = core.aemet_api_key()

    countries = core.parse_countries(core.read_url_text(core.COUNTRIES_URL))
    ghcn_stations = core.parse_ghcn_stations(
        core.read_url_text(core.STATIONS_URL),
        countries,
    )
    # Austria and Poland are national-source countries now, just like DE/FR/ES.
    ghcn_stations = {
        sid: meta
        for sid, meta in ghcn_stations.items()
        if meta.country not in {"Österreich", "Polen"}
    }
    log(
        f"GHCN-Metadaten Rest-Europa nach Ausschluss DE/FR/ES/AT/PL: "
        f"{len(ghcn_stations):,}"
    )
    if not ghcn_stations:
        raise RuntimeError("Keine GHCN-Stationen für Rest-Europa gefunden.")

    dwd_text = core.decode_text_smart(core.read_url_bytes(core.DWD_STATIONS_URL))
    dwd_stations = core.parse_dwd_stations(dwd_text)
    if not dwd_stations:
        raise RuntimeError("Keine DWD-KL-Stationsmetadaten gefunden.")

    aemet_stations = core.load_aemet_inventory(aemet_key)

    ghcn_cache = cache_dir / (
        f"ghcn_europe_baseline_through_{cutoff_year}_v"
        f"{core.GHCN_BASELINE_FORMAT_VERSION}.pkl.gz"
    )
    dwd_cache = cache_dir / (
        f"dwd_germany_kl_baseline_through_{cutoff_year}_v"
        f"{core.DWD_BASELINE_FORMAT_VERSION}.pkl.gz"
    )
    mf_cache = cache_dir / (
        f"meteofrance_daily_baseline_through_{cutoff_year}_v"
        f"{core.MF_BASELINE_FORMAT_VERSION}.pkl.gz"
    )

    force_all = args.force_baseline
    ghcn_baseline = core.load_or_build_ghcn_baseline(
        ghcn_cache, ghcn_stations, cutoff_year, force_all
    )
    dwd_baseline = core.load_or_build_dwd_baseline(
        dwd_cache,
        dwd_stations,
        cutoff_year,
        force_all or args.force_dwd_baseline,
        args.dwd_workers,
    )
    mf_baseline = core.load_or_build_mf_baseline(
        mf_cache,
        cutoff_year,
        force_all or args.force_mf_baseline,
        args.mf_workers,
    )
    aemet_baseline = load_or_build_aemet_baseline_safe(
        cache_dir,
        aemet_key,
        aemet_stations,
        cutoff_year,
        force=force_all or args.force_aemet_baseline,
    )
    austria_baseline = austria.load_or_build_baseline(
        cache_dir,
        cutoff_year,
        force=force_all or args.force_austria_baseline,
    )
    poland_baseline = _load_or_build_poland(
        cache_dir,
        current_year,
        force=force_all or args.force_poland_baseline,
        workers=args.poland_workers,
    )

    # Running year: always refreshed.
    ghcn_current = core.parse_current_ghcn_year(current_year, ghcn_stations)
    dwd_current = core.parse_current_dwd_year(
        current_year, dwd_stations, workers=max(4, args.dwd_workers)
    )
    mf_current, mf_current_stations = core.parse_current_mf_year(
        current_year, workers=max(4, args.mf_workers)
    )
    aemet_current = parse_current_aemet_year_safe(
        current_year, aemet_key, aemet_stations
    )
    austria_current = austria.parse_current_year(
        current_year, austria_baseline.get("stations", {})
    )
    poland_current, poland_latest_month = poland.parse_current_year(
        current_year,
        poland_baseline.get("stations", {}),
        workers=max(4, args.poland_workers),
    )

    if not austria_current:
        raise RuntimeError(f"GeoSphere Austria lieferte für {current_year} keine aktuellen Stationen.")
    if not poland_current:
        raise RuntimeError(f"IMGW Polen lieferte für {current_year} keine aktuellen Stationen.")

    mf_stations = dict(mf_baseline.get("stations", {}))
    mf_stations.update(mf_current_stations)
    if not mf_stations:
        raise RuntimeError("Keine Météo-France-Stationen gefunden.")

    stations = dict(ghcn_stations)
    stations.update(dwd_stations)
    stations.update(mf_stations)
    stations.update(aemet_stations)
    stations.update(austria_baseline.get("stations", {}))
    stations.update(poland_baseline.get("stations", {}))

    states = {
        sid: state
        for sid, state in ghcn_baseline.get("states", {}).items()
        if sid in ghcn_stations
    }
    states.update(dwd_baseline.get("states", {}))
    states.update(mf_baseline.get("states", {}))
    states.update(aemet_baseline.get("states", {}))
    states.update(austria_baseline.get("states", {}))
    states.update(poland_baseline.get("states", {}))

    current = dict(ghcn_current)
    current.update(dwd_current)
    current.update(mf_current)
    current.update(aemet_current)
    current.update(austria_current)
    current.update(poland_current)

    if output_dir.exists():
        import shutil
        shutil.rmtree(output_dir)

    core.merge_and_write(output_dir, stations, states, current, current_year)
    payload = patch_index_metadata(
        output_dir,
        current_year=current_year,
        austria_current_count=len(austria_current),
        poland_current_count=len(poland_current),
        poland_latest_month=poland_latest_month,
    )
    validate_payload(payload)

    log(
        f"EUROPA AUTOMATIK OK: {payload.get('station_count', 0):,} Stationen in "
        f"{payload.get('country_count', 0)} Ländern | Polen aktuell bis Monat "
        f"{poland_latest_month:02d}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
