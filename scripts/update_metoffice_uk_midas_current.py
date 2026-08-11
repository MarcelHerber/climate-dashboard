#!/usr/bin/env python3
"""Build the provisional/current 2026 UK temperature cache.

Historical authority:
    Met Office MIDAS Open through 2025.

Current-year bridge:
    NOAA/NCEI GHCN-Daily for UK stations (country prefix "UK").

Why a bridge?
    The freely accessible Met Office Weather DataHub Land Observations feed
    only exposes the most recent 48 hours. It therefore cannot retrospectively
    reconstruct January-to-date 2026. The restricted ongoing MIDAS archive is
    intentionally not used.

This script:
  * selects all UK GHCN-Daily stations whose TMAX and/or TMIN inventory reaches
    2026,
  * downloads their by_station files,
  * keeps only 2026 TMAX/TMIN with blank NOAA QFLAG,
  * crosswalks current GHCN stations to the completed Met Office MIDAS
    historical cache using WMO ID first and otherwise a strict
    coordinate/name match,
  * writes a separate provisional 2026 cache.

GHCN MFLAG="H" values (highest/lowest hourly temperature) are retained but
explicitly counted and marked as provisional provenance. Such values are
conservative for extremes and must not be confused with final MIDAS daily
temperature observations.
"""
from __future__ import annotations

import argparse
import csv
import difflib
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
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import update_metoffice_uk_midas_station_cache as hist

YEAR = 2026
FORMAT_VERSION = 2
COUNTRY = "United Kingdom"
COUNTRY_CODE = "UK"
SOURCE = "NOAA/NCEI GHCN-Daily (2026 bridge)"
HISTORICAL_SOURCE = "Met Office MIDAS Open through 2025"

BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
STATIONS_URL = f"{BASE_URL}/ghcnd-stations.txt"
INVENTORY_URL = f"{BASE_URL}/ghcnd-inventory.txt"
VERSION_URL = f"{BASE_URL}/ghcnd-version.txt"
BY_STATION_ROOT = f"{BASE_URL}/by_station"

CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
UA = "climate-dashboard-uk-ghcn-current-bridge/2.0 (+GitHub Actions)"

HTTP_TIMEOUT = 90
TRIES = 4


def log(msg: str = "") -> None:
    print(msg, flush=True)


def historical_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "metoffice_uk_midas_daily_baseline_through_2025_v1.pkl.gz"


def current_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "metoffice_uk_ghcn_bridge_current_2026_v2.pkl.gz"


def current_status_path(cache_dir: Path) -> Path:
    return cache_dir / "metoffice_uk_ghcn_bridge_current_2026_status.json"


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


def request_bytes(url: str, attempts: int = TRIES) -> bytes:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                raw = response.read()
                if not raw:
                    raise RuntimeError("leere HTTP-Antwort")
                return raw
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                raise
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            last = exc

        if attempt < attempts:
            time.sleep(min(20, attempt * 2))

    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last}")


def request_text(url: str) -> str:
    raw = request_bytes(url)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def parse_ghcn_stations(text: str) -> dict[str, dict[str, Any]]:
    """Parse fixed-width ghcnd-stations.txt."""
    out: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        if len(line) < 42:
            continue
        sid = line[0:11].strip()
        if not sid.startswith("UK"):
            continue
        try:
            lat = float(line[12:20])
            lon = float(line[21:30])
        except ValueError:
            continue

        elev_text = line[31:37].strip()
        try:
            elev = float(elev_text)
        except ValueError:
            elev = None

        out[sid] = {
            "ghcn_id": sid,
            "lat": lat,
            "lon": lon,
            "elevation_m": elev,
            "name": line[41:71].strip(),
            "wmo_id": line[80:85].strip() if len(line) >= 85 else "",
        }
    return out


