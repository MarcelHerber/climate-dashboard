#!/usr/bin/env python3
"""
Build compact historical daily TMIN/TMAX records for Sweden from SMHI MetObs.

Source:
- SMHI MetObs CORE network
- Parameter 19: daily minimum air temperature
- Parameter 20: daily maximum air temperature
- Period: corrected-archive
- Historical baseline accepts only quality G (controlled and approved).

SMHI recommends avoiding aggressive parallel downloading of historical data,
therefore this builder is deliberately sequential and checkpointed.

The cache stores compact station record state, not raw daily time series:
- first/last accepted date
- observation days
- absolute Tmin/Tmax records
- calendar-day Tmin/Tmax records
- station metadata
- quality counters / diagnostics
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import os
import pickle
import re
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SOURCE = "SMHI Open Data"
PUBLIC_URL = "https://opendata.smhi.se/metobs/"
BASE = "https://opendata-download-metobs.smhi.se/api/version/latest"

PARAM_TMIN = 19
PARAM_TMAX = 20
NETWORK = "CORE"
ACCEPTED_HISTORICAL_QUALITY = {"G"}

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
UA = "climate-dashboard-smhi-sweden-cache/1.0"
TRIES = 6
HTTP_TIMEOUT = 150
REQUEST_SLEEP = 0.20


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"smhi_sweden_daily_baseline_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"smhi_sweden_progress_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"smhi_sweden_status_through_{cutoff_year}.json"


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
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
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
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
        tmp.unlink(missing_ok=True)


def request_bytes(url: str, *, allow_404: bool = False) -> bytes | None:
    last: Exception | None = None
    for attempt in range(1, TRIES + 1):
        if REQUEST_SLEEP:
            time.sleep(REQUEST_SLEEP)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404 and allow_404:
                return None
            if exc.code in {408, 429, 500, 502, 503, 504} and attempt < TRIES:
                wait = min(60, attempt * 5)
                log(f"WARNUNG HTTP {exc.code}; neuer Versuch in {wait}s …")
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt >= TRIES:
                break
            wait = min(45, attempt * 4)
            log(f"WARNUNG {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(f"SMHI-Abruf fehlgeschlagen: {url}: {last}")


def request_json(url: str) -> dict[str, Any]:
    raw = request_bytes(url)
    if not raw:
        raise RuntimeError(f"Leere JSON-Antwort: {url}")
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Unerwartete JSON-Struktur: {url}")
    return obj


def parameter_url(parameter: int) -> str:
    return f"{BASE}/parameter/{parameter}.json?measuringStations=core"


def archive_url(parameter: int, station: str) -> str:
    return (
        f"{BASE}/parameter/{parameter}/station/{station}/"
        "period/corrected-archive/data.csv"
    )


def station_map(parameter: int) -> dict[str, dict[str, Any]]:
    payload = request_json(parameter_url(parameter))
    rows = payload.get("station") or []
    out: dict[str, dict[str, Any]] = {}

    if not isinstance(rows, list):
        return out

    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("key", "")).strip()
        if not sid:
            continue
        measuring = str(row.get("measuringStations") or "").upper()
        if measuring and measuring != NETWORK:
            continue
        out[sid] = row
    return out


def parse_time_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()

    try:
        x = float(text)
    except (TypeError, ValueError):
        x = None

    if x is not None:
        if abs(x) > 10_000_000_000:
            x /= 1000.0
        try:
            return datetime.fromtimestamp(x, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None

    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def merge_inventory(
    tmin_stations: dict[str, dict[str, Any]],
    tmax_stations: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    common = sorted(set(tmin_stations) & set(tmax_stations))
    inventory: dict[str, dict[str, Any]] = {}

    for sid in common:
        a = tmin_stations[sid]
        b = tmax_stations[sid]
        row = b if b else a

        def number(key: str) -> float | None:
            for source in (b, a):
                try:
                    x = float(source.get(key))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(x):
                    return x
            return None

        starts = [
            d for d in (parse_time_date(a.get("from")), parse_time_date(b.get("from")))
            if d
        ]
        ends = [
            d for d in (parse_time_date(a.get("to")), parse_time_date(b.get("to")))
            if d
        ]

        inventory[sid] = {
            "id": sid,
            "name": str(row.get("name") or a.get("name") or sid).strip(),
            "country": "Sweden",
            "country_code": "SE",
            "lat": number("latitude"),
            "lon": number("longitude"),
            "elevation_m": number("height"),
            "active": bool(a.get("active")) and bool(b.get("active")),
            "owner": str(row.get("owner") or a.get("owner") or "").strip(),
            "owner_category": str(
                row.get("ownerCategory") or a.get("ownerCategory") or ""
            ).strip(),
            "network": NETWORK,
            "metadata_from": min(starts).isoformat() if starts else None,
            "metadata_to": max(ends).isoformat() if ends else None,
            "source": SOURCE,
        }

    return inventory, common


def decode_csv(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def norm(text: str) -> str:
    text = text.strip().lower()
    text = (
        text.replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
    )
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def parse_date_text(text: str) -> date | None:
    text = text.strip()
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def parse_corrected_archive(
    raw: bytes,
    *,
    cutoff_year: int | None = None,
) -> list[tuple[date, float, str]]:
    text = decode_csv(raw)
    lines = text.splitlines()

    header_index = None
    delimiter = ";"

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        lower = norm(line)
        has_date_axis = any(
            token in lower
            for token in (
                "datum",
                "date",
                "representativt_dygn",
                "representative_day",
            )
        )
        has_quality = "kvalitet" in lower or "quality" in lower
        if has_date_axis and has_quality:
            header_index = i
            delimiter = ";" if line.count(";") >= line.count(",") else ","
            break

    if header_index is None:
        raise RuntimeError("SMHI corrected-archive: Datenkopf nicht erkannt.")

    reader = csv.DictReader(
        io.StringIO("\n".join(lines[header_index:])),
        delimiter=delimiter,
    )
    headers = list(reader.fieldnames or [])
    normalized = {norm(h): h for h in headers if h is not None}

    date_col = None
    for candidate in (
        "representativt_dygn",
        "representative_day",
        "ref",
        "datum",
        "date",
        "fran_datum_tid_utc",
        "from_date_time_utc",
    ):
        if candidate in normalized:
            date_col = normalized[candidate]
            break
    if date_col is None:
        raise RuntimeError(f"SMHI CSV: Datumsspalte fehlt: {headers}")

    quality_col = None
    for candidate in ("kvalitet", "quality"):
        if candidate in normalized:
            quality_col = normalized[candidate]
            break

    excluded = {
        norm(date_col),
        "tid_utc",
        "time_utc",
        "tid",
        "time",
        "kvalitet",
        "quality",
        "fran_datum_tid_utc",
        "till_datum_tid_utc",
        "from_date_time_utc",
        "to_date_time_utc",
        "representativt_dygn",
        "representative_day",
        "ref",
        "tidsutsnitt",
    }

    value_col = None
    rows: list[tuple[date, float, str]] = []

    for row in reader:
        d = parse_date_text(str(row.get(date_col, "")))
        if d is None:
            continue
        if cutoff_year is not None and d.year > cutoff_year:
            continue

        if value_col is None:
            for h in headers:
                if h is None or norm(h) in excluded:
                    continue
                text_value = str(row.get(h, "")).strip().replace(",", ".")
                try:
                    candidate_value = float(text_value)
                except ValueError:
                    continue
                if math.isfinite(candidate_value):
                    value_col = h
                    break

        if value_col is None:
            continue

        raw_value = str(row.get(value_col, "")).strip().replace(",", ".")
        try:
            value = float(raw_value)
        except ValueError:
            continue

        if not math.isfinite(value) or value < -90 or value > 65:
            continue

        quality = str(row.get(quality_col, "") if quality_col else "").strip()
        rows.append((d, value, quality))

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
    return (
        old is None
        or value > float(old[0])
        or (value == float(old[0]) and d.isoformat() < str(old[1]))
    )


def better_min(old: list[Any] | None, value: float, d: date) -> bool:
    return (
        old is None
        or value < float(old[0])
        or (value == float(old[0]) and d.isoformat() < str(old[1]))
    )


def consume_day(
    records: dict[str, dict[str, Any]],
    sid: str,
    d: date,
    tmin: float | None,
    tmax: float | None,
) -> bool:
    if tmin is None and tmax is None:
        return False

    rec = records.setdefault(sid, empty_record())
    iso = d.isoformat()
    mmdd = d.strftime("%m-%d")

    if rec["first_date"] is None or iso < rec["first_date"]:
        rec["first_date"] = iso
    if rec["last_date"] is None or iso > rec["last_date"]:
        rec["last_date"] = iso

    rec["observation_days"] += 1

    if tmax is not None:
        tmax = round(float(tmax), 1)
        if better_max(rec["tmax_abs"], tmax, d):
            rec["tmax_abs"] = [tmax, iso]
        old = rec["calendar_tmax"].get(mmdd)
        if better_max(old, tmax, d):
            rec["calendar_tmax"][mmdd] = [tmax, iso]

    if tmin is not None:
        tmin = round(float(tmin), 1)
        if better_min(rec["tmin_abs"], tmin, d):
            rec["tmin_abs"] = [tmin, iso]
        old = rec["calendar_tmin"].get(mmdd)
        if better_min(old, tmin, d):
            rec["calendar_tmin"][mmdd] = [tmin, iso]

    return True


def merge_station_archives(
    tmin_rows: list[tuple[date, float, str]],
    tmax_rows: list[tuple[date, float, str]],
    *,
    accepted_quality: set[str],
) -> tuple[list[tuple[date, float | None, float | None]], dict[str, int]]:
    qcounts: dict[str, int] = {}
    by_day: dict[date, dict[str, float]] = {}

    for element, rows in (("TMIN", tmin_rows), ("TMAX", tmax_rows)):
        for d, value, quality in rows:
            q = quality or "(leer)"
            qcounts[q] = qcounts.get(q, 0) + 1
            if quality not in accepted_quality:
                continue
            by_day.setdefault(d, {})[element] = value

    merged = []
    for d in sorted(by_day):
        values = by_day[d]
        merged.append((d, values.get("TMIN"), values.get("TMAX")))

    return merged, qcounts


def initial_progress(cutoff_year: int) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "cutoff_year": cutoff_year,
        "stage": "inventory",
        "inventory": {},
        "station_ids": [],
        "processed_station_ids": [],
        "records": {},
        "archive_station_count": 0,
        "rows_with_temperature": 0,
        "quality_counts": {},
        "archive_first_date": None,
        "archive_last_date": None,
        "complete": False,
    }


def update_quality_counts(target: dict[str, int], incoming: dict[str, int]) -> None:
    for key, value in incoming.items():
        target[key] = int(target.get(key, 0)) + int(value)


def write_status(cache_dir: Path, cutoff_year: int, progress: dict[str, Any]) -> None:
    inventory = progress.get("inventory", {})
    records = progress.get("records", {})
    status = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "cutoff_year": cutoff_year,
        "stage": progress.get("stage"),
        "complete": bool(progress.get("complete")),
        "inventory_count": len(inventory),
        "station_candidates": len(progress.get("station_ids", [])),
        "processed_stations": len(progress.get("processed_station_ids", [])),
        "archive_station_count": int(progress.get("archive_station_count", 0)),
        "station_count": len(records),
        "rows_with_temperature": int(progress.get("rows_with_temperature", 0)),
        "quality_counts": progress.get("quality_counts", {}),
        "accepted_historical_quality": sorted(ACCEPTED_HISTORICAL_QUALITY),
        "archive_first_date": progress.get("archive_first_date"),
        "archive_last_date": progress.get("archive_last_date"),
        "baseline_file": str(baseline_path(cache_dir, cutoff_year)),
    }
    atomic_json(status_path(cache_dir, cutoff_year), status)


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
            and obj.get("format_version") == FORMAT_VERSION
            and obj.get("cutoff_year") == cutoff_year
            and obj.get("complete") is True
            and obj.get("records")
        )
    except Exception:
        return False


def load_baseline(cache_dir: Path, cutoff_year: int) -> dict[str, Any]:
    path = baseline_path(cache_dir, cutoff_year)
    if not valid_final(path, cutoff_year):
        raise RuntimeError(f"SMHI-Schweden-Baseline fehlt/unvollständig: {path}")
    obj = load_pickle_gzip(path)
    assert isinstance(obj, dict)
    return obj


def runtime_reached(start: float, max_minutes: float) -> bool:
    return (time.monotonic() - start) / 60.0 >= max_minutes


def build_baseline(
    cache_dir: Path,
    cutoff_year: int,
    *,
    force: bool = False,
    max_runtime_minutes: float = 140.0,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    final = baseline_path(cache_dir, cutoff_year)
    prog_path = progress_path(cache_dir, cutoff_year)

    if force:
        final.unlink(missing_ok=True)
        prog_path.unlink(missing_ok=True)
        status_path(cache_dir, cutoff_year).unlink(missing_ok=True)

    if not force and valid_final(final, cutoff_year):
        log(f"Verwende vorhandenen SMHI-Baselinecache: {final}")
        return final

    if not force and prog_path.exists():
        try:
            progress = load_pickle_gzip(prog_path)
            if (
                progress.get("format_version") != FORMAT_VERSION
                or progress.get("cutoff_year") != cutoff_year
            ):
                progress = initial_progress(cutoff_year)
        except Exception:
            progress = initial_progress(cutoff_year)
    else:
        progress = initial_progress(cutoff_year)

    start = time.monotonic()

    log("=== SMHI SCHWEDEN HISTORISCHE BASELINE ===")
    log(
        f"CORE-Netz | Tmin Parameter {PARAM_TMIN} | Tmax Parameter {PARAM_TMAX} | "
        f"corrected-archive | nur Qualität G | Cutoff {cutoff_year}"
    )

    if progress["stage"] == "inventory":
        tmin_stations = station_map(PARAM_TMIN)
        tmax_stations = station_map(PARAM_TMAX)
        inventory, common = merge_inventory(tmin_stations, tmax_stations)

        if not common:
            raise RuntimeError("Keine gemeinsamen SMHI CORE Tmin/Tmax-Stationen.")

        progress["inventory"] = inventory
        progress["station_ids"] = common
        progress["stage"] = "archives"
        save_progress(cache_dir, cutoff_year, progress)

        log(
            f"SMHI Inventar: Tmin {len(tmin_stations)} | Tmax {len(tmax_stations)} | "
            f"gemeinsam {len(common)}."
        )

    if progress["stage"] == "archives":
        done = set(progress.get("processed_station_ids", []))
        station_ids = progress["station_ids"]

        for idx, sid in enumerate(station_ids, 1):
            if sid in done:
                continue

            raw_tmin = request_bytes(archive_url(PARAM_TMIN, sid), allow_404=True)
            raw_tmax = request_bytes(archive_url(PARAM_TMAX, sid), allow_404=True)

            if raw_tmin and raw_tmax:
                try:
                    tmin_rows = parse_corrected_archive(
                        raw_tmin, cutoff_year=cutoff_year
                    )
                    tmax_rows = parse_corrected_archive(
                        raw_tmax, cutoff_year=cutoff_year
                    )
                except RuntimeError as exc:
                    log(f"WARNUNG Station {sid}: {exc}")
                    tmin_rows, tmax_rows = [], []

                merged, qcounts = merge_station_archives(
                    tmin_rows,
                    tmax_rows,
                    accepted_quality=ACCEPTED_HISTORICAL_QUALITY,
                )
                update_quality_counts(progress["quality_counts"], qcounts)

                station_used = False
                for d, tn, tx in merged:
                    if consume_day(progress["records"], sid, d, tn, tx):
                        progress["rows_with_temperature"] += 1
                        station_used = True

                        iso = d.isoformat()
                        if (
                            progress["archive_first_date"] is None
                            or iso < progress["archive_first_date"]
                        ):
                            progress["archive_first_date"] = iso
                        if (
                            progress["archive_last_date"] is None
                            or iso > progress["archive_last_date"]
                        ):
                            progress["archive_last_date"] = iso

                if station_used:
                    progress["archive_station_count"] += 1

            progress["processed_station_ids"].append(sid)
            done.add(sid)

            # Save every station: network jobs can safely resume after any interruption.
            save_progress(cache_dir, cutoff_year, progress)

            if len(done) % 10 == 0 or len(done) == len(station_ids):
                log(
                    f"SMHI Archive: {len(done)}/{len(station_ids)} Stationen geprüft | "
                    f"{progress['archive_station_count']} mit G-Archivdaten | "
                    f"{len(progress['records'])} Stationsreihen | "
                    f"{progress['rows_with_temperature']:,} Stationstage."
                )

            if runtime_reached(start, max_runtime_minutes):
                log(
                    "Laufzeitgrenze erreicht. Zwischenstand wurde gespeichert; "
                    "Workflow mit force=false erneut starten."
                )
                return prog_path

        progress["stage"] = "finalize"

    if progress["stage"] == "finalize":
        if not progress["records"]:
            raise RuntimeError("SMHI-Schweden-Baseline enthält keine Datensätze.")

        progress["complete"] = True
        progress["stage"] = "complete"

        final_payload = {
            **progress,
            "complete": True,
            "public_url": PUBLIC_URL,
            "parameters": {
                "tmin": PARAM_TMIN,
                "tmax": PARAM_TMAX,
            },
            "network": NETWORK,
            "historical_period": "corrected-archive",
            "historical_quality_policy": (
                "Only quality G (controlled and approved) is used for "
                "historical record baselines. Y values are retained only in "
                "diagnostic quality counts and excluded from record state."
            ),
        }

        # Lists useful for checkpointing are not needed in the final compact file.
        final_payload.pop("processed_station_ids", None)
        final_payload.pop("station_ids", None)

        atomic_pickle_gzip(final, final_payload)
        write_status(cache_dir, cutoff_year, final_payload)
        prog_path.unlink(missing_ok=True)

        log()
        log("=== SMHI SWEDEN BASELINE SUMMARY ===")
        log(f"Stationsreihen: {len(final_payload['records'])}")
        log(
            f"Archivstationen mit kontrollierten Daten: "
            f"{final_payload['archive_station_count']}"
        )
        log(f"Stationstage: {final_payload['rows_with_temperature']:,}")
        log(
            f"Datenzeitraum: {final_payload['archive_first_date']} bis "
            f"{final_payload['archive_last_date']}"
        )
        log(f"Qualitätscodes gesamt: {final_payload['quality_counts']}")
        log(f"Output: {final}")
        log("SMHI Sweden Baseline OK.")
        return final

    save_progress(cache_dir, cutoff_year, progress)
    return prog_path


def self_test() -> None:
    sample = """Stationsnamn;Rörbäcksnäs
