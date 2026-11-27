#!/usr/bin/env python3
"""Quellen des Europa-Anomalie- und Rekordmonitors (Stufe A, B1, B2.1).

Grundidee
---------
Die vorhandenen nationalen Adapter bleiben unverändert. Zur Laufzeit wird in ihre Parse-/Consume-Funktionen
ein Hook eingehängt, der jeden Tageswert zusätzlich in eine kompakte Stationsreihe (``Series``) schreibt.
Die Reihe liegt im selben Zwischenstand wie die Rekorddaten des Adapters (Station-Dict bzw. Teil-Zustand).
Damit gilt automatisch dieselbe Fortsetzbarkeit wie beim Adapter: Checkpoints, Einzeldatei-Caches und
Blockcaches enthalten die Reihe mit. Erst am Ende entsteht daraus der Engine-Stand
(Klimamittel, Rekorde, Messjahre).

* Qualitätsregeln: Die Hooks rufen zuerst die Originalfunktion auf und verwenden für die Wiederholung der
  Zeilenschleife ausschließlich Hilfsfunktionen und Grenzwerte des Adapters. Es gibt keine eigenen Prüfregeln.
* Eigener Cache: Alles liegt unter ``<cache-dir>/adapters_h<N>`` und ``<cache-dir>/engines``. Die Caches des
  bestehenden Europa-Rekord-Workflows werden weder gelesen noch verändert (Ausnahme: ``--chmi-cache-dir``,
  nur lesend, weil der CHMI-Cache bereits die vollständigen Tagesreihen enthält).
* Keine stillen Quellenwechsel: Fällt eine Quelle aus oder ist ihre Baseline noch im Aufbau, bleibt sie mit
  Status und Meldung in der Ergebnisliste. Ihre Stationen werden nicht durch GHCN oder eine andere Quelle ersetzt.
"""
from __future__ import annotations

import calendar
import csv
import datetime as dt
import gzip
import importlib
import io
import json
import math
import os
import pickle
import re
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import europe_climate_engine as E
import update_europe_station_records as core

HOOK_VERSION = 1                                  # bei Änderung der Erfassung hochzählen (neuer Cache-Ordner)
BELGIUM_NORMALS_FROM_YEAR = 2000                  # ohne Uccle: vorher SYNOP-Fenstermaxima/-minima, inhomogen zu AWS
BELGIUM_UCCLE_CODE = "6447"
MIN_CAPTURE_SHARE = 0.9                           # so viele Stationen mit Rekorddaten müssen auch eine Reihe haben

# Länder mit eigener nationaler Quelle, deren GHCN-Stationen daher nicht in "GHCN Rest-Europa" auftauchen.
# (identisch zur Ausschlussliste des bestehenden Europa-Rekord-Skripts; GM/FR/SP schließt der Core selbst aus)
GHCN_EXCLUDED_CODES = {"AU", "PL", "NL", "NO", "DA", "SW", "BE", "SZ", "FI", "EZ", "HU", "EI", "EN", "SI"}


def default_log(message: str) -> None:
    print(message, flush=True)


# =========================================================================== Ergebnis-Typen
class BaselineIncomplete(RuntimeError):
    """Die historische Baseline ist noch im Aufbau (Laufzeitlimit, fehlende Teile). Nächster Lauf setzt fort."""


@dataclass
class SourceResult:
    key: str
    label: str
    stage: str
    countries: Tuple[str, ...]
    status: str = "planned"                       # ok | failed | building | planned
    message: str = ""
    stations: Dict[str, Any] = field(default_factory=dict)      # sid -> core.StationMeta
    engines: Dict[str, dict] = field(default_factory=dict)      # sid -> finaler Engine-Stand
    current: Dict[str, dict] = field(default_factory=dict)      # sid -> {"TMAX": {mmdd: (wert, datum)}, "TMIN": {...}}
    notes: List[str] = field(default_factory=list)


@dataclass
class Ctx:
    year: int
    cache_dir: Path
    workers: int = 6
    force: frozenset = frozenset()
    max_runtime_minutes: float = 150.0
    chmi_cache_dir: Optional[Path] = None
    baseline_only: bool = False
    log: Callable[[str], None] = default_log
    _ghcn_all: Optional[dict] = None

    @property
    def cutoff(self) -> int:
        return self.year - 1

    @property
    def adapters_dir(self) -> Path:
        # Ordner trägt die Hook-Version: Nach einer Änderung der Erfassung werden keine Zwischenstände ohne Reihen wiederverwendet.
        return self.cache_dir / f"adapters_h{HOOK_VERSION}"

    @property
    def engines_dir(self) -> Path:
        return self.cache_dir / "engines"

    def forced(self, key: str) -> bool:
        return "all" in self.force or key in self.force

    def ghcn_all(self) -> Dict[str, Any]:
        """GHCN-Stationsverzeichnis (alle europäischen Codes), einmal je Lauf geladen."""
        if self._ghcn_all is None:
            countries = core.parse_countries(core.read_url_text(core.COUNTRIES_URL))
            self._ghcn_all = core.parse_ghcn_stations(core.read_url_text(core.STATIONS_URL), countries)
        return self._ghcn_all


# =========================================================================== Hook-Verwaltung
_ORIG: Dict[Tuple[str, str], Tuple[Any, Any]] = {}
_TLS = threading.local()


def _patch(module: Any, name: str, replacement: Callable) -> None:
    key = (module.__name__, name)
    if key in _ORIG:
        return
    _ORIG[key] = (module, getattr(module, name))
    setattr(module, name, replacement)


def _orig(module: Any, name: str) -> Callable:
    return _ORIG[(module.__name__, name)][1]


def uninstall_hooks() -> None:
    for (_mod, _name), (module, original) in list(_ORIG.items()):
        setattr(module, _name, original)
    _ORIG.clear()


def _tenths(value: Any, decimals: Optional[int] = None) -> Optional[int]:
    """°C -> Zehntelgrad. decimals: Rundung, die der Adapter vor dem Speichern anwendet (damit identisch zu seinen Rekorden)."""
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if decimals is not None:
        number = round(number, decimals)
    return int(round(number * 10.0))


def _merge_pk(target: dict, incoming: dict) -> None:
    for sid, state in incoming.items():
        pk = state.get("_pk") if isinstance(state, dict) else None
        if pk is None or sid not in target:
            continue
        dst = target[sid]
        have = dst.get("_pk")
        if have is None:
            dst["_pk"] = pk.copy()
        else:
            have.merge(pk)


