#!/usr/bin/env python3
"""
Build a compact Danish daily TMAX/TMIN station-record baseline.

Architecture
------------
1) DMI digitised Meteorological Yearbooks, 1867-1983:
   https://download.dmi.dk/public/opendata/STAKKEVIS/daily_data/
   Direct daily columns `tmax` and `tmin`.

2) GHCN-Daily transition bridge:
   - years missing from DMI yearbooks: 1971-1975, 1977, 1978
   - transition period 1984-2010
   Only Danish GHCN stations that can be mapped to a five-digit DMI/WMO
   station id are used. GHCN quality-flagged values are rejected.

3) DMI Climate Data, 2011 through cutoff year:
   official QC'd daily station values:
   `max_temp_w_date` and `min_temp`.

The cache stores records, not raw daily archives:
- first/last date
- observation-day count
- absolute TMAX/TMIN record
- calendar-day TMAX/TMIN records
- compact provenance counters

The overall public source is labelled "DMI Open Data"; the cache explicitly
documents GHCN-Daily as a transition/coverage bridge.
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SOURCE = "DMI Open Data"
BRIDGE_SOURCE = "GHCN-Daily"
PUBLIC_URL = "https://www.dmi.dk/friedata/"
YEARBOOK_DOC_URL = (
    "https://www.dmi.dk/friedata/dokumentation/data/"
    "historical-observations-from-1873"
)
YEARBOOK_BASE = "https://download.dmi.dk/public/opendata/STAKKEVIS/daily_data/"

DMI_API = "https://opendataapi.dmi.dk/v2"
CLIMATE_STATIONS_URL = f"{DMI_API}/climateData/collections/station/items"
METOBS_STATIONS_URL = f"{DMI_API}/metObs/collections/station/items"
CLIMATE_VALUES_URL = f"{DMI_API}/climateData/collections/stationValue/items"

GHCN_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
GHCN_STATIONS_URL = f"{GHCN_BASE}/ghcnd-stations.txt"
GHCN_ALL_BASE = f"{GHCN_BASE}/all"

DENMARK_BBOX = "7,54,16,58"
COPENHAGEN = ZoneInfo("Europe/Copenhagen")

YEARBOOK_FIRST_YEAR = 1867
YEARBOOK_LAST_YEAR = 1983
MISSING_YEARBOOK_YEARS = {1971, 1972, 1973, 1974, 1975, 1977, 1978}
GHCN_BRIDGE_FIRST_YEAR = 1984
GHCN_BRIDGE_LAST_YEAR = 2010
CLIMATE_FIRST_YEAR = 2011

CLIMATE_TMAX = "max_temp_w_date"
CLIMATE_TMIN = "min_temp"

BASELINE_FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")

MAX_HTTP_TRIES = 6
HTTP_TIMEOUT = 150
REQUEST_SLEEP = 0.15

UA = "climate-dashboard-dmi-denmark-cache/1.0"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"dmi_denmark_daily_baseline_through_{cutoff_year}"
        f"_v{BASELINE_FORMAT_VERSION}.pkl.gz"
    )


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"dmi_denmark_progress_through_{cutoff_year}"
        f"_v{BASELINE_FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"dmi_denmark_status_through_{cutoff_year}.json"


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as handle:
            pickle.dump(obj, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_pickle_gzip(path: Path) -> Any:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


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
    allow_404: bool = False,
) -> bytes | None:
    if params:
        query = urllib.parse.urlencode(params, doseq=True, safe=",:/+")
        url = f"{url}?{query}"

    last: Exception | None = None

    for attempt in range(1, MAX_HTTP_TRIES + 1):
        if REQUEST_SLEEP:
            time.sleep(REQUEST_SLEEP)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404 and allow_404:
                return None
            if exc.code in {408, 429, 500, 502, 503, 504} and attempt < MAX_HTTP_TRIES:
                wait = min(60, attempt * 5)
                log(f"WARNUNG HTTP {exc.code}: {url}; neuer Versuch in {wait}s …")
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt >= MAX_HTTP_TRIES:
                break
            wait = min(45, attempt * 4)
            log(f"WARNUNG {exc}: {url}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(f"HTTP-Abruf fehlgeschlagen: {url}: {last}")


def request_text(url: str, **kwargs: Any) -> str:
    raw = request_bytes(url, **kwargs)
    if raw is None:
        return ""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = request_bytes(url, params=params)
    if not raw:
        raise RuntimeError(f"Leere JSON-Antwort: {url}")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unerwartete JSON-Struktur: {url}")
    return payload


def paged_features(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    payload = request_json(url, params=params)
    result = list(payload.get("features") or [])
    pages = 1

    while pages < max_pages:
        next_url = None
        for link in payload.get("links") or []:
            if isinstance(link, dict) and link.get("rel") == "next":
                next_url = link.get("href")
                break
        if not next_url:
            break
        payload = request_json(str(next_url))
        result.extend(payload.get("features") or [])
        pages += 1

    return [x for x in result if isinstance(x, dict)]


def prop(feature: dict[str, Any], key: str, default: Any = None) -> Any:
    properties = feature.get("properties")
    return properties.get(key, default) if isinstance(properties, dict) else default


def _first_number(mapping: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = mapping.get(key)
        try:
            x = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):
            return x
    return None


def _first_text(mapping: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def merge_dmi_station_inventory(
    feature_groups: list[list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for features in feature_groups:
        for feature in features:
            if str(prop(feature, "country", "")).upper() != "DNK":
                continue
            sid = str(prop(feature, "stationId", "")).strip()
            if not sid:
                continue
            grouped.setdefault(sid, []).append(feature)

    inventory: dict[str, dict[str, Any]] = {}

    for sid, features in grouped.items():
        rows: list[dict[str, Any]] = []
        for feature in features:
            p = dict(feature.get("properties") or {})
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) >= 2:
                p["_lon"] = coords[0]
                p["_lat"] = coords[1]
            rows.append(p)

        def rank(row: dict[str, Any]) -> tuple[int, int, str]:
            active = str(row.get("status", "")).lower() == "active"
            has_coords = row.get("_lat") is not None and row.get("_lon") is not None
            return (0 if active else 1, 0 if has_coords else 1, str(row.get("validFrom") or ""))

        rows.sort(key=rank)
        chosen = rows[0]
        names = [
            str(row.get("name")).strip()
            for row in rows
            if row.get("name") not in (None, "")
        ]
        starts = [
            str(row.get("operationFrom"))[:10]
            for row in rows
            if row.get("operationFrom")
        ]
        ends = [
            str(row.get("operationTo"))[:10]
            for row in rows
            if row.get("operationTo")
        ]

        wmo = None
        for row in rows:
            value = row.get("wmoStationId")
            if value not in (None, ""):
                wmo = str(value).strip().zfill(5)
                break

        inventory[sid] = {
            "id": sid,
            "name": names[-1] if names else sid,
            "country": "Denmark",
            "country_code": "DK",
            "lat": _first_number(chosen, ("_lat", "latitude", "lat")),
            "lon": _first_number(chosen, ("_lon", "longitude", "lon")),
            "elevation_m": _first_number(
                chosen, ("height", "elevation", "altitude", "elevation_m")
            ),
            "status": "Active"
            if any(str(x.get("status", "")).lower() == "active" for x in rows)
            else str(chosen.get("status") or ""),
            "operation_from": min(starts) if starts else None,
            "operation_to": max(ends) if ends else None,
            "wmo_station_id": wmo,
            "source": SOURCE,
        }

    return inventory


def fetch_dmi_inventory() -> dict[str, dict[str, Any]]:
    params = {"limit": 1000, "bbox": DENMARK_BBOX}
    climate = paged_features(CLIMATE_STATIONS_URL, params, max_pages=20)
    metobs = paged_features(METOBS_STATIONS_URL, params, max_pages=20)
    return merge_dmi_station_inventory([climate, metobs])


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


def consume_row(
    records: dict[str, dict[str, Any]],
    station_id: str,
    d: date,
    tmin: float | None,
    tmax: float | None,
    *,
    provenance: str,
) -> bool:
    if tmin is None and tmax is None:
        return False

    rec = records.setdefault(station_id, empty_record())
    iso = d.isoformat()
    mmdd = d.strftime("%m-%d")

    if rec["first_date"] is None or iso < rec["first_date"]:
        rec["first_date"] = iso
    if rec["last_date"] is None or iso > rec["last_date"]:
        rec["last_date"] = iso

    rec["observation_days"] += 1
    prov = rec.setdefault("provenance_days", {})
    prov[provenance] = int(prov.get(provenance, 0)) + 1

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


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", ".")
    if text.lower() in {"nan", "na", "null", "-", "--", "////"}:
        return None
    try:
        x = float(text)
    except ValueError:
        return None
    if not math.isfinite(x) or x < -90 or x > 65:
        return None
    return x


def discover_yearbook_urls() -> list[str]:
    html = request_text(YEARBOOK_BASE)
    hrefs = re.findall(r'href=["\']([^"\']+\.csv)["\']', html, flags=re.I)
    return sorted({urllib.parse.urljoin(YEARBOOK_BASE, x) for x in hrefs})


def parse_yearbook_csv(
    raw: bytes,
) -> tuple[list[tuple[str, date, float | None, float | None]], dict[str, str]]:
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], {}

    fields = {str(name).strip().lower(): name for name in reader.fieldnames}
    required = ("#statid", "yyyy", "mm", "dd", "tmax", "tmin")
    if not all(k in fields for k in required):
        return [], {}

    rows: list[tuple[str, date, float | None, float | None]] = []
    names: dict[str, str] = {}

    for row in reader:
        sid_raw = str(row.get(fields["#statid"], "")).strip()
        sid_digits = re.sub(r"\D", "", sid_raw)
        if not sid_digits:
            continue
        sid = sid_digits.zfill(5)[-5:]

        # Danish historical land stations in this yearbook archive are in the
        # 20xxx-32xxx block. 33xxx is Faroe; 34xxx is Greenland.
        try:
            station_number = int(sid)
        except ValueError:
            continue
        if not (20000 <= station_number <= 32999):
            continue

        try:
            y = int(float(str(row.get(fields["yyyy"], "")).replace(",", ".")))
            m = int(float(str(row.get(fields["mm"], "")).replace(",", ".")))
            day = int(float(str(row.get(fields["dd"], "")).replace(",", ".")))
            d = date(y, m, day)
        except (ValueError, TypeError):
            continue

        if d.year < YEARBOOK_FIRST_YEAR or d.year > YEARBOOK_LAST_YEAR:
            continue
        if d.year in MISSING_YEARBOOK_YEARS:
            # DMI says no Meteorological Yearbook was published for these years.
            continue

        tx = parse_float(row.get(fields["tmax"]))
        tn = parse_float(row.get(fields["tmin"]))
        if tx is None and tn is None:
            continue

        rows.append((sid, d, tn, tx))

        name_col = fields.get("stnavn")
        if name_col:
            name = str(row.get(name_col, "")).strip()
            if name:
                names[sid] = name

    return rows, names


def ensure_yearbook_inventory(
    inventory: dict[str, dict[str, Any]],
    sid: str,
    name: str | None,
) -> None:
    if sid in inventory:
        if name and (
            not inventory[sid].get("name")
            or inventory[sid].get("name") == sid
        ):
            inventory[sid]["name"] = name
        return

    inventory[sid] = {
        "id": sid,
        "name": name or sid,
        "country": "Denmark",
        "country_code": "DK",
        "lat": None,
        "lon": None,
        "elevation_m": None,
        "status": "Historical",
        "operation_from": None,
        "operation_to": None,
        "wmo_station_id": None,
        "source": SOURCE,
    }


def parse_ghcn_station_catalog(text: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        if len(line) < 71:
            continue
        ghcn_id = line[0:11].strip()
        if not ghcn_id.startswith("DA"):
            continue
        try:
            lat = float(line[12:20])
            lon = float(line[21:30])
        except ValueError:
            continue
        try:
            elev = float(line[31:37])
            if elev <= -999:
                elev = None
        except ValueError:
            elev = None
        name = line[41:71].strip()
        out[ghcn_id] = {
            "ghcn_id": ghcn_id,
            "name": name,
            "lat": lat,
            "lon": lon,
            "elevation_m": elev,
        }
    return out


def map_ghcn_to_dmi_id(
    ghcn_id: str,
    dmi_inventory: dict[str, dict[str, Any]],
) -> str | None:
    # WMO-based GHCN IDs for Denmark have the form DAM00006030.
    suffix = ghcn_id[-5:]
    if not suffix.isdigit():
        return None

    if suffix in dmi_inventory:
        return suffix

    for sid, meta in dmi_inventory.items():
        wmo = str(meta.get("wmo_station_id") or "").zfill(5)
        if wmo == suffix:
            return sid

    # Keep a WMO-style DMI id even if DMI's current station inventory no
    # longer contains the station. GHCN metadata then supplies map position.
    return suffix


def ensure_ghcn_inventory(
    inventory: dict[str, dict[str, Any]],
    sid: str,
    meta: dict[str, Any],
) -> None:
    if sid in inventory:
        return
    inventory[sid] = {
        "id": sid,
        "name": meta.get("name") or sid,
        "country": "Denmark",
        "country_code": "DK",
        "lat": meta.get("lat"),
        "lon": meta.get("lon"),
        "elevation_m": meta.get("elevation_m"),
        "status": "Historical",
        "operation_from": None,
        "operation_to": None,
        "wmo_station_id": sid if sid.isdigit() and len(sid) == 5 else None,
        "source": SOURCE,
        "metadata_fallback": BRIDGE_SOURCE,
    }


def wanted_bridge_year(year: int) -> bool:
    return year in MISSING_YEARBOOK_YEARS or (
        GHCN_BRIDGE_FIRST_YEAR <= year <= GHCN_BRIDGE_LAST_YEAR
    )


def parse_ghcn_dly(
    text: str,
    *,
    station_id: str,
) -> list[tuple[str, date, float | None, float | None]]:
    by_day: dict[date, dict[str, float]] = {}

    for line in text.splitlines():
        if len(line) < 269:
            continue
        element = line[17:21]
        if element not in {"TMAX", "TMIN"}:
            continue

        try:
            year = int(line[11:15])
            month = int(line[15:17])
        except ValueError:
            continue

        if not wanted_bridge_year(year):
            continue

        for day in range(1, 32):
            offset = 21 + (day - 1) * 8
            field = line[offset : offset + 8]
            if len(field) < 8:
                continue
            try:
                raw_value = int(field[0:5])
            except ValueError:
                continue
            qflag = field[6:7]
            if raw_value == -9999 or qflag.strip():
                continue
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            value = raw_value / 10.0
            if not -90 <= value <= 65:
                continue
            by_day.setdefault(d, {})[element] = value

    rows = []
    for d in sorted(by_day):
        values = by_day[d]
        rows.append(
            (
                station_id,
                d,
                values.get("TMIN"),
                values.get("TMAX"),
            )
        )
    return rows


def parse_rfc3339(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def climate_feature_local_day(feature: dict[str, Any]) -> date | None:
    dt = parse_rfc3339(prop(feature, "from"))
    if dt is None:
        return None
    return dt.astimezone(COPENHAGEN).date()


def fetch_climate_parameter_year(
    parameter: str,
    year: int,
) -> list[dict[str, Any]]:
    start = date(year, 1, 1) - timedelta(days=1)
    end = date(year + 1, 1, 1) + timedelta(days=1)
    return paged_features(
        CLIMATE_VALUES_URL,
        {
            "bbox": DENMARK_BBOX,
            "parameterId": parameter,
            "timeResolution": "day",
            "datetime": (
                f"{start.isoformat()}T00:00:00Z/"
                f"{end.isoformat()}T23:59:59Z"
            ),
            "limit": 300000,
        },
        max_pages=20,
    )


def climate_year_rows(
    year: int,
    inventory: dict[str, dict[str, Any]],
) -> list[tuple[str, date, float | None, float | None]]:
    # DMI may expose duplicate stationValue objects. Their documentation says
    # the newest `created` timestamp is the authoritative one.
    values: dict[tuple[str, date], dict[str, tuple[datetime, float]]] = {}

    for parameter, element in (
        (CLIMATE_TMAX, "TMAX"),
        (CLIMATE_TMIN, "TMIN"),
    ):
        features = fetch_climate_parameter_year(parameter, year)
        for feature in features:
            sid = str(prop(feature, "stationId", "")).strip()
            if not sid:
                continue
            if sid not in inventory:
                # Keep only Danish stations. The bbox can in theory include a
                # neighbouring country's station.
                continue

            d = climate_feature_local_day(feature)
            if d is None or d.year != year:
                continue

            try:
                value = float(prop(feature, "value"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value) or value < -90 or value > 65:
                continue

            created = parse_rfc3339(prop(feature, "created"))
            if created is None:
                created = datetime(1970, 1, 1, tzinfo=timezone.utc)

            key = (sid, d)
            old = values.setdefault(key, {}).get(element)
            if old is None or created > old[0]:
                values[key][element] = (created, value)

    rows = []
    for (sid, d), pair in sorted(values.items()):
        rows.append(
            (
                sid,
                d,
                pair.get("TMIN", (None, None))[1],
                pair.get("TMAX", (None, None))[1],
            )
        )
    return rows


def make_progress(cutoff_year: int) -> dict[str, Any]:
    return {
        "format_version": BASELINE_FORMAT_VERSION,
        "source": SOURCE,
        "bridge_source": BRIDGE_SOURCE,
        "cutoff_year": cutoff_year,
        "stage": "inventory",
        "inventory": {},
        "records": {},
        "yearbook_urls": [],
        "yearbook_done": [],
        "yearbook_files_used": 0,
        "yearbook_rows_with_temperature": 0,
        "ghcn_ids": [],
        "ghcn_done": [],
        "ghcn_rows_with_temperature": 0,
        "ghcn_station_count": 0,
        "climate_next_year": CLIMATE_FIRST_YEAR,
        "climate_processed_years": 0,
        "climate_rows_with_temperature": 0,
        "complete": False,
    }


def write_status(cache_dir: Path, cutoff_year: int, progress: dict[str, Any]) -> None:
    records = progress.get("records", {})
    inventory = progress.get("inventory", {})
    with_coords = sum(
        1
        for x in inventory.values()
        if x.get("lat") is not None and x.get("lon") is not None
    )
    status = {
        "format_version": BASELINE_FORMAT_VERSION,
        "source": SOURCE,
        "bridge_source": BRIDGE_SOURCE,
        "cutoff_year": cutoff_year,
        "stage": progress.get("stage"),
        "complete": bool(progress.get("complete")),
        "station_count": len(records),
        "inventory_count": len(inventory),
        "inventory_with_coordinates": with_coords,
        "yearbook_files_total": len(progress.get("yearbook_urls", [])),
        "yearbook_files_processed": len(progress.get("yearbook_done", [])),
        "yearbook_files_used": progress.get("yearbook_files_used", 0),
        "yearbook_rows_with_temperature": progress.get(
            "yearbook_rows_with_temperature", 0
        ),
        "ghcn_station_files_total": len(progress.get("ghcn_ids", [])),
        "ghcn_station_files_processed": len(progress.get("ghcn_done", [])),
        "ghcn_station_count": progress.get("ghcn_station_count", 0),
        "ghcn_rows_with_temperature": progress.get(
            "ghcn_rows_with_temperature", 0
        ),
        "climate_next_year": progress.get("climate_next_year"),
        "climate_processed_years": progress.get("climate_processed_years", 0),
        "climate_rows_with_temperature": progress.get(
            "climate_rows_with_temperature", 0
        ),
        "rows_with_temperature": (
            int(progress.get("yearbook_rows_with_temperature", 0))
            + int(progress.get("ghcn_rows_with_temperature", 0))
            + int(progress.get("climate_rows_with_temperature", 0))
        ),
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
            and obj.get("format_version") == BASELINE_FORMAT_VERSION
            and obj.get("cutoff_year") == cutoff_year
            and obj.get("complete") is True
            and obj.get("records")
        )
    except Exception:
        return False


def load_baseline(cache_dir: Path, cutoff_year: int) -> dict[str, Any]:
    path = baseline_path(cache_dir, cutoff_year)
    if not valid_final(path, cutoff_year):
        raise RuntimeError(f"DMI Denmark Baseline fehlt/ist unvollständig: {path}")
    obj = load_pickle_gzip(path)
    assert isinstance(obj, dict)
    return obj


def runtime_reached(started: float, limit_minutes: float) -> bool:
    return (time.monotonic() - started) / 60.0 >= limit_minutes


def build_baseline(
    cache_dir: Path,
    cutoff_year: int,
    *,
    force: bool = False,
    max_runtime_minutes: float = 140.0,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    final = baseline_path(cache_dir, cutoff_year)
    prog = progress_path(cache_dir, cutoff_year)
    stat = status_path(cache_dir, cutoff_year)

    if force:
        for path in (final, prog, stat):
            path.unlink(missing_ok=True)

    if not force and valid_final(final, cutoff_year):
        log(f"Verwende vorhandenen DMI-Dänemark-Baselinecache: {final}")
        return final

    if not force and prog.exists():
        try:
            progress = load_pickle_gzip(prog)
            if (
                progress.get("format_version") != BASELINE_FORMAT_VERSION
                or progress.get("cutoff_year") != cutoff_year
            ):
                progress = make_progress(cutoff_year)
        except Exception:
            progress = make_progress(cutoff_year)
    else:
        progress = make_progress(cutoff_year)

    started = time.monotonic()

    log("=== DMI DÄNEMARK HISTORISCHE BASELINE ===")
    log(
        f"Ziel: Jahrbücher {YEARBOOK_FIRST_YEAR}-{YEARBOOK_LAST_YEAR} + "
        f"GHCN-Brücke 1984-2010 / fehlende Jahrbuchjahre + "
        f"DMI climateData {CLIMATE_FIRST_YEAR}-{cutoff_year}."
    )

    # Stage 1: DMI station inventory.
    if progress["stage"] == "inventory":
        inventory = fetch_dmi_inventory()
        if not inventory:
            raise RuntimeError("DMI-Stationsinventar für Dänemark ist leer.")
        progress["inventory"] = inventory
        progress["yearbook_urls"] = discover_yearbook_urls()
        if not progress["yearbook_urls"]:
            raise RuntimeError("Keine DMI-Jahrbuch-CSV-Dateien entdeckt.")
        progress["stage"] = "yearbooks"
        save_progress(cache_dir, cutoff_year, progress)
        log(
            f"DMI Inventar: {len(inventory)} Stationen | "
            f"historisches Verzeichnis: {len(progress['yearbook_urls'])} CSV-Dateien."
        )

    # Stage 2: DMI digitised yearbooks.
    if progress["stage"] == "yearbooks":
        done = set(progress.get("yearbook_done", []))
        urls = progress["yearbook_urls"]

        for idx, url in enumerate(urls, 1):
            if url in done:
                continue

            raw = request_bytes(url)
            if raw is None:
                continue
            rows, names = parse_yearbook_csv(raw)

            used = False
            for sid, d, tn, tx in rows:
                ensure_yearbook_inventory(
                    progress["inventory"], sid, names.get(sid)
                )
                if consume_row(
                    progress["records"],
                    sid,
                    d,
                    tn,
                    tx,
                    provenance="DMI_YEARBOOK",
                ):
                    progress["yearbook_rows_with_temperature"] += 1
                    used = True

            if used:
                progress["yearbook_files_used"] += 1

            progress["yearbook_done"].append(url)
            done.add(url)
            save_progress(cache_dir, cutoff_year, progress)

            log(
                f"DMI Jahrbuch: {len(done)}/{len(urls)} Dateien | "
                f"{progress['yearbook_files_used']} DK-Dateien genutzt | "
                f"{progress['yearbook_rows_with_temperature']:,} Temperaturtage."
            )

            if runtime_reached(started, max_runtime_minutes):
                log("Laufzeitgrenze erreicht; DMI-Zwischenstand gespeichert.")
                return prog

        progress["stage"] = "ghcn_catalog"
        save_progress(cache_dir, cutoff_year, progress)

    # Stage 3a: Danish GHCN station catalogue.
    if progress["stage"] == "ghcn_catalog":
        catalog = parse_ghcn_station_catalog(request_text(GHCN_STATIONS_URL))
        if not catalog:
            raise RuntimeError("Keine dänischen GHCN-Stationen gefunden.")

        mapped = {}
        for ghcn_id, meta in catalog.items():
            sid = map_ghcn_to_dmi_id(ghcn_id, progress["inventory"])
            if sid is None:
                continue
            mapped[ghcn_id] = sid
            ensure_ghcn_inventory(progress["inventory"], sid, meta)

        progress["ghcn_map"] = mapped
        progress["ghcn_catalog"] = catalog
        progress["ghcn_ids"] = sorted(mapped)
        progress["stage"] = "ghcn"
        save_progress(cache_dir, cutoff_year, progress)

        log(
            f"GHCN Dänemark: {len(catalog)} Metadatenstationen | "
            f"{len(mapped)} auf DMI/WMO-Kennung abbildbar."
        )

    # Stage 3b: GHCN bridge station files.
    if progress["stage"] == "ghcn":
        done = set(progress.get("ghcn_done", []))
        ids = progress.get("ghcn_ids", [])

        for idx, ghcn_id in enumerate(ids, 1):
            if ghcn_id in done:
                continue

            raw = request_bytes(
                f"{GHCN_ALL_BASE}/{ghcn_id}.dly", allow_404=True
            )
            if raw:
                text = raw.decode("ascii", errors="replace")
                sid = progress["ghcn_map"][ghcn_id]
                rows = parse_ghcn_dly(text, station_id=sid)
                station_used = False
                for row_sid, d, tn, tx in rows:
                    if consume_row(
                        progress["records"],
                        row_sid,
                        d,
                        tn,
                        tx,
                        provenance="GHCN_BRIDGE",
                    ):
                        progress["ghcn_rows_with_temperature"] += 1
                        station_used = True
                if station_used:
                    progress["ghcn_station_count"] += 1

            progress["ghcn_done"].append(ghcn_id)
            done.add(ghcn_id)

            if len(done) % 10 == 0 or len(done) == len(ids):
                save_progress(cache_dir, cutoff_year, progress)
                log(
                    f"GHCN-Brücke: {len(done)}/{len(ids)} Stationsdateien | "
                    f"{progress['ghcn_station_count']} Stationen mit Brückendaten | "
                    f"{progress['ghcn_rows_with_temperature']:,} Temperaturtage."
                )

            if runtime_reached(started, max_runtime_minutes):
                save_progress(cache_dir, cutoff_year, progress)
                log("Laufzeitgrenze erreicht; GHCN-Zwischenstand gespeichert.")
                return prog

        # large catalog is not needed in the final compact cache/progress.
        progress.pop("ghcn_catalog", None)
        progress["stage"] = "climate"
        save_progress(cache_dir, cutoff_year, progress)

    # Stage 4: DMI climateData official daily station values.
    if progress["stage"] == "climate":
        year = max(
            CLIMATE_FIRST_YEAR,
            int(progress.get("climate_next_year", CLIMATE_FIRST_YEAR)),
        )

        while year <= cutoff_year:
            rows = climate_year_rows(year, progress["inventory"])
            if not rows:
                raise RuntimeError(
                    f"DMI climateData liefert für {year} keine täglichen TMAX/TMIN-Werte."
                )

            consumed = 0
            for sid, d, tn, tx in rows:
                if consume_row(
                    progress["records"],
                    sid,
                    d,
                    tn,
                    tx,
                    provenance="DMI_CLIMATE",
                ):
                    consumed += 1

            progress["climate_rows_with_temperature"] += consumed
            progress["climate_processed_years"] += 1
            progress["climate_next_year"] = year + 1
            save_progress(cache_dir, cutoff_year, progress)

            log(
                f"DMI climateData: bis {year} | "
                f"{progress['climate_processed_years']}/"
                f"{max(0, cutoff_year-CLIMATE_FIRST_YEAR+1)} Jahre | "
                f"{len(progress['records'])} Stationsreihen | "
                f"{progress['climate_rows_with_temperature']:,} Temperaturtage."
            )

            if runtime_reached(started, max_runtime_minutes):
                log("Laufzeitgrenze erreicht; climateData-Zwischenstand gespeichert.")
                return prog

            year += 1

        progress["stage"] = "finalize"

    if progress["stage"] == "finalize":
        if not progress["records"]:
            raise RuntimeError("DMI-Dänemark-Baseline enthält keine Datensätze.")

        progress["complete"] = True
        progress["stage"] = "complete"

        # Retain only compact mapping state needed for transparency/debugging.
        progress.pop("ghcn_map", None)
        progress.pop("yearbook_urls", None)
        progress.pop("yearbook_done", None)
        progress.pop("ghcn_ids", None)
        progress.pop("ghcn_done", None)

        final_payload = {
            **progress,
            "complete": True,
            "public_url": PUBLIC_URL,
            "yearbook_public_url": YEARBOOK_DOC_URL,
            "bridge_public_url": GHCN_BASE,
            "segments": [
                {
                    "period": "1867-1983",
                    "source": SOURCE,
                    "product": "digitised Meteorological Yearbooks",
                    "note": (
                        "No DMI yearbooks were published in 1971-1975, 1977, 1978."
                    ),
                },
                {
                    "period": "1971-1975, 1977-1978 and 1984-2010",
                    "source": BRIDGE_SOURCE,
                    "product": "GHCN-Daily transition bridge",
                    "note": (
                        "Only quality-unflagged Danish TMAX/TMIN mapped to "
                        "five-digit DMI/WMO station identifiers."
                    ),
                },
                {
                    "period": f"2011-{cutoff_year}",
                    "source": SOURCE,
                    "product": "climateData stationValue",
                    "parameters": [CLIMATE_TMAX, CLIMATE_TMIN],
                    "day_type": "Danish local day",
                },
            ],
            "notes": (
                "Compact daily TMAX/TMIN record cache. Raw daily rows are not retained. "
                "DMI yearbook data are digitised historical observations and should be "
                "treated with DMI's published caution regarding possible digitisation errors."
            ),
        }

        atomic_pickle_gzip(final, final_payload)
        write_status(cache_dir, cutoff_year, final_payload)
        prog.unlink(missing_ok=True)

        log()
        log("=== DMI DENMARK BASELINE SUMMARY ===")
        log(f"Stationsreihen: {len(final_payload['records'])}")
        log(
            f"Jahrbuch-Tage: {final_payload['yearbook_rows_with_temperature']:,}"
        )
        log(
            f"GHCN-Brücken-Tage: {final_payload['ghcn_rows_with_temperature']:,}"
        )
        log(
            f"DMI climateData-Tage: {final_payload['climate_rows_with_temperature']:,}"
        )
        log(f"Output: {final}")
        log("DMI Denmark Baseline OK.")
        return final

    save_progress(cache_dir, cutoff_year, progress)
    return prog


def self_test() -> None:
    # Historical CSV parser.
    sample_csv = b"""#statid,stnavn,tabnavn,YYYY,MM,DD,tmax,tmin
