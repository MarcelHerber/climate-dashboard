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
- Finland: FMI Open Data (daily multipointcoverage)
- Czechia: CHMI Open Data (daily TMA/TMI)
- Hungary: HungaroMet Open Data (original controlled long series + HABP_1D)
- Ireland: Met Éireann Climate Data Online (daily maxtp/mintp)
- Estonia: Estonian Environment Agency climate API (daily DTAX/DTAN)
- Slovenia: ARSO Agromet official daily Tmin/Tmax month tables (73 map-ready IDs)
- remaining Europe: GHCN-Daily

The core Stations-V5 writer remains unchanged. Dedicated compact national
caches are adapted into the core StationMeta/state/current contracts before
writing ``europe_stations/index.json`` and the 366 calendar packs.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import update_europe_station_records as core
import dwd_daily_map as dwd_daily_map
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
import update_fmi_finland_station_cache as fmi_hist
import update_fmi_finland_current as fmi_current_mod
import update_chmi_czechia_station_cache as chmi_hist
import update_chmi_czechia_current as chmi_current_mod
import update_hungaromet_hungary_station_cache as hungary_hist
import update_hungaromet_hungary_current as hungary_current_mod
import update_met_eireann_ireland_station_cache as ireland_hist
import update_met_eireann_ireland_current as ireland_current_mod
import update_ilmateenistus_estonia_station_cache as estonia_hist
import update_ilmateenistus_estonia_current as estonia_current_mod
import update_arso_slovenia_station_cache as slovenia_hist
import update_arso_slovenia_current as slovenia_current_mod
import update_arso_slovenia_station_metadata as slovenia_meta


ACTIVE_GRACE_DAYS = 45
SLOVENIA_IGNORED_IDS = {"346"}
SLOVENIA_EXPECTED_MAP_READY = 73
NATIONAL_GHCN_CODES = {"GM", "FR", "SP", "ES", "AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN", "SI"}
OPPOSITE_EXTREMES_CACHE_VERSION = 1

# The legacy Stations-V5 core only persists the conventional record direction
# (highest TMAX / lowest TMIN). Keep its payload version unchanged and extend it
# at runtime with the opposite absolute station extremes. This makes the change
# backward-compatible with the existing frontend while the next frontend step
# can opt into the two new JSON fields.
def _opposite_better(element: str, new_value: int, old_value: int | None) -> bool:
    if old_value is None:
        return True
    return new_value < old_value if element == "TMAX" else new_value > old_value


def _update_opposite_record(record, value: int, date_int: int, element: str):
    if record is None or _opposite_better(element, value, record[0]):
        return (value, date_int, 1)
    if value == record[0]:
        return (record[0], min(int(record[1]), int(date_int)), int(record[2]) + 1)
    return record


def _merge_opposite_records(a, b, element: str):
    if a is None:
        return b
    if b is None:
        return a
    if _opposite_better(element, b[0], a[0]):
        return b
    if _opposite_better(element, a[0], b[0]):
        return a
    return (a[0], min(int(a[1]), int(b[1])), int(a[2]) + int(b[2]))


# GeoSphere/IMGW historical cache modules use this injected helper while still
# sharing all other state/merge machinery with the unchanged core module.
core.update_opposite_record = _update_opposite_record

_CORE_PARSE_DLY_STATION = core.parse_dly_station
_CORE_PARSE_DWD_PRODUCT_BYTES = core.parse_dwd_product_bytes
_CORE_PARSE_MF_STREAM = core.parse_mf_stream
_CORE_MERGE_MF_PARTIAL = core.merge_mf_partial
_CORE_FINALIZE_MF_STATES = core.finalize_mf_states


def _parse_dly_station_with_opposite(stream, cutoff_year: int) -> dict:
    raw_data = stream.read()
    if isinstance(raw_data, str):
        raw_data = raw_data.encode("ascii", errors="ignore")
    state = _CORE_PARSE_DLY_STATION(io.BytesIO(raw_data), cutoff_year)
    for raw in raw_data.splitlines():
        line = raw.decode("ascii", errors="ignore") if isinstance(raw, bytes) else str(raw)
        if len(line) < 21:
            continue
        try:
            year = int(line[11:15]); month = int(line[15:17])
        except ValueError:
            continue
        if year > cutoff_year:
            continue
        element = line[17:21]
        if element not in ("TMAX", "TMIN"):
            continue
        try:
            max_day = calendar.monthrange(year, month)[1]
        except (ValueError, calendar.IllegalMonthError):
            continue
        for day in range(1, max_day + 1):
            pos = 21 + (day - 1) * 8
            if pos + 8 > len(line):
                break
            try:
                value = int(line[pos:pos + 5])
            except ValueError:
                continue
            if value == -9999 or line[pos + 6:pos + 7].strip():
                continue
            try:
                date_obj = dt.date(year, month, day)
            except ValueError:
                continue
            date_int = int(date_obj.strftime("%Y%m%d"))
            block = state[element]
            block["opposite_abs"] = _update_opposite_record(
                block.get("opposite_abs"), value, date_int, element
            )
    return state


def _parse_dwd_product_bytes_with_opposite(data: bytes, cutoff_year=None, exact_year=None) -> dict:
    state = _CORE_PARSE_DWD_PRODUCT_BYTES(data, cutoff_year=cutoff_year, exact_year=exact_year)
    if exact_year is not None:
        return state
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        candidates = [name for name in zf.namelist() if re.search(r"produkt_klima_tag_.*\.txt$", name, re.I)]
        if not candidates:
            candidates = [name for name in zf.namelist() if name.lower().endswith(".txt") and "produkt" in name.lower()]
        for member in candidates:
            with zf.open(member) as raw:
                text = io.TextIOWrapper(raw, encoding="latin-1", errors="replace", newline="")
                reader = csv.DictReader(text, delimiter=";")
                if not reader.fieldnames:
                    continue
                fmap = {str(k).strip(): k for k in reader.fieldnames if k is not None}
                date_key, tx_key, tn_key = fmap.get("MESS_DATUM"), fmap.get("TXK"), fmap.get("TNK")
                if not date_key:
                    continue
                for row in reader:
                    datestr = str(row.get(date_key, "")).strip()
                    if not re.fullmatch(r"\d{8}", datestr):
                        continue
                    year = int(datestr[:4])
                    if cutoff_year is not None and year > cutoff_year:
                        continue
                    date_int = int(datestr)
                    mmdd = f"{datestr[4:6]}-{datestr[6:8]}"
                    for element, key in (("TMAX", tx_key), ("TMIN", tn_key)):
                        if not key:
                            continue
                        value = core.dwd_float_to_tenths(row.get(key, ""))
                        if value is None:
                            continue
                        block = state[element]
                        block["opposite_abs"] = _update_opposite_record(
                            block.get("opposite_abs"), value, date_int, element
                        )
                        if dwd_daily_map.REFERENCE_START <= year <= dwd_daily_map.REFERENCE_END:
                            dwd_daily_map.add_climatology_value(block, mmdd, value)
    return state


