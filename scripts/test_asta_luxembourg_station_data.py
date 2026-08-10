#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html.parser
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

WFS_URL = "https://wms.inspire.geoportail.lu/geoserver/mf/wfs"
ASTA_METEOROLOGY_PAGE = "https://agriculture.public.lu/de/betrieb/meteorologie.html"
AGRIMETEO_HOME = "https://www.agrimeteo.lu/"
UA = "climate-dashboard-asta-luxembourg-probe/1.1"

ASTA_TMAX_LAYER_SUFFIX = "MF.PointTimeSeriesObservation_Daily_ASTA_max_ta200max"
ASTA_TMIN_LAYER_SUFFIX = "MF.PointTimeSeriesObservation_Daily_ASTA_min_ta200min"
ASTA_TMAX_VALUE_FIELD = "max_ta200max"
ASTA_TMIN_VALUE_FIELD = "min_ta200min"
TIMEOUT = 120
TRIES = 5


def log(msg: str = "") -> None:
    print(msg, flush=True)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def http_bytes(url: str, *, accept: str = "*/*") -> bytes:
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
                raw = response.read()
                if not raw:
                    raise RuntimeError("Leere HTTP-Antwort")
                return raw
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            RuntimeError,
        ) as exc:
            last = exc
            retryable = (
                not isinstance(exc, urllib.error.HTTPError)
                or exc.code in {408, 429, 500, 502, 503, 504}
            )
            if attempt >= TRIES or not retryable:
                raise
            wait = min(30, 3 * attempt)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)
    raise RuntimeError(str(last))


def wfs_url(params: dict[str, Any]) -> str:
    query = {"SERVICE": "WFS", "VERSION": "2.0.0", **params}
    return WFS_URL + "?" + urllib.parse.urlencode(query, doseq=True)


def get_capabilities() -> bytes:
    return http_bytes(
        wfs_url({"REQUEST": "GetCapabilities"}),
        accept="application/xml,text/xml,*/*",
    )


