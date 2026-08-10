#!/usr/bin/env python3
"""
MeteoSwiss Switzerland probe for climate-dashboard station records.

Official Open Data collections inspected:
1) SwissMetNet raw/quality-controlled station measurements
   ch.meteoschweiz.ogd-smn
2) Swiss NBCN homogeneous climate-station series
   ch.meteoschweiz.ogd-nbcn

Goals:
- discover daily Tmin/Tmax parameter identifiers from live metadata
- count stations and actual data-inventory coverage
- determine earliest/latest daily Tmin/Tmax inventory dates
- inspect STAC assets for historical/recent daily CSV files
- parse a real daily sample file and print date/value columns
- compare raw SwissMetNet coverage with homogeneous NBCN coverage
- keep the two products explicitly separate; this probe does NOT merge them

No API key / secret is required.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from typing import Any

UA = "climate-dashboard-meteoswiss-switzerland-probe/1.0"
TRIES = 5
TIMEOUT = 90

STAC_ROOT = "https://data.geo.admin.ch/api/stac/v1"
DATA_ROOT = "https://data.geo.admin.ch"

COLLECTIONS = {
    "SMN": {
        "id": "ch.meteoschweiz.ogd-smn",
        "label": "SwissMetNet station measurements",
        "prefix": "ogd-smn",
        "homogeneous": False,
    },
    "NBCN": {
        "id": "ch.meteoschweiz.ogd-nbcn",
        "label": "Swiss NBCN homogeneous climate series",
        "prefix": "ogd-nbcn",
        "homogeneous": True,
    },
}


def log(msg: str = "") -> None:
    print(msg, flush=True)


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
            wait = min(20, attempt * 3)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(str(last))


def get_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = request_bytes(url, params=params, accept="application/json,*/*")
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"JSON-Antwort ist kein Objekt: {url}")
    return obj


def decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t,")
        return dialect.delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in (";", ",", "\t", "|")}
        return max(counts, key=counts.get)


def read_csv_bytes(raw: bytes) -> tuple[list[str], list[dict[str, str]], str]:
    text = decode_text(raw)
    delimiter = sniff_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fields = list(reader.fieldnames or [])
    rows = [dict(row) for row in reader]
    return fields, rows, delimiter


def norm(value: Any) -> str:
    s = str(value or "").lower()
    s = (
        s.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("é", "e")
        .replace("è", "e")
        .replace("à", "a")
        .replace("ê", "e")
    )
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def pick_column(
    fields: list[str],
    exact: tuple[str, ...],
    contains: tuple[str, ...] = (),
) -> str | None:
    normalized = {norm(field): field for field in fields}

    for candidate in exact:
        key = norm(candidate)
        if key in normalized:
            return normalized[key]

    for field in fields:
        n = norm(field)
        if any(norm(candidate) in n for candidate in contains):
            return field

    return None


def collection_asset_urls(
    collection: dict[str, Any],
    prefix: str,
) -> dict[str, str]:
    assets = collection.get("assets")
    out: dict[str, str] = {}

    if isinstance(assets, dict):
        for key, meta in assets.items():
            if isinstance(meta, dict) and meta.get("href"):
                out[str(key)] = str(meta["href"])

    defaults = {
        f"{prefix}_meta_parameters.csv":
            f"{DATA_ROOT}/{collection['id']}/{prefix}_meta_parameters.csv",
        f"{prefix}_meta_stations.csv":
            f"{DATA_ROOT}/{collection['id']}/{prefix}_meta_stations.csv",
        f"{prefix}_meta_datainventory.csv":
            f"{DATA_ROOT}/{collection['id']}/{prefix}_meta_datainventory.csv",
    }
    for key, url in defaults.items():
        out.setdefault(key, url)

    return out


def find_meta_url(assets: dict[str, str], suffix: str) -> str:
    for key, url in assets.items():
        if key.lower().endswith(suffix.lower()) or url.lower().endswith(suffix.lower()):
            return url
    raise RuntimeError(f"Metadaten-Datei nicht gefunden: {suffix}")


def parameter_columns(fields: list[str]) -> dict[str, str | None]:
    return {
        "id": pick_column(
            fields,
            ("parameter", "parameter_id", "param_id", "shortname", "identifier"),
            ("parameter", "shortname", "identifier"),
        ),
        "description": pick_column(
            fields,
            ("description", "parameter_description", "name", "definition"),
            ("description", "bezeichnung", "definition"),
        ),
        "granularity": pick_column(
            fields,
            ("granularity", "time_interval", "temporal_resolution", "interval"),
            ("granularity", "resolution", "interval"),
        ),
        "unit": pick_column(
            fields,
            ("unit", "unit_of_measurement"),
            ("unit", "einheit"),
        ),
    }


def station_columns(fields: list[str]) -> dict[str, str | None]:
    return {
        "id": pick_column(
            fields,
            ("station_abbr", "station_id", "station", "abbr", "identifier"),
            ("station", "abbr"),
        ),
        "name": pick_column(
            fields,
            ("station_name", "name"),
            ("station_name",),
        ),
        "lat": pick_column(
            fields,
            ("latitude", "lat"),
            ("latitude",),
        ),
        "lon": pick_column(
            fields,
            ("longitude", "lon"),
            ("longitude",),
        ),
        "elev": pick_column(
            fields,
            ("station_height_masl", "altitude", "elevation", "height"),
            ("altitude", "elevation", "height"),
        ),
        "wigos": pick_column(
            fields,
            ("wigos_id", "wigos"),
            ("wigos",),
        ),
    }


def inventory_columns(fields: list[str]) -> dict[str, str | None]:
    return {
        "station": pick_column(
            fields,
            ("station_abbr", "station_id", "station", "abbr"),
            ("station", "abbr"),
        ),
        "parameter": pick_column(
            fields,
            ("parameter", "parameter_id", "param_id", "shortname"),
            ("parameter", "shortname"),
        ),
        "start": pick_column(
            fields,
            ("start_date", "date_from", "from", "start"),
            ("start_date", "date_from", "start"),
        ),
        "end": pick_column(
            fields,
            ("end_date", "date_to", "to", "end"),
            ("end_date", "date_to", "end"),
        ),
    }


def text_of_row(row: dict[str, str]) -> str:
    return " ".join(str(value or "") for value in row.values()).lower()


def looks_daily(row: dict[str, str], parameter_id: str) -> bool:
    pid = parameter_id.lower()
    text = text_of_row(row)

    # MeteoSwiss identifiers often encode daily with d/p.
    # Prefer metadata wording when available.
    daily_words = (
        "daily", "day", "taeglich", "täglich", "jour", "giornal",
        "24:00", "24h",
    )
    if any(word in text for word in daily_words):
        return True

    return bool(re.search(r"(?:d[0-9a-z]*[nxv]?|p[nx])$", pid))


def temp_kind(row: dict[str, str], parameter_id: str) -> str | None:
    pid = parameter_id.lower()
    text = text_of_row(row)

    temp_words = (
        "temperature", "temperatur", "température", "temperatura",
        "air temperature", "lufttemperatur",
    )
    if not any(word in text for word in temp_words) and not pid.startswith(("tre", "tho", "th")):
        return None

    max_words = ("maximum", "maximal", "maximum", "massima", "höchst", "hoechst")
    min_words = ("minimum", "minimal", "minimum", "minima", "tiefst")

    if any(word in text for word in max_words) or pid.endswith(("dx", "px", "d1", "x")):
        return "TMAX"
    if any(word in text for word in min_words) or pid.endswith(("dn", "pn", "d2", "n")):
        return "TMIN"

    return None


def discover_daily_temperature_parameters(
    rows: list[dict[str, str]],
    columns: dict[str, str | None],
) -> dict[str, list[dict[str, str]]]:
    pid_col = columns["id"]
    if not pid_col:
        raise RuntimeError("Parameter-ID-Spalte wurde nicht erkannt.")

    found = {"TMIN": [], "TMAX": []}

    for row in rows:
        pid = str(row.get(pid_col, "") or "").strip()
        if not pid:
            continue
        if not looks_daily(row, pid):
            continue
        kind = temp_kind(row, pid)
        if kind:
            found[kind].append(row)

    return found


def parse_date_loose(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None

    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass

    for candidate in (text[:10], text[:8]):
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue

    return None


def inventory_for_parameters(
    rows: list[dict[str, str]],
    columns: dict[str, str | None],
    parameter_ids: set[str],
) -> dict[str, Any]:
    station_col = columns["station"]
    parameter_col = columns["parameter"]
    start_col = columns["start"]
    end_col = columns["end"]

    if not station_col or not parameter_col:
        raise RuntimeError("Inventar: Stations-/Parameterspalte nicht erkannt.")

    selected = []
    stations = set()
    starts = []
    ends = []
    by_param: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        pid = str(row.get(parameter_col, "") or "").strip()
        if pid not in parameter_ids:
            continue

        station = str(row.get(station_col, "") or "").strip().upper()
        if not station:
            continue

        selected.append(row)
        stations.add(station)
        by_param[pid].add(station)

        if start_col:
            d = parse_date_loose(row.get(start_col))
            if d:
                starts.append(d)
        if end_col:
            d = parse_date_loose(row.get(end_col))
            if d:
                ends.append(d)

    return {
        "rows": selected,
        "stations": stations,
        "by_param": by_param,
        "earliest": min(starts) if starts else None,
        "latest": max(ends) if ends else None,
    }


def station_info(
    rows: list[dict[str, str]],
    columns: dict[str, str | None],
) -> dict[str, dict[str, str]]:
    id_col = columns["id"]
    if not id_col:
        return {}

    out = {}
    for row in rows:
        sid = str(row.get(id_col, "") or "").strip().upper()
        if sid:
            out[sid] = row
    return out


def stac_items(collection_id: str, limit: int = 500) -> list[dict[str, Any]]:
    url = f"{STAC_ROOT}/collections/{collection_id}/items"
    payload = get_json(url, {"limit": limit})
    items = payload.get("features") or []
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


def item_station_id(item: dict[str, Any]) -> str:
    candidates = [
        item.get("id"),
        (item.get("properties") or {}).get("station"),
        (item.get("properties") or {}).get("station_id"),
        (item.get("properties") or {}).get("station_abbr"),
    ]
    text = " ".join(str(x or "") for x in candidates).lower()

    # MeteoSwiss station ids are 3 letters; asset names also contain them.
    tokens = re.findall(r"(?:^|[_\-\s])([a-z]{3})(?:[_\-\s]|$)", text)
    # IDs such as "ogd-smn_ber" also contain generic three-letter tokens
    # ("ogd", "smn"). The station abbreviation is the final matching token.
    if tokens:
        return tokens[-1].upper()

    assets = item.get("assets") or {}
    if isinstance(assets, dict):
        for key, meta in assets.items():
            href = ""
            if isinstance(meta, dict):
                href = str(meta.get("href", ""))
            probe = f"{key} {href}".lower()
            m = re.search(r"ogd-[a-z0-9\-]+_([a-z]{3})_", probe)
            if m:
                return m.group(1).upper()

    return ""


def assets_for_item(item: dict[str, Any]) -> list[tuple[str, str]]:
    assets = item.get("assets") or {}
    out = []
    if not isinstance(assets, dict):
        return out
    for key, meta in assets.items():
        if isinstance(meta, dict) and meta.get("href"):
            out.append((str(key), str(meta["href"])))
    return out


def classify_daily_asset(name: str, href: str) -> str | None:
    text = f"{name} {href}".lower()
    filename = href.rsplit("/", 1)[-1].lower()

    is_daily = (
        re.search(r"_d_(?:historical|recent)(?:[_\-.]|$)", filename)
        or re.search(r"_d_[0-9]{4}", filename)
        or "_daily_" in filename
    )
    if not is_daily:
        return None

    if "historical" in text:
        return "historical"
    if "recent" in text:
        return "recent"
    return "daily-other"


def choose_item_for_station(
    items: list[dict[str, Any]],
    preferred: list[str],
) -> tuple[str, dict[str, Any]] | None:
    indexed = {}
    for item in items:
        sid = item_station_id(item)
        if sid:
            indexed[sid] = item

    for sid in preferred:
        if sid in indexed:
            return sid, indexed[sid]

    for sid, item in sorted(indexed.items()):
        return sid, item

    return None


def inspect_sample_daily_csv(
    href: str,
    wanted_parameter_ids: set[str],
) -> dict[str, Any]:
    raw = request_bytes(href, accept="text/csv,*/*")
    fields, rows, delimiter = read_csv_bytes(raw)

    date_col = pick_column(
        fields,
        ("reference_timestamp", "timestamp", "date", "datum", "time"),
        ("timestamp", "date", "datum"),
    )

    present_params = [pid for pid in wanted_parameter_ids if pid in fields]

    dates = []
    value_ranges: dict[str, list[float]] = defaultdict(list)

    for row in rows:
        if date_col:
            d = parse_date_loose(row.get(date_col))
            if d:
                dates.append(d)

        for pid in present_params:
            raw_value = str(row.get(pid, "") or "").strip()
            if not raw_value:
                continue
            try:
                value = float(raw_value.replace(",", "."))
            except ValueError:
                continue
            if math.isfinite(value):
                value_ranges[pid].append(value)

    return {
        "fields": fields,
        "rows": len(rows),
        "delimiter": delimiter,
        "date_col": date_col,
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
        "present_params": present_params,
        "value_ranges": {
            pid: (min(values), max(values))
            for pid, values in value_ranges.items()
            if values
        },
    }


def summarize_parameter_rows(
    found: dict[str, list[dict[str, str]]],
    columns: dict[str, str | None],
) -> None:
    pid_col = columns["id"]
    desc_col = columns["description"]
    unit_col = columns["unit"]

    for kind in ("TMIN", "TMAX"):
        log(f"{kind}-Kandidaten: {len(found[kind])}")
        for row in found[kind][:10]:
            pid = row.get(pid_col, "") if pid_col else ""
            desc = row.get(desc_col, "") if desc_col else ""
            unit = row.get(unit_col, "") if unit_col else ""
            log(f"  {pid}: {desc} [{unit}]")


def inspect_collection(key: str) -> dict[str, Any]:
    config = COLLECTIONS[key]
    cid = config["id"]
    prefix = config["prefix"]

    log()
    log("=" * 72)
    log(f"{key}: {config['label']}")
    log("=" * 72)

    collection = get_json(f"{STAC_ROOT}/collections/{cid}")
    log(f"Collection ID: {collection.get('id')}")
    log(f"Titel: {collection.get('title')}")
    log(f"Lizenz: {collection.get('license')}")

    assets = collection_asset_urls(collection, prefix)
    params_url = find_meta_url(assets, f"{prefix}_meta_parameters.csv")
    stations_url = find_meta_url(assets, f"{prefix}_meta_stations.csv")
    inventory_url = find_meta_url(assets, f"{prefix}_meta_datainventory.csv")

    p_fields, p_rows, p_delim = read_csv_bytes(
        request_bytes(params_url, accept="text/csv,*/*")
    )
    s_fields, s_rows, s_delim = read_csv_bytes(
        request_bytes(stations_url, accept="text/csv,*/*")
    )
    i_fields, i_rows, i_delim = read_csv_bytes(
        request_bytes(inventory_url, accept="text/csv,*/*")
    )

    log(f"Parameter-Metadaten: {len(p_rows)} Zeilen | Trennzeichen {p_delim!r}")
    log(f"Stations-Metadaten: {len(s_rows)} Zeilen | Trennzeichen {s_delim!r}")
    log(f"Dateninventar: {len(i_rows)} Zeilen | Trennzeichen {i_delim!r}")
    log(f"Parameter-Spalten: {' | '.join(p_fields)}")
    log(f"Stations-Spalten: {' | '.join(s_fields)}")
    log(f"Inventar-Spalten: {' | '.join(i_fields)}")

    p_cols = parameter_columns(p_fields)
    s_cols = station_columns(s_fields)
    i_cols = inventory_columns(i_fields)

    log(f"Erkannte Parameterfelder: {p_cols}")
    log(f"Erkannte Stationsfelder: {s_cols}")
    log(f"Erkannte Inventarfelder: {i_cols}")

    found = discover_daily_temperature_parameters(p_rows, p_cols)
    summarize_parameter_rows(found, p_cols)

    tmin_ids = {
        str(row.get(p_cols["id"], "")).strip()
        for row in found["TMIN"]
        if p_cols["id"]
    }
    tmax_ids = {
        str(row.get(p_cols["id"], "")).strip()
        for row in found["TMAX"]
        if p_cols["id"]
    }

    if not tmin_ids or not tmax_ids:
        raise RuntimeError(
            f"{key}: tägliche Tmin/Tmax-Parameter wurden nicht zuverlässig erkannt."
        )

    all_temp_ids = tmin_ids | tmax_ids
    inv = inventory_for_parameters(i_rows, i_cols, all_temp_ids)

    station_meta = station_info(s_rows, s_cols)

    log()
    log("=== DATENINVENTAR TAGES-TEMPERATUR ===")
    log(f"Stationen mit Tmin/Tmax-Inventareinträgen: {len(inv['stations'])}")
    log(f"Frühester Inventarbeginn: {inv['earliest']}")
    log(f"Neuester Inventarstand: {inv['latest']}")
    for pid, stations in sorted(inv["by_param"].items()):
        log(f"  {pid}: {len(stations)} Stationen")

    both = set()
    for tn in tmin_ids:
        for tx in tmax_ids:
            both |= inv["by_param"].get(tn, set()) & inv["by_param"].get(tx, set())
    log(f"Stationen mit erkanntem täglichem Tmin UND Tmax: {len(both)}")

    items = stac_items(cid)
    log()
    log(f"STAC-Items: {len(items)}")

    preferred = [x for x in ("BER", "ZUR", "KLO", "GVE", "LUG", "SIA") if x in both]
    selected = choose_item_for_station(items, preferred or sorted(both))

    sample_info = None
    if selected:
        sid, item = selected
        meta = station_meta.get(sid, {})
        name_col = s_cols["name"]
        name = str(meta.get(name_col, "") or "") if name_col else ""
        log(f"Sample-Station: {sid} {name}".strip())

        daily_assets = []
        for asset_name, href in assets_for_item(item):
            asset_type = classify_daily_asset(asset_name, href)
            if asset_type:
                daily_assets.append((asset_type, asset_name, href))

        log(f"Daily-Assets an Sample-Station: {len(daily_assets)}")
        for asset_type, asset_name, href in daily_assets[:20]:
            log(f"  {asset_type}: {asset_name} -> {href}")

        # Prefer historical for proving long coverage; otherwise recent.
        daily_assets.sort(
            key=lambda x: (
                0 if x[0] == "historical" else
                1 if x[0] == "recent" else 2,
                x[1],
            )
        )

        if daily_assets:
            asset_type, asset_name, href = daily_assets[0]
            sample_info = inspect_sample_daily_csv(href, all_temp_ids)
            log()
            log(f"=== DAILY CSV SAMPLE ({asset_type}) ===")
            log(f"Asset: {asset_name}")
            log(f"Zeilen: {sample_info['rows']}")
            log(f"Trennzeichen: {sample_info['delimiter']!r}")
            log(f"Datumsspalte: {sample_info['date_col']}")
            log(f"CSV-Zeitraum: {sample_info['first_date']} bis {sample_info['last_date']}")
            log(f"Enthaltene Tmin/Tmax-Parameter: {sample_info['present_params']}")
            log(f"Wertebereiche: {sample_info['value_ranges']}")
            log(f"CSV-Spalten: {' | '.join(sample_info['fields'])}")
        else:
            log("WARNUNG: Kein tägliches historical/recent Asset am Sample-Item erkannt.")
    else:
        log("WARNUNG: Kein passendes Stations-STAC-Item gefunden.")

    return {
        "key": key,
        "collection_id": cid,
        "station_count": len(s_rows),
        "temp_station_count": len(inv["stations"]),
        "both_count": len(both),
        "earliest_inventory": inv["earliest"],
        "latest_inventory": inv["latest"],
        "tmin_ids": sorted(tmin_ids),
        "tmax_ids": sorted(tmax_ids),
        "sample": sample_info,
    }


def run_probe() -> None:
    log("=== METEOSWISS SCHWEIZ PROBE ===")
    log("SMN = beobachtete/qualitätsgeprüfte Stationswerte")
    log("NBCN = statistisch homogenisierte Klimareihen")
    log("Keine API-Keys/Secrets erforderlich.")

    smn = inspect_collection("SMN")
    nbcn = inspect_collection("NBCN")

    log()
    log("=" * 72)
    log("=== METEOSWISS SWITZERLAND PROBE SUMMARY ===")
    log("=" * 72)
    log(
        f"SMN: {smn['station_count']} Stations-Metadaten | "
        f"{smn['both_count']} Stationen mit erkanntem täglichem Tmin+Tmax | "
        f"Inventar ab {smn['earliest_inventory']} bis {smn['latest_inventory']}"
    )
    log(f"SMN Tmin-IDs: {smn['tmin_ids']}")
    log(f"SMN Tmax-IDs: {smn['tmax_ids']}")

    log(
        f"NBCN: {nbcn['station_count']} Stations-Metadaten | "
        f"{nbcn['both_count']} Stationen mit erkanntem täglichem Tmin+Tmax | "
        f"Inventar ab {nbcn['earliest_inventory']} bis {nbcn['latest_inventory']}"
    )
    log(f"NBCN Tmin-IDs: {nbcn['tmin_ids']}")
    log(f"NBCN Tmax-IDs: {nbcn['tmax_ids']}")

    log()
    log("Entscheidungsregel für den nächsten Schritt:")
    log(
        "1) Sind rohe SMN-Tagesextreme historisch lang genug, verwenden wir "
        "sie als primäre Rekordquelle."
    )
    log(
        "2) NBCN bleibt zunächst separat. Homogenisierte Tageswerte werden "
        "nicht automatisch mit beobachteten Tagesrekorden vermischt."
    )
    log(
        "3) Falls SMN bei alten Stationen große Lücken hat, prüfen wir gezielt, "
        "ob und wie NBCN transparent als historische Brücke geeignet ist."
    )
    log("MeteoSwiss Switzerland Probe OK.")


def self_test() -> None:
    fields = ["parameter", "description", "unit", "time_interval"]
    rows = [
        {
            "parameter": "tre200dn",
            "description": "Air temperature 2 m above ground; daily minimum",
            "unit": "°C",
            "time_interval": "daily",
        },
        {
            "parameter": "tre200dx",
            "description": "Air temperature 2 m above ground; daily maximum",
            "unit": "°C",
            "time_interval": "daily",
        },
        {
            "parameter": "tre200h0",
            "description": "Air temperature 2 m above ground; hourly mean",
            "unit": "°C",
            "time_interval": "hourly",
        },
    ]
    cols = parameter_columns(fields)
    found = discover_daily_temperature_parameters(rows, cols)
    assert len(found["TMIN"]) == 1
    assert len(found["TMAX"]) == 1
    assert found["TMIN"][0]["parameter"] == "tre200dn"
    assert found["TMAX"][0]["parameter"] == "tre200dx"

    csv_raw = (
        b"station_abbr;parameter;start_date;end_date\n"
        b"BER;tre200dn;1864-01-01;2026-08-09\n"
        b"BER;tre200dx;1864-01-01;2026-08-09\n"
    )
    f, r, d = read_csv_bytes(csv_raw)
    assert d == ";"
    ic = inventory_columns(f)
    inv = inventory_for_parameters(r, ic, {"tre200dn", "tre200dx"})
    assert inv["stations"] == {"BER"}
    assert inv["earliest"] == date(1864, 1, 1)

    item = {
        "id": "ogd-smn_ber",
        "assets": {
            "hist": {
                "href": "https://example/ogd-smn_ber_d_historical_2020-2029.csv"
            }
        },
    }
    assert item_station_id(item) == "BER"
    assert classify_daily_asset(
        "hist",
        "https://example/ogd-smn_ber_d_historical_2020-2029.csv",
    ) == "historical"

    print("MeteoSwiss Switzerland probe self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
    else:
        run_probe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
