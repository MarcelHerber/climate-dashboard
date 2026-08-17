#!/usr/bin/env python3
"""Build the historical ARSO Slovenia daily-temperature baseline through cutoff year.

Production step: historical cache only.
This script does NOT yet integrate Slovenia into the unified Europe importer.

Official ARSO source discovered and verified in the preceding probes:
  https://meteo.arso.gov.si/met/sl/agromet/data/month/

The page exposes a numeric climate-station inventory and JavaScript builds
monthly text files as:

  https://meteo.arso.gov.si/uploads/probase/www/agromet/product/form/sl/data/
      <station_id>_<YYYY><MM>.txt

Example:
  192_202607.txt  -> Ljubljana Bežigrad, July 2026

Verified file structure:
  Postaja: Ljubljana Bežigrad
  Julij 2026

  dan    etp    rr    tmin    tmax    tpov    tmin5
  1      ...           18.5    33.8    ...

Only tmin/tmax are consumed here.

Design:
- Parse the live official numeric ARSO inventory.
- Respect advertised station start/end years.
- Build one resumable task per station-month through cutoff year.
- 404 / "Ni podatkov!" are valid missing months and are marked processed.
- Transient/network failures remain pending and are retried on the next run.
- Store only compact record extrema/calendar records, matching the existing
  Europe provider cache style.
- Save progress atomically after every batch.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import html
import io
import json
import math
import os
import pickle
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, UTC
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1

SOURCE = "ARSO Slovenia agrometeorological daily month tables"
COUNTRY = "Slovenia"
COUNTRY_CODE = "SI"
NETWORK = "ARSO climate station"

FORM_URL = "https://meteo.arso.gov.si/met/sl/agromet/data/month/"
DATA_BASE = (
    "https://meteo.arso.gov.si/uploads/probase/www/agromet/"
    "product/form/sl/data/"
)

CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
UA = "climate-dashboard-arso-slovenia-cache/1.0 (+GitHub Actions)"
HTTP_TIMEOUT = 45
TRIES = 4

# Deliberately broad physical plausibility bounds for Slovenia, only intended
# to reject corrupt/sentinel values. They do not filter genuine extremes.
TMIN_MIN = -65.0
TMIN_MAX = 55.0
TMAX_MIN = -55.0
TMAX_MAX = 65.0


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"arso_slovenia_daily_baseline_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"arso_slovenia_progress_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"arso_slovenia_status_through_{cutoff_year}.json"


def atomic_pickle_gz(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as fh:
            pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_pickle_gz(path: Path) -> Any:
    with gzip.open(path, "rb") as fh:
        return pickle.load(fh)


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
        tmp.unlink(missing_ok=True)


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1250", "iso-8859-2", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def http_bytes(url: str, allow_404: bool = False) -> bytes | None:
    last: Exception | None = None

    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/plain,text/html,*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                raw = response.read()
                if not raw:
                    raise RuntimeError("Leere HTTP-Antwort")
                return raw
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            last = exc
            retryable = exc.code in {408, 429, 500, 502, 503, 504}
            if not retryable or attempt >= TRIES:
                raise
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            last = exc
            if attempt >= TRIES:
                break

        wait = min(20, attempt * 2)
        time.sleep(wait)

    raise RuntimeError(f"ARSO-Abruf fehlgeschlagen: {url}: {last}")


def strip_tags(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def parse_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text.lower() in {
        "null",
        "(null)",
        "na",
        "nan",
        "-",
    }:
        return None
    text = text.replace(",", ".")
    try:
        x = float(text)
    except ValueError:
        return None
    if not math.isfinite(x):
        return None
    return x


def parse_period(label: str) -> tuple[int | None, int | None]:
    """Parse labels such as '(1961- )', '(1961-2016)', '(2017- )'."""
    match = re.search(
        r"\(\s*((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})?\s*\)",
        label,
    )
    if not match:
        return None, None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else None
    return start, end


def parse_numeric_inventory(page: str) -> dict[str, dict[str, Any]]:
    """Extract the largest select containing 3-digit numeric station IDs."""
    selects = list(
        re.finditer(
            r"<select\b([^>]*)>(.*?)</select>",
            page,
            flags=re.I | re.S,
        )
    )

    candidates: list[list[tuple[str, str]]] = []

    for select in selects:
        body = select.group(2)
        options: list[tuple[str, str]] = []

        for opt in re.finditer(
            r"<option\b([^>]*)>(.*?)</option>",
            body,
            flags=re.I | re.S,
        ):
            attrs = opt.group(1)
            label = strip_tags(opt.group(2)).strip()
            vm = re.search(
                r"\bvalue\s*=\s*['\"]?([^'\"\s>]+)",
                attrs,
                flags=re.I,
            )
            value = html.unescape(vm.group(1)).strip() if vm else ""
            if re.fullmatch(r"\d{3}", value):
                options.append((value, label))

        if len(options) >= 10:
            candidates.append(options)

    if not candidates:
        raise RuntimeError(
            "ARSO-Stationsinventar nicht gefunden: "
            "kein Select mit numerischen 3-stelligen Stations-IDs."
        )

    options = max(candidates, key=len)
    inventory: dict[str, dict[str, Any]] = {}

    for sid, label in options:
        start_year, end_year = parse_period(label)
        name = re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()

        # IDs are the source-native station identity. Same station names with
        # different IDs are intentionally kept separate.
        inventory[sid] = {
            "id": sid,
            "name": name,
            "label": label,
            "start_year": start_year,
            "end_year": end_year,
            "lat": None,
            "lon": None,
            "elevation_m": None,
            "source": SOURCE,
            "network": NETWORK,
            "country": COUNTRY,
            "country_code": COUNTRY_CODE,
        }

    return inventory


def load_inventory() -> tuple[dict[str, dict[str, Any]], str]:
    raw = http_bytes(FORM_URL)
    assert raw is not None
    page = decode(raw)
    inventory = parse_numeric_inventory(page)
    return inventory, FORM_URL


def month_url(station_id: str, year: int, month: int) -> str:
    return f"{DATA_BASE}{station_id}_{year:04d}{month:02d}.txt"


def is_no_data(text: str) -> bool:
    cleaned = strip_tags(text).strip().lower()
    return cleaned in {
        "",
        "ni podatkov!",
        "ni podatkov",
        "no data!",
        "no data",
    }


def normalize_header(value: str) -> str:
    value = html.unescape(value).strip().lower()
    for old, new in (
        ("č", "c"),
        ("š", "s"),
        ("ž", "z"),
        ("°", ""),
    ):
        value = value.replace(old, new)
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def parse_month_text(
    text: str,
    station_id: str,
    year: int,
    month: int,
) -> list[tuple[date, float | None, float | None]]:
    """Parse ARSO monthly TXT into (date, tmin, tmax)."""
    if is_no_data(text):
        return []

    lines = text.splitlines()
    header_idx = None
    headers: list[str] = []

    for idx, line in enumerate(lines[:30]):
        if "\t" not in line:
            continue
        candidate = [normalize_header(x) for x in line.split("\t")]
        if "dan" in candidate and "tmin" in candidate and "tmax" in candidate:
            header_idx = idx
            headers = candidate
            break

    if header_idx is None:
        preview = " | ".join(x.strip() for x in lines[:8])
        raise ValueError(
            f"ARSO-Schema unerwartet für {station_id} {year:04d}-{month:02d}: "
            f"{preview[:600]}"
        )

    idx_day = headers.index("dan")
    idx_tmin = headers.index("tmin")
    idx_tmax = headers.index("tmax")
    need = max(idx_day, idx_tmin, idx_tmax)

    out: list[tuple[date, float | None, float | None]] = []

    for line in lines[header_idx + 1 :]:
        if not line.strip():
            continue

        cells = next(csv.reader([line], delimiter="\t"))
        if len(cells) <= need:
            continue

        try:
            day = int(cells[idx_day].strip())
        except (TypeError, ValueError):
            continue

        if day < 1 or day > calendar.monthrange(year, month)[1]:
            continue

        d = date(year, month, day)
        tmin = parse_float(cells[idx_tmin])
        tmax = parse_float(cells[idx_tmax])
        out.append((d, tmin, tmax))

    return out


def empty_record() -> dict[str, Any]:
    return {
        "first_date": None,
        "last_date": None,
        "observation_days": 0,
        "tmax_days": 0,
        "tmin_days": 0,
        "tmax_abs": None,
        "tmax_low_abs": None,
        "tmin_abs": None,
        "tmin_high_abs": None,
        "calendar_tmax": {},
        "calendar_tmin": {},
        # Keep the same optional fields as other Europe provider records.
        "tmax_indicator_counts": {},
        "tmin_indicator_counts": {},
    }


def better_max(old: list[Any] | None, value: float) -> bool:
    return old is None or float(value) > float(old[0])


def better_min(old: list[Any] | None, value: float) -> bool:
    return old is None or float(value) < float(old[0])


def qc_values(
    tmin: float | None,
    tmax: float | None,
    stats: dict[str, int],
) -> tuple[float | None, float | None]:
    if tmin is not None and not (TMIN_MIN <= tmin <= TMIN_MAX):
        stats["qc_rejected_tmin"] = stats.get("qc_rejected_tmin", 0) + 1
        tmin = None

    if tmax is not None and not (TMAX_MIN <= tmax <= TMAX_MAX):
        stats["qc_rejected_tmax"] = stats.get("qc_rejected_tmax", 0) + 1
        tmax = None

    if tmin is not None and tmax is not None and tmin > tmax:
        stats["qc_rejected_inconsistent_days"] = (
            stats.get("qc_rejected_inconsistent_days", 0) + 1
        )
        return None, None

    return tmin, tmax


def consume_day(
    rec: dict[str, Any],
    d: date,
    tmin: float | None,
    tmax: float | None,
) -> bool:
    if tmin is None and tmax is None:
        return False

    iso = d.isoformat()
    mmdd = d.strftime("%m-%d")

    if rec["first_date"] is None or iso < rec["first_date"]:
        rec["first_date"] = iso
    if rec["last_date"] is None or iso > rec["last_date"]:
        rec["last_date"] = iso

    rec["observation_days"] += 1

    if tmax is not None:
        rec["tmax_days"] += 1

        if better_max(rec["tmax_abs"], tmax):
            rec["tmax_abs"] = [float(tmax), iso]
        if better_min(rec["tmax_low_abs"], tmax):
            rec["tmax_low_abs"] = [float(tmax), iso]

        old = rec["calendar_tmax"].get(mmdd)
        if better_max(old, tmax):
            rec["calendar_tmax"][mmdd] = [float(tmax), iso]

    if tmin is not None:
        rec["tmin_days"] += 1

        if better_min(rec["tmin_abs"], tmin):
            rec["tmin_abs"] = [float(tmin), iso]
        if better_max(rec["tmin_high_abs"], tmin):
            rec["tmin_high_abs"] = [float(tmin), iso]

        old = rec["calendar_tmin"].get(mmdd)
        if better_min(old, tmin):
            rec["calendar_tmin"][mmdd] = [float(tmin), iso]

    return True


def candidate_tasks(
    inventory: dict[str, dict[str, Any]],
    cutoff_year: int,
) -> list[tuple[str, int, int]]:
    tasks: list[tuple[str, int, int]] = []

    for sid in sorted(inventory):
        meta = inventory[sid]
        start = meta.get("start_year")

        # The official ARSO inventory starts at 1961. If a future label cannot
        # be parsed, use 1961 conservatively instead of dropping the station.
        if not isinstance(start, int):
            start = 1961

        end = meta.get("end_year")
        if not isinstance(end, int):
            end = cutoff_year

        end = min(end, cutoff_year)
        if start > end:
            continue

        for year in range(start, end + 1):
            for month in range(1, 13):
                tasks.append((sid, year, month))

    return tasks


def task_key(task: tuple[str, int, int]) -> str:
    sid, year, month = task
    return f"{sid}:{year:04d}{month:02d}"


def fetch_month(task: tuple[str, int, int]) -> dict[str, Any]:
    sid, year, month = task
    url = month_url(sid, year, month)

    try:
        raw = http_bytes(url, allow_404=True)
    except Exception as exc:
        return {
            "task": task,
            "key": task_key(task),
            "url": url,
            "status": "error",
            "error": str(exc),
        }

    if raw is None:
        return {
            "task": task,
            "key": task_key(task),
            "url": url,
            "status": "missing_404",
            "rows": [],
        }

    text = decode(raw)

    if is_no_data(text):
        return {
            "task": task,
            "key": task_key(task),
            "url": url,
            "status": "no_data",
            "rows": [],
        }

    try:
        rows = parse_month_text(text, sid, year, month)
    except Exception as exc:
        return {
            "task": task,
            "key": task_key(task),
            "url": url,
            "status": "error",
            "error": f"Parser: {exc}",
        }

    return {
        "task": task,
        "key": task_key(task),
        "url": url,
        "status": "ok",
        "rows": rows,
    }


def aggregate_summary(
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    used = {
        sid: rec
        for sid, rec in records.items()
        if int(rec.get("observation_days", 0)) > 0
    }

    first_dates = [
        rec["first_date"]
        for rec in used.values()
        if rec.get("first_date")
    ]
    last_dates = [
        rec["last_date"]
        for rec in used.values()
        if rec.get("last_date")
    ]

    return {
        "station_count": len(used),
        "rows_with_temperature": sum(
            int(rec.get("observation_days", 0)) for rec in used.values()
        ),
        "tmax_rows": sum(
            int(rec.get("tmax_days", 0)) for rec in used.values()
        ),
        "tmin_rows": sum(
            int(rec.get("tmin_days", 0)) for rec in used.values()
        ),
        "first_date": min(first_dates) if first_dates else None,
        "last_date": max(last_dates) if last_dates else None,
    }


def make_status(
    *,
    cutoff_year: int,
    inventory: dict[str, dict[str, Any]],
    records: dict[str, dict[str, Any]],
    all_tasks_count: int,
    processed: set[str],
    counters: dict[str, int],
    failed: dict[str, str],
    complete: bool,
    baseline: Path,
    progress: Path,
    inventory_source: str,
) -> dict[str, Any]:
    summary = aggregate_summary(records)

    return {
        "source": SOURCE,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "format_version": FORMAT_VERSION,
        "cutoff_year": cutoff_year,
        "complete": bool(complete),
        "inventory_source": inventory_source,
        "inventory_count": len(inventory),
        "month_task_count": all_tasks_count,
        "processed_months": len(processed),
        "pending_months": max(0, all_tasks_count - len(processed)),
        "months_with_temperature": counters.get("months_with_temperature", 0),
        "months_no_data": counters.get("months_no_data", 0),
        "months_404": counters.get("months_404", 0),
        "failed_months_count": len(failed),
        "qc_rejected_tmin": counters.get("qc_rejected_tmin", 0),
        "qc_rejected_tmax": counters.get("qc_rejected_tmax", 0),
        "qc_rejected_inconsistent_days": counters.get(
            "qc_rejected_inconsistent_days",
            0,
        ),
        **summary,
        "baseline_file": str(baseline),
        "progress_file": str(progress),
        "updated_utc": datetime.now(UTC).isoformat(),
    }


def save_progress(
    *,
    path: Path,
    cutoff_year: int,
    inventory: dict[str, dict[str, Any]],
    records: dict[str, dict[str, Any]],
    processed: set[str],
    counters: dict[str, int],
    failed: dict[str, str],
    inventory_source: str,
) -> None:
    payload = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "cutoff_year": cutoff_year,
        "inventory_source": inventory_source,
        "inventory": inventory,
        "records": records,
        "processed_months": processed,
        "counters": counters,
        "failed_months": failed,
        "saved_utc": datetime.now(UTC).isoformat(),
    }
    atomic_pickle_gz(path, payload)


def valid_baseline(path: Path, cutoff_year: int) -> bool:
    if not path.exists():
        return False

    try:
        payload = load_pickle_gz(path)
    except Exception:
        return False

    if not isinstance(payload, dict):
        return False
    if payload.get("format_version") != FORMAT_VERSION:
        return False
    if payload.get("country_code") != COUNTRY_CODE:
        return False
    if int(payload.get("cutoff_year", -1)) != cutoff_year:
        return False
    if not payload.get("complete"):
        return False

    records = payload.get("records")
    if not isinstance(records, dict) or not records:
        return False

    return any(
        int(rec.get("observation_days", 0)) > 0
        for rec in records.values()
        if isinstance(rec, dict)
    )


def build_final_payload(
    *,
    cutoff_year: int,
    inventory: dict[str, dict[str, Any]],
    records: dict[str, dict[str, Any]],
    counters: dict[str, int],
    inventory_source: str,
) -> dict[str, Any]:
    used_records = {
        sid: rec
        for sid, rec in records.items()
        if int(rec.get("observation_days", 0)) > 0
    }

    return {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "cutoff_year": cutoff_year,
        "complete": True,
        "inventory_source": inventory_source,
        "inventory": inventory,
        "records": used_records,
        "parameters": {
            "tmax": "tmax",
            "tmin": "tmin",
            "date": "year/month from filename + dan",
            "unit": "degC",
        },
        "public_url": FORM_URL,
        "quality_note": (
            "Official ARSO monthly daily tables. Broad plausibility QC only; "
            "days with Tmin>Tmax are rejected. Missing/blank single variables "
            "remain missing while the other temperature variable is retained."
        ),
        "counters": counters,
        "built_utc": datetime.now(UTC).isoformat(),
    }


def self_test() -> int:
    sample_html = """
    <select name="postaja">
      <option value="0">Izberi postajo</option>
      <option value="192">Ljubljana Bežigrad (1961- )</option>
      <option value="097">Bilje (1962- )</option>
      <option value="164">Babno Polje (1961-2016)</option>
      <option value="048">Kredarica (1961- )</option>
      <option value="249">Novo mesto (1961- )</option>
      <option value="268">Celje Medlog (1961- )</option>
      <option value="355">Murska Sobota (1961- )</option>
      <option value="464">Portorož - letališče (1974- )</option>
      <option value="311">Maribor - letališče (1977- )</option>
      <option value="257">Črnomelj - Dobliče (1961- )</option>
    </select>
    """
    inv = parse_numeric_inventory(sample_html)
    assert len(inv) == 10
    assert inv["192"]["start_year"] == 1961
    assert inv["192"]["end_year"] is None
    assert inv["164"]["start_year"] == 1961
    assert inv["164"]["end_year"] == 2016

    assert (
        month_url("192", 2026, 7)
        == DATA_BASE + "192_202607.txt"
    )

    sample_txt = """Postaja: Ljubljana Bežigrad