def _parse_mf_stream_with_opposite(fileobj, *, cutoff_year=None, exact_year=None):
    raw_data = fileobj.read()
    partial, current, metas = _CORE_PARSE_MF_STREAM(
        io.BytesIO(raw_data), cutoff_year=cutoff_year, exact_year=exact_year
    )
    if exact_year is not None:
        return partial, current, metas
    with gzip.GzipFile(fileobj=io.BytesIO(raw_data)) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.DictReader(text, delimiter=";")
        if not reader.fieldnames:
            return partial, current, metas
        fmap = {str(k).strip().upper(): k for k in reader.fieldnames if k is not None}
        if "NUM_POSTE" not in fmap or "AAAAMMJJ" not in fmap:
            return partial, current, metas
        for row in reader:
            sid = core.mf_station_id(row.get(fmap["NUM_POSTE"], ""))
            datestr = str(row.get(fmap["AAAAMMJJ"], "")).strip().replace(".0", "")
            if not sid or not re.fullmatch(r"\d{8}", datestr):
                continue
            year = int(datestr[:4])
            if cutoff_year is not None and year > cutoff_year:
                continue
            lat = core.mf_float(row.get(fmap.get("LAT", ""), "")) if "LAT" in fmap else None
            lon = core.mf_float(row.get(fmap.get("LON", ""), "")) if "LON" in fmap else None
            if lat is None or lon is None or not (core.LAT_MIN <= lat <= core.LAT_MAX and core.LON_MIN <= lon <= core.LON_MAX):
                continue
            date_int = int(datestr)
            for element, value_col, quality_col in (("TMAX", "TX", "QTX"), ("TMIN", "TN", "QTN")):
                if value_col not in fmap:
                    continue
                value = core.mf_temp_to_tenths(row.get(fmap[value_col], ""))
                qraw = row.get(fmap[quality_col], "") if quality_col in fmap else ""
                if value is None or not core.mf_quality_ok(qraw):
                    continue
                state = partial.setdefault(sid, core.mf_empty_partial_state())
                block = state[element]
                block["opposite_abs"] = _update_opposite_record(
                    block.get("opposite_abs"), value, date_int, element
                )
    return partial, current, metas


def _merge_mf_partial_with_opposite(target: dict, incoming: dict) -> None:
    _CORE_MERGE_MF_PARTIAL(target, incoming)
    for sid, src_state in incoming.items():
        dst_state = target.setdefault(sid, core.mf_empty_partial_state())
        for element in ("TMAX", "TMIN"):
            src = src_state.get(element, {})
            dst = dst_state.setdefault(element, {})
            dst["opposite_abs"] = _merge_opposite_records(
                dst.get("opposite_abs"), src.get("opposite_abs"), element
            )


def _finalize_mf_states_with_opposite(partial: dict) -> dict:
    out = _CORE_FINALIZE_MF_STATES(partial)
    for sid, src_state in partial.items():
        if sid not in out:
            continue
        for element in ("TMAX", "TMIN"):
            out[sid][element]["opposite_abs"] = src_state.get(element, {}).get("opposite_abs")
    return out


core.parse_dly_station = _parse_dly_station_with_opposite
core.parse_dwd_product_bytes = _parse_dwd_product_bytes_with_opposite
core.parse_mf_stream = _parse_mf_stream_with_opposite
core.merge_mf_partial = _merge_mf_partial_with_opposite
core.finalize_mf_states = _finalize_mf_states_with_opposite

# Force one clean Météo-France per-resource rebuild because the old cached
# partial states do not contain the new opposite absolute extremes.
_BASE_MF_RESOURCE_CACHE_FORMAT_VERSION = int(getattr(core, "MF_RESOURCE_CACHE_FORMAT_VERSION", 1))
core.MF_RESOURCE_CACHE_FORMAT_VERSION = (
    _BASE_MF_RESOURCE_CACHE_FORMAT_VERSION + 100 * OPPOSITE_EXTREMES_CACHE_VERSION
)


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

        for element, abs_key, opposite_key, cal_key in (
            ("TMAX", "tmax_abs", "tmax_low_abs", "calendar_tmax"),
            ("TMIN", "tmin_abs", "tmin_high_abs", "calendar_tmin"),
        ):
            block = state[element]
            block["abs"] = _compact_record_triplet(record.get(abs_key))
            block["opposite_abs"] = _compact_record_triplet(record.get(opposite_key))
            cal: dict[str, tuple[int, int, int]] = {}
            raw_cal = record.get(cal_key, {})
            if isinstance(raw_cal, dict):
                for mmdd, value_date in raw_cal.items():
                    converted = _compact_record_triplet(value_date)
                    if converted is not None:
                        cal[str(mmdd)] = converted
            block["cal"] = cal
            has_values = block["abs"] is not None or block.get("opposite_abs") is not None or bool(cal)
            block["start"] = start if has_values else None
            block["end"] = end if has_values else None
            # The compact national caches store first/last observation and
            # observation-day count, but not a distinct-year set. The inclusive
            # observation span is therefore used for the frontend length filter.
            block["years"] = years if has_values else 0
        if (state["TMAX"]["abs"] is not None or state["TMIN"]["abs"] is not None or
                state["TMAX"].get("opposite_abs") is not None or state["TMIN"].get("opposite_abs") is not None):
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



def fmi_inventory_to_meta(inventory: dict[str, dict[str, Any]]) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    for raw_id, meta in inventory.items():
        if not isinstance(meta, dict):
            continue
        sid = f"FMI:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat", "latitude"),
            lon_keys=("lon", "longitude"),
            elev_keys=("elevation_m", "elevation", "height"),
            name_keys=("name",),
            country_code="FI",
            country="Finnland",
            source=fmi_hist.SOURCE,
            quality_rule=(
                "FMI Open Data daily multipointcoverage: tägliches tmin/tmax; "
                "historische Plausibilitätsprüfung gegen offizielle finnische "
                "Messrekorde, laufendes Jahr mit weiter Notfall-QC; Tmin>Tmax verworfen."
            ),
        )
        if station is not None:
            out[sid] = station
    return out


def estonia_inventory_to_meta(inventory: dict[str, dict[str, Any]]) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    for raw_id, meta in inventory.items():
        if not isinstance(meta, dict):
            continue
        sid = f"ILMATEENISTUS:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat", "latitude"),
            lon_keys=("lon", "longitude"),
            elev_keys=("elevation_m", "elevation", "height"),
            name_keys=("name",),
            country_code="EN",
            country="Estland",
            source=estonia_hist.SOURCE,
            quality_rule=(
                "Estonian Environment Agency climate API: tägliche DTAX=Tmax und "
                "DTAN=Tmin für das verifizierte aktive 25-Stationen-Netz. "
                "Nichtnumerische Werte werden verworfen; Tmin>Tmax wird abgelehnt."
            ),
        )
        if station is not None:
            out[sid] = station
    return out