def _carry_pk(partial: dict, out: dict) -> None:
    for sid, state in partial.items():
        pk = state.get("_pk") if isinstance(state, dict) else None
        if pk is not None and sid in out:
            out[sid]["_pk"] = pk


# =========================================================================== Reihen aus Rohdaten (reine Funktionen)
def series_from_dly(data: bytes, cutoff_year: int) -> Optional[E.Series]:
    """GHCN-Daily .dly: nur TMAX/TMIN mit leerem Qualitätsflag (wie ``core.parse_dly_station``)."""
    ser = E.Series()
    for raw in io.BytesIO(data):
        line = raw.decode("ascii", errors="ignore")
        if len(line) < 21:
            continue
        try:
            year = int(line[11:15])
            month = int(line[15:17])
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
            if element == "TMAX":
                ser.add(year, month, day, value, None)
            else:
                ser.add(year, month, day, None, value)
    return ser if ser.y else None


def series_from_dwd_zip(data: bytes, cutoff_year: Optional[int]) -> Optional[E.Series]:
    """DWD KL-Produkt: TXK/TNK (wie ``core.parse_dwd_product_bytes``)."""
    ser = E.Series()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        candidates = [n for n in zf.namelist() if re.search(r"produkt_klima_tag_.*\.txt$", n, re.I)]
        if not candidates:
            candidates = [n for n in zf.namelist() if n.lower().endswith(".txt") and "produkt" in n.lower()]
        for member in candidates:
            with zf.open(member) as raw:
                text = io.TextIOWrapper(raw, encoding="latin-1", errors="replace", newline="")
                header = text.readline()
                if not header:
                    continue
                names = [h.strip() for h in header.rstrip("\r\n").split(";")]
                if "MESS_DATUM" not in names or ("TXK" not in names and "TNK" not in names):
                    continue
                i_date = names.index("MESS_DATUM")
                i_tx = names.index("TXK") if "TXK" in names else -1
                i_tn = names.index("TNK") if "TNK" in names else -1
                for line in text:
                    parts = line.rstrip("\r\n").split(";")
                    if i_date >= len(parts):
                        continue
                    ds = parts[i_date].strip()
                    if len(ds) != 8 or not ds.isdigit():
                        continue
                    year = int(ds[:4])
                    if cutoff_year is not None and year > cutoff_year:
                        continue
                    try:
                        dt.date(year, int(ds[4:6]), int(ds[6:8]))
                    except ValueError:
                        continue
                    tx = core.dwd_float_to_tenths(parts[i_tx]) if 0 <= i_tx < len(parts) else None
                    tn = core.dwd_float_to_tenths(parts[i_tn]) if 0 <= i_tn < len(parts) else None
                    ser.add(year, int(ds[4:6]), int(ds[6:8]), tx, tn)
    return ser if ser.y else None


def series_from_mf_gz(data: bytes, cutoff_year: Optional[int]) -> Dict[str, E.Series]:
    """Météo-France Q_*_RR-T-Vent.csv.gz: TX/TN mit Qualitätscodes 0/1/9/leer (wie ``core.parse_mf_stream``)."""
    out: Dict[str, E.Series] = {}
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.reader(text, delimiter=";")
        header = next(reader, None)
        if not header:
            return out
        fmap = {str(k).strip().upper(): i for i, k in enumerate(header)}
        if "NUM_POSTE" not in fmap or "AAAAMMJJ" not in fmap or not ({"TX", "TN"} & set(fmap)):
            return out                                   # der Core meldet diesen Fall selbst als Fehler
        i_id, i_date = fmap["NUM_POSTE"], fmap["AAAAMMJJ"]
        i_lat, i_lon = fmap.get("LAT"), fmap.get("LON")
        i_tx, i_qtx, i_tn, i_qtn = fmap.get("TX"), fmap.get("QTX"), fmap.get("TN"), fmap.get("QTN")

        def cell(row: list, idx: Optional[int]) -> str:
            return row[idx] if idx is not None and idx < len(row) else ""

        for row in reader:
            sid = core.mf_station_id(cell(row, i_id))
            ds = str(cell(row, i_date)).strip().replace(".0", "")
            if not sid or len(ds) != 8 or not ds.isdigit():
                continue
            year = int(ds[:4])
            if cutoff_year is not None and year > cutoff_year:
                continue
            try:
                dt.date(year, int(ds[4:6]), int(ds[6:8]))
            except ValueError:
                continue
            lat = core.mf_float(cell(row, i_lat)) if i_lat is not None else None
            lon = core.mf_float(cell(row, i_lon)) if i_lon is not None else None
            if lat is None or lon is None or not (core.LAT_MIN <= lat <= core.LAT_MAX and core.LON_MIN <= lon <= core.LON_MAX):
                continue
            tx = tn = None
            if i_tx is not None:
                v = core.mf_temp_to_tenths(cell(row, i_tx))
                if v is not None and core.mf_quality_ok(cell(row, i_qtx) if i_qtx is not None else ""):
                    tx = v
            if i_tn is not None:
                v = core.mf_temp_to_tenths(cell(row, i_tn))
                if v is not None and core.mf_quality_ok(cell(row, i_qtn) if i_qtn is not None else ""):
                    tn = v
            if tx is None and tn is None:
                continue
            ser = out.get(sid)
            if ser is None:
                ser = out[sid] = E.Series()
            ser.add(year, int(ds[4:6]), int(ds[6:8]), tx, tn)
    return out