Julij 2026

dan\tetp\trr\ttmin\ttmax\ttpov\ttmin5
1\t5.3\t0\t18.5\t33.8\t24.7\t15.5
2\t4.8\t0\t18.4\t29.5\t24.0\t17.4
3\t5.4\t0\t\t29.8\t24.1\t12.7
4\t5.9\t0\t15.5\t\t24.0\t11.4
"""
    rows = parse_month_text(sample_txt, "192", 2026, 7)
    assert len(rows) == 4
    assert rows[0] == (date(2026, 7, 1), 18.5, 33.8)
    assert rows[2] == (date(2026, 7, 3), None, 29.8)
    assert rows[3] == (date(2026, 7, 4), 15.5, None)

    rec = empty_record()
    stats: dict[str, int] = {}
    for d, tmin, tmax in rows:
        tmin, tmax = qc_values(tmin, tmax, stats)
        consume_day(rec, d, tmin, tmax)

    assert rec["observation_days"] == 4
    assert rec["tmax_days"] == 3
    assert rec["tmin_days"] == 3
    assert rec["tmax_abs"] == [33.8, "2026-07-01"]
    assert rec["tmax_low_abs"] == [29.5, "2026-07-02"]
    assert rec["tmin_abs"] == [15.5, "2026-07-04"]
    assert rec["tmin_high_abs"] == [18.5, "2026-07-01"]
    assert rec["calendar_tmax"]["07-01"] == [33.8, "2026-07-01"]
    assert rec["calendar_tmin"]["07-04"] == [15.5, "2026-07-04"]

    inconsistent = qc_values(25.0, 20.0, stats)
    assert inconsistent == (None, None)
    assert stats["qc_rejected_inconsistent_days"] == 1

    tasks = candidate_tasks(
        {
            "001": {
                "start_year": 2024,
                "end_year": 2025,
            }
        },
        2025,
    )
    assert len(tasks) == 24
    assert task_key(tasks[0]) == "001:202401"
    assert task_key(tasks[-1]) == "001:202512"

    log("ARSO Slovenia station-cache self-test OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cutoff-year",
        type=int,
        default=datetime.now(UTC).year - 1,
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=CACHE_DIR_DEFAULT,
    )
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=600)
    parser.add_argument("--max-runtime-minutes", type=float, default=155.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if args.cutoff_year < 1961:
        raise SystemExit("--cutoff-year muss >= 1961 sein.")
    if args.workers < 1:
        raise SystemExit("--workers muss >= 1 sein.")
    if args.batch_size < 1:
        raise SystemExit("--batch-size muss >= 1 sein.")

    cache_dir = args.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)

    baseline = baseline_path(cache_dir, args.cutoff_year)
    progress = progress_path(cache_dir, args.cutoff_year)
    status_file = status_path(cache_dir, args.cutoff_year)

    if args.force:
        for path in (baseline, progress, status_file):
            path.unlink(missing_ok=True)

    log("=== ARSO SLOWENIEN · HISTORISCHER STATIONSCACHE ===")
    log(f"Ziel: tägliche Tmin/Tmax-Baseline bis {args.cutoff_year}")
    log(f"Cache: {baseline}")
    log()

    if valid_baseline(baseline, args.cutoff_year) and not args.force:
        payload = load_pickle_gz(baseline)
        inventory = payload.get("inventory", {})
        records = payload.get("records", {})
        counters = payload.get("counters", {})
        summary = aggregate_summary(records)

        status = {
            "source": SOURCE,
            "country": COUNTRY,
            "country_code": COUNTRY_CODE,
            "format_version": FORMAT_VERSION,
            "cutoff_year": args.cutoff_year,
            "complete": True,
            "inventory_source": payload.get("inventory_source", FORM_URL),
            "inventory_count": len(inventory),
            "station_count": summary["station_count"],
            "rows_with_temperature": summary["rows_with_temperature"],
            "tmax_rows": summary["tmax_rows"],
            "tmin_rows": summary["tmin_rows"],
            "first_date": summary["first_date"],
            "last_date": summary["last_date"],
            "baseline_file": str(baseline),
            "progress_file": str(progress),
            "updated_utc": datetime.now(UTC).isoformat(),
        }
        atomic_json(status_file, status)

        log("Vorhandene vollständige ARSO-Baseline ist gültig.")
        log(json.dumps(status, indent=2, ensure_ascii=False))
        return 0

    inventory, inventory_source = load_inventory()
    log(f"Offizielles ARSO-Inventar: {len(inventory):,} Stationen")
    log(f"Quelle: {inventory_source}")

    all_tasks = candidate_tasks(inventory, args.cutoff_year)
    all_task_keys = {task_key(t) for t in all_tasks}
    log(
        f"Kandidaten bis {args.cutoff_year}: "
        f"{len(all_tasks):,} Stationsmonate"
    )

    records: dict[str, dict[str, Any]] = {
        sid: empty_record()
        for sid in inventory
    }
    processed: set[str] = set()
    counters: dict[str, int] = {
        "months_with_temperature": 0,
        "months_no_data": 0,
        "months_404": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_tmax": 0,
        "qc_rejected_inconsistent_days": 0,
    }
    failed: dict[str, str] = {}

    if progress.exists() and not args.force:
        try:
            saved = load_pickle_gz(progress)
            if (
                isinstance(saved, dict)
                and saved.get("format_version") == FORMAT_VERSION
                and saved.get("country_code") == COUNTRY_CODE
                and int(saved.get("cutoff_year", -1)) == args.cutoff_year
            ):
                saved_records = saved.get("records")
                if isinstance(saved_records, dict):
                    for sid in inventory:
                        if sid in saved_records and isinstance(
                            saved_records[sid],
                            dict,
                        ):
                            records[sid] = saved_records[sid]

                processed = set(saved.get("processed_months", set()))
                # Ignore keys no longer in the current official task universe.
                processed &= all_task_keys

                saved_counters = saved.get("counters")
                if isinstance(saved_counters, dict):
                    counters.update(
                        {
                            str(k): int(v)
                            for k, v in saved_counters.items()
                            if isinstance(v, (int, float))
                        }
                    )

                saved_failed = saved.get("failed_months")
                if isinstance(saved_failed, dict):
                    failed = {
                        str(k): str(v)
                        for k, v in saved_failed.items()
                        if str(k) in all_task_keys
                    }

                log(
                    "Zwischenstand geladen: "
                    f"{len(processed):,}/{len(all_tasks):,} Stationsmonate"
                )
        except Exception as exc:
            log(f"WARNUNG: Progress unlesbar, starte frisch: {exc}")

    pending = [
        task
        for task in all_tasks
        if task_key(task) not in processed
    ]

    if not pending:
        log("Keine offenen Stationsmonate mehr.")
    else:
        log(f"Noch offen: {len(pending):,} Stationsmonate")

    started = time.monotonic()
    processed_this_run = 0
    rows_this_run = 0
    successful_this_run = 0
    missing_this_run = 0
    errors_this_run = 0

    # Batch loop gives us frequent durable resume points.
    for batch_start in range(0, len(pending), args.batch_size):
        elapsed_min = (time.monotonic() - started) / 60.0
        if elapsed_min >= args.max_runtime_minutes:
            log(
                f"Zeitlimit erreicht ({elapsed_min:.1f} min). "
                "Zwischenstand wird gespeichert."
            )
            break

        batch = pending[
            batch_start : batch_start + args.batch_size
        ]

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_map = {
                executor.submit(fetch_month, task): task
                for task in batch
            }

            for future in as_completed(future_map):
                result = future.result()
                sid, year, month = result["task"]
                key = result["key"]
                status = result["status"]

                if status == "error":
                    failed[key] = result.get("error", "unbekannter Fehler")
                    errors_this_run += 1
                    # Do NOT mark as processed. It will be retried next run.
                    continue

                # Valid source outcomes: data, 404 or explicit no-data.
                processed.add(key)
                failed.pop(key, None)
                processed_this_run += 1

                if status == "missing_404":
                    counters["months_404"] = (
                        counters.get("months_404", 0) + 1
                    )
                    missing_this_run += 1
                    continue

                if status == "no_data":
                    counters["months_no_data"] = (
                        counters.get("months_no_data", 0) + 1
                    )
                    missing_this_run += 1
                    continue

                rec = records.setdefault(sid, empty_record())
                month_had_temperature = False

                for d, tmin, tmax in result.get("rows", []):
                    tmin, tmax = qc_values(tmin, tmax, counters)
                    if consume_day(rec, d, tmin, tmax):
                        rows_this_run += 1
                        month_had_temperature = True

                if month_had_temperature:
                    counters["months_with_temperature"] = (
                        counters.get("months_with_temperature", 0) + 1
                    )
                    successful_this_run += 1
                else:
                    counters["months_no_data"] = (
                        counters.get("months_no_data", 0) + 1
                    )
                    missing_this_run += 1

        save_progress(
            path=progress,
            cutoff_year=args.cutoff_year,
            inventory=inventory,
            records=records,
            processed=processed,
            counters=counters,
            failed=failed,
            inventory_source=inventory_source,
        )

        summary = aggregate_summary(records)
        elapsed_min = (time.monotonic() - started) / 60.0

        log(
            f"ARSO historical: {len(processed):,}/{len(all_tasks):,} Monate | "
            f"{summary['station_count']:,} Stationsreihen | "
            f"{summary['rows_with_temperature']:,} Temperatur-Tage | "
            f"dieser Lauf {elapsed_min:.1f} min"
        )

        status = make_status(
            cutoff_year=args.cutoff_year,
            inventory=inventory,
            records=records,
            all_tasks_count=len(all_tasks),
            processed=processed,
            counters=counters,
            failed=failed,
            complete=False,
            baseline=baseline,
            progress=progress,
            inventory_source=inventory_source,
        )
        atomic_json(status_file, status)

    # Re-evaluate all pending keys after the current run.
    remaining = all_task_keys - processed
    complete = not remaining

    # If network/parser errors occurred but were all later resolved in the same
    # run, they have been removed from failed. Completion is driven by keys.
    save_progress(
        path=progress,
        cutoff_year=args.cutoff_year,
        inventory=inventory,
        records=records,
        processed=processed,
        counters=counters,
        failed=failed,
        inventory_source=inventory_source,
    )

    if complete:
        final_payload = build_final_payload(
            cutoff_year=args.cutoff_year,
            inventory=inventory,
            records=records,
            counters=counters,
            inventory_source=inventory_source,
        )
        atomic_pickle_gz(baseline, final_payload)

        if not valid_baseline(baseline, args.cutoff_year):
            raise SystemExit(
                f"Finaler ARSO-Baselinecache ist ungültig: {baseline}"
            )

    status = make_status(
        cutoff_year=args.cutoff_year,
        inventory=inventory,
        records=records,
        all_tasks_count=len(all_tasks),
        processed=processed,
        counters=counters,
        failed=failed,
        complete=complete,
        baseline=baseline,
        progress=progress,
        inventory_source=inventory_source,
    )
    atomic_json(status_file, status)

    elapsed_min = (time.monotonic() - started) / 60.0

    log()
    log("=" * 88)
    log("ARSO SLOWENIEN · STATUS")
    log("=" * 88)
    log(json.dumps(status, indent=2, ensure_ascii=False))
    log()
    log(
        f"Dieser Lauf: {processed_this_run:,} erledigte Monate | "
        f"{successful_this_run:,} mit Temperatur | "
        f"{missing_this_run:,} 404/no-data | "
        f"{errors_this_run:,} temporäre Fehler | "
        f"{rows_this_run:,} Temperatur-Tage | "
        f"{elapsed_min:.1f} min"
    )

    if complete:
        log()
        log("ARSO Slowenien historische Baseline vollständig.")
        log(f"Finaler Cache: {baseline}")
    else:
        log()
        log(
            f"ARSO Slowenien noch nicht vollständig: "
            f"{len(remaining):,} Stationsmonate offen."
        )
        log(
            "Der Zwischenstand ist gespeichert. Workflow mit force=false "
            "erneut starten."
        )

        if failed:
            log("Beispiele noch fehlerhafter Monate:")
            for key, error in list(sorted(failed.items()))[:20]:
                log(f"  {key}: {error}")

    # A partial run is not a script error. The workflow's final validation step
    # decides whether another resume run is needed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
