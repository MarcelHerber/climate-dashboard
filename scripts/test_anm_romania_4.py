#!/usr/bin/env python3
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

BASE = "https://inspire.meteoromania.ro"
WFS = BASE + "/WIGOS/WFS"
UA = "climate-dashboard-anm-romania-probe4/1.0"
TIMEOUT = 60
RETRIES = 3
MAX_BYTES = 35 * 1024 * 1024
MAX_PAGES = 100
MAX_FOLLOW = 20

TOKENS = (
    "m201", "n201", "climat", "bufr201",
    "temperature", "minimum", "maximum",
    "tmin", "tmax", "observation",
    "observedproperty", "phenomenontime", "resulttime",
)

DATE_RE = re.compile(
    r"\b(?:18|19|20)\d{2}-\d{2}-\d{2}"
    r"(?:[T ][0-2]\d:[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)


def get(url: str):
    headers = {
        "User-Agent": UA,
        "Accept": "application/gml+xml,application/xml,text/xml,application/json,*/*",
    }
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise RuntimeError(f"Antwort zu groß: {url}")
                return raw, dict(resp.headers.items()), int(resp.status)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"Request fehlgeschlagen: {url}: {last}")


def xml(raw: bytes, url: str):
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML-Parsefehler {url}: {exc}; "
            f"sample={raw[:600].decode('utf-8','replace')!r}"
        )


def local(tag: str) -> str:
    return tag.split("}")[-1]


def wfs_url(**params: str) -> str:
    return WFS + "?" + urllib.parse.urlencode(params)


def normalize(url: str) -> str:
    return urllib.parse.urljoin(WFS, url.replace("&amp;", "&"))


def hrefs(root) -> list[str]:
    out = set()
    for elem in root.iter():
        for key, value in elem.attrib.items():
            if key.endswith("href") or key == "href":
                out.add(normalize(str(value)))
    return sorted(out)


def ids(root) -> list[str]:
    out = set()
    for elem in root.iter():
        for key, value in elem.attrib.items():
            if key.endswith("}id") or key == "id":
                out.add(str(value))
    return sorted(out)


def members(root):
    out = []
    for elem in root.iter():
        if local(elem.tag) == "member" and list(elem):
            out.append(list(elem)[0])
    return out


def next_url(root):
    if root.attrib.get("next"):
        return normalize(root.attrib["next"])
    for elem in root.iter():
        if local(elem.tag).lower() == "next":
            for key, value in elem.attrib.items():
                if key.endswith("href") or key == "href":
                    return normalize(str(value))
    return None


def feature_types() -> list[str]:
    url = wfs_url(service="WFS", version="2.0.0", request="GetCapabilities")
    raw, _, _ = get(url)
    root = xml(raw, url)
    out = []
    for ft in root.iter():
        if local(ft.tag) != "FeatureType":
            continue
        for child in ft:
            if local(child.tag) == "Name" and child.text:
                out.append(child.text.strip())
                break
    return out


def first_text(root, target: str):
    for elem in root.iter():
        if local(elem.tag) == target and elem.text and elem.text.strip():
            return elem.text.strip()
    return None


def station_row(member):
    blob = ET.tostring(member, encoding="unicode")
    low = blob.lower()
    all_links = hrefs(member)
    rel = [
        u for u in all_links
        if any(
            t in u.lower()
            for t in (
                "m201", "n201", "climat", "bufr201",
                "observation", "observedproperty", "process"
            )
        )
    ]
    return {
        "id": first_text(member, "localId") or (ids(member)[0] if ids(member) else None),
        "name": first_text(member, "name"),
        "climat": any(t in low for t in ("m201", "n201", "climat", "bufr201")),
        "temperature": any(t in low for t in ("temperature", "minimum", "maximum", "tmin", "tmax")),
        "links": rel,
        "all_hrefs": all_links,
    }


def paginate_facilities(type_name: str):
    url = wfs_url(
        service="WFS", version="2.0.0", request="GetFeature",
        typeNames=type_name, count="1000", startIndex="0"
    )
    seen = set()
    rows = []
    pages = []

    for page in range(1, MAX_PAGES + 1):
        if url in seen:
            raise RuntimeError(f"Pagination-Schleife: {url}")
        seen.add(url)

        raw, headers, status = get(url)
        root = xml(raw, url)
        ms = members(root)
        nxt = next_url(root)

        pages.append({
            "page": page,
            "bytes": len(raw),
            "numberMatched": root.attrib.get("numberMatched"),
            "numberReturned": root.attrib.get("numberReturned"),
            "members": len(ms),
            "next": nxt,
            "status": status,
            "content_type": headers.get("Content-Type"),
        })

        print(
            f"Seite {page:02d}: {len(ms)} Features | "
            f"{len(raw):,} Bytes | next={'JA' if nxt else 'NEIN'}"
        )

        rows.extend(station_row(m) for m in ms)

        if not nxt:
            break
        url = nxt
    else:
        raise RuntimeError("Zu viele Seiten; Sicherheitsabbruch.")

    return rows, pages


def dates(raw: bytes):
    return sorted(set(DATE_RE.findall(raw.decode("utf-8", "replace"))))


