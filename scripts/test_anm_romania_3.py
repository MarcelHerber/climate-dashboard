#!/usr/bin/env python3
# Third Romanian ANM probe: resolve the N201/CLIMAT observation graph.
#
# This step:
# - reads the discovered N201 CLIMAT network endpoint
# - inspects ALL links and feature identifiers
# - finds N201 in the EnvironmentalMonitoringNetwork WFS collection
# - follows N201 station-member links
# - follows only ANM-local CLIMAT / observation links from a small station sample
# - tries standard WFS ResourceId lookups for discovered ids
# - reports time strings, observed-property links and possible Tmin/Tmax payloads
#
# It does NOT build a cache.

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, deque
from typing import Any

BASE = "https://inspire.meteoromania.ro"
WFS = BASE + "/WIGOS/WFS"
N201_URL = (
    BASE
    + "/ids/OM_Observation.EnvironmentalMonitoringNetwork.N201.CLIMATComposed.BUFR"
)
USER_AGENT = "climate-dashboard-anm-romania-probe3/1.0"
TIMEOUT = 60
RETRIES = 3
MAX_BYTES = 30 * 1024 * 1024
MAX_FOLLOW = 50

KEYWORDS = (
    "n201",
    "m201",
    "climat",
    "bufr201",
    "temperature",
    "minimum",
    "maximum",
    "tmin",
    "tmax",
    "phenomenontime",
    "resulttime",
    "observedproperty",
    "observation",
)

