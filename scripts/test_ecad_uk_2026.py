#!/usr/bin/env python3
"""Probe ECA&D as an open 2026 bridge for UK daily TMAX/TMIN.

This probe deliberately does NOT build a production cache.

It checks the official ECA&D predefined metadata files for:
  * UK (GB) TX/TN station inventory
  * source series which actually extend into 2026
  * exact UK Met Office 09-09 definitions (TX9 / TN9)
  * whether those participant source series also occur in the downloadable
    non-blended subset
  * the contribution of GTS/SYNOP sources to blended series
  * an optional crosswalk against an already completed Met Office MIDAS
    historical cache if one is present locally

Important ECA&D timing semantics:
  TX9 = maximum from previous-day 09 GMT to current-day 09 GMT,
        shifted one day back by ECA&D staff.
  TN9 = minimum from previous-day 09 GMT to current-day 09 GMT.

Therefore TX9/TN9 are the preferred pair for matching the Met Office MIDAS
09-09 daily-temperature convention used by this project.
"""
from __future__ import annotations

import csv
import difflib
import gzip
import io
import math
import pickle
import re
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

UA = "climate-dashboard-ecad-uk-probe/1.0 (+GitHub Actions)"

BLEND_STATION_TX = (
    "https://knmi-ecad-assets-prd.s3.amazonaws.com/download/"
    "ECA_blend_station_tx.txt"
)
BLEND_STATION_TN = (
    "https://knmi-ecad-assets-prd.s3.amazonaws.com/download/"
    "ECA_blend_station_tn.txt"
)
BLEND_SOURCE_TX = (
    "https://knmi-ecad-assets-prd.s3.amazonaws.com/download/"
    "ECA_blend_source_tx.txt"
)
BLEND_SOURCE_TN = (
    "https://knmi-ecad-assets-prd.s3.amazonaws.com/download/"
    "ECA_blend_source_tn.txt"
)
NONBLEND_INFO_TX = (
    "https://knmi-ecad-assets-prd.s3.amazonaws.com/download/"
    "ECA_nonblend_info_tx.txt"
)
NONBLEND_INFO_TN = (
    "https://knmi-ecad-assets-prd.s3.amazonaws.com/download/"
    "ECA_nonblend_info_tn.txt"
)

ECAD_DAILY_PAGE = "https://www.ecad.eu/dailydata/"
ECAD_ELEMENTS_PAGE = "https://www.ecad.eu/dailydata/datadictionaryelement.php"

COUNTRY = "GB"
YEAR_START = 20260101
JUNE_END = 20260630

MIDAS_CACHE = Path(
    ".cache/europe-stations/"
    "metoffice_uk_midas_daily_baseline_through_2025_v1.pkl.gz"
)

