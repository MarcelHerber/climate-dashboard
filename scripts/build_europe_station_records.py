#!/usr/bin/env python3
"""Publish the complete Europe station-record frontend from EXISTING caches.

Source hierarchy for this transition release
--------------------------------------------
* Germany: DWD CDC (replaces GHCN)
* France: Météo-France (replaces GHCN; partial historical shard coverage allowed)
* Spain: GHCN-Daily until the AEMET historical cache is ready
* Rest of Europe: GHCN-Daily

No historical archive is rebuilt by this script. It only restores/reads the
existing GHCN, DWD and Météo-France caches. Current-year feeds can optionally
be refreshed; failures there are non-fatal so historical publication remains
possible.
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
import update_geosphere_austria_station_cache as austria


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
        raise RuntimeError(f"DWD-Cache endet {payload.get('cutoff_year')}, benötigt wird {cutoff_year}.")
    if not payload.get("states"):
        raise RuntimeError("DWD-Cache enthält keine Stationsdaten.")
    return payload


def load_ghcn_cache(cache_dir: Path, cutoff_year: int) -> dict:
    path = cache_dir / (
        f"ghcn_europe_baseline_through_{cutoff_year}_v{core.GHCN_BASELINE_FORMAT_VERSION}.pkl.gz"
    )
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(
            "GHCN-Historical-Cache fehlt. Der Europa-Publish darf den GHCN-Rest nicht entfernen. "
            f"Erwartet: {path}"
        )
    with gzip.open(path, "rb") as handle:
        payload = pickle.load(handle)
    if payload.get("format_version") != core.GHCN_BASELINE_FORMAT_VERSION:
        raise RuntimeError("GHCN-Cache hat ein unerwartetes Format.")
    if payload.get("cutoff_year") != cutoff_year:
        raise RuntimeError(f"GHCN-Cache endet {payload.get('cutoff_year')}, benötigt wird {cutoff_year}.")
    if not payload.get("states"):
        raise RuntimeError("GHCN-Cache enthält keine Stationsdaten.")
    return payload


def parse_ghcn_publish_stations(text: str, countries: Dict[str, str], exclude_austria: bool = False) -> Dict[str, core.StationMeta]:
    """GHCN fallback for all mapped European countries except DE/FR.

    Spain intentionally remains included until AEMET is ready. Germany and
    France are excluded because their national sources are authoritative in
    this publication.
    """
    stations: Dict[str, core.StationMeta] = {}
    for raw in text.splitlines():
        if len(raw) < 42:
            continue
        sid = raw[0:11].strip()
        code = sid[:2]
        if code not in core.EUROPE_CODES or code in {"GM", "FR"} or (exclude_austria and code == "AU"):
            continue
        try:
            lat = float(raw[12:20])
            lon = float(raw[21:30])
            elev_raw = float(raw[31:37])
        except ValueError:
            continue
        if not (core.LAT_MIN <= lat <= core.LAT_MAX and core.LON_MIN <= lon <= core.LON_MAX):
            continue
        elev = None if elev_raw <= -999 else round(elev_raw, 1)
        name = raw[41:71].strip() or sid
        country = core.COUNTRY_NAME_DE.get(code, countries.get(code, code))
        stations[sid] = core.StationMeta(
            sid, lat, lon, elev, name, code, country, core.GHCN_SOURCE,
            "GHCN-Daily: nur TMAX/TMIN mit leerem Q-FLAG; Werte mit gesetztem Qualitätsflag werden verworfen.",
        )
    return stations


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
    return max(available, 423)


def patch_index_metadata(
    output_dir: Path,
    *,
    current_year: int,
    mf_available: int,
    mf_total: int,
    mf_bad_shards: int,
    current_ghcn_ok: bool,
    current_dwd_ok: bool,
    current_mf_ok: bool,
    austria_enabled: bool,
    austria_station_count: int,
    current_austria_ok: bool,
    current_ghcn_spain_count: int,
    current_austria_count: int,
) -> dict:
    path = output_dir / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    counts: Dict[str, int] = {}
    for row in payload.get("stations", []):
        source = row.get("source")
        counts[source] = counts.get(source, 0) + 1

    missing = max(0, mf_total - mf_available)
    payload["source"] = "DWD CDC (Deutschland) + Météo-France (Frankreich) + " + ("GeoSphere Austria (Österreich) + " if austria_enabled else "") + "GHCN-Daily (übriges Europa inkl. Spanien)"
    payload["source_url"] = core.GHCN_BASE
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
        *([
            {
                "name": austria.SOURCE,
                "scope": "Österreich",
                "url": austria.PUBLIC_URL,
                "stations": austria_station_count,
                "historical_complete": True,
            }
        ] if austria_enabled else []),
        {
            "name": core.GHCN_SOURCE,
            "scope": "übriges Europa einschließlich Spanien" + ("; Österreich durch GeoSphere Austria ersetzt" if austria_enabled else " (Österreich noch GHCN)"),
            "url": core.GHCN_BASE,
            "stations": counts.get(core.GHCN_SOURCE, 0),
            "historical_complete": True,
        },
    ]
    payload["quality_rule"] = (
        "Deutschland: DWD CDC Tageswerte KL (TXK/TNK, Fehlwerte verworfen). "
        + "Frankreich: Météo-France TX/TN aus den täglichen Klimadateien; Qualitätscodes 0/1/9 bzw. ältere leere Codes akzeptiert, Code 2 verworfen. "
        + ("Österreich: GeoSphere Austria klima-v2-1d, qualitätsgeprüfte tägliche tlmax/tlmin. " if austria_enabled else "")
        + "Übriges Europa einschließlich Spanien: GHCN-Daily TMAX/TMIN nur mit leerem Q-FLAG."
    )
    payload["history_scope"] = (
        f"Deutschland vollständig aus dem DWD-KL-Historical-Cache bis {current_year - 1}. "
        f"Frankreich als Zwischenstand aus {mf_available} von {mf_total} Météo-France-Historical-Ressourcen. "
        + ("Österreich wird aus GeoSphere Austria klima-v2-1d bereitgestellt; " if austria_enabled else "Österreich bleibt vorerst GHCN-Daily; ")
        + "alle übrigen europäischen Länder einschließlich Spanien bleiben aus dem bestehenden GHCN-Daily-Historical-Cache enthalten. "
        + "Spanien wird erst nach fertigem AEMET-Cache von GHCN auf AEMET umgestellt."
    )
    payload["publication_scope"] = "Europa vollständig: DWD Deutschland + Météo-France Frankreich + " + ("GeoSphere Austria Österreich + " if austria_enabled else "") + "GHCN-Daily Rest-Europa"
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
        **({
            "Österreich": {
                "source": austria.SOURCE,
                "historical_complete": True,
                "current_year_refresh_ok": current_austria_ok,
                "current_year_station_count": current_austria_count,
            }
        } if austria_enabled else {}),
        "Rest-Europa": {
            "source": core.GHCN_SOURCE,
            "historical_complete": True,
            "includes_spain": True,
            "spain_current_year_station_count": current_ghcn_spain_count,
            "austria_replaced_by_national_source": austria_enabled,
            "current_year_refresh_ok": current_ghcn_ok,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


def self_test() -> None:
    # Publishing metadata parser must keep Spain but exclude Germany/France.
    def ghcn_line(sid: str, lat: float, lon: float, elev: float, name: str) -> str:
        return f"{sid:<11} {lat:8.4f} {lon:9.4f} {elev:6.1f}    {name:<30}".ljust(85)

    sample = "\n".join([
        ghcn_line("SP000000001", 40.0, -3.0, 600.0, "MADRID TEST"),
        ghcn_line("GM000000001", 50.0, 8.0, 100.0, "GERMANY TEST"),
        ghcn_line("FR000000001", 48.0, 2.0, 100.0, "FRANCE TEST"),
        ghcn_line("IT000000001", 42.0, 12.0, 100.0, "ITALY TEST"),
        ghcn_line("AU000000001", 47.5, 14.0, 500.0, "AUSTRIA TEST"),
    ])
    parsed = parse_ghcn_publish_stations(sample, {})
    assert "SP000000001" in parsed
    assert "IT000000001" in parsed
    assert "GM000000001" not in parsed
    assert "FR000000001" not in parsed
    assert "AU000000001" in parsed
    parsed_with_austria_national = parse_ghcn_publish_stations(sample, {}, exclude_austria=True)
    assert "SP000000001" in parsed_with_austria_national
    assert "IT000000001" in parsed_with_austria_national
    assert "AU000000001" not in parsed_with_austria_national

    with tempfile.TemporaryDirectory() as tmpname:
        tmp = Path(tmpname)
        cutoff = 2025
        dwd_path = tmp / f"dwd_germany_kl_baseline_through_{cutoff}_v{core.DWD_BASELINE_FORMAT_VERSION}.pkl.gz"
        with gzip.open(dwd_path, "wb") as h:
            pickle.dump({"format_version": core.DWD_BASELINE_FORMAT_VERSION, "cutoff_year": cutoff, "states": {"DWD:00001": core.empty_state()}}, h)
        assert load_dwd_cache(tmp, cutoff)["cutoff_year"] == cutoff

        ghcn_path = tmp / f"ghcn_europe_baseline_through_{cutoff}_v{core.GHCN_BASELINE_FORMAT_VERSION}.pkl.gz"
        with gzip.open(ghcn_path, "wb") as h:
            pickle.dump({"format_version": core.GHCN_BASELINE_FORMAT_VERSION, "cutoff_year": cutoff, "states": {"SP000000001": core.empty_state()}}, h)
        assert load_ghcn_cache(tmp, cutoff)["cutoff_year"] == cutoff

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
        with gzip.open(shard_dir / "00_test.pkl.gz", "wb") as h:
            pickle.dump({
                "format_version": core.MF_RESOURCE_CACHE_FORMAT_VERSION,
                "url": "https://example.invalid/test.csv.gz",
                "cutoff_year": cutoff,
                "partial": partial,
                "metas": {sid: (meta, 20250701)},
            }, h)
        states, stations, n, bad = load_mf_shards(tmp, cutoff)
        assert n == 1 and bad == 0 and sid in states and sid in stations
    print("Publish Europe self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--cache-dir", default=".cache/europe-stations")
    parser.add_argument("--output", default="europe_stations")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--no-current", action="store_true", help="Nur historische Caches veröffentlichen")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    current_year = args.year
    cutoff_year = current_year - 1
    cache_dir = Path(args.cache_dir)
    output_dir = Path(args.output)

    core.log("=== PUBLISH EUROPA-STATIONEN ===")
    core.log("DWD Deutschland + Météo-France Frankreich + optional GeoSphere Austria + GHCN-Daily übriges Europa inkl. Spanien.")
    core.log("Historische Archive werden NICHT neu aufgebaut; vorhandene Caches werden zusammengesetzt.")

    ghcn_baseline = load_ghcn_cache(cache_dir, cutoff_year)
    dwd_baseline = load_dwd_cache(cache_dir, cutoff_year)
    mf_states, mf_stations, mf_available, mf_bad = load_mf_shards(cache_dir, cutoff_year)
    mf_total = read_mf_resource_total(cache_dir, cutoff_year, mf_available)

    austria_baseline = None
    austria_path = austria.baseline_path(cache_dir, cutoff_year)
    if austria_path.exists():
        austria_baseline = austria.load_baseline(cache_dir, cutoff_year)
        core.log(f"GeoSphere-Austria-Historical aus Cache: {len(austria_baseline.get('states', {})):,} Stationsreihen.")
    else:
        core.log("GeoSphere-Austria-Cache noch nicht vorhanden: Österreich bleibt für diesen Publish vollständig über GHCN-Daily enthalten.")

    # Small metadata files are refreshed so every cached state can be placed on the map.
    countries = core.parse_countries(core.read_url_text(core.COUNTRIES_URL))
    ghcn_meta_all = parse_ghcn_publish_stations(core.read_url_text(core.STATIONS_URL), countries, exclude_austria=bool(austria_baseline))
    ghcn_states = {sid: st for sid, st in ghcn_baseline.get("states", {}).items() if sid in ghcn_meta_all}
    ghcn_stations = {sid: meta for sid, meta in ghcn_meta_all.items() if sid in ghcn_states}
    if not ghcn_stations:
        raise RuntimeError("GHCN-Cache konnte keiner Rest-Europa-Station zugeordnet werden.")

    # Spain must stay visible until AEMET is ready; never silently drop it.
    spanish_ghcn = sum(1 for meta in ghcn_stations.values() if meta.country_code == "SP")
    if spanish_ghcn == 0:
        raise RuntimeError(
            "Der vorhandene GHCN-Cache enthält keine nutzbaren Spanien-Stationen. "
            "Publish wird abgebrochen, damit Spanien nicht still von der Europa-Karte verschwindet."
        )

    dwd_text = core.decode_text_smart(core.read_url_bytes(core.DWD_STATIONS_URL))
    dwd_all = core.parse_dwd_stations(dwd_text)
    dwd_stations = {sid: meta for sid, meta in dwd_all.items() if sid in dwd_baseline["states"]}
    if not dwd_stations:
        raise RuntimeError("DWD-Metadaten konnten den gecachten DWD-Zuständen nicht zugeordnet werden.")

    core.log(f"GHCN-Historical aus Cache: {len(ghcn_states):,} Stationen Rest-Europa, davon Spanien {spanish_ghcn:,}.")
    core.log(f"DWD-Historical aus Cache: {len(dwd_baseline['states']):,} Stationen.")
    core.log(
        f"Météo-France-Historical aus Einzelcache: {len(mf_states):,} Stationen | "
        f"{mf_available}/{mf_total} Ressourcen verfügbar | {max(0, mf_total-mf_available)} fehlen."
    )

    ghcn_current: Dict[str, dict] = {}
    dwd_current: Dict[str, dict] = {}
    mf_current: Dict[str, dict] = {}
    austria_current: Dict[str, dict] = {}
    ghcn_current_ok = dwd_current_ok = mf_current_ok = austria_current_ok = False
    ghcn_spain_current_count = 0
    ghcn_austria_current_count = 0
    austria_current_count = 0

    if not args.no_current:
        try:
            ghcn_current = core.parse_current_ghcn_year(current_year, ghcn_stations)
            ghcn_current_ok = True
            ghcn_spain_current_count = sum(
                1 for sid in ghcn_current
                if sid in ghcn_stations and ghcn_stations[sid].country_code == "SP"
            )
            ghcn_austria_current_count = sum(
                1 for sid in ghcn_current
                if sid in ghcn_stations and ghcn_stations[sid].country_code == "AU"
            )
            core.log(
                f"GHCN {current_year} Publish-Kontrolle: Spanien {ghcn_spain_current_count:,} Stationen mit laufenden Daten; "
                + (
                    f"Österreich {ghcn_austria_current_count:,} via GHCN (kein GeoSphere-Cache)."
                    if not austria_baseline else
                    f"Österreich {ghcn_austria_current_count:,} via GHCN (muss 0 sein, da GeoSphere aktiv)."
                )
            )
            if spanish_ghcn > 0 and ghcn_spain_current_count == 0:
                raise RuntimeError(
                    "Spanien ist historisch über GHCN vorhanden, aber im laufenden GHCN-Jahr wurden 0 spanische Stationen gefunden. "
                    "Publish wird gestoppt, damit Spanien 2026 nicht still fehlt."
                )
            if austria_baseline and ghcn_austria_current_count != 0:
                raise RuntimeError(
                    "GeoSphere Austria ist aktiv, aber GHCN-current enthält noch Österreich. "
                    "Publish wird gestoppt, um gemischte Quellen zu verhindern."
                )
        except Exception as exc:
            ghcn_current_ok = False
            core.log(f"WARNUNG: GHCN {current_year} konnte nicht vollständig aktualisiert werden; Historical-Stand bleibt online: {exc}")

        try:
            dwd_current = core.parse_current_dwd_year(current_year, dwd_all, workers=max(4, args.workers))
            dwd_current_ok = True
        except Exception as exc:
            core.log(f"WARNUNG: DWD {current_year} konnte nicht aktualisiert werden; Historical-Stand bleibt online: {exc}")

        try:
            mf_current, mf_current_stations = core.parse_current_mf_year(current_year, workers=max(4, args.workers))
            mf_stations.update(mf_current_stations)
            mf_current_ok = True
        except Exception as exc:
            core.log(f"WARNUNG: Météo-France {current_year} konnte nicht vollständig aktualisiert werden; Historical-Zwischenstand bleibt online: {exc}")

        if austria_baseline:
            try:
                austria_current = austria.parse_current_year(current_year, austria_baseline.get("stations", {}))
                austria_current_count = len(austria_current)
                if austria_current_count == 0:
                    raise RuntimeError(
                        f"GeoSphere Austria lieferte für {current_year} 0 Stationen mit TMAX/TMIN."
                    )
                austria_current_ok = True
                core.log(f"GeoSphere Austria {current_year} Publish-Kontrolle: {austria_current_count:,} Stationen mit laufenden TMAX/TMIN-Daten.")
            except Exception as exc:
                austria_current_ok = False
                core.log(f"WARNUNG: GeoSphere Austria {current_year} konnte nicht aktualisiert werden; Historical-Stand bleibt online: {exc}")
    else:
        core.log("Laufendes Jahr wurde per --no-current übersprungen.")

    # Source hierarchy: GHCN base first; national sources replace DE/FR and AT when available.
    stations = dict(ghcn_stations)
    stations.update(dwd_stations)
    stations.update(mf_stations)
    states = dict(ghcn_states)
    states.update(dwd_baseline["states"])
    states.update(mf_states)
    current = dict(ghcn_current)
    current.update(dwd_current)
    current.update(mf_current)
    if austria_baseline:
        stations.update(austria_baseline.get("stations", {}))
        states.update(austria_baseline.get("states", {}))
        current.update(austria_current)

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
        current_ghcn_ok=ghcn_current_ok,
        current_dwd_ok=dwd_current_ok,
        current_mf_ok=mf_current_ok,
        austria_enabled=bool(austria_baseline),
        austria_station_count=len(austria_baseline.get("states", {})) if austria_baseline else 0,
        current_austria_ok=austria_current_ok,
        current_ghcn_spain_count=ghcn_spain_current_count,
        current_austria_count=austria_current_count,
    )

    rows = payload.get("stations", [])
    de = [x for x in rows if x.get("country") == "Deutschland"]
    fr = [x for x in rows if x.get("country") == "Frankreich"]
    es = [x for x in rows if x.get("country") == "Spanien"]
    at = [x for x in rows if x.get("country") == "Österreich"]
    ghcn = [x for x in rows if x.get("source") == core.GHCN_SOURCE]
    if not de or not fr or not es or not ghcn:
        raise RuntimeError(
            f"Europa-Publish unvollständig: DE={len(de)}, FR={len(fr)}, ES={len(es)}, GHCN={len(ghcn)}"
        )
    if not all(x.get("source") == core.DWD_SOURCE for x in de):
        raise RuntimeError("Deutschland enthält noch eine Nicht-DWD-Quelle.")
    if not all(x.get("source") == core.MF_SOURCE for x in fr):
        raise RuntimeError("Frankreich enthält noch eine Nicht-Météo-France-Quelle.")
    if not all(x.get("source") == core.GHCN_SOURCE for x in es):
        raise RuntimeError("Spanien soll bis zur AEMET-Umstellung vollständig über GHCN kommen.")
    if austria_baseline:
        if not at or not all(x.get("source") == austria.SOURCE for x in at):
            raise RuntimeError("Österreich-Cache ist vorhanden, aber Österreich wurde nicht vollständig durch GeoSphere Austria ersetzt.")

    core.log(
        f"PUBLISH EUROPA OK: {payload.get('station_count', 0):,} Stationen in {payload.get('country_count', 0)} Ländern | "
        f"DWD {len(de):,} | Météo-France {len(fr):,} | "
        + (f"GeoSphere Austria {len(at):,} | " if austria_baseline else f"Österreich GHCN {len(at):,} | ")
        + f"GHCN {len(ghcn):,} (inkl. Spanien {len(es):,}) | Frankreich {mf_available}/{mf_total} Historical-Ressourcen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
