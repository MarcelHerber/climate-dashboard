#!/usr/bin/env python3
# Probe official Romanian ANM temperature sources.
# This step inspects only:
# - ANM current weather REST endpoint
# - ANM INSPIRE WFS capabilities / feature types
# - tiny WFS samples, looking specifically for M201 (CLIMAT)
#   daily Tmin/Tmax/mean-temperature observations
# - station/network metadata and linked observation URLs
# It does NOT build a historical cache and does NOT modify Europe output.

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any

SOURCE = "Administrația Națională de Meteorologie (ANM România)"
CURRENT_URL = "https://www.meteoromania.ro/wp-json/meteoapi/v2/starea-vremii"
WFS_BASE = "https://inspire.meteoromania.ro/WIGOS/WFS"
CAPABILITIES_URL = (
    WFS_BASE + "?service=WFS&version=2.0.0&request=GetCapabilities"
)
USER_AGENT = "climate-dashboard-anm-romania-probe/1.0"
TIMEOUT = 45
RETRIES = 3

NS = {
    "wfs": "http://www.opengis.net/wfs/2.0",
    "ows": "http://www.opengis.net/ows/1.1",
    "xlink": "http://www.w3.org/1999/xlink",
}


def fetch_bytes(url: str) -> tuple[bytes, dict[str, str], int]:
    last: Exception | None = None
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/xml, text/xml, */*",
    }
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read(), dict(resp.headers.items()), int(resp.status)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"Request failed: {url}: {last}")


def fetch_json(url: str) -> Any:
    body, _, _ = fetch_bytes(url)
    return json.loads(body.decode("utf-8-sig"))


def fetch_xml(url: str) -> tuple[ET.Element, bytes]:
    body, _, _ = fetch_bytes(url)
    try:
        return ET.fromstring(body), body
    except ET.ParseError as exc:
        sample = body[:500].decode("utf-8", "replace")
        raise RuntimeError(f"XML parse failed for {url}: {exc}; sample={sample!r}")


def compact_text(raw: bytes, limit: int = 2600) -> str:
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[:limit] + " ..."
    return text


def walk_lists(obj: Any, path: str = "$") -> list[tuple[str, list[Any]]]:
    out: list[tuple[str, list[Any]]] = []
    if isinstance(obj, list):
        out.append((path, obj))
        for i, item in enumerate(obj[:4]):
            out.extend(walk_lists(item, f"{path}[{i}]"))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            out.extend(walk_lists(value, f"{path}.{key}"))
    return out


def current_api_probe() -> None:
    print("=== ANM CURRENT REST API ===")
    obj = fetch_json(CURRENT_URL)
    print(f"Top-Level-Typ: {type(obj).__name__}")

    if isinstance(obj, dict):
        print("Top-Level-Keys:", ", ".join(sorted(map(str, obj.keys()))))
    lists = walk_lists(obj)
    if lists:
        path, rows = max(lists, key=lambda x: len(x[1]))
        print(f"Größte Liste: {path} | Einträge: {len(rows)}")
        samples = [x for x in rows[:2] if isinstance(x, (dict, list))]
        if samples:
            print("Beispiel aktuelle Daten:")
            print(json.dumps(samples, ensure_ascii=False, indent=2)[:5000])
    else:
        print("Keine Listenstruktur in der REST-Antwort gefunden.")
    print()


def feature_types(root: ET.Element) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for ft in root.findall(".//wfs:FeatureType", NS):
        name = (ft.findtext("wfs:Name", default="", namespaces=NS) or "").strip()
        title = (ft.findtext("wfs:Title", default="", namespaces=NS) or "").strip()
        abstract = (
            ft.findtext("wfs:Abstract", default="", namespaces=NS) or ""
        ).strip()
        if name:
            out.append({"name": name, "title": title, "abstract": abstract})
    return out


def getfeature_url(type_name: str, count: int = 2) -> str:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": type_name,
        "count": str(count),
    }
    return WFS_BASE + "?" + urllib.parse.urlencode(params)


def describe_url(type_name: str) -> str:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "DescribeFeatureType",
        "typeNames": type_name,
    }
    return WFS_BASE + "?" + urllib.parse.urlencode(params)


def xml_stats(root: ET.Element) -> dict[str, Any]:
    tags = Counter()
    hrefs: list[str] = []
    text_hits: list[str] = []
    needles = ("m201", "climat", "minimum", "maximum", "temperature", "tmin", "tmax")

    for elem in root.iter():
        local = elem.tag.split("}")[-1]
        tags[local] += 1

        for attr, value in elem.attrib.items():
            if attr.endswith("href") or attr == "href":
                hrefs.append(str(value))
            low = str(value).lower()
            if any(n in low for n in needles):
                text_hits.append(str(value))

        if elem.text:
            text = elem.text.strip()
            low = text.lower()
            if text and any(n in low for n in needles):
                text_hits.append(text)

    return {
        "top_tags": tags.most_common(20),
        "interesting_hrefs": sorted(
            {
                h
                for h in hrefs
                if any(n in h.lower() for n in ("m201", "climat", "observ"))
            }
        )[:30],
        "interesting_values": sorted(set(text_hits))[:50],
    }


def try_feature(type_name: str) -> dict[str, Any]:
    result: dict[str, Any] = {"type_name": type_name}

    try:
        droot, draw = fetch_xml(describe_url(type_name))
        result["describe_ok"] = True
        result["describe_sample"] = compact_text(draw, 1800)
        result["describe_stats"] = xml_stats(droot)
    except Exception as exc:
        result["describe_ok"] = False
        result["describe_error"] = str(exc)

    try:
        groot, graw = fetch_xml(getfeature_url(type_name, count=2))
        result["getfeature_ok"] = True
        result["numberMatched"] = groot.attrib.get("numberMatched")
        result["numberReturned"] = groot.attrib.get("numberReturned")
        result["sample"] = compact_text(graw, 3200)
        result["stats"] = xml_stats(groot)
    except Exception as exc:
        result["getfeature_ok"] = False
        result["getfeature_error"] = str(exc)

    return result


def wfs_probe() -> list[dict[str, Any]]:
    print("=== ANM INSPIRE WFS ===")
    root, raw = fetch_xml(CAPABILITIES_URL)
    print(f"GetCapabilities: OK | {len(raw):,} Bytes")

    types = feature_types(root)
    print(f"FeatureTypes: {len(types)}")
    for row in types:
        print(f"- {row['name']} | {row['title']}")
        if row["abstract"]:
            print(f"  {row['abstract'][:260]}")

    if not types:
        raise RuntimeError("Keine WFS FeatureTypes gefunden.")

    print()
    print("=== KLEINE WFS-SAMPLES ===")
    results: list[dict[str, Any]] = []
    for row in types:
        name = row["name"]
        print()
        print(f"--- {name} ---")
        result = try_feature(name)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2)[:9500])

    return results


def summarize(results: list[dict[str, Any]]) -> None:
    blob = json.dumps(results, ensure_ascii=False).lower()

    print()
    print("=== M201 / CLIMAT SUCHE ===")
    for needle in ("m201", "climat", "minimum", "maximum", "temperature"):
        print(f"{needle}: {'GEFUNDEN' if needle in blob else 'nicht gefunden'}")

    linked: list[str] = []
    for result in results:
        for section in ("stats", "describe_stats"):
            stats = result.get(section)
            if isinstance(stats, dict):
                linked.extend(stats.get("interesting_hrefs") or [])

    linked = sorted(set(map(str, linked)))
    if linked:
        print()
        print("Interessante verlinkte Observation-/CLIMAT-URLs:")
        for url in linked[:50]:
            print("-", url)

    print()
    print("=== FAZIT FÜR DIESEN PROBE-SCHRITT ===")
    if "m201" in blob or "climat" in blob:
        print(
            "M201/CLIMAT ist im maschinenlesbaren WFS-Pfad sichtbar. "
            "Nächster Schritt: konkrete Tageswerte + Zeitabdeckung je Station testen."
        )
    else:
        print(
            "M201/CLIMAT ist in den ersten WFS-Samples noch nicht direkt sichtbar. "
            "Dann nutzen wir die ausgegebenen Feature-/Link-Strukturen für einen gezielten zweiten Probe."
        )
    print("Noch KEIN historischer Cache gebaut.")


def self_test() -> None:
    xml = (
        b'<?xml version="1.0"?>'
        b'<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">'
        b'<wfs:FeatureTypeList><wfs:FeatureType>'
        b'<wfs:Name>ef:EnvironmentalMonitoringFacility</wfs:Name>'
        b'<wfs:Title>Stations</wfs:Title>'
        b'</wfs:FeatureType></wfs:FeatureTypeList>'
        b'</wfs:WFS_Capabilities>'
    )
    root = ET.fromstring(xml)
    rows = feature_types(root)
    assert rows[0]["name"] == "ef:EnvironmentalMonitoringFacility"
    assert "request=GetFeature" in getfeature_url("ef:EnvironmentalMonitoringFacility")
    obj = {"data": [{"temperature": 10}, {"temperature": 11}]}
    largest = max(walk_lists(obj), key=lambda x: len(x[1]))
    assert largest[1][0]["temperature"] == 10
    print("ANM Romania probe self-test OK.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    print("=== ANM RUMÄNIEN PROBE ===")
    print(f"Quelle: {SOURCE}")
    print(f"Current API: {CURRENT_URL}")
    print(f"WFS: {CAPABILITIES_URL}")
    print()

    current_api_probe()
    results = wfs_probe()
    summarize(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