def parse_capabilities(raw: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(raw)
    layers = []
    for node in root.iter():
        if local(node.tag) != "FeatureType":
            continue
        fields: dict[str, str] = {}
        for child in list(node):
            lname = local(child.tag)
            if lname in {"Name", "Title", "Abstract"}:
                text = (child.text or "").strip()
                if text:
                    fields[lname.lower()] = text
        if fields.get("name"):
            layers.append(
                {
                    "name": fields["name"],
                    "title": fields.get("title", ""),
                    "abstract": fields.get("abstract", ""),
                }
            )
    return layers


def daily_asta_layers(layers: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for layer in layers:
        text = (
            layer.get("name", "") + " " +
            layer.get("title", "") + " " +
            layer.get("abstract", "")
        ).lower()
        if (
            "pointtimeseriesobservation_daily_asta" in text
            or "daily_asta" in text
            or ("asta" in text and "daily" in text and "pointtimeseries" in text)
        ):
            out.append(layer)
    out.sort(key=lambda x: x["name"].lower())
    return out


def exact_layer(
    layers: list[dict[str, str]],
    suffix: str,
) -> dict[str, str] | None:
    wanted = suffix.lower()
    for layer in layers:
        name = str(layer.get("name", "")).lower()
        if name == wanted or name.endswith(":" + wanted) or name.endswith(wanted):
            return layer
    return None


def score_temperature_layer(layer: dict[str, str], kind: str) -> int:
    text = (
        layer.get("name", "") + " " +
        layer.get("title", "") + " " +
        layer.get("abstract", "")
    ).lower()
    score = 0
    for token in ("ta200", "air temperature", "lufttemperatur", "temperature"):
        if token in text:
            score += 5

    if kind == "max":
        for token in (
            "max_ta200", "max ta200", "maximum air temperature",
            "daily maximum", "_max_", "max_", "maximum"
        ):
            if token in text:
                score += 10
        for bad in ("minimum", "_min_", "min_ta200"):
            if bad in text:
                score -= 20
    else:
        for token in (
            "min_ta200", "min ta200", "minimum air temperature",
            "daily minimum", "_min_", "min_", "minimum"
        ):
            if token in text:
                score += 10
        for bad in ("maximum", "_max_", "max_ta200"):
            if bad in text:
                score -= 20

    if "avg_ta200" in text or "average air temperature" in text:
        score -= 30
    return score


def candidate_layers(
    layers: list[dict[str, str]], kind: str
) -> list[tuple[int, dict[str, str]]]:
    scored = [(score_temperature_layer(layer, kind), layer) for layer in layers]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    return scored


def get_geojson(
    typename: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "SRSNAME": "EPSG:4326",
        "OUTPUTFORMAT": "application/json",
    }
    filters = []
    if start is not None:
        filters.append(f"datetime AFTER {start.isoformat()}T00:00:00Z")
    if end is not None:
        filters.append(f"datetime BEFORE {end.isoformat()}T23:59:59Z")
    if filters:
        params["CQL_FILTER"] = " AND ".join(filters)

    raw = http_bytes(wfs_url(params), accept="application/json,*/*")
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError("Unerwartete GeoJSON-Struktur.")
    return obj


def feature_properties(obj: dict[str, Any]) -> list[dict[str, Any]]:
    features = obj.get("features")
    if not isinstance(features, list):
        return []
    out = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        geom = feature.get("geometry")
        if not isinstance(props, dict):
            props = {}
        out.append(
            {
                "properties": props,
                "geometry": geom if isinstance(geom, dict) else None,
                "id": feature.get("id"),
            }
        )
    return out


def detect_key(
    rows: list[dict[str, Any]],
    candidates: tuple[str, ...],
) -> str | None:
    keys = Counter()
    for row in rows:
        for key in row["properties"]:
            keys[str(key)] += 1
    lower_map = {key.lower(): key for key in keys}

    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    for key in keys:
        lower = key.lower()
        if any(candidate.lower() in lower for candidate in candidates):
            return key
    return None


def parse_date_value(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_float(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def geometry_lon_lat(
    geometry: dict[str, Any] | None,
) -> tuple[float, float] | None:
    if not geometry:
        return None
    coords = geometry.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    try:
        lon = float(coords[0])
        lat = float(coords[1])
    except (TypeError, ValueError):
        return None
    if not (5.0 <= lon <= 7.5 and 49.0 <= lat <= 51.0):
        if 5.0 <= lat <= 7.5 and 49.0 <= lon <= 51.0:
            lon, lat = lat, lon
    return lon, lat


def summarize_geojson(
    typename: str,
    obj: dict[str, Any],
    *,
    expected_value_field: str | None = None,
) -> dict[str, Any]:
    rows = feature_properties(obj)
    name_key = detect_key(
        rows, ("name_descr", "station_name", "name", "station", "location")
    )
    id_key = detect_key(
        rows, ("station_id", "stationid", "id_station", "code", "localid")
    )
    date_key = detect_key(
        rows, ("datetime", "date", "phenomenon_time", "time")
    )
    value_key = None
    if expected_value_field:
        available = {
            str(key).lower(): str(key)
            for row in rows
            for key in row["properties"].keys()
        }
        value_key = available.get(expected_value_field.lower())

    if value_key is None:
        value_key = detect_key(
            rows, ("result", "value", "observation", "measurement", "val")
        )

    if value_key is None:
        # ASTA layers expose the measurement using the parameter code itself
        # (e.g. max_ta200max / min_ta200min), not a generic "value" field.
        ignored = {
            "datetime", "gml_identifier", "featureofinterest_xlink_href",
            "name_descr", "day", "geometry"
        }
        numeric_candidates = []
        for row in rows:
            for key, raw_value in row["properties"].items():
                if str(key).lower() in ignored:
                    continue
                if parse_float(raw_value) is not None:
                    numeric_candidates.append(str(key))
        if numeric_candidates:
            value_key = Counter(numeric_candidates).most_common(1)[0][0]

    stations, station_ids, coords = set(), set(), set()
    dates, values = [], []

    for row in rows:
        props = row["properties"]
        if name_key and props.get(name_key) not in (None, ""):
            stations.add(str(props[name_key]).strip())
        if id_key and props.get(id_key) not in (None, ""):
            station_ids.add(str(props[id_key]).strip())

        pos = geometry_lon_lat(row["geometry"])
        if pos:
            coords.add((round(pos[0], 6), round(pos[1], 6)))

        if date_key:
            d = parse_date_value(props.get(date_key))
            if d:
                dates.append(d)
        if value_key:
            x = parse_float(props.get(value_key))
            if x is not None:
                values.append(x)

    property_keys = sorted(
        {str(key) for row in rows for key in row["properties"].keys()}
    )

    return {
        "typename": typename,
        "feature_count": len(rows),
        "property_keys": property_keys,
        "name_key": name_key,
        "id_key": id_key,
        "date_key": date_key,
        "value_key": value_key,
        "station_names": sorted(stations),
        "station_ids": sorted(station_ids),
        "coordinate_count": len(coords),
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
        "min_value": min(values) if values else None,
        "max_value": max(values) if values else None,
    }


class LinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = " ".join(" ".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None
            self._text = []


def archive_links(url: str) -> list[tuple[str, str]]:
    raw = http_bytes(url, accept="text/html,*/*")
    parser = LinkParser()
    parser.feed(raw.decode("utf-8", errors="replace"))

    keywords = (
        "agrimeteo", "meteor", "meteo", "archiv", "archive",
        "jahr", "annuaire", "atlas", "original", "download",
        "daten", "donnée", "donnee"
    )
    extensions = (".zip", ".csv", ".txt", ".xls", ".xlsx", ".pdf", ".gml")

    wanted, seen = [], set()
    for href, label in parser.links:
        absolute = urllib.parse.urljoin(url, href)
        haystack = (absolute + " " + label).lower()
        if any(word in haystack for word in keywords) or any(
            ext in haystack for ext in extensions
        ):
            key = (absolute, label)
            if key not in seen:
                seen.add(key)
                wanted.append(key)
    return wanted


def probe_layer(
    typename: str,
    label: str,
    expected_value_field: str,
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    recent_end = today
    recent_start = today - timedelta(days=45)

    log()
    log(f"=== {label}: {typename} ===")
    log(f"Aktueller Probezeitraum: {recent_start} bis {recent_end}")

    current = get_geojson(typename, start=recent_start, end=recent_end)
    summary = summarize_geojson(
        typename,
        current,
        expected_value_field=expected_value_field,
    )

    log(f"Features: {summary['feature_count']:,}")
    log(
        "Erkannte Felder: "
        f"name={summary['name_key']} | id={summary['id_key']} | "
        f"date={summary['date_key']} | value={summary['value_key']}"
    )
    log(f"Property-Keys: {summary['property_keys']}")
    log(
        f"Stationen nach Name: {len(summary['station_names'])} | "
        f"Station-IDs: {len(summary['station_ids'])} | "
        f"Koordinaten: {summary['coordinate_count']}"
    )
    log(
        f"Datenzeitraum: {summary['first_date']} bis {summary['last_date']}"
    )
    log(
        f"Wertebereich im Sample: {summary['min_value']} bis "
        f"{summary['max_value']}"
    )

    if summary["station_names"]:
        log("Stations-Sample:")
        for name in summary["station_names"][:20]:
            log(f"  {name}")

    old_end = today - timedelta(days=700)
    old_start = old_end - timedelta(days=14)
    log(
        f"Historischer WFS-Probezeitraum (~700 Tage zurück): "
        f"{old_start} bis {old_end}"
    )

    try:
        old_obj = get_geojson(typename, start=old_start, end=old_end)
        old_summary = summarize_geojson(
            typename,
            old_obj,
            expected_value_field=expected_value_field,
        )
        log(
            f"Historischer Probe: {old_summary['feature_count']:,} Features | "
            f"{old_summary['first_date']} bis {old_summary['last_date']}"
        )
        summary["old_feature_count"] = old_summary["feature_count"]
        summary["old_first_date"] = old_summary["first_date"]
        summary["old_last_date"] = old_summary["last_date"]
    except Exception as exc:
        log(f"Historischer Probe abgelehnt/fehlgeschlagen: {exc}")
        summary["old_error"] = str(exc)

    return summary


def self_test() -> None:
    capabilities = b'''<?xml version="1.0"?>
<WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">
 <wfs:FeatureTypeList>
  <wfs:FeatureType>
   <wfs:Name>mf:MF.PointTimeSeriesObservation_Daily_ASTA_avg_ta200</wfs:Name>
   <wfs:Title>Daily average air temperature</wfs:Title>
  </wfs:FeatureType>
  <wfs:FeatureType>
   <wfs:Name>mf:MF.PointTimeSeriesObservation_Daily_ASTA_max_ta200max</wfs:Name>
   <wfs:Title>Daily maximum air temperature</wfs:Title>
  </wfs:FeatureType>
  <wfs:FeatureType>
   <wfs:Name>mf:MF.PointTimeSeriesObservation_Daily_ASTA_min_ta200min</wfs:Name>
   <wfs:Title>Daily minimum air temperature</wfs:Title>
  </wfs:FeatureType>
 </wfs:FeatureTypeList>
</WFS_Capabilities>'''

    layers = daily_asta_layers(parse_capabilities(capabilities))
    assert len(layers) == 3
    assert exact_layer(
        layers, ASTA_TMAX_LAYER_SUFFIX
    ) is not None
    assert exact_layer(
        layers, ASTA_TMIN_LAYER_SUFFIX
    ) is not None

    sample = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "f1",
                "properties": {
                    "name_descr": "Arsdorf",
                    "datetime": "2026-08-01T00:00:00Z",
                    "max_ta200max": 29.4,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [5.88, 49.86],
                },
            },
            {
                "id": "f2",
                "properties": {
                    "name_descr": "Remich",
                    "datetime": "2026-08-01T00:00:00Z",
                    "max_ta200max": 31.2,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [6.36, 49.54],
                },
            },
        ],
    }

    summary = summarize_geojson(
        "test",
        sample,
        expected_value_field="max_ta200max",
    )
    assert summary["feature_count"] == 2
    assert summary["name_key"] == "name_descr"
    assert summary["date_key"] == "datetime"
    assert summary["value_key"] == "max_ta200max"
    assert len(summary["station_names"]) == 2
    assert summary["max_value"] == 31.2
    print("ASTA Luxembourg probe self-test OK")


def probe() -> None:
    log("=== ASTA / AGRIMETEO LUXEMBURG PROBE ===")
    log("Quelle: offizielles Luxemburg INSPIRE GeoServer WFS")
    log("Ziel: zusätzliche ASTA-Stationen; Findel bleibt bei GHCN.")
    log("Keine API-Keys/Secrets erforderlich.")

    log()
    log("=== WFS GETCAPABILITIES ===")
    raw = get_capabilities()
    all_layers = parse_capabilities(raw)
    asta_daily = daily_asta_layers(all_layers)

    log(f"FeatureTypes insgesamt: {len(all_layers)}")
    log(f"ASTA Daily FeatureTypes: {len(asta_daily)}")

    if not asta_daily:
        raise RuntimeError(
            "Keine ASTA-Daily-Layer in den WFS-Capabilities gefunden."
        )

    log("ASTA-Daily-Layer:")
    for layer in asta_daily:
        log(
            f"  {layer['name']} | title={layer['title']} | "
            f"abstract={layer['abstract'][:180]}"
        )

    max_candidates = candidate_layers(asta_daily, "max")
    min_candidates = candidate_layers(asta_daily, "min")

    log()
    log("TMAX-Kandidaten (nur Diagnose):")
    for score, layer in max_candidates[:8]:
        log(f"  Score {score:>3}: {layer['name']} | {layer['title']}")

    log("TMIN-Kandidaten (nur Diagnose):")
    for score, layer in min_candidates[:8]:
        log(f"  Score {score:>3}: {layer['name']} | {layer['title']}")

    tmax_exact = exact_layer(asta_daily, ASTA_TMAX_LAYER_SUFFIX)
    tmin_exact = exact_layer(asta_daily, ASTA_TMIN_LAYER_SUFFIX)

    if tmax_exact is None:
        raise RuntimeError(
            "Offizieller ASTA-TMAX-2m-Layer fehlt: "
            + ASTA_TMAX_LAYER_SUFFIX
        )
    if tmin_exact is None:
        raise RuntimeError(
            "Offizieller ASTA-TMIN-2m-Layer fehlt: "
            + ASTA_TMIN_LAYER_SUFFIX
        )

    tmax_layer = tmax_exact["name"]
    tmin_layer = tmin_exact["name"]

    log()
    log(f"Verwende TMAX fest: {tmax_layer} -> {ASTA_TMAX_VALUE_FIELD}")
    log(f"Verwende TMIN fest: {tmin_layer} -> {ASTA_TMIN_VALUE_FIELD}")

    tmax_summary = probe_layer(
        tmax_layer, "TMAX", ASTA_TMAX_VALUE_FIELD
    )
    tmin_summary = probe_layer(
        tmin_layer, "TMIN", ASTA_TMIN_VALUE_FIELD
    )

    log()
    log("=== OFFIZIELLE ASTA-ARCHIVSEITE ===")
    try:
        links = archive_links(ASTA_METEOROLOGY_PAGE)
        log(f"Relevante Links auf Landwirtschaftsportal: {len(links)}")
        for href, label in links[:60]:
            log(f"  {label or '(ohne Linktext)'} -> {href}")
    except Exception as exc:
        links = []
        log(f"Archivseite konnte nicht ausgewertet werden: {exc}")

    log()
    log("=== AGRIMETEO HOMEPAGE ===")
    try:
        agri_links = archive_links(AGRIMETEO_HOME)
        log(f"Relevante AgriMeteo-Links: {len(agri_links)}")
        for href, label in agri_links[:60]:
            log(f"  {label or '(ohne Linktext)'} -> {href}")
    except Exception as exc:
        agri_links = []
        log(f"AgriMeteo-Seite konnte nicht ausgewertet werden: {exc}")

    log()
    log("=" * 76)
    log("=== ASTA LUXEMBOURG PROBE SUMMARY ===")
    log("=" * 76)
    log(f"TMAX-Layer: {tmax_layer}")
    log(f"TMIN-Layer: {tmin_layer}")
    log(
        f"TMAX recent: {tmax_summary['feature_count']:,} Features | "
        f"{len(tmax_summary['station_names'])} Stationsnamen | "
        f"{tmax_summary['first_date']} bis {tmax_summary['last_date']}"
    )
    log(
        f"TMIN recent: {tmin_summary['feature_count']:,} Features | "
        f"{len(tmin_summary['station_names'])} Stationsnamen | "
        f"{tmin_summary['first_date']} bis {tmin_summary['last_date']}"
    )
    log(
        f"TMAX ~700 Tage zurück: "
        f"{tmax_summary.get('old_feature_count', 'Fehler')}"
    )
    log(
        f"TMIN ~700 Tage zurück: "
        f"{tmin_summary.get('old_feature_count', 'Fehler')}"
    )
    log(
        f"Archiv-/Download-Linktreffer: "
        f"Landwirtschaftsportal={len(links)} | AgriMeteo={len(agri_links)}"
    )
    log(
        "Nächster Schritt: Current direkt aus WFS, ältere Historie aus "
        "ASTA-Originaldaten/Jahrbüchern sofern maschinenlesbar auffindbar."
    )
    log("ASTA Luxembourg Probe OK.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        probe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
