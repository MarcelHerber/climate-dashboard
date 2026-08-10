#!/usr/bin/env python3
"""
Build compact historical daily TMIN/TMAX station records for Finland
from Finnish Meteorological Institute (FMI) Open Data WFS.

Official observation query:
  fmi::observations::weather::daily::multipointcoverage

Variables: tmin, tmax
No API key is required.
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
import xml.etree.ElementTree as ET
from calendar import monthrange
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SOURCE = "FMI Open Data"
PUBLIC_URL = "https://en.ilmatieteenlaitos.fi/open-data"
WFS_URL = "https://opendata.fmi.fi/wfs"
STORED_QUERY = "fmi::observations::weather::daily::multipointcoverage"
FINLAND_BBOX = "19.0,59.0,32.0,71.5"
COUNTRY = "Finland"
COUNTRY_CODE = "FI"
PARAM_TMIN = "tmin"
PARAM_TMAX = "tmax"

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
START_DATE = date(1844, 1, 1)

# Official FMI measured national records through 2025.
OFFICIAL_RECORD_REFERENCE_YEAR = 2025
OFFICIAL_TMAX_RECORD_C = 37.2
OFFICIAL_TMIN_RECORD_C = -51.5

# For future historical cutoffs after the verified reference year.
EMERGENCY_TMAX_CEILING_C = 45.0
EMERGENCY_TMIN_FLOOR_C = -60.0

UA = "climate-dashboard-fmi-finland-cache/1.0"
TRIES = 6
HTTP_TIMEOUT = 180
REQUEST_SLEEP = 0.55


def log(msg: str = "") -> None:
    print(msg, flush=True)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"fmi_finland_daily_baseline_through_{cutoff_year}_v{FORMAT_VERSION}.pkl.gz"


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"fmi_finland_progress_through_{cutoff_year}_v{FORMAT_VERSION}.pkl.gz"


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"fmi_finland_status_through_{cutoff_year}.json"


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


def parse_xml(raw: bytes) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        preview = raw[:3000].decode("utf-8", errors="replace")
        raise RuntimeError(f"FMI XML konnte nicht geparst werden: {exc}\n{preview}") from exc


def request_bytes(params: dict[str, Any]) -> bytes:
    query = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "storedquery_id": STORED_QUERY,
        **params,
    }
    url = WFS_URL + "?" + urllib.parse.urlencode(query, doseq=True)
    last: Exception | None = None

    for attempt in range(1, TRIES + 1):
        if REQUEST_SLEEP:
            time.sleep(REQUEST_SLEEP)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/xml,text/xml,*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                raw = response.read()
                if not raw:
                    raise RuntimeError("Leere FMI-WFS-Antwort")
                return raw
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in {408, 429, 500, 502, 503, 504} and attempt < TRIES:
                wait = min(60, 5 * attempt)
                log(f"WARNUNG FMI HTTP {exc.code}; neuer Versuch in {wait}s …")
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            last = exc
            if attempt >= TRIES:
                break
            wait = min(60, 5 * attempt)
            log(f"WARNUNG FMI {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(f"FMI-WFS-Abruf fehlgeschlagen: {last}")


def exception_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def iso_start(d: date) -> str:
    return d.isoformat() + "T00:00:00Z"


def iso_end(d: date) -> str:
    return d.isoformat() + "T23:59:59Z"


def child_text(node: ET.Element, wanted: str) -> str | None:
    for element in node.iter():
        if local(element.tag) == wanted and element.text:
            text = element.text.strip()
            if text:
                return text
    return None


def attr_local(node: ET.Element, wanted: str) -> str | None:
    wanted = wanted.lower()
    for key, value in node.attrib.items():
        if local(key).lower() == wanted:
            return str(value)
    return None


def parse_pos(text: str | None) -> tuple[float, float] | None:
    if not text:
        return None
    parts = text.replace(",", " ").split()
    if len(parts) < 2:
        return None
    try:
        a = float(parts[0]); b = float(parts[1])
    except ValueError:
        return None
    if 50 <= a <= 75 and 10 <= b <= 40:
        return (a, b)
    if 50 <= b <= 75 and 10 <= a <= 40:
        return (b, a)
    return (a, b)


def codespace_values(node: ET.Element, element_name: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for element in node.iter():
        if local(element.tag) != element_name:
            continue
        text = (element.text or "").strip()
        if not text:
            continue
        out.append((text, attr_local(element, "codeSpace") or ""))
    return out


def parse_station_points(root: ET.Element) -> tuple[dict[str, tuple[float, float]], list[tuple[float, float]]]:
    by_id: dict[str, tuple[float, float]] = {}
    ordered: list[tuple[float, float]] = []
    for node in root.iter():
        if local(node.tag) != "Point":
            continue
        pos = parse_pos(child_text(node, "pos"))
        if pos is None:
            continue
        ordered.append(pos)
        gid = attr_local(node, "id")
        if gid:
            by_id[gid] = pos
    return by_id, ordered


def parse_locations(root: ET.Element) -> list[dict[str, Any]]:
    point_by_id, points_ordered = parse_station_points(root)
    locations: list[dict[str, Any]] = []

    for node in root.iter():
        if local(node.tag) != "Location":
            continue
        identifiers = codespace_values(node, "identifier")
        names = codespace_values(node, "name")

        fmisid = next((text for text, cs in identifiers if "stationcode/fmisid" in cs.lower()), None)
        if not fmisid:
            fmisid = next((text for text, _ in identifiers if text.isdigit()), None)
        name = next((text for text, cs in names if "locationcode/name" in cs.lower()), names[0][0] if names else None)

        representative_href = None
        for element in node.iter():
            if local(element.tag) == "representativePoint":
                representative_href = attr_local(element, "href")
                break

        pos = None
        if representative_href:
            point_id = representative_href.rsplit("#", 1)[-1]
            pos = point_by_id.get(point_id)

        locations.append({
            "id": str(fmisid or "").strip(),
            "name": str(name or fmisid or "").strip(),
            "lat": pos[0] if pos else None,
            "lon": pos[1] if pos else None,
        })

    # Probe shows LocationCollection and pointMember use the same station order.
    if len(points_ordered) == len(locations):
        for loc, pos in zip(locations, points_ordered):
            if loc["lat"] is None or loc["lon"] is None:
                loc["lat"], loc["lon"] = pos
    return locations


def parse_fields(root: ET.Element) -> list[str]:
    fields = []
    for node in root.iter():
        if local(node.tag) == "field":
            name = attr_local(node, "name")
            if name:
                fields.append(name)
    return list(dict.fromkeys(fields))


def parse_positions(root: ET.Element) -> list[tuple[float, float, int]]:
    text = None
    for node in root.iter():
        if local(node.tag) in {"positions", "posList"} and node.text:
            text = " ".join(node.text.split())
            if text:
                break
    if not text:
        return []
    nums = [float(x) for x in text.split()]
    if len(nums) % 3 != 0:
        raise RuntimeError(f"FMI positions: {len(nums)} Zahlen sind nicht durch 3 teilbar.")
    return [(nums[i], nums[i+1], int(nums[i+2])) for i in range(0, len(nums), 3)]


def parse_tuple_rows(root: ET.Element, fields: list[str]) -> list[dict[str, float | None]]:
    text = None
    for node in root.iter():
        if local(node.tag) in {"doubleOrNilReasonTupleList", "tupleList"} and node.text:
            text = " ".join(node.text.split())
            if text:
                break
    if not text:
        return []
    if not fields:
        raise RuntimeError("FMI Coverage enthält keine Felddefinitionen.")
    tokens = text.split()
    width = len(fields)
    if len(tokens) % width != 0:
        raise RuntimeError(f"FMI Tuple-Liste ({len(tokens)}) passt nicht zu {width} Feldern.")
    out = []
    for i in range(0, len(tokens), width):
        row: dict[str, float | None] = {}
        for field, token in zip(fields, tokens[i:i+width]):
            if token.lower() in {"nan", "nil", "null"}:
                row[field] = None
            else:
                try:
                    value = float(token)
                except ValueError:
                    value = None
                row[field] = value if value is None or math.isfinite(value) else None
        out.append(row)
    return out


def close_coord(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= 0.0002


def parse_mpc_response(raw: bytes) -> tuple[dict[str, dict[str, Any]], list[tuple[str, date, float | None, float | None]]]:
    root = parse_xml(raw)
    locations = parse_locations(root)
    fields = parse_fields(root)
    positions = parse_positions(root)
    values = parse_tuple_rows(root, fields)

    if not positions and not values:
        return {}, []
    if PARAM_TMIN not in fields or PARAM_TMAX not in fields:
        raise RuntimeError(f"FMI Coverage-Felder unerwartet: {fields}; tmin/tmax fehlen.")
    if len(positions) != len(values):
        raise RuntimeError(f"FMI Coverage-Längenfehler: positions={len(positions)}, values={len(values)}.")
    if not locations:
        raise RuntimeError("FMI Coverage enthält Werte, aber keine Location-Metadaten.")
    if len(positions) % len(locations) != 0:
        raise RuntimeError(f"FMI Coverage nicht rechteckig: {len(positions)} Positionen / {len(locations)} Locations.")

    rows_per_station = len(positions) // len(locations)
    inventory: dict[str, dict[str, Any]] = {}
    station_days: list[tuple[str, date, float | None, float | None]] = []
    seen_station_ids: set[str] = set()

    for index, loc in enumerate(locations):
        sid = str(loc.get("id") or "").strip()
        block_start = index * rows_per_station
        block_end = block_start + rows_per_station
        pos_block = positions[block_start:block_end]
        val_block = values[block_start:block_end]

        if not sid:
            continue
        if sid in seen_station_ids:
            raise RuntimeError(f"FMI Coverage enthält FMISID {sid} mehrfach.")
        seen_station_ids.add(sid)

        first_lat = pos_block[0][0] if pos_block else None
        first_lon = pos_block[0][1] if pos_block else None
        for lat, lon, _ in pos_block:
            if first_lat is not None and (abs(lat-first_lat) > 0.0002 or abs(lon-first_lon) > 0.0002):
                raise RuntimeError(f"FMI Stationsblock {sid} wechselt Koordinate.")

        loc_lat = loc.get("lat"); loc_lon = loc.get("lon")
        if loc_lat is not None and loc_lon is not None and first_lat is not None:
            if not (close_coord(float(loc_lat), float(first_lat)) and close_coord(float(loc_lon), float(first_lon))):
                raise RuntimeError(
                    f"FMI Location/positions-Reihenfolge stimmt nicht: {sid} "
                    f"metadata=({loc_lat},{loc_lon}) coverage=({first_lat},{first_lon})."
                )

        lat = float(loc_lat) if loc_lat is not None else first_lat
        lon = float(loc_lon) if loc_lon is not None else first_lon
        inventory[sid] = {
            "id": sid,
            "name": str(loc.get("name") or sid).strip(),
            "country": COUNTRY,
            "country_code": COUNTRY_CODE,
            "lat": lat,
            "lon": lon,
            "elevation_m": None,
            "network": "FMI surface weather observations",
            "source": SOURCE,
        }

        for (_, _, epoch), value_row in zip(pos_block, val_block):
            try:
                d = datetime.fromtimestamp(epoch, tz=timezone.utc).date()
            except (OverflowError, OSError, ValueError):
                continue
            station_days.append((sid, d, value_row.get(PARAM_TMIN), value_row.get(PARAM_TMAX)))

    return inventory, station_days


def better_max(old: list[Any] | None, value: float) -> bool:
    return old is None or float(value) > float(old[0])


def better_min(old: list[Any] | None, value: float) -> bool:
    return old is None or float(value) < float(old[0])


def empty_record() -> dict[str, Any]:
    return {
        "first_date": None,
        "last_date": None,
        "observation_days": 0,
        "tmax_abs": None,
        "tmin_abs": None,
        "calendar_tmax": {},
        "calendar_tmin": {},
        "provenance_days": {"FMI_WFS_DAILY": 0},
    }


def historical_limits(cutoff_year: int) -> tuple[float, float]:
    if cutoff_year <= OFFICIAL_RECORD_REFERENCE_YEAR:
        return OFFICIAL_TMAX_RECORD_C, OFFICIAL_TMIN_RECORD_C
    return EMERGENCY_TMAX_CEILING_C, EMERGENCY_TMIN_FLOOR_C


def qc_day(tmin: float | None, tmax: float | None, *, cutoff_year: int, stats: dict[str, Any]) -> tuple[float | None, float | None]:
    max_limit, min_limit = historical_limits(cutoff_year)
    if tmin is not None and tmax is not None and tmin > tmax:
        stats["qc_rejected_inconsistent_days"] += 1
        return None, None
    if tmax is not None and tmax > max_limit:
        stats["qc_rejected_tmax"] += 1
        tmax = None
    if tmin is not None and tmin < min_limit:
        stats["qc_rejected_tmin"] += 1
        tmin = None
    return tmin, tmax


def consume_day(rec: dict[str, Any], d: date, tmin: float | None, tmax: float | None) -> bool:
    if tmin is None and tmax is None:
        return False
    iso = d.isoformat(); mmdd = d.strftime("%m-%d")
    if rec["first_date"] is None or iso < rec["first_date"]:
        rec["first_date"] = iso
    if rec["last_date"] is None or iso > rec["last_date"]:
        rec["last_date"] = iso
    rec["observation_days"] += 1
    rec["provenance_days"]["FMI_WFS_DAILY"] += 1
    if tmax is not None:
        if better_max(rec["tmax_abs"], tmax): rec["tmax_abs"] = [float(tmax), iso]
        old = rec["calendar_tmax"].get(mmdd)
        if better_max(old, tmax): rec["calendar_tmax"][mmdd] = [float(tmax), iso]
    if tmin is not None:
        if better_min(rec["tmin_abs"], tmin): rec["tmin_abs"] = [float(tmin), iso]
        old = rec["calendar_tmin"].get(mmdd)
        if better_min(old, tmin): rec["calendar_tmin"][mmdd] = [float(tmin), iso]
    return True


def update_span(progress: dict[str, Any], d: date) -> None:
    iso = d.isoformat()
    if progress["first_date"] is None or iso < progress["first_date"]: progress["first_date"] = iso
    if progress["last_date"] is None or iso > progress["last_date"]: progress["last_date"] = iso


def last_day_of_month(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def historical_blocks(cutoff_year: int) -> list[tuple[date, date]]:
    end = date(cutoff_year, 12, 31)
    blocks: list[tuple[date, date]] = []
    for year in range(START_DATE.year, cutoff_year + 1):
        if year < 1850:
            for month in range(1, 13):
                a = date(year, month, 1); b = last_day_of_month(year, month)
                if a <= end: blocks.append((a, min(b, end)))
        else:
            for first_month in (1, 4, 7, 10):
                a = date(year, first_month, 1)
                b = last_day_of_month(year, first_month + 2)
                if a <= end: blocks.append((a, min(b, end)))
    return blocks


def current_blocks(year: int, through: date) -> list[tuple[date, date]]:
    blocks = []
    for first_month in (1, 4, 7, 10):
        a = date(year, first_month, 1)
        if a > through: break
        b = min(last_day_of_month(year, first_month + 2), through)
        blocks.append((a, b))
    return blocks


def split_monthly(start: date, end: date) -> list[tuple[date, date]]:
    out = []; cur = date(start.year, start.month, 1)
    while cur <= end:
        b = min(end, last_day_of_month(cur.year, cur.month))
        out.append((max(start, cur), b))
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
    return out


def fetch_period(start: date, end: date, *, allow_empty_400: bool = False) -> list[bytes]:
    params = {
        "starttime": iso_start(start),
        "endtime": iso_end(end),
        "parameters": f"{PARAM_TMIN},{PARAM_TMAX}",
        "timestep": 1440,
        "bbox": FINLAND_BBOX,
    }
    try:
        return [request_bytes(params)]
    except urllib.error.HTTPError as exc:
        body = exception_body(exc); span_days = (end-start).days + 1
        if span_days > 35:
            log(f"WARNUNG FMI {start} bis {end}: HTTP {exc.code}; teile Block monatsweise.")
            raws: list[bytes] = []
            for a, b in split_monthly(start, end):
                raws.extend(fetch_period(a, b, allow_empty_400=allow_empty_400))
            return raws
        if exc.code == 400 and allow_empty_400:
            compact = " ".join(body.split())
            log(f"FMI {start} bis {end}: HTTP 400 im frühen Explorationsbereich; als leer/unverfügbar markiert. {compact[:240]}")
            return []
        raise RuntimeError(f"FMI HTTP {exc.code} für {start} bis {end}: {' '.join(body.split())[:1200]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
        span_days = (end-start).days + 1
        if span_days > 35:
            log(f"WARNUNG FMI {start} bis {end}: {exc}; teile Block monatsweise.")
            raws: list[bytes] = []
            for a, b in split_monthly(start, end):
                raws.extend(fetch_period(a, b, allow_empty_400=allow_empty_400))
            return raws
        raise


def block_id(start: date, end: date) -> str:
    return f"{start.isoformat()}_{end.isoformat()}"


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
        "processed_blocks": [],
        "rows_with_temperature": 0,
        "first_date": None,
        "last_date": None,
        "qc_rejected_tmax": 0,
        "qc_rejected_tmin": 0,
        "qc_rejected_inconsistent_days": 0,
    }


def valid_final(path: Path, cutoff_year: int) -> bool:
    if not path.exists(): return False
    try: obj = load_pickle_gzip(path)
    except Exception: return False
    return isinstance(obj, dict) and obj.get("format_version") == FORMAT_VERSION and obj.get("cutoff_year") == cutoff_year and obj.get("complete") is True and len(obj.get("records", {})) > 0


def write_status(cache_dir: Path, cutoff_year: int, payload: dict[str, Any]) -> None:
    status = {
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
        "processed_blocks": len(payload.get("processed_blocks", [])),
        "qc_rejected_tmax": int(payload.get("qc_rejected_tmax", 0)),
        "qc_rejected_tmin": int(payload.get("qc_rejected_tmin", 0)),
        "qc_rejected_inconsistent_days": int(payload.get("qc_rejected_inconsistent_days", 0)),
        "baseline_file": str(baseline_path(cache_dir, cutoff_year)),
    }
    atomic_json(status_path(cache_dir, cutoff_year), status)


def process_raw_into_progress(raw: bytes, progress: dict[str, Any], *, cutoff_year: int) -> int:
    inventory_delta, rows = parse_mpc_response(raw)
    for sid, meta in inventory_delta.items():
        old = progress["inventory"].get(sid)
        if not isinstance(old, dict):
            progress["inventory"][sid] = meta
        else:
            for key in ("name", "lat", "lon", "network", "source"):
                value = meta.get(key)
                if value not in (None, ""): old[key] = value

    accepted = 0
    for sid, d, tmin, tmax in rows:
        if d.year > cutoff_year: continue
        tmin, tmax = qc_day(tmin, tmax, cutoff_year=cutoff_year, stats=progress)
        if tmin is None and tmax is None: continue
        rec = progress["records"].setdefault(sid, empty_record())
        if consume_day(rec, d, tmin, tmax):
            accepted += 1; update_span(progress, d)
    return accepted


def build_baseline(cache_dir: Path, cutoff_year: int, *, force: bool = False, max_runtime_minutes: float = 155.0) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    final = baseline_path(cache_dir, cutoff_year); prog_file = progress_path(cache_dir, cutoff_year)
    if force:
        final.unlink(missing_ok=True); prog_file.unlink(missing_ok=True); status_path(cache_dir, cutoff_year).unlink(missing_ok=True)
    if not force and valid_final(final, cutoff_year):
        log(f"Verwende vorhandenen FMI-Finnland-Baselinecache: {final}"); return final

    if not force and prog_file.exists():
        try:
            progress = load_pickle_gzip(prog_file)
            if progress.get("format_version") != FORMAT_VERSION or progress.get("cutoff_year") != cutoff_year:
                progress = initial_progress(cutoff_year)
        except Exception:
            progress = initial_progress(cutoff_year)
    else:
        progress = initial_progress(cutoff_year)

    blocks = historical_blocks(cutoff_year); done = set(progress["processed_blocks"]); started = time.monotonic()
    max_limit, min_limit = historical_limits(cutoff_year)

    log("=== FMI FINNLAND HISTORISCHE BASELINE ===")
    log(f"Daily multipointcoverage | tmin/tmax | {START_DATE} bis {cutoff_year}-12-31")
    log(f"Finnland-BBOX: {FINLAND_BBOX}")
    log(f"QC: TMAX <= {max_limit:.1f} C | TMIN >= {min_limit:.1f} C | TMIN <= TMAX")
    log(f"Blöcke insgesamt: {len(blocks)} | bereits verarbeitet: {len(done)}")

    for index, (start, end) in enumerate(blocks, start=1):
        bid = block_id(start, end)
        if bid in done: continue
        raws = fetch_period(start, end, allow_empty_400=end < date(1850,1,1))
        accepted = sum(process_raw_into_progress(raw, progress, cutoff_year=cutoff_year) for raw in raws)
        progress["processed_blocks"].append(bid); done.add(bid)
        progress["rows_with_temperature"] = sum(int(rec.get("observation_days",0)) for rec in progress["records"].values())
        atomic_pickle_gzip(prog_file, progress)

        if index % 10 == 0 or index == len(blocks) or (accepted > 0 and index % 4 == 0):
            log(f"FMI: {index}/{len(blocks)} Blöcke | {len(progress['records'])} Stationsreihen | {progress['rows_with_temperature']:,} Stationstage | Zeitraum {progress['first_date']} bis {progress['last_date']}")
        if (time.monotonic()-started)/60 >= max_runtime_minutes:
            log("Laufzeitgrenze erreicht. FMI-Zwischenstand gespeichert; Workflow mit force=false erneut starten.")
            return prog_file

    if not progress["records"]: raise RuntimeError("FMI-Finnland-Baseline enthält keine Stationsreihen.")
    progress["complete"] = True
    payload = {
        **progress,
        "parameters": {"TMIN": PARAM_TMIN, "TMAX": PARAM_TMAX},
        "stored_query": STORED_QUERY,
        "bbox": FINLAND_BBOX,
        "public_url": PUBLIC_URL,
        "record_reference_url": "https://en.ilmatieteenlaitos.fi/weather-records",
        "quality_note": "Official FMI daily station Tmin/Tmax from WFS multipointcoverage. Historical plausibility QC uses published Finnish measured temperature records through 2025 and rejects Tmin>Tmax days.",
    }
    atomic_pickle_gzip(final, payload); write_status(cache_dir, cutoff_year, payload); prog_file.unlink(missing_ok=True)

    log(); log("=== FMI FINLAND BASELINE SUMMARY ===")
    log(f"Stationsreihen: {len(payload['records'])}")
    log(f"Inventar: {len(payload['inventory'])} FMISIDs")
    log(f"Stationstage: {payload['rows_with_temperature']:,}")
    log(f"Datenzeitraum: {payload['first_date']} bis {payload['last_date']}")
    log(f"Historische QC verworfen: TMAX>{max_limit:.1f} C = {payload['qc_rejected_tmax']:,} | TMIN<{min_limit:.1f} C = {payload['qc_rejected_tmin']:,} | TMIN>TMAX = {payload['qc_rejected_inconsistent_days']:,}")
    log(f"Verarbeitete Zeitblöcke: {len(payload['processed_blocks'])}")
    log(f"Output: {final}")
    log("FMI Finland Baseline OK.")
    return final


def load_baseline(cache_dir: Path, cutoff_year: int) -> dict[str, Any]:
    path = baseline_path(cache_dir, cutoff_year)
    if not valid_final(path, cutoff_year): raise RuntimeError(f"FMI-Finnland-Baseline fehlt/unvollständig: {path}")
    obj = load_pickle_gzip(path); assert isinstance(obj, dict); return obj


def self_test() -> None:
    xml = b'''<?xml version="1.0"?>
<root xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:swe="http://www.opengis.net/swe/2.0" xmlns:xlink="http://www.w3.org/1999/xlink">
 <Location><gml:identifier codeSpace="http://xml.fmi.fi/namespace/stationcode/fmisid">100001</gml:identifier><gml:name codeSpace="http://xml.fmi.fi/namespace/locationcode/name">Test One</gml:name><representativePoint xlink:href="#p1"/></Location>
 <Location><gml:identifier codeSpace="http://xml.fmi.fi/namespace/stationcode/fmisid">100002</gml:identifier><gml:name codeSpace="http://xml.fmi.fi/namespace/locationcode/name">Test Two</gml:name><representativePoint xlink:href="#p2"/></Location>
 <gml:pointMember><gml:Point gml:id="p1"><gml:pos>60.0 24.0</gml:pos></gml:Point></gml:pointMember>
 <gml:pointMember><gml:Point gml:id="p2"><gml:pos>61.0 25.0</gml:pos></gml:Point></gml:pointMember>
 <swe:DataRecord><swe:field name="tmin"/><swe:field name="tmax"/></swe:DataRecord>
 <positions>60.0 24.0 1767225600 60.0 24.0 1767312000 61.0 25.0 1767225600 61.0 25.0 1767312000</positions>
 <swe:doubleOrNilReasonTupleList>-5.0 1.0 -4.0 2.0 -10.0 -2.0 NaN 0.0</swe:doubleOrNilReasonTupleList>
</root>'''
    inv, rows = parse_mpc_response(xml)
    assert list(inv) == ["100001","100002"] and len(rows) == 4
    assert inv["100001"]["lat"] == 60.0 and inv["100002"]["lon"] == 25.0
    assert rows[0][2:] == (-5.0,1.0) and rows[3][2:] == (None,0.0)

    stats = {"qc_rejected_tmax":0,"qc_rejected_tmin":0,"qc_rejected_inconsistent_days":0}
    tn,tx=qc_day(-10.0,38.0,cutoff_year=2025,stats=stats); assert tn == -10.0 and tx is None
    tn,tx=qc_day(-52.0,-20.0,cutoff_year=2025,stats=stats); assert tn is None and tx == -20.0
    tn,tx=qc_day(5.0,4.0,cutoff_year=2025,stats=stats); assert tn is None and tx is None
    assert stats == {"qc_rejected_tmax":1,"qc_rejected_tmin":1,"qc_rejected_inconsistent_days":1}

    rec=empty_record(); consume_day(rec,date(2025,1,1),-5.0,2.0); consume_day(rec,date(2025,1,2),-6.0,3.0)
    assert rec["tmax_abs"] == [3.0,"2025-01-02"] and rec["tmin_abs"] == [-6.0,"2025-01-02"] and rec["observation_days"] == 2
    print("FMI Finland historical cache self-test OK")


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--self-test",action="store_true"); parser.add_argument("--cache-dir",default=str(CACHE_DIR_DEFAULT)); parser.add_argument("--cutoff-year",type=int,default=date.today().year-1); parser.add_argument("--force",action="store_true"); parser.add_argument("--max-runtime-minutes",type=float,default=155.0); args=parser.parse_args()
    if args.self_test: self_test(); return 0
    build_baseline(Path(args.cache_dir),args.cutoff_year,force=args.force,max_runtime_minutes=args.max_runtime_minutes); return 0

if __name__ == "__main__":
    raise SystemExit(main())