def hungary_inventory_to_meta(
    inventory: dict[str, dict[str, Any]],
    *,
    record_ids: set[str] | None = None,
) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    raw_ids = set(str(x) for x in inventory)
    if record_ids is not None:
        raw_ids &= set(str(x) for x in record_ids)
    for raw_id in sorted(raw_ids):
        meta = inventory.get(raw_id)
        if not isinstance(meta, dict):
            continue
        sid = f"HUNGAROMET:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat", "latitude"),
            lon_keys=("lon", "longitude"),
            elev_keys=("elevation_m", "elevation", "height"),
            name_keys=("name",),
            country_code="HU",
            country="Ungarn",
            source=hungary_hist.SOURCE,
            quality_rule=(
                "HungaroMet: kontrollierte, nicht homogenisierte Original-Langreihen ab 1901 "
                "plus HABP_1D Tagesbeobachtungen (tn/tx). -999/fehlende und unplausible Werte "
                "sowie Tmin>Tmax werden verworfen; Q_tn/Q_tx sind derzeit reservierte Felder."
            ),
        )
        if station is not None:
            out[sid] = station
    return out


def ireland_inventory_to_meta(
    inventory: dict[str, dict[str, Any]],
    *,
    record_ids: set[str],
) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    for raw_id in sorted(set(str(x) for x in record_ids), key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x)):
        meta = inventory.get(raw_id)
        if not isinstance(meta, dict):
            continue
        sid = f"METEIREANN:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat", "latitude"),
            lon_keys=("lon", "longitude"),
            elev_keys=("elevation_m", "elevation", "height"),
            name_keys=("name",),
            country_code="EI",
            country="Irland",
            source=ireland_hist.SOURCE,
            quality_rule=(
                "Met Éireann Climate Data Online: tägliche Lufttemperatur maxtp=TMAX und "
                "mintp=TMIN; gmin/igmin (Grasminimum) werden bewusst ignoriert. "
                "Fehlende/nichtnumerische Werte sowie grob unplausible Werte und Tmin>Tmax "
                "werden verworfen; Nordirland ist ausgeschlossen."
            ),
        )
        if station is not None:
            out[sid] = station
    return out



def _slovenia_filter_records(records: dict[str, Any]) -> dict[str, Any]:
    return {
        str(raw_id): record
        for raw_id, record in records.items()
        if str(raw_id) not in SLOVENIA_IGNORED_IDS
    }


def _load_slovenia_map_metadata() -> dict[str, dict[str, Any]]:
    # Resolve exactly the 73 accepted ARSO coordinates.
    # NOAA/GHCN is deliberately not called here: ID 346 is now an intentional
    # exclusion rather than a matching problem to solve.
    inventory, _ = slovenia_hist.load_inventory()
    current_meta, historical_meta = slovenia_meta.load_agromet_metadata()
    gis_rows = slovenia_meta.load_gis_rows()

    result = slovenia_meta.build_metadata(
        inventory,
        current_meta,
        historical_meta,
        gis_rows,
        [],
    )
    metadata = result.get("metadata", {})
    if not isinstance(metadata, dict):
        raise RuntimeError("ARSO-Metadatenresultat ist kein Dictionary.")

    inventory_ids = set(str(x) for x in inventory)
    expected_ids = inventory_ids - SLOVENIA_IGNORED_IDS
    actual_ids = set(str(x) for x in metadata)

    if len(inventory) != 74:
        raise RuntimeError(f"ARSO-Inventar hat {len(inventory)} statt 74 IDs.")
    if not SLOVENIA_IGNORED_IDS.issubset(inventory_ids):
        raise RuntimeError("ARSO-ID 346 fehlt unerwartet im Quellinventar.")
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise RuntimeError(
            "ARSO-Metadaten sind nicht exakt die 73 freigegebenen IDs: "
            f"missing={missing}, extra={extra}"
        )
    if len(metadata) != SLOVENIA_EXPECTED_MAP_READY:
        raise RuntimeError(
            f"ARSO: {len(metadata)} statt 73 kartierbare Stationen."
        )
    if "346" in metadata:
        raise RuntimeError("ARSO 346 darf nicht veröffentlicht werden.")

    return metadata


def slovenia_metadata_to_meta(
    metadata: dict[str, dict[str, Any]],
) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}

    for raw_id, meta in metadata.items():
        raw_id = str(raw_id)
        if raw_id in SLOVENIA_IGNORED_IDS or not isinstance(meta, dict):
            continue

        sid = f"ARSO:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat",),
            lon_keys=("lon",),
            elev_keys=("elevation_m",),
            name_keys=("name", "metadata_name"),
            country_code="SI",
            country="Slowenien",
            source=slovenia_hist.SOURCE,
            quality_rule=(
                "ARSO Slowenien: offizielle Agromet-Tageswerte Tmin/Tmax aus "
                "monatlichen TXT-Tabellen; grobe Plausibilitäts-QC, Tmin>Tmax "
                "wird verworfen. Von 74 Quell-IDs werden exakt 73 kartiert; "
                "ID 346 Turški Vrh ist wegen fehlender verifizierter Koordinate "
                "bewusst ausgeschlossen."
            ),
        )
        if station is not None:
            out[sid] = station

    if len(out) != SLOVENIA_EXPECTED_MAP_READY:
        raise RuntimeError(f"ARSO StationMeta: {len(out)} statt 73 Stationen.")
    if "ARSO:346" in out:
        raise RuntimeError("ARSO:346 wurde trotz Ausschluss erzeugt.")

    return out


def chmi_payload_inventory(base_payload: dict, current_payload: dict | None = None) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for payload in (base_payload, current_payload or {}):
        for raw_id, record in payload.get("stations", {}).items():
            if not isinstance(record, dict):
                continue
            meta = record.get("meta", {})
            if not isinstance(meta, dict):
                continue
            old = inventory.setdefault(str(raw_id), {})
            for key, value in meta.items():
                if value not in (None, ""):
                    old[key] = value
    return inventory


def chmi_inventory_to_meta(inventory: dict[str, dict[str, Any]]) -> dict[str, core.StationMeta]:
    out: dict[str, core.StationMeta] = {}
    for raw_id, meta in inventory.items():
        if not isinstance(meta, dict):
            continue
        sid = f"CHMI:{raw_id}"
        station = _make_station_meta(
            sid=sid,
            raw_meta=meta,
            lat_keys=("lat", "latitude"),
            lon_keys=("lon", "longitude"),
            elev_keys=("elevation", "elevation_m", "height"),
            name_keys=("name",),
            country_code="CZ",
            country="Tschechien",
            source=chmi_hist.SOURCE,
            quality_rule=(
                "CHMI Open Data tägliche TMA/TMI-Werte; ausschließlich QUALITY=0 (Good). "
                "Nichtnumerische Werte und unplausible Temperatur-/Tmin>Tmax-Fälle werden verworfen."
            ),
        )
        if station is not None:
            out[sid] = station
    return out


