#!/usr/bin/env python3
from __future__ import annotations

import argparse
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

SOURCE = "AEMET OpenData"
PUBLIC_URL = "https://opendata.aemet.es/"
API_ROOT = "https://opendata.aemet.es/opendata/api"

INVENTORY_PATH = "/valores/climatologicos/inventarioestaciones/todasestaciones"
DAILY_ALL_PATH = (
    "/valores/climatologicos/diarios/datos/"
    "fechaini/{start}/fechafin/{end}/todasestaciones"
)

BASELINE_FORMAT_VERSION = 2
START_DATE = date(1920, 1, 1)
WINDOW_DAYS = 14

# AEMET can answer with HTTP 429. 1.70 seconds between *all* HTTP starts
# keeps the client deliberately conservative.
MIN_REQUEST_INTERVAL_SECONDS = 1.70
MAX_HTTP_TRIES = 7
CHECKPOINT_EVERY_WINDOWS = 20

_last_request_started = 0.0


def log(message: str) -> None:
    print(message, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"aemet_spain_daily_baseline_through_{cutoff_year}_v"
        f"{BASELINE_FORMAT_VERSION}.pkl.gz"
    )


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"aemet_spain_progress_through_{cutoff_year}_v"
        f"{BASELINE_FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"aemet_spain_status_through_{cutoff_year}.json"


def _atomic_pickle_gz(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _load_pickle_gz(path: Path) -> Any:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


def _atomic_json(path: Path, payload: Any) -> None:
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
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _rate_limit() -> None:
    global _last_request_started
    now = time.monotonic()
    wait = MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_started)
    if wait > 0:
        time.sleep(wait)
    _last_request_started = time.monotonic()


def _decode_json(raw: bytes, label: str) -> Any:
    candidates = []
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text not in candidates:
            candidates.append(text)

    for text in candidates:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue

    preview = raw[:800].decode("utf-8", errors="replace")
    raise RuntimeError(f"{label}: Antwort ist kein gültiges JSON: {preview}")


