#!/usr/bin/env python3
"""Build a compact Met Éireann historical daily TMIN/TMAX cache for Ireland.

Source:
  Met Éireann Climate Data Online / StationDetails.csv
  Daily station files dly<station>.csv

Important:
- "maxtp" = daily maximum AIR temperature in °C.
- "mintp" = daily minimum AIR temperature in °C.
- "gmin"/"igmin" are grass-minimum fields and are deliberately ignored.
- The Met Éireann StationDetails.csv header "station name" contains the numeric
  station identifier, while "name" contains the actual station name.
- The one StationDetails entry in County Antrim is excluded so this cache
  represents the Republic of Ireland (IE), not Northern Ireland / UK.
- Daily files may contain the current year; this baseline keeps data only
  through cutoff_year (normally previous calendar year).

The cache is intentionally compact. For each station it stores:
- absolute TMAX/TMIN extrema,
- calendar-day TMAX/TMIN extrema,
- first/last valid temperature date,
- observation-day count,
- basic station metadata.

Progress is written after each batch so rerunning the workflow with force=false
continues from the last successfully processed stations.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

SOURCE = "Met Éireann Climate Data Online"
COUNTRY = "Ireland"
COUNTRY_CODE = "IE"
PUBLIC_URL = "https://www.met.ie/climate/available-data/historical-data"
STATION_DETAILS_URLS = (
    "https://clidata.met.ie/cli/climate_data/webdata/StationDetails.csv",
    "https://cli.fusio.net/cli/climate_data/webdata/StationDetails.csv",
)
DAILY_BASES = (
    # Current official Met Éireann host. The old cli.fusio.net mirror is
    # deliberately NOT used here: GitHub runners repeatedly report
    # "Network is unreachable" for that legacy mirror. If both official
    # clidata paths return HTTP 404, the station is treated as having no
    # downloadable daily file instead of being blocked by the legacy mirror.
    "https://clidata.met.ie/cli/climate_data/webdata",
    # Some catalogue entries historically used the webdatac path.
    "https://clidata.met.ie/cli/climate_data/webdatac",
)

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
UA = "climate-dashboard-met-eireann-ireland-cache/1.0"
HTTP_TIMEOUT = 90
TRIES = 4

# Very broad plausibility envelope, intentionally wider than Irish records.
TMAX_MIN = -45.0
TMAX_MAX = 50.0
TMIN_MIN = -50.0
TMIN_MAX = 45.0

# Republic of Ireland only. StationDetails currently contains one Antrim entry.
NI_COUNTIES = {
    "antrim", "armagh", "down", "fermanagh", "londonderry", "derry", "tyrone"
}


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"met_eireann_ireland_daily_baseline_through_{cutoff_year}_v{FORMAT_VERSION}.pkl.gz"


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"met_eireann_ireland_progress_through_{cutoff_year}_v{FORMAT_VERSION}.pkl.gz"


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"met_eireann_ireland_status_through_{cutoff_year}.json"


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
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
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
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
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
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
                "Accept": "text/csv,text/plain,*/*",
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
        wait = min(20, 2 * attempt)
        log(f"WARNUNG Met Éireann: {last}; neuer Versuch in {wait}s …")
        time.sleep(wait)
    raise RuntimeError(f"Met-Éireann-Abruf fehlgeschlagen: {url}: {last}")


def fetch_first(urls: tuple[str, ...]) -> tuple[str, bytes]:
    errors: list[str] = []
    for url in urls:
        try:
            raw = http_bytes(url)
            assert raw is not None
            return url, raw
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Keine StationDetails-Quelle erreichbar:\n" + "\n".join(errors))


def norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").strip().lower())


def parse_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"null", "(null)", "na", "nan"}:
        return None
    text = text.replace(",", ".")
    try:
        x = float(text)
    except ValueError:
        return None
    if not math.isfinite(x):
        return None
    return x


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def empty_record() -> dict[str, Any]:
    return {
        "first_date": None,
        "last_date": None,
        "observation_days": 0,
        "tmax_abs": None,
        "tmin_abs": None,
        "calendar_tmax": {},
        "calendar_tmin": {},
        "tmax_indicator_counts": {},
        "tmin_indicator_counts": {},
    }


def better_max(old: list[Any] | None, value: float) -> bool:
    return old is None or float(value) > float(old[0])


def better_min(old: list[Any] | None, value: float) -> bool:
    return old is None or float(value) < float(old[0])


def consume_day(rec: dict[str, Any], d: date, tmin: float | None, tmax: float | None) -> bool:
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
        if better_max(rec["tmax_abs"], tmax):
            rec["tmax_abs"] = [float(tmax), iso]
        old = rec["calendar_tmax"].get(mmdd)
        if better_max(old, tmax):
            rec["calendar_tmax"][mmdd] = [float(tmax), iso]

    if tmin is not None:
        if better_min(rec["tmin_abs"], tmin):
            rec["tmin_abs"] = [float(tmin), iso]
        old = rec["calendar_tmin"].get(mmdd)
        if better_min(old, tmin):
            rec["calendar_tmin"][mmdd] = [float(tmin), iso]

    return True


def qc_values(
    tmin: float | None,
    tmax: float | None,
    stats: dict[str, int],
) -> tuple[float | None, float | None]:
    if tmax is not None and not (TMAX_MIN <= tmax <= TMAX_MAX):
        stats["qc_rejected_tmax"] = stats.get("qc_rejected_tmax", 0) + 1
        tmax = None
    if tmin is not None and not (TMIN_MIN <= tmin <= TMIN_MAX):
        stats["qc_rejected_tmin"] = stats.get("qc_rejected_tmin", 0) + 1
        tmin = None
    if tmin is not None and tmax is not None and tmin > tmax:
        stats["qc_rejected_inconsistent_days"] = stats.get("qc_rejected_inconsistent_days", 0) + 1
        return None, None
    return tmin, tmax


def load_inventory() -> tuple[dict[str, dict[str, Any]], int, str]:
    source_url, raw = fetch_first(STATION_DETAILS_URLS)
    text = decode(raw)
    rows = list(csv.reader(io.StringIO(text), delimiter=","))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise RuntimeError("StationDetails.csv ist leer oder unlesbar.")

    header = [c.strip().lstrip("\ufeff") for c in rows[0]]
    hnorm = [norm(x) for x in header]

    def exact(name: str) -> int | None:
        n = norm(name)
        for i, h in enumerate(hnorm):
            if h == n:
                return i
        return None

    # Met Éireann special naming:
    # "station name" = numeric station identifier
    # "name"         = real station name
    idx_station = exact("station name")
    idx_name = exact("name")
    idx_county = exact("county")
    idx_height = exact("height(m)")
    idx_lat = exact("latitude")
    idx_lon = exact("longitude")
    idx_open = exact("open year")
    idx_close = exact("close year")

    if idx_station is None or idx_name is None:
        raise RuntimeError(
            f"StationDetails-Schema unerwartet. Header: {' | '.join(header)}"
        )

    inventory: dict[str, dict[str, Any]] = {}
    excluded_ni = 0

    for row in rows[1:]:
        def cell(i: int | None) -> str:
            return row[i].strip() if i is not None and i < len(row) else ""

        sid = cell(idx_station)
        if not re.fullmatch(r"\d+", sid or ""):
            continue

        county = cell(idx_county)
        if norm(county) in {norm(x) for x in NI_COUNTIES}:
            excluded_ni += 1
            continue

        meta = {
            "id": sid,
            "name": cell(idx_name),
            "county": county,
            "lat": parse_float(cell(idx_lat)),
            "lon": parse_float(cell(idx_lon)),
            "elevation_m": parse_float(cell(idx_height)),
            "open_year": cell(idx_open) or None,
            "close_year": None if cell(idx_close).lower() in {"", "(null)", "null"} else cell(idx_close),
            "source": SOURCE,
            "network": "Met Éireann climate station",
            "country": COUNTRY,
            "country_code": COUNTRY_CODE,
        }

        # In case an identifier ever appears more than once, keep one metadata
        # record while preserving the earliest opening and latest closing span.
        if sid in inventory:
            old = inventory[sid]
            years = [y for y in (old.get("open_year"), meta.get("open_year")) if y and str(y).isdigit()]
            if years:
                old["open_year"] = str(min(map(int, years)))
            if old.get("close_year") in {None, ""} or meta.get("close_year") in {None, ""}:
                old["close_year"] = None
            else:
                try:
                    old["close_year"] = str(max(int(old["close_year"]), int(meta["close_year"])))
                except Exception:
                    pass
            if not old.get("name") and meta.get("name"):
                old["name"] = meta["name"]
        else:
            inventory[sid] = meta

    return inventory, excluded_ni, source_url


def find_daily_header(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        s = line.strip().lstrip("\ufeff").lower()
        if re.match(r"^date\s*[,;\t]", s):
            return i
    return None


def indicator_before(header: list[str], target_index: int) -> int | None:
    if target_index > 0 and norm(header[target_index - 1]) == "ind":
        return target_index - 1
    return None


def parse_daily_file(
    raw: bytes,
    cutoff_year: int,
    qc_stats: dict[str, int],
) -> dict[str, Any]:
    text = decode(raw)
    lines = text.splitlines()
    header_i = find_daily_header(lines)
    if header_i is None:
        raise RuntimeError("Messdaten-Header 'date,...' nicht gefunden.")

    csv_text = "\n".join(lines[header_i:])
    first_line = lines[header_i]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    rows = list(csv.reader(io.StringIO(csv_text), delimiter=delimiter))
    if not rows:
        raise RuntimeError("Messdatenblock leer.")

    header = [c.strip().lstrip("\ufeff") for c in rows[0]]
    hn = [norm(x) for x in header]

    def col(name: str) -> int | None:
        n = norm(name)
        for i, h in enumerate(hn):
            if h == n:
                return i
        return None

    date_i = col("date")
    tx_i = col("maxtp")
    tn_i = col("mintp")

    if date_i is None:
        raise RuntimeError(f"Datumsspalte fehlt. Header: {' | '.join(header)}")

    # A daily file may be rainfall-only. That is a valid file, but not useful
    # for this temperature cache.
    if tx_i is None and tn_i is None:
        return {
            "record": None,
            "has_temperature_columns": False,
            "header": header,
            "rows_total": max(0, len(rows) - 1),
        }

    tx_ind_i = indicator_before(header, tx_i) if tx_i is not None else None
    tn_ind_i = indicator_before(header, tn_i) if tn_i is not None else None

    rec = empty_record()
    local_qc = {
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
    }

    def cell(row: list[str], i: int | None) -> str:
        return row[i].strip() if i is not None and i < len(row) else ""

    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        d = parse_date(cell(row, date_i))
        if d is None or d.year > cutoff_year:
            continue

        tx = parse_float(cell(row, tx_i))
        tn = parse_float(cell(row, tn_i))

        tn, tx = qc_values(tn, tx, local_qc)
        if tn is None and tx is None:
            continue

        if tx is not None and tx_ind_i is not None:
            code = cell(row, tx_ind_i) or "(blank)"
            rec["tmax_indicator_counts"][code] = rec["tmax_indicator_counts"].get(code, 0) + 1
        if tn is not None and tn_ind_i is not None:
            code = cell(row, tn_ind_i) or "(blank)"
            rec["tmin_indicator_counts"][code] = rec["tmin_indicator_counts"].get(code, 0) + 1

        consume_day(rec, d, tn, tx)

    for key, val in local_qc.items():
        qc_stats[key] = qc_stats.get(key, 0) + int(val)

    return {
        "record": rec if rec["observation_days"] > 0 else None,
        "has_temperature_columns": True,
        "header": header,
        "rows_total": max(0, len(rows) - 1),
    }


def daily_urls(sid: str) -> list[str]:
    return [f"{base}/dly{sid}.csv" for base in DAILY_BASES]


def fetch_station_daily(
    sid: str,
    cutoff_year: int,
) -> dict[str, Any]:
    urls = daily_urls(sid)
    transient_errors: list[str] = []
    seen_404 = 0

    for url in urls:
        try:
            raw = http_bytes(url, allow_404=True)
            if raw is None:
                seen_404 += 1
                continue

            qc_stats = {
                "qc_rejected_tmax": 0,
                "qc_rejected_tmin": 0,
                "qc_rejected_inconsistent_days": 0,
            }
            parsed = parse_daily_file(raw, cutoff_year, qc_stats)
            return {
                "status": "ok",
                "sid": sid,
                "url": url,
                "source_base": url.rsplit("/", 1)[0],
                "record": parsed["record"],
                "has_temperature_columns": parsed["has_temperature_columns"],
                "rows_total": parsed["rows_total"],
                "qc": qc_stats,
            }
        except urllib.error.HTTPError as exc:
            # Non-404 HTTP errors are not silently converted to "missing".
            transient_errors.append(f"{url}: HTTP {exc.code}")
        except Exception as exc:
            transient_errors.append(f"{url}: {exc}")

    if seen_404 == len(urls):
        return {"status": "missing", "sid": sid}

    if transient_errors:
        raise RuntimeError("; ".join(transient_errors))

    return {"status": "missing", "sid": sid}


def initial_progress(cutoff_year: int) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "cutoff_year": cutoff_year,
        "complete": False,
        "inventory": {},
        "records": {},
        "processed_station_ids": [],
        "daily_file_station_ids": [],
        "missing_daily_station_ids": [],
        "daily_without_temperature_ids": [],
        "source_base_counts": {},
        "rows_with_temperature": 0,
        "first_date": None,
        "last_date": None,
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
        "excluded_northern_ireland_inventory_rows": 0,
        "station_details_url": None,
    }


def valid_final(path: Path, cutoff_year: int) -> bool:
    if not path.exists():
        return False
    try:
        obj = load_pickle_gzip(path)
    except Exception:
        return False
    return (
        isinstance(obj, dict)
        and obj.get("format_version") == FORMAT_VERSION
        and obj.get("cutoff_year") == cutoff_year
        and obj.get("complete") is True
        and len(obj.get("records", {})) > 0
    )


def refresh_summary(progress: dict[str, Any]) -> None:
    records = progress.get("records", {})
    progress["rows_with_temperature"] = sum(
        int(rec.get("observation_days", 0)) for rec in records.values()
    )
    firsts = [rec.get("first_date") for rec in records.values() if rec.get("first_date")]
    lasts = [rec.get("last_date") for rec in records.values() if rec.get("last_date")]
    progress["first_date"] = min(firsts) if firsts else None
    progress["last_date"] = max(lasts) if lasts else None


def write_status(cache_dir: Path, cutoff_year: int, payload: dict[str, Any]) -> None:
    atomic_json(
        status_path(cache_dir, cutoff_year),
        {
            "source": SOURCE,
            "country": COUNTRY,
            "country_code": COUNTRY_CODE,
            "format_version": FORMAT_VERSION,
            "cutoff_year": cutoff_year,
            "complete": bool(payload.get("complete")),
            "baseline_file": str(baseline_path(cache_dir, cutoff_year)),
            "inventory_count": len(payload.get("inventory", {})),
            "station_count": len(payload.get("records", {})),
            "processed_station_count": len(payload.get("processed_station_ids", [])),
            "daily_files_found": len(payload.get("daily_file_station_ids", [])),
            "daily_files_missing": len(payload.get("missing_daily_station_ids", [])),
            "daily_files_without_temperature": len(payload.get("daily_without_temperature_ids", [])),
            "rows_with_temperature": int(payload.get("rows_with_temperature", 0)),
            "first_date": payload.get("first_date"),
            "last_date": payload.get("last_date"),
            "qc_rejected_tmax": int(payload.get("qc_rejected_tmax", 0)),
            "qc_rejected_tmin": int(payload.get("qc_rejected_tmin", 0)),
            "qc_rejected_inconsistent_days": int(payload.get("qc_rejected_inconsistent_days", 0)),
            "excluded_northern_ireland_inventory_rows": int(
                payload.get("excluded_northern_ireland_inventory_rows", 0)
            ),
            "source_base_counts": payload.get("source_base_counts", {}),
            "station_details_url": payload.get("station_details_url"),
        },
    )


def build_baseline(
    cache_dir: Path,
    cutoff_year: int,
    force: bool = False,
    workers: int = 12,
    batch_size: int = 100,
    max_runtime_minutes: float = 155.0,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    final = baseline_path(cache_dir, cutoff_year)
    prog_file = progress_path(cache_dir, cutoff_year)

    if force:
        final.unlink(missing_ok=True)
        prog_file.unlink(missing_ok=True)
        status_path(cache_dir, cutoff_year).unlink(missing_ok=True)

    if not force and valid_final(final, cutoff_year):
        log(f"Verwende vorhandenen Met-Éireann-Irland-Baselinecache: {final}")
        return final

    if not force and prog_file.exists():
        try:
            progress = load_pickle_gzip(prog_file)
            if (
                progress.get("format_version") != FORMAT_VERSION
                or progress.get("cutoff_year") != cutoff_year
            ):
                progress = initial_progress(cutoff_year)
        except Exception:
            progress = initial_progress(cutoff_year)
    else:
        progress = initial_progress(cutoff_year)

    inventory, excluded_ni, station_details_url = load_inventory()
    progress["inventory"] = inventory
    progress["excluded_northern_ireland_inventory_rows"] = excluded_ni
    progress["station_details_url"] = station_details_url

    processed = set(progress.get("processed_station_ids", []))
    pending = [sid for sid in sorted(inventory, key=lambda x: int(x)) if sid not in processed]

    log("=== MET ÉIREANN IRLAND HISTORISCHE BASELINE ===")
    log(f"Ziel: Lufttemperatur TMAX=maxtp und TMIN=mintp bis {cutoff_year}")
    log(f"StationDetails: {station_details_url}")
    log(f"Inventar Republik Irland: {len(inventory):,}")
    log(f"Ausgeschlossene Nordirland-Zeilen: {excluded_ni:,}")
    log(f"Bereits verarbeitet: {len(processed):,}")
    log(f"Noch offen: {len(pending):,}")
    log("gmin/igmin werden NICHT als Tmin verwendet.")

    # Met Éireann is more reliable with moderate parallelism from GitHub
    # runners. Keep the CLI option for compatibility, but cap the effective
    # concurrency here.
    workers = max(1, min(int(workers), 8))
    batch_size = max(workers, int(batch_size))
    started = time.monotonic()
    deferred_errors: dict[str, str] = {}

    while pending:
        if (time.monotonic() - started) / 60 >= max_runtime_minutes:
            refresh_summary(progress)
            atomic_pickle_gzip(prog_file, progress)
            write_status(cache_dir, cutoff_year, progress)
            raise RuntimeError(
                "Met-Éireann-Laufzeitgrenze erreicht; Zwischenstand gespeichert. "
                "Workflow mit force=false erneut starten."
            )

        batch = pending[:batch_size]
        errors: list[tuple[str, str]] = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(fetch_station_daily, sid, cutoff_year): sid for sid in batch
            }
            for fut in as_completed(futures):
                sid = futures[fut]
                try:
                    result = fut.result()
                    if result["status"] == "missing":
                        if sid not in progress["missing_daily_station_ids"]:
                            progress["missing_daily_station_ids"].append(sid)
                    else:
                        if sid not in progress["daily_file_station_ids"]:
                            progress["daily_file_station_ids"].append(sid)

                        base = result.get("source_base") or "(unknown)"
                        progress["source_base_counts"][base] = (
                            progress["source_base_counts"].get(base, 0) + 1
                        )

                        if result.get("has_temperature_columns"):
                            rec = result.get("record")
                            if rec is not None:
                                progress["records"][sid] = rec
                            else:
                                if sid not in progress["daily_without_temperature_ids"]:
                                    progress["daily_without_temperature_ids"].append(sid)
                        else:
                            if sid not in progress["daily_without_temperature_ids"]:
                                progress["daily_without_temperature_ids"].append(sid)

                        qc = result.get("qc", {})
                        for key in (
                            "qc_rejected_tmax",
                            "qc_rejected_tmin",
                            "qc_rejected_inconsistent_days",
                        ):
                            progress[key] = progress.get(key, 0) + int(qc.get(key, 0))

                    if sid not in processed:
                        progress["processed_station_ids"].append(sid)
                        processed.add(sid)
                except Exception as exc:
                    errors.append((sid, str(exc)))

        refresh_summary(progress)
        atomic_pickle_gzip(prog_file, progress)
        write_status(cache_dir, cutoff_year, progress)

        log(
            f"Fortschritt: {len(processed):,}/{len(inventory):,} Stationen | "
            f"Temperaturreihen {len(progress['records']):,} | "
            f"Daily-Dateien {len(progress['daily_file_station_ids']):,} | "
            f"404/fehlend {len(progress['missing_daily_station_ids']):,} | "
            f"Fehler {len(errors):,}"
        )

        if errors:
            for sid, msg in errors:
                deferred_errors[sid] = msg
            sample = "; ".join(f"{sid}: {msg}" for sid, msg in errors[:5])
            log(
                f"WARNUNG: {len(errors)} Station(en) in diesem Batch vorerst "
                f"zurückgestellt. Der Lauf arbeitet mit den übrigen Stationen weiter. "
                f"Beispiele: {sample}"
            )

        # Always advance past the attempted batch. Failed IDs stay unprocessed
        # and therefore automatically become the only open IDs on a later
        # force=false run, while successful/missing stations never block again.
        pending = [sid for sid in pending[len(batch):] if sid not in processed]

    # If transient failures remain after the complete sweep, persist their IDs
    # and stop only now. The next force=false run then retries just those IDs.
    if deferred_errors:
        progress["deferred_error_station_ids"] = sorted(
            deferred_errors, key=lambda x: int(x)
        )
        progress["deferred_errors"] = {
            sid: deferred_errors[sid]
            for sid in progress["deferred_error_station_ids"]
        }
        refresh_summary(progress)
        atomic_pickle_gzip(prog_file, progress)
        write_status(cache_dir, cutoff_year, progress)

        sample = "; ".join(
            f"{sid}: {deferred_errors[sid]}"
            for sid in progress["deferred_error_station_ids"][:8]
        )
        raise RuntimeError(
            f"Met Éireann: Der komplette offene Stationsbestand wurde abgearbeitet, "
            f"aber {len(deferred_errors)} Station(en) hatten weiterhin einen "
            f"temporären Download/Parser-Fehler. Alle anderen Stationen sind "
            f"gespeichert. Workflow mit force=false erneut starten; dann werden "
            f"nur diese noch offenen IDs erneut versucht. Beispiele: {sample}"
        )

    progress.pop("deferred_error_station_ids", None)
    progress.pop("deferred_errors", None)

    # Final cleanup and summary.
    progress["records"] = {
        sid: rec
        for sid, rec in progress["records"].items()
        if rec.get("tmax_abs") is not None or rec.get("tmin_abs") is not None
    }
    refresh_summary(progress)

    if not progress["records"]:
        raise RuntimeError("Met-Éireann-Irland-Baseline enthält keine Temperaturreihen.")

    progress["complete"] = True
    payload = {
        **progress,
        "parameters": {
            "TMAX": "maxtp",
            "TMIN": "mintp",
        },
        "ignored_temperature_like_fields": ["gmin", "igmin"],
        "public_url": PUBLIC_URL,
        "quality_note": (
            "Official Met Éireann daily station files. maxtp/mintp are used as "
            "daily maximum/minimum AIR temperature. gmin/igmin are grass-minimum "
            "fields and are deliberately ignored. Indicator fields are retained as "
            "counts but are not interpreted as rejection flags because the CSV key "
            "labels them generically as Indicator (i). Blank/non-numeric values and "
            "only very broad implausible/Tmin>Tmax cases are rejected."
        ),
    }

    atomic_pickle_gzip(final, payload)
    write_status(cache_dir, cutoff_year, payload)
    prog_file.unlink(missing_ok=True)

    log()
    log("=== MET ÉIREANN IRELAND BASELINE SUMMARY ===")
    log(f"Stationsinventar Republik Irland: {len(payload['inventory']):,}")
    log(f"Temperatur-Stationsreihen: {len(payload['records']):,}")
    log(f"Verarbeitete Stations-IDs: {len(payload['processed_station_ids']):,}")
    log(f"Gefundene Daily-Dateien: {len(payload['daily_file_station_ids']):,}")
    log(f"Fehlende Daily-Dateien: {len(payload['missing_daily_station_ids']):,}")
    log(f"Daily-Dateien ohne nutzbare Temperatur: {len(payload['daily_without_temperature_ids']):,}")
    log(f"Stationstage mit TMAX und/oder TMIN: {payload['rows_with_temperature']:,}")
    log(f"Datenzeitraum: {payload['first_date']} bis {payload['last_date']}")
    log(
        "QC verworfen: "
        f"TMAX={payload['qc_rejected_tmax']:,} | "
        f"TMIN={payload['qc_rejected_tmin']:,} | "
        f"TMIN>TMAX={payload['qc_rejected_inconsistent_days']:,}"
    )
    log(f"Output: {final}")
    log("Met Éireann Ireland historische Baseline vollständig OK.")
    return final


def self_test() -> None:
    assert parse_date("01-jan-1942") == date(1942, 1, 1)
    assert parse_date("31-jul-2026") == date(2026, 7, 31)
    assert parse_float(" 13.6 ") == 13.6
    assert parse_float(" ") is None

    fixture = """Station Name: TEST