def series_from_austria_payload(payload: dict, pmax: str, pmin: str, cutoff_year: Optional[int], mod: Any) -> Dict[str, E.Series]:
    """GeoSphere Austria klima-v2-1d (wie ``parse_feature_collection`` im historischen Modus)."""
    out: Dict[str, E.Series] = {}
    timestamps = payload.get("timestamps") or payload.get("time") or []
    dates = [mod.parse_timestamp(x) for x in timestamps]
    features = payload.get("features") or []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties") if isinstance(feat.get("properties"), dict) else feat
        raw_id = mod.feature_station_raw_id(props)
        if not raw_id:
            continue
        sid = f"GSA:{raw_id}"
        params = props.get("parameters") if isinstance(props.get("parameters"), dict) else {}
        for parameter_name, element in ((pmax, "TMAX"), (pmin, "TMIN")):
            block = params.get(parameter_name)
            if block is None:
                for k, v in params.items():
                    if str(k).lower() == parameter_name.lower():
                        block = v
                        break
            if isinstance(block, dict):
                values = block.get("data") or block.get("values") or []
            elif isinstance(block, list):
                values = block
            else:
                values = []
            for date_obj, raw_value in zip(dates, values):
                if date_obj is None:
                    continue
                if cutoff_year is not None and date_obj.year > cutoff_year:
                    continue
                value = mod.temp_to_tenths(raw_value)
                if value is None:
                    continue
                ser = out.get(sid)
                if ser is None:
                    ser = out[sid] = E.Series()
                if element == "TMAX":
                    ser.add(date_obj.year, date_obj.month, date_obj.day, value, None)
                else:
                    ser.add(date_obj.year, date_obj.month, date_obj.day, None, value)
    return out


def series_from_imgw_members(raw_members: Iterable[bytes], schema: dict, cutoff_year: Optional[int], mod: Any) -> Dict[str, E.Series]:
    """IMGW k_d-CSV (wie ``parse_zip`` im historischen Modus). raw_members sind die bereits gelesenen CSV-Bytes."""
    out: Dict[str, E.Series] = {}
    indexes = [schema[key] for key in ("station", "name", "year", "month", "day", "tmax", "tmin")]
    max_index = max(index for index in indexes if index is not None)
    for raw_member in raw_members:
        text = mod.decode_polish(raw_member)
        delimiter = mod.detect_delimiter(text)
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            if len(row) <= max_index:
                continue
            raw = row[schema["station"]].strip().replace(".0", "")
            if not raw:
                continue
            try:
                year = int(float(row[schema["year"]]))
                month = int(float(row[schema["month"]]))
                day = int(float(row[schema["day"]]))
                dt.date(year, month, day)
            except (ValueError, TypeError):
                continue
            if cutoff_year is not None and year > cutoff_year:
                continue
            tx = mod.temp_tenths(row[schema["tmax"]])
            tn = mod.temp_tenths(row[schema["tmin"]])
            if tx is None and tn is None:
                continue
            sid = f"IMGW:{raw}"
            ser = out.get(sid)
            if ser is None:
                ser = out[sid] = E.Series()
            ser.add(year, month, day, tx, tn)
    return out


def series_from_chmi_packed(record: dict, missing: int) -> Optional[E.Series]:
    """CHMI-Cache: ``ordinals`` (Tagesnummern), ``tmax_tenths``, ``tmin_tenths``; MISSING_I16 = fehlend."""
    ser = E.Series()
    for ordv, tx_raw, tn_raw in zip(record.get("ordinals", []), record.get("tmax_tenths", []), record.get("tmin_tenths", [])):
        try:
            day = dt.date.fromordinal(int(ordv))
        except (TypeError, ValueError, OverflowError):
            continue
        tx = tn = None
        try:
            v = int(tx_raw)
            tx = None if v == missing else v
        except (TypeError, ValueError):
            pass
        try:
            v = int(tn_raw)
            tn = None if v == missing else v
        except (TypeError, ValueError):
            pass
        ser.add(day.year, day.month, day.day, tx, tn)
    return ser if ser.y else None


# =========================================================================== Hooks: Core (DWD, GHCN, Météo-France)
def install_core_hooks() -> None:
    def parse_dwd(data: bytes, cutoff_year=None, exact_year=None) -> dict:
        state = _orig(core, "parse_dwd_product_bytes")(data, cutoff_year=cutoff_year, exact_year=exact_year)
        if exact_year is None:
            ser = series_from_dwd_zip(data, cutoff_year)
            if ser is not None:
                state["_pk"] = ser
        return state

    def parse_dly(stream, cutoff_year: int) -> dict:
        data = stream.read()
        state = _orig(core, "parse_dly_station")(io.BytesIO(data), cutoff_year)
        ser = series_from_dly(data, cutoff_year)
        if ser is not None:
            state["_pk"] = ser
        return state

    def parse_mf(fileobj, *, cutoff_year=None, exact_year=None):
        orig = _orig(core, "parse_mf_stream")
        if exact_year is not None:
            return orig(fileobj, cutoff_year=cutoff_year, exact_year=exact_year)
        data = fileobj.read()
        partial, current, metas = orig(io.BytesIO(data), cutoff_year=cutoff_year, exact_year=None)
        for sid, ser in series_from_mf_gz(data, cutoff_year).items():
            if sid in partial:
                partial[sid]["_pk"] = ser
        return partial, current, metas

    def merge_mf(target: dict, incoming: dict) -> None:
        _orig(core, "merge_mf_partial")(target, incoming)
        _merge_pk(target, incoming)

    def finalize_mf(partial: dict) -> dict:
        out = _orig(core, "finalize_mf_states")(partial)
        _carry_pk(partial, out)
        return out

    _patch(core, "parse_dwd_product_bytes", parse_dwd)
    _patch(core, "parse_dly_station", parse_dly)
    _patch(core, "parse_mf_stream", parse_mf)
    _patch(core, "merge_mf_partial", merge_mf)
    _patch(core, "finalize_mf_states", finalize_mf)


# =========================================================================== Hooks: Adapter-Module
def install_austria_hooks(mod: Any) -> None:
    def parse_fc(payload, pmax, pmin, cutoff_year=None, exact_year=None):
        partial, current = _orig(mod, "parse_feature_collection")(payload, pmax, pmin, cutoff_year, exact_year)
        if exact_year is None:
            for sid, ser in series_from_austria_payload(payload, pmax, pmin, cutoff_year, mod).items():
                if sid in partial:
                    partial[sid]["_pk"] = ser
        return partial, current

    def merge(target: dict, incoming: dict) -> None:
        _orig(mod, "merge_partial_states")(target, incoming)
        _merge_pk(target, incoming)

    def finalize(partial: dict) -> dict:
        out = _orig(mod, "finalize_partial_states")(partial)
        _carry_pk(partial, out)
        return out

    _patch(mod, "parse_feature_collection", parse_fc)
    _patch(mod, "merge_partial_states", merge)
    _patch(mod, "finalize_partial_states", finalize)