def chmi_packed_to_core_states(stations_payload: dict[str, dict[str, Any]]) -> dict[str, dict]:
    states: dict[str, dict] = {}
    missing = int(getattr(chmi_hist, "MISSING_I16", -32768))

    for raw_id, record in stations_payload.items():
        if not isinstance(record, dict):
            continue
        sid = f"CHMI:{raw_id}"
        state = core.empty_state()
        years = {"TMAX": set(), "TMIN": set()}

        ordinals = record.get("ordinals", [])
        tmax_values = record.get("tmax_tenths", [])
        tmin_values = record.get("tmin_tenths", [])

        for ordv, tx_raw, tn_raw in zip(ordinals, tmax_values, tmin_values):
            try:
                day = dt.date.fromordinal(int(ordv))
            except (TypeError, ValueError, OverflowError):
                continue
            date_int = int(day.strftime("%Y%m%d"))
            mmdd = f"{day.month:02d}-{day.day:02d}"

            for element, raw_value, choose_max in (
                ("TMAX", tx_raw, True),
                ("TMIN", tn_raw, False),
            ):
                try:
                    value = int(raw_value)
                except (TypeError, ValueError):
                    continue
                if value == missing:
                    continue

                block = state[element]
                rec = (value, date_int, 1)
                old_abs = block.get("abs")
                if old_abs is None or (value > old_abs[0] if choose_max else value < old_abs[0]):
                    block["abs"] = rec
                block["opposite_abs"] = _update_opposite_record(
                    block.get("opposite_abs"), value, date_int, element
                )

                old_cal = block["cal"].get(mmdd)
                if old_cal is None or (value > old_cal[0] if choose_max else value < old_cal[0]):
                    block["cal"][mmdd] = rec

                if block.get("start") is None:
                    block["start"] = date_int
                block["end"] = date_int
                years[element].add(day.year)

        for element in ("TMAX", "TMIN"):
            state[element]["years"] = len(years[element])

        if state["TMAX"]["abs"] is not None or state["TMIN"]["abs"] is not None:
            states[sid] = state

    return states


def chmi_packed_to_core_current(stations_payload: dict[str, dict[str, Any]]) -> dict[str, dict]:
    current: dict[str, dict] = {}
    missing = int(getattr(chmi_hist, "MISSING_I16", -32768))

    for raw_id, record in stations_payload.items():
        if not isinstance(record, dict):
            continue
        sid = f"CHMI:{raw_id}"
        out = {"TMAX": {}, "TMIN": {}}

        for ordv, tx_raw, tn_raw in zip(
            record.get("ordinals", []),
            record.get("tmax_tenths", []),
            record.get("tmin_tenths", []),
        ):
            try:
                day = dt.date.fromordinal(int(ordv))
            except (TypeError, ValueError, OverflowError):
                continue
            date_int = int(day.strftime("%Y%m%d"))
            mmdd = f"{day.month:02d}-{day.day:02d}"

            for element, raw_value, choose_max in (
                ("TMAX", tx_raw, True),
                ("TMIN", tn_raw, False),
            ):
                try:
                    value = int(raw_value)
                except (TypeError, ValueError):
                    continue
                if value == missing:
                    continue
                old = out[element].get(mmdd)
                pair = (value, date_int)
                if old is None or (value > old[0] if choose_max else value < old[0]):
                    out[element][mmdd] = pair

        if out["TMAX"] or out["TMIN"]:
            current[sid] = out
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



