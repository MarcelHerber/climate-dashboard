#!/usr/bin/env python3
"""
Build a compact historical Norway daily Tmax/Tmin station-record cache from
MET Norway Frost.

Policy:
- SensorSystem sources in Norway.
- Source must offer BOTH daily max/min air temperature.
- At least one station holder must be MET.NO.
- Recommended/default source sensor and time series only.
- Daily standard time offset/level via Frost defaults.
- Quality codes 0..4 only.

Important Frost time rule:
Intervals are [start, end), so one full year is queried as
YYYY-01-01/(YYYY+1)-01-01.

No huge raw daily archive is retained. Each response is immediately reduced
to compact absolute and calendar-day record state.
"""

from __future__ import annotations

import argparse
import base64
import calendar
import gzip
import http.client
import json
import math
import os
import pickle
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


API = "https://frost.met.no"
SOURCE = "MET Norway Frost"
PUBLIC_URL = "https://frost.met.no/"
TMAX = "max(air_temperature P1D)"
TMIN = "min(air_temperature P1D)"
ELEMENTS = f"{TMAX},{TMIN}"

BASELINE_FORMAT_VERSION = 1
EARLIEST_INVENTORY_DATE = date(1800, 1, 1)
SOURCE_CHUNK_SIZE = 40
MAX_HTTP_TRIES = 7
REQUEST_TIMEOUT = 180
MIN_REQUEST_INTERVAL_SECONDS = 0.35
CHECKPOINT_EVERY_REQUESTS = 10
ACCEPTABLE_QUALITIES = "0,1,2,3,4"

CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
_last_request_started = 0.0


class FrostTooManyObservations(RuntimeError):
    pass


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"frost_norway_daily_baseline_through_{cutoff_year}"
        f"_v{BASELINE_FORMAT_VERSION}.pkl.gz"
    )


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"frost_norway_progress_through_{cutoff_year}"
        f"_v{BASELINE_FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"frost_norway_status_through_{cutoff_year}.json"


def auth_header(client_id: str) -> str:
    token = base64.b64encode(f"{client_id}:".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def pace_request() -> None:
    global _last_request_started
    now = time.monotonic()
    wait = MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_started)
    if wait > 0:
        time.sleep(wait)
    _last_request_started = time.monotonic()


def backoff_seconds(attempt: int) -> int:
    return min(90, 5 * (2 ** max(0, attempt - 1)))


def request_json_url(
    url: str,
    client_id: str,
    *,
    allow_no_data: bool = False,
) -> dict[str, Any] | None:
    last_error: Exception | None = None

    for attempt in range(1, MAX_HTTP_TRIES + 1):
        pace_request()
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": auth_header(client_id),
                "User-Agent": "climate-dashboard-frost-norway-cache/1.0",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("Frost-Antwort ist kein JSON-Objekt.")
            return payload

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")

            # Frost officially rejects requests estimated to produce too many
            # observations with HTTP 403. Let the caller split the request.
            if exc.code == 403 and "too many" in body.lower():
                raise FrostTooManyObservations(body[:1000]) from exc

            if allow_no_data and exc.code in (404, 412):
                return None

            if exc.code == 429 and attempt < MAX_HTTP_TRIES:
                wait = max(60, backoff_seconds(attempt))
                log(
                    f"Frost HTTP 429 ({attempt}/{MAX_HTTP_TRIES}); "
                    f"warte {wait}s …"
                )
                time.sleep(wait)
                last_error = exc
                continue

            if 500 <= exc.code <= 599 and attempt < MAX_HTTP_TRIES:
                wait = backoff_seconds(attempt)
                log(
                    f"Frost HTTP {exc.code} ({attempt}/{MAX_HTTP_TRIES}); "
                    f"warte {wait}s …"
                )
                time.sleep(wait)
                last_error = exc
                continue

            raise RuntimeError(
                f"Frost HTTP {exc.code}: {body[:1000]}"
            ) from exc

        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
            last_error = exc
            if attempt >= MAX_HTTP_TRIES:
                break
            wait = backoff_seconds(attempt)
            log(
                f"Frost Versuch {attempt}/{MAX_HTTP_TRIES} fehlgeschlagen: "
                f"{exc}; warte {wait}s …"
            )
            time.sleep(wait)

    raise RuntimeError(
        f"Frost-Abruf nach {MAX_HTTP_TRIES} Versuchen fehlgeschlagen: {last_error}"
    )