def install_poland_hooks(mod: Any) -> None:
    def read_member(archive_bytes, zf, member, schema):
        raw = _orig(mod, "_read_zip_member_with_crc_fallback")(archive_bytes, zf, member, schema)
        capture = getattr(_TLS, "imgw_capture", None)
        if capture is not None:
            capture.append(raw)
        return raw

    def parse_zip(data, schema, *, cutoff_year=None, exact_year=None):
        orig = _orig(mod, "parse_zip")
        if exact_year is not None:
            return orig(data, schema, cutoff_year=cutoff_year, exact_year=exact_year)
        _TLS.imgw_capture = []
        try:
            partial, current, names = orig(data, schema, cutoff_year=cutoff_year, exact_year=None)
            raws = _TLS.imgw_capture
        finally:
            _TLS.imgw_capture = None
        for sid, ser in series_from_imgw_members(raws, schema, cutoff_year, mod).items():
            if sid in partial:
                partial[sid]["_pk"] = ser
        return partial, current, names

    def merge(target: dict, incoming: dict) -> None:
        _orig(mod, "merge_partial_states")(target, incoming)
        _merge_pk(target, incoming)

    def finalize(partial: dict) -> dict:
        out = _orig(mod, "finalize_partial_states")(partial)
        _carry_pk(partial, out)
        return out

    _patch(mod, "_read_zip_member_with_crc_fallback", read_member)
    _patch(mod, "parse_zip", parse_zip)
    _patch(mod, "merge_partial_states", merge)
    _patch(mod, "finalize_partial_states", finalize)


def _attach(rec: dict, year: int, month: int, day: int, tx: Optional[int], tn: Optional[int]) -> None:
    ser = rec.get("_pk")
    if ser is None:
        ser = rec["_pk"] = E.Series()
    ser.add(year, month, day, tx, tn)


def install_aemet_hooks(mod: Any) -> None:
    def consume(payload, *, window_start, window_end, inventory, records):
        result = _orig(mod, "consume_daily_payload")(
            payload, window_start=window_start, window_end=window_end, inventory=inventory, records=records)
        rows = payload
        if isinstance(rows, dict):
            rows = rows["datos"] if isinstance(rows.get("datos"), list) else [rows]
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get("indicativo", "")).strip()
            day_text = str(raw.get("fecha", "")).strip()[:10]
            if not sid or len(day_text) != 10 or sid not in records:
                continue
            try:
                day = dt.date.fromisoformat(day_text)
            except ValueError:
                continue
            tx = _tenths(mod.parse_number(raw.get("tmax")), 1)
            tn = _tenths(mod.parse_number(raw.get("tmin")), 1)
            if tx is None and tn is None:
                continue
            _attach(records[sid], day.year, day.month, day.day, tx, tn)
        return result

    _patch(mod, "consume_daily_payload", consume)


def install_knmi_hooks(mod: Any) -> None:
    def consume(records, rows):
        n = _orig(mod, "consume_rows")(records, rows)
        for station_id, d, tn, tx in rows:
            rec = records.get(station_id)
            if rec is not None:
                _attach(rec, d.year, d.month, d.day, _tenths(tx, 1), _tenths(tn, 1))
        return n

    _patch(mod, "consume_rows", consume)


def install_belgium_hooks(mod: Any) -> None:
    def consume(records, sid, d, tmin, tmax, provenance):
        used = _orig(mod, "consume_day")(records, sid, d, tmin, tmax, provenance)
        if used:
            _attach(records[sid], d.year, d.month, d.day, _tenths(tmax, 2), _tenths(tmin, 2))
        return used

    _patch(mod, "consume_day", consume)


def install_swiss_hooks(mod: Any) -> None:
    def consume(rec, d, tmin, tmax):
        used = _orig(mod, "consume_day")(rec, d, tmin, tmax)
        if used:
            _attach(rec, d.year, d.month, d.day, _tenths(tmax), _tenths(tmin))
        return used

    _patch(mod, "consume_day", consume)