def request_json(
    url: str,
    *,
    api_key: str | None = None,
    label: str,
    allow_404: bool = False,
) -> Any | None:
    if api_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode({'api_key': api_key})}"

    last_error: Exception | None = None

    for attempt in range(1, MAX_HTTP_TRIES + 1):
        _rate_limit()
        req = urllib.request.Request(
            url,
            headers={
                "Cache-Control": "no-cache",
                "Accept": "application/json",
                "User-Agent": "climate-dashboard-aemet-cache/1.0",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=150) as response:
                raw = response.read()
            if not raw:
                raise RuntimeError(f"{label}: leere HTTP-Antwort.")
            return _decode_json(raw, label)

        except urllib.error.HTTPError as exc:
            last_error = exc

            if exc.code == 404 and allow_404:
                return None

            if exc.code == 401:
                raise RuntimeError(
                    f"{label}: HTTP 401 – AEMET_API_KEY nicht akzeptiert."
                ) from exc

            if exc.code == 403:
                raise RuntimeError(
                    f"{label}: HTTP 403 – Zugriff verweigert."
                ) from exc

            if exc.code == 429:
                wait = max(70, 20 * attempt)
                log(
                    f"{label}: HTTP 429 – AEMET-Limit erreicht; "
                    f"warte {wait}s (Versuch {attempt}/{MAX_HTTP_TRIES}) …"
                )
                time.sleep(wait)
                continue

            if exc.code >= 500:
                wait = min(180, 15 * attempt)
                log(
                    f"{label}: HTTP {exc.code}; warte {wait}s "
                    f"(Versuch {attempt}/{MAX_HTTP_TRIES}) …"
                )
                time.sleep(wait)
                continue

            body = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(
                f"{label}: HTTP {exc.code}: {body}"
            ) from exc

        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
            last_error = exc
            if attempt >= MAX_HTTP_TRIES:
                break
            wait = min(90, 5 * attempt)
            log(
                f"{label}: Versuch {attempt}/{MAX_HTTP_TRIES} "
                f"fehlgeschlagen: {exc}; warte {wait}s …"
            )
            time.sleep(wait)

    raise RuntimeError(
        f"{label}: nach {MAX_HTTP_TRIES} Versuchen fehlgeschlagen: {last_error}"
    )


def fetch_api_payload(
    api_path: str,
    api_key: str,
    *,
    label: str,
    no_data_is_empty: bool = False,
) -> Any:
    # Re-fetch metadata if its temporary "datos" URL expires.
    last_error: Exception | None = None

    for outer_attempt in range(1, 4):
        meta = request_json(
            API_ROOT + api_path,
            api_key=api_key,
            label=f"{label} Metadaten",
            allow_404=no_data_is_empty,
        )

        if meta is None:
            return []

        if not isinstance(meta, dict):
            raise RuntimeError(
                f"{label}: unerwartete Metadatenantwort "
                f"({type(meta).__name__})."
            )

        estado = meta.get("estado")
        descripcion = str(meta.get("descripcion", "") or "")

        if str(estado) == "404":
            if no_data_is_empty:
                return []
            raise RuntimeError(f"{label}: AEMET estado 404: {descripcion}")

        if estado not in (None, 200, "200"):
            if str(estado) == "429":
                wait = 75 * outer_attempt
                log(f"{label}: AEMET estado 429; warte {wait}s …")
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"{label}: AEMET estado={estado}: "
                f"{descripcion or 'keine Beschreibung'}"
            )

        data_url = meta.get("datos")
        if not isinstance(data_url, str) or not data_url.strip():
            if no_data_is_empty and "NO HAY DATOS" in descripcion.upper():
                return []
            raise RuntimeError(f"{label}: AEMET lieferte keine datos-URL.")

        try:
            payload = request_json(
                data_url.strip(),
                label=f"{label} Daten",
                allow_404=False,
            )
            return payload
        except RuntimeError as exc:
            last_error = exc
            if outer_attempt < 3:
                log(
                    f"{label}: temporäre Datenadresse fehlgeschlagen; "
                    "hole AEMET-Metadaten neu …"
                )
                time.sleep(3)
                continue
            raise

    raise RuntimeError(f"{label}: endgültig fehlgeschlagen: {last_error}")


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NULL", "-", "NONE"}:
        return None
    text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def parse_dms(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().upper().replace(" ", "")
    if not text:
        return None

    try:
        return float(text.replace(",", "."))
    except ValueError:
        pass

    hemisphere = text[-1:] if text[-1:] in {"N", "S", "E", "W", "O"} else ""
    digits = "".join(ch for ch in text[:-1] if ch.isdigit()) if hemisphere else ""
    if not hemisphere or len(digits) < 6:
        return None

    deg_digits = len(digits) - 4
    if deg_digits not in (2, 3):
        return None

    degrees = int(digits[:deg_digits])
    minutes = int(digits[deg_digits:deg_digits + 2])
    seconds = int(digits[deg_digits + 2:deg_digits + 4])

    result = degrees + minutes / 60.0 + seconds / 3600.0
    if hemisphere in {"S", "W", "O"}:
        result = -result
    return result


def inventory_from_payload(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        raise RuntimeError("AEMET-Stationsinventar ist keine Liste.")

    result: dict[str, dict[str, Any]] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("indicativo", "")).strip()
        if not sid:
            continue

        result[sid] = {
            "id": sid,
            "name": str(raw.get("nombre", "") or sid).strip(),
            "province": str(raw.get("provincia", "") or "").strip(),
            "height": parse_number(raw.get("altitud")),
            "latitude": parse_dms(raw.get("latitud")),
            "longitude": parse_dms(raw.get("longitud")),
            "synop": str(raw.get("indsinop", "") or "").strip(),
            "country": "Spanien",
            "source": SOURCE,
        }

    if len(result) < 100:
        raise RuntimeError(
            f"AEMET-Stationsinventar unerwartet klein: {len(result)} Stationen."
        )
    return result


def empty_station_record() -> dict[str, Any]:
    return {
        "first_date": None,
        "last_date": None,
        "observation_days": 0,
        "tmax_abs": None,
        "tmax_low_abs": None,
        "tmin_abs": None,
        "tmin_high_abs": None,
        "calendar_tmax": {},
        "calendar_tmin": {},
    }


def _better_max(candidate: float, candidate_date: str, current: Any) -> bool:
    if current is None:
        return True
    current_value = float(current[0])
    current_date = str(current[1])
    return candidate > current_value or (
        candidate == current_value and candidate_date < current_date
    )


def _better_min(candidate: float, candidate_date: str, current: Any) -> bool:
    if current is None:
        return True
    current_value = float(current[0])
    current_date = str(current[1])
    return candidate < current_value or (
        candidate == current_value and candidate_date < current_date
    )


def consume_daily_payload(
    payload: Any,
    *,
    window_start: date,
    window_end: date,
    inventory: dict[str, dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    if isinstance(payload, dict):
        # Defensive support for a possible wrapper.
        if isinstance(payload.get("datos"), list):
            payload = payload["datos"]
        else:
            payload = [payload]

    if not isinstance(payload, list):
        raise RuntimeError(
            f"AEMET-Tagesdaten: unerwarteter Typ {type(payload).__name__}."
        )

    accepted_rows = 0
    station_ids: set[str] = set()

    for raw in payload:
        if not isinstance(raw, dict):
            continue

        sid = str(raw.get("indicativo", "")).strip()
        day_text = str(raw.get("fecha", "")).strip()[:10]
        if not sid or len(day_text) != 10:
            continue

        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue

        if day < window_start or day > window_end:
            raise RuntimeError(
                f"AEMET lieferte Datum {day_text} außerhalb des "
                f"angefragten Fensters {window_start}–{window_end}."
            )

        tmax = parse_number(raw.get("tmax"))
        tmin = parse_number(raw.get("tmin"))
        if tmax is None and tmin is None:
            continue

        # Broad physical sanity bounds; values outside are treated as malformed.
        if tmax is not None and not (-60.0 <= tmax <= 60.0):
            raise RuntimeError(f"Unplausible AEMET TMAX {tmax} bei {sid} am {day_text}.")
        if tmin is not None and not (-60.0 <= tmin <= 60.0):
            raise RuntimeError(f"Unplausible AEMET TMIN {tmin} bei {sid} am {day_text}.")

        if sid not in inventory:
            inventory[sid] = {
                "id": sid,
                "name": str(raw.get("nombre", "") or sid).strip(),
                "province": str(raw.get("provincia", "") or "").strip(),
                "height": parse_number(raw.get("altitud")),
                "latitude": None,
                "longitude": None,
                "synop": "",
                "country": "Spanien",
                "source": SOURCE,
            }

        state = records.setdefault(sid, empty_station_record())
        accepted_rows += 1
        station_ids.add(sid)

        if state["first_date"] is None or day_text < state["first_date"]:
            state["first_date"] = day_text
        if state["last_date"] is None or day_text > state["last_date"]:
            state["last_date"] = day_text
        state["observation_days"] += 1

        mmdd = day_text[5:10]

        if tmax is not None:
            if _better_max(tmax, day_text, state["tmax_abs"]):
                state["tmax_abs"] = [round(tmax, 1), day_text]
            if _better_min(tmax, day_text, state["tmax_low_abs"]):
                state["tmax_low_abs"] = [round(tmax, 1), day_text]
            current = state["calendar_tmax"].get(mmdd)
            if _better_max(tmax, day_text, current):
                state["calendar_tmax"][mmdd] = [round(tmax, 1), day_text]

        if tmin is not None:
            if _better_min(tmin, day_text, state["tmin_abs"]):
                state["tmin_abs"] = [round(tmin, 1), day_text]
            if _better_max(tmin, day_text, state["tmin_high_abs"]):
                state["tmin_high_abs"] = [round(tmin, 1), day_text]
            current = state["calendar_tmin"].get(mmdd)
            if _better_min(tmin, day_text, current):
                state["calendar_tmin"][mmdd] = [round(tmin, 1), day_text]

    return accepted_rows, len(station_ids)


def windows(start: date, end: date):
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=WINDOW_DAYS - 1), end)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def fresh_progress(cutoff_year: int, inventory: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "format_version": BASELINE_FORMAT_VERSION,
        "source": SOURCE,
        "public_url": PUBLIC_URL,
        "cutoff_year": cutoff_year,
        "start_date": START_DATE.isoformat(),
        "end_date": date(cutoff_year, 12, 31).isoformat(),
        "next_date": START_DATE.isoformat(),
        "complete": False,
        "inventory": inventory,
        "records": {},
        "processed_windows": 0,
        "data_windows": 0,
        "empty_windows": 0,
        "rows_with_temperature": 0,
        "last_checkpoint": None,
    }


def write_status(cache_dir: Path, cutoff_year: int, progress: dict[str, Any]) -> None:
    end_date = date(cutoff_year, 12, 31)
    total_windows = sum(1 for _ in windows(START_DATE, end_date))
    processed = int(progress.get("processed_windows", 0))

    payload = {
        "source": SOURCE,
        "format_version": BASELINE_FORMAT_VERSION,
        "cutoff_year": cutoff_year,
        "start_date": START_DATE.isoformat(),
        "end_date": end_date.isoformat(),
        "total_windows": total_windows,
        "processed_windows": processed,
        "remaining_windows": max(0, total_windows - processed),
        "data_windows": int(progress.get("data_windows", 0)),
        "empty_windows": int(progress.get("empty_windows", 0)),
        "rows_with_temperature": int(progress.get("rows_with_temperature", 0)),
        "station_count": len(progress.get("records", {})),
        "inventory_count": len(progress.get("inventory", {})),
        "next_date": progress.get("next_date"),
        "complete": bool(progress.get("complete")),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _atomic_json(status_path(cache_dir, cutoff_year), payload)


def save_progress(cache_dir: Path, cutoff_year: int, progress: dict[str, Any]) -> None:
    progress["last_checkpoint"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _atomic_pickle_gz(progress_path(cache_dir, cutoff_year), progress)
    write_status(cache_dir, cutoff_year, progress)


def finalize_baseline(cache_dir: Path, cutoff_year: int, progress: dict[str, Any]) -> Path:
    progress["complete"] = True
    progress["next_date"] = None
    progress["built_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    target = baseline_path(cache_dir, cutoff_year)
    _atomic_pickle_gz(target, progress)
    save_progress(cache_dir, cutoff_year, progress)
    return target


def load_baseline(cache_dir: Path, cutoff_year: int) -> dict[str, Any]:
    path = baseline_path(cache_dir, cutoff_year)
    payload = _load_pickle_gz(path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"AEMET-Baseline ist ungültig: {path}")
    if payload.get("format_version") != BASELINE_FORMAT_VERSION:
        raise RuntimeError(
            f"AEMET-Baseline hat Formatversion {payload.get('format_version')}; "
            f"erwartet {BASELINE_FORMAT_VERSION}."
        )
    if int(payload.get("cutoff_year", -1)) != cutoff_year:
        raise RuntimeError("AEMET-Baseline hat falsches cutoff_year.")
    if not payload.get("complete"):
        raise RuntimeError("AEMET-Baseline ist nicht als vollständig markiert.")
    return payload


def build_baseline(
    *,
    api_key: str,
    cutoff_year: int,
    cache_dir: Path,
    force: bool = False,
    max_runtime_minutes: float = 235.0,
) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    final = baseline_path(cache_dir, cutoff_year)
    prog = progress_path(cache_dir, cutoff_year)

    if force:
        for path in (final, prog, status_path(cache_dir, cutoff_year)):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    if final.exists() and not force:
        payload = load_baseline(cache_dir, cutoff_year)
        log(
            f"Verwende vollständigen AEMET-Spanien-Cache: {final} "
            f"({len(payload.get('records', {})):,} Stationsreihen)."
        )
        write_status(cache_dir, cutoff_year, payload)
        return payload

    if prog.exists() and not force:
        progress = _load_pickle_gz(prog)
        if (
            not isinstance(progress, dict)
            or progress.get("format_version") != BASELINE_FORMAT_VERSION
            or int(progress.get("cutoff_year", -1)) != cutoff_year
        ):
            raise RuntimeError(
                "Vorhandener AEMET-Fortschrittscache passt nicht zur aktuellen Version. "
                "Einmal mit force=true neu aufbauen."
            )
        log(
            f"Setze AEMET-Spanien-Basisbestand fort: "
            f"{progress.get('processed_windows', 0):,} Fenster bereits verarbeitet, "
            f"{len(progress.get('records', {})):,} Stationsreihen."
        )
    else:
        inventory_payload = fetch_api_payload(
            INVENTORY_PATH,
            api_key,
            label="AEMET Stationsinventar",
        )
        inventory = inventory_from_payload(inventory_payload)
        log(f"AEMET Stationsinventar: {len(inventory):,} Stationskennungen.")
        progress = fresh_progress(cutoff_year, inventory)
        save_progress(cache_dir, cutoff_year, progress)

    end_date = date(cutoff_year, 12, 31)
    next_date_text = progress.get("next_date")
    next_date = date.fromisoformat(next_date_text) if next_date_text else START_DATE

    remaining = list(windows(next_date, end_date))
    total_windows = sum(1 for _ in windows(START_DATE, end_date))

    log("=== AEMET SPANIEN HISTORISCHE BASELINE ===")
    log(
        f"Zeitraum {START_DATE.isoformat()} bis {end_date.isoformat()} | "
        f"{total_windows:,} Fenster à maximal {WINDOW_DAYS} Tage."
    )
    log(
        "Jedes Fenster wird direkt in einen kompakten Rekord-Zwischenspeicher "
        "eingearbeitet; kein riesiger Rohdatenbestand wird gespeichert."
    )

    started = time.monotonic()
    deadline = started + max_runtime_minutes * 60.0
    processed_this_run = 0

    for window_start, window_end in remaining:
        # Stop gracefully early enough that GitHub Actions can still save its cache.
        if time.monotonic() >= deadline:
            save_progress(cache_dir, cutoff_year, progress)
            log(
                f"AEMET Laufzeitlimit erreicht nach {processed_this_run:,} neuen Fenstern. "
                "Fortschritt wurde gespeichert; nächsten Workflow-Lauf mit force=false starten."
            )
            return progress

        start_api = f"{window_start.isoformat()}T00:00:00UTC"
        end_api = f"{window_end.isoformat()}T23:59:59UTC"
        api_path = DAILY_ALL_PATH.format(start=start_api, end=end_api)
        label = f"AEMET {window_start}–{window_end}"

        try:
            payload = fetch_api_payload(
                api_path,
                api_key,
                label=label,
                no_data_is_empty=True,
            )
        except Exception:
            # The current window has not been consumed yet, therefore it is
            # safe to persist the last fully completed window before aborting.
            save_progress(cache_dir, cutoff_year, progress)
            log(
                "AEMET: Abruf eines Fensters ist trotz Wiederholungen "
                "fehlgeschlagen. Letzter vollständiger Zwischenstand wurde "
                "vor dem Abbruch gesichert."
            )
            raise

        rows, station_count = consume_daily_payload(
            payload,
            window_start=window_start,
            window_end=window_end,
            inventory=progress["inventory"],
            records=progress["records"],
        )

        progress["processed_windows"] += 1
        processed_this_run += 1
        progress["rows_with_temperature"] += rows

        if rows:
            progress["data_windows"] += 1
        else:
            progress["empty_windows"] += 1

        progress["next_date"] = (
            (window_end + timedelta(days=1)).isoformat()
            if window_end < end_date
            else None
        )

        done = int(progress["processed_windows"])
        if (
            done % CHECKPOINT_EVERY_WINDOWS == 0
            or done == total_windows
        ):
            save_progress(cache_dir, cutoff_year, progress)

        if (
            processed_this_run == 1
            or processed_this_run % 25 == 0
            or done == total_windows
        ):
            elapsed = (time.monotonic() - started) / 60.0
            log(
                f"AEMET historical: {done:,}/{total_windows:,} Fenster | "
                f"{len(progress['records']):,} Stationsreihen | "
                f"{progress['rows_with_temperature']:,} Temperatur-Zeilen | "
                f"dieser Lauf {elapsed:.1f} min."
            )

    target = finalize_baseline(cache_dir, cutoff_year, progress)
    log(
        f"AEMET SPANIEN OK: {len(progress['records']):,} Stationsreihen "
        f"mit TMAX/TMIN bis {cutoff_year}."
    )
    log(f"Gesamtcache: {target}")
    return progress


def self_test() -> None:
    assert parse_number("40,1") == 40.1
    assert parse_number("-3.5") == -3.5
    assert parse_number("") is None

    lat = parse_dms("402441N")
    lon = parse_dms("0034040W")
    assert lat is not None and abs(lat - 40.4113888889) < 1e-6
    assert lon is not None and abs(lon + 3.6777777778) < 1e-6

    inventory = {
        "X": {
            "id": "X",
            "name": "Test",
            "province": "Test",
            "height": 1.0,
            "latitude": 40.0,
            "longitude": -3.0,
            "synop": "",
            "country": "Spanien",
            "source": SOURCE,
        }
    }
    records: dict[str, dict[str, Any]] = {}
    payload = [
        {"fecha": "2020-07-01", "indicativo": "X", "tmax": "40,0", "tmin": "20,0"},
        {"fecha": "2021-07-01", "indicativo": "X", "tmax": "41,2", "tmin": "19,0"},
    ]
    # Feed rows through two distinct windows to mimic separate years.
    r1, _ = consume_daily_payload(
        payload[:1],
        window_start=date(2020, 7, 1),
        window_end=date(2020, 7, 14),
        inventory=inventory,
        records=records,
    )
    r2, _ = consume_daily_payload(
        payload[1:],
        window_start=date(2021, 7, 1),
        window_end=date(2021, 7, 14),
        inventory=inventory,
        records=records,
    )
    assert r1 == 1 and r2 == 1
    assert records["X"]["tmax_abs"] == [41.2, "2021-07-01"]
    assert records["X"]["tmin_abs"] == [19.0, "2021-07-01"]
    assert records["X"]["tmax_low_abs"] is not None
    assert records["X"]["tmin_high_abs"] is not None
    assert records["X"]["calendar_tmax"]["07-01"] == [41.2, "2021-07-01"]
    assert records["X"]["calendar_tmin"]["07-01"] == [19.0, "2021-07-01"]

    assert len(list(windows(date(2020, 1, 1), date(2020, 1, 31)))) == 3
    print("AEMET Spain historical cache self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Baut den historischen AEMET-Spanien-Stationscache."
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache/europe-stations"),
    )
    parser.add_argument(
        "--cutoff-year",
        type=int,
        default=date.today().year - 1,
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-runtime-minutes", type=float, default=235.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.cutoff_year < 1920:
        raise RuntimeError("cutoff-year muss mindestens 1920 sein.")

    api_key = os.environ.get("AEMET_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("AEMET_API_KEY fehlt.")

    build_baseline(
        api_key=api_key,
        cutoff_year=args.cutoff_year,
        cache_dir=args.cache_dir,
        force=args.force,
        max_runtime_minutes=args.max_runtime_minutes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