DATE_RE = re.compile(
    r"\b(?:18|19|20)\d{2}[-/]\d{2}[-/]\d{2}"
    r"(?:[T ][0-2]\d:[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)


def get(url: str) -> tuple[bytes, dict[str, str], int]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/gml+xml,application/xml,text/xml,application/json,*/*",
    }
    last: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise RuntimeError(f"Antwort > {MAX_BYTES:,} Bytes: {url}")
                return raw, dict(resp.headers.items()), int(resp.status)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"Request fehlgeschlagen: {url}: {last}")


def parse_xml(raw: bytes, url: str) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        sample = raw[:800].decode("utf-8", "replace")
        raise RuntimeError(f"XML-Parsefehler {url}: {exc}; sample={sample!r}")


def local(tag: str) -> str:
    return tag.split("}")[-1]


def all_hrefs(root: ET.Element) -> list[str]:
    out: set[str] = set()
    for elem in root.iter():
        for key, value in elem.attrib.items():
            if key.endswith("href") or key == "href":
                v = str(value).strip()
                if v:
                    out.add(v)
    return sorted(out)


def gml_ids(root: ET.Element) -> list[str]:
    out: set[str] = set()
    for elem in root.iter():
        for key, value in elem.attrib.items():
            if key.endswith("}id") or key == "id":
                v = str(value).strip()
                if v:
                    out.add(v)
    return sorted(out)


def dates_from_raw(raw: bytes) -> list[str]:
    return sorted(set(DATE_RE.findall(raw.decode("utf-8", "replace"))))


def tag_counts(root: ET.Element) -> list[tuple[str, int]]:
    counts = Counter(local(elem.tag) for elem in root.iter())
    return counts.most_common(40)


def interesting_lines(raw: bytes, limit: int = 120) -> list[str]:
    text = raw.decode("utf-8", "replace")
    chunks = re.split(r"[\r\n]+", text)
    out: list[str] = []
    for chunk in chunks:
        low = chunk.lower()
        if any(k in low for k in KEYWORDS):
            cleaned = re.sub(r"\s+", " ", chunk).strip()
            if cleaned:
                out.append(cleaned[:1800])
    return out[:limit]


def summarize_xml(url: str, raw: bytes, root: ET.Element) -> dict[str, Any]:
    hrefs = all_hrefs(root)
    return {
        "url": url,
        "bytes": len(raw),
        "root": local(root.tag),
        "root_attributes": dict(root.attrib),
        "tag_counts": tag_counts(root),
        "gml_ids": gml_ids(root)[:120],
        "dates": dates_from_raw(raw)[:200],
        "interesting_lines": interesting_lines(raw),
        "interesting_hrefs": [
            h
            for h in hrefs
            if any(k in h.lower() for k in KEYWORDS)
            or "/ids/" in h.lower()
        ][:250],
        "all_href_count": len(hrefs),
    }


def wfs_url(**params: str) -> str:
    return WFS + "?" + urllib.parse.urlencode(params)


def fetch_network_collection() -> tuple[bytes, ET.Element]:
    url = wfs_url(
        service="WFS",
        version="2.0.0",
        request="GetFeature",
        typeNames="ef:EnvironmentalMonitoringNetwork",
        count="5000",
    )
    raw, _, _ = get(url)
    return raw, parse_xml(raw, url)


def elements_containing(root: ET.Element, needles: tuple[str, ...]) -> list[ET.Element]:
    out: list[ET.Element] = []
    for elem in root.iter():
        blob = ET.tostring(elem, encoding="unicode").lower()
        if any(n in blob for n in needles):
            out.append(elem)
    return out


def find_n201_member_links(root: ET.Element) -> list[str]:
    links: set[str] = set()
    for elem in root.iter():
        subtree_text = ET.tostring(elem, encoding="unicode").lower()
        if "n201" not in subtree_text and "climat" not in subtree_text:
            continue
        for sub in elem.iter():
            for key, value in sub.attrib.items():
                if key.endswith("href") or key == "href":
                    v = str(value)
                    if "/ids/" in v or "facility" in v.lower() or "station" in v.lower():
                        links.add(v)
    return sorted(links)


def classify_link(url: str) -> str:
    low = url.lower()
    if any(x in low for x in ("climat", "n201", "m201", "bufr201")):
        return "CLIMAT"
    if "om_observation" in low or "observation" in low:
        return "OBS"
    if "environmentalmonitoringfacility" in low:
        return "FACILITY"
    if "observedproperty" in low:
        return "PROPERTY"
    return "OTHER"


def safe_follow(url: str) -> dict[str, Any]:
    if not url.startswith(BASE):
        return {"url": url, "skipped": "extern"}

    try:
        raw, headers, status = get(url)
        result: dict[str, Any] = {
            "url": url,
            "class": classify_link(url),
            "status": status,
            "content_type": headers.get("Content-Type"),
            "bytes": len(raw),
        }
        ctype = (headers.get("Content-Type") or "").lower()

        if "json" in ctype:
            obj = json.loads(raw.decode("utf-8-sig"))
            result["json_type"] = type(obj).__name__
            result["sample"] = json.dumps(obj, ensure_ascii=False)[:3500]
            result["dates"] = dates_from_raw(raw)[:100]
            return result

        root = parse_xml(raw, url)
        result["xml"] = summarize_xml(url, raw, root)
        return result
    except Exception as exc:
        return {"url": url, "class": classify_link(url), "error": str(exc)}


def resource_id_candidates(ids: list[str]) -> list[str]:
    urls: list[str] = []
    for rid in ids[:30]:
        urls.append(
            wfs_url(
                service="WFS",
                version="2.0.0",
                request="GetFeature",
                resourceID=rid,
            )
        )
    return urls


def recursive_climat_follow(seed_urls: list[str]) -> list[dict[str, Any]]:
    queue = deque((url, 0) for url in seed_urls)
    seen: set[str] = set()
    results: list[dict[str, Any]] = []

    while queue and len(results) < MAX_FOLLOW:
        url, depth = queue.popleft()
        if url in seen:
            continue
        seen.add(url)

        result = safe_follow(url)
        results.append(result)

        if depth >= 2:
            continue

        xml_info = result.get("xml")
        if not isinstance(xml_info, dict):
            continue

        for href in xml_info.get("interesting_hrefs") or []:
            if not isinstance(href, str) or not href.startswith(BASE):
                continue
            low = href.lower()
            if any(
                token in low
                for token in (
                    "n201",
                    "m201",
                    "climat",
                    "bufr201",
                    "om_observation",
                    "environmentalmonitoringfacility",
                    "observedproperty",
                )
            ):
                queue.append((href, depth + 1))

    return results


def self_test() -> None:
    xml = (
        b'<root xmlns:xlink="http://www.w3.org/1999/xlink">'
        b'<a xlink:href="https://inspire.meteoromania.ro/ids/N201.CLIMAT"/>'
        b'<b>2020-01-02T00:00:00Z</b>'
        b'</root>'
    )
    root = ET.fromstring(xml)
    assert "https://inspire.meteoromania.ro/ids/N201.CLIMAT" in all_hrefs(root)
    assert dates_from_raw(xml) == ["2020-01-02T00:00:00Z"]
    assert classify_link("https://x/CLIMAT") == "CLIMAT"
    print("ANM Romania probe 3 self-test OK.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    print("=== ANM RUMÄNIEN PROBE 3 ===")
    print("N201/CLIMAT Observation-Graph und Stationsmitglieder")
    print()

    print("=== 1. DIREKTER N201-ENDPUNKT ===")
    raw, headers, status = get(N201_URL)
    n201_root = parse_xml(raw, N201_URL)
    n201_summary = summarize_xml(N201_URL, raw, n201_root)
    n201_summary["status"] = status
    n201_summary["content_type"] = headers.get("Content-Type")
    print(json.dumps(n201_summary, ensure_ascii=False, indent=2)[:22000])

    print()
    print("=== 2. ENVIRONMENTAL MONITORING NETWORK VOLLSTÄNDIG ===")
    net_raw, net_root = fetch_network_collection()
    print(f"Network-Collection: {len(net_raw):,} Bytes")
    print("root attrs:", json.dumps(dict(net_root.attrib), ensure_ascii=False))

    n201_elements = elements_containing(net_root, ("n201", "climat"))
    print(f"Elemente mit N201/CLIMAT: {len(n201_elements)}")

    member_links = find_n201_member_links(net_root)
    print(f"N201-nahe Member-/Facility-Links: {len(member_links)}")
    for url in member_links[:100]:
        print("-", url)

    print()
    print("=== 3. N201/CLIMAT-LINKS AUS DIREKTEM ENDPOINT ===")
    direct_links = [
        h for h in all_hrefs(n201_root)
        if h.startswith(BASE)
    ]
    for url in direct_links[:150]:
        print(f"- [{classify_link(url)}] {url}")

    seeds: list[str] = []
    for url in direct_links + member_links:
        if not url.startswith(BASE):
            continue
        cls = classify_link(url)
        if cls in {"CLIMAT", "OBS", "FACILITY", "PROPERTY"}:
            seeds.append(url)

    seeds = list(dict.fromkeys(seeds))[:25]

    print()
    print("=== 4. RELEVANTE LINKS VERFOLGEN ===")
    followed = recursive_climat_follow(seeds)
    for idx, result in enumerate(followed, start=1):
        print()
        print(f"--- Follow {idx}/{len(followed)} ---")
        print(json.dumps(result, ensure_ascii=False, indent=2)[:12000])

    print()
    print("=== 5. RESOURCE-ID TESTS ===")
    ids = gml_ids(n201_root)
    for result in followed:
        xml_info = result.get("xml")
        if isinstance(xml_info, dict):
            ids.extend(xml_info.get("gml_ids") or [])
    ids = list(dict.fromkeys(map(str, ids)))

    print(f"Gefundene IDs: {len(ids)}")
    for rid in ids[:60]:
        print("-", rid)

    rid_results: list[dict[str, Any]] = []
    for url in resource_id_candidates(ids)[:20]:
        res = safe_follow(url)
        rid_results.append(res)
        print(json.dumps(res, ensure_ascii=False, indent=2)[:8000])

    print()
    print("=== 6. ZEIT-/TEMPERATUR-SUCHE GESAMT ===")
    blob = json.dumps(
        {
            "n201": n201_summary,
            "followed": followed,
            "resource_ids": rid_results,
        },
        ensure_ascii=False,
    ).lower()

    for needle in (
        "phenomenontime",
        "resulttime",
        "observedproperty",
        "temperature",
        "minimum",
        "maximum",
        "tmin",
        "tmax",
        "bufr201",
        "climat",
    ):
        print(f"{needle}: {'GEFUNDEN' if needle in blob else 'nicht gefunden'}")

    all_dates: set[str] = set(n201_summary.get("dates") or [])
    for result in followed + rid_results:
        xml_info = result.get("xml")
        if isinstance(xml_info, dict):
            all_dates.update(xml_info.get("dates") or [])
        all_dates.update(result.get("dates") or [])

    dates = sorted(all_dates)
    print(f"Gefundene Datums-/Zeitwerte: {len(dates)}")
    if dates:
        print("Erstes Datum:", dates[0])
        print("Letztes Datum:", dates[-1])
        print("Erste 30:")
        for d in dates[:30]:
            print("-", d)
        print("Letzte 30:")
        for d in dates[-30:]:
            print("-", d)

    print()
    print("=== FAZIT ===")
    if dates and ("minimum" in blob or "maximum" in blob or "bufr201" in blob):
        print(
            "CLIMAT-Observationen mit Zeitbezug sind erreichbar. "
            "Nächster Schritt: Wertefelder dekodieren und Stations-/Zeitabdeckung bestimmen."
        )
    elif followed:
        print(
            "CLIMAT-Linkgraph ist erreichbar, aber die konkreten Tageswerte sind noch "
            "nicht eindeutig dekodiert. Bitte diesen Log schicken; die ausgegebenen IDs/Links "
            "reichen für den nächsten gezielten Decoder-Probe."
        )
    else:
        print(
            "Der N201-Endpunkt existiert, exponiert aber keine weiterverfolgbaren "
            "Stations-/Observation-Links im aktuellen INSPIRE-Payload."
        )

    print("Noch KEIN historischer Cache gebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