def parse_ghcn_inventory(text: str) -> dict[str, dict[str, tuple[int, int]]]:
    """Parse fixed-width ghcnd-inventory.txt for UK TMAX/TMIN."""
    out: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)

    for line in text.splitlines():
        if len(line) < 45:
            continue
        sid = line[0:11].strip()
        if not sid.startswith("UK"):
            continue

        element = line[31:35].strip()
        if element not in {"TMAX", "TMIN"}:
            continue

        try:
            first = int(line[36:40])
            last = int(line[41:45])
        except ValueError:
            continue

        out[sid][element] = (first, last)

    return dict(out)


def active_2026_stations(
    stations: dict[str, dict[str, Any]],
    inventory: dict[str, dict[str, tuple[int, int]]],
) -> list[dict[str, Any]]:
    selected = []

    for sid, elements in inventory.items():
        if sid not in stations:
            continue

        has_tmax = (
            "TMAX" in elements
            and elements["TMAX"][0] <= YEAR <= elements["TMAX"][1]
        )
        has_tmin = (
            "TMIN" in elements
            and elements["TMIN"][0] <= YEAR <= elements["TMIN"][1]
        )
        if not has_tmax and not has_tmin:
            continue

        obj = dict(stations[sid])
        obj["has_tmax_2026_inventory"] = has_tmax
        obj["has_tmin_2026_inventory"] = has_tmin
        obj["inventory"] = elements
        selected.append(obj)

    selected.sort(key=lambda x: x["ghcn_id"])
    return selected


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"\b(AIRPORT|AP|WEATHER CENTRE|WEATHER CENTER)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(text.split())


def name_similarity(a: str, b: str) -> float:
    aa = normalize_name(a)
    bb = normalize_name(b)
    if not aa or not bb:
        return 0.0
    return difflib.SequenceMatcher(None, aa, bb).ratio()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def first_number(obj: Any, key_needles: tuple[str, ...]) -> float | None:
    if not isinstance(obj, dict):
        return None

    # Prefer exact-looking fields.
    for key, value in obj.items():
        nk = hist.normalize_ref(key)
        if not any(needle in nk for needle in key_needles):
            continue
        try:
            x = float(str(value).strip())
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):
            return x
    return None


def extract_wmo_values(obj: Any) -> set[str]:
    found: set[str] = set()

    def visit(x: Any, parent_key: str = "") -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                nk = hist.normalize_ref(k)
                if "wmo" in nk:
                    for token in re.findall(r"\d{4,5}", str(v)):
                        found.add(token.zfill(5))
                visit(v, nk)
        elif isinstance(x, (list, tuple)):
            for v in x:
                visit(v, parent_key)

    visit(obj)
    return found