def follow(url: str):
    try:
        raw, headers, status = get(url)
        result = {
            "url": url,
            "status": status,
            "bytes": len(raw),
            "content_type": headers.get("Content-Type"),
            "dates": dates(raw),
        }
        root = xml(raw, url)
        result["root"] = local(root.tag)
        result["root_attributes"] = dict(root.attrib)
        result["ids"] = ids(root)[:100]
        result["hrefs"] = hrefs(root)[:200]
        result["tags"] = Counter(local(e.tag) for e in root.iter()).most_common(35)
        low = raw.decode("utf-8", "replace").lower()
        result["flags"] = {t: t in low for t in TOKENS}
        return result
    except Exception as exc:
        return {"url": url, "error": str(exc)}


def self_test():
    raw = (
        b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
        b'next="https://example/page2">'
        b'<wfs:member><x id="s1"><name>Test</name>'
        b'<a href="https://inspire.meteoromania.ro/ids/OBS.CLIMAT.M201"/>'
        b'</x></wfs:member></wfs:FeatureCollection>'
    )
    root = ET.fromstring(raw)
    assert next_url(root) == "https://example/page2"
    assert len(members(root)) == 1
    assert station_row(members(root)[0])["climat"] is True
    print("ANM Romania probe 4 self-test OK.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()

    if args.self_test:
        self_test()
        return 0

    print("=== ANM RUMÄNIEN PROBE 4 ===")
    print("Stationsebene: vollständige WFS-Pagination + CLIMAT-Verknüpfungen")
    print()

    types = feature_types()
    print("=== FEATURE TYPES ===")
    for t in types:
        print("-", t)

    facility_types = [t for t in types if "EnvironmentalMonitoringFacility" in t]
    if not facility_types:
        raise RuntimeError("Kein EnvironmentalMonitoringFacility-FeatureType gefunden.")

    rows = []
    pages = []
    for t in facility_types:
        print()
        print(f"=== PAGINATION {t} ===")
        r, pg = paginate_facilities(t)
        rows.extend(r)
        pages.extend(pg)

    print()
    print("=== PAGINATION-STATUS ===")
    print(json.dumps(pages, ensure_ascii=False, indent=2))

    climat_rows = [r for r in rows if r["climat"]]
    temp_rows = [r for r in rows if r["temperature"]]
    linked_rows = [r for r in rows if r["links"]]

    print()
    print("=== STATIONS-ZUSAMMENFASSUNG ===")
    print(f"Facility-Features gesamt: {len(rows)}")
    print(f"Mit M201/N201/CLIMAT/BUFR201: {len(climat_rows)}")
    print(f"Mit Temperatur-Begriffen: {len(temp_rows)}")
    print(f"Mit relevanten Links: {len(linked_rows)}")

    print()
    print("=== CLIMAT-STATIONSKANDIDATEN ===")
    for i, row in enumerate(climat_rows, 1):
        print(f"{i:03d} | id={row['id']} | name={row['name']} | links={len(row['links'])}")
        for u in row["links"][:25]:
            print("   -", u)

    exact_links = []
    other_links = []
    for row in rows:
        for u in row["links"]:
            if any(t in u.lower() for t in ("m201", "n201", "climat", "bufr201")):
                exact_links.append(u)
            else:
                other_links.append(u)

    exact_links = list(dict.fromkeys(exact_links))
    other_links = list(dict.fromkeys(other_links))

    print()
    print("=== EXAKTE CLIMAT-LINKS ===")
    print(f"Einmalige Links: {len(exact_links)}")
    for u in exact_links[:100]:
        print("-", u)

    follow_urls = (exact_links or other_links)[:MAX_FOLLOW]
    followed = []

    print()
    print("=== LINKS VERFOLGEN ===")
    for i, u in enumerate(follow_urls, 1):
        print(f"--- Follow {i}/{len(follow_urls)} ---")
        res = follow(u)
        followed.append(res)
        print(json.dumps(res, ensure_ascii=False, indent=2)[:10000])

    blob = json.dumps(
        {"stations": rows, "followed": followed},
        ensure_ascii=False
    ).lower()

    print()
    print("=== GESAMTBEWERTUNG ===")
    for t in TOKENS:
        print(f"{t}: {'GEFUNDEN' if t in blob else 'nicht gefunden'}")

    ds = sorted({
        d
        for res in followed
        for d in (res.get("dates") or [])
    })
    print(f"Datums-/Zeitwerte in verfolgten Links: {len(ds)}")
    if ds:
        print("Erstes:", ds[0])
        print("Letztes:", ds[-1])

    print()
    print("=== FAZIT ===")
    if exact_links:
        print(
            "CLIMAT/M201 ist an konkreten Stationen verlinkt. "
            "Nächster Schritt: Observation-Payload dekodieren und Zeitabdeckung bestimmen."
        )
    elif climat_rows:
        print(
            "CLIMAT/M201 ist auf Stationsebene sichtbar, aber nicht als direkter href. "
            "Die Stationsstruktur reicht für einen gezielten Decoder-Probe."
        )
    else:
        print(
            "Nach vollständiger Facility-Pagination ist CLIMAT/M201 nicht sichtbar. "
            "Dann wechseln wir gezielt zum Pre-defined-WFS-Gesamtdownload."
        )

    print("Noch KEIN historischer Cache gebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
