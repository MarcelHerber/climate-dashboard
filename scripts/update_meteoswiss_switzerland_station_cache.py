#!/usr/bin/env python3
"""
MeteoSwiss Switzerland historical daily Tmin/Tmax cache.

Primary source only:
  MeteoSwiss SwissMetNet (SMN)
  Collection: ch.meteoschweiz.ogd-smn
  Daily Tmin: tre200dn
  Daily Tmax: tre200dx

The cache deliberately does NOT mix in homogeneous NBCN daily series.

Historical STAC assets are discovered dynamically per station. MeteoSwiss
splits historical data into files (normally decade chunks); all daily
historical assets are parsed and values are filtered to cutoff_year.

No API key / secret is required.
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
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

SOURCE = "MeteoSwiss Open Data"
NETWORK = "SwissMetNet"
COLLECTION_ID = "ch.meteoschweiz.ogd-smn"
STAC_ITEMS = (
    f"https://data.geo.admin.ch/api/stac/v1/collections/"
    f"{COLLECTION_ID}/items"
)
STATIONS_META = (
    f"https://data.geo.admin.ch/{COLLECTION_ID}/ogd-smn_meta_stations.csv"
)

TMIN_PARAM = "tre200dn"
TMAX_PARAM = "tre200dx"

# Official measured Swiss national extremes published by MeteoSwiss.
# Historical source values outside these bounds cannot be valid Swiss
# temperature observations and are excluded before record aggregation.
HISTORICAL_TMAX_CEILING_C = 41.5
HISTORICAL_TMIN_FLOOR_C = -41.8

FORMAT_VERSION = 2
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
UA = "climate-dashboard-meteoswiss-switzerland-cache/1.0"
TRIES = 5
TIMEOUT = 120
REQUEST_SLEEP = 0.05


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"meteoswiss_switzerland_daily_baseline_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"meteoswiss_switzerland_progress_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"meteoswiss_switzerland_status_through_{cutoff_year}.json"
    )


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
) -> bytes:
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
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            last = exc
            retryable = (
                not isinstance(exc, urllib.error.HTTPError)
                or exc.code in {408, 429, 500, 502, 503, 504}
            )
            if attempt >= TRIES or not retryable:
                raise
            wait = min(30, attempt * 4)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(f"Abruf fehlgeschlagen {url}: {last}")


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = request_bytes(url, params=params, accept="application/json,*/*")
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Keine JSON-Objektantwort: {url}")
    return obj


def decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:30])
    try:
        return csv.Sniffer().sniff(
            sample, delimiters=";,\t|"
        ).delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in (";", ",", "\t", "|")}
        return max(counts, key=counts.get)


def read_csv(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = decode_text(raw)
    delimiter = sniff_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return list(reader.fieldnames or []), [dict(row) for row in reader]


def norm(value: Any) -> str:
    s = str(value or "").lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def pick_column(
    fields: list[str],
    exact: tuple[str, ...],
    contains: tuple[str, ...] = (),
) -> str | None:
    by_norm = {norm(field): field for field in fields}
    for candidate in exact:
        if norm(candidate) in by_norm:
            return by_norm[norm(candidate)]
    for field in fields:
        n = norm(field)
        if any(norm(candidate) in n for candidate in contains):
            return field
    return None


def parse_day(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).date()
    except ValueError:
        pass

    for candidate, fmt in (
        (text[:10], "%Y-%m-%d"),
        (text[:8], "%Y%m%d"),
        (text[:10], "%d.%m.%Y"),
    ):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None


def temp_value(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        x = float(text.replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(x) or x < -90 or x > 65:
        return None
    return round(x, 2)


def apply_historical_extreme_qc(
    tmin: float | None,
    tmax: float | None,
    *,
    qc_stats: dict[str, Any] | None = None,
) -> tuple[float | None, float | None]:
    """Reject historical Swiss values contradicting official national extremes."""
    tn, tx = tmin, tmax
    if tx is not None and tx > HISTORICAL_TMAX_CEILING_C:
        if qc_stats is not None:
            qc_stats["qc_rejected_tmax"] = int(qc_stats.get("qc_rejected_tmax", 0)) + 1
        tx = None
    if tn is not None and tn < HISTORICAL_TMIN_FLOOR_C:
        if qc_stats is not None:
            qc_stats["qc_rejected_tmin"] = int(qc_stats.get("qc_rejected_tmin", 0)) + 1
        tn = None
    if tn is not None and tx is not None and tn > tx:
        if qc_stats is not None:
            qc_stats["qc_rejected_inconsistent_days"] = int(qc_stats.get("qc_rejected_inconsistent_days", 0)) + 1
        return None, None
    return tn, tx


def get_all_stac_items() -> list[dict[str, Any]]:
    url = STAC_ITEMS
    params: dict[str, Any] | None = {"limit": 100}
    items: list[dict[str, Any]] = []
    seen_urls = set()

    while url:
        key = (url, tuple(sorted((params or {}).items())))
        if key in seen_urls:
            raise RuntimeError("STAC-Paginierung läuft im Kreis.")
        seen_urls.add(key)

        payload = get_json(url, params)
        features = payload.get("features") or []
        if not isinstance(features, list):
            features = []
        items.extend(x for x in features if isinstance(x, dict))

        next_url = None
        for link in payload.get("links") or []:
            if (
                isinstance(link, dict)
                and link.get("rel") == "next"
                and link.get("href")
            ):
                next_url = str(link["href"])
                break

        url = next_url
        params = None

    return items


def station_id_from_item(item: dict[str, Any]) -> str:
    probes = [str(item.get("id", ""))]
    assets = item.get("assets")
    if isinstance(assets, dict):
        probes.extend(str(key) for key in assets)
        for meta in assets.values():
            if isinstance(meta, dict):
                probes.append(str(meta.get("href", "")))

    for probe in probes:
        match = re.search(
            r"ogd-smn[_/-]([a-z]{3})(?:[_./-]|$)",
            probe.lower(),
        )
        if match:
            return match.group(1).upper()

    # Fallback: station abbreviations are three letters and normally the last
    # useful token in the item id.
    tokens = re.findall(r"(?:^|[_-])([a-z]{3})(?:[_-]|$)", str(item.get("id","")).lower())
    return tokens[-1].upper() if tokens else ""


def asset_entries(item: dict[str, Any]) -> list[tuple[str, str]]:
    assets = item.get("assets")
    out = []
    if isinstance(assets, dict):
        for key, meta in assets.items():
            if isinstance(meta, dict) and meta.get("href"):
                out.append((str(key), str(meta["href"])))
    return out


def daily_asset_kind(name: str, href: str) -> str | None:
    text = f"{name} {href}".lower()
    filename = href.rsplit("/", 1)[-1].lower()

    daily = (
        re.search(r"_d_(?:historical|recent)(?:[_\-.]|$)", filename)
        or "_daily_" in filename
    )
    if not daily:
        return None

    if "historical" in text:
        return "historical"
    if "recent" in text:
        return "recent"
    return None


def historical_daily_assets(item: dict[str, Any]) -> list[str]:
    urls = []
    for name, href in asset_entries(item):
        if daily_asset_kind(name, href) == "historical":
            urls.append(href)
    return sorted(set(urls))


def recent_daily_assets(item: dict[str, Any]) -> list[str]:
    urls = []
    for name, href in asset_entries(item):
        if daily_asset_kind(name, href) == "recent":
            urls.append(href)
    return sorted(set(urls))


def load_station_metadata() -> dict[str, dict[str, Any]]:
    fields, rows = read_csv(request_bytes(STATIONS_META, accept="text/csv,*/*"))

    id_col = pick_column(
        fields,
        ("station_abbr", "station_id", "station", "abbr"),
        ("station", "abbr"),
    )
    name_col = pick_column(
        fields, ("station_name", "name"), ("station_name",)
    )
    lat_col = pick_column(
        fields,
        (
            "station_coordinates_wgs84_lat",
            "station_coordinates_wgs84_latitude",
            "latitude",
            "lat",
        ),
        ("wgs84_lat", "latitude"),
    )
    lon_col = pick_column(
        fields,
        (
            "station_coordinates_wgs84_lon",
            "station_coordinates_wgs84_longitude",
            "longitude",
            "lon",
        ),
        ("wgs84_lon", "longitude"),
    )
    elev_col = pick_column(
        fields,
        ("station_height_masl", "altitude", "elevation", "height"),
        ("altitude", "elevation", "height"),
    )
    wigos_col = pick_column(
        fields, ("wigos_id", "wigos"), ("wigos",)
    )

    if not id_col:
        raise RuntimeError("MeteoSwiss Stations-ID-Spalte nicht erkannt.")

    out = {}
    for row in rows:
        sid = str(row.get(id_col, "") or "").strip().upper()
        if not sid:
            continue

        def fnum(value: Any) -> float | None:
            try:
                x = float(str(value).replace(",", "."))
            except (TypeError, ValueError):
                return None
            return x if math.isfinite(x) else None

        out[sid] = {
            "id": sid,
            "name": str(row.get(name_col, "") or sid).strip() if name_col else sid,
            "country": "Switzerland",
            "country_code": "CH",
            "lat": fnum(row.get(lat_col)) if lat_col else None,
            "lon": fnum(row.get(lon_col)) if lon_col else None,
            "elevation_m": fnum(row.get(elev_col)) if elev_col else None,
            "wigos_id": str(row.get(wigos_col, "") or "").strip() if wigos_col else None,
            "network": NETWORK,
            "source": SOURCE,
        }

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
        "provenance_days": {"METEOSWISS_SMN": 0},
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
    rec["provenance_days"]["METEOSWISS_SMN"] += 1

    if tmax is not None:
        if better_max(rec["tmax_abs"], tmax, iso):
            rec["tmax_abs"] = [tmax, iso]
        old = rec["calendar_tmax"].get(mmdd)
        if better_max(old, tmax, iso):
            rec["calendar_tmax"][mmdd] = [tmax, iso]

    if tmin is not None:
        if better_min(rec["tmin_abs"], tmin, iso):
            rec["tmin_abs"] = [tmin, iso]
        old = rec["calendar_tmin"].get(mmdd)
        if better_min(old, tmin, iso):
            rec["calendar_tmin"][mmdd] = [tmin, iso]

    return True


def parse_daily_asset(
    raw: bytes,
    *,
    cutoff_year: int | None = None,
    only_year: int | None = None,
    historical_qc: bool = False,
    qc_stats: dict[str, Any] | None = None,
) -> list[tuple[date, float | None, float | None]]:
    fields, rows = read_csv(raw)

    date_col = pick_column(
        fields,
        (
            "reference_timestamp",
            "timestamp",
            "date",
            "datum",
            "reference_date",
        ),
        ("timestamp", "date", "datum"),
    )
    if not date_col:
        raise RuntimeError(
            "MeteoSwiss Daily CSV: Datumsspalte nicht erkannt: "
            + " | ".join(fields)
        )

    if TMIN_PARAM not in fields and TMAX_PARAM not in fields:
        # Historical chunks at a station may predate these parameters entirely.
        return []

    out = []
    for row in rows:
        d = parse_day(row.get(date_col))
        if d is None:
            continue
        if cutoff_year is not None and d.year > cutoff_year:
            continue
        if only_year is not None and d.year != only_year:
            continue

        tn = temp_value(row.get(TMIN_PARAM)) if TMIN_PARAM in fields else None
        tx = temp_value(row.get(TMAX_PARAM)) if TMAX_PARAM in fields else None
        if historical_qc:
            tn, tx = apply_historical_extreme_qc(tn, tx, qc_stats=qc_stats)
        if tn is None and tx is None:
            continue

        out.append((d, tn, tx))

    return out


def initial_progress(cutoff_year: int) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "network": NETWORK,
        "collection_id": COLLECTION_ID,
        "cutoff_year": cutoff_year,
        "inventory": {},
        "records": {},
        "processed_stations": [],
        "asset_count": 0,
        "rows_with_temperature": 0,
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
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
        "network": NETWORK,
        "cutoff_year": cutoff_year,
        "complete": bool(payload.get("complete")),
        "inventory_count": len(payload.get("inventory", {})),
        "station_count": len(payload.get("records", {})),
        "asset_count": int(payload.get("asset_count", 0)),
        "rows_with_temperature": int(payload.get("rows_with_temperature", 0)),
        "qc_rejected_tmax": int(payload.get("qc_rejected_tmax", 0)),
        "qc_rejected_tmin": int(payload.get("qc_rejected_tmin", 0)),
        "qc_rejected_inconsistent_days": int(payload.get("qc_rejected_inconsistent_days", 0)),
        "first_date": payload.get("first_date"),
        "last_date": payload.get("last_date"),
        "processed_station_count": len(payload.get("processed_stations", [])),
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
        raise RuntimeError(f"MeteoSwiss-Baseline fehlt/unvollständig: {path}")
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
    prog_file = progress_path(cache_dir, cutoff_year)

    if force:
        final.unlink(missing_ok=True)
        prog_file.unlink(missing_ok=True)
        status_path(cache_dir, cutoff_year).unlink(missing_ok=True)

    if not force and valid_final(final, cutoff_year):
        log(f"Verwende vorhandenen MeteoSwiss-Baselinecache: {final}")
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

    started = time.monotonic()

    log("=== METEOSWISS SCHWEIZ HISTORISCHE BASELINE ===")
    log(
        f"SwissMetNet | Tmin {TMIN_PARAM} | Tmax {TMAX_PARAM} | "
        f"daily historical | Cutoff {cutoff_year}"
    )
    log("NBCN-Homogenreihen werden NICHT eingemischt.")

    if not progress["inventory"]:
        progress["inventory"] = load_station_metadata()
        save_progress(cache_dir, cutoff_year, progress)

    items = get_all_stac_items()
    by_station = {}
    for item in items:
        sid = station_id_from_item(item)
        if sid:
            by_station[sid] = item

    log(
        f"Stations-Metadaten: {len(progress['inventory'])} | "
        f"STAC-Stationen: {len(by_station)}."
    )

    done = set(progress["processed_stations"])
    station_ids = sorted(by_station)

    for index, sid in enumerate(station_ids, start=1):
        if sid in done:
            continue

        assets = historical_daily_assets(by_station[sid])
        rec = empty_record()
        asset_used = 0

        for href in assets:
            raw = request_bytes(href, accept="text/csv,*/*")
            rows = parse_daily_asset(
                raw,
                cutoff_year=cutoff_year,
                historical_qc=True,
                qc_stats=progress,
            )
            if rows:
                asset_used += 1
            for d, tn, tx in rows:
                if consume_day(rec, d, tn, tx):
                    update_span(progress, d)
            time.sleep(REQUEST_SLEEP)

        if rec["observation_days"] > 0:
            progress["records"][sid] = rec

        progress["asset_count"] += asset_used
        progress["rows_with_temperature"] = sum(
            int(r.get("observation_days", 0))
            for r in progress["records"].values()
        )
        progress["processed_stations"].append(sid)
        done.add(sid)
        save_progress(cache_dir, cutoff_year, progress)

        if index % 10 == 0 or index == len(station_ids):
            log(
                f"MeteoSwiss: {index}/{len(station_ids)} Stationen geprüft | "
                f"{len(progress['records'])} Stationsreihen | "
                f"{progress['rows_with_temperature']:,} Stationstage | "
                f"{progress['asset_count']} historische Tagesdateien."
            )

        if (time.monotonic() - started) / 60 >= max_runtime_minutes:
            log(
                "Laufzeitgrenze erreicht. Zwischenstand gespeichert; "
                "Workflow mit force=false erneut starten."
            )
            return prog_file

    if not progress["records"]:
        raise RuntimeError("MeteoSwiss-Baseline enthält keine Stationsreihen.")

    progress["complete"] = True
    payload = {
        **progress,
        "parameters": {
            "TMIN": TMIN_PARAM,
            "TMAX": TMAX_PARAM,
        },
        "quality_note": (
            "Daily SwissMetNet station values only. Homogeneous NBCN daily "
            "series are intentionally not mixed into station records. "
            "Historical TMAX values above 41.5 C and TMIN values below -41.8 C "
            "are excluded because they contradict MeteoSwiss's published Swiss "
            "national measured extremes through the historical cutoff year."
        ),
        "public_url": (
            "https://data.geo.admin.ch/api/stac/v1/collections/"
            + COLLECTION_ID
        ),
    }

    atomic_pickle_gzip(final, payload)
    write_status(cache_dir, cutoff_year, payload)
    prog_file.unlink(missing_ok=True)

    log()
    log("=== METEOSWISS SWITZERLAND BASELINE SUMMARY ===")
    log(f"Stationsreihen: {len(payload['records'])}")
    log(f"Historische Tagesdateien: {payload['asset_count']}")
    log(f"Stationstage: {payload['rows_with_temperature']:,}")
    log(
        "Historische QC verworfen: "
        f"TMAX>{HISTORICAL_TMAX_CEILING_C:.1f} C = {payload.get('qc_rejected_tmax', 0):,} | "
        f"TMIN<{HISTORICAL_TMIN_FLOOR_C:.1f} C = {payload.get('qc_rejected_tmin', 0):,} | "
        f"TMIN>TMAX = {payload.get('qc_rejected_inconsistent_days', 0):,}"
    )
    log(f"Datenzeitraum: {payload['first_date']} bis {payload['last_date']}")
    log(f"Inventar: {len(payload['inventory'])} Stationen")
    log(f"Output: {final}")
    log("MeteoSwiss Switzerland Baseline OK.")
    return final


def self_test() -> None:
    raw = (
        b"station_abbr;reference_timestamp;tre200dn;tre200dx\n"
        b"BER;1864-01-01; -8.2; 1.4\n"
        b"BER;1864-01-02; -7.0; 2.5\n"
    )
    rows = parse_daily_asset(raw, cutoff_year=1864)
    assert len(rows) == 2
    assert rows[0][0] == date(1864, 1, 1)
    assert rows[0][1] == -8.2
    assert rows[0][2] == 1.4

    rec = empty_record()
    assert consume_day(rec, *rows[0]) is True
    assert consume_day(rec, *rows[1]) is True
    assert rec["calendar_tmin"]["01-01"] == [-8.2, "1864-01-01"]
    assert rec["calendar_tmax"]["01-02"] == [2.5, "1864-01-02"]

    qc = {}
    tn, tx = apply_historical_extreme_qc(-10.0, 51.8, qc_stats=qc)
    assert tn == -10.0 and tx is None
    assert qc["qc_rejected_tmax"] == 1
    tn, tx = apply_historical_extreme_qc(-50.0, 10.0, qc_stats=qc)
    assert tn is None and tx == 10.0
    assert qc["qc_rejected_tmin"] == 1

    bad_raw = (
        b"station_abbr;reference_timestamp;tre200dn;tre200dx\n"
        b"CMA;2000-01-02;-5.0;51.8\n"
        b"GRO;2003-08-11;20.0;41.5\n"
    )
    bad_rows = parse_daily_asset(
        bad_raw, cutoff_year=2025, historical_qc=True, qc_stats=qc
    )
    assert bad_rows[0][2] is None
    assert bad_rows[1][2] == 41.5

    meta_fields = [
        "station_abbr",
        "station_name",
        "station_height_masl",
        "station_coordinates_wgs84_lat",
        "station_coordinates_wgs84_lon",
    ]
    assert pick_column(
        meta_fields,
        ("station_coordinates_wgs84_lat", "latitude", "lat"),
        ("wgs84_lat", "latitude"),
    ) == "station_coordinates_wgs84_lat"
    assert pick_column(
        meta_fields,
        ("station_coordinates_wgs84_lon", "longitude", "lon"),
        ("wgs84_lon", "longitude"),
    ) == "station_coordinates_wgs84_lon"

    item = {
        "id": "ogd-smn_ber",
        "assets": {
            "h": {
                "href": (
                    "https://data.geo.admin.ch/x/"
                    "ogd-smn_ber_d_historical_1860-1869.csv"
                )
            },
            "r": {
                "href": (
                    "https://data.geo.admin.ch/x/"
                    "ogd-smn_ber_d_recent.csv"
                )
            },
        },
    }
    assert station_id_from_item(item) == "BER"
    assert len(historical_daily_assets(item)) == 1
    assert len(recent_daily_assets(item)) == 1

    print("MeteoSwiss Switzerland historical cache self-test OK")


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