# =========================================================================== Engine-Cache je Quelle
def _atomic_pickle(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=5) as handle:
        pickle.dump(obj, handle, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def _load_pickle(path: Path) -> Any:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


def engine_cache_path(ctx: Ctx, key: str) -> Path:
    return ctx.engines_dir / f"{key}_through_{ctx.cutoff}_e{E.ENGINE_VERSION}_h{HOOK_VERSION}.pkl.gz"


def load_engine_cache(ctx: Ctx, key: str) -> Optional[dict]:
    path = engine_cache_path(ctx, key)
    if not path.exists() or ctx.forced(key):
        return None
    try:
        payload = _load_pickle(path)
    except Exception as exc:
        ctx.log(f"{key}: Engine-Cache unlesbar ({exc}); wird neu aufgebaut.")
        return None
    if (payload.get("engine_version") != E.ENGINE_VERSION or payload.get("hook_version") != HOOK_VERSION
            or payload.get("cutoff_year") != ctx.cutoff or not payload.get("engines")):
        return None
    return payload


def save_engine_cache(ctx: Ctx, key: str, engines: dict, stations: dict, notes: List[str]) -> None:
    _atomic_pickle(engine_cache_path(ctx, key), {
        "engine_version": E.ENGINE_VERSION, "hook_version": HOOK_VERSION, "cutoff_year": ctx.cutoff,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "engines": engines,
        "stations": stations, "notes": notes,
    })


def _check_capture(label: str, with_records: int, with_series: int) -> None:
    if with_records and with_series < MIN_CAPTURE_SHARE * with_records:
        raise RuntimeError(
            f"{label}: Nur {with_series} von {with_records} Stationen haben eine Tageswertreihe. Die Baseline wurde vermutlich "
            "ohne Erfassung gebaut (alter Cache?). Mit --force-baseline neu aufbauen.")


def _engines_from_holders(label: str, holders: Dict[str, dict], sid_of: Callable[[str], str],
                          normals_from: Callable[[str], Optional[int]] = lambda raw: None) -> Dict[str, dict]:
    """holders: raw_id -> Dict mit '_pk'. Der Holder gibt die Reihe frei, sobald der Engine-Stand berechnet ist."""
    engines: Dict[str, dict] = {}
    for raw_id in list(holders):
        holder = holders[raw_id]
        ser = holder.pop("_pk", None) if isinstance(holder, dict) else None
        if ser is None:
            continue
        final = ser.to_final(normals_from(raw_id))
        if final is not None:
            engines[sid_of(raw_id)] = final
    _check_capture(label, len(holders), len(engines))
    return engines


# =========================================================================== Quellen
def _import(name: str) -> Any:
    return importlib.import_module(name)


def _allsrc() -> Any:
    """Stationsmetadaten-Konverter des bestehenden Europa-Skripts (gleiche Namen, Koordinaten, Länder)."""
    return _import("update_europe_station_records_all_sources")


def _finish(res: SourceResult, ctx: Ctx, engines: dict, stations: dict, current: dict, notes: List[str]) -> SourceResult:
    res.engines, res.stations, res.current, res.notes = engines, stations, current, notes
    res.status = "ok"
    res.message = (f"{len(stations)} Stationen, {len(engines)} mit Tageswertreihe, "
                   f"{len(current)} mit Daten für {ctx.year}")
    return res


def _status_summary(mod: Any, ctx: Ctx) -> str:
    try:
        data = json.loads(mod.status_path(ctx.adapters_dir, ctx.cutoff).read_text(encoding="utf-8"))
    except Exception:
        return ""
    parts = []
    for key, label in (("processed_windows", "Fenster"), ("processed_years", "Jahre"), ("stage", "Stufe"),
                       ("station_count", "Stationsreihen")):
        if data.get(key) is not None:
            parts.append(f"{label} {data[key]}" + (f"/{data['total_windows']}" if key == "processed_windows" and data.get("total_windows") else "")
                         + (f"/{data['total_years']}" if key == "processed_years" and data.get("total_years") else ""))
    return " | ".join(parts)


# ---- Deutschland (DWD CDC)
def run_dwd(ctx: Ctx, res: SourceResult) -> SourceResult:
    stations_text = core.decode_text_smart(core.read_url_bytes(core.DWD_STATIONS_URL))
    stations = core.parse_dwd_stations(stations_text)
    if not stations:
        raise RuntimeError("Keine DWD-KL-Stationsmetadaten gefunden.")
    cached = load_engine_cache(ctx, res.key)
    if cached:
        engines = cached["engines"]
    else:
        install_core_hooks()
        cache_file = ctx.adapters_dir / f"dwd_kl_baseline_through_{ctx.cutoff}_core{core.DWD_BASELINE_FORMAT_VERSION}_h{HOOK_VERSION}.pkl.gz"
        base = core.load_or_build_dwd_baseline(cache_file, stations, ctx.cutoff, ctx.forced(res.key), max(1, ctx.workers))
        engines = _engines_from_holders("DWD", base["states"], lambda raw: raw)
        save_engine_cache(ctx, res.key, engines, {}, [])
    if ctx.baseline_only:
        return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, {}, [])
    current = core.parse_current_dwd_year(ctx.year, stations, workers=max(4, ctx.workers))
    if not current:
        raise RuntimeError(f"Keine aktuellen DWD-KL-Daten für {ctx.year}.")
    notes = ["Tmean = (Tmax+Tmin)/2 aus DWD TXK/TNK, einheitlich zu allen anderen Ländern (nicht der offizielle DWD-TMK)."]
    return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, current, notes)


# ---- Frankreich (Météo-France)
def run_meteofrance(ctx: Ctx, res: SourceResult) -> SourceResult:
    cached = load_engine_cache(ctx, res.key)
    stations: Dict[str, Any] = dict(cached["stations"]) if cached else {}
    if cached:
        engines = cached["engines"]
    else:
        install_core_hooks()
        cache_file = ctx.adapters_dir / f"meteofrance_baseline_through_{ctx.cutoff}_core{core.MF_BASELINE_FORMAT_VERSION}_h{HOOK_VERSION}.pkl.gz"
        base = core.load_or_build_mf_baseline(cache_file, ctx.cutoff, ctx.forced(res.key), max(1, ctx.workers))
        stations = dict(base.get("stations", {}))
        engines = _engines_from_holders("Météo-France", base["states"], lambda raw: raw)
        save_engine_cache(ctx, res.key, engines, stations, [])
    if ctx.baseline_only:
        return _finish(res, ctx, engines, stations, {}, [])
    current, cur_stations = core.parse_current_mf_year(ctx.year, workers=max(4, ctx.workers))
    if not current:
        raise RuntimeError(f"Keine aktuellen Météo-France-Daten für {ctx.year}.")
    stations.update(cur_stations)
    return _finish(res, ctx, engines, stations, current, [])


# ---- Rest-Europa (GHCN-Daily)
def ghcn_rest_stations(all_stations: Dict[str, Any]) -> Dict[str, Any]:
    return {sid: meta for sid, meta in all_stations.items() if meta.country_code not in GHCN_EXCLUDED_CODES}


def run_ghcn_rest(ctx: Ctx, res: SourceResult) -> SourceResult:
    stations = ghcn_rest_stations(ctx.ghcn_all())
    if not stations:
        raise RuntimeError("Keine GHCN-Stationen für Rest-Europa gefunden.")
    cached = load_engine_cache(ctx, res.key)
    if cached:
        engines = cached["engines"]
    else:
        install_core_hooks()
        cache_file = ctx.adapters_dir / f"ghcn_rest_baseline_through_{ctx.cutoff}_core{core.GHCN_BASELINE_FORMAT_VERSION}_h{HOOK_VERSION}.pkl.gz"
        base = core.load_or_build_ghcn_baseline(cache_file, stations, ctx.cutoff, ctx.forced(res.key))
        states = {sid: st for sid, st in base["states"].items() if sid in stations}
        engines = _engines_from_holders("GHCN", states, lambda raw: raw)
        save_engine_cache(ctx, res.key, engines, {}, [])
    if ctx.baseline_only:
        return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, {}, [])
    current = core.parse_current_ghcn_year(ctx.year, stations)
    notes = ["Enthält derzeit auch GB, RO, PT, LU (Stufe C ersetzt diese später durch nationale Quellen)."]
    return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, current, notes)