20000,Skagen Fyr,x,1901,1,1,5.4,-1.2
20000,Skagen Fyr,x,1901,1,2,6.1,-2.0
33060,Hoyvik,x,1901,1,1,8.0,2.0
"""
    rows, names = parse_yearbook_csv(sample_csv)
    assert len(rows) == 2
    assert rows[0] == ("20000", date(1901, 1, 1), -1.2, 5.4)
    assert names["20000"] == "Skagen Fyr"

    # GHCN mapping and fixed-width daily parser.
    inv = {
        "06030": {
            "id": "06030",
            "wmo_station_id": "06030",
        }
    }
    assert map_ghcn_to_dmi_id("DAM00006030", inv) == "06030"

    def ghcn_line(element: str, values: dict[int, int]) -> str:
        line = "DAM00006030198401" + element
        for day in range(1, 32):
            value = values.get(day, -9999)
            line += f"{value:5d}   "
        return line

    ghcn_rows = parse_ghcn_dly(
        "\n".join(
            [
                ghcn_line("TMAX", {1: 123, 2: 150}),
                ghcn_line("TMIN", {1: -20, 2: -10}),
            ]
        ),
        station_id="06030",
    )
    assert ghcn_rows[0] == ("06030", date(1984, 1, 1), -2.0, 12.3)

    # Local-day conversion: winter 23:00 UTC is next Danish day.
    feature = {
        "properties": {
            "from": "2017-01-31T23:00:00Z",
        }
    }
    assert climate_feature_local_day(feature) == date(2017, 2, 1)

    # Record/tie behaviour.
    records: dict[str, dict[str, Any]] = {}
    consume_row(
        records, "06030", date(2000, 1, 2), -3.0, 10.0,
        provenance="TEST"
    )
    consume_row(
        records, "06030", date(1999, 1, 2), -3.0, 10.0,
        provenance="TEST"
    )
    assert records["06030"]["tmax_abs"] == [10.0, "1999-01-02"]
    assert records["06030"]["tmin_abs"] == [-3.0, "1999-01-02"]

    print("DMI Denmark historical cache self-test OK")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    p.add_argument("--cutoff-year", type=int, default=date.today().year - 1)
    p.add_argument("--force", action="store_true")
    p.add_argument("--max-runtime-minutes", type=float, default=140.0)
    args = p.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.cutoff_year < CLIMATE_FIRST_YEAR:
        raise RuntimeError("cutoff-year muss mindestens 2011 sein.")

    build_baseline(
        Path(args.cache_dir),
        args.cutoff_year,
        force=args.force,
        max_runtime_minutes=args.max_runtime_minutes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
