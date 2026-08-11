#!/usr/bin/env python3
"""Build compact historical Hungarian daily TMIN/TMAX station records.

Authoritative HungaroMet sources combined here:
1) non-homogenized, data-controlled original daily series for 10 long stations
   from 1901 through the previous year (tx_o / tn_o), and
2) the operational automatic-station daily historical archive (HABP_1D),
   available mainly from 2002 onward.

The cache stores only absolute and calendar-day extrema plus metadata.  It does
not mix homogenized series into measured-station records.
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
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

SOURCE = "HungaroMet Open Data"
PUBLIC_URL = "https://odp.met.hu/climate/"
COUNTRY = "Hungary"
COUNTRY_CODE = "HU"
BASE = "https://odp.met.hu/climate"
LONG_TX_INDEX = f"{BASE}/station_data_series/daily/from_1901/maximum_temperature/"
LONG_TN_INDEX = f"{BASE}/station_data_series/daily/from_1901/minimum_temperature/"
LONG_META_INDEX = f"{BASE}/station_data_series/daily/from_1901/meta/"
OBS_HIST_INDEX = f"{BASE}/observations_hungary/daily/historical/"
OBS_RECENT_INDEX = f"{BASE}/observations_hungary/daily/recent/"
OBS_META_URL = f"{BASE}/observations_hungary/meta/station_meta_auto.csv"

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
UA = "climate-dashboard-hungaromet-hungary-cache/1.0"
TRIES = 6
HTTP_TIMEOUT = 150

# Wide emergency plausibility envelope. Missing values in HABP are -999.
HIST_TMAX_CEILING = 45.0
HIST_TMIN_FLOOR = -45.0
MISSING_LIMIT = -900.0


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"hungaromet_hungary_daily_baseline_through_{cutoff_year}_v{FORMAT_VERSION}.pkl.gz"


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"hungaromet_hungary_progress_through_{cutoff_year}_v{FORMAT_VERSION}.pkl.gz"


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"hungaromet_hungary_status_through_{cutoff_year}.json"


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
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def http_bytes(url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        })
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                raw = response.read()
                if not raw:
                    raise RuntimeError("Leere HTTP-Antwort")
                return raw
        except urllib.error.HTTPError as exc:
            last = exc
            retryable = exc.code in {408, 429, 500, 502, 503, 504}
            if not retryable or attempt >= TRIES:
                raise
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            last = exc
            if attempt >= TRIES:
                break
        wait = min(45, 3 * attempt)
        log(f"WARNUNG HungaroMet: {last}; neuer Versuch in {wait}s …")
        time.sleep(wait)
    raise RuntimeError(f"HungaroMet-Abruf fehlgeschlagen: {last}")


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1250", "iso-8859-2", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def hrefs(html: str) -> list[str]:
    return re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I)


def list_index(index_url: str, pattern: str) -> list[tuple[re.Match[str], str]]:
    html = decode(http_bytes(index_url))
    rx = re.compile(pattern, flags=re.I)
    out: list[tuple[re.Match[str], str]] = []
    for href in hrefs(html):
        name = urllib.parse.unquote(href).rsplit("/", 1)[-1]
        match = rx.fullmatch(name)
        if match:
            out.append((match, urllib.parse.urljoin(index_url, href)))
    return out


def sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:40])
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in (";", ",", "\t", "|")}
        return max(counts, key=counts.get)


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def parse_float(value: Any) -> float | None:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        x = float(text)
    except ValueError:
        return None
    if not math.isfinite(x) or x <= MISSING_LIMIT:
        return None
    return x


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None
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
        "provenance_days": {},
    }


def better_max(old: list[Any] | None, value: float) -> bool:
    return old is None or float(value) > float(old[0])


def better_min(old: list[Any] | None, value: float) -> bool:
    return old is None or float(value) < float(old[0])


def qc_values(tmin: float | None, tmax: float | None, stats: dict[str, int]) -> tuple[float | None, float | None]:
    if tmax is not None and not (-45.0 <= tmax <= HIST_TMAX_CEILING):
        stats["qc_rejected_tmax"] = stats.get("qc_rejected_tmax", 0) + 1
        tmax = None
    if tmin is not None and not (HIST_TMIN_FLOOR <= tmin <= 45.0):
        stats["qc_rejected_tmin"] = stats.get("qc_rejected_tmin", 0) + 1
        tmin = None
    if tmin is not None and tmax is not None and tmin > tmax:
        stats["qc_rejected_inconsistent_days"] = stats.get("qc_rejected_inconsistent_days", 0) + 1
        return None, None
    return tmin, tmax


def consume_day(rec: dict[str, Any], d: date, tmin: float | None, tmax: float | None, provenance: str) -> bool:
    if tmin is None and tmax is None:
        return False
    iso = d.isoformat()
    mmdd = d.strftime("%m-%d")
    if rec["first_date"] is None or iso < rec["first_date"]:
        rec["first_date"] = iso
    if rec["last_date"] is None or iso > rec["last_date"]:
        rec["last_date"] = iso
    rec["observation_days"] += 1
    rec["provenance_days"][provenance] = rec["provenance_days"].get(provenance, 0) + 1
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


def load_auto_metadata() -> dict[str, dict[str, Any]]:
    text = decode(http_bytes(OBS_META_URL))
    delimiter = sniff_delimiter(text)
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = str(row.get("StationNumber") or "").strip().lstrip("#").strip()
        if not sid:
            continue
        end = re.sub(r"\D", "", str(row.get("EndDate") or ""))
        old = out.get(sid)
        old_end = str(old.get("end_date_raw") or "") if old else ""
        if old is not None and end < old_end:
            continue
        lat = parse_float(row.get("Latitude")); lon = parse_float(row.get("Longitude")); elev = parse_float(row.get("Elevation"))
        out[sid] = {
            "id": sid,
            "name": str(row.get("StationName") or sid).strip(),
            "region": str(row.get("RegioName") or "").strip(),
            "lat": lat,
            "lon": lon,
            "elevation_m": elev,
            "start_date_raw": re.sub(r"\D", "", str(row.get("StartDate") or "")),
            "end_date_raw": end,
            "network": "HungaroMet automatic station network",
            "source": SOURCE,
        }
    return out


def parse_obs_zip(raw: bytes, *, cutoff_year: int | None = None) -> tuple[str | None, list[tuple[date, float | None, float | None]]]:
    if not raw.startswith(b"PK"):
        raise RuntimeError("HABP-Antwort ist kein ZIP")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        if not members:
            raise RuntimeError("Leeres HABP-ZIP")
        member = next((n for n in members if n.lower().endswith(".csv")), members[0])
        text = decode(zf.read(member))
    delimiter = sniff_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))

    header_i = None
    header: list[str] = []
    for i, row in enumerate(rows):
        clean = [str(x).strip().lstrip("\ufeff") for x in row]
        names = {x.lstrip("#").strip() for x in clean}
        # The metadata header begins with #StationNumber; the measurement header does not.
        if "StationNumber" in names and "Time" in names and "tn" in names and "tx" in names:
            header_i = i
            header = [x.lstrip("#").strip() for x in clean]
            break
    if header_i is None:
        # Some current station ZIPs can contain metadata but no measurement rows.
        return None, []

    idx = {name: i for i, name in enumerate(header)}
    output: list[tuple[date, float | None, float | None]] = []
    sid: str | None = None
    for row in rows[header_i + 1:]:
        if not row or str(row[0]).strip().startswith("##"):
            continue
        if len(row) <= max(idx["StationNumber"], idx["Time"], idx["tn"], idx["tx"]):
            continue
        this_sid = str(row[idx["StationNumber"]]).strip().lstrip("#").strip()
        d = parse_date(row[idx["Time"]])
        if not this_sid or d is None:
            continue
        if cutoff_year is not None and d.year > cutoff_year:
            continue
        tn = parse_float(row[idx["tn"]]); tx = parse_float(row[idx["tx"]])
        sid = sid or this_sid
        output.append((d, tn, tx))
    return sid, output


def historical_inventory() -> list[tuple[str, str, str, str]]:
    items = list_index(OBS_HIST_INDEX, r"HABP_1D_(\d+)_(\d{8})_(\d{8})_hist\.zip")
    out = [(m.group(1), m.group(2), m.group(3), url) for m, url in items]
    out.sort(key=lambda x: (x[0], x[1], x[2]))
    return out


def recent_inventory() -> dict[str, str]:
    items = list_index(OBS_RECENT_INDEX, r"HABP_1D_(\d+)_akt\.zip")
    return {m.group(1): url for m, url in items}


def long_inventory() -> dict[str, dict[str, str]]:
    tx_items = list_index(LONG_TX_INDEX, r"tx_o_(.+)_(\d{4})(\d{4})\.csv\.zip")
    tn_items = list_index(LONG_TN_INDEX, r"tn_o_(.+)_(\d{4})(\d{4})\.csv\.zip")
    tx = {m.group(1): (m.group(2), m.group(3), url) for m, url in tx_items}
    tn = {m.group(1): (m.group(2), m.group(3), url) for m, url in tn_items}
    paired: dict[str, dict[str, str]] = {}
    for city in sorted(set(tx) & set(tn)):
        paired[city] = {
            "tx_url": tx[city][2], "tn_url": tn[city][2],
            "start_year": min(tx[city][0], tn[city][0]),
            "end_year": max(tx[city][1], tn[city][1]),
            "meta_url": urllib.parse.urljoin(LONG_META_INDEX, f"t_meta_{city}_{tx[city][0]}{tx[city][1]}.csv"),
        }
    return paired


def parse_long_zip(raw: bytes, *, cutoff_year: int) -> dict[date, float]:
    if not raw.startswith(b"PK"):
        raise RuntimeError("Langreihen-Antwort ist kein ZIP")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        if not members:
            raise RuntimeError("Leeres Langreihen-ZIP")
        member = next((n for n in members if n.lower().endswith(".csv")), members[0])
        text = decode(zf.read(member))
    delimiter = sniff_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    out: dict[date, float] = {}
    # Official format: first row header; first column date; second column data.
    for row in rows[1:]:
        if len(row) < 2:
            continue
        d = parse_date(row[0]); value = parse_float(row[1])
        if d is None or value is None or d.year > cutoff_year:
            continue
        out[d] = value
    return out


def _header_indexes(header: list[str]) -> tuple[int | None, int | None, int | None]:
    norms = [normalize(x) for x in header]
    lat_i = lon_i = elev_i = None
    for i, key in enumerate(norms):
        if lat_i is None and (key in {"lat", "latitude"} or "szelesseg" in key): lat_i = i
        if lon_i is None and (key in {"lon", "longitude"} or "hosszusag" in key): lon_i = i
        if elev_i is None and ("elev" in key or "magassag" in key or key == "height"): elev_i = i
    return lat_i, lon_i, elev_i


def parse_long_metadata(raw: bytes) -> dict[str, Any]:
    text = decode(raw)
    delimiter = sniff_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        return {}
    lat_i, lon_i, elev_i = _header_indexes([str(x) for x in rows[0]])
    candidates: list[tuple[float, float, float | None]] = []
    if lat_i is not None and lon_i is not None:
        for row in rows[1:]:
            if len(row) <= max(lat_i, lon_i): continue
            lat = parse_float(row[lat_i]); lon = parse_float(row[lon_i])
            elev = parse_float(row[elev_i]) if elev_i is not None and len(row) > elev_i else None
            if lat is not None and lon is not None and 45.0 <= lat <= 49.5 and 16.0 <= lon <= 23.0:
                candidates.append((lat, lon, elev))
    if not candidates:
        # Defensive fallback for metadata layouts with Hungarian/legacy headers.
        for row in rows:
            nums = [parse_float(x) for x in row]
            nums = [x for x in nums if x is not None]
            lats = [x for x in nums if 45.0 <= x <= 49.5]
            lons = [x for x in nums if 16.0 <= x <= 23.0]
            if lats and lons:
                elevs = [x for x in nums if 30.0 <= x <= 1100.0 and x not in {lats[0], lons[0]}]
                candidates.append((lats[0], lons[0], elevs[-1] if elevs else None))
    if not candidates:
        return {}
    lat, lon, elev = candidates[-1]
    return {"lat": lat, "lon": lon, "elevation_m": elev}


def match_city_metadata(city: str, auto_inventory: dict[str, dict[str, Any]]) -> dict[str, Any]:
    target = normalize(city)
    candidates = []
    for meta in auto_inventory.values():
        name = normalize(meta.get("name"))
        if target and (target in name or name in target):
            candidates.append(meta)
    if not candidates:
        return {}
    candidates.sort(key=lambda m: str(m.get("end_date_raw") or ""), reverse=True)
    return dict(candidates[0])


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
        "processed_historical_urls": [],
        "processed_long_cities": [],
        "rows_with_temperature": 0,
        "first_date": None,
        "last_date": None,
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
    }


def update_span(progress: dict[str, Any], rec: dict[str, Any]) -> None:
    first = rec.get("first_date"); last = rec.get("last_date")
    if first and (progress["first_date"] is None or first < progress["first_date"]): progress["first_date"] = first
    if last and (progress["last_date"] is None or last > progress["last_date"]): progress["last_date"] = last


def valid_final(path: Path, cutoff_year: int) -> bool:
    if not path.exists(): return False
    try: obj = load_pickle_gzip(path)
    except Exception: return False
    return isinstance(obj, dict) and obj.get("format_version") == FORMAT_VERSION and obj.get("cutoff_year") == cutoff_year and obj.get("complete") is True and len(obj.get("records", {})) > 0


def write_status(cache_dir: Path, cutoff_year: int, payload: dict[str, Any]) -> None:
    atomic_json(status_path(cache_dir, cutoff_year), {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "country": COUNTRY,
        "cutoff_year": cutoff_year,
        "complete": bool(payload.get("complete")),
        "station_count": len(payload.get("records", {})),
        "inventory_count": len(payload.get("inventory", {})),
        "rows_with_temperature": int(payload.get("rows_with_temperature", 0)),
        "first_date": payload.get("first_date"),
        "last_date": payload.get("last_date"),
        "historical_files_processed": len(payload.get("processed_historical_urls", [])),
        "long_series_processed": len(payload.get("processed_long_cities", [])),
        "qc_rejected_tmax": int(payload.get("qc_rejected_tmax", 0)),
        "qc_rejected_tmin": int(payload.get("qc_rejected_tmin", 0)),
        "qc_rejected_inconsistent_days": int(payload.get("qc_rejected_inconsistent_days", 0)),
        "baseline_file": str(baseline_path(cache_dir, cutoff_year)),
    })


def process_historical_resource(url: str, cutoff_year: int) -> tuple[str | None, list[tuple[date, float | None, float | None]]]:
    return parse_obs_zip(http_bytes(url), cutoff_year=cutoff_year)


def build_baseline(cache_dir: Path, cutoff_year: int, *, force: bool = False, workers: int = 12, max_runtime_minutes: float = 150.0) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    final = baseline_path(cache_dir, cutoff_year); prog_file = progress_path(cache_dir, cutoff_year)
    if force:
        final.unlink(missing_ok=True); prog_file.unlink(missing_ok=True); status_path(cache_dir, cutoff_year).unlink(missing_ok=True)
    if not force and valid_final(final, cutoff_year):
        log(f"Verwende vorhandenen HungaroMet-Ungarn-Baselinecache: {final}")
        return final

    if not force and prog_file.exists():
        try:
            progress = load_pickle_gzip(prog_file)
            if progress.get("format_version") != FORMAT_VERSION or progress.get("cutoff_year") != cutoff_year:
                progress = initial_progress(cutoff_year)
        except Exception:
            progress = initial_progress(cutoff_year)
    else:
        progress = initial_progress(cutoff_year)

    started = time.monotonic()
    auto_inventory = load_auto_metadata()
    for sid, meta in auto_inventory.items():
        progress["inventory"].setdefault(sid, meta)

    long_items = long_inventory()
    done_long = set(progress.get("processed_long_cities", []))
    log("=== HUNGAROMET UNGARN HISTORISCHE BASELINE ===")
    log(f"10 Original-Langreihen ab 1901 + HABP_1D historical bis {cutoff_year}")
    log(f"Automaten-Metadaten: {len(auto_inventory)} aktuelle/alte Stationssegmente zusammengeführt")
    log(f"Langreihen gefunden: {len(long_items)}")

    for city, info in long_items.items():
        if city in done_long:
            continue
        tx_map = parse_long_zip(http_bytes(info["tx_url"]), cutoff_year=cutoff_year)
        tn_map = parse_long_zip(http_bytes(info["tn_url"]), cutoff_year=cutoff_year)
        raw_id = f"LONG-{city}"
        rec = progress["records"].setdefault(raw_id, empty_record())
        for d in sorted(set(tx_map) | set(tn_map)):
            tn, tx = qc_values(tn_map.get(d), tx_map.get(d), progress)
            consume_day(rec, d, tn, tx, "HUNGAROMET_LONG_ORIGINAL")
        meta: dict[str, Any] = {}
        try:
            meta = parse_long_metadata(http_bytes(info["meta_url"]))
        except Exception as exc:
            log(f"WARNUNG Langreihen-Metadaten {city}: {exc}")
        if not meta.get("lat") or not meta.get("lon"):
            fallback = match_city_metadata(city, auto_inventory)
            for key in ("lat", "lon", "elevation_m"):
                if fallback.get(key) is not None:
                    meta[key] = fallback[key]
        meta.update({
            "id": raw_id,
            "name": f"{city} · Originalreihe 1901–",
            "network": "HungaroMet controlled non-homogenized long series",
            "source": SOURCE,
            "long_series": True,
        })
        progress["inventory"][raw_id] = meta
        progress["processed_long_cities"].append(city); done_long.add(city)
        update_span(progress, rec)
        atomic_pickle_gzip(prog_file, progress)
        log(f"Langreihe {city}: {rec.get('first_date')} bis {rec.get('last_date')} | {rec.get('observation_days',0):,} Tage")

    hist_items = historical_inventory()
    done_urls = set(progress.get("processed_historical_urls", []))
    pending = [(sid, start, end, url) for sid, start, end, url in hist_items if url not in done_urls and int(start[:4]) <= cutoff_year]
    log(f"HABP historical: {len(hist_items)} Dateien im Index | offen {len(pending)}")
    workers = max(1, min(int(workers), 20))
    errors: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(process_historical_resource, url, cutoff_year): (sid_hint, url) for sid_hint, _, _, url in pending}
        done_count = 0
        for fut in as_completed(futs):
            sid_hint, url = futs[fut]; done_count += 1
            try:
                sid, rows = fut.result()
                sid = sid or sid_hint
                if sid and rows:
                    rec = progress["records"].setdefault(sid, empty_record())
                    for d, tn0, tx0 in rows:
                        tn, tx = qc_values(tn0, tx0, progress)
                        consume_day(rec, d, tn, tx, "HUNGAROMET_HABP_HIST")
                    update_span(progress, rec)
                progress["processed_historical_urls"].append(url); done_urls.add(url)
            except Exception as exc:
                errors.append((url, str(exc)))
            if done_count % 20 == 0 or done_count == len(futs):
                progress["rows_with_temperature"] = sum(int(r.get("observation_days",0)) for r in progress["records"].values())
                atomic_pickle_gzip(prog_file, progress)
                log(f"HABP: {done_count}/{len(futs)} offene Dateien | Stationsreihen {len(progress['records'])} | Fehler {len(errors)}")
            if (time.monotonic() - started) / 60 >= max_runtime_minutes:
                atomic_pickle_gzip(prog_file, progress)
                raise RuntimeError("HungaroMet-Laufzeitgrenze erreicht; Zwischenstand gespeichert. Workflow erneut mit force=false starten.")

    if errors:
        atomic_pickle_gzip(prog_file, progress)
        sample = "; ".join(f"{u.rsplit('/',1)[-1]}: {e}" for u, e in errors[:5])
        raise RuntimeError(f"HungaroMet historical: {len(errors)} Dateien fehlgeschlagen; erfolgreiche Dateien sind im Fortschrittscache. Erneut starten. Beispiele: {sample}")

    # Remove records that carry no valid temperature extrema.
    progress["records"] = {
        sid: rec for sid, rec in progress["records"].items()
        if rec.get("tmax_abs") is not None or rec.get("tmin_abs") is not None
    }
    if not progress["records"]:
        raise RuntimeError("HungaroMet-Ungarn-Baseline enthält keine Temperatur-Stationen.")

    progress["rows_with_temperature"] = sum(int(r.get("observation_days",0)) for r in progress["records"].values())
    firsts = [r.get("first_date") for r in progress["records"].values() if r.get("first_date")]
    lasts = [r.get("last_date") for r in progress["records"].values() if r.get("last_date")]
    progress["first_date"] = min(firsts) if firsts else None
    progress["last_date"] = max(lasts) if lasts else None
    progress["complete"] = True
    payload = {
        **progress,
        "parameters": {"TMIN": "tn", "TMAX": "tx"},
        "public_url": PUBLIC_URL,
        "long_series_url": LONG_TX_INDEX.rsplit("/maximum_temperature/",1)[0] + "/",
        "historical_observations_url": OBS_HIST_INDEX,
        "quality_note": (
            "HungaroMet controlled non-homogenized original 10-station series from 1901 plus HABP_1D automatic-station historical data. "
            "HABP Q_tn/Q_tx fields are currently reserved; -999/non-numeric values and implausible/Tmin>Tmax cases are rejected. "
            "Homogenized series are deliberately not used for measured station records."
        ),
    }
    atomic_pickle_gzip(final, payload); write_status(cache_dir, cutoff_year, payload); prog_file.unlink(missing_ok=True)
    log(); log("=== HUNGAROMET HUNGARY BASELINE SUMMARY ===")
    log(f"Stationsreihen: {len(payload['records']):,}")
    log(f"Inventar: {len(payload['inventory']):,}")
    log(f"Stationstage: {payload['rows_with_temperature']:,}")
    log(f"Datenzeitraum: {payload['first_date']} bis {payload['last_date']}")
    log(f"Langreihen: {len(payload['processed_long_cities'])} | HABP-Dateien: {len(payload['processed_historical_urls'])}")
    log(f"QC verworfen: TX={payload['qc_rejected_tmax']:,} | TN={payload['qc_rejected_tmin']:,} | TN>TX={payload['qc_rejected_inconsistent_days']:,}")
    log(f"Output: {final}")
    log("HungaroMet Hungary Baseline OK.")
    return final


def load_baseline(cache_dir: Path, cutoff_year: int) -> dict[str, Any]:
    path = baseline_path(cache_dir, cutoff_year)
    if not valid_final(path, cutoff_year):
        raise RuntimeError(f"HungaroMet-Ungarn-Baseline fehlt/unvollständig: {path}")
    obj = load_pickle_gzip(path)
    assert isinstance(obj, dict)
    return obj


def self_test() -> None:
    assert parse_date("20260102") == date(2026,1,2)
    assert parse_float("-999") is None and parse_float("36.0") == 36.0
    rec = empty_record(); stats = {"qc_rejected_tmax":0,"qc_rejected_tmin":0,"qc_rejected_inconsistent_days":0}
    tn,tx = qc_values(20.6,36.0,stats); consume_day(rec,date(2005,7,28),tn,tx,"TEST")
    tn,tx = qc_values(21.2,35.8,stats); consume_day(rec,date(2005,7,29),tn,tx,"TEST")
    assert rec["tmax_abs"] == [36.0,"2005-07-28"] and rec["tmin_abs"] == [20.6,"2005-07-28"]

    csv_text = "##Meta\n#StationNumber;StartDate;EndDate;Latitude;Longitude;Elevation;StationName;EOR\n#        13704;20050727;20260102;47.6783;16.6022;232.8;Sopron Kuruc-domb;EOR\n##Meta END\nStationNumber;Time;rau;Q_rau;t;Q_t;tn;Q_tn;tx;Q_tx;EOR\n13704;20260101;0.0;;2.5;;-0.3;;8.2;;EOR\n"
    bio=io.BytesIO()
    with zipfile.ZipFile(bio,"w",zipfile.ZIP_DEFLATED) as zf: zf.writestr("HABP.csv",csv_text)
    sid,rows=parse_obs_zip(bio.getvalue(),cutoff_year=2026)
    assert sid == "13704" and rows[0] == (date(2026,1,1),-0.3,8.2)

    long_text = "date;tx\n19010101;-1.2\n19010102;2.3\n"
    bio2=io.BytesIO()
    with zipfile.ZipFile(bio2,"w",zipfile.ZIP_DEFLATED) as zf: zf.writestr("tx.csv",long_text)
    parsed=parse_long_zip(bio2.getvalue(),cutoff_year=2025)
    assert parsed[date(1901,1,2)] == 2.3
    print("HungaroMet Hungary historical cache self-test OK")


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--cache-dir",default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--cutoff-year",type=int,default=date.today().year-1)
    parser.add_argument("--force",action="store_true")
    parser.add_argument("--workers",type=int,default=12)
    parser.add_argument("--max-runtime-minutes",type=float,default=150.0)
    args=parser.parse_args()
    if args.self_test: self_test(); return 0
    build_baseline(Path(args.cache_dir),args.cutoff_year,force=args.force,workers=args.workers,max_runtime_minutes=args.max_runtime_minutes)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
