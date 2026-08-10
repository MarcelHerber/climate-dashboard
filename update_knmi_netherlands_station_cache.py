#!/usr/bin/env python3
"""
Build a compact KNMI Netherlands daily TX/TN station-record baseline.

Source:
    https://www.daggegevens.knmi.nl/klimatologie/daggegevens

The official KNMI script interface accepts POST parameters:
    start=YYYYMMDD
    end=YYYYMMDD
    vars=TN:TX
    stns=ALL

This builder deliberately uses yearly chunks instead of downloading tens of
thousands of individual NetCDF daily files from the KNMI Data Platform.

Output cache schema is intentionally compact:
- station metadata
- first/last observation date
- number of temperature observation-days
- absolute TX/TN records
- calendar-day TX/TN records (MM-DD)

No raw multi-million-row daily archive is retained.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import http.client
import io
import json
import os
import pickle
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


SOURCE = "KNMI"
PUBLIC_URL = "https://www.daggegevens.knmi.nl/klimatologie/daggegevens"

BASELINE_FORMAT_VERSION = 1
START_YEAR = 1901
MAX_HTTP_TRIES = 7
REQUEST_TIMEOUT = 180
MIN_REQUEST_INTERVAL_SECONDS = 1.0

CACHE_DIR_DEFAULT = Path(".cache/europe-stations")

_last_request_started = 0.0


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"knmi_netherlands_daily_baseline_through_{cutoff_year}"
        f"_v{BASELINE_FORMAT_VERSION}.pkl.gz"
    )


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"knmi_netherlands_progress_through_{cutoff_year}"
        f"_v{BASELINE_FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"knmi_netherlands_status_through_{cutoff_year}.json"


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
        if tmp.exists():
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
            json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def pace_request() -> None:
    global _last_request_started
    now = time.monotonic()
    wait = MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_started)
    if wait > 0:
        time.sleep(wait)
    _last_request_started = time.monotonic()


def backoff_seconds(attempt: int) -> int:
    return min(60, 5 * (2 ** max(0, attempt - 1)))


def request_knmi(start: date, end: date) -> str:
    payload = urllib.parse.urlencode(
        {
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "vars": "TN:TX",
            "stns": "ALL",
        }
    ).encode("ascii")

    last_error: Exception | None = None

    for attempt in range(1, MAX_HTTP_TRIES + 1):
        pace_request()

        req = urllib.request.Request(
            PUBLIC_URL,
            data=payload,
            method="POST",
            headers={
                "User-Agent": "climate-dashboard-knmi-cache/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/plain,text/csv,*/*",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                raw = response.read()
                content_type = response.headers.get("content-type", "")

            text = raw.decode("utf-8", errors="replace")

            # A missing required parameter would make KNMI return the HTML form.
            if "<html" in text[:1000].lower() or "text/html" in content_type.lower():
                raise RuntimeError(
                    "KNMI lieferte HTML statt Tagesdaten. "
                    "POST-Parameter wurden offenbar nicht akzeptiert."
                )

            if "STN" not in text or "YYYYMMDD" not in text:
                raise RuntimeError(
                    "KNMI-Antwort enthält keinen erkennbaren Tagesdaten-Header."
                )

            return text

        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < MAX_HTTP_TRIES:
                wait = max(60, backoff_seconds(attempt))
                log(
                    f"KNMI {start.year}: HTTP 429; "
                    f"warte {wait}s ({attempt}/{MAX_HTTP_TRIES}) …"
                )
                time.sleep(wait)
                last_error = exc
                continue

            if 500 <= exc.code <= 599 and attempt < MAX_HTTP_TRIES:
                wait = backoff_seconds(attempt)
                log(
                    f"KNMI {start.year}: HTTP {exc.code}; "
                    f"warte {wait}s ({attempt}/{MAX_HTTP_TRIES}) …"
                )
                time.sleep(wait)
                last_error = exc
                continue

            raise RuntimeError(
                f"KNMI HTTP {exc.code}: {body[:500]}"
            ) from exc

        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
            RuntimeError,
        ) as exc:
            last_error = exc
            if attempt >= MAX_HTTP_TRIES:
                break
            wait = backoff_seconds(attempt)
            log(
                f"KNMI {start.year}: Versuch {attempt}/{MAX_HTTP_TRIES} "
                f"fehlgeschlagen: {exc}; warte {wait}s …"
            )
            time.sleep(wait)

    raise RuntimeError(
        f"KNMI {start.year}: Abruf nach {MAX_HTTP_TRIES} Versuchen fehlgeschlagen: "
        f"{last_error}"
    )


STATION_RE = re.compile(
    r"^\s*#\s*(\d{3}):\s*"
    r"([+-]?\d+(?:\.\d+)?)\s+"
    r"([+-]?\d+(?:\.\d+)?)\s+"
    r"([+-]?\d+(?:\.\d+)?)\s+"
    r"(.+?)\s*$"
)


def parse_station_metadata(text: str) -> dict[str, dict[str, Any]]:
    stations: dict[str, dict[str, Any]] = {}

    for line in text.splitlines():
        m = STATION_RE.match(line)
        if not m:
            continue

        station_id, lon, lat, elevation, name = m.groups()
        stations[station_id] = {
            "station_id": station_id,
            "name": name.strip(),
            "lat": float(lat),
            "lon": float(lon),
            "elevation_m": float(elevation),
            "country": "Netherlands",
            "country_code": "NL",
            "source": SOURCE,
        }

    return stations


def parse_number_tenths(value: str) -> float | None:
    s = value.strip()
    if not s:
        return None

    try:
        raw = float(s)
    except ValueError:
        return None

    # KNMI daily temperature fields are in 0.1 °C.
    value_c = raw / 10.0
    if not (-60.0 <= value_c <= 60.0):
        return None
    return value_c


def parse_daily_rows(text: str) -> list[tuple[str, date, float | None, float | None]]:
    header: list[str] | None = None
    rows: list[tuple[str, date, float | None, float | None]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#"):
            stripped = line.lstrip("#").strip()
            if "STN" in stripped and "YYYYMMDD" in stripped and "," in stripped:
                header = [x.strip() for x in stripped.split(",")]
            continue

        if header is None:
            continue

        parsed = next(csv.reader([raw_line]))
        parsed = [x.strip() for x in parsed]

        if len(parsed) < len(header):
            parsed += [""] * (len(header) - len(parsed))

        mapping = {
            header[i]: parsed[i]
            for i in range(min(len(header), len(parsed)))
        }

        station_id = mapping.get("STN", "").strip()
        date_raw = mapping.get("YYYYMMDD", "").strip()

        if not station_id or len(date_raw) != 8 or not date_raw.isdigit():
            continue

        try:
            d = date(
                int(date_raw[0:4]),
                int(date_raw[4:6]),
                int(date_raw[6:8]),
            )
        except ValueError:
            continue

        tn = parse_number_tenths(mapping.get("TN", ""))
        tx = parse_number_tenths(mapping.get("TX", ""))

        if tn is None and tx is None:
            continue

        rows.append((station_id.zfill(3), d, tn, tx))

    return rows


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
    old_value = float(old[0])
    old_date = str(old[1])
    return value > old_value or (value == old_value and d.isoformat() < old_date)


def better_min(old: list[Any] | None, value: float, d: date) -> bool:
    if old is None:
        return True
    old_value = float(old[0])
    old_date = str(old[1])
    return value < old_value or (value == old_value and d.isoformat() < old_date)


def consume_rows(
    records: dict[str, dict[str, Any]],
    rows: list[tuple[str, date, float | None, float | None]],
) -> int:
    consumed = 0

    for station_id, d, tn, tx in rows:
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


def make_new_progress(cutoff_year: int) -> dict[str, Any]:
    return {
        "format_version": BASELINE_FORMAT_VERSION,
        "source": SOURCE,
        "start_year": START_YEAR,
        "cutoff_year": cutoff_year,
        "next_year": START_YEAR,
        "processed_years": 0,
        "rows_with_temperature": 0,
        "inventory": {},
        "records": {},
        "complete": False,
    }


def save_progress(cache_dir: Path, cutoff_year: int, progress: dict[str, Any]) -> None:
    atomic_pickle_gzip(progress_path(cache_dir, cutoff_year), progress)
    write_status(cache_dir, cutoff_year, progress)


def write_status(cache_dir: Path, cutoff_year: int, progress: dict[str, Any]) -> None:
    records = progress.get("records", {})
    status = {
        "format_version": BASELINE_FORMAT_VERSION,
        "source": SOURCE,
        "start_year": START_YEAR,
        "cutoff_year": cutoff_year,
        "next_year": progress.get("next_year"),
        "processed_years": progress.get("processed_years", 0),
        "total_years": cutoff_year - START_YEAR + 1,
        "rows_with_temperature": progress.get("rows_with_temperature", 0),
        "station_count": len(records),
        "inventory_count": len(progress.get("inventory", {})),
        "complete": bool(progress.get("complete", False)),
        "baseline_file": str(baseline_path(cache_dir, cutoff_year)),
    }
    atomic_json(status_path(cache_dir, cutoff_year), status)


def valid_final_baseline(path: Path, cutoff_year: int) -> bool:
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
    cache_dir: Path,
    cutoff_year: int,
    *,
    force: bool = False,
    max_runtime_minutes: float = 110.0,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    final_path = baseline_path(cache_dir, cutoff_year)
    prog_path = progress_path(cache_dir, cutoff_year)
    stat_path = status_path(cache_dir, cutoff_year)

    if force:
        for p in (final_path, prog_path, stat_path):
            p.unlink(missing_ok=True)

    if not force and valid_final_baseline(final_path, cutoff_year):
        log(f"Verwende vorhandenen KNMI-Baseline-Cache: {final_path}")
        return final_path

    if not force and prog_path.exists():
        try:
            progress = load_pickle_gzip(prog_path)
            if (
                progress.get("format_version") == BASELINE_FORMAT_VERSION
                and progress.get("cutoff_year") == cutoff_year
            ):
                log(
                    "Setze KNMI-Niederlande-Basisbestand fort: "
                    f"{progress.get('processed_years', 0)} Jahre bereits verarbeitet, "
                    f"{len(progress.get('records', {}))} Stationsreihen."
                )
            else:
                progress = make_new_progress(cutoff_year)
        except Exception:
            progress = make_new_progress(cutoff_year)
    else:
        progress = make_new_progress(cutoff_year)

    total_years = cutoff_year - START_YEAR + 1
    started = time.monotonic()

    log("=== KNMI NIEDERLANDE HISTORISCHE BASELINE ===")
    log(
        f"Zeitraum {START_YEAR}-01-01 bis {cutoff_year}-12-31 | "
        f"{total_years} Jahresblöcke."
    )
    log(
        "Quelle: offizielle KNMI-Daggegevens-Skriptschnittstelle; "
        "nur TN/TX, kein großer Rohdatenbestand."
    )

    year = int(progress["next_year"])

    while year <= cutoff_year:
        elapsed_min = (time.monotonic() - started) / 60.0
        if elapsed_min >= max_runtime_minutes:
            save_progress(cache_dir, cutoff_year, progress)
            log(
                f"KNMI Laufzeitgrenze nach {elapsed_min:.1f} min erreicht. "
                "Zwischenstand gespeichert; mit force=false fortsetzen."
            )
            return prog_path

        start = date(year, 1, 1)
        end = date(year, 12, 31)

        try:
            text = request_knmi(start, end)
        except Exception:
            save_progress(cache_dir, cutoff_year, progress)
            log(
                "KNMI-Abruf fehlgeschlagen. Letzter vollständiger "
                "Jahres-Zwischenstand wurde gespeichert."
            )
            raise

        inventory = parse_station_metadata(text)
        progress["inventory"].update(inventory)

        rows = parse_daily_rows(text)
        consumed = consume_rows(progress["records"], rows)

        progress["rows_with_temperature"] += consumed
        progress["processed_years"] += 1
        progress["next_year"] = year + 1

        # Every processed year is a checkpoint: reruns lose at most one
        # in-memory HTTP response, never a completed saved year.
        save_progress(cache_dir, cutoff_year, progress)

        log(
            f"KNMI historical: {progress['processed_years']}/{total_years} Jahre "
            f"| bis {year} | {len(progress['records'])} Stationsreihen "
            f"| {progress['rows_with_temperature']:,} Temperatur-Zeilen "
            f"| dieser Lauf {((time.monotonic()-started)/60):.1f} min."
        )

        year += 1

    if not progress["records"]:
        raise RuntimeError("KNMI-Baseline enthält keine TN/TX-Stationsdaten.")

    progress["complete"] = True
    progress["next_year"] = cutoff_year + 1

    final = {
        **progress,
        "complete": True,
        "public_url": PUBLIC_URL,
        "notes": (
            "Daily KNMI station TN/TX. Temperatures converted from 0.1 °C "
            "to °C. Compact record cache; raw daily rows are not retained."
        ),
    }

    atomic_pickle_gzip(final_path, final)
    write_status(cache_dir, cutoff_year, final)

    log(
        f"KNMI NETHERLANDS OK: {len(final['records'])} Stationsreihen "
        f"mit TN/TX bis {cutoff_year} | "
        f"{final['rows_with_temperature']:,} Temperatur-Zeilen."
    )
    return final_path


def self_test() -> None:
    sample = """# SOURCE: ROYAL NETHERLANDS METEOROLOGICAL INSTITUTE (KNMI)
