#!/usr/bin/env python3
"""Unified Europe station-record updater using national authoritative sources.

National sources:
- Germany: DWD CDC
- France: Météo-France
- Spain: AEMET OpenData (dedicated compact cache, 1920+)
- Austria: GeoSphere Austria
- Poland: IMGW-PIB
- Netherlands: KNMI
- Norway: MET Norway Frost (MET.NO station holders)
- Denmark: DMI Open Data (DMI yearbooks + transition bridge + climateData)
- Sweden: SMHI Open Data (CORE, historical G; current G/Y)
- Belgium: KMI/RMI Open Data (Uccle GHCN bridge; other stations SYNOP bridge; AWS 2000+)
- Switzerland: MeteoSwiss Open Data (SwissMetNet daily)
- remaining Europe: GHCN-Daily

The core Stations-V5 writer remains unchanged. Dedicated compact national
caches are adapted into the core StationMeta/state/current contracts before
writing ``europe_stations/index.json`` and the 366 calendar packs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
from typing import Any

import update_europe_station_records as core
import update_geosphere_austria_station_cache as austria
import update_imgw_poland_station_cache as poland
import update_aemet_spain_station_cache as aemet_hist
import update_aemet_spain_current as aemet_current_mod
import update_knmi_netherlands_station_cache as knmi_hist
import update_knmi_netherlands_current as knmi_current_mod
import update_frost_norway_station_cache as frost_hist
import update_frost_norway_current as frost_current_mod
import update_dmi_denmark_station_cache as dmi_hist
import update_dmi_denmark_current as dmi_current_mod
import update_smhi_sweden_station_cache as smhi_hist
import update_smhi_sweden_current as smhi_current_mod
import update_rmi_belgium_station_cache as belgium_hist
import update_rmi_belgium_current as belgium_current_mod
import update_meteoswiss_switzerland_station_cache as swiss_hist
import update_meteoswiss_switzerland_current as swiss_current_mod


ACTIVE_GRACE_DAYS = 45
NATIONAL_GHCN_CODES = {"GM", "FR", "SP", "ES", "AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ"}


def log(message: str) -> None:
    core.log(message)


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _iso_to_date_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value)[:10]
    try:
        return int(dt.date.fromisoformat(text).strftime("%Y%m%d"))
    except ValueError:
        return None


def _date_int_to_date(value: int | None) -> dt.date | None:
    if value is None:
        return None
    text = str(int(value))
    if len(text) != 8:
        return None
    try:
        return dt.date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _date_int_to_iso(value: int | None) -> str | None:
    day = _date_int_to_date(value)
    return day.isoformat() if day else None


def _tenths(value: Any) -> int | None:
    number = _finite_float(value)
    return None if number is None else int(round(number * 10.0))


def _compact_record_triplet(value_date: Any) -> tuple[int, int, int] | None:
    if not isinstance(value_date, (list, tuple)) or len(value_date) < 2:
        return None
    value = _tenths(value_date[0])
    date_int = _iso_to_date_int(value_date[1])
    if value is None or date_int is None:
        return None
    # Dedicated compact caches deliberately retain the earliest tie only.
    return value, date_int, 1


def _compact_record_pair(value_date: Any) -> tuple[int, int] | None:
    rec = _compact_record_triplet(value_date)
    return None if rec is None else (rec[0], rec[1])


def _span_years(record: dict[str, Any]) -> int:
    first = record.get("first_date")
    last = record.get("last_date")
    try:
        first_day = dt.date.fromisoformat(str(first)[:10])
        last_day = dt.date.fromisoformat(str(last)[:10])
    except ValueError:
        return 0
    if last_day < first_day:
        return 0
    return last_day.year - first_day.year + 1


def compact_records_to_core_states(
    records: dict[str, dict[str, Any]],
    *,
    prefix: str,
) -> dict[str, dict]:
    states: dict[str, dict] = {}
    for raw_id, record in records.items():
        if not isinstance(record, dict):
            continue
        sid = f"{prefix}:{raw_id}"
        state = core.empty_state()
        start = _iso_to_date_int(record.get("first_date"))
        end = _iso_to_date_int(record.get("last_date"))
        years = _span_years(record)

        for element, abs_key, cal_key in (
            ("TMAX", "tmax_abs", "calendar_tmax"),
            ("TMIN", "tmin_abs", "calendar_tmin"),
        ):
            block = state[element]
            block["abs"] = _compact_record_triplet(record.get(abs_key))
            cal: dict[str, tuple[int, int, int]] = {}
            raw_cal = record.get(cal_key, {})
            if isinstance(raw_cal, dict):
                for mmdd, value_date in raw_cal.items():
                    converted = _compact_record_triplet(value_date)
                    if converted is not None:
                        cal[str(mmdd)] = converted
            block["cal"] = cal
            has_values = block["abs"] is not None or bool(cal)
            block["start"] = start if has_values else None
            block["end"] = end if has_values else None
            # The compact national caches store first/last observation and
            # observation-day count, but not a distinct-year set. The inclusive
            # observation span is therefore used for the frontend length filter.
            block["years"] = years if has_values else 0
        if state["TMAX"]["abs"] is not None or state["TMIN"]["abs"] is not None:
            states[sid] = state
    return states


def compact_records_to_core_current(
    records: dict[str, dict[str, Any]],
    *,
    prefix: str,
) -> dict[str, dict]:
    current: dict[str, dict] = {}
    for raw_id, record in records.items():
        if not isinstance(record, dict):
            continue
        sid = f"{prefix}:{raw_id}"
        out = {"TMAX": {}, "TMIN": {}}
        for element, key in (("TMAX", "calendar_tmax"), ("TMIN", "calendar_tmin")):
            raw_cal = record.get(key, {})
            if not isinstance(raw_cal, dict):
                continue
            for mmdd, value_date in raw_cal.items():
                converted = _compact_record_pair(value_date)
                if converted is not None:
                    out[element][str(mmdd)] = converted
        if out["TMAX"] or out["TMIN"]:
            current[sid] = out
    return current


def _make_station_meta(
    *,
    sid: str,
    raw_meta: dict[str, Any],
    lat_keys: tuple[str, ...],
    lon_keys: tuple[str, ...],
    elev_keys: tuple[str, ...],
    name_keys: tuple[str, ...],
    country_code: str,
    country: str,
    source: str,
    quality_rule: str,
) -> core.StationMeta | None:
    def first(keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = raw_meta.get(key)
            if value not in (None, ""):
                return value
        return None

    lat = _finite_float(first(lat_keys))
    lon = _finite_float(first(lon_keys))
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    elev = _finite_float(first(elev_keys))
    name = str(first(name_keys) or sid.split(":", 1)[-1]).strip()
    return core.StationMeta(
        sid,
        lat,
        lon,
        None if elev is None else round(elev, 1),
        name,
        country_code,
        country,
        source,
        quality_rule,
    )


def aemet_inventory_to_meta(inventory: dict[str, dict[str, Any]]) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    for raw_id, meta in inventory.items():
        if not isinstance(meta, dict):
            continue
        sid = f"AEMET:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("latitude", "lat"),
            lon_keys=("longitude", "lon"),
            elev_keys=("height", "elevation_m", "elevation"),
            name_keys=("name", "nombre"),
            country_code="ES",
            country="Spanien",
            source=aemet_hist.SOURCE,
            quality_rule=(
                "AEMET OpenData Tagesklimatologie: tmax/tmin wie veröffentlicht; "
                "fehlende oder nichtnumerische Werte werden verworfen."
            ),
        )
        if station is not None:
            out[sid] = station
    return out


def _knmi_ghcn_fallback(
    raw_id: str,
    ghcn_nl_stations: dict[str, core.StationMeta],
) -> core.StationMeta | None:
    """Resolve KNMI's three-digit station number through its WMO/GHCN id.

    KNMI station 260 corresponds to WMO 06260 and therefore normally to
    GHCN-Daily id NLM00006260.  We use GHCN here only as a coordinate/name
    metadata fallback; all temperature observations and records remain KNMI.
    """
    code = str(raw_id).strip()
    if not code.isdigit():
        return None
    code3 = code.zfill(3)[-3:]

    preferred_ids = (
        f"NLM00006{code3}",
        f"NLW00006{code3}",
    )
    candidate = None
    for ghcn_id in preferred_ids:
        if ghcn_id in ghcn_nl_stations:
            candidate = ghcn_nl_stations[ghcn_id]
            break

    if candidate is None:
        # Defensive fallback for any alternative GHCN identifier carrying
        # the same Dutch/WMO station suffix.
        matches = [
            meta
            for ghcn_id, meta in ghcn_nl_stations.items()
            if ghcn_id.endswith(code3)
        ]
        if len(matches) == 1:
            candidate = matches[0]
        elif matches:
            # Prefer IDs containing the Dutch WMO block 06xxx.
            matches.sort(
                key=lambda meta: (
                    "00006" not in meta.id,
                    meta.id,
                )
            )
            candidate = matches[0]

    if candidate is None:
        return None

    sid = f"KNMI:{code}"
    return core.StationMeta(
        sid,
        candidate.lat,
        candidate.lon,
        candidate.elev,
        candidate.name or f"KNMI {code}",
        "NL",
        "Niederlande",
        knmi_hist.SOURCE,
        (
            "KNMI Daggegevens: tägliche TX/TN; veröffentlichte Werte in 0,1 °C "
            "werden in °C umgerechnet, Fehlwerte verworfen. "
            "Stationskoordinaten/-name bei fehlenden KNMI-Antwortmetadaten "
            "über die zugehörige niederländische WMO/GHCN-Stationskennung."
        ),
    )


def knmi_inventory_to_meta(
    inventory: dict[str, dict[str, Any]],
    *,
    record_ids: set[str] | None = None,
    ghcn_nl_stations: dict[str, core.StationMeta] | None = None,
) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    ghcn_nl_stations = ghcn_nl_stations or {}

    raw_ids = set(str(x) for x in inventory)
    if record_ids:
        raw_ids.update(str(x) for x in record_ids)

    for raw_id in sorted(raw_ids):
        meta = inventory.get(raw_id)
        if not isinstance(meta, dict):
            # Some dicts may use a numeric-looking key object; be defensive.
            meta = inventory.get(str(raw_id))

        station = None
        if isinstance(meta, dict):
            station = _make_station_meta(
                sid=f"KNMI:{raw_id}",
                raw_meta=meta,
                lat_keys=("lat", "latitude"),
                lon_keys=("lon", "longitude"),
                elev_keys=("elevation_m", "elevation", "height"),
                name_keys=("name",),
                country_code="NL",
                country="Niederlande",
                source=knmi_hist.SOURCE,
                quality_rule=(
                    "KNMI Daggegevens: tägliche TX/TN; veröffentlichte Werte in 0,1 °C "
                    "werden in °C umgerechnet, Fehlwerte verworfen."
                ),
            )

        if station is None:
            station = _knmi_ghcn_fallback(raw_id, ghcn_nl_stations)

        if station is not None:
            out[station.id] = station

    return out


def frost_inventory_to_meta(inventory: dict[str, dict[str, Any]]) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    for raw_id, meta in inventory.items():
        if not isinstance(meta, dict):
            continue
        sid = f"FROST:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat", "latitude"),
            lon_keys=("lon", "longitude"),
            elev_keys=("elevation_m", "elevation", "height"),
            name_keys=("name",),
            country_code="NO",
            country="Norwegen",
            source=frost_hist.SOURCE,
            quality_rule=(
                "MET Norway Frost: SensorSystem-Quellen mit Stationshalter MET.NO; "
                "max/min(air_temperature P1D), Standard-Zeitreihe/-Level, Quality 0–4."
            ),
        )
        if station is not None:
            out[sid] = station
    return out



def _dmi_ghcn_metadata_fallback(
    raw_id: str,
    raw_meta: dict[str, Any] | None,
    ghcn_dk_stations: dict[str, core.StationMeta],
) -> core.StationMeta | None:
    """Use GHCN/WMO only as a metadata fallback for a DMI station.

    Temperature observations and records remain DMI/its documented historical
    transition cache. This fallback supplies only map coordinates/name where a
    historical DMI inventory row has no usable geometry.
    """
    raw_meta = raw_meta if isinstance(raw_meta, dict) else {}
    candidates: list[str] = []

    wmo = str(raw_meta.get("wmo_station_id") or "").strip()
    if wmo.isdigit():
        candidates.append(wmo.zfill(5)[-5:])

    code = str(raw_id).strip()
    if code.isdigit():
        candidates.append(code.zfill(5)[-5:])

    candidates = list(dict.fromkeys(candidates))
    candidate: core.StationMeta | None = None

    for suffix in candidates:
        for ghcn_id in (f"DAM000{suffix}", f"DAW000{suffix}"):
            if ghcn_id in ghcn_dk_stations:
                candidate = ghcn_dk_stations[ghcn_id]
                break
        if candidate is not None:
            break

        matches = [
            meta
            for ghcn_id, meta in ghcn_dk_stations.items()
            if ghcn_id.endswith(suffix)
        ]
        if len(matches) == 1:
            candidate = matches[0]
            break
        if matches:
            matches.sort(key=lambda meta: ("M000" not in meta.id, meta.id))
            candidate = matches[0]
            break

    if candidate is None:
        return None

    sid = f"DMI:{raw_id}"
    return core.StationMeta(
        sid,
        candidate.lat,
        candidate.lon,
        candidate.elev,
        str(raw_meta.get("name") or candidate.name or raw_id).strip(),
        "DK",
        "Dänemark",
        dmi_hist.SOURCE,
        (
            "DMI Open Data: historische Jahrbuch-Tageswerte tmax/tmin; "
            "dokumentierte GHCN-Daily-Übergangsbrücke für fehlende Jahrbuchjahre "
            "und 1984–2010; ab 2011 DMI climateData max_temp_w_date/min_temp "
            "für den dänischen lokalen Kalendertag. GHCN wird hier nur als "
            "Metadatenfallback für Koordinaten/Stationsname verwendet."
        ),
    )


def dmi_inventory_to_meta(
    inventory: dict[str, dict[str, Any]],
    *,
    record_ids: set[str] | None = None,
    ghcn_dk_stations: dict[str, core.StationMeta] | None = None,
) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    ghcn_dk_stations = ghcn_dk_stations or {}

    raw_ids = set(str(x) for x in inventory)
    if record_ids:
        raw_ids.update(str(x) for x in record_ids)

    for raw_id in sorted(raw_ids):
        raw_meta = inventory.get(raw_id)
        if not isinstance(raw_meta, dict):
            raw_meta = {}

        station = _make_station_meta(
            sid=f"DMI:{raw_id}",
            raw_meta=raw_meta,
            lat_keys=("lat", "latitude"),
            lon_keys=("lon", "longitude"),
            elev_keys=("elevation_m", "elevation", "height"),
            name_keys=("name",),
            country_code="DK",
            country="Dänemark",
            source=dmi_hist.SOURCE,
            quality_rule=(
                "DMI Open Data: 1867–1983 digitalisierte Meteorological Yearbooks "
                "(direkte tmax/tmin; offiziell fehlende Jahrbücher 1971–1975, "
                "1977–1978 über die dokumentierte GHCN-Daily-Brücke), 1984–2010 "
                "GHCN-Daily-Übergangsbrücke, ab 2011 qualitätskontrollierte "
                "DMI climateData max_temp_w_date/min_temp nach dänischem Lokaltag."
            ),
        )

        if station is None:
            station = _dmi_ghcn_metadata_fallback(
                raw_id,
                raw_meta,
                ghcn_dk_stations,
            )

        if station is not None:
            out[station.id] = station

    return out



def smhi_inventory_to_meta(inventory: dict[str, dict[str, Any]]) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    for raw_id, meta in inventory.items():
        if not isinstance(meta, dict):
            continue
        sid = f"SMHI:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat", "latitude"),
            lon_keys=("lon", "longitude"),
            elev_keys=("elevation_m", "height", "elevation"),
            name_keys=("name",),
            country_code="SE",
            country="Schweden",
            source=smhi_hist.SOURCE,
            quality_rule=(
                "SMHI MetObs CORE: tägliches Tmin Parameter 19 und Tmax Parameter 20. "
                "Historische corrected-archive-Werte nur mit Qualität G; im laufenden "
                "Jahr G und vorläufiges Y, wobei G bei Überlappung Vorrang hat."
            ),
        )
        if station is not None:
            out[sid] = station
    return out


def belgium_inventory_to_meta(inventory: dict[str, dict[str, Any]]) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    for raw_id, meta in inventory.items():
        if not isinstance(meta, dict):
            continue
        sid = f"RMI:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat", "latitude"),
            lon_keys=("lon", "longitude"),
            elev_keys=("elevation_m", "elevation", "height"),
            name_keys=("name",),
            country_code="BE",
            country="Belgien",
            source=belgium_hist.SOURCE,
            quality_rule=(
                "Belgien-Hybrid: Uccle 06447 vor 2000 aus GHCN-Daily mit leerem Q-FLAG; "
                "übrige belgische Stationen 1952–1999 aus KMI/RMI SYNOP "
                "(Tmin 18–06 UTC, Tmax 06–18 UTC); ab 2000 für alle Stationen "
                "KMI/RMI AWS aws_1day."
            ),
        )
        if station is not None:
            out[sid] = station
    return out


def swiss_inventory_to_meta(inventory: dict[str, dict[str, Any]]) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    for raw_id, meta in inventory.items():
        if not isinstance(meta, dict):
            continue
        sid = f"METEOSWISS:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=(
                "lat", "latitude", "station_coordinates_wgs84_lat",
                "station_coordinates_wgs84_latitude",
            ),
            lon_keys=(
                "lon", "longitude", "station_coordinates_wgs84_lon",
                "station_coordinates_wgs84_longitude",
            ),
            elev_keys=("elevation_m", "elevation", "height"),
            name_keys=("name",),
            country_code="CH",
            country="Schweiz",
            source=swiss_hist.SOURCE,
            quality_rule=(
                "MeteoSwiss SwissMetNet Tageswerte: tre200dn (Tmin) und tre200dx (Tmax) "
                "aus daily historical/recent. Homogenisierte NBCN-Tagesreihen werden "
                "bewusst nicht mit den beobachteten Stationsrekorden vermischt."
            ),
        )
        if station is not None:
            out[sid] = station
    return out


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


def validate_meteoswiss_historical_extremes(payload: dict[str, Any]) -> None:
    """Fail closed if a stale Swiss cache still contains impossible records."""
    bad = []
    records = payload.get("records", {})
    if not isinstance(records, dict):
        return
    for sid, rec in records.items():
        if not isinstance(rec, dict):
            continue
        for key, bound, mode in (
            ("tmax_abs", swiss_hist.HISTORICAL_TMAX_CEILING_C, "max"),
            ("tmin_abs", swiss_hist.HISTORICAL_TMIN_FLOOR_C, "min"),
        ):
            pair = rec.get(key)
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                value = float(pair[0])
                if (mode == "max" and value > bound) or (mode == "min" and value < bound):
                    bad.append(f"{sid} {key}={value} C ({pair[1]})")
        for key, bound, mode in (
            ("calendar_tmax", swiss_hist.HISTORICAL_TMAX_CEILING_C, "max"),
            ("calendar_tmin", swiss_hist.HISTORICAL_TMIN_FLOOR_C, "min"),
        ):
            cal = rec.get(key, {})
            if not isinstance(cal, dict):
                continue
            for mmdd, pair in cal.items():
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                value = float(pair[0])
                if (mode == "max" and value > bound) or (mode == "min" and value < bound):
                    bad.append(f"{sid} {key} {mmdd}={value} C ({pair[1]})")
                    if len(bad) >= 20:
                        break
            if len(bad) >= 20:
                break
        if len(bad) >= 20:
            break
    if bad:
        raise RuntimeError(
            "MeteoSwiss-Historiencache enthält Werte außerhalb der offiziellen "
            "Schweizer Messrekorde. Schweiz-Baseline v2 neu aufbauen. Beispiele: "
            + "; ".join(bad)
        )


def _load_compact_national_sources(
    cache_dir: Path,
    current_year: int,
    *,
    force_aemet: bool,
    force_knmi: bool,
    force_frost: bool,
    force_dmi: bool,
    force_smhi: bool,
    force_belgium: bool,
    force_swiss: bool,
) -> tuple[dict, ...]:
    cutoff_year = current_year - 1
    aemet_key = os.environ.get("AEMET_API_KEY", "").strip()
    frost_client_id = os.environ.get("FROST_CLIENT_ID", "").strip()
    if not aemet_key:
        raise RuntimeError("AEMET_API_KEY fehlt.")
    if not frost_client_id:
        raise RuntimeError("FROST_CLIENT_ID fehlt.")

    aemet_hist.build_baseline(
        api_key=aemet_key,
        cutoff_year=cutoff_year,
        cache_dir=cache_dir,
        force=force_aemet,
    )
    aemet_base = aemet_hist.load_baseline(cache_dir, cutoff_year)

    knmi_hist.build_baseline(cache_dir, cutoff_year, force=force_knmi)
    knmi_base_path = knmi_hist.baseline_path(cache_dir, cutoff_year)
    knmi_base = knmi_hist.load_pickle_gzip(knmi_base_path)
    if not isinstance(knmi_base, dict) or not knmi_base.get("complete"):
        raise RuntimeError(f"KNMI-Baseline unvollständig: {knmi_base_path}")

    frost_hist.build_baseline(
        frost_client_id,
        cache_dir,
        cutoff_year,
        force=force_frost,
    )
    frost_base_path = frost_hist.baseline_path(cache_dir, cutoff_year)
    if not frost_hist.valid_final(frost_base_path, cutoff_year):
        raise RuntimeError(f"Frost-Baseline unvollständig: {frost_base_path}")
    frost_base = frost_hist.load_pickle_gzip(frost_base_path)

    dmi_hist.build_baseline(
        cache_dir,
        cutoff_year,
        force=force_dmi,
        max_runtime_minutes=300.0,
    )
    dmi_base = dmi_hist.load_baseline(cache_dir, cutoff_year)

    smhi_hist.build_baseline(
        cache_dir,
        cutoff_year,
        force=force_smhi,
        max_runtime_minutes=300.0,
    )
    smhi_base = smhi_hist.load_baseline(cache_dir, cutoff_year)

    belgium_hist.build_baseline(
        cache_dir,
        cutoff_year,
        force=force_belgium,
        max_runtime_minutes=300.0,
    )
    belgium_base = belgium_hist.load_baseline(cache_dir, cutoff_year)

    swiss_hist.build_baseline(
        cache_dir,
        cutoff_year,
        force=force_swiss,
        max_runtime_minutes=300.0,
    )
    swiss_base = swiss_hist.load_baseline(cache_dir, cutoff_year)
    validate_meteoswiss_historical_extremes(swiss_base)

    # Running year is deliberately refreshed on every unified run.
    aemet_current_path = aemet_current_mod.build_current(
        api_key=aemet_key,
        year=current_year,
        cache_dir=cache_dir,
    )
    aemet_cur = aemet_hist._load_pickle_gz(aemet_current_path)

    knmi_current_path = knmi_current_mod.build_current(cache_dir, current_year)
    knmi_cur = knmi_hist.load_pickle_gzip(knmi_current_path)

    frost_current_path = frost_current_mod.build_current(
        frost_client_id,
        cache_dir,
        current_year,
    )
    frost_cur = frost_hist.load_pickle_gzip(frost_current_path)

    dmi_current_path = dmi_current_mod.build_current(cache_dir, current_year)
    dmi_cur = dmi_hist.load_pickle_gzip(dmi_current_path)

    smhi_current_path = smhi_current_mod.build_current(cache_dir, current_year)
    smhi_cur = smhi_current_mod.load_pickle_gzip(smhi_current_path)

    belgium_current_path = belgium_current_mod.build_current(cache_dir, current_year)
    belgium_cur = belgium_hist.load_pickle_gzip(belgium_current_path)

    swiss_current_path = swiss_current_mod.build_current(cache_dir, current_year)
    swiss_cur = swiss_hist.load_pickle_gzip(swiss_current_path)

    return (
        aemet_base, aemet_cur,
        knmi_base, knmi_cur,
        frost_base, frost_cur,
        dmi_base, dmi_cur,
        smhi_base, smhi_cur,
        belgium_base, belgium_cur,
        swiss_base, swiss_cur,
    )


def _source_counts(index_payload: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in index_payload.get("stations", []):
        source = row.get("source")
        if source:
            counts[source] = counts.get(source, 0) + 1
    return counts


def _latest_current_date(cur_state: dict[str, Any]) -> int | None:
    latest: int | None = None
    for element in ("TMAX", "TMIN"):
        values = cur_state.get(element, {}) if isinstance(cur_state, dict) else {}
        if not isinstance(values, dict):
            continue
        for obs in values.values():
            if not isinstance(obs, (list, tuple)) or len(obs) < 2:
                continue
            try:
                date_int = int(obs[1])
            except (TypeError, ValueError):
                continue
            latest = date_int if latest is None else max(latest, date_int)
    return latest


def _latest_historical_date(state: dict[str, Any]) -> int | None:
    latest: int | None = None
    for element in ("TMAX", "TMIN"):
        block = state.get(element, {}) if isinstance(state, dict) else {}
        try:
            end = int(block.get("end")) if block.get("end") is not None else None
        except (TypeError, ValueError):
            end = None
        if end is not None:
            latest = end if latest is None else max(latest, end)
    return latest


def add_station_activity(
    payload: dict,
    *,
    stations: dict[str, core.StationMeta],
    states: dict[str, dict],
    current: dict[str, dict],
) -> None:
    station_current: dict[str, int | None] = {
        sid: _latest_current_date(cur_state)
        for sid, cur_state in current.items()
    }
    source_latest: dict[str, int] = {}
    for sid, date_int in station_current.items():
        if date_int is None:
            continue
        meta = stations.get(sid)
        if meta is None:
            continue
        old = source_latest.get(meta.source)
        source_latest[meta.source] = date_int if old is None else max(old, date_int)

    thresholds: dict[str, dt.date] = {}
    for source, date_int in source_latest.items():
        day = _date_int_to_date(date_int)
        if day is not None:
            thresholds[source] = day - dt.timedelta(days=ACTIVE_GRACE_DAYS)

    active_count = 0
    for row in payload.get("stations", []):
        sid = str(row.get("id") or "")
        meta = stations.get(sid)
        current_int = station_current.get(sid)
        historical_int = _latest_historical_date(states.get(sid, {}))
        last_int = max(
            [x for x in (historical_int, current_int) if x is not None],
            default=None,
        )
        row["last_observation"] = _date_int_to_iso(last_int)

        current_day = _date_int_to_date(current_int)
        threshold = thresholds.get(meta.source) if meta else None
        active = bool(current_day is not None and threshold is not None and current_day >= threshold)
        row["active"] = active
        if active:
            active_count += 1

    payload["active_station_count"] = active_count
    payload["active_grace_days"] = ACTIVE_GRACE_DAYS
    payload["active_rule"] = (
        "Eine Station gilt als aktiv, wenn ihr letzter Wert des laufenden Jahres "
        f"höchstens {ACTIVE_GRACE_DAYS} Tage hinter dem neuesten Wert ihrer eigenen Datenquelle liegt."
    )
    payload["source_latest_observation"] = {
        source: _date_int_to_iso(value)
        for source, value in sorted(source_latest.items())
    }


def patch_index_metadata(
    output_dir: Path,
    *,
    current_year: int,
    stations: dict[str, core.StationMeta],
    states: dict[str, dict],
    current: dict[str, dict],
    austria_current_count: int,
    poland_current_count: int,
    poland_latest_month: int | None,
    aemet_current_count: int,
    knmi_current_count: int,
    frost_current_count: int,
    dmi_current_count: int,
    smhi_current_count: int,
    belgium_current_count: int,
    swiss_current_count: int,
) -> dict:
    path = output_dir / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    add_station_activity(payload, stations=stations, states=states, current=current)
    counts = _source_counts(payload)

    payload["source"] = (
        "DWD CDC (Deutschland) + Météo-France (Frankreich) + "
        "AEMET OpenData (Spanien) + GeoSphere Austria (Österreich) + "
        "IMGW-PIB (Polen) + KNMI (Niederlande) + MET Norway Frost (Norwegen) + "
        "DMI Open Data (Dänemark) + SMHI Open Data (Schweden) + "
        "KMI/RMI Open Data (Belgien) + MeteoSwiss Open Data (Schweiz) + "
        "GHCN-Daily (übriges Europa)"
    )
    payload["sources"] = [
        {"name": core.DWD_SOURCE, "scope": "Deutschland", "url": core.DWD_BASE, "stations": counts.get(core.DWD_SOURCE, 0)},
        {"name": core.MF_SOURCE, "scope": "Frankreich", "url": core.MF_PUBLIC_BASE, "stations": counts.get(core.MF_SOURCE, 0)},
        {"name": aemet_hist.SOURCE, "scope": "Spanien", "url": aemet_hist.PUBLIC_URL, "stations": counts.get(aemet_hist.SOURCE, 0)},
        {"name": austria.SOURCE, "scope": "Österreich", "url": austria.PUBLIC_URL, "stations": counts.get(austria.SOURCE, 0)},
        {"name": poland.SOURCE, "scope": "Polen", "url": poland.PUBLIC_URL, "stations": counts.get(poland.SOURCE, 0)},
        {"name": knmi_hist.SOURCE, "scope": "Niederlande", "url": knmi_hist.PUBLIC_URL, "stations": counts.get(knmi_hist.SOURCE, 0)},
        {"name": frost_hist.SOURCE, "scope": "Norwegen", "url": frost_hist.PUBLIC_URL, "stations": counts.get(frost_hist.SOURCE, 0)},
        {"name": dmi_hist.SOURCE, "scope": "Dänemark", "url": dmi_hist.PUBLIC_URL, "stations": counts.get(dmi_hist.SOURCE, 0)},
        {"name": smhi_hist.SOURCE, "scope": "Schweden", "url": smhi_hist.PUBLIC_URL, "stations": counts.get(smhi_hist.SOURCE, 0)},
        {"name": belgium_hist.SOURCE, "scope": "Belgien", "url": belgium_hist.PUBLIC_URL, "stations": counts.get(belgium_hist.SOURCE, 0)},
        {"name": swiss_hist.SOURCE, "scope": "Schweiz", "url": f"https://data.geo.admin.ch/api/stac/v1/collections/{swiss_hist.COLLECTION_ID}", "stations": counts.get(swiss_hist.SOURCE, 0)},
        {"name": core.GHCN_SOURCE, "scope": "übriges Europa", "url": core.GHCN_BASE, "stations": counts.get(core.GHCN_SOURCE, 0)},
    ]
    payload["quality_rule"] = (
        "Deutschland: DWD CDC Tageswerte KL (TXK/TNK, Fehlwerte verworfen). "
        "Frankreich: Météo-France TX/TN aus täglichen Klimadateien; Qualitätscodes 0/1/9 bzw. ältere leere Codes akzeptiert, Code 2 verworfen. "
        "Spanien: AEMET OpenData tmax/tmin wie veröffentlicht. "
        "Österreich: GeoSphere Austria klima-v2-1d, tägliche tlmax/tlmin. "
        "Polen: IMGW-PIB tägliche Klimadaten k_d mit TMAX/TMIN. "
        "Niederlande: KNMI Daggegevens TX/TN. "
        "Norwegen: MET Norway Frost tägliche max/min(air_temperature P1D), MET.NO-Stationshalter, Standard-Zeitreihe/-Level, Quality 0–4. "
        "Dänemark: DMI-Jahrbücher 1867–1983 mit tmax/tmin, dokumentierte GHCN-Daily-Übergangsbrücke für fehlende Jahrbücher und 1984–2010, ab 2011 DMI climateData. "
        "Schweden: SMHI MetObs CORE, historisch corrected-archive nur Qualität G; aktuell G/Y mit G-Vorrang. "
        "Belgien: Uccle vor 2000 GHCN-Daily (leerer Q-FLAG), übrige Stationen 1952–1999 KMI/RMI SYNOP; ab 2000 KMI/RMI AWS aws_1day. "
        "Schweiz: MeteoSwiss SwissMetNet Tageswerte tre200dn/tre200dx; NBCN-Homogenreihen werden nicht eingemischt. "
        "Übriges Europa: GHCN-Daily TMAX/TMIN nur mit leerem Q-FLAG."
    )
    payload["history_scope"] = (
        f"Historische Baselines bis {current_year - 1}: DWD Deutschland, Météo-France Frankreich, "
        "AEMET Spanien ab 1920, GeoSphere Austria Österreich, IMGW-PIB Polen, "
        "KNMI Niederlande ab 1901, MET Norway Frost für MET.NO-Stationen, "
        "DMI Dänemark ab 1867 mit dokumentierter Übergangsbrücke, SMHI Schweden, "
        "KMI/RMI Belgien mit historischer Hybridbrücke sowie MeteoSwiss SwissMetNet Schweiz ab 1864; "
        "GHCN-Daily für das übrige Europa. "
        f"Das laufende Jahr {current_year} wird bei jedem Workflow-Lauf separat aktualisiert."
    )
    payload["publication_scope"] = (
        "Europa vollständig: nationale Quellen für Deutschland, Frankreich, Spanien, Österreich, Polen, "
        "Niederlande, Norwegen, Dänemark, Schweden, Belgien und die Schweiz; GHCN-Daily für Rest-Europa"
    )
    payload["coverage"] = {
        "Deutschland": {"source": core.DWD_SOURCE, "historical_complete": True},
        "Frankreich": {"source": core.MF_SOURCE, "historical_complete": True},
        "Spanien": {"source": aemet_hist.SOURCE, "historical_complete": True, "current_year_station_count": aemet_current_count},
        "Österreich": {"source": austria.SOURCE, "historical_complete": True, "current_year_station_count": austria_current_count},
        "Polen": {"source": poland.SOURCE, "historical_complete": True, "current_year_station_count": poland_current_count, "current_year_latest_published_month": poland_latest_month},
        "Niederlande": {"source": knmi_hist.SOURCE, "historical_complete": True, "current_year_station_count": knmi_current_count},
        "Norwegen": {"source": frost_hist.SOURCE, "historical_complete": True, "current_year_station_count": frost_current_count},
        "Dänemark": {
            "source": dmi_hist.SOURCE,
            "historical_complete": True,
            "current_year_station_count": dmi_current_count,
            "history_note": (
                "DMI-Jahrbücher 1867–1983; GHCN-Daily nur als dokumentierte "
                "Übergangs-/Lückenbrücke; DMI climateData ab 2011."
            ),
        },
        "Schweden": {
            "source": smhi_hist.SOURCE,
            "historical_complete": True,
            "current_year_station_count": smhi_current_count,
            "history_note": "SMHI CORE; historische corrected-archive-Werte nur Qualität G; laufendes Jahr G/Y mit G-Vorrang.",
        },
        "Belgien": {
            "source": belgium_hist.SOURCE,
            "historical_complete": True,
            "current_year_station_count": belgium_current_count,
            "history_note": "Uccle vor 2000 GHCN-Daily; übrige Stationen 1952–1999 KMI/RMI SYNOP; ab 2000 KMI/RMI AWS.",
        },
        "Schweiz": {
            "source": swiss_hist.SOURCE,
            "historical_complete": True,
            "current_year_station_count": swiss_current_count,
            "history_note": "MeteoSwiss SwissMetNet tre200dn/tre200dx; NBCN-Homogenreihen bewusst ausgeschlossen.",
        },
        "Rest-Europa": {"source": core.GHCN_SOURCE, "historical_complete": True},
    }

    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


def validate_payload(payload: dict) -> None:
    rows = payload.get("stations", [])
    expected = {
        "Deutschland": core.DWD_SOURCE,
        "Frankreich": core.MF_SOURCE,
        "Spanien": aemet_hist.SOURCE,
        "Österreich": austria.SOURCE,
        "Polen": poland.SOURCE,
        "Niederlande": knmi_hist.SOURCE,
        "Norwegen": frost_hist.SOURCE,
        "Dänemark": dmi_hist.SOURCE,
        "Schweden": smhi_hist.SOURCE,
        "Belgien": belgium_hist.SOURCE,
        "Schweiz": swiss_hist.SOURCE,
    }
    for country, source in expected.items():
        country_rows = [row for row in rows if row.get("country") == country]
        if not country_rows:
            raise RuntimeError(f"Keine Stationen für {country} erzeugt.")
        wrong = [row for row in country_rows if row.get("source") != source]
        if wrong:
            wrong_sources = sorted({row.get("source") for row in wrong})
            raise RuntimeError(f"{country} enthält falsche/gemischte Quellen: {wrong_sources}; erwartet {source}.")

    ghcn_rows = [row for row in rows if row.get("source") == core.GHCN_SOURCE]
    if not ghcn_rows:
        raise RuntimeError("Keine GHCN-Daily-Stationen für Rest-Europa erzeugt.")
    forbidden_ghcn = [row for row in ghcn_rows if row.get("country_code") in NATIONAL_GHCN_CODES]
    if forbidden_ghcn:
        codes = sorted({row.get("country_code") for row in forbidden_ghcn})
        raise RuntimeError(f"GHCN enthält weiterhin national ersetzte Länder: {codes}")

    if len({row.get("country") for row in rows}) < 10:
        raise RuntimeError("Zu wenige Länder in der Europa-Ausgabe.")

    counts = _source_counts(payload)
    for source in (
        core.DWD_SOURCE,
        core.MF_SOURCE,
        aemet_hist.SOURCE,
        austria.SOURCE,
        poland.SOURCE,
        knmi_hist.SOURCE,
        frost_hist.SOURCE,
        dmi_hist.SOURCE,
        smhi_hist.SOURCE,
        belgium_hist.SOURCE,
        swiss_hist.SOURCE,
        core.GHCN_SOURCE,
    ):
        if counts.get(source, 0) <= 0:
            raise RuntimeError(f"Quelle {source} hat 0 Stationen.")

    if not rows or any("active" not in row or "last_observation" not in row for row in rows):
        raise RuntimeError("Aktivstatus/letzte Beobachtung fehlt bei mindestens einer Station.")
    if int(payload.get("active_station_count", 0)) <= 0:
        raise RuntimeError("Aktivfilter würde 0 Stationen liefern.")

    log("Europa-Quellenprüfung OK: " + ", ".join(f"{name}={count:,}" for name, count in sorted(counts.items())))
    log(f"Aktive Stationen nach {ACTIVE_GRACE_DAYS}-Tage-Regel: {payload.get('active_station_count', 0):,}")


def self_test() -> None:
    # KNMI station metadata may be absent from Daggegevens responses.
    # Verify WMO/GHCN fallback: KNMI 260 -> NLM00006260 (De Bilt).
    fake_ghcn = {
        "NLM00006260": core.StationMeta(
            "NLM00006260", 52.101, 5.177, 2.0, "DE BILT",
            "NL", "Niederlande", core.GHCN_SOURCE, "test"
        )
    }
    knmi_meta_test = knmi_inventory_to_meta(
        {},
        record_ids={"260"},
        ghcn_nl_stations=fake_ghcn,
    )
    assert "KNMI:260" in knmi_meta_test
    assert abs(knmi_meta_test["KNMI:260"].lat - 52.101) < 1e-9
    assert knmi_meta_test["KNMI:260"].source == knmi_hist.SOURCE

    fake_dk_ghcn = {
        "DAM00006030": core.StationMeta(
            "DAM00006030", 57.736, 10.631, 5.0, "SKAGEN",
            "DA", "Dänemark", core.GHCN_SOURCE, "test"
        )
    }
    dmi_meta_test = dmi_inventory_to_meta(
        {
            "06030": {
                "name": "SKAGEN",
                "wmo_station_id": "06030",
                "lat": None,
                "lon": None,
            }
        },
        record_ids={"06030"},
        ghcn_dk_stations=fake_dk_ghcn,
    )
    assert "DMI:06030" in dmi_meta_test
    assert dmi_meta_test["DMI:06030"].source == dmi_hist.SOURCE
    assert dmi_meta_test["DMI:06030"].country == "Dänemark"

    assert {"SW", "BE", "SZ"}.issubset(NATIONAL_GHCN_CODES)

    smhi_meta_test = smhi_inventory_to_meta({"1": {"name": "Test SE", "lat": 60.0, "lon": 15.0, "elevation_m": 100}})
    assert smhi_meta_test["SMHI:1"].country == "Schweden"
    belgium_meta_test = belgium_inventory_to_meta({"6447": {"name": "Uccle", "lat": 50.8, "lon": 4.35, "elevation_m": 100}})
    assert belgium_meta_test["RMI:6447"].source == belgium_hist.SOURCE
    swiss_meta_test = swiss_inventory_to_meta({"BER": {"name": "Bern", "lat": 46.95, "lon": 7.45, "elevation_m": 553}})
    assert swiss_meta_test["METEOSWISS:BER"].country == "Schweiz"

    sample_records = {
        "X": {
            "first_date": "1901-01-01",
            "last_date": "2025-12-31",
            "observation_days": 1000,
            "tmax_abs": [40.1, "2020-07-01"],
            "tmin_abs": [-20.2, "1940-01-01"],
            "calendar_tmax": {"07-01": [40.1, "2020-07-01"]},
            "calendar_tmin": {"01-01": [-20.2, "1940-01-01"]},
        }
    }
    states = compact_records_to_core_states(sample_records, prefix="TEST")
    assert states["TEST:X"]["TMAX"]["abs"] == (401, 20200701, 1)
    assert states["TEST:X"]["TMIN"]["cal"]["01-01"] == (-202, 19400101, 1)
    current = compact_records_to_core_current(
        {"X": {"calendar_tmax": {"08-01": [31.2, "2026-08-01"]}, "calendar_tmin": {}}},
        prefix="TEST",
    )
    assert current["TEST:X"]["TMAX"]["08-01"] == (312, 20260801)

    meta = core.StationMeta("TEST:X", 50.0, 8.0, 100.0, "Test", "ZZ", "Testland", "TEST", "test")
    payload = {"stations": [{"id": "TEST:X", "source": "TEST"}]}
    add_station_activity(payload, stations={"TEST:X": meta}, states=states, current=current)
    assert payload["stations"][0]["active"] is True
    assert payload["stations"][0]["last_observation"] == "2026-08-01"
    validate_meteoswiss_historical_extremes({
        "records": {
            "GRO": {
                "tmax_abs": [41.5, "2003-08-11"],
                "tmin_abs": [-10.0, "2003-01-01"],
                "calendar_tmax": {"08-11": [41.5, "2003-08-11"]},
                "calendar_tmin": {"01-01": [-10.0, "2003-01-01"]},
            }
        }
    })
    try:
        validate_meteoswiss_historical_extremes({
            "records": {
                "CMA": {
                    "tmax_abs": [51.8, "2000-01-02"],
                    "calendar_tmax": {"01-02": [51.8, "2000-01-02"]},
                }
            }
        })
    except RuntimeError:
        pass
    else:
        raise AssertionError("MeteoSwiss historical fail-safe did not reject 51.8 C")

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
    parser.add_argument("--force-knmi-baseline", action="store_true")
    parser.add_argument("--force-frost-baseline", action="store_true")
    parser.add_argument("--force-dmi-baseline", action="store_true")
    parser.add_argument("--force-smhi-baseline", action="store_true")
    parser.add_argument("--force-belgium-baseline", action="store_true")
    parser.add_argument("--force-swiss-baseline", action="store_true")
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
    if not os.environ.get("FROST_CLIENT_ID", "").strip():
        raise RuntimeError("FROST_CLIENT_ID fehlt.")

    log("=== EUROPA-STATIONSREKORDE · ALLE NATIONALEN QUELLEN ===")
    log(
        "DWD Deutschland + Météo-France Frankreich + AEMET Spanien + GeoSphere Austria + "
        "IMGW Polen + KNMI Niederlande + MET Norway Frost + DMI Dänemark + "
        "SMHI Schweden + KMI/RMI Belgien + MeteoSwiss Schweiz + GHCN-Daily Rest-Europa."
    )

    countries = core.parse_countries(core.read_url_text(core.COUNTRIES_URL))
    ghcn_all_stations = core.parse_ghcn_stations(core.read_url_text(core.STATIONS_URL), countries)

    # Keep national GHCN/WMO metadata only as coordinate/name lookups where
    # an authoritative national inventory has no usable geometry.
    # Their observations remain excluded from GHCN below.
    ghcn_nl_metadata = {
        sid: meta
        for sid, meta in ghcn_all_stations.items()
        if meta.country_code == "NL"
    }
    ghcn_dk_metadata = {
        sid: meta
        for sid, meta in ghcn_all_stations.items()
        if meta.country_code == "DA"
    }

    ghcn_stations = {
        sid: meta
        for sid, meta in ghcn_all_stations.items()
        if meta.country_code not in {"AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ"}
    }
    log(
        f"GHCN-Metadaten Rest-Europa nach Ausschluss DE/FR/ES/AT/PL/NL/NO/DK/SE/BE/CH: "
        f"{len(ghcn_stations):,}"
    )
    if not ghcn_stations:
        raise RuntimeError("Keine GHCN-Stationen für Rest-Europa gefunden.")

    dwd_text = core.decode_text_smart(core.read_url_bytes(core.DWD_STATIONS_URL))
    dwd_stations = core.parse_dwd_stations(dwd_text)
    if not dwd_stations:
        raise RuntimeError("Keine DWD-KL-Stationsmetadaten gefunden.")

    ghcn_cache = cache_dir / f"ghcn_europe_baseline_through_{cutoff_year}_v{core.GHCN_BASELINE_FORMAT_VERSION}.pkl.gz"
    dwd_cache = cache_dir / f"dwd_germany_kl_baseline_through_{cutoff_year}_v{core.DWD_BASELINE_FORMAT_VERSION}.pkl.gz"
    mf_cache = cache_dir / f"meteofrance_daily_baseline_through_{cutoff_year}_v{core.MF_BASELINE_FORMAT_VERSION}.pkl.gz"

    force_all = args.force_baseline
    ghcn_baseline = core.load_or_build_ghcn_baseline(ghcn_cache, ghcn_stations, cutoff_year, force_all)
    dwd_baseline = core.load_or_build_dwd_baseline(
        dwd_cache, dwd_stations, cutoff_year, force_all or args.force_dwd_baseline, args.dwd_workers
    )
    mf_baseline = core.load_or_build_mf_baseline(
        mf_cache, cutoff_year, force_all or args.force_mf_baseline, args.mf_workers
    )
    austria_baseline = austria.load_or_build_baseline(
        cache_dir, cutoff_year, force=force_all or args.force_austria_baseline
    )
    poland_baseline = _load_or_build_poland(
        cache_dir,
        current_year,
        force=force_all or args.force_poland_baseline,
        workers=args.poland_workers,
    )

    (
        aemet_base,
        aemet_cur_payload,
        knmi_base,
        knmi_cur_payload,
        frost_base,
        frost_cur_payload,
        dmi_base,
        dmi_cur_payload,
        smhi_base,
        smhi_cur_payload,
        belgium_base,
        belgium_cur_payload,
        swiss_base,
        swiss_cur_payload,
    ) = _load_compact_national_sources(
        cache_dir,
        current_year,
        force_aemet=force_all or args.force_aemet_baseline,
        force_knmi=force_all or args.force_knmi_baseline,
        force_frost=force_all or args.force_frost_baseline,
        force_dmi=force_all or args.force_dmi_baseline,
        force_smhi=force_all or args.force_smhi_baseline,
        force_belgium=force_all or args.force_belgium_baseline,
        force_swiss=force_all or args.force_swiss_baseline,
    )

    ghcn_current = core.parse_current_ghcn_year(current_year, ghcn_stations)
    dwd_current = core.parse_current_dwd_year(current_year, dwd_stations, workers=max(4, args.dwd_workers))
    mf_current, mf_current_stations = core.parse_current_mf_year(current_year, workers=max(4, args.mf_workers))
    austria_current = austria.parse_current_year(current_year, austria_baseline.get("stations", {}))
    poland_current, poland_latest_month = poland.parse_current_year(
        current_year, poland_baseline.get("stations", {}), workers=max(4, args.poland_workers)
    )

    aemet_current = compact_records_to_core_current(aemet_cur_payload.get("records", {}), prefix="AEMET")
    knmi_current = compact_records_to_core_current(knmi_cur_payload.get("records", {}), prefix="KNMI")
    frost_current = compact_records_to_core_current(frost_cur_payload.get("records", {}), prefix="FROST")
    dmi_current = compact_records_to_core_current(dmi_cur_payload.get("records", {}), prefix="DMI")
    smhi_current = compact_records_to_core_current(smhi_cur_payload.get("records", {}), prefix="SMHI")
    belgium_current = compact_records_to_core_current(belgium_cur_payload.get("records", {}), prefix="RMI")
    swiss_current = compact_records_to_core_current(swiss_cur_payload.get("records", {}), prefix="METEOSWISS")

    for label, data in (
        ("GeoSphere Austria", austria_current),
        ("IMGW Polen", poland_current),
        ("AEMET Spanien", aemet_current),
        ("KNMI Niederlande", knmi_current),
        ("Frost Norwegen", frost_current),
        ("DMI Dänemark", dmi_current),
        ("SMHI Schweden", smhi_current),
        ("KMI/RMI Belgien", belgium_current),
        ("MeteoSwiss Schweiz", swiss_current),
    ):
        if not data:
            raise RuntimeError(f"{label} lieferte für {current_year} keine aktuellen Stationsdaten.")

    mf_stations = dict(mf_baseline.get("stations", {}))
    mf_stations.update(mf_current_stations)
    if not mf_stations:
        raise RuntimeError("Keine Météo-France-Stationen gefunden.")

    aemet_inventory = dict(aemet_base.get("inventory", {}))
    aemet_inventory.update(aemet_cur_payload.get("inventory", {}))
    knmi_inventory = dict(knmi_base.get("inventory", {}))
    knmi_inventory.update(knmi_cur_payload.get("inventory", {}))
    frost_inventory = dict(frost_base.get("inventory", {}))
    frost_inventory.update(frost_cur_payload.get("inventory", {}))
    dmi_inventory = dict(dmi_base.get("inventory", {}))
    dmi_inventory.update(dmi_cur_payload.get("inventory", {}))
    smhi_inventory = dict(smhi_base.get("inventory", {}))
    smhi_inventory.update(smhi_cur_payload.get("inventory", {}))
    belgium_inventory = dict(belgium_base.get("inventory", {}))
    belgium_inventory.update(belgium_cur_payload.get("inventory", {}))
    swiss_inventory = dict(swiss_base.get("inventory", {}))
    swiss_inventory.update(swiss_cur_payload.get("inventory", {}))

    aemet_stations = aemet_inventory_to_meta(aemet_inventory)

    knmi_record_ids = set(str(x) for x in knmi_base.get("records", {}))
    knmi_record_ids.update(str(x) for x in knmi_cur_payload.get("records", {}))
    knmi_stations = knmi_inventory_to_meta(
        knmi_inventory,
        record_ids=knmi_record_ids,
        ghcn_nl_stations=ghcn_nl_metadata,
    )
    log(
        f"KNMI Metadaten: {len(knmi_stations)} von {len(knmi_record_ids)} "
        "Stationsreihen kartierbar (KNMI-Metadaten bzw. WMO/GHCN-Fallback)."
    )

    frost_stations = frost_inventory_to_meta(frost_inventory)

    dmi_record_ids = set(str(x) for x in dmi_base.get("records", {}))
    dmi_record_ids.update(str(x) for x in dmi_cur_payload.get("records", {}))
    dmi_stations = dmi_inventory_to_meta(
        dmi_inventory,
        record_ids=dmi_record_ids,
        ghcn_dk_stations=ghcn_dk_metadata,
    )
    log(
        f"DMI Metadaten: {len(dmi_stations)} von {len(dmi_record_ids)} "
        "Stationsreihen kartierbar (DMI-Metadaten bzw. WMO/GHCN-Metadatenfallback)."
    )

    smhi_stations = smhi_inventory_to_meta(smhi_inventory)
    belgium_stations = belgium_inventory_to_meta(belgium_inventory)
    swiss_stations = swiss_inventory_to_meta(swiss_inventory)

    # Older MeteoSwiss v1 cache files may contain station names/elevation but
    # no parsed WGS84 coordinates because the live metadata fields are named
    # station_coordinates_wgs84_lat/lon. Refresh metadata live without
    # rebuilding the expensive historical temperature baseline.
    swiss_record_ids = set(str(x) for x in swiss_base.get("records", {}))
    swiss_record_ids.update(str(x) for x in swiss_cur_payload.get("records", {}))
    if not swiss_stations or not any(
        f"METEOSWISS:{raw_id}" in swiss_stations for raw_id in swiss_record_ids
    ):
        fresh_swiss_inventory = swiss_hist.load_station_metadata()
        swiss_inventory.update(fresh_swiss_inventory)
        swiss_stations = swiss_inventory_to_meta(swiss_inventory)
        log(
            f"MeteoSwiss Metadaten live repariert: {len(swiss_stations)} "
            f"kartierbare Stationen für {len(swiss_record_ids)} Stationsreihen."
        )
    else:
        log(
            f"MeteoSwiss Metadaten: {len(swiss_stations)} kartierbare "
            f"Stationen für {len(swiss_record_ids)} Stationsreihen."
        )

    if not aemet_stations or not knmi_stations or not frost_stations or not dmi_stations or not smhi_stations or not belgium_stations or not swiss_stations:
        raise RuntimeError(
            "Nationale Metadaten unvollständig: "
            f"AEMET={len(aemet_stations)}, KNMI={len(knmi_stations)}, "
            f"Frost={len(frost_stations)}, DMI={len(dmi_stations)}, "
            f"SMHI={len(smhi_stations)}, Belgien={len(belgium_stations)}, "
            f"MeteoSwiss={len(swiss_stations)}"
        )

    stations = dict(ghcn_stations)
    stations.update(dwd_stations)
    stations.update(mf_stations)
    stations.update(austria_baseline.get("stations", {}))
    stations.update(poland_baseline.get("stations", {}))
    stations.update(aemet_stations)
    stations.update(knmi_stations)
    stations.update(frost_stations)
    stations.update(dmi_stations)
    stations.update(smhi_stations)
    stations.update(belgium_stations)
    stations.update(swiss_stations)

    states = {sid: state for sid, state in ghcn_baseline.get("states", {}).items() if sid in ghcn_stations}
    states.update(dwd_baseline.get("states", {}))
    states.update(mf_baseline.get("states", {}))
    states.update(austria_baseline.get("states", {}))
    states.update(poland_baseline.get("states", {}))
    states.update(compact_records_to_core_states(aemet_base.get("records", {}), prefix="AEMET"))
    states.update(compact_records_to_core_states(knmi_base.get("records", {}), prefix="KNMI"))
    states.update(compact_records_to_core_states(frost_base.get("records", {}), prefix="FROST"))
    states.update(compact_records_to_core_states(dmi_base.get("records", {}), prefix="DMI"))
    states.update(compact_records_to_core_states(smhi_base.get("records", {}), prefix="SMHI"))
    states.update(compact_records_to_core_states(belgium_base.get("records", {}), prefix="RMI"))
    states.update(compact_records_to_core_states(swiss_base.get("records", {}), prefix="METEOSWISS"))

    current = dict(ghcn_current)
    current.update(dwd_current)
    current.update(mf_current)
    current.update(austria_current)
    current.update(poland_current)
    current.update(aemet_current)
    current.update(knmi_current)
    current.update(frost_current)
    current.update(dmi_current)
    current.update(smhi_current)
    current.update(belgium_current)
    current.update(swiss_current)

    if output_dir.exists():
        import shutil
        shutil.rmtree(output_dir)

    core.merge_and_write(output_dir, stations, states, current, current_year)
    payload = patch_index_metadata(
        output_dir,
        current_year=current_year,
        stations=stations,
        states=states,
        current=current,
        austria_current_count=len(austria_current),
        poland_current_count=len(poland_current),
        poland_latest_month=poland_latest_month,
        aemet_current_count=len(aemet_current),
        knmi_current_count=len(knmi_current),
        frost_current_count=len(frost_current),
        dmi_current_count=len(dmi_current),
        smhi_current_count=len(smhi_current),
        belgium_current_count=len(belgium_current),
        swiss_current_count=len(swiss_current),
    )
    validate_payload(payload)

    month_text = f"{poland_latest_month:02d}" if poland_latest_month is not None else "–"
    log(
        f"EUROPA AUTOMATIK OK: {payload.get('station_count', 0):,} Stationen in "
        f"{payload.get('country_count', 0)} Ländern | aktiv {payload.get('active_station_count', 0):,} | "
        f"Polen aktuell bis Monat {month_text}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