# ---- Tschechien (CHMI; der vorhandene Cache enthält die vollständigen Tagesreihen)
def run_chmi(ctx: Ctx, res: SourceResult) -> SourceResult:
    allsrc = _allsrc()
    chmi_hist = allsrc.chmi_hist
    chmi_cur = allsrc.chmi_current_mod
    cached = load_engine_cache(ctx, res.key)
    if cached:
        stations = dict(cached["stations"])
        engines = cached["engines"]
    else:
        if ctx.chmi_cache_dir:
            # Fremdes Verzeichnis (Cache des bestehenden Workflows): nur lesen, nie bauen oder erzwingen.
            base = chmi_hist.load_baseline(Path(ctx.chmi_cache_dir), ctx.cutoff)
        else:
            chmi_hist.build_baseline(ctx.adapters_dir, ctx.cutoff, force=ctx.forced(res.key), workers=max(1, ctx.workers))
            base = chmi_hist.load_baseline(ctx.adapters_dir, ctx.cutoff)
        stations = allsrc.chmi_inventory_to_meta(allsrc.chmi_payload_inventory(base))
        missing = int(getattr(chmi_hist, "MISSING_I16", -32768))
        engines = {}
        rec_count = 0
        for raw_id, record in base.get("stations", {}).items():
            if not isinstance(record, dict):
                continue
            rec_count += 1
            ser = series_from_chmi_packed(record, missing)
            final = ser.to_final() if ser is not None else None
            if final is not None:
                engines[f"CHMI:{raw_id}"] = final
        _check_capture("CHMI", rec_count, len(engines))
        save_engine_cache(ctx, res.key, engines, stations, [])
    if ctx.baseline_only:
        return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, {}, [])
    chmi_cur.build_current(ctx.adapters_dir, ctx.year, workers=max(1, ctx.workers))
    cur_payload = chmi_cur.load_current(ctx.adapters_dir, ctx.year)
    stations.update(allsrc.chmi_inventory_to_meta(allsrc.chmi_payload_inventory({}, cur_payload)))
    current = allsrc.chmi_packed_to_core_current(cur_payload.get("stations", {}))
    if not current:
        raise RuntimeError(f"CHMI lieferte für {ctx.year} keine aktuellen Stationsdaten.")
    return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, current, [])


# ---- Österreich (GeoSphere Austria)
def run_geosphere(ctx: Ctx, res: SourceResult) -> SourceResult:
    austria = _import("update_geosphere_austria_station_cache")
    cached = load_engine_cache(ctx, res.key)
    if cached:
        stations = dict(cached["stations"])
        engines = cached["engines"]
    else:
        install_austria_hooks(austria)
        base = austria.load_or_build_baseline(ctx.adapters_dir, ctx.cutoff, force=ctx.forced(res.key))
        stations = dict(base.get("stations", {}))
        engines = _engines_from_holders("GeoSphere Austria", base["states"], lambda raw: raw)
        save_engine_cache(ctx, res.key, engines, stations, [])
    if ctx.baseline_only:
        return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, {}, [])
    current = austria.parse_current_year(ctx.year, stations)
    if not current:
        raise RuntimeError(f"GeoSphere Austria lieferte für {ctx.year} keine aktuellen Stationsdaten.")
    return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, current, [])


# ---- Polen (IMGW-PIB)
def run_imgw(ctx: Ctx, res: SourceResult) -> SourceResult:
    poland = _import("update_imgw_poland_station_cache")
    cached = load_engine_cache(ctx, res.key)
    if cached:
        stations = dict(cached["stations"])
        engines = cached["engines"]
    else:
        install_poland_hooks(poland)
        path = poland.baseline_path(ctx.adapters_dir, ctx.cutoff)
        if ctx.forced(res.key) or not path.exists():
            poland.build_baseline(current_year=ctx.year, cache_dir=ctx.adapters_dir, workers=max(1, ctx.workers),
                                  force=ctx.forced(res.key))
        if not path.exists():
            detail = ""
            status = ctx.adapters_dir / f"imgw_poland_status_through_{ctx.cutoff}.json"
            if status.exists():
                try:
                    s = json.loads(status.read_text(encoding="utf-8"))
                    detail = f" ({s.get('available', 0)}/{s.get('resource_count', 0)} Ressourcen verfügbar, {s.get('missing', 0)} fehlen)"
                except Exception:
                    pass
            raise BaselineIncomplete(f"IMGW-Polen-Baseline unvollständig{detail}; nächster Lauf setzt fort.")
        base = poland.load_baseline(ctx.adapters_dir, ctx.cutoff)
        stations = dict(base.get("stations", {}))
        engines = _engines_from_holders("IMGW Polen", base["states"], lambda raw: raw)
        save_engine_cache(ctx, res.key, engines, stations, [])
    if ctx.baseline_only:
        return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, {}, [])
    current, latest_month = poland.parse_current_year(ctx.year, stations, workers=max(4, ctx.workers))
    if not current:
        raise RuntimeError(f"IMGW lieferte für {ctx.year} keine aktuellen Stationsdaten.")
    notes = [f"IMGW veröffentlicht Tageswerte monatsweise; aktuell bis Monat {latest_month:02d}."] if latest_month else []
    return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, current, notes)


# ---- Spanien (AEMET OpenData)
def run_aemet(ctx: Ctx, res: SourceResult) -> SourceResult:
    api_key = os.environ.get("AEMET_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("AEMET_API_KEY fehlt.")
    aemet = _import("update_aemet_spain_station_cache")
    cur_mod = _import("update_aemet_spain_current")
    allsrc = _allsrc()
    cached = load_engine_cache(ctx, res.key)
    if cached:
        stations = dict(cached["stations"])
        engines = cached["engines"]
        inventory = {}
    else:
        install_aemet_hooks(aemet)
        progress = aemet.build_baseline(api_key=api_key, cutoff_year=ctx.cutoff, cache_dir=ctx.adapters_dir,
                                        force=ctx.forced(res.key), max_runtime_minutes=ctx.max_runtime_minutes)
        if not progress.get("complete"):
            raise BaselineIncomplete("AEMET-Baseline im Aufbau: " + (_status_summary(aemet, ctx) or "Fortschritt gespeichert")
                                     + "; nächster Lauf setzt fort.")
        base = aemet.load_baseline(ctx.adapters_dir, ctx.cutoff)
        inventory = dict(base.get("inventory", {}))
        stations = allsrc.aemet_inventory_to_meta(inventory)
        engines = _engines_from_holders("AEMET", base["records"], lambda raw: f"AEMET:{raw}")
        save_engine_cache(ctx, res.key, engines, stations, [])
    if ctx.baseline_only:
        return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, {}, [])
    cur_path = cur_mod.build_current(api_key=api_key, year=ctx.year, cache_dir=ctx.adapters_dir)
    cur_payload = aemet._load_pickle_gz(cur_path)
    inventory = dict(inventory)
    inventory.update(cur_payload.get("inventory", {}))
    stations.update(allsrc.aemet_inventory_to_meta(inventory))
    current = allsrc.compact_records_to_core_current(cur_payload.get("records", {}), prefix="AEMET")
    if not current:
        raise RuntimeError(f"AEMET lieferte für {ctx.year} keine aktuellen Stationsdaten.")
    return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, current, [])