def build_midas_metadata(
    baseline: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    candidates: list[dict[str, Any]] = []
    wmo_to_keys: dict[str, list[str]] = defaultdict(list)

    for key, meta in baseline.get("station_details", {}).items():
        if not isinstance(meta, dict):
            continue

        dataset_meta = meta.get("dataset_metadata", {})
        lat = first_number(
            dataset_meta,
            ("latitude", "station_lat", "src_lat", "lat"),
        )
        lon = first_number(
            dataset_meta,
            ("longitude", "station_lon", "src_lon", "long", "lon"),
        )

        # Guard against accidentally treating unrelated numeric fields as coords.
        if lat is not None and not (49.0 <= lat <= 61.5):
            lat = None
        if lon is not None and not (-9.5 <= lon <= 2.5):
            lon = None

        name = str(meta.get("name") or key)
        wmos = extract_wmo_values(meta)

        candidate = {
            "key": key,
            "name": name,
            "lat": lat,
            "lon": lon,
            "wmo_ids": sorted(wmos),
            "meta": meta,
        }
        candidates.append(candidate)

        for wmo in wmos:
            wmo_to_keys[wmo].append(key)

    return candidates, dict(wmo_to_keys)


def crosswalk_one(
    ghcn: dict[str, Any],
    midas_candidates: list[dict[str, Any]],
    midas_by_key: dict[str, dict[str, Any]],
    wmo_to_keys: dict[str, list[str]],
) -> dict[str, Any]:
    """Strict GHCN -> MIDAS crosswalk.

    Priority:
      1. unique WMO ID
      2. very close coordinate match
      3. close coordinate + good station-name similarity
    """
    wmo = str(ghcn.get("wmo_id", "")).strip()
    if wmo:
        wmo = wmo.zfill(5)
        keys = wmo_to_keys.get(wmo, [])
        if len(keys) == 1:
            key = keys[0]
            target = midas_by_key[key]
            distance = None
            if target["lat"] is not None and target["lon"] is not None:
                distance = haversine_km(
                    ghcn["lat"], ghcn["lon"], target["lat"], target["lon"]
                )
            return {
                "matched": True,
                "midas_key": key,
                "method": "WMO",
                "distance_km": distance,
                "name_similarity": name_similarity(
                    ghcn["name"], target["name"]
                ),
            }

    distances = []
    for candidate in midas_candidates:
        if candidate["lat"] is None or candidate["lon"] is None:
            continue
        dist = haversine_km(
            ghcn["lat"],
            ghcn["lon"],
            candidate["lat"],
            candidate["lon"],
        )
        sim = name_similarity(ghcn["name"], candidate["name"])
        distances.append((dist, -sim, candidate))

    if not distances:
        return {
            "matched": False,
            "midas_key": None,
            "method": "NO_MIDAS_COORDINATES",
            "distance_km": None,
            "name_similarity": None,
        }

    distances.sort(key=lambda x: (x[0], x[1]))
    best_dist, neg_sim, best = distances[0]
    best_sim = -neg_sim
    second_dist = distances[1][0] if len(distances) > 1 else float("inf")

    # Rule A: almost identical coordinates and no near-tie.
    if best_dist <= 0.75 and second_dist - best_dist >= 0.15:
        return {
            "matched": True,
            "midas_key": best["key"],
            "method": "COORD_STRICT",
            "distance_km": round(best_dist, 3),
            "name_similarity": round(best_sim, 3),
        }

    # Rule B: same local site plus reasonably similar name.
    if best_dist <= 3.0 and best_sim >= 0.55:
        return {
            "matched": True,
            "midas_key": best["key"],
            "method": "COORD_NAME",
            "distance_km": round(best_dist, 3),
            "name_similarity": round(best_sim, 3),
        }

    # Rule C: renamed/variant site but exceptionally similar station name.
    if best_dist <= 7.0 and best_sim >= 0.82:
        return {
            "matched": True,
            "midas_key": best["key"],
            "method": "NAME_COORD",
            "distance_km": round(best_dist, 3),
            "name_similarity": round(best_sim, 3),
        }

    return {
        "matched": False,
        "midas_key": None,
        "method": "UNMATCHED",
        "distance_km": round(best_dist, 3),
        "name_similarity": round(best_sim, 3),
        "nearest_midas_key": best["key"],
        "nearest_midas_name": best["name"],
    }


def download_by_station(station_id: str) -> bytes:
    errors = []
    for suffix in (".csv.gz", ".csv"):
        url = f"{BY_STATION_ROOT}/{station_id}{suffix}"
        try:
            return request_bytes(url)
        except urllib.error.HTTPError as exc:
            errors.append(f"{url}: HTTP {exc.code}")
            if exc.code != 404:
                raise
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("; ".join(errors))


def parse_by_station(
    raw: bytes,
    station_id: str,
) -> tuple[dict[date, dict[str, Any]], Counter, Counter, Counter]:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8", errors="replace")

    rows = csv.reader(io.StringIO(text))
    daily: dict[date, dict[str, Any]] = {}
    stats = Counter()
    mflags = Counter()
    sflags = Counter()

    for row in rows:
        if not row:
            continue

        # Optional header tolerance.
        if row[0].strip().upper() == "ID":
            continue
        if len(row) < 7:
            stats["short_rows"] += 1
            continue

        sid = row[0].strip()
        if sid != station_id:
            continue

        datestr = row[1].strip()
        element = row[2].strip()
        if element not in {"TMAX", "TMIN"}:
            continue
        if not datestr.startswith(str(YEAR)):
            continue

        try:
            d = datetime.strptime(datestr, "%Y%m%d").date()
            raw_value = int(row[3].strip())
        except (ValueError, IndexError):
            stats["bad_value_or_date"] += 1
            continue

        if raw_value == -9999:
            stats["missing_values"] += 1
            continue

        mflag = row[4].strip() if len(row) > 4 else ""
        qflag = row[5].strip() if len(row) > 5 else ""
        sflag = row[6].strip() if len(row) > 6 else ""
        obstime = row[7].strip() if len(row) > 7 else ""

        mflags[mflag or "<leer>"] += 1
        sflags[sflag or "<leer>"] += 1

        if qflag:
            stats[f"rejected_qflag_{qflag}"] += 1
            continue

        value = raw_value / 10.0
        if element == "TMAX" and not hist.plausible_tmax(value):
            stats["rejected_tmax_plausibility"] += 1
            continue
        if element == "TMIN" and not hist.plausible_tmin(value):
            stats["rejected_tmin_plausibility"] += 1
            continue

        slot = daily.setdefault(
            d,
            {
                "tmax": None,
                "tmin": None,
                "tmax_mflag": "",
                "tmin_mflag": "",
                "tmax_sflag": "",
                "tmin_sflag": "",
                "tmax_obstime": "",
                "tmin_obstime": "",
            },
        )

        key = element.lower()
        if slot[key] is not None:
            stats[f"duplicate_{element.lower()}"] += 1

        slot[key] = value
        slot[f"{key}_mflag"] = mflag
        slot[f"{key}_sflag"] = sflag
        slot[f"{key}_obstime"] = obstime
        stats[f"accepted_{element.lower()}"] += 1

    return daily, stats, mflags, sflags


def build_current(cache_dir: Path) -> Path:
    baseline_file = historical_cache_path(cache_dir)
    if not baseline_file.exists():
        raise RuntimeError(
            "Historischer UK-MIDAS-Cache fehlt. Erst den historischen "
            "UK-Workflow bis 2025 vollständig abschließen."
        )

    baseline = load_pickle_gzip(baseline_file)
    if not isinstance(baseline, dict) or baseline.get("complete") is not True:
        raise RuntimeError(
            "Historischer UK-MIDAS-Cache ist noch nicht vollständig."
        )

    log("=== UK CURRENT 2026 · GHCN-BRÜCKE ===")
    log("Historie: Met Office MIDAS Open bis 2025")
    log("Current 2026: NOAA/NCEI GHCN-Daily")
    log("NOAA QFLAG: nur leer/ungeflaggt akzeptiert")
    log()

    station_text = request_text(STATIONS_URL)
    inventory_text = request_text(INVENTORY_URL)
    try:
        ghcn_version = request_text(VERSION_URL).strip()
    except Exception:
        ghcn_version = "unbekannt"

    stations = parse_ghcn_stations(station_text)
    inventory = parse_ghcn_inventory(inventory_text)
    active = active_2026_stations(stations, inventory)

    both = sum(
        1
        for x in active
        if x["has_tmax_2026_inventory"] and x["has_tmin_2026_inventory"]
    )
    tmax_any = sum(1 for x in active if x["has_tmax_2026_inventory"])
    tmin_any = sum(1 for x in active if x["has_tmin_2026_inventory"])

    log(f"UK GHCN-Stationen im Stationsfile: {len(stations):,}")
    log(f"Mit TMAX und/oder TMIN bis 2026: {len(active):,}")
    log(f"  TMAX bis 2026: {tmax_any:,}")
    log(f"  TMIN bis 2026: {tmin_any:,}")
    log(f"  beide Elemente: {both:,}")
    log()

    midas_candidates, wmo_to_keys = build_midas_metadata(baseline)
    midas_by_key = {x["key"]: x for x in midas_candidates}

    log(f"MIDAS-Stationen für Crosswalk: {len(midas_candidates):,}")
    log(
        "MIDAS-Stationen mit Koordinaten: "
        f"{sum(x['lat'] is not None and x['lon'] is not None for x in midas_candidates):,}"
    )
    log(f"Eindeutige MIDAS-WMO-IDs: {sum(len(v) == 1 for v in wmo_to_keys.values()):,}")
    log()

    records: dict[str, dict[str, Any]] = {}
    station_details: dict[str, dict[str, Any]] = {}
    crosswalk_rows: list[dict[str, Any]] = []

    global_stats = Counter()
    global_mflags = Counter()
    global_sflags = Counter()

    successful_files = 0
    failed_files: dict[str, str] = {}

    for idx, ghcn in enumerate(active, 1):
        sid = ghcn["ghcn_id"]

        try:
            raw = download_by_station(sid)
            daily, stats, mflags, sflags = parse_by_station(raw, sid)
            successful_files += 1
        except Exception as exc:
            failed_files[sid] = str(exc)
            continue

        global_stats.update(stats)
        global_mflags.update(mflags)
        global_sflags.update(sflags)

        # Inventory may already say 2026 while no 2026 row has reached the
        # by_station file yet.
        if not daily:
            global_stats["stations_without_2026_values"] += 1
            continue

        cw = crosswalk_one(
            ghcn,
            midas_candidates,
            midas_by_key,
            wmo_to_keys,
        )

        if cw["matched"]:
            out_key = cw["midas_key"]
        else:
            out_key = f"ghcn_{sid}"

        rec = hist.empty_record()

        for d in sorted(daily):
            vals = daily[d]
            tmax = vals.get("tmax")
            tmin = vals.get("tmin")
            provenance = ["GHCN_2026_BRIDGE"]

            if vals.get("tmax_mflag") == "H":
                provenance.append("TMAX_HOURLY_EXTREME_MFLAG_H")
            if vals.get("tmin_mflag") == "H":
                provenance.append("TMIN_HOURLY_EXTREME_MFLAG_H")

            hist.consume_day(
                rec,
                d,
                tmin,
                tmax,
                provenance,
            )

        if rec.get("tmax_abs") is None and rec.get("tmin_abs") is None:
            continue

        # If two GHCN identifiers map to one MIDAS station, do not silently
        # merge them. Keep the second identifier separate and flag the conflict.
        if out_key in records:
            conflict_key = f"ghcn_{sid}"
            cw = dict(cw)
            cw["collision_with_existing_output_key"] = out_key
            cw["matched"] = False
            cw["method"] = "CROSSWALK_COLLISION"
            out_key = conflict_key
            global_stats["crosswalk_collisions"] += 1

        records[out_key] = rec

        if cw["matched"]:
            base_meta = dict(
                baseline.get("station_details", {}).get(cw["midas_key"], {})
            )
        else:
            base_meta = {}

        detail = {
            **base_meta,
            "current_source": SOURCE,
            "ghcn_id": sid,
            "ghcn_name": ghcn["name"],
            "ghcn_lat": ghcn["lat"],
            "ghcn_lon": ghcn["lon"],
            "ghcn_elevation_m": ghcn["elevation_m"],
            "ghcn_wmo_id": ghcn["wmo_id"],
            "ghcn_inventory": ghcn["inventory"],
            "crosswalk": cw,
            "current_only_2026": not cw["matched"],
        }
        station_details[out_key] = detail

        crosswalk_rows.append(
            {
                "ghcn_id": sid,
                "ghcn_name": ghcn["name"],
                "output_key": out_key,
                **cw,
            }
        )

        if idx % 10 == 0 or idx == len(active):
            log(
                f"Fortschritt: {idx}/{len(active)} GHCN-Stationen | "
                f"2026-Reihen {len(records)} | Downloads Fehler {len(failed_files)}"
            )

    if failed_files:
        sample = "; ".join(
            f"{k}: {v[:120]}" for k, v in list(failed_files.items())[:8]
        )
        raise RuntimeError(
            f"{len(failed_files)} aktive UK-GHCN-Stationsdateien konnten "
            f"nicht geladen werden. Kein unvollständiger Current-Cache wird "
            f"veröffentlicht. Beispiele: {sample}"
        )

    if not records:
        raise RuntimeError("Keine gültigen UK-2026-TMAX/TMIN-Daten gefunden.")

    first_dates = [
        rec["first_date"] for rec in records.values() if rec.get("first_date")
    ]
    last_dates = [
        rec["last_date"] for rec in records.values() if rec.get("last_date")
    ]

    first_date = min(first_dates) if first_dates else None
    last_date = max(last_dates) if last_dates else None

    matched = sum(1 for x in crosswalk_rows if x.get("matched"))
    unmatched = len(crosswalk_rows) - matched

    payload = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "historical_source": HISTORICAL_SOURCE,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "year": YEAR,
        "complete": True,
        "partial_year": True,
        "provisional_bridge": True,
        "ghcn_version": ghcn_version,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "records": records,
        "station_details": station_details,
        "crosswalk": crosswalk_rows,
        "station_count": len(records),
        "matched_historical_station_count": matched,
        "unmatched_current_station_count": unmatched,
        "first_date": first_date,
        "last_date": last_date,
        "observation_days": sum(
            int(rec.get("observation_days", 0)) for rec in records.values()
        ),
        "tmax_days": sum(
            int(rec.get("tmax_days", 0)) for rec in records.values()
        ),
        "tmin_days": sum(
            int(rec.get("tmin_days", 0)) for rec in records.values()
        ),
        "stats": dict(global_stats),
        "mflag_counts": dict(global_mflags),
        "sflag_counts": dict(global_sflags),
        "quality_note": (
            "2026 is a provisional GHCN-Daily bridge because the free Met "
            "Office Land Observations API only provides the most recent 48 "
            "hours, while the ongoing retrospective MIDAS archive is restricted. "
            "Only GHCN TMAX/TMIN with blank QFLAG are accepted. MFLAG H values "
            "are retained and explicitly marked as hourly-extreme-derived; "
            "NOAA documents H as highest/lowest hourly temperature. Historical "
            "records through 2025 remain Met Office MIDAS Open. The current "
            "bridge should be replaced by the next annual MIDAS Open release "
            "once 2026 becomes openly available."
        ),
    }

    out = current_cache_path(cache_dir)
    atomic_pickle_gzip(out, payload)

    status = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "historical_source": HISTORICAL_SOURCE,
        "year": YEAR,
        "complete": True,
        "provisional_bridge": True,
        "ghcn_version": ghcn_version,
        "ghcn_stations_total": len(stations),
        "ghcn_active_tmax_or_tmin_2026": len(active),
        "ghcn_active_both_2026": both,
        "station_count_with_2026_values": len(records),
        "matched_historical_station_count": matched,
        "unmatched_current_station_count": unmatched,
        "first_date": first_date,
        "last_date": last_date,
        "observation_days": payload["observation_days"],
        "tmax_days": payload["tmax_days"],
        "tmin_days": payload["tmin_days"],
        "mflag_counts": dict(global_mflags),
        "sflag_counts": dict(global_sflags),
        "stats": dict(global_stats),
        "crosswalk": crosswalk_rows,
    }
    atomic_json(current_status_path(cache_dir), status)

    log()
    log("=== UK CURRENT 2026 SUMMARY · GHCN-BRÜCKE ===")
    log(f"GHCN-Version: {ghcn_version}")
    log(f"Aktive GHCN-Kandidaten 2026: {len(active):,}")
    log(f"Stationsdateien erfolgreich: {successful_files:,}/{len(active):,}")
    log(f"2026-Temperaturreihen: {len(records):,}")
    log(f"Mit MIDAS-Historie gematcht: {matched:,}")
    log(f"Unmatched/current-only: {unmatched:,}")
    log(f"TMAX-Tage: {payload['tmax_days']:,}")
    log(f"TMIN-Tage: {payload['tmin_days']:,}")
    log(f"Datenzeitraum: {first_date} bis {last_date}")
    log(f"MFLAG-Verteilung: {dict(global_mflags.most_common())}")
    log(f"SFLAG-Verteilung: {dict(global_sflags.most_common())}")
    log(f"Output: {out}")
    log("UK Current-2026 GHCN-Brückencache vollständig OK.")
    log()
    log("=== CROSSWALK ===")
    for row in crosswalk_rows:
        log(
            f"{row['ghcn_id']} | {row['ghcn_name']} -> "
            f"{row['output_key']} | {row['method']} | "
            f"dist={row.get('distance_km')} km | "
            f"name_sim={row.get('name_similarity')}"
        )

    return out


