#!/usr/bin/env python3
# Second Romanian ANM INSPIRE probe.
#
# Goal:
# - scan ALL small WFS station/network feature collections, not only first 2 rows
# - list/describe WFS stored queries
# - search exhaustively for N201/M201/CLIMAT/BUFR201 references
# - follow only a small number of discovered relevant URLs
# - test conservative N301->N201 / AEROS->CLIMAT analogues from discovered ANM URLs
#
# No historical cache is built.

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

WFS_BASE = "https://inspire.meteoromania.ro/WIGOS/WFS"
USER_AGENT = "climate-dashboard-anm-romania-probe2/1.0"
TIMEOUT = 60
RETRIES = 3
MAX_RESPONSE_BYTES = 30 * 1024 * 1024

NS = {
    "wfs": "http://www.opengis.net/wfs/2.0",
}

NEEDLES = (
    "m201", "n201", "climat", "bufr201",
    "minimum", "maximum", "tmin", "tmax",
    "daily minimum", "daily maximum",
)


def request_bytes(url: str) -> tuple[bytes, dict[str, str], int]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/xml,text/xml,application/gml+xml,application/json,*/*",
    }
    last: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise RuntimeError(
                        f"Antwort größer als Sicherheitslimit {MAX_RESPONSE_BYTES:,} Bytes: {url}"
                    )
                return data, dict(resp.headers.items()), int(resp.status)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"Request fehlgeschlagen: {url}: {last}")


def xml_request(url: str) -> tuple[ET.Element, bytes]:
    raw, _, _ = request_bytes(url)
    try:
        return ET.fromstring(raw), raw
    except ET.ParseError as exc:
        sample = raw[:600].decode("utf-8", "replace")
        raise RuntimeError(f"Kein parsebares XML: {exc}; sample={sample!r}")


def params_url(**params: str) -> str:
    return WFS_BASE + "?" + urllib.parse.urlencode(params)


def capabilities() -> tuple[ET.Element, bytes]:
    return xml_request(
        params_url(service="WFS", version="2.0.0", request="GetCapabilities")
    )


def feature_types(root: ET.Element) -> list[str]:
    out: list[str] = []
    for node in root.findall(".//wfs:FeatureType/wfs:Name", NS):
        if node.text and node.text.strip():
            out.append(node.text.strip())
    return out


def matches(raw: bytes) -> list[str]:
    text = raw.decode("utf-8", "replace")
    found: list[str] = []
    for line in re.split(r"[\r\n]+", text):
        low = line.lower()
        if any(n in low for n in NEEDLES):
            line2 = re.sub(r"\s+", " ", line).strip()
            if line2:
                found.append(line2[:1200])
    return found[:120]


def all_hrefs(root: ET.Element) -> list[str]:
    out: list[str] = []
    for elem in root.iter():
        for key, value in elem.attrib.items():
            if key.endswith("href") or key == "href":
                out.append(str(value))
    return sorted(set(out))


def relevant_hrefs(root: ET.Element) -> list[str]:
    out: list[str] = []
    for href in all_hrefs(root):
        low = href.lower()
        if any(x in low for x in ("201", "climat", "observation", "observedproperty", "bufr")):
            out.append(href)
    return out


def scan_feature(type_name: str) -> dict[str, Any]:
    url = params_url(
        service="WFS",
        version="2.0.0",
        request="GetFeature",
        typeNames=type_name,
        count="5000",
    )
    root, raw = xml_request(url)
    return {
        "type_name": type_name,
        "bytes": len(raw),
        "numberMatched": root.attrib.get("numberMatched"),
        "numberReturned": root.attrib.get("numberReturned"),
        "matches": matches(raw),
        "relevant_hrefs": relevant_hrefs(root)[:250],
    }


def probe_stored_queries() -> dict[str, Any]:
    result: dict[str, Any] = {}
    list_url = params_url(
        service="WFS",
        version="2.0.0",
        request="ListStoredQueries",
    )
    try:
        lroot, lraw = xml_request(list_url)
        result["list_ok"] = True
        result["list_bytes"] = len(lraw)

        ids: list[str] = []
        for elem in lroot.iter():
            if elem.tag.split("}")[-1] == "StoredQuery":
                sqid = elem.attrib.get("id")
                if sqid:
                    ids.append(sqid)

        result["ids"] = ids
        result["list_matches"] = matches(lraw)

        described: dict[str, Any] = {}
        for sqid in ids[:30]:
            durl = params_url(
                service="WFS",
                version="2.0.0",
                request="DescribeStoredQueries",
                storedQueryId=sqid,
            )
            try:
                _, draw = xml_request(durl)
                described[sqid] = {
                    "bytes": len(draw),
                    "matches": matches(draw),
                    "sample": re.sub(
                        r"\s+", " ", draw.decode("utf-8", "replace")
                    )[:2200],
                }
            except Exception as exc:
                described[sqid] = {"error": str(exc)}
        result["described"] = described

    except Exception as exc:
        result["list_ok"] = False
        result["error"] = str(exc)

    return result


def candidate_urls_from_discovered(hrefs: list[str]) -> list[str]:
    candidates: set[str] = set()
    for href in hrefs:
        low = href.lower()
        if "n301" in low or "aeros" in low or "bufr301" in low:
            for network_code in ("N201", "M201"):
                cand = href
                replacements = (
                    ("N301", network_code),
                    ("n301", network_code.lower()),
                    ("AEROS", "CLIMAT"),
                    ("aeros", "climat"),
                    ("BUFR301", "BUFR201"),
                    ("bufr301", "bufr201"),
                )
                for old, new in replacements:
                    cand = cand.replace(old, new)
                if cand != href:
                    candidates.add(cand)
    return sorted(candidates)[:20]


def inspect_url(url: str) -> dict[str, Any]:
    try:
        raw, headers, status = request_bytes(url)
        text = raw.decode("utf-8", "replace")
        return {
            "url": url,
            "ok": True,
            "status": status,
            "bytes": len(raw),
            "content_type": headers.get("Content-Type"),
            "matches": matches(raw),
            "sample": re.sub(r"\s+", " ", text)[:2500],
        }
    except Exception as exc:
        return {"url": url, "ok": False, "error": str(exc)}


def self_test() -> None:
    raw = b'<x href="https://example/N301/AEROS/BUFR301">temperature</x>'
    root = ET.fromstring(raw)
    hrefs = all_hrefs(root)
    cands = candidate_urls_from_discovered(hrefs)
    assert hrefs == ["https://example/N301/AEROS/BUFR301"]
    assert any("N201" in x and "CLIMAT" in x and "BUFR201" in x for x in cands)
    assert "climat" in NEEDLES
    print("ANM Romania probe 2 self-test OK.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    print("=== ANM RUMÄNIEN PROBE 2 ===")
    print("Vollscan der WFS-Stations-/Netzstruktur + Stored Queries")
    print()

    cap_root, cap_raw = capabilities()
    types = feature_types(cap_root)

    print(f"GetCapabilities: {len(cap_raw):,} Bytes")
    print(f"FeatureTypes: {len(types)}")
    for t in types:
        print("-", t)

    print()
    print("=== STORED QUERIES ===")
    stored = probe_stored_queries()
    print(json.dumps(stored, ensure_ascii=False, indent=2)[:18000])

    print()
    print("=== VOLLSTÄNDIGE FEATURE-SCANS ===")
    scans: list[dict[str, Any]] = []
    discovered_hrefs: set[str] = set()

    for i, type_name in enumerate(types, start=1):
        print()
        print(f"--- {i}/{len(types)} {type_name} ---")
        try:
            result = scan_feature(type_name)
            scans.append(result)
            discovered_hrefs.update(result.get("relevant_hrefs") or [])
            print(
                f"bytes={result['bytes']:,} "
                f"matched={result['numberMatched']} "
                f"returned={result['numberReturned']}"
            )

            if result["matches"]:
                print("Treffer M201/CLIMAT/Tmin/Tmax:")
                for line in result["matches"][:40]:
                    print(line)
            else:
                print("Keine direkten M201/CLIMAT/Tmin/Tmax-Treffer.")

            if result["relevant_hrefs"]:
                print("Relevante hrefs:")
                for href in result["relevant_hrefs"][:80]:
                    print("-", href)

        except Exception as exc:
            scans.append({"type_name": type_name, "error": str(exc)})
            print("FEHLER:", exc)

    full_blob = json.dumps(
        {"stored": stored, "scans": scans},
        ensure_ascii=False,
    ).lower()

    print()
    print("=== GESAMT-SUCHE ===")
    for needle in (
        "m201", "n201", "climat", "bufr201",
        "minimum", "maximum", "tmin", "tmax",
    ):
        print(f"{needle}: {'GEFUNDEN' if needle in full_blob else 'nicht gefunden'}")

    relevant_201 = [
        h for h in sorted(discovered_hrefs)
        if any(x in h.lower() for x in ("m201", "n201", "climat", "bufr201"))
    ]

    if relevant_201:
        print()
        print("=== DIREKT GEFUNDENE M201/N201/CLIMAT-LINKS ===")
        for url in relevant_201[:30]:
            print("-", url)

        print()
        print("=== GEFUNDENE LINKS TESTEN ===")
        for url in relevant_201[:10]:
            print(json.dumps(inspect_url(url), ensure_ascii=False, indent=2)[:5000])

    candidates = candidate_urls_from_discovered(sorted(discovered_hrefs))
    if candidates:
        print()
        print("=== AUS ANM-N301-MUSTER ABGELEITETE N201/M201-KANDIDATEN ===")
        for url in candidates:
            print("-", url)

        print()
        print("=== KANDIDATEN TESTEN ===")
        for url in candidates[:12]:
            print(json.dumps(inspect_url(url), ensure_ascii=False, indent=2)[:5000])

    print()
    print("=== FAZIT ===")
    if any(x in full_blob for x in ("m201", "n201", "climat", "bufr201")) or relevant_201:
        print(
            "M201/CLIMAT ist im vollständigen ANM-WFS-Pfad auffindbar. "
            "Bitte diesen Log schicken; als nächsten Schritt lesen wir konkrete Tageswerte und Zeitabdeckung."
        )
    else:
        print(
            "Auch der vollständige WFS-Metadatenpfad exponiert M201/CLIMAT nicht direkt. "
            "Dann ist der öffentlich beworbene CLIMAT-Datensatz vermutlich nicht als frei abrufbare "
            "historische O&M-Reihe hinter dem WFS veröffentlicht."
        )

    print("Noch KEIN historischer Cache gebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