# ---- Niederlande (KNMI)
def run_knmi(ctx: Ctx, res: SourceResult) -> SourceResult:
    knmi = _import("update_knmi_netherlands_station_cache")
    cur_mod = _import("update_knmi_netherlands_current")
    allsrc = _allsrc()
    ghcn_nl = {sid: m for sid, m in ctx.ghcn_all().items() if m.country_code == "NL"}
    cached = load_engine_cache(ctx, res.key)
    inventory: dict = {}
    record_ids: set = set()
    if cached:
        stations = dict(cached["stations"])
        engines = cached["engines"]
    else:
        install_knmi_hooks(knmi)
        path = knmi.build_baseline(ctx.adapters_dir, ctx.cutoff, force=ctx.forced(res.key),
                                   max_runtime_minutes=ctx.max_runtime_minutes)
        if not knmi.valid_final_baseline(path, ctx.cutoff):
            raise BaselineIncomplete("KNMI-Baseline im Aufbau: " + (_status_summary(knmi, ctx) or "Fortschritt gespeichert")
                                     + "; nächster Lauf setzt fort.")
        base = knmi.load_pickle_gzip(path)
        inventory = dict(base.get("inventory", {}))
        record_ids = set(str(x) for x in base.get("records", {}))
        stations = allsrc.knmi_inventory_to_meta(inventory, record_ids=record_ids, ghcn_nl_stations=ghcn_nl)
        engines = _engines_from_holders("KNMI", base["records"], lambda raw: f"KNMI:{raw}")
        save_engine_cache(ctx, res.key, engines, stations, [])
    if ctx.baseline_only:
        return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, {}, [])
    cur_path = cur_mod.build_current(ctx.adapters_dir, ctx.year)
    cur_payload = knmi.load_pickle_gzip(cur_path)
    inventory.update(cur_payload.get("inventory", {}))
    record_ids.update(str(x) for x in cur_payload.get("records", {}))
    stations.update(allsrc.knmi_inventory_to_meta(inventory, record_ids=record_ids, ghcn_nl_stations=ghcn_nl))
    current = allsrc.compact_records_to_core_current(cur_payload.get("records", {}), prefix="KNMI")
    if not current:
        raise RuntimeError(f"KNMI lieferte für {ctx.year} keine aktuellen Stationsdaten.")
    return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, current, [])


# ---- Belgien (KMI/RMI; Uccle = GHCN-Brücke vor 2000, übrige = SYNOP 1952-1999, ab 2000 AWS)
def run_belgium(ctx: Ctx, res: SourceResult) -> SourceResult:
    belgium = _import("update_rmi_belgium_station_cache")
    cur_mod = _import("update_rmi_belgium_current")
    allsrc = _allsrc()
    uccle = str(getattr(belgium, "UCCLE_CODE", BELGIUM_UCCLE_CODE))
    cached = load_engine_cache(ctx, res.key)
    inventory: dict = {}
    if cached:
        stations = dict(cached["stations"])
        engines = cached["engines"]
    else:
        install_belgium_hooks(belgium)
        path = belgium.build_baseline(ctx.adapters_dir, ctx.cutoff, force=ctx.forced(res.key),
                                      max_runtime_minutes=ctx.max_runtime_minutes)
        if not belgium.valid_final(path, ctx.cutoff):
            raise BaselineIncomplete("KMI/RMI-Baseline im Aufbau: " + (_status_summary(belgium, ctx) or "Fortschritt gespeichert")
                                     + "; nächster Lauf setzt fort.")
        base = belgium.load_baseline(ctx.adapters_dir, ctx.cutoff)
        inventory = dict(base.get("inventory", {}))
        stations = allsrc.belgium_inventory_to_meta(inventory)
        engines = _engines_from_holders(
            "KMI/RMI", base["records"], lambda raw: f"RMI:{raw}",
            normals_from=lambda raw: None if str(raw) == uccle else BELGIUM_NORMALS_FROM_YEAR)
        save_engine_cache(ctx, res.key, engines, stations, [])
    if ctx.baseline_only:
        return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, {}, [])
    cur_path = cur_mod.build_current(ctx.adapters_dir, ctx.year)
    cur_payload = belgium.load_pickle_gzip(cur_path)
    inventory.update(cur_payload.get("inventory", {}))
    stations.update(allsrc.belgium_inventory_to_meta(inventory))
    current = allsrc.compact_records_to_core_current(cur_payload.get("records", {}), prefix="RMI")
    if not current:
        raise RuntimeError(f"KMI/RMI lieferte für {ctx.year} keine aktuellen Stationsdaten.")
    notes = [f"Klimamittel: Außer Uccle nur aus AWS-Daten ab {BELGIUM_NORMALS_FROM_YEAR} (die SYNOP-Fenstermaxima/-minima "
             "1952-1999 sind nicht homogen zu AWS). Rekorde und Messjahre nutzen wie bisher alle Jahre."]
    return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, current, notes)