def get_json(
    path: str,
    client_id: str,
    params: dict[str, Any],
    *,
    allow_no_data: bool = False,
) -> dict[str, Any] | None:
    clean = {
        k: str(v)
        for k, v in params.items()
        if v is not None and str(v) != ""
    }
    query = urllib.parse.urlencode(clean, safe="(),:*")
    return request_json_url(
        f"{API}{path}?{query}",
        client_id,
        allow_no_data=allow_no_data,
    )


def paged_data(
    path: str,
    client_id: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    payload = get_json(path, client_id, params)
    rows: list[dict[str, Any]] = []

    while payload:
        data = payload.get("data", [])
        if isinstance(data, list):
            rows.extend(x for x in data if isinstance(x, dict))

        next_link = payload.get("nextLink")
        if not isinstance(next_link, str) or not next_link:
            break

        payload = request_json_url(next_link, client_id)

    return rows


def holder_names(source: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "stationHolders",
        "stationholders",
        "stationHolder",
        "stationholder",
    ):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    values.append(item.strip())
                elif isinstance(item, dict):
                    for subkey in ("name", "id", "shortName"):
                        sub = item.get(subkey)
                        if isinstance(sub, str) and sub.strip():
                            values.append(sub.strip())
                            break
    return values


def is_metno_holder(source: dict[str, Any]) -> bool:
    return any(x.strip().upper() == "MET.NO" for x in holder_names(source))


def canonical_station_id(value: str) -> str:
    return str(value).split(":")[0].strip().upper()


def parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def geometry_point(source: dict[str, Any]) -> tuple[float | None, float | None]:
    geometry = source.get("geometry")
    if not isinstance(geometry, dict):
        return None, None
    coords = geometry.get("coordinates")

    if isinstance(coords, list) and len(coords) >= 2:
        try:
            # GeoJSON order: lon, lat.
            return float(coords[1]), float(coords[0])
        except (TypeError, ValueError):
            return None, None

    return None, None


def inventory_entry(source: dict[str, Any]) -> dict[str, Any]:
    sid = canonical_station_id(source.get("id") or source.get("sourceId") or "")
    lat, lon = geometry_point(source)
    return {
        "station_id": sid,
        "name": str(source.get("name") or source.get("shortName") or sid),
        "lat": lat,
        "lon": lon,
        "elevation_m": source.get("masl"),
        "valid_from": source.get("validFrom"),
        "valid_to": source.get("validTo"),
        "holders": holder_names(source),
        "country": "Norway",
        "country_code": "NO",
        "source": SOURCE,
    }


def fetch_historical_inventory(
    client_id: str,
    cutoff_year: int,
) -> dict[str, dict[str, Any]]:
    end = date(cutoff_year + 1, 1, 1)
    rows = paged_data(
        "/sources/v0.jsonld",
        client_id,
        {
            "types": "SensorSystem",
            "country": "NO",
            "elements": ELEMENTS,
            "validtime": f"{EARLIEST_INVENTORY_DATE.isoformat()}/{end.isoformat()}",
        },
    )

    all_eligible = 0
    inventory: dict[str, dict[str, Any]] = {}

    for row in rows:
        sid = canonical_station_id(row.get("id") or row.get("sourceId") or "")
        if not sid:
            continue
        all_eligible += 1
        if not is_metno_holder(row):
            continue
        inventory[sid] = inventory_entry(row)

    log(
        f"Frost historisches Inventar: {all_eligible} norwegische Quellen mit "
        f"Tmax+Tmin; davon {len(inventory)} mit Stationshalter MET.NO."
    )

    if not inventory:
        raise RuntimeError("Keine MET.NO-Stationen im historischen Frost-Inventar.")

    return inventory


def source_active_in_year(meta: dict[str, Any], year: int) -> bool:
    start = parse_iso_date(meta.get("valid_from"))
    end = parse_iso_date(meta.get("valid_to"))
    year_start = date(year, 1, 1)
    year_end = date(year + 1, 1, 1)

    if start is not None and start >= year_end:
        return False
    if end is not None and end < year_start:
        return False
    return True


def earliest_inventory_year(inventory: dict[str, dict[str, Any]]) -> int:
    years = []
    for meta in inventory.values():
        d = parse_iso_date(meta.get("valid_from"))
        if d is not None:
            years.append(d.year)
    return min(years) if years else 1860


def chunks(values: list[str], n: int) -> list[list[str]]:
    return [values[i:i+n] for i in range(0, len(values), n)]


def observation_payload(
    client_id: str,
    sources: list[str],
    start: date,
    end_exclusive: date,
) -> dict[str, Any] | None:
    return get_json(
        "/observations/v0.jsonld",
        client_id,
        {
            "sources": ",".join(sources),
            "referencetime": f"{start.isoformat()}/{end_exclusive.isoformat()}",
            "elements": ELEMENTS,
            "timeoffsets": "default",
            "levels": "default",
            "timeseriesids": "0",
            "qualities": ACCEPTABLE_QUALITIES,
        },
        allow_no_data=True,
    )


def split_date_range(start: date, end_exclusive: date) -> tuple[tuple[date, date], tuple[date, date]]:
    days = (end_exclusive - start).days
    if days <= 1:
        raise RuntimeError("Kann Frost-Zeitraum nicht weiter teilen.")
    mid = start + timedelta(days=days // 2)
    return (start, mid), (mid, end_exclusive)


def fetch_observations_resilient(
    client_id: str,
    sources: list[str],
    start: date,
    end_exclusive: date,
) -> list[dict[str, Any]]:
    try:
        payload = observation_payload(client_id, sources, start, end_exclusive)
    except FrostTooManyObservations:
        if len(sources) > 1:
            mid = len(sources) // 2
            return (
                fetch_observations_resilient(
                    client_id, sources[:mid], start, end_exclusive
                )
                + fetch_observations_resilient(
                    client_id, sources[mid:], start, end_exclusive
                )
            )

        left, right = split_date_range(start, end_exclusive)
        return (
            fetch_observations_resilient(client_id, sources, *left)
            + fetch_observations_resilient(client_id, sources, *right)
        )

    if not payload:
        return []

    data = payload.get("data", [])
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def quality_rank(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999


def flatten_best_observations(
    rows: list[dict[str, Any]],
    start: date,
    end_exclusive: date,
) -> list[tuple[str, date, float | None, float | None]]:
    # Best value per station/date/element; lower quality code wins.
    chosen: dict[tuple[str, date, str], tuple[int, float]] = {}

    for row in rows:
        station_id = canonical_station_id(row.get("sourceId") or "")
        ref = parse_iso_date(row.get("referenceTime"))
        if not station_id or ref is None or not (start <= ref < end_exclusive):
            continue

        observations = row.get("observations")
        if not isinstance(observations, list):
            continue

        for obs in observations:
            if not isinstance(obs, dict):
                continue

            element = str(obs.get("elementId") or "")
            if element not in (TMAX, TMIN):
                continue

            if str(obs.get("timeResolution") or "") not in ("", "P1D"):
                continue

            # With timeoffsets=default this should normally be PT18H for daily
            # temperature extremes. Keep the API-selected default but reject
            # explicit non-daily values above.
            try:
                value = float(obs.get("value"))
            except (TypeError, ValueError):
                continue

            if not math.isfinite(value) or not (-60.0 <= value <= 60.0):
                continue

            q = quality_rank(obs.get("qualityCode"))
            key = (station_id, ref, element)
            old = chosen.get(key)
            if old is None or q < old[0]:
                chosen[key] = (q, value)

    by_day: dict[tuple[str, date], dict[str, float]] = {}
    for (sid, d, element), (_, value) in chosen.items():
        by_day.setdefault((sid, d), {})[element] = value

    out = []
    for (sid, d), vals in sorted(by_day.items()):
        out.append(
            (
                sid,
                d,
                vals.get(TMIN),
                vals.get(TMAX),
            )
        )
    return out


def empty_record() -> dict[str, Any]:
    return {
        "first_date": None,
        "last_date": None,
        "observation_days": 0,
        "tmax_abs": None,
        "tmin_abs": None,
        "calendar_tmax": {},
        "calendar_tmin": {},
    }


def better_max(old: list[Any] | None, value: float, d: date) -> bool:
    if old is None:
        return True
    return value > float(old[0]) or (
        value == float(old[0]) and d.isoformat() < str(old[1])
    )


def better_min(old: list[Any] | None, value: float, d: date) -> bool:
    if old is None:
        return True
    return value < float(old[0]) or (
        value == float(old[0]) and d.isoformat() < str(old[1])
    )


def consume_rows(
    records: dict[str, dict[str, Any]],
    rows: list[tuple[str, date, float | None, float | None]],
) -> int:
    consumed = 0

    for station_id, d, tn, tx in rows:
        if tn is None and tx is None:
            continue

        rec = records.setdefault(station_id, empty_record())
        iso = d.isoformat()
        mmdd = d.strftime("%m-%d")

        if rec["first_date"] is None or iso < rec["first_date"]:
            rec["first_date"] = iso
        if rec["last_date"] is None or iso > rec["last_date"]:
            rec["last_date"] = iso

        rec["observation_days"] += 1

        if tx is not None:
            if better_max(rec["tmax_abs"], tx, d):
                rec["tmax_abs"] = [round(tx, 1), iso]
            old = rec["calendar_tmax"].get(mmdd)
            if better_max(old, tx, d):
                rec["calendar_tmax"][mmdd] = [round(tx, 1), iso]

        if tn is not None:
            if better_min(rec["tmin_abs"], tn, d):
                rec["tmin_abs"] = [round(tn, 1), iso]
            old = rec["calendar_tmin"].get(mmdd)
            if better_min(old, tn, d):
                rec["calendar_tmin"][mmdd] = [round(tn, 1), iso]

        consumed += 1

    return consumed


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_pickle_gzip(path: Path) -> Any:
    with gzip.open(path, "rb") as f:
        return pickle.load(f)


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(
            json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def new_progress(
    cutoff_year: int,
    inventory: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    start_year = earliest_inventory_year(inventory)
    return {
        "format_version": BASELINE_FORMAT_VERSION,
        "source": SOURCE,
        "cutoff_year": cutoff_year,
        "start_year": start_year,
        "next_year": start_year,
        "next_chunk_index": 0,
        "processed_requests": 0,
        "processed_years": 0,
        "rows_with_temperature": 0,
        "inventory": inventory,
        "records": {},
        "complete": False,
    }


def write_status(cache_dir: Path, cutoff_year: int, progress: dict[str, Any]) -> None:
    atomic_json(
        status_path(cache_dir, cutoff_year),
        {
            "format_version": BASELINE_FORMAT_VERSION,
            "source": SOURCE,
            "cutoff_year": cutoff_year,
            "start_year": progress.get("start_year"),
            "next_year": progress.get("next_year"),
            "next_chunk_index": progress.get("next_chunk_index"),
            "processed_requests": progress.get("processed_requests", 0),
            "processed_years": progress.get("processed_years", 0),
            "rows_with_temperature": progress.get("rows_with_temperature", 0),
            "inventory_count": len(progress.get("inventory", {})),
            "station_count": len(progress.get("records", {})),
            "complete": bool(progress.get("complete", False)),
            "baseline_file": str(baseline_path(cache_dir, cutoff_year)),
        },
    )


def save_progress(cache_dir: Path, cutoff_year: int, progress: dict[str, Any]) -> None:
    atomic_pickle_gzip(progress_path(cache_dir, cutoff_year), progress)
    write_status(cache_dir, cutoff_year, progress)


def valid_final(path: Path, cutoff_year: int) -> bool:
    if not path.exists():
        return False
    try:
        obj = load_pickle_gzip(path)
        return bool(
            isinstance(obj, dict)
            and obj.get("format_version") == BASELINE_FORMAT_VERSION
            and obj.get("cutoff_year") == cutoff_year
            and obj.get("complete") is True
            and obj.get("records")
        )
    except Exception:
        return False


def build_baseline(
    client_id: str,
    cache_dir: Path,
    cutoff_year: int,
    *,
    force: bool = False,
    max_runtime_minutes: float = 220.0,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    final = baseline_path(cache_dir, cutoff_year)
    prog = progress_path(cache_dir, cutoff_year)
    stat = status_path(cache_dir, cutoff_year)

    if force:
        for p in (final, prog, stat):
            p.unlink(missing_ok=True)

    if not force and valid_final(final, cutoff_year):
        log(f"Verwende vorhandenen Frost-Norwegen-Baselinecache: {final}")
        return final

    progress: dict[str, Any] | None = None
    if not force and prog.exists():
        try:
            candidate = load_pickle_gzip(prog)
            if (
                candidate.get("format_version") == BASELINE_FORMAT_VERSION
                and candidate.get("cutoff_year") == cutoff_year
            ):
                progress = candidate
                log(
                    "Setze Frost-Norwegen-Basisbestand fort: "
                    f"Jahr {progress.get('next_year')} / "
                    f"Chunk {progress.get('next_chunk_index')} | "
                    f"{len(progress.get('records', {}))} Stationsreihen."
                )
        except Exception:
            progress = None

    if progress is None:
        inventory = fetch_historical_inventory(client_id, cutoff_year)
        progress = new_progress(cutoff_year, inventory)
        save_progress(cache_dir, cutoff_year, progress)

    inventory = progress["inventory"]
    start_year = int(progress["start_year"])
    total_years = cutoff_year - start_year + 1
    started = time.monotonic()

    log("=== MET NORWAY / FROST HISTORISCHE BASELINE ===")
    log(
        f"Zeitraum ab {start_year} bis {cutoff_year}; "
        f"nur Stationshalter MET.NO; Tages-TMAX/TMIN."
    )
    log(
        "Frost-Intervalle werden jahresweise als [01-01, nächstes 01-01) "
        "abgerufen; Standard-Zeitserie/Level, Quality 0–4."
    )

    year = int(progress["next_year"])

    while year <= cutoff_year:
        elapsed = (time.monotonic() - started) / 60.0
        if elapsed >= max_runtime_minutes:
            save_progress(cache_dir, cutoff_year, progress)
            log(
                f"Frost Laufzeitgrenze nach {elapsed:.1f} min erreicht. "
                "Zwischenstand gespeichert; mit force=false fortsetzen."
            )
            return prog

        active = sorted(
            sid for sid, meta in inventory.items()
            if source_active_in_year(meta, year)
        )
        year_chunks = chunks(active, SOURCE_CHUNK_SIZE)

        chunk_index = (
            int(progress.get("next_chunk_index", 0))
            if year == int(progress.get("next_year", year))
            else 0
        )

        if not year_chunks:
            progress["processed_years"] += 1
            progress["next_year"] = year + 1
            progress["next_chunk_index"] = 0
            save_progress(cache_dir, cutoff_year, progress)
            year += 1
            continue

        start = date(year, 1, 1)
        end_exclusive = date(year + 1, 1, 1)

        while chunk_index < len(year_chunks):
            elapsed = (time.monotonic() - started) / 60.0
            if elapsed >= max_runtime_minutes:
                save_progress(cache_dir, cutoff_year, progress)
                log(
                    f"Frost Laufzeitgrenze nach {elapsed:.1f} min erreicht. "
                    "Zwischenstand gespeichert."
                )
                return prog

            source_chunk = year_chunks[chunk_index]

            try:
                raw_rows = fetch_observations_resilient(
                    client_id,
                    source_chunk,
                    start,
                    end_exclusive,
                )
            except Exception:
                save_progress(cache_dir, cutoff_year, progress)
                log(
                    "Frost-Abruf ist trotz Wiederholungen fehlgeschlagen. "
                    "Letzter vollständiger Chunk wurde gespeichert."
                )
                raise

            rows = flatten_best_observations(raw_rows, start, end_exclusive)
            consumed = consume_rows(progress["records"], rows)

            progress["rows_with_temperature"] += consumed
            progress["processed_requests"] += 1
            chunk_index += 1
            progress["next_year"] = year
            progress["next_chunk_index"] = chunk_index

            if (
                progress["processed_requests"] % CHECKPOINT_EVERY_REQUESTS == 0
                or chunk_index == len(year_chunks)
            ):
                save_progress(cache_dir, cutoff_year, progress)

        progress["processed_years"] += 1
        progress["next_year"] = year + 1
        progress["next_chunk_index"] = 0
        save_progress(cache_dir, cutoff_year, progress)

        log(
            f"Frost historical: {progress['processed_years']}/{total_years} Jahre "
            f"| bis {year} | aktive MET.NO-Quellen {len(active)} "
            f"| {len(progress['records'])} Stationsreihen "
            f"| {progress['rows_with_temperature']:,} Temperatur-Zeilen "
            f"| dieser Lauf {((time.monotonic()-started)/60):.1f} min."
        )

        year += 1

    if not progress["records"]:
        raise RuntimeError("Frost-Norwegen-Baseline enthält keine Stationsdaten.")

    progress["complete"] = True
    progress["next_year"] = cutoff_year + 1
    progress["next_chunk_index"] = 0
    progress["public_url"] = PUBLIC_URL
    progress["element_tmax"] = TMAX
    progress["element_tmin"] = TMIN
    progress["qualities"] = ACCEPTABLE_QUALITIES
    progress["holder_policy"] = "station holder contains MET.NO"

    atomic_pickle_gzip(final, progress)
    write_status(cache_dir, cutoff_year, progress)

    log(
        f"FROST NORWAY OK: {len(progress['records'])} Stationsreihen "
        f"mit TMAX/TMIN bis {cutoff_year} | "
        f"{progress['rows_with_temperature']:,} Temperatur-Zeilen."
    )
    return final


def self_test() -> None:
    assert canonical_station_id("SN18700:0") == "SN18700"
    assert canonical_station_id("sn18700") == "SN18700"

    src = {
        "stationHolders": ["MET.NO", "AVINOR"],
        "id": "SN87110",
        "name": "ANDØYA",
        "validFrom": "1958-06-01T00:00:00.000Z",
        "validTo": None,
        "geometry": {"coordinates": [16.1312, 69.3073]},
    }
    assert is_metno_holder(src)
    inv = inventory_entry(src)
    assert inv["lat"] == 69.3073
    assert inv["lon"] == 16.1312
    assert source_active_in_year(inv, 1958)
    assert not source_active_in_year(inv, 1957)

    rows = [
        {
            "sourceId": "SN18700:0",
            "referenceTime": "2024-07-01T00:00:00.000Z",
            "observations": [
                {
                    "elementId": TMAX,
                    "value": 21.1,
                    "timeOffset": "PT18H",
                    "timeResolution": "P1D",
                    "qualityCode": 0,
                },
                {
                    "elementId": TMIN,
                    "value": 10.0,
                    "timeOffset": "PT18H",
                    "timeResolution": "P1D",
                    "qualityCode": 0,
                },
            ],
        }
    ]
    flat = flatten_best_observations(
        rows, date(2024, 1, 1), date(2025, 1, 1)
    )
    assert flat == [("SN18700", date(2024, 7, 1), 10.0, 21.1)]

    recs: dict[str, dict[str, Any]] = {}
    consume_rows(recs, flat)
    assert recs["SN18700"]["tmax_abs"] == [21.1, "2024-07-01"]
    assert recs["SN18700"]["tmin_abs"] == [10.0, "2024-07-01"]

    a, b = split_date_range(date(2020, 1, 1), date(2021, 1, 1))
    assert a[0] == date(2020, 1, 1)
    assert b[1] == date(2021, 1, 1)
    assert a[1] == b[0]

    print("Frost Norway historical cache self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument(
        "--cutoff-year",
        type=int,
        default=date.today().year - 1,
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        default=220.0,
    )
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    client_id = os.environ.get("FROST_CLIENT_ID", "").strip()
    if not client_id:
        raise SystemExit("FROST_CLIENT_ID fehlt.")

    build_baseline(
        client_id,
        Path(args.cache_dir),
        args.cutoff_year,
        force=args.force,
        max_runtime_minutes=args.max_runtime_minutes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