#
# STN      LON(east)   LAT(north)     ALT(m)  NAME
# 260:         5.177       52.101       2.00  DE BILT
# 280:         6.586       53.125       3.50  EELDE
#
# STN,YYYYMMDD,   TN,   TX
#
  260,19010101,  -25,   41
  260,19010102,  -30,   55
  280,19010102,     ,   38
"""
    meta = parse_station_metadata(sample)
    assert meta["260"]["name"] == "DE BILT"
    assert abs(meta["260"]["lat"] - 52.101) < 1e-9

    rows = parse_daily_rows(sample)
    assert len(rows) == 3
    assert rows[0][2] == -2.5
    assert rows[0][3] == 4.1
    assert rows[2][2] is None
    assert rows[2][3] == 3.8

    records: dict[str, dict[str, Any]] = {}
    consume_rows(records, rows)
    assert records["260"]["tmax_abs"] == [5.5, "1901-01-02"]
    assert records["260"]["tmin_abs"] == [-3.0, "1901-01-02"]
    assert records["260"]["calendar_tmax"]["01-01"] == [4.1, "1901-01-01"]
    assert records["280"]["observation_days"] == 1

    # Tie rule: earliest date wins.
    tie = [
        ("260", date(1902, 1, 1), -3.0, 4.1),
    ]
    consume_rows(records, tie)
    assert records["260"]["calendar_tmax"]["01-01"] == [4.1, "1901-01-01"]

    print("KNMI Netherlands historical cache self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--cache-dir",
        default=str(CACHE_DIR_DEFAULT),
    )
    parser.add_argument(
        "--cutoff-year",
        type=int,
        default=date.today().year - 1,
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        default=110.0,
    )
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.cutoff_year < START_YEAR:
        raise SystemExit(
            f"--cutoff-year muss mindestens {START_YEAR} sein."
        )

    build_baseline(
        Path(args.cache_dir),
        args.cutoff_year,
        force=args.force,
        max_runtime_minutes=args.max_runtime_minutes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