# ---- Schweiz (MeteoSwiss SwissMetNet)
def run_meteoswiss(ctx: Ctx, res: SourceResult) -> SourceResult:
    swiss = _import("update_meteoswiss_switzerland_station_cache")
    cur_mod = _import("update_meteoswiss_switzerland_current")
    allsrc = _allsrc()
    cached = load_engine_cache(ctx, res.key)
    inventory: dict = {}
    if cached:
        stations = dict(cached["stations"])
        engines = cached["engines"]
    else:
        install_swiss_hooks(swiss)
        path = swiss.build_baseline(ctx.adapters_dir, ctx.cutoff, force=ctx.forced(res.key),
                                    max_runtime_minutes=ctx.max_runtime_minutes)
        if not swiss.valid_final(path, ctx.cutoff):
            raise BaselineIncomplete("MeteoSwiss-Baseline im Aufbau: " + (_status_summary(swiss, ctx) or "Fortschritt gespeichert")
                                     + "; nächster Lauf setzt fort.")
        base = swiss.load_baseline(ctx.adapters_dir, ctx.cutoff)
        inventory = dict(base.get("inventory", {}))
        stations = allsrc.swiss_inventory_to_meta(inventory)
        if not any(f"METEOSWISS:{raw}" in stations for raw in base.get("records", {})):
            inventory.update(swiss.load_station_metadata())
            stations = allsrc.swiss_inventory_to_meta(inventory)
        engines = _engines_from_holders("MeteoSwiss", base["records"], lambda raw: f"METEOSWISS:{raw}")
        save_engine_cache(ctx, res.key, engines, stations, [])
    if ctx.baseline_only:
        return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, {}, [])
    cur_path = cur_mod.build_current(ctx.adapters_dir, ctx.year)
    cur_payload = swiss.load_pickle_gzip(cur_path)
    inventory.update(cur_payload.get("inventory", {}))
    stations.update(allsrc.swiss_inventory_to_meta(inventory))
    current = allsrc.compact_records_to_core_current(cur_payload.get("records", {}), prefix="METEOSWISS")
    if not current:
        raise RuntimeError(f"MeteoSwiss lieferte für {ctx.year} keine aktuellen Stationsdaten.")
    return _finish(res, ctx, {s: e for s, e in engines.items() if s in stations}, stations, current, [])


# =========================================================================== Registry
@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    stage: str
    countries: Tuple[str, ...]
    run: Optional[Callable[[Ctx, SourceResult], SourceResult]] = None


SPECS: Tuple[Spec, ...] = (
    Spec("dwd_de", "DWD CDC Deutschland", "A", ("DE",), run_dwd),
    Spec("meteofrance_fr", "Météo-France Frankreich", "A", ("FR",), run_meteofrance),
    Spec("chmi_cz", "ČHMÚ Tschechien", "A", ("CZ",), run_chmi),
    Spec("ghcn_rest", "GHCN-Daily Rest-Europa", "A", ("*",), run_ghcn_rest),
    Spec("geosphere_at", "GeoSphere Austria", "B1", ("AT",), run_geosphere),
    Spec("imgw_pl", "IMGW-PIB Polen", "B1", ("PL",), run_imgw),
    Spec("meteoswiss_ch", "MeteoSwiss Schweiz", "B2.1", ("CH",), run_meteoswiss),
    Spec("knmi_nl", "KNMI Niederlande", "B2.1", ("NL",), run_knmi),
    Spec("rmi_be", "KMI/RMI Belgien", "B2.1", ("BE",), run_belgium),
    Spec("aemet_es", "AEMET Spanien", "B2.1", ("ES",), run_aemet),
    # noch nicht angebunden: erscheinen als "fehlt, geplant" im Index (Adapter-Dateien fehlen noch)
    Spec("dmi_dk", "DMI Dänemark", "B2.2", ("DK",)),
    Spec("smhi_se", "SMHI Schweden", "B2.2", ("SE",)),
    Spec("frost_no", "MET Norway Frost", "B2.2", ("NO",)),
    Spec("fmi_fi", "FMI Finnland", "B2.2", ("FI",)),
    Spec("hungaromet_hu", "HungaroMet Ungarn", "B2.3", ("HU",)),
    Spec("meteireann_ie", "Met Éireann Irland", "B2.3", ("IE",)),
    Spec("ilmateenistus_ee", "Ilmateenistus Estland", "B2.3", ("EE",)),
    Spec("arso_si", "ARSO Slowenien", "B2.3", ("SI",)),
)
SPEC_BY_KEY = {s.key: s for s in SPECS}
STAGE_ORDER = ("A", "B1", "B2.1", "B2.2", "B2.3", "C")
DEFAULT_STAGES = ("A", "B1", "B2.1")


def select_specs(selection: Optional[Iterable[str]]) -> List[Spec]:
    """Auswahl nach Stufen (A, B1, B2.1 …) oder Quellenschlüsseln; Standard = A, B1, B2.1."""
    wanted = list(selection) if selection else list(DEFAULT_STAGES)
    out: List[Spec] = []
    for token in wanted:
        token = token.strip()
        if token in STAGE_ORDER:
            out.extend(s for s in SPECS if s.stage == token)
        elif token in SPEC_BY_KEY:
            out.append(SPEC_BY_KEY[token])
        elif token == "all":
            out.extend(SPECS)
        else:
            raise ValueError(f"Unbekannte Quelle/Stufe: {token}")
    seen, ordered = set(), []
    for s in out:
        if s.key not in seen:
            seen.add(s.key)
            ordered.append(s)
    return ordered


def classify_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if isinstance(exc, BaselineIncomplete) or "unvollständig" in text or "setzt fort" in text:
        return "building"
    return "failed"


def run_sources(ctx: Ctx, specs: List[Spec]) -> List[SourceResult]:
    """Alle bekannten Quellen. Ausgewählte werden ausgeführt; Fehler eines Landes stoppen die anderen nicht.
    Nicht ausgewählte oder noch nicht angebundene Quellen bleiben als 'planned' sichtbar (fehlt, nicht ersetzt)."""
    chosen = {s.key for s in specs}
    results: List[SourceResult] = []
    for spec in SPECS:
        res = SourceResult(spec.key, spec.label, spec.stage, spec.countries)
        if spec.key not in chosen:
            res.status = "planned"
            res.message = "noch nicht angebunden" if spec.run is None else "in diesem Lauf nicht ausgewählt"
        elif spec.run is None:
            res.status = "planned"
            res.message = "Adapter noch nicht angebunden (geplant)"
        else:
            started = time.monotonic()
            ctx.log(f"=== {spec.label} ({spec.stage}) ===")
            try:
                res = spec.run(ctx, res)
            except Exception as exc:                                  # bewusst breit: ein Land darf die anderen nicht stoppen
                res.status = classify_error(exc)
                res.message = f"{type(exc).__name__}: {exc}"
                res.stations, res.engines, res.current = {}, {}, {}
                ctx.log(f"{spec.label}: {res.status.upper()} – {res.message}")
            ctx.log(f"{spec.label}: {res.status} ({time.monotonic() - started:.0f} s) {res.message}")
        results.append(res)
    return results
