#!/usr/bin/env python3
"""Build a resumable GeoSphere Austria daily-station cache for the Europe dashboard.

Official source
---------------
GeoSphere Austria Dataset API, resource ``klima-v2-1d`` (quality-checked daily
station data). We use the daily maximum/minimum air-temperature parameters and
store exactly the compact record state used by the existing Europe frontend.

The API limits JSON/CSV requests to 1,000,000 values and 240 requests/hour.
Therefore the historical build is split into dynamic multi-year blocks. Every
successful block is cached immediately, so a later run only requests missing
blocks. The final baseline covers everything through ``current_year - 1``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import pickle
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import update_europe_station_records as core

API_BASE = "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1d"
PUBLIC_URL = "https://data.hub.geosphere.at/de/dataset/klima-v2-1d"
SOURCE = "GeoSphere Austria"
RESOURCE_ID = "klima-v2-1d"
BASELINE_FORMAT_VERSION = 2
BLOCK_FORMAT_VERSION = 2
# Stay comfortably below the official 1,000,000-value JSON/CSV request limit.
REQUEST_VALUE_BUDGET = 850_000
MAX_BLOCK_YEARS = 15
# 5 req/s official limit; this keeps sequential requests well below it.
MIN_REQUEST_SPACING_SECONDS = 0.35


class RateGate:
    def __init__(self, spacing: float = MIN_REQUEST_SPACING_SECONDS):
        self.spacing = spacing
        self.last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delay = self.spacing - (now - self.last)
        if delay > 0:
            time.sleep(delay)
        self.last = time.monotonic()


RATE_GATE = RateGate()



def update_opposite_record(record, value: int, date_int: int, element: str):
    """Lowest TMAX / highest TMIN with earliest date retained on ties."""
    better = record is None or (value < record[0] if element == "TMAX" else value > record[0])
    if better:
        return (value, date_int, 1)
    if value == record[0]:
        return (record[0], min(int(record[1]), int(date_int)), int(record[2]) + 1)
    return record


def merge_opposite_records(a, b, element: str):
    if a is None:
        return b
    if b is None:
        return a
    if (b[0] < a[0] if element == "TMAX" else b[0] > a[0]):
        return b
    if (a[0] < b[0] if element == "TMAX" else a[0] > b[0]):
        return a
    return (a[0], min(int(a[1]), int(b[1])), int(a[2]) + int(b[2]))


def merge_partial_states(target: dict, incoming: dict) -> None:
    for sid, src_state in incoming.items():
        dst_state = target.setdefault(sid, core.mf_empty_partial_state())
        for element in ("TMAX", "TMIN"):
            src = src_state[element]
            dst = dst_state[element]
            dst["abs"] = core.merge_record_tuples(dst.get("abs"), src.get("abs"), element)
            dst["opposite_abs"] = merge_opposite_records(
                dst.get("opposite_abs"), src.get("opposite_abs"), element
            )
            for mmdd, rec in src.get("cal", {}).items():
                dst["cal"][mmdd] = core.merge_record_tuples(dst["cal"].get(mmdd), rec, element)
            starts = [x for x in (dst.get("start"), src.get("start")) if x is not None]
            dst["start"] = min(starts) if starts else None
            ends = [x for x in (dst.get("end"), src.get("end")) if x is not None]
            dst["end"] = max(ends) if ends else None
            dst.setdefault("year_set", set()).update(src.get("year_set", set()))


def finalize_partial_states(partial: dict) -> dict:
    out = {}
    for sid, state in partial.items():
        dst = core.empty_state()
        for element in ("TMAX", "TMIN"):
            src = state[element]
            dst[element]["abs"] = src.get("abs")
            dst[element]["opposite_abs"] = src.get("opposite_abs")
            dst[element]["cal"] = src.get("cal", {})
            dst[element]["start"] = src.get("start")
            dst[element]["end"] = src.get("end")
            dst[element]["years"] = len(src.get("year_set", set()))
        out[sid] = dst
    return out

def log(msg: str) -> None:
    print(msg, flush=True)


def api_json(url: str, attempts: int = 5, timeout: int = 180) -> dict:
    last = None
    for attempt in range(1, attempts + 1):
        RATE_GATE.wait()
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "climate-dashboard-austria/1.0 (+GitHub Actions)",
                    "Accept": "application/json, application/geo+json;q=0.9, */*;q=0.1",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 429 and attempt < attempts:
                # GeoSphere publishes hourly/second limits; if 429 is hit, give it room.
                retry_after = exc.headers.get("Retry-After")
                try:
                    wait = max(10, int(retry_after)) if retry_after else min(60 * attempt, 180)
                except ValueError:
                    wait = min(60 * attempt, 180)
                log(f"GeoSphere HTTP 429; neuer Versuch {attempt + 1}/{attempts} in {wait}s …")
                time.sleep(wait)
                continue
            if 500 <= exc.code < 600 and attempt < attempts:
                wait = min(10 * attempt, 45)
                log(f"GeoSphere HTTP {exc.code}; neuer Versuch {attempt + 1}/{attempts} in {wait}s …")
                time.sleep(wait)
                continue
            raise RuntimeError(f"GeoSphere HTTP {exc.code}: {url}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < attempts:
                wait = min(10 * attempt, 45)
                log(f"GeoSphere-Verbindungsfehler; neuer Versuch {attempt + 1}/{attempts} in {wait}s …")
                time.sleep(wait)
                continue
            break
    raise RuntimeError(f"GeoSphere-Anfrage fehlgeschlagen: {url}: {last}")


def metadata() -> dict:
    payload = api_json(API_BASE + "/metadata", attempts=5, timeout=180)
    if not isinstance(payload, dict):
        raise RuntimeError("GeoSphere-Metadaten sind kein JSON-Objekt.")
    return payload


def _first(mapping: dict, names: Iterable[str], default=None):
    low = {str(k).lower(): v for k, v in mapping.items()}
    for name in names:
        if name.lower() in low and low[name.lower()] not in (None, ""):
            return low[name.lower()]
    return default


def _date_year(value, default: int) -> int:
    if value in (None, ""):
        return default
    text = str(value)
    m = re.search(r"(17|18|19|20|21)\d{2}", text)
    return int(m.group(0)) if m else default


def _as_float(value) -> Optional[float]:
    try:
        x = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def discover_parameters(md: dict) -> Tuple[str, str]:
    params = md.get("parameters") or []
    if isinstance(params, dict):
        params = list(params.values())
    rows = [p for p in params if isinstance(p, dict)]
    names = {str(_first(p, ["name", "id", "parameter"], "")): p for p in rows}
    # Current official v2 names. Keep semantic fallback so a metadata wording change
    # yields a useful result instead of silently using a wrong variable.
    tmax = next((n for n in names if n.lower() == "tlmax"), None)
    tmin = next((n for n in names if n.lower() == "tlmin"), None)
    if not tmax:
        for name, p in names.items():
            hay = " ".join(str(_first(p, [k], "")) for k in ["name", "long_name", "description"]).lower()
            if "temperatur" in hay and ("max" in hay or "maximum" in hay or "maximal" in hay):
                tmax = name; break
    if not tmin:
        for name, p in names.items():
            hay = " ".join(str(_first(p, [k], "")) for k in ["name", "long_name", "description"]).lower()
            if "temperatur" in hay and ("min" in hay or "minimum" in hay or "minimal" in hay):
                tmin = name; break
    if not tmax or not tmin:
        sample = sorted(names)[:60]
        raise RuntimeError(f"GeoSphere-Parameter tlmax/tlmin nicht gefunden. Verfügbare Namen (Auszug): {sample}")
    return tmax, tmin


def _station_rows(md: dict) -> List[dict]:
    for key in ("stations", "station", "station_metadata"):
        value = md.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            # Sometimes metadata collections are keyed by station id.
            out = []
            for sid, row in value.items():
                if isinstance(row, dict):
                    item = dict(row); item.setdefault("id", sid); out.append(item)
            if out:
                return out
    raise RuntimeError(f"GeoSphere-Metadaten enthalten keine erkennbare Stationsliste. Keys: {sorted(md)[:40]}")


def normalize_raw_station_id(value) -> str:
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def parse_stations(md: dict, cutoff_year: int) -> Tuple[Dict[str, core.StationMeta], Dict[str, Tuple[int, int]], Dict[str, str]]:
    stations: Dict[str, core.StationMeta] = {}
    availability: Dict[str, Tuple[int, int]] = {}
    raw_ids: Dict[str, str] = {}
    rows = _station_rows(md)
    for row in rows:
        raw_id = _first(row, ["id", "station_id", "station", "nr", "number"])
        if raw_id in (None, ""):
            continue
        raw_id = normalize_raw_station_id(raw_id)
        sid = f"GSA:{raw_id}"
        name = str(_first(row, ["name", "station_name", "bezeichnung"], raw_id)).strip()
        lat = _as_float(_first(row, ["lat", "latitude", "breite", "geo_latitude"]))
        lon = _as_float(_first(row, ["lon", "longitude", "laenge", "geo_longitude"]))
        elev = _as_float(_first(row, ["altitude", "elevation", "height", "hoehe", "station_height"]))
        if lat is None or lon is None:
            # Some metadata variants may place geometry in a GeoJSON-like field.
            geom = row.get("geometry")
            if isinstance(geom, dict):
                coords = geom.get("coordinates")
                if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    lon = _as_float(coords[0]); lat = _as_float(coords[1])
        if lat is None or lon is None:
            continue
        start_year = _date_year(_first(row, ["start", "start_date", "start_time", "von", "valid_from"]), 1775)
        end_year = _date_year(_first(row, ["end", "end_date", "end_time", "bis", "valid_to"]), cutoff_year)
        start_year = max(1700, min(start_year, cutoff_year))
        end_year = max(start_year, min(end_year, cutoff_year))
        state = str(_first(row, ["state", "bundesland", "region"], "")).strip()
        quality = "GeoSphere Austria klima-v2-1d: qualitätsgeprüfte tägliche Stationsdaten; tlmax/tlmin wie veröffentlicht."
        if state:
            quality += f" Bundesland: {state}."
        stations[sid] = core.StationMeta(
            sid, float(lat), float(lon), None if elev is None else round(elev, 1),
            name, "AU", "Österreich", SOURCE, quality,
        )
        availability[sid] = (start_year, end_year)
        raw_ids[sid] = raw_id
    if not stations:
        sample_keys = sorted(rows[0]) if rows else []
        raise RuntimeError(f"Keine GeoSphere-Stationen aus Metadaten gelesen. Erste Stations-Keys: {sample_keys}")
    return stations, availability, raw_ids


def days_inclusive(y1: int, y2: int) -> int:
    return (dt.date(y2, 12, 31) - dt.date(y1, 1, 1)).days + 1


def active_for_block(availability: Dict[str, Tuple[int, int]], y1: int, y2: int) -> List[str]:
    return [sid for sid, (s, e) in availability.items() if s <= y2 and e >= y1]


def plan_blocks(availability: Dict[str, Tuple[int, int]], cutoff_year: int, parameter_count: int = 2) -> List[Tuple[int, int, List[str]]]:
    first_year = min(s for s, _ in availability.values())
    y = first_year
    blocks: List[Tuple[int, int, List[str]]] = []
    while y <= cutoff_year:
        best = None
        upper = min(cutoff_year, y + MAX_BLOCK_YEARS - 1)
        for y2 in range(y, upper + 1):
            ids = active_for_block(availability, y, y2)
            if not ids:
                best = (y, y2, ids)
                continue
            values = parameter_count * days_inclusive(y, y2) * len(ids)
            if values <= REQUEST_VALUE_BUDGET:
                best = (y, y2, ids)
            else:
                break
        if best is None:
            # A single year must always fit for <=1140 daily stations and 2 params,
            # but keep a precise failure if the provider grows beyond that.
            ids = active_for_block(availability, y, y)
            values = parameter_count * days_inclusive(y, y) * len(ids)
            raise RuntimeError(
                f"GeoSphere Request-Plan kann Jahr {y} nicht unter {REQUEST_VALUE_BUDGET:,} Werte packen "
                f"({len(ids)} Stationen, {values:,} Werte)."
            )
        blocks.append(best)
        y = best[1] + 1
    return blocks


def block_key(y1: int, y2: int, station_ids: List[str]) -> str:
    digest = hashlib.sha1("\n".join(sorted(station_ids)).encode("utf-8")).hexdigest()[:10]
    return f"{y1:04d}_{y2:04d}_{len(station_ids):04d}_{digest}"


def query_url(raw_station_ids: List[str], pmax: str, pmin: str, y1: int, y2: int) -> str:
    query = urllib.parse.urlencode({
        "parameters": f"{pmax},{pmin}",
        "station_ids": ",".join(raw_station_ids),
        "start": f"{y1:04d}-01-01",
        "end": f"{y2:04d}-12-31",
    })
    return API_BASE + "?" + query


def temp_to_tenths(value) -> Optional[int]:
    x = _as_float(value)
    if x is None or x <= -90 or x >= 70:
        return None
    return int(round(x * 10.0))


def parse_timestamp(value) -> Optional[dt.date]:
    if value in (None, ""):
        return None
    text = str(value)
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def feature_station_raw_id(props: dict) -> Optional[str]:
    raw = _first(props, ["station", "station_id", "id", "stationId"])
    if isinstance(raw, dict):
        raw = _first(raw, ["id", "station_id", "station"])
    return None if raw in (None, "") else normalize_raw_station_id(raw)


def parse_feature_collection(payload: dict, pmax: str, pmin: str, cutoff_year: Optional[int] = None, exact_year: Optional[int] = None):
    timestamps = payload.get("timestamps") or payload.get("time") or []
    if not isinstance(timestamps, list):
        raise RuntimeError("GeoSphere-Datenantwort ohne Timestamp-Liste.")
    dates = [parse_timestamp(x) for x in timestamps]
    features = payload.get("features") or []
    if not isinstance(features, list):
        raise RuntimeError("GeoSphere-Datenantwort ohne Feature-Liste.")
    partial: Dict[str, dict] = {}
    current: Dict[str, dict] = {}
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties") if isinstance(feat.get("properties"), dict) else feat
        raw_id = feature_station_raw_id(props)
        if not raw_id:
            continue
        sid = f"GSA:{raw_id}"
        params = props.get("parameters") if isinstance(props.get("parameters"), dict) else {}
        for parameter_name, element in ((pmax, "TMAX"), (pmin, "TMIN")):
            block = params.get(parameter_name)
            if block is None:
                # API parameter keys may be normalized in case.
                for k, v in params.items():
                    if str(k).lower() == parameter_name.lower():
                        block = v; break
            if isinstance(block, dict):
                values = block.get("data") or block.get("values") or []
            elif isinstance(block, list):
                values = block
            else:
                values = []
            for date_obj, raw_value in zip(dates, values):
                if date_obj is None:
                    continue
                if exact_year is not None and date_obj.year != exact_year:
                    continue
                if cutoff_year is not None and date_obj.year > cutoff_year:
                    continue
                value = temp_to_tenths(raw_value)
                if value is None:
                    continue
                date_int = int(date_obj.strftime("%Y%m%d")); mmdd = date_obj.strftime("%m-%d")
                if exact_year is not None:
                    c = current.setdefault(sid, {"TMAX": {}, "TMIN": {}})
                    c[element][mmdd] = (value, date_int)
                else:
                    state = partial.setdefault(sid, core.mf_empty_partial_state())
                    b = state[element]
                    b["abs"] = core.update_record(b.get("abs"), value, date_int, element)
                    b["opposite_abs"] = update_opposite_record(b.get("opposite_abs"), value, date_int, element)
                    b["cal"][mmdd] = core.update_record(b["cal"].get(mmdd), value, date_int, element)
                    b["start"] = date_int if b.get("start") is None else min(b["start"], date_int)
                    b["end"] = date_int if b.get("end") is None else max(b["end"], date_int)
                    b.setdefault("year_set", set()).add(date_obj.year)
    return partial, current


def save_pickle_gz(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=5) as h:
        pickle.dump(payload, h, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def load_block(path: Path, cutoff_year: int) -> Optional[dict]:
    try:
        with gzip.open(path, "rb") as h:
            p = pickle.load(h)
        if p.get("format_version") != BLOCK_FORMAT_VERSION or p.get("cutoff_year") != cutoff_year:
            return None
        return p
    except Exception:
        return None


def build_baseline(cache_dir: Path, cutoff_year: int, force: bool = False) -> dict:
    md = metadata()
    pmax, pmin = discover_parameters(md)
    stations, availability, raw_ids = parse_stations(md, cutoff_year)
    blocks = plan_blocks(availability, cutoff_year)
    block_dir = cache_dir / f"geosphere_austria_blocks_through_{cutoff_year}_v{BLOCK_FORMAT_VERSION}"
    if force and block_dir.exists():
        import shutil
        shutil.rmtree(block_dir)
    block_dir.mkdir(parents=True, exist_ok=True)

    log(f"GeoSphere Austria Metadaten: {len(stations):,} Stationsreihen | Parameter {pmax}/{pmin}.")
    log(f"Historischer Plan bis {cutoff_year}: {len(blocks)} API-Blöcke unter {REQUEST_VALUE_BUDGET:,} Werten je Request.")
    if len(blocks) > 220:
        log("WARNUNG: Mehr als 220 geplante Requests; der Code respektiert 429/Retry, der Erstlauf kann dadurch länger dauern.")

    merged: Dict[str, dict] = {}
    from_cache = fresh = failed = 0
    failures = []
    for i, (y1, y2, ids) in enumerate(blocks, 1):
        if not ids:
            continue
        key = block_key(y1, y2, ids)
        path = block_dir / f"{key}.pkl.gz"
        cached = None if force else load_block(path, cutoff_year)
        if cached is not None:
            merge_partial_states(merged, cached.get("partial", {}))
            from_cache += 1
        else:
            raw = [raw_ids[sid] for sid in ids]
            values = 2 * days_inclusive(y1, y2) * len(ids)
            try:
                payload = api_json(query_url(raw, pmax, pmin, y1, y2), attempts=5, timeout=240)
                partial, _ = parse_feature_collection(payload, pmax, pmin, cutoff_year=cutoff_year)
                block_payload = {
                    "format_version": BLOCK_FORMAT_VERSION,
                    "cutoff_year": cutoff_year,
                    "years": [y1, y2],
                    "station_count_requested": len(ids),
                    "parameter_names": [pmax, pmin],
                    "partial": partial,
                }
                save_pickle_gz(path, block_payload)
                merge_partial_states(merged, partial)
                fresh += 1
            except Exception as exc:
                failed += 1
                failures.append({"years": [y1, y2], "stations": len(ids), "error": str(exc)})
                log(f"FEHLER GeoSphere Block {y1}–{y2}: {exc}")
        if i == 1 or i % 10 == 0 or i == len(blocks):
            log(
                f"  GeoSphere historical: {i}/{len(blocks)} Blöcke | Cache {from_cache} | neu {fresh} | "
                f"fehlerhaft {failed} | {len(merged):,} Stationen mit TMAX/TMIN …"
            )

    report = cache_dir / f"geosphere_austria_failed_blocks_through_{cutoff_year}.json"
    report.write_text(json.dumps({
        "cutoff_year": cutoff_year,
        "planned_blocks": len(blocks),
        "failed_blocks": failures,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        raise RuntimeError(
            f"GeoSphere Austria Baseline noch unvollständig: {len(failures)} von {len(blocks)} Blöcken fehlgeschlagen. "
            "Erfolgreiche Blöcke sind einzeln gecacht; force=false setzt beim nächsten Lauf fort."
        )

    states = finalize_partial_states(merged)
    stations = {sid: meta for sid, meta in stations.items() if sid in states}
    if not states:
        raise RuntimeError("GeoSphere Austria Baseline enthält keine TMAX/TMIN-Daten.")
    return {
        "format_version": BASELINE_FORMAT_VERSION,
        "cutoff_year": cutoff_year,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "resource_id": RESOURCE_ID,
        "parameter_names": [pmax, pmin],
        "states": states,
        "stations": stations,
        "block_count": len(blocks),
    }


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"geosphere_austria_daily_baseline_through_{cutoff_year}_v{BASELINE_FORMAT_VERSION}.pkl.gz"


def load_or_build_baseline(cache_dir: Path, cutoff_year: int, force: bool = False) -> dict:
    path = baseline_path(cache_dir, cutoff_year)
    if path.exists() and not force:
        try:
            with gzip.open(path, "rb") as h:
                p = pickle.load(h)
            if p.get("format_version") == BASELINE_FORMAT_VERSION and p.get("cutoff_year") == cutoff_year and p.get("states"):
                log(f"Verwende GeoSphere-Austria-Baseline: {path}")
                return p
        except Exception as exc:
            log(f"GeoSphere-Austria-Gesamtcache unlesbar ({exc}); Blockcaches werden verwendet.")
    payload = build_baseline(cache_dir, cutoff_year, force=force)
    save_pickle_gz(path, payload)
    log(f"GeoSphere-Austria-Gesamtcache gespeichert: {path} ({path.stat().st_size/1024/1024:.1f} MB)")
    return payload


def load_baseline(cache_dir: Path, cutoff_year: int) -> dict:
    path = baseline_path(cache_dir, cutoff_year)
    if not path.exists():
        raise RuntimeError(f"GeoSphere-Austria-Cache fehlt: {path}")
    with gzip.open(path, "rb") as h:
        p = pickle.load(h)
    if p.get("format_version") != BASELINE_FORMAT_VERSION or p.get("cutoff_year") != cutoff_year or not p.get("states"):
        raise RuntimeError("GeoSphere-Austria-Cache hat ein unerwartetes Format oder ist leer.")
    return p


def parse_current_year(year: int, stations: Dict[str, core.StationMeta]) -> dict:
    md = metadata()
    pmax, pmin = discover_parameters(md)
    _all_stations, availability, raw_ids = parse_stations(md, year)
    ids = [sid for sid in stations if sid in raw_ids and availability.get(sid, (year, year))[0] <= year <= availability.get(sid, (year, year))[1]]
    if not ids:
        return {}
    # A full year with all 1140 stations and two parameters remains below the
    # official 1,000,000-value limit; split only if the network grows.
    max_ids = max(1, REQUEST_VALUE_BUDGET // (2 * days_inclusive(year, year)))
    current: Dict[str, dict] = {}
    chunks = [ids[i:i+max_ids] for i in range(0, len(ids), max_ids)]
    log(f"Lade GeoSphere Austria {year}: {len(ids):,} Stationsreihen in {len(chunks)} API-Request(s) …")
    for i, chunk in enumerate(chunks, 1):
        raw = [raw_ids[sid] for sid in chunk]
        payload = api_json(query_url(raw, pmax, pmin, year, year), attempts=5, timeout=240)
        _partial, got = parse_feature_collection(payload, pmax, pmin, exact_year=year)
        current.update(got)
        log(f"  GeoSphere {year}: Request {i}/{len(chunks)} | {len(current):,} Stationen mit TMAX/TMIN …")
    return current


def self_test() -> None:
    md = {
        "parameters": [
            {"name": "tlmax", "long_name": "Lufttemperatur 2m Maximalwert"},
            {"name": "tlmin", "long_name": "Lufttemperatur 2m Minimalwert"},
        ],
        "stations": [
            {"id": 1, "name": "TEST", "lat": 48.2, "lon": 16.3, "altitude": 200, "start": "1900-01-01", "end": "2100-12-31"}
        ],
    }
    assert discover_parameters(md) == ("tlmax", "tlmin")
    stations, av, raw = parse_stations(md, 2025)
    assert "GSA:1" in stations and av["GSA:1"] == (1900, 2025) and raw["GSA:1"] == "1"
    blocks = plan_blocks(av, 2025)
    assert blocks and blocks[-1][1] == 2025
    payload = {
        "timestamps": ["2025-07-01T00:00+02:00", "2025-07-02T00:00+02:00"],
        "features": [{
            "properties": {
                "station": 1,
                "parameters": {
                    "tlmax": {"data": [31.2, 32.4]},
                    "tlmin": {"data": [18.1, 19.0]},
                },
            }
        }],
    }
    partial, current = parse_feature_collection(payload, "tlmax", "tlmin", cutoff_year=2025)
    assert not current and partial["GSA:1"]["TMAX"]["abs"][0] == 324
    final = finalize_partial_states(partial)
    assert final["GSA:1"]["TMAX"]["years"] == 1
    _p, cur = parse_feature_collection(payload, "tlmax", "tlmin", exact_year=2025)
    assert cur["GSA:1"]["TMIN"]["07-02"][0] == 190
    print("GeoSphere Austria self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--cache-dir", default=".cache/europe-stations")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    cutoff = args.year - 1
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    log("=== GEOSPHERE AUSTRIA ONLY BASELINE ===")
    log("Quelle: GeoSphere Austria klima-v2-1d; nur Österreich, keine anderen Länder werden bearbeitet.")
    status_path = cache_dir / f"geosphere_austria_status_through_{cutoff}.json"
    try:
        payload = load_or_build_baseline(cache_dir, cutoff, force=args.force)
    except Exception as exc:
        status_path.write_text(json.dumps({
            "complete": False, "cutoff_year": cutoff, "error": str(exc),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"GEOSPHERE AUSTRIA ZWISCHENSTAND: {exc}")
        log("Erfolgreiche Blockcaches bleiben erhalten. Der Workflow speichert sie jetzt; nächster Lauf mit force=false setzt fort.")
        return 0
    status_path.write_text(json.dumps({
        "complete": True, "cutoff_year": cutoff,
        "station_count": len(payload.get("states", {})),
        "block_count": payload.get("block_count"),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log(
        f"GEOSPHERE AUSTRIA OK: {len(payload.get('states', {})):,} Stationsreihen mit TMAX/TMIN bis {cutoff} | "
        f"{payload.get('block_count', '?')} historische API-Blöcke."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