Stationsnummer;112080

Från Datum Tid (UTC);Till Datum Tid (UTC);Representativt dygn;Lufttemperatur;Kvalitet;;Tidsutsnitt:
1951-01-01 18:00:00;1951-01-02 18:00:00;1951-01-02;-22.4;G;;1 dygn
1951-01-02 18:00:00;1951-01-03 18:00:00;1951-01-03;-19.8;Y;;1 dygn
"""
    rows = parse_corrected_archive(sample.encode("utf-8"), cutoff_year=1951)
    assert rows == [
        (date(1951, 1, 2), -22.4, "G"),
        (date(1951, 1, 3), -19.8, "Y"),
    ]

    merged, counts = merge_station_archives(
        rows,
        [
            (date(1951, 1, 2), -5.0, "G"),
            (date(1951, 1, 3), -4.0, "Y"),
        ],
        accepted_quality={"G"},
    )
    assert merged == [(date(1951, 1, 2), -22.4, -5.0)]
    assert counts == {"G": 2, "Y": 2}

    records: dict[str, dict[str, Any]] = {}
    assert consume_day(
        records, "112080", date(1951, 1, 2), -22.4, -5.0
    )
    assert records["112080"]["tmin_abs"] == [-22.4, "1951-01-02"]
    assert records["112080"]["tmax_abs"] == [-5.0, "1951-01-02"]

    print("SMHI Sweden historical cache self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--cutoff-year", type=int, default=date.today().year - 1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-runtime-minutes", type=float, default=140.0)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_baseline(
        Path(args.cache_dir),
        args.cutoff_year,
        force=args.force,
        max_runtime_minutes=args.max_runtime_minutes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