Station Height: 10 M
Latitude:53.0 ,Longitude:-7.0

date: - 00 to 00 utc
maxtp: - Maximum Air Temperature (C)
mintp: - Minimum Air Temperature (C)
gmin: - Grass Minimum Temperature (C)
ind: - Indicator (i)

date,ind,maxtp,ind,mintp,igmin,gmin,ind,rain
01-jan-1942,0,9.7,0,6.8,0,4.7,2,0.0
02-jan-1942,0,10.2,1,5.0,0,-20.0,0,0.1
03-jan-2026,0,99.0,0,-99.0,0,-99.0,0,0.0
"""
    stats = {
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
    }
    parsed = parse_daily_file(fixture.encode("utf-8"), 2025, stats)
    rec = parsed["record"]
    assert rec is not None
    assert rec["observation_days"] == 2
    assert rec["tmax_abs"] == [10.2, "1942-01-02"]
    assert rec["tmin_abs"] == [5.0, "1942-01-02"]
    # Grass minimum -20.0 must not become AIR Tmin.
    assert rec["tmin_abs"][0] != -20.0
    assert rec["tmax_indicator_counts"] == {"0": 2}
    assert rec["tmin_indicator_counts"] == {"0": 1, "1": 1}

    qc = {"qc_rejected_tmax": 0, "qc_rejected_tmin": 0, "qc_rejected_inconsistent_days": 0}
    tn, tx = qc_values(12.0, 11.0, qc)
    assert tn is None and tx is None
    assert qc["qc_rejected_inconsistent_days"] == 1

    urls = daily_urls("532")
    assert urls
    assert all("clidata.met.ie" in url for url in urls)
    assert all("cli.fusio.net" not in url for url in urls)

    print("Met Éireann Ireland historical cache self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--cutoff-year", type=int, default=date.today().year - 1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-runtime-minutes", type=float, default=155.0)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_baseline(
        Path(args.cache_dir),
        args.cutoff_year,
        force=args.force,
        workers=args.workers,
        batch_size=args.batch_size,
        max_runtime_minutes=args.max_runtime_minutes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
