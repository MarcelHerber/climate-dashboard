#!/usr/bin/env python3
"""
Belgium RMI/KMI Open Data probe for climate-dashboard station records.

The probe discovers the official GeoServer/WFS interface and inspects:
- aws:aws_station
- aws:aws_1day
- synop:synop_station
- synop:synop_data

Goals:
- verify daily TEMP_MAX / TEMP_MIN in aws_1day
- inspect station metadata fields and feature counts
- determine earliest/latest available AWS daily timestamps when WFS sorting works
- inspect SYNOP daily Tmin/Tmax as a possible historical bridge
- print enough schema/sample information to build a robust cache next

No API key / secret is required.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

UA = "climate-dashboard-rmi-belgium-probe/1.0"
TRIES = 5
TIMEOUT = 90

WFS_CANDIDATES = [
    "https://opendata.meteo.be/geoserver/ows",
    "https://opendata.meteo.be/geoserver/aws/ows",
    "https://opendata.meteo.be/geoserver/synop/ows",
]

EXPECTED = {
    "aws_station": ("aws:aws_station", "aws_station"),
    "aws_1day": ("aws:aws_1day", "aws_1day"),
    "synop_station": ("synop:synop_station", "synop_station"),
    "synop_data": ("synop:synop_data", "synop_data"),
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
        query = urllib.parse.urlencode(params, doseq=True)
        url = url + ("&" if "?" in url else "?") + query

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
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
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
            wait = min(20, 3 * attempt)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(str(last))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def get_capabilities(endpoint: str) -> tuple[bytes, list[str]]:
    raw = request_bytes(
        endpoint,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetCapabilities",
        },
        accept="application/xml,text/xml,*/*",
    )
    root = ET.fromstring(raw)
    names: list[str] = []
    for el in root.iter():
        if local_name(el.tag) != "FeatureType":
            continue
        for child in el:
            if local_name(child.tag) == "Name" and child.text:
                names.append(child.text.strip())
                break
    return raw, names


def discover_wfs() -> tuple[str, list[str]]:
    errors = []
    for endpoint in WFS_CANDIDATES:
        try:
            _, names = get_capabilities(endpoint)
            if names:
                return endpoint, names
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
    raise RuntimeError(
        "Kein RMI/KMI-WFS-Endpunkt erreichbar. " + " | ".join(errors)
    )


def resolve_layer(names: list[str], aliases: tuple[str, ...]) -> str | None:
    lower = {name.lower(): name for name in names}
    for alias in aliases:
        if alias.lower() in lower:
            return lower[alias.lower()]
    for name in names:
        tail = name.split(":")[-1].lower()
        for alias in aliases:
            if tail == alias.split(":")[-1].lower():
                return name
    return None


def describe_feature(endpoint: str, typename: str) -> list[tuple[str, str]]:
    raw = request_bytes(
        endpoint,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "DescribeFeatureType",
            "typeNames": typename,
        },
        accept="application/xml,text/xml,*/*",
    )
    root = ET.fromstring(raw)
    fields: list[tuple[str, str]] = []
    for el in root.iter():
        if local_name(el.tag) != "element":
            continue
        name = el.attrib.get("name")
        typ = el.attrib.get("type", "")
        if name:
            fields.append((name, typ))
    # preserve order, remove duplicates
    seen = set()
    out = []
    for item in fields:
        if item[0] not in seen:
            seen.add(item[0])
            out.append(item)
    return out


def get_features(
    endpoint: str,
    typename: str,
    *,
    count: int = 10,
    sort_by: str | None = None,
    cql_filter: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": typename,
        "outputFormat": "application/json",
        "count": count,
    }
    if sort_by:
        params["sortBy"] = sort_by
    if cql_filter:
        params["CQL_FILTER"] = cql_filter

    raw = request_bytes(
        endpoint,
        params=params,
        accept="application/json,*/*",
    )
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"{typename}: GeoJSON ist kein Objekt.")
    return obj


def feature_count(endpoint: str, typename: str) -> int | None:
    raw = request_bytes(
        endpoint,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": typename,
            "resultType": "hits",
        },
        accept="application/xml,text/xml,*/*",
    )
    root = ET.fromstring(raw)
    for key in ("numberMatched", "numberOfFeatures"):
        raw_value = root.attrib.get(key)
        if raw_value and str(raw_value).isdigit():
            return int(raw_value)
    return None


def feature_properties(payload: dict[str, Any]) -> list[dict[str, Any]]:
    features = payload.get("features") or []
    out = []
    if isinstance(features, list):
        for f in features:
            if isinstance(f, dict) and isinstance(f.get("properties"), dict):
                out.append(f["properties"])
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def choose_field(fields: list[str], candidates: tuple[str, ...]) -> str | None:
    mapping = {norm(x): x for x in fields}
    for candidate in candidates:
        if norm(candidate) in mapping:
            return mapping[norm(candidate)]
    for field in fields:
        n = norm(field)
        if any(norm(c) in n for c in candidates):
            return field
    return None


def infer_fields(
    schema: list[tuple[str, str]],
    samples: list[dict[str, Any]],
) -> dict[str, str | None]:
    fields = [x[0] for x in schema]
    for row in samples:
        fields.extend(k for k in row if k not in fields)

    date_candidates = (
        "timestamp", "datetime", "date", "time", "valid_time",
        "observation_time", "datetime_utc", "day",
    )
    station_candidates = (
        "station_id", "stationid", "station", "code", "id", "wmo",
    )

    # Schema types are very helpful for date discovery.
    date_from_type = None
    for name, typ in schema:
        t = typ.lower()
        if "date" in t or "time" in t:
            date_from_type = name
            break

    return {
        "date": date_from_type or choose_field(fields, date_candidates),
        "station": choose_field(fields, station_candidates),
        "tmax": choose_field(fields, ("TEMP_MAX", "temp_max", "tmax")),
        "tmin": choose_field(fields, ("TEMP_MIN", "temp_min", "tmin")),
        "name": choose_field(
            fields, ("station_name", "name", "stationname", "location")
        ),
        "elevation": choose_field(
            fields, ("elevation", "height", "altitude", "elev")
        ),
    }


def pretty_properties(row: dict[str, Any], max_fields: int = 30) -> str:
    items = list(row.items())[:max_fields]
    return json.dumps(dict(items), ensure_ascii=False, default=str)


def sorted_edge(
    endpoint: str,
    typename: str,
    date_field: str,
    direction: str,
) -> dict[str, Any] | None:
    # GeoServer commonly accepts "field A/D" with WFS 2.0.
    variants = [
        f"{date_field} {direction}",
        f"{date_field} {'ASC' if direction == 'A' else 'DESC'}",
    ]
    for sort_by in variants:
        try:
            payload = get_features(
                endpoint,
                typename,
                count=1,
                sort_by=sort_by,
            )
            rows = feature_properties(payload)
            if rows:
                return rows[0]
        except Exception:
            continue
    return None


def current_year_probe(
    endpoint: str,
    typename: str,
    date_field: str | None,
) -> tuple[dict[str, Any] | None, str]:
    year = datetime.utcnow().year
    if not date_field:
        return None, "kein Datumsfeld erkannt"

    filters = [
        f"{date_field} >= '{year}-01-01T00:00:00Z'",
        f"{date_field} >= '{year}-01-01'",
        f"{date_field} DURING {year}-01-01T00:00:00Z/{year}-12-31T23:59:59Z",
    ]
    for cql in filters:
        try:
            payload = get_features(
                endpoint,
                typename,
                count=3,
                sort_by=f"{date_field} D",
                cql_filter=cql,
            )
            rows = feature_properties(payload)
            if rows:
                return rows[0], cql
        except Exception:
            continue
    return None, "CQL-Current-Abfrage ohne Treffer/Unterstützung"


def inspect_layer(
    endpoint: str,
    typename: str,
    label: str,
) -> dict[str, Any]:
    log()
    log(f"=== {label}: {typename} ===")

    schema = describe_feature(endpoint, typename)
    log("Schema:")
    for name, typ in schema:
        log(f"  {name}: {typ}")

    total = None
    try:
        total = feature_count(endpoint, typename)
        log(f"Feature-Anzahl: {total if total is not None else 'unbekannt'}")
    except Exception as exc:
        log(f"WARNUNG Feature-Anzahl: {exc}")

    sample = get_features(endpoint, typename, count=5)
    rows = feature_properties(sample)
    log(f"Sample-Features: {len(rows)}")
    if rows:
        log(f"Sample-Eigenschaften: {pretty_properties(rows[0])}")

    inferred = infer_fields(schema, rows)
    log(f"Erkannte Felder: {inferred}")

    earliest = latest = None
    date_field = inferred["date"]
    if date_field:
        earliest = sorted_edge(endpoint, typename, date_field, "A")
        latest = sorted_edge(endpoint, typename, date_field, "D")
        if earliest:
            log(
                f"Frühester sortierter Treffer: "
                f"{date_field}={earliest.get(date_field)!r}"
            )
        else:
            log("Frühester sortierter Treffer: Sortierung nicht verfügbar.")
        if latest:
            log(
                f"Neuester sortierter Treffer: "
                f"{date_field}={latest.get(date_field)!r}"
            )
        else:
            log("Neuester sortierter Treffer: Sortierung nicht verfügbar.")

    return {
        "schema": schema,
        "total": total,
        "sample": rows,
        "fields": inferred,
        "earliest": earliest,
        "latest": latest,
    }


def run_probe() -> None:
    log("=== KMI/RMI BELGIEN PROBE ===")
    log("Quelle: Royal Meteorological Institute of Belgium Open Data")
    log("Keine API-Keys/Secrets erforderlich.")

    endpoint, names = discover_wfs()
    log(f"WFS-Endpunkt: {endpoint}")
    log(f"FeatureTypes im WFS: {len(names)}")

    resolved: dict[str, str | None] = {}
    for key, aliases in EXPECTED.items():
        resolved[key] = resolve_layer(names, aliases)
        log(f"{key}: {resolved[key] or 'NICHT GEFUNDEN'}")

    if not resolved["aws_station"] or not resolved["aws_1day"]:
        raise RuntimeError(
            "AWS-Stations- oder Tageslayer fehlt; Belgien-Probe kann nicht fortfahren."
        )

    aws_station = inspect_layer(
        endpoint,
        resolved["aws_station"],
        "AWS STATIONEN",
    )
    aws_day = inspect_layer(
        endpoint,
        resolved["aws_1day"],
        "AWS TAGESWERTE",
    )

    if not aws_day["fields"]["tmax"] or not aws_day["fields"]["tmin"]:
        raise RuntimeError(
            "aws_1day enthält im Live-Schema/Sample kein erkennbares TEMP_MAX + TEMP_MIN."
        )

    log()
    log("=== AWS CURRENT CHECK ===")
    current_row, current_filter = current_year_probe(
        endpoint,
        resolved["aws_1day"],
        aws_day["fields"]["date"],
    )
    if current_row:
        log(f"2026/aktuelles Jahr: Treffer mit Filter {current_filter}")
        log(f"Aktuellstes Sample: {pretty_properties(current_row)}")
    else:
        log(f"Aktueller-Jahr-Test: {current_filter}")

    synop_day = None
    synop_station = None
    if resolved["synop_station"]:
        try:
            synop_station = inspect_layer(
                endpoint,
                resolved["synop_station"],
                "SYNOP STATIONEN",
            )
        except Exception as exc:
            log(f"WARNUNG synop_station: {exc}")

    if resolved["synop_data"]:
        try:
            synop_day = inspect_layer(
                endpoint,
                resolved["synop_data"],
                "SYNOP DATEN",
            )
        except Exception as exc:
            log(f"WARNUNG synop_data: {exc}")

    log()
    log("=== KMI/RMI BELGIUM PROBE SUMMARY ===")
    log(f"WFS: {endpoint}")
    log(f"AWS station layer: {resolved['aws_station']}")
    log(f"AWS daily layer: {resolved['aws_1day']}")
    log(f"AWS TEMP_MAX field: {aws_day['fields']['tmax']}")
    log(f"AWS TEMP_MIN field: {aws_day['fields']['tmin']}")
    log(f"AWS date field: {aws_day['fields']['date']}")
    log(f"AWS station-id field: {aws_day['fields']['station']}")
    if aws_day["earliest"] and aws_day["fields"]["date"]:
        field = aws_day["fields"]["date"]
        log(f"AWS frühester Tageswert: {aws_day['earliest'].get(field)!r}")
    if aws_day["latest"] and aws_day["fields"]["date"]:
        field = aws_day["fields"]["date"]
        log(f"AWS neuester Tageswert: {aws_day['latest'].get(field)!r}")

    if synop_day:
        log(f"SYNOP TEMP_MAX field: {synop_day['fields']['tmax']}")
        log(f"SYNOP TEMP_MIN field: {synop_day['fields']['tmin']}")
        if synop_day["earliest"] and synop_day["fields"]["date"]:
            field = synop_day["fields"]["date"]
            log(f"SYNOP frühester Treffer: {synop_day['earliest'].get(field)!r}")

    log("KMI/RMI Belgium Probe OK.")


def self_test() -> None:
    schema = [
        ("fid", "xsd:int"),
        ("timestamp", "xsd:dateTime"),
        ("station_id", "xsd:string"),
        ("TEMP_MAX", "xsd:double"),
        ("TEMP_MIN", "xsd:double"),
    ]
    sample = [{
        "timestamp": "2026-08-09T00:00:00Z",
        "station_id": "06447",
        "TEMP_MAX": 28.1,
        "TEMP_MIN": 14.2,
    }]
    fields = infer_fields(schema, sample)
    assert fields["date"] == "timestamp"
    assert fields["station"] == "station_id"
    assert fields["tmax"] == "TEMP_MAX"
    assert fields["tmin"] == "TEMP_MIN"

    names = ["aws:aws_station", "aws:aws_1day", "synop:synop_data"]
    assert resolve_layer(names, ("aws:aws_1day", "aws_1day")) == "aws:aws_1day"

    print("KMI/RMI Belgium probe self-test OK")


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