SAMPLE_NAMES = (
    "HEATHROW",
    "LEUCHARS",
    "ROTHAMSTED",
    "WRITTLE",
    "BRADFORD",
    "BUXTON",
    "WELLESBOURNE",
    "KINLOCHEWE",
    "MANSTON",
    "HURN",
    "OXFORD",
    "ESKDALEMUIR",
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def request_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/plain,*/*",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        raw = response.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8-sig", errors="replace")


def parse_table(text: str, header_first_field: str) -> tuple[list[dict[str, str]], str]:
    """Parse ECA&D metadata text after its human-readable preamble."""
    lines = text.splitlines()
    header_idx = None

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(header_first_field + ","):
            header_idx = i
            break

    if header_idx is None:
        raise RuntimeError(
            f"ECA&D header {header_first_field!r} not found."
        )

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    rows: list[dict[str, str]] = []

    for row in reader:
        cleaned = {}
        for key, value in row.items():
            if key is None:
                continue
            cleaned[key.strip()] = (value or "").strip()
        if cleaned:
            rows.append(cleaned)

    created = ""
    for line in lines[:header_idx]:
        if "created on" in line.lower() or "file created on" in line.lower():
            created = line.strip()
            break

    return rows, created


def int_or_none(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize_country(row: dict[str, str]) -> str:
    return row.get("CN", "").strip().upper()


def station_id(row: dict[str, str]) -> int | None:
    return int_or_none(row.get("STAID", ""))


def source_id(row: dict[str, str]) -> int | None:
    return int_or_none(row.get("SOUID", ""))


def parse_dms(text: str) -> float | None:
    s = str(text).strip()
    m = re.fullmatch(r"([+-])(\d+):(\d+):(\d+)", s)
    if not m:
        return None
    sign = -1.0 if m.group(1) == "-" else 1.0
    deg = int(m.group(2))
    minute = int(m.group(3))
    second = int(m.group(4))
    return sign * (deg + minute / 60.0 + second / 3600.0)


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(
        r"\b(AIRPORT|AP|WEATHER CENTRE|WEATHER CENTER|METEOROLOGICAL STATION)\b",
        " ",
        text,
    )
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
        math.sin(dp / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    )
    return 2.0 * r * math.asin(math.sqrt(a))


def uk_station_map(rows: list[dict[str, str]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        if normalize_country(row) != COUNTRY:
            continue
        sid = station_id(row)
        if sid is None:
            continue
        out[sid] = {
            "staid": sid,
            "name": row.get("STANAME", "").strip(),
            "lat": parse_dms(row.get("LAT", "")),
            "lon": parse_dms(row.get("LON", "")),
            "height_m": int_or_none(row.get("HGHT", "")),
        }
    return out


def uk_blend_sources(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if normalize_country(row) != COUNTRY:
            continue
        sid = station_id(row)
        souid = source_id(row)
        if sid is None or souid is None:
            continue
        out.append(
            {
                "staid": sid,
                "souid": souid,
                "name": row.get("SOUNAME", "").strip(),
                "lat": parse_dms(row.get("LAT", "")),
                "lon": parse_dms(row.get("LON", "")),
                "height_m": int_or_none(row.get("HGHT", "")),
                "eleid": row.get("ELEI", row.get("ELEID", "")).strip(),
                "start": int_or_none(row.get("START", "")),
                "stop": int_or_none(row.get("STOP", "")),
                "parid": row.get("PARID", "").strip(),
                "parname": row.get("PARNAME", "").strip(),
            }
        )
    return out


def uk_nonblend_sources(rows: list[dict[str, str]]) -> dict[int, dict[str, Any]]:
    out = {}
    for row in rows:
        if normalize_country(row) != COUNTRY:
            continue
        souid = source_id(row)
        if souid is None:
            continue
        out[souid] = {
            "souid": souid,
            "name": row.get("SOUNAME", "").strip(),
            "lat": parse_dms(row.get("LAT", "")),
            "lon": parse_dms(row.get("LON", "")),
            "height_m": int_or_none(row.get("HGHT", "")),
            "eleid": row.get("ELEID", row.get("ELEI", "")).strip(),
            "start": int_or_none(row.get("START", "")),
            "stop": int_or_none(row.get("STOP", "")),
            "parid": row.get("PARID", "").strip(),
            "parname": row.get("PARNAME", "").strip(),
        }
    return out


def group_by_station(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[row["staid"]].append(row)
    return dict(out)


def active_sources(
    rows: list[dict[str, Any]],
    *,
    eleid: str | None = None,
    ukmo_only: bool = False,
) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        stop = row.get("stop")
        if stop is None or stop < YEAR_START:
            continue
        if eleid is not None and row.get("eleid") != eleid:
            continue
        if ukmo_only:
            if row.get("parid") != "35":
                continue
            if "UKMO" not in row.get("parname", "").upper():
                continue
        out.append(row)
    return out


def best_exact_source(
    rows: list[dict[str, Any]],
    eleid: str,
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if row.get("eleid") == eleid
        and row.get("parid") == "35"
        and "UKMO" in row.get("parname", "").upper()
        and (row.get("stop") or 0) >= YEAR_START
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda x: (x.get("stop") or 0, x.get("start") or 0))


def recursively_find_number(obj: Any, exact_keys: tuple[str, ...]) -> float | None:
    targets = {re.sub(r"[^a-z0-9]+", "_", k.lower()).strip("_") for k in exact_keys}

    def visit(x: Any) -> float | None:
        if isinstance(x, dict):
            for key, value in x.items():
                nk = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
                if nk in targets:
                    try:
                        number = float(str(value).strip())
                    except (TypeError, ValueError):
                        number = None
                    if number is not None and math.isfinite(number):
                        return number
            for value in x.values():
                found = visit(value)
                if found is not None:
                    return found
        elif isinstance(x, (list, tuple)):
            for value in x:
                found = visit(value)
                if found is not None:
                    return found
        return None

    return visit(obj)


def load_midas_candidates() -> list[dict[str, Any]]:
    if not MIDAS_CACHE.exists():
        return []

    with gzip.open(MIDAS_CACHE, "rb") as f:
        baseline = pickle.load(f)

    if not isinstance(baseline, dict) or baseline.get("complete") is not True:
        return []

    out = []
    for key, meta in baseline.get("station_details", {}).items():
        if not isinstance(meta, dict):
            continue

        dmeta = meta.get("dataset_metadata", {})
        lat = recursively_find_number(
            dmeta,
            ("latitude", "station_latitude", "src_latitude", "lat"),
        )
        lon = recursively_find_number(
            dmeta,
            ("longitude", "station_longitude", "src_longitude", "lon"),
        )

        if lat is not None and not (49.0 <= lat <= 61.5):
            lat = None
        if lon is not None and not (-9.5 <= lon <= 2.5):
            lon = None

        out.append(
            {
                "key": key,
                "name": str(meta.get("name") or key),
                "lat": lat,
                "lon": lon,
            }
        )
    return out


def crosswalk_ecad_to_midas(
    station: dict[str, Any],
    midas: list[dict[str, Any]],
) -> dict[str, Any]:
    if station["lat"] is None or station["lon"] is None:
        return {"matched": False, "method": "ECAD_NO_COORD"}

    candidates = []
    for target in midas:
        if target["lat"] is None or target["lon"] is None:
            continue
        d = haversine_km(
            station["lat"], station["lon"], target["lat"], target["lon"]
        )
        sim = name_similarity(station["name"], target["name"])
        candidates.append((d, -sim, target))

    if not candidates:
        return {"matched": False, "method": "MIDAS_NO_COORD"}

    candidates.sort(key=lambda x: (x[0], x[1]))
    dist, neg_sim, target = candidates[0]
    sim = -neg_sim
    second = candidates[1][0] if len(candidates) > 1 else float("inf")

    if dist <= 0.75 and second - dist >= 0.15:
        return {
            "matched": True,
            "method": "COORD_STRICT",
            "midas_key": target["key"],
            "midas_name": target["name"],
            "distance_km": round(dist, 3),
            "name_similarity": round(sim, 3),
        }

    if dist <= 3.0 and sim >= 0.55:
        return {
            "matched": True,
            "method": "COORD_NAME",
            "midas_key": target["key"],
            "midas_name": target["name"],
            "distance_km": round(dist, 3),
            "name_similarity": round(sim, 3),
        }

    if dist <= 7.0 and sim >= 0.82:
        return {
            "matched": True,
            "method": "NAME_COORD",
            "midas_key": target["key"],
            "midas_name": target["name"],
            "distance_km": round(dist, 3),
            "name_similarity": round(sim, 3),
        }

    return {
        "matched": False,
        "method": "UNMATCHED",
        "nearest_midas_key": target["key"],
        "nearest_midas_name": target["name"],
        "distance_km": round(dist, 3),
        "name_similarity": round(sim, 3),
    }


def print_source(row: dict[str, Any] | None) -> str:
    if row is None:
        return "-"
    return (
        f"SOUID={row['souid']} {row['name']} | {row['eleid']} | "
        f"{row['start']}-{row['stop']} | PARID={row['parid']} "
        f"{row['parname']}"
    )


def main() -> int:
    log("=== ECA&D UK 2026 PROBE ===")
    log("Noch kein Produktionscache.")
    log()

    targets = {
        "blend_station_tx": (BLEND_STATION_TX, "STAID"),
        "blend_station_tn": (BLEND_STATION_TN, "STAID"),
        "blend_source_tx": (BLEND_SOURCE_TX, "STAID"),
        "blend_source_tn": (BLEND_SOURCE_TN, "STAID"),
        "nonblend_info_tx": (NONBLEND_INFO_TX, "SOUID"),
        "nonblend_info_tn": (NONBLEND_INFO_TN, "SOUID"),
    }

    parsed = {}
    created = {}

    for key, (url, header) in targets.items():
        log(f"Lade {key}: {url}")
        text = request_text(url)
        rows, stamp = parse_table(text, header)
        parsed[key] = rows
        created[key] = stamp
        log(f"  {len(rows):,} Datensätze | {stamp}")

    tx_stations = uk_station_map(parsed["blend_station_tx"])
    tn_stations = uk_station_map(parsed["blend_station_tn"])
    tx_sources = uk_blend_sources(parsed["blend_source_tx"])
    tn_sources = uk_blend_sources(parsed["blend_source_tn"])
    nb_tx = uk_nonblend_sources(parsed["nonblend_info_tx"])
    nb_tn = uk_nonblend_sources(parsed["nonblend_info_tn"])

    tx_by_station = group_by_station(tx_sources)
    tn_by_station = group_by_station(tn_sources)

    common_stations = sorted(set(tx_stations) & set(tn_stations))

    log()
    log("=" * 82)
    log("1. ECA&D UK INVENTORY")
    log("=" * 82)
    log(f"Blended TX-Stationen GB: {len(tx_stations):,}")
    log(f"Blended TN-Stationen GB: {len(tn_stations):,}")
    log(f"Gemeinsame TX+TN-Stationen GB: {len(common_stations):,}")
    log(f"Blended TX-Quellreihen GB: {len(tx_sources):,}")
    log(f"Blended TN-Quellreihen GB: {len(tn_sources):,}")
    log(f"Non-blended/downloadbare TX-Quellreihen GB: {len(nb_tx):,}")
    log(f"Non-blended/downloadbare TN-Quellreihen GB: {len(nb_tn):,}")

    tx_active_any = active_sources(tx_sources)
    tn_active_any = active_sources(tn_sources)
    tx_exact = active_sources(tx_sources, eleid="TX9", ukmo_only=True)
    tn_exact = active_sources(tn_sources, eleid="TN9", ukmo_only=True)

    log()
    log("=" * 82)
    log("2. UK 2026 SOURCE COVERAGE")
    log("=" * 82)
    log(f"TX-Quellen mit STOP >= 2026-01-01: {len(tx_active_any):,}")
    log(f"TN-Quellen mit STOP >= 2026-01-01: {len(tn_active_any):,}")
    log(
        "Davon exakte UKMO-09-09-Quellen TX9: "
        f"{len(tx_exact):,} | Stationen={len({x['staid'] for x in tx_exact}):,}"
    )
    log(
        "Davon exakte UKMO-09-09-Quellen TN9: "
        f"{len(tn_exact):,} | Stationen={len({x['staid'] for x in tn_exact}):,}"
    )

    tx_ele_counts = Counter(row["eleid"] for row in tx_active_any)
    tn_ele_counts = Counter(row["eleid"] for row in tn_active_any)

    log()
    log("=" * 82)
    log("3. ELEMENT-IDs DER 2026-QUELLEN")
    log("=" * 82)
    log(f"TX: {dict(tx_ele_counts.most_common())}")
    log(f"TN: {dict(tn_ele_counts.most_common())}")
    log("Bevorzugt für MIDAS-Kompatibilität: TX9 + TN9.")
    log(
        "GTS/SYNOP-Erweiterungen sind typischerweise TX7/TN6 und werden "
        "getrennt betrachtet."
    )

    exact_pairs = []
    exact_pairs_downloadable = []
    exact_pairs_to_june_end = []

    for sid in common_stations:
        tx = best_exact_source(tx_by_station.get(sid, []), "TX9")
        tn = best_exact_source(tn_by_station.get(sid, []), "TN9")
        if tx is None or tn is None:
            continue

        station = tx_stations.get(sid) or tn_stations[sid]
        item = {
            "staid": sid,
            "station": station,
            "tx": tx,
            "tn": tn,
            "tx_nonblend_downloadable": tx["souid"] in nb_tx,
            "tn_nonblend_downloadable": tn["souid"] in nb_tn,
        }
        exact_pairs.append(item)

        if item["tx_nonblend_downloadable"] and item["tn_nonblend_downloadable"]:
            exact_pairs_downloadable.append(item)

        if (tx.get("stop") or 0) >= 20260629 and (tn.get("stop") or 0) >= 20260629:
            exact_pairs_to_june_end.append(item)

    log()
    log("=" * 82)
    log("4. EXAKTE TX9+TN9-PAARE")
    log("=" * 82)
    log(
        "ECA&D-Stationen mit UKMO TX9 UND TN9, beide mit Daten in 2026: "
        f"{len(exact_pairs):,}"
    )
    log(
        "Davon beide Originalquellen im non-blended/downloadbaren Bestand: "
        f"{len(exact_pairs_downloadable):,}"
    )
    log(
        "Davon TX und TN mindestens bis 29.06.2026 geführt: "
        f"{len(exact_pairs_to_june_end):,}"
    )

    # Show whether the newest 2026 extension is participant or GTS.
    gts_tx = [
        x for x in tx_active_any
        if x.get("parid") == "-" or "SYNOPTICAL" in x.get("parname", "").upper()
    ]
    gts_tn = [
        x for x in tn_active_any
        if x.get("parid") == "-" or "SYNOPTICAL" in x.get("parname", "").upper()
    ]

    log()
    log("=" * 82)
    log("5. BLENDING / GTS")
    log("=" * 82)
    log(f"GB TX-GTS/SYNOP-Quellen mit 2026-Abdeckung: {len(gts_tx):,}")
    log(f"GB TN-GTS/SYNOP-Quellen mit 2026-Abdeckung: {len(gts_tn):,}")
    log(
        "Hinweis: Diese GTS-Reihen sind nicht unsere bevorzugte Rekordquelle. "
        "Für eine mögliche UK-2026-Brücke priorisieren wir participant/UKMO "
        "TX9 und TN9."
    )

    log()
    log("=" * 82)
    log("6. STATIONSSAMPLES")
    log("=" * 82)

    sample_items = []
    for item in exact_pairs:
        name = normalize_name(item["station"]["name"])
        if any(target in name for target in SAMPLE_NAMES):
            sample_items.append(item)

    if len(sample_items) < 12:
        known = {x["staid"] for x in sample_items}
        for item in sorted(
            exact_pairs,
            key=lambda x: min(x["tx"]["stop"] or 0, x["tn"]["stop"] or 0),
            reverse=True,
        ):
            if item["staid"] in known:
                continue
            sample_items.append(item)
            known.add(item["staid"])
            if len(sample_items) >= 20:
                break

    for item in sample_items[:20]:
        st = item["station"]
        log(
            f"{item['staid']:5d} | {st['name']} | "
            f"{st['lat']:.4f},{st['lon']:.4f} | "
            f"TX_STOP={item['tx']['stop']} | TN_STOP={item['tn']['stop']} | "
            f"nonblend TX/TN="
            f"{item['tx_nonblend_downloadable']}/"
            f"{item['tn_nonblend_downloadable']}"
        )
        log(f"       TX: {print_source(item['tx'])}")
        log(f"       TN: {print_source(item['tn'])}")

    # Optional MIDAS crosswalk if baseline is already available in restored cache.
    midas = load_midas_candidates()

    log()
    log("=" * 82)
    log("7. OPTIONALER MIDAS-CROSSWALK")
    log("=" * 82)

    if not midas:
        log(
            "Historischer MIDAS-Cache ist in diesem Run noch nicht vollständig "
            "vorhanden -> Crosswalk wird übersprungen."
        )
    else:
        matched = 0
        unmatched = 0
        log(f"MIDAS-Kandidaten geladen: {len(midas):,}")

        for item in exact_pairs_downloadable:
            cw = crosswalk_ecad_to_midas(item["station"], midas)
            if cw.get("matched"):
                matched += 1
            else:
                unmatched += 1

            if matched + unmatched <= 30:
                log(
                    f"ECA STAID {item['staid']} {item['station']['name']} -> "
                    f"{cw.get('midas_key', cw.get('nearest_midas_key', '-'))} | "
                    f"{cw['method']} | dist={cw.get('distance_km')} | "
                    f"name_sim={cw.get('name_similarity')}"
                )

        log(f"Sauber gematcht: {matched:,}")
        log(f"Nicht sicher gematcht: {unmatched:,}")

    log()
    log("=" * 82)
    log("8. FAZIT")
    log("=" * 82)

    if exact_pairs_downloadable:
        log(
            "ECA&D besitzt frei herunterladbare britische participant/UKMO-"
            "Quellreihen mit exakt passender TX9/TN9-Tagesdefinition und "
            "2026-Abdeckung."
        )
        log(
            "Nächster Schritt wäre NICHT sofort die Europa-Integration, sondern "
            "eine kleine Tagesdatenprobe für ausgewählte STAIDs, um VALUE/QFLAG/"
            "SOUID und die tatsächliche letzte 2026-Datenzeile zu prüfen."
        )
    else:
        log(
            "Keine vollständig downloadbaren TX9/TN9-Paare gefunden. "
            "ECA&D wäre damit für unseren Current-Cache nicht geeignet."
        )

    log()
    log("Bitte aus dem GitHub-Log schicken:")
    log("1. ECA&D UK INVENTORY")
    log("2. UK 2026 SOURCE COVERAGE")
    log("3. ELEMENT-IDs DER 2026-QUELLEN")
    log("4. EXAKTE TX9+TN9-PAARE")
    log("5. STATIONSSAMPLES")
    log("6. OPTIONALER MIDAS-CROSSWALK (falls vorhanden)")
    return 0


def self_test() -> None:
    sample_station = """\
EUROPEAN CLIMATE ASSESSMENT & DATASET
STAID,STANAME                                 ,CN,      LAT,       LON,HGHT
 1860,HEATHROW                                ,GB  ,+51:28:44,-000:26:56,   25
"""
    rows, _ = parse_table(sample_station, "STAID")
    stations = uk_station_map(rows)
    assert 1860 in stations
    assert abs(stations[1860]["lat"] - 51.4788889) < 1e-4

    sample_source = """\
EUROPEAN CLIMATE ASSESSMENT & DATASET
STAID, SOUID,SOUNAME                                 ,CN,      LAT,       LON,HGHT,ELEI,   START,    STOP,PARID,PARNAME
 1860,105838,HEATHROW                                ,GB,+51:28:44,-000:26:56,  25, TX9,19591231,20260629,   35,National Climate Information Centre (UKMO)
"""
    rows, _ = parse_table(sample_source, "STAID")
    src = uk_blend_sources(rows)
    assert len(src) == 1
    assert src[0]["eleid"] == "TX9"
    assert src[0]["stop"] == 20260629
    assert len(active_sources(src, eleid="TX9", ukmo_only=True)) == 1

    print("ECA&D UK probe self-test OK")


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