def _load_or_build_slovenia_baseline(
    cache_dir: Path,
    current_year: int,
    force: bool,
) -> dict:
    cutoff_year = current_year - 1
    path = slovenia_hist.baseline_path(cache_dir, cutoff_year)

    if force or not slovenia_hist.valid_baseline(path, cutoff_year):
        script = Path(__file__).with_name(
            "update_arso_slovenia_station_cache.py"
        )
        cmd = [
            sys.executable,
            str(script),
            "--cutoff-year",
            str(cutoff_year),
            "--workers",
            "12",
            "--batch-size",
            "600",
            "--max-runtime-minutes",
            "300",
        ]
        if force:
            cmd.append("--force")

        log(
            "Baue/aktualisiere ARSO-Slowenien-Baseline bis "
            f"{cutoff_year} ..."
        )
        subprocess.run(cmd, check=True)

    if not slovenia_hist.valid_baseline(path, cutoff_year):
        raise RuntimeError(f"ARSO-Slowenien-Baseline unvollständig: {path}")

    payload = slovenia_hist.load_pickle_gz(path)
    if not isinstance(payload, dict) or payload.get("complete") is not True:
        raise RuntimeError(f"ARSO-Slowenien-Baseline ungültig: {path}")

    log(f"Verwende ARSO-Slowenien-Baseline: {path}")
    return payload


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
    force_fmi: bool,
    force_estonia: bool,
    force_slovenia: bool,
    force_chmi: bool,
    force_hungary: bool,
    force_ireland: bool,
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

    fmi_hist.build_baseline(
        cache_dir,
        cutoff_year,
        force=force_fmi,
        max_runtime_minutes=300.0,
    )
    fmi_base = fmi_hist.load_baseline(cache_dir, cutoff_year)

    estonia_hist.build_baseline(
        cache_dir,
        cutoff_year,
        force=force_estonia,
        max_runtime_minutes=155.0,
    )
    estonia_base_path = estonia_hist.baseline_path(cache_dir, cutoff_year)
    if not estonia_hist.valid_final(estonia_base_path, cutoff_year):
        raise RuntimeError(f"Estland-Baseline unvollständig: {estonia_base_path}")
    estonia_base = estonia_hist.load_pickle_gzip(estonia_base_path)

    slovenia_base = _load_or_build_slovenia_baseline(
        cache_dir,
        current_year,
        force=force_slovenia,
    )

    chmi_hist.build_baseline(
        cache_dir,
        cutoff_year,
        force=force_chmi,
        workers=8,
    )
    chmi_base = chmi_hist.load_baseline(cache_dir, cutoff_year)

    hungary_hist.build_baseline(
        cache_dir,
        cutoff_year,
        force=force_hungary,
        workers=12,
        max_runtime_minutes=150.0,
    )
    hungary_base = hungary_hist.load_baseline(cache_dir, cutoff_year)

    ireland_hist.build_baseline(
        cache_dir,
        cutoff_year,
        force=force_ireland,
        workers=8,
        batch_size=100,
        max_runtime_minutes=150.0,
    )
    ireland_base_path = ireland_hist.baseline_path(cache_dir, cutoff_year)
    if not ireland_hist.valid_final(ireland_base_path, cutoff_year):
        raise RuntimeError(f"Met-Éireann-Irland-Baseline unvollständig: {ireland_base_path}")
    ireland_base = ireland_hist.load_pickle_gzip(ireland_base_path)

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

    fmi_current_path = fmi_current_mod.build_current(cache_dir, current_year)
    fmi_cur = fmi_hist.load_pickle_gzip(fmi_current_path)

    estonia_current_path = estonia_current_mod.build_current(cache_dir, current_year)
    estonia_cur = estonia_hist.load_pickle_gzip(estonia_current_path)
    if not isinstance(estonia_cur, dict) or estonia_cur.get("complete") is not True:
        raise RuntimeError(f"Estland-Current unvollständig: {estonia_current_path}")

    slovenia_current_path = slovenia_current_mod.build_current(
        cache_dir,
        current_year,
        workers=12,
    )
    slovenia_cur = slovenia_hist.load_pickle_gz(slovenia_current_path)
    if not isinstance(slovenia_cur, dict) or slovenia_cur.get("complete") is not True:
        raise RuntimeError(f"ARSO-Slowenien-Current unvollständig: {slovenia_current_path}")

    chmi_current_path = chmi_current_mod.build_current(cache_dir, current_year, workers=12)
    chmi_cur = chmi_current_mod.load_current(cache_dir, current_year)

    hungary_current_path = hungary_current_mod.build_current(cache_dir, current_year, workers=14)
    hungary_cur = hungary_current_mod.load_current(cache_dir, current_year)

    ireland_current_path = ireland_current_mod.build_current(cache_dir, current_year, workers=12)
    ireland_cur = ireland_hist.load_pickle_gzip(ireland_current_path)
    if not isinstance(ireland_cur, dict) or ireland_cur.get("complete") is not True:
        raise RuntimeError(f"Met-Éireann-Irland-Current unvollständig: {ireland_current_path}")

    return (
        aemet_base, aemet_cur,
        knmi_base, knmi_cur,
        frost_base, frost_cur,
        dmi_base, dmi_cur,
        smhi_base, smhi_cur,
        belgium_base, belgium_cur,
        swiss_base, swiss_cur,
        fmi_base, fmi_cur,
        estonia_base, estonia_cur,
        slovenia_base, slovenia_cur,
        chmi_base, chmi_cur,
        hungary_base, hungary_cur,
        ireland_base, ireland_cur,
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


def _current_opposite_absolute(current_state: dict[str, Any] | None, element: str):
    record = None
    if not isinstance(current_state, dict):
        return None
    values = current_state.get(element, {})
    if not isinstance(values, dict):
        return None
    for item in values.values():
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            value, date_int = int(item[0]), int(item[1])
        except (TypeError, ValueError):
            continue
        record = _update_opposite_record(record, value, date_int, element)
    return record


def add_opposite_station_extremes(payload: dict, *, states: dict[str, dict], current: dict[str, dict]) -> None:
    """Add lowest TMAX and highest TMIN without changing Stations-V5 fields."""
    missing: list[str] = []
    for row in payload.get("stations", []):
        sid = str(row.get("id") or "")
        historical = states.get(sid, {})
        current_state = current.get(sid, {})
        for element, payload_key, new_key in (
            ("TMAX", "tmax", "lowest_record"),
            ("TMIN", "tmin", "highest_record"),
        ):
            base = historical.get(element, {}).get("opposite_abs") if isinstance(historical, dict) else None
            cur = _current_opposite_absolute(current_state, element)
            final = _merge_opposite_records(base, cur, element)
            target = row.setdefault(payload_key, {})
            target[new_key] = core.record_json(final)
            # A conventional record implies that at least one valid value exists;
            # therefore the opposite extreme must also be derivable after a clean
            # cache rebuild.
            if target.get("record") is not None and target[new_key] is None:
                missing.append(f"{sid}:{element}")
    if missing:
        preview = ", ".join(missing[:12])
        raise RuntimeError(
            f"Gegenextreme fehlen für {len(missing)} Stationsparameter nach dem Neuaufbau: {preview}"
        )
    payload["additional_station_extremes"] = {
        "tmax_lowest": "stations[].tmax.lowest_record",
        "tmin_highest": "stations[].tmin.highest_record",
        "unit": "°C",
        "scope": "Allzeit-Stationsrekord einschließlich laufendem Jahr",
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
    fmi_current_count: int,
    estonia_current_count: int,
    slovenia_current_count: int,
    chmi_current_count: int,
    hungary_current_count: int,
    ireland_current_count: int,
) -> dict:
    path = output_dir / "index.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    add_station_activity(payload, stations=stations, states=states, current=current)
    add_opposite_station_extremes(payload, states=states, current=current)
    counts = _source_counts(payload)

    payload["source"] = (
        "DWD CDC (Deutschland) + Météo-France (Frankreich) + "
        "AEMET OpenData (Spanien) + GeoSphere Austria (Österreich) + "
        "IMGW-PIB (Polen) + KNMI (Niederlande) + MET Norway Frost (Norwegen) + "
        "DMI Open Data (Dänemark) + SMHI Open Data (Schweden) + "
        "KMI/RMI Open Data (Belgien) + MeteoSwiss Open Data (Schweiz) + "
        "FMI Open Data (Finnland) + CHMI Open Data (Tschechien) + "
        "HungaroMet Open Data (Ungarn) + Met Éireann Climate Data Online (Irland) + "
        "Estonian Environment Agency climate API (Estland) + "
        "ARSO Agromet (Slowenien) + GHCN-Daily (übriges Europa)"
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
        {"name": fmi_hist.SOURCE, "scope": "Finnland", "url": fmi_hist.PUBLIC_URL, "stations": counts.get(fmi_hist.SOURCE, 0)},
        {"name": chmi_hist.SOURCE, "scope": "Tschechien", "url": chmi_hist.PUBLIC_URL, "stations": counts.get(chmi_hist.SOURCE, 0)},
        {"name": hungary_hist.SOURCE, "scope": "Ungarn", "url": hungary_hist.PUBLIC_URL, "stations": counts.get(hungary_hist.SOURCE, 0)},
        {"name": ireland_hist.SOURCE, "scope": "Irland", "url": ireland_hist.PUBLIC_URL, "stations": counts.get(ireland_hist.SOURCE, 0)},
        {"name": estonia_hist.SOURCE, "scope": "Estland", "url": estonia_hist.PUBLIC_URL, "stations": counts.get(estonia_hist.SOURCE, 0)},
        {"name": slovenia_hist.SOURCE, "scope": "Slowenien", "url": slovenia_hist.FORM_URL, "stations": counts.get(slovenia_hist.SOURCE, 0)},
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
        "Finnland: FMI Open Data tägliches tmin/tmax aus daily multipointcoverage mit historischer Plausibilitäts-QC und Tmin<=Tmax. "
        "Tschechien: CHMI Open Data tägliche TMA/TMI ausschließlich mit QUALITY=0 (Good). "
        "Ungarn: HungaroMet kontrollierte, nicht homogenisierte Original-Langreihen ab 1901 plus HABP_1D tn/tx; Q_tn/Q_tx sind derzeit reserviert, -999/fehlende und unplausible Werte werden verworfen. "
        "Irland: Met Éireann Climate Data Online maxtp/mintp; gmin/igmin werden ausgeschlossen; Republik Irland ohne Nordirland. "
        "Estland: Estonian Environment Agency climate API DTAX/DTAN; nichtnumerische Werte verworfen, Tmin>Tmax abgelehnt. "
        "Slowenien: ARSO Agromet tägliche Tmin/Tmax-Monatstabellen; grobe Plausibilitäts-QC und Tmin>Tmax verworfen; ID 346 Turški Vrh bewusst ohne Kartenintegration. "
        "Übriges Europa: GHCN-Daily TMAX/TMIN nur mit leerem Q-FLAG."
    )
    payload["history_scope"] = (
        f"Historische Baselines bis {current_year - 1}: DWD Deutschland, Météo-France Frankreich, "
        "AEMET Spanien ab 1920, GeoSphere Austria Österreich, IMGW-PIB Polen, "
        "KNMI Niederlande ab 1901, MET Norway Frost für MET.NO-Stationen, "
        "DMI Dänemark ab 1867 mit dokumentierter Übergangsbrücke, SMHI Schweden, "
        "KMI/RMI Belgien mit historischer Hybridbrücke, MeteoSwiss SwissMetNet Schweiz ab 1864, "
        "FMI Finnland ab 1844, CHMI Tschechien bis zurück 1775 sowie HungaroMet Ungarn "
        "mit 10 kontrollierten Original-Langreihen ab 1901 und HABP_1D Stationsnetz vor allem ab 2002; "
        "Met Éireann Irland mit offiziellen täglichen maxtp/mintp-Reihen bis zurück 1939; "
        "Estonian Environment Agency Estland für das verifizierte aktive 25-Stationen-Netz ab 1991 (Roomassaare ab 2007); "
        "ARSO Slowenien mit offiziellen täglichen Tmin/Tmax-Reihen und 73 kartierbaren Quell-IDs (346 ausgeschlossen); "
        "GHCN-Daily für das übrige Europa. "
        f"Das laufende Jahr {current_year} wird bei jedem Workflow-Lauf separat aktualisiert."
    )
    payload["publication_scope"] = (
        "Europa vollständig: nationale Quellen für Deutschland, Frankreich, Spanien, Österreich, Polen, "
        "Niederlande, Norwegen, Dänemark, Schweden, Belgien, die Schweiz, Finnland, Tschechien, Ungarn, Irland, Estland und Slowenien; GHCN-Daily für Rest-Europa"
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
        "Finnland": {
            "source": fmi_hist.SOURCE,
            "historical_complete": True,
            "current_year_station_count": fmi_current_count,
            "history_note": "FMI daily multipointcoverage tmin/tmax; historische Baseline ab 1844.",
        },
        "Tschechien": {
            "source": chmi_hist.SOURCE,
            "historical_complete": True,
            "current_year_station_count": chmi_current_count,
            "history_note": "CHMI TMA/TMI; ausschließlich QUALITY=0; historische Reihen bis 1775.",
        },
        "Ungarn": {
            "source": hungary_hist.SOURCE,
            "historical_complete": True,
            "current_year_station_count": hungary_current_count,
            "history_note": "HungaroMet: kontrollierte nicht homogenisierte Originalreihen ab 1901 plus automatisches HABP_1D Stationsnetz (historisch vor allem ab 2002).",
        },
        "Irland": {
            "source": ireland_hist.SOURCE,
            "historical_complete": True,
            "current_year_station_count": ireland_current_count,
            "history_note": "Met Éireann: offizielle tägliche maxtp/mintp-Lufttemperatur; gmin/igmin ausgeschlossen; nur Republik Irland.",
        },
        "Estland": {
            "source": estonia_hist.SOURCE,
            "historical_complete": True,
            "current_year_station_count": estonia_current_count,
            "history_note": "Estonian Environment Agency: DTAX/DTAN für 25 verifizierte aktive Stationen; öffentliche Baseline ab 1991, Roomassaare ab 2007.",
        },
        "Slowenien": {
            "source": slovenia_hist.SOURCE,
            "historical_complete": True,
            "current_year_station_count": slovenia_current_count,
            "published_station_count": SLOVENIA_EXPECTED_MAP_READY,
            "ignored_station_ids": sorted(SLOVENIA_IGNORED_IDS),
            "history_note": "ARSO Agromet tägliche Tmin/Tmax-Monatstabellen; 73/74 Quell-IDs mit verifizierten Koordinaten. ID 346 Turški Vrh bewusst ausgeschlossen.",
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
        "Finnland": fmi_hist.SOURCE,
        "Tschechien": chmi_hist.SOURCE,
        "Ungarn": hungary_hist.SOURCE,
        "Irland": ireland_hist.SOURCE,
        "Estland": estonia_hist.SOURCE,
        "Slowenien": slovenia_hist.SOURCE,
    }
    for country, source in expected.items():
        country_rows = [row for row in rows if row.get("country") == country]
        if not country_rows:
            raise RuntimeError(f"Keine Stationen für {country} erzeugt.")
        wrong = [row for row in country_rows if row.get("source") != source]
        if wrong:
            wrong_sources = sorted({row.get("source") for row in wrong})
            raise RuntimeError(f"{country} enthält falsche/gemischte Quellen: {wrong_sources}; erwartet {source}.")

    slovenia_rows = [
        row for row in rows
        if row.get("country") == "Slowenien"
    ]
    if len(slovenia_rows) != SLOVENIA_EXPECTED_MAP_READY:
        raise RuntimeError(
            f"Slowenien enthält {len(slovenia_rows)} statt exakt 73 Stationen."
        )
    if any(str(row.get("id")) == "ARSO:346" for row in slovenia_rows):
        raise RuntimeError("ARSO:346 darf nicht in der Europa-Ausgabe erscheinen.")

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
        fmi_hist.SOURCE,
        chmi_hist.SOURCE,
        hungary_hist.SOURCE,
        ireland_hist.SOURCE,
        estonia_hist.SOURCE,
        slovenia_hist.SOURCE,
        core.GHCN_SOURCE,
    ):
        if counts.get(source, 0) <= 0:
            raise RuntimeError(f"Quelle {source} hat 0 Stationen.")

    if not rows or any("active" not in row or "last_observation" not in row for row in rows):
        raise RuntimeError("Aktivstatus/letzte Beobachtung fehlt bei mindestens einer Station.")
    missing_opposite = []
    for row in rows:
        if row.get("tmax", {}).get("record") is not None and row.get("tmax", {}).get("lowest_record") is None:
            missing_opposite.append(f"{row.get('id')}:TMAX")
        if row.get("tmin", {}).get("record") is not None and row.get("tmin", {}).get("highest_record") is None:
            missing_opposite.append(f"{row.get('id')}:TMIN")
    if missing_opposite:
        raise RuntimeError(
            "Neue Gegenextreme fehlen: " + ", ".join(missing_opposite[:12])
        )
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

    assert {"SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN", "SI"}.issubset(NATIONAL_GHCN_CODES)
    assert SLOVENIA_IGNORED_IDS == {"346"}
    assert SLOVENIA_EXPECTED_MAP_READY == 73
    assert "346" not in _slovenia_filter_records({"345": {}, "346": {}, "347": {}})
    one_si = _make_station_meta(
        sid="ARSO:192", raw_meta={"name": "Ljubljana", "lat": 46.06, "lon": 14.51, "elevation_m": 299},
        lat_keys=("lat",), lon_keys=("lon",), elev_keys=("elevation_m",), name_keys=("name",),
        country_code="SI", country="Slowenien", source=slovenia_hist.SOURCE, quality_rule="test"
    )
    assert one_si is not None and one_si.country == "Slowenien" and one_si.id == "ARSO:192"

    ireland_meta_test = ireland_inventory_to_meta(
        {"532": {"name": "Dublin Airport", "lat": 53.43, "lon": -6.25, "elevation_m": 71}},
        record_ids={"532"},
    )
    assert ireland_meta_test["METEIREANN:532"].country == "Irland"
    assert ireland_meta_test["METEIREANN:532"].country_code == "EI"
    assert ireland_meta_test["METEIREANN:532"].source == ireland_hist.SOURCE

    smhi_meta_test = smhi_inventory_to_meta({"1": {"name": "Test SE", "lat": 60.0, "lon": 15.0, "elevation_m": 100}})
    assert smhi_meta_test["SMHI:1"].country == "Schweden"
    belgium_meta_test = belgium_inventory_to_meta({"6447": {"name": "Uccle", "lat": 50.8, "lon": 4.35, "elevation_m": 100}})
    assert belgium_meta_test["RMI:6447"].source == belgium_hist.SOURCE
    swiss_meta_test = swiss_inventory_to_meta({"BER": {"name": "Bern", "lat": 46.95, "lon": 7.45, "elevation_m": 553}})
    assert swiss_meta_test["METEOSWISS:BER"].country == "Schweiz"
    fmi_meta_test = fmi_inventory_to_meta({"100001": {"name": "Test FI", "lat": 60.2, "lon": 24.9, "elevation_m": 50}})
    assert fmi_meta_test["FMI:100001"].country == "Finnland"
    estonia_meta_test = estonia_inventory_to_meta({"AJHARK01": {"name": "Tallinn-Harku", "lat": 59.398, "lon": 24.603}})
    assert estonia_meta_test["ILMATEENISTUS:AJHARK01"].country == "Estland"
    assert estonia_meta_test["ILMATEENISTUS:AJHARK01"].source == estonia_hist.SOURCE
    chmi_meta_test = chmi_inventory_to_meta({"0-203-X": {"name": "Praha", "lat": 50.08, "lon": 14.43, "elevation": 200}})
    assert chmi_meta_test["CHMI:0-203-X"].country == "Tschechien"

    from array import array as _array
    packed = {"X": {
        "ordinals": _array("i", [dt.date(2025,1,1).toordinal(), dt.date(2025,1,2).toordinal()]),
        "tmax_tenths": _array("h", [100, 120]),
        "tmin_tenths": _array("h", [-50, -30]),
    }}
    packed_states = chmi_packed_to_core_states(packed)
    assert packed_states["CHMI:X"]["TMAX"]["abs"] == (120, 20250102, 1)
    packed_current = chmi_packed_to_core_current(packed)
    assert packed_current["CHMI:X"]["TMIN"]["01-01"] == (-50, 20250101)

    sample_records = {
        "X": {
            "first_date": "1901-01-01",
            "last_date": "2025-12-31",
            "observation_days": 1000,
            "tmax_abs": [40.1, "2020-07-01"],
            "tmax_low_abs": [-10.5, "1940-01-01"],
            "tmin_abs": [-20.2, "1940-01-01"],
            "tmin_high_abs": [22.3, "2020-07-01"],
            "calendar_tmax": {"07-01": [40.1, "2020-07-01"]},
            "calendar_tmin": {"01-01": [-20.2, "1940-01-01"]},
        }
    }
    states = compact_records_to_core_states(sample_records, prefix="TEST")
    assert states["TEST:X"]["TMAX"]["abs"] == (401, 20200701, 1)
    assert states["TEST:X"]["TMIN"]["cal"]["01-01"] == (-202, 19400101, 1)
    assert states["TEST:X"]["TMAX"]["opposite_abs"] == (-105, 19400101, 1)
    assert states["TEST:X"]["TMIN"]["opposite_abs"] == (223, 20200701, 1)
    current = compact_records_to_core_current(
        {"X": {"calendar_tmax": {"08-01": [31.2, "2026-08-01"]}, "calendar_tmin": {}}},
        prefix="TEST",
    )
    assert current["TEST:X"]["TMAX"]["08-01"] == (312, 20260801)

    meta = core.StationMeta("TEST:X", 50.0, 8.0, 100.0, "Test", "ZZ", "Testland", "TEST", "test")
    payload = {"stations": [{"id": "TEST:X", "source": "TEST", "tmax": {"record": {"value": 40.1}}, "tmin": {"record": {"value": -20.2}}}]}
    add_station_activity(payload, stations={"TEST:X": meta}, states=states, current=current)
    add_opposite_station_extremes(payload, states=states, current=current)
    assert payload["stations"][0]["active"] is True
    assert payload["stations"][0]["tmax"]["lowest_record"]["value"] == -10.5
    assert payload["stations"][0]["tmin"]["highest_record"]["value"] == 22.3
    assert payload["stations"][0]["last_observation"] == "2026-08-01"
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
    parser.add_argument("--force-fmi-baseline", action="store_true")
    parser.add_argument("--force-chmi-baseline", action="store_true")
    parser.add_argument("--force-hungary-baseline", action="store_true")
    parser.add_argument("--force-ireland-baseline", action="store_true")
    parser.add_argument("--force-estonia-baseline", action="store_true")
    parser.add_argument("--force-slovenia-baseline", action="store_true")
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
        "SMHI Schweden + KMI/RMI Belgien + MeteoSwiss Schweiz + FMI Finnland + "
        "CHMI Tschechien + HungaroMet Ungarn + Met Éireann Irland + Estland Climate API + ARSO Slowenien + GHCN-Daily Rest-Europa."
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
        if meta.country_code not in {"AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN", "SI"}
    }
    log(
        f"GHCN-Metadaten Rest-Europa nach Ausschluss DE/FR/ES/AT/PL/NL/NO/DK/SE/BE/CH/FI/CZ/HU/IE/EE/SI: "
        f"{len(ghcn_stations):,}"
    )
    if not ghcn_stations:
        raise RuntimeError("Keine GHCN-Stationen für Rest-Europa gefunden.")

    dwd_text = core.decode_text_smart(core.read_url_bytes(core.DWD_STATIONS_URL))
    dwd_stations = core.parse_dwd_stations(dwd_text)
    if not dwd_stations:
        raise RuntimeError("Keine DWD-KL-Stationsmetadaten gefunden.")

    ghcn_cache = cache_dir / (
        f"ghcn_europe_baseline_through_{cutoff_year}_v{core.GHCN_BASELINE_FORMAT_VERSION}"
        f"_opposite_v{OPPOSITE_EXTREMES_CACHE_VERSION}.pkl.gz"
    )
    dwd_cache = cache_dir / (
        f"dwd_germany_kl_baseline_through_{cutoff_year}_v{core.DWD_BASELINE_FORMAT_VERSION}"
        f"_opposite_v{OPPOSITE_EXTREMES_CACHE_VERSION}_clim_v{dwd_daily_map.CACHE_VERSION}.pkl.gz"
    )
    mf_cache = cache_dir / (
        f"meteofrance_daily_baseline_through_{cutoff_year}_v{core.MF_BASELINE_FORMAT_VERSION}"
        f"_opposite_v{OPPOSITE_EXTREMES_CACHE_VERSION}.pkl.gz"
    )

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
        fmi_base,
        fmi_cur_payload,
        estonia_base,
        estonia_cur_payload,
        slovenia_base,
        slovenia_cur_payload,
        chmi_base,
        chmi_cur_payload,
        hungary_base,
        hungary_cur_payload,
        ireland_base,
        ireland_cur_payload,
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
        force_fmi=force_all or args.force_fmi_baseline,
        force_estonia=force_all or args.force_estonia_baseline,
        force_slovenia=force_all or args.force_slovenia_baseline,
        force_chmi=force_all or args.force_chmi_baseline,
        force_hungary=force_all or args.force_hungary_baseline,
        force_ireland=force_all or args.force_ireland_baseline,
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
    fmi_current = compact_records_to_core_current(fmi_cur_payload.get("records", {}), prefix="FMI")
    estonia_current = compact_records_to_core_current(estonia_cur_payload.get("records", {}), prefix="ILMATEENISTUS")
    slovenia_current = compact_records_to_core_current(
        _slovenia_filter_records(slovenia_cur_payload.get("records", {})),
        prefix="ARSO",
    )
    chmi_current = chmi_packed_to_core_current(chmi_cur_payload.get("stations", {}))
    hungary_current = compact_records_to_core_current(hungary_cur_payload.get("records", {}), prefix="HUNGAROMET")
    ireland_current = compact_records_to_core_current(ireland_cur_payload.get("records", {}), prefix="METEIREANN")

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
        ("FMI Finnland", fmi_current),
        ("Estland Climate API", estonia_current),
        ("ARSO Slowenien", slovenia_current),
        ("CHMI Tschechien", chmi_current),
        ("HungaroMet Ungarn", hungary_current),
        ("Met Éireann Irland", ireland_current),
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
    fmi_inventory = dict(fmi_base.get("inventory", {}))
    fmi_inventory.update(fmi_cur_payload.get("inventory", {}))
    estonia_inventory = dict(estonia_base.get("inventory", {}))
    estonia_inventory.update(estonia_cur_payload.get("inventory", {}))
    chmi_inventory = chmi_payload_inventory(chmi_base, chmi_cur_payload)
    hungary_inventory = dict(hungary_base.get("inventory", {}))
    hungary_inventory.update(hungary_cur_payload.get("inventory", {}))
    ireland_inventory = dict(ireland_base.get("inventory", {}))
    ireland_inventory.update(ireland_cur_payload.get("inventory", {}))

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
    fmi_stations = fmi_inventory_to_meta(fmi_inventory)
    estonia_stations = estonia_inventory_to_meta(estonia_inventory)
    slovenia_metadata = _load_slovenia_map_metadata()
    slovenia_stations = slovenia_metadata_to_meta(slovenia_metadata)
    log(
        f"ARSO Slowenien Metadaten: {len(slovenia_stations)} Stationen; "
        "ID 346 Turški Vrh bewusst ausgeschlossen."
    )
    chmi_stations = chmi_inventory_to_meta(chmi_inventory)

    hungary_record_ids = set(str(x) for x in hungary_base.get("records", {}))
    hungary_record_ids.update(str(x) for x in hungary_cur_payload.get("records", {}))
    hungary_stations = hungary_inventory_to_meta(
        hungary_inventory,
        record_ids=hungary_record_ids,
    )

    ireland_record_ids = set(str(x) for x in ireland_base.get("records", {}))
    ireland_record_ids.update(str(x) for x in ireland_cur_payload.get("records", {}))
    ireland_stations = ireland_inventory_to_meta(
        ireland_inventory,
        record_ids=ireland_record_ids,
    )
    log(
        f"Met Éireann Metadaten: {len(ireland_stations)} von {len(ireland_record_ids)} "
        "Temperatur-Stationsreihen kartierbar."
    )

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

    if (not aemet_stations or not knmi_stations or not frost_stations or not dmi_stations
            or not smhi_stations or not belgium_stations or not swiss_stations
            or not fmi_stations or not estonia_stations or not slovenia_stations or not chmi_stations or not hungary_stations
            or not ireland_stations):
        raise RuntimeError(
            "Nationale Metadaten unvollständig: "
            f"AEMET={len(aemet_stations)}, KNMI={len(knmi_stations)}, "
            f"Frost={len(frost_stations)}, DMI={len(dmi_stations)}, "
            f"SMHI={len(smhi_stations)}, Belgien={len(belgium_stations)}, "
            f"MeteoSwiss={len(swiss_stations)}, FMI={len(fmi_stations)}, "
            f"Estland={len(estonia_stations)}, Slowenien={len(slovenia_stations)}, CHMI={len(chmi_stations)}, HungaroMet={len(hungary_stations)}, "
            f"MetEireann={len(ireland_stations)}"
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
    stations.update(fmi_stations)
    stations.update(estonia_stations)
    stations.update(slovenia_stations)
    stations.update(chmi_stations)
    stations.update(hungary_stations)
    stations.update(ireland_stations)

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
    states.update(compact_records_to_core_states(fmi_base.get("records", {}), prefix="FMI"))
    states.update(compact_records_to_core_states(estonia_base.get("records", {}), prefix="ILMATEENISTUS"))
    states.update(compact_records_to_core_states(
        _slovenia_filter_records(slovenia_base.get("records", {})),
        prefix="ARSO",
    ))
    states.update(chmi_packed_to_core_states(chmi_base.get("stations", {})))
    states.update(compact_records_to_core_states(hungary_base.get("records", {}), prefix="HUNGAROMET"))
    states.update(compact_records_to_core_states(ireland_base.get("records", {}), prefix="METEIREANN"))

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
    current.update(fmi_current)
    current.update(estonia_current)
    current.update(slovenia_current)
    current.update(chmi_current)
    current.update(hungary_current)
    current.update(ireland_current)

    if output_dir.exists():
        import shutil
        shutil.rmtree(output_dir)

    core.merge_and_write(output_dir, stations, states, current, current_year)
    dwd_daily_map.write_daily_map(
        output_dir / "dwd_daily_map",
        stations=dwd_stations,
        baseline=dwd_baseline,
        current=dwd_current,
        current_year=current_year,
        station_listing_text=dwd_text,
    )
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
        fmi_current_count=len(fmi_current),
        estonia_current_count=len(estonia_current),
        slovenia_current_count=len(slovenia_current),
        chmi_current_count=len(chmi_current),
        hungary_current_count=len(hungary_current),
        ireland_current_count=len(ireland_current),
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