def self_test() -> None:
    # GHCN station fixed-width parser.
    line = (
        "UKM00003772  51.4780   -0.4610   25.3    HEATHROW"
        "                         03772"
    )
    # Build a guaranteed correctly-positioned synthetic line.
    buf = [" "] * 90
    buf[0:11] = list("UKM00003772")
    buf[12:20] = list(f"{51.4780:8.4f}")
    buf[21:30] = list(f"{-0.4610:9.4f}")
    buf[31:37] = list(f"{25.3:6.1f}")
    name = "HEATHROW"
    buf[41:41+len(name)] = list(name)
    buf[80:85] = list("03772")
    parsed = parse_ghcn_stations("".join(buf))
    assert parsed["UKM00003772"]["wmo_id"] == "03772"

    # Inventory parser.
    inv = [" "] * 50
    inv[0:11] = list("UKM00003772")
    inv[12:20] = list(f"{51.4780:8.4f}")
    inv[21:30] = list(f"{-0.4610:9.4f}")
    inv[31:35] = list("TMAX")
    inv[36:40] = list("1948")
    inv[41:45] = list("2026")
    inventory = parse_ghcn_inventory("".join(inv))
    assert inventory["UKM00003772"]["TMAX"] == (1948, 2026)

    # GHCN by_station parser with one accepted and one QFLAG-rejected value.
    rows = (
        "UKM00003772,20260801,TMAX,350,, ,G,0900\n"
        "UKM00003772,20260801,TMIN,180,,X,G,0900\n"
    )
    daily, stats, _, _ = parse_by_station(
        rows.encode("utf-8"), "UKM00003772"
    )
    assert daily[date(2026, 8, 1)]["tmax"] == 35.0
    assert daily[date(2026, 8, 1)]["tmin"] is None
    assert stats["rejected_qflag_X"] == 1

    # Coordinate/name crosswalk.
    ghcn = {
        "name": "HEATHROW",
        "lat": 51.4780,
        "lon": -0.4610,
        "wmo_id": "",
    }
    midas = [{
        "key": "00708_heathrow",
        "name": "heathrow",
        "lat": 51.479,
        "lon": -0.449,
        "wmo_ids": [],
        "meta": {},
    }]
    cw = crosswalk_one(
        ghcn,
        midas,
        {"00708_heathrow": midas[0]},
        {},
    )
    assert cw["matched"] is True

    print("UK current 2026 GHCN bridge self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_current(Path(args.cache_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
