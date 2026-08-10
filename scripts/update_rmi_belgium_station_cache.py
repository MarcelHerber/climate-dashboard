#!/usr/bin/env python3
"""
Belgium historical daily Tmin/Tmax cache for climate-dashboard.

Hybrid architecture
===================
Uccle / KMI code 6447 / WMO 06447:
    pre-2000  -> NOAA GHCN-Daily station BE000006447
                 TMIN/TMAX with blank Q-FLAG only.
    2000+     -> KMI/RMI aws:aws_1day.

All other Belgian stations:
    1952-1999 -> KMI/RMI synop:synop_data.
                 Tmin reporting window approx. 18-06 UTC.
                 Tmax reporting window approx. 06-18 UTC.
    2000+     -> KMI/RMI aws:aws_1day.

SYNOP is deliberately NOT used for Uccle because the overlap test showed
GHCN-Daily agrees substantially better with AWS there.

From 2000 onward only AWS is used for every station; historical bridges are
never mixed into the AWS era.

No API key / secret is required.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import pickle
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

SOURCE = "KMI/RMI Open Data"
BRIDGE_SOURCE = "GHCN-Daily"
PUBLIC_URL = "https://opendata.meteo.be/"
WFS = "https://opendata.meteo.be/geoserver/ows"

SYNOP_STATION = "synop:synop_station"
SYNOP_DATA = "synop:synop_data"
AWS_STATION = "aws:aws_station"
AWS_DAY = "aws:aws_1day"

GHCN_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
GHCN_UCCLE_ID = "BE000006447"
UCCLE_CODE = "6447"

SYNOP_START_YEAR = 1952
BRIDGE_END_YEAR = 1999
AWS_START_YEAR = 2000

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
UA = "climate-dashboard-rmi-belgium-hybrid-cache/1.0"
TRIES = 6
TIMEOUT = 150
PAGE_SIZE = 5000


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"rmi_belgium_daily_baseline_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"rmi_belgium_progress_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"rmi_belgium_status_through_{cutoff_year}.json"


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


def request_bytes(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    accept: str = "*/*",
    allow_404: bool = False,
) -> bytes | None:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
            params, doseq=True
        )

    last: Exception | None = None
    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": accept,
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404 and allow_404:
                return None

            # GeoServer error bodies are extremely useful for diagnosing
            # malformed WFS/CQL requests. Do not hide them behind "HTTP 400".
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                body = ""
            if body:
                compact = " ".join(body.split())
                log(f"HTTP {exc.code} Serverantwort: {compact[:1200]}")

            if exc.code in {408, 429, 500, 502, 503, 504} and attempt < TRIES:
                wait = min(45, attempt * 5)
                log(f"WARNUNG HTTP {exc.code}; neuer Versuch in {wait}s …")
                time.sleep(wait)
                continue
            raise
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            last = exc
            if attempt >= TRIES:
                break
            wait = min(40, attempt * 4)
            log(f"WARNUNG {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last}")


def wfs_page(
    typename: str,
    *,
    count: int,
    start_index: int = 0,
    cql_filter: str | None = None,
    property_names: tuple[str, ...] | None = None,
    sort_by: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": typename,
        "outputFormat": "application/json",
        "count": count,
    }
    # KMI/RMI GeoServer rejects startIndex on some layer/query combinations.
    # Never send the redundant startIndex=0.
    if start_index:
        params["startIndex"] = start_index
    if cql_filter:
        params["CQL_FILTER"] = cql_filter
    if property_names:
        params["propertyName"] = ",".join(property_names)
    if sort_by:
        params["sortBy"] = sort_by

    raw = request_bytes(
        WFS,
        params=params,
        accept="application/json,*/*",
    )
    if not raw:
        return {}
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"{typename}: ungültige WFS-JSON-Antwort.")
    return obj


def wfs_all(
    typename: str,
    *,
    cql_filter: str | None = None,
    property_names: tuple[str, ...] | None = None,
    sort_by: str | None = None,
    page_size: int = PAGE_SIZE,
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    start = 0

    while True:
        payload = wfs_page(
            typename,
            count=page_size,
            start_index=start,
            cql_filter=cql_filter,
            property_names=property_names,
            sort_by=sort_by,
        )
        rows = payload.get("features") or []
        if not isinstance(rows, list):
            rows = []

        features.extend(x for x in rows if isinstance(x, dict))

        if not rows or len(rows) < page_size:
            break
        start += len(rows)

    return features


def props(feature: dict[str, Any]) -> dict[str, Any]:
    row = feature.get("properties")
    return row if isinstance(row, dict) else {}


def fnum(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def valid_temp(value: Any) -> float | None:
    x = fnum(value)
    if x is None or x < -90 or x > 65:
        return None
    return round(x, 2)


def month_windows(year: int) -> list[tuple[str, str]]:
    """Return half-open monthly UTC windows [start, next_month)."""
    windows: list[tuple[str, str]] = []
    for month in range(1, 13):
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        windows.append((start.isoformat(), end.isoformat()))
    return windows


def wfs_small_query(
    typename: str,
    *,
    cql_filter: str,
    property_names: tuple[str, ...],
    count: int,
) -> list[dict[str, Any]]:
    """One intentionally small GeoServer query without startIndex."""
    payload = wfs_page(
        typename,
        count=count,
        start_index=0,
        cql_filter=cql_filter,
        property_names=property_names,
        sort_by="timestamp A",
    )
    rows = payload.get("features") or []
    if not isinstance(rows, list):
        return []
    return [x for x in rows if isinstance(x, dict)]


def parse_iso_day(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def station_code(row: dict[str, Any]) -> str | None:
    try:
        return str(int(row.get("code")))
    except (TypeError, ValueError):
        return None


def station_layer_inventory(
    typename: str,
    network: str,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    payload = wfs_page(
        typename,
        count=1000,
        property_names=None,
    )
    station_features = payload.get("features") or []
    if not isinstance(station_features, list):
        station_features = []

    for feature in station_features:
        if not isinstance(feature, dict):
            continue
        row = props(feature)
        sid = station_code(row)
        if not sid:
            continue

        geometry = feature.get("geometry")
        lat = lon = None
        if isinstance(geometry, dict):
            coords = geometry.get("coordinates")
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                lon = fnum(coords[0])
                lat = fnum(coords[1])

        def pick(*keys: str) -> Any:
            for key in keys:
                value = row.get(key)
                if value not in (None, ""):
                    return value
            return None

        name = pick(
            "name",
            "station_name",
            "stationname",
            "location",
            "nom",
            "naam",
        )
        elevation = fnum(
            pick("elevation", "height", "altitude", "elev")
        )

        out[sid] = {
            "id": sid,
            "name": str(name or f"KMI/RMI {sid}").strip(),
            "country": "Belgium",
            "country_code": "BE",
            "lat": lat,
            "lon": lon,
            "elevation_m": elevation,
            "network": network,
            "source": SOURCE,
            "raw_properties": row,
        }

    return out


def merge_inventory(
    synop: dict[str, dict[str, Any]],
    aws: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out = {sid: dict(meta) for sid, meta in synop.items()}

    for sid, meta in aws.items():
        if sid not in out:
            out[sid] = dict(meta)
            continue

        merged = out[sid]
        for key in ("name", "lat", "lon", "elevation_m"):
            value = meta.get(key)
            if value not in (None, "", f"KMI/RMI {sid}"):
                merged[key] = value
        merged["network"] = "SYNOP+AWS"

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
        "provenance_days": {
            "GHCN_UCCLE": 0,
            "RMI_SYNOP": 0,
            "RMI_AWS": 0,
        },
    }


def better_max(old: list[Any] | None, value: float, iso: str) -> bool:
    return (
        old is None
        or value > float(old[0])
        or (value == float(old[0]) and iso < str(old[1]))
    )


def better_min(old: list[Any] | None, value: float, iso: str) -> bool:
    return (
        old is None
        or value < float(old[0])
        or (value == float(old[0]) and iso < str(old[1]))
    )


def consume_day(
    records: dict[str, dict[str, Any]],
    sid: str,
    d: date,
    tmin: float | None,
    tmax: float | None,
    provenance: str,
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
    rec["provenance_days"][provenance] = (
        int(rec["provenance_days"].get(provenance, 0)) + 1
    )

    if tmax is not None:
        value = round(float(tmax), 2)
        if better_max(rec["tmax_abs"], value, iso):
            rec["tmax_abs"] = [value, iso]
        old = rec["calendar_tmax"].get(mmdd)
        if better_max(old, value, iso):
            rec["calendar_tmax"][mmdd] = [value, iso]

    if tmin is not None:
        value = round(float(tmin), 2)
        if better_min(rec["tmin_abs"], value, iso):
            rec["tmin_abs"] = [value, iso]
        old = rec["calendar_tmin"].get(mmdd)
        if better_min(old, value, iso):
            rec["calendar_tmin"][mmdd] = [value, iso]

    return True


def synop_year_rows(year: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for start, end in month_windows(year):
        cql = (
            f"timestamp >= '{start}T00:00:00Z' AND "
            f"timestamp < '{end}T00:00:00Z' AND "
            "(temp_min IS NOT NULL OR temp_max IS NOT NULL)"
        )
        features = wfs_small_query(
            SYNOP_DATA,
            cql_filter=cql,
            property_names=("code", "timestamp", "temp_min", "temp_max"),
            count=3000,
        )
        rows.extend(props(feature) for feature in features)

    return rows



def aggregate_synop_days(
    rows: list[dict[str, Any]],
    year: int,
) -> dict[tuple[str, date], tuple[float | None, float | None]]:
    by_day: dict[tuple[str, date], dict[str, float]] = defaultdict(dict)

    for row in rows:
        sid = station_code(row)
        d = parse_iso_day(row.get("timestamp"))
        if not sid or d is None or d.year != year:
            continue

        # Uccle pre-2000 is intentionally supplied by GHCN instead.
        if sid == UCCLE_CODE:
            continue

        tn = valid_temp(row.get("temp_min"))
        tx = valid_temp(row.get("temp_max"))

        key = (sid, d)
        if tn is not None:
            old = by_day[key].get("TMIN")
            by_day[key]["TMIN"] = tn if old is None else min(old, tn)
        if tx is not None:
            old = by_day[key].get("TMAX")
            by_day[key]["TMAX"] = tx if old is None else max(old, tx)

    return {
        key: (values.get("TMIN"), values.get("TMAX"))
        for key, values in by_day.items()
    }


def parse_ghcn_dly_pre2000(
    raw: bytes,
) -> dict[date, dict[str, float]]:
    text = raw.decode("ascii", errors="replace")
    out: dict[date, dict[str, float]] = defaultdict(dict)

    for line in text.splitlines():
        if len(line) < 269:
            continue
        try:
            year = int(line[11:15])
            month = int(line[15:17])
        except ValueError:
            continue

        if year >= AWS_START_YEAR:
            continue

        element = line[17:21]
        if element not in {"TMAX", "TMIN"}:
            continue

        for day in range(1, 32):
            pos = 21 + (day - 1) * 8
            block = line[pos:pos + 8]
            if len(block) < 8:
                continue

            try:
                raw_value = int(block[0:5])
            except ValueError:
                continue

            qflag = block[6:7]
            if raw_value == -9999 or qflag.strip():
                continue

            try:
                d = date(year, month, day)
            except ValueError:
                continue

            out[d][element] = raw_value / 10.0

    return out


def load_uccle_ghcn(
    progress: dict[str, Any],
) -> int:
    raw = request_bytes(
        f"{GHCN_BASE}/all/{GHCN_UCCLE_ID}.dly"
    )
    if not raw:
        raise RuntimeError("GHCN-Uccle-Datei ist leer.")

    days = parse_ghcn_dly_pre2000(raw)
    used = 0

    for d in sorted(days):
        vals = days[d]
        if consume_day(
            progress["records"],
            UCCLE_CODE,
            d,
            vals.get("TMIN"),
            vals.get("TMAX"),
            "GHCN_UCCLE",
        ):
            used += 1
            update_span(progress, d)

    return used


def aws_year_rows(year: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for start, end in month_windows(year):
        cql = (
            f"timestamp >= '{start}T00:00:00Z' AND "
            f"timestamp < '{end}T00:00:00Z'"
        )
        features = wfs_small_query(
            AWS_DAY,
            cql_filter=cql,
            property_names=("code", "timestamp", "temp_min", "temp_max"),
            count=1000,
        )
        rows.extend(props(feature) for feature in features)

    return rows



def initial_progress(cutoff_year: int) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "bridge_source": BRIDGE_SOURCE,
        "cutoff_year": cutoff_year,
        "stage": "inventory",
        "inventory": {},
        "records": {},
        "processed_synop_years": [],
        "processed_aws_years": [],
        "uccle_ghcn_rows": 0,
        "synop_rows": 0,
        "aws_rows": 0,
        "first_date": None,
        "last_date": None,
        "complete": False,
    }


def update_span(progress: dict[str, Any], d: date) -> None:
    iso = d.isoformat()
    if progress["first_date"] is None or iso < progress["first_date"]:
        progress["first_date"] = iso
    if progress["last_date"] is None or iso > progress["last_date"]:
        progress["last_date"] = iso


def write_status(
    cache_dir: Path,
    cutoff_year: int,
    payload: dict[str, Any],
) -> None:
    status = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "bridge_source": BRIDGE_SOURCE,
        "cutoff_year": cutoff_year,
        "stage": payload.get("stage"),
        "complete": bool(payload.get("complete")),
        "inventory_count": len(payload.get("inventory", {})),
        "station_count": len(payload.get("records", {})),
        "uccle_ghcn_rows": int(payload.get("uccle_ghcn_rows", 0)),
        "synop_rows": int(payload.get("synop_rows", 0)),
        "aws_rows": int(payload.get("aws_rows", 0)),
        "first_date": payload.get("first_date"),
        "last_date": payload.get("last_date"),
        "processed_synop_years": payload.get("processed_synop_years", []),
        "processed_aws_years": payload.get("processed_aws_years", []),
        "baseline_file": str(baseline_path(cache_dir, cutoff_year)),
    }
    atomic_json(status_path(cache_dir, cutoff_year), status)


def save_progress(
    cache_dir: Path,
    cutoff_year: int,
    progress: dict[str, Any],
) -> None:
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
        raise RuntimeError(f"Belgien-Baseline fehlt/unvollständig: {path}")
    obj = load_pickle_gzip(path)
    assert isinstance(obj, dict)
    return obj


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
        log(f"Verwende vorhandenen Belgien-Baselinecache: {final}")
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

    started = time.monotonic()

    log("=== KMI/RMI BELGIEN HYBRID-BASELINE ===")
    log(
        "Uccle: GHCN-Daily vor 2000; übrige Stationen: "
        "KMI/RMI SYNOP 1952-1999; alle Stationen: KMI/RMI AWS ab 2000."
    )

    if progress["stage"] == "inventory":
        synop_inventory = station_layer_inventory(SYNOP_STATION, "SYNOP")
        aws_inventory = station_layer_inventory(AWS_STATION, "AWS")
        inventory = merge_inventory(synop_inventory, aws_inventory)

        if not inventory:
            raise RuntimeError("Belgisches Stationsinventar ist leer.")
        if UCCLE_CODE not in inventory:
            raise RuntimeError("Uccle/6447 fehlt im belgischen Inventar.")

        inventory[UCCLE_CODE]["historical_bridge"] = {
            "source": BRIDGE_SOURCE,
            "station_id": GHCN_UCCLE_ID,
            "through_year": BRIDGE_END_YEAR,
        }

        progress["inventory"] = inventory
        progress["stage"] = "uccle_ghcn"
        save_progress(cache_dir, cutoff_year, progress)

        log(
            f"Inventar: SYNOP {len(synop_inventory)} | AWS {len(aws_inventory)} | "
            f"vereinigt {len(inventory)} Stationen."
        )

    if progress["stage"] == "uccle_ghcn":
        used = load_uccle_ghcn(progress)
        progress["uccle_ghcn_rows"] = used
        progress["stage"] = "synop"
        save_progress(cache_dir, cutoff_year, progress)

        log(
            f"Uccle GHCN-Brücke: {used:,} Stationstage vor {AWS_START_YEAR}."
        )

    if progress["stage"] == "synop":
        done = set(int(x) for x in progress["processed_synop_years"])

        for year in range(SYNOP_START_YEAR, min(BRIDGE_END_YEAR, cutoff_year) + 1):
            if year in done:
                continue

            rows = synop_year_rows(year)
            daily = aggregate_synop_days(rows, year)
            used = 0

            for (sid, d), (tn, tx) in sorted(daily.items()):
                if sid not in progress["inventory"]:
                    continue

                if consume_day(
                    progress["records"],
                    sid,
                    d,
                    tn,
                    tx,
                    "RMI_SYNOP",
                ):
                    used += 1
                    update_span(progress, d)

            progress["synop_rows"] += used
            progress["processed_synop_years"].append(year)
            done.add(year)
            save_progress(cache_dir, cutoff_year, progress)

            log(
                f"SYNOP {year}: {len(rows):,} Extremwert-Features | "
                f"{used:,} Stationstage ohne Uccle | "
                f"gesamt {progress['synop_rows']:,}."
            )

            if (time.monotonic() - started) / 60 >= max_runtime_minutes:
                log(
                    "Laufzeitgrenze erreicht. Zwischenstand gespeichert; "
                    "Workflow mit force=false erneut starten."
                )
                return prog_path

        progress["stage"] = "aws"
        save_progress(cache_dir, cutoff_year, progress)

    if progress["stage"] == "aws":
        done = set(int(x) for x in progress["processed_aws_years"])

        for year in range(AWS_START_YEAR, cutoff_year + 1):
            if year in done:
                continue

            rows = aws_year_rows(year)
            used = 0

            for row in rows:
                sid = station_code(row)
                d = parse_iso_day(row.get("timestamp"))
                if not sid or d is None or d.year != year:
                    continue
                if sid not in progress["inventory"]:
                    continue

                tn = valid_temp(row.get("temp_min"))
                tx = valid_temp(row.get("temp_max"))

                if consume_day(
                    progress["records"],
                    sid,
                    d,
                    tn,
                    tx,
                    "RMI_AWS",
                ):
                    used += 1
                    update_span(progress, d)

            progress["aws_rows"] += used
            progress["processed_aws_years"].append(year)
            done.add(year)
            save_progress(cache_dir, cutoff_year, progress)

            log(
                f"AWS {year}: {len(rows):,} Tagesfeatures | "
                f"{used:,} Stationstage | gesamt {progress['aws_rows']:,}."
            )

            if (time.monotonic() - started) / 60 >= max_runtime_minutes:
                log(
                    "Laufzeitgrenze erreicht. Zwischenstand gespeichert; "
                    "Workflow mit force=false erneut starten."
                )
                return prog_path

        progress["stage"] = "finalize"

    if progress["stage"] == "finalize":
        if not progress["records"]:
            raise RuntimeError("Belgien-Baseline enthält keine Stationsreihen.")

        progress["stage"] = "complete"
        progress["complete"] = True

        payload = {
            **progress,
            "segments": [
                {
                    "scope": "Uccle 06447",
                    "from": "start of GHCN series",
                    "to": "1999-12-31",
                    "source": BRIDGE_SOURCE,
                    "dataset": GHCN_UCCLE_ID,
                    "quality_rule": "TMIN/TMAX only with blank Q-FLAG",
                },
                {
                    "scope": "all Belgian stations except Uccle",
                    "from": "1952-01-01",
                    "to": "1999-12-31",
                    "source": SOURCE,
                    "dataset": SYNOP_DATA,
                    "tmin_window": "18-06 UTC",
                    "tmax_window": "06-18 UTC",
                },
                {
                    "scope": "all Belgian AWS stations",
                    "from": "2000-01-01",
                    "to": f"{cutoff_year}-12-31",
                    "source": SOURCE,
                    "dataset": AWS_DAY,
                },
            ],
            "quality_note": (
                "Uccle uses the substantially better-matching GHCN-Daily "
                "historical bridge before 2000. Other stations use KMI/RMI "
                "SYNOP from 1952-1999. From 2000 onward only KMI/RMI AWS "
                "daily data are used for all stations."
            ),
            "public_url": PUBLIC_URL,
        }

        atomic_pickle_gzip(final, payload)
        write_status(cache_dir, cutoff_year, payload)
        prog_path.unlink(missing_ok=True)

        log()
        log("=== KMI/RMI BELGIUM BASELINE SUMMARY ===")
        log(f"Stationsreihen: {len(payload['records'])}")
        log(f"Uccle GHCN-Stationstage vor 2000: {payload['uccle_ghcn_rows']:,}")
        log(f"SYNOP-Stationstage 1952-1999 ohne Uccle: {payload['synop_rows']:,}")
        log(f"AWS-Stationstage ab 2000: {payload['aws_rows']:,}")
        log(f"Datenzeitraum: {payload['first_date']} bis {payload['last_date']}")
        log(f"Inventar: {len(payload['inventory'])} Stationen")
        log(f"Output: {final}")
        log("KMI/RMI Belgium Baseline OK.")
        return final

    save_progress(cache_dir, cutoff_year, progress)
    return prog_path


def self_test() -> None:
    synop_rows = [
        {
            "code": 6447,
            "timestamp": "1999-07-01T06:00:00Z",
            "temp_min": 9.2,
            "temp_max": None,
        },
        {
            "code": 6455,
            "timestamp": "1999-07-01T06:00:00Z",
            "temp_min": 8.1,
            "temp_max": None,
        },
        {
            "code": 6455,
            "timestamp": "1999-07-01T18:00:00Z",
            "temp_min": None,
            "temp_max": 25.1,
        },
    ]
    daily = aggregate_synop_days(synop_rows, 1999)
    assert ("6447", date(1999, 7, 1)) not in daily
    assert daily[("6455", date(1999, 7, 1))] == (8.1, 25.1)

    # Minimal GHCN .dly line for Uccle.
    prefix = f"{GHCN_UCCLE_ID}199901TMAX"
    blocks = []
    for day in range(1, 32):
        blocks.append(f"{251:5d}   " if day == 1 else f"{-9999:5d}   ")
    parsed = parse_ghcn_dly_pre2000(
        (prefix + "".join(blocks) + "\n").encode("ascii")
    )
    assert parsed[date(1999, 1, 1)]["TMAX"] == 25.1

    windows = month_windows(2025)
    assert len(windows) == 12
    assert windows[0] == ("2025-01-01", "2025-02-01")
    assert windows[-1] == ("2025-12-01", "2026-01-01")

    records: dict[str, dict[str, Any]] = {}
    consume_day(
        records, "6447", date(1999, 1, 1), None, 25.1, "GHCN_UCCLE"
    )
    consume_day(
        records, "6455", date(1999, 7, 1), 8.1, 25.1, "RMI_SYNOP"
    )
    consume_day(
        records, "6447", date(2000, 7, 1), 10.2, 26.0, "RMI_AWS"
    )
    assert records["6447"]["provenance_days"]["GHCN_UCCLE"] == 1
    assert records["6447"]["provenance_days"]["RMI_SYNOP"] == 0
    assert records["6447"]["provenance_days"]["RMI_AWS"] == 1

    print("KMI/RMI Belgium hybrid historical cache self-test OK")


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
