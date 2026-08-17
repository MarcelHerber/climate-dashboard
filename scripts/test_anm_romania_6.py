#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

BASE = "https://inspire.meteoromania.ro"
WFS = BASE + "/WIGOS/WFS"
UA = "climate-dashboard-anm-romania-probe6/1.0"
TIMEOUT = 90
RETRIES = 3
MAX_BYTES = 50 * 1024 * 1024
MAX_PAGES = 100
SAMPLE_STATIONS = 3

MAX_TOKEN = "TemperatureMaximumDailyCLIMAT"
MIN_TOKEN = "TemperatureMinimumDailyCLIMAT"
AVG_TOKEN = "TemperatureAverageDailyCLIMAT"

DATE_RE = re.compile(
    r"^(?:18|19|20)\d{2}-\d{2}-\d{2}"
    r"(?:T[0-2]\d:[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)


def get(url: str):
    headers = {
        "User-Agent": UA,
        "Accept": "application/gml+xml,application/xml,text/xml,*/*",
    }
    last = None
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
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"Request fehlgeschlagen: {url}: {last}")


def parse_xml(raw: bytes, url: str):
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML-Parsefehler {url}: {exc}; "
            f"sample={raw[:700].decode('utf-8','replace')!r}"
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


def members(root):
    out = []
    for elem in root.iter():
        if local(elem.tag) == "member" and list(elem):
            out.append(list(elem)[0])
    return out


def next_url(root):
    raw = root.attrib.get("next")
    return normalize(raw) if raw else None


def first_text(root, wanted: str):
    for elem in root.iter():
        if local(elem.tag) == wanted and elem.text and elem.text.strip():
            return elem.text.strip()
    return None


def feature_types():
    url = wfs_url(service="WFS", version="2.0.0", request="GetCapabilities")
    raw, _, _ = get(url)
    root = parse_xml(raw, url)
    out = []
    for ft in root.iter():
        if local(ft.tag) != "FeatureType":
            continue
        for child in ft:
            if local(child.tag) == "Name" and child.text:
                out.append(child.text.strip())
                break
    return out


def endpoint_kind(url: str):
    low = url.lower()
    if MAX_TOKEN.lower() in low:
        return "tmax"
    if MIN_TOKEN.lower() in low:
        return "tmin"
    if AVG_TOKEN.lower() in low:
        return "tavg"
    return None


def station_key_from_url(url: str):
    marker = "/ids/"
    if marker not in url:
        return None
    tail = url.split(marker, 1)[1]
    # The URL commonly contains:
    # EnvironmentalMonitoringFacility.15015/TemperatureMaximumDailyCLIMAT
    return tail.split("/", 1)[0]


def station_meta(member):
    urls = [u for u in hrefs(member) if endpoint_kind(u)]
    sid = first_text(member, "localId")
    name = first_text(member, "name")
    return {
        "local_id": sid,
        "name": name,
        "urls": urls,
    }


def collect_inventory():
    types = feature_types()
    facility_types = [t for t in types if "EnvironmentalMonitoringFacility" in t]
    if not facility_types:
        raise RuntimeError("Kein EnvironmentalMonitoringFacility-FeatureType.")

    station_rows = []
    for type_name in facility_types:
        url = wfs_url(
            service="WFS",
            version="2.0.0",
            request="GetFeature",
            typeNames=type_name,
            count="1000",
            startIndex="0",
        )
        seen = set()
        for page in range(1, MAX_PAGES + 1):
            if url in seen:
                raise RuntimeError("Pagination-Schleife.")
            seen.add(url)

            raw, _, _ = get(url)
            root = parse_xml(raw, url)
            ms = members(root)

            print(
                f"Facility-Seite {page:02d}: "
                f"{len(ms)} Features | {len(raw):,} Bytes"
            )

            station_rows.extend(station_meta(m) for m in ms)

            nxt = next_url(root)
            if not nxt:
                break
            url = nxt
        else:
            raise RuntimeError("Zu viele Facility-Seiten.")

    # Build endpoint inventory keyed by facility id parsed from the URL.
    inv = defaultdict(lambda: {"tmax": None, "tmin": None, "tavg": None, "names": set(), "local_ids": set()})

    for row in station_rows:
        for url in row["urls"]:
            key = station_key_from_url(url) or row["local_id"] or url
            kind = endpoint_kind(url)
            if kind:
                inv[key][kind] = url
            if row["name"]:
                inv[key]["names"].add(row["name"])
            if row["local_id"]:
                inv[key]["local_ids"].add(row["local_id"])

    clean = {}
    for key, row in inv.items():
        clean[key] = {
            "tmax": row["tmax"],
            "tmin": row["tmin"],
            "tavg": row["tavg"],
            "names": sorted(row["names"]),
            "local_ids": sorted(row["local_ids"]),
        }

    return station_rows, clean


def find_desc_text(elem, names):
    for sub in elem.iter():
        if local(sub.tag) in names and sub.text and sub.text.strip():
            return sub.text.strip()
    return None


def time_value_pairs(root):
    pairs = []

    # Standard WaterML 2 structure:
    # point -> MeasurementTVP -> time + value
    for elem in root.iter():
        if local(elem.tag) not in ("MeasurementTVP", "TVP"):
            continue

        t = find_desc_text(elem, {"time", "timePosition"})
        v = find_desc_text(elem, {"value"})
        if not t or not v:
            continue

        try:
            value = float(v.replace(",", "."))
        except ValueError:
            continue

        pairs.append((t, value))

    # Fallback: any "point" containing a recognizable date and numeric value.
    if not pairs:
        for elem in root.iter():
            if local(elem.tag) != "point":
                continue
            t = find_desc_text(elem, {"time", "timePosition"})
            v = find_desc_text(elem, {"value"})
            if not t or not v:
                continue
            try:
                value = float(v.replace(",", "."))
            except ValueError:
                continue
            pairs.append((t, value))

    # deterministic dedupe
    out = []
    seen = set()
    for t, v in pairs:
        key = (t, v)
        if key not in seen:
            seen.add(key)
            out.append((t, v))
    return out


def unit_candidates(root):
    rows = []
    for elem in root.iter():
        lname = local(elem.tag)
        if lname.lower() in ("uom", "unitofmeasure", "unit"):
            item = {
                "tag": lname,
                "text": (elem.text or "").strip() or None,
                "attrs": dict(elem.attrib),
            }
            rows.append(item)

        for key, value in elem.attrib.items():
            lowk = key.lower()
            if "uom" in lowk or "unit" in lowk:
                rows.append({
                    "tag": lname,
                    "attribute": key,
                    "value": str(value),
                })

    # unique
    unique = []
    seen = set()
    for row in rows:
        key = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique[:80]


def temperature_property_links(root):
    out = set()
    for u in hrefs(root):
        low = u.lower()
        if any(x in low for x in ("temperature", "tmax", "tmin", "maximum", "minimum", "climat")):
            out.add(u)
    return sorted(out)


def raw_stats(values):
    if not values:
        return None
    vals = sorted(values)
    return {
        "count": len(vals),
        "min": min(vals),
        "max": max(vals),
        "median": statistics.median(vals),
        "first_values": vals[:5],
        "last_values": vals[-5:],
    }


def maybe_celsius(value):
    # diagnostic only; actual converter will use explicit unit after this probe.
    if value > 150:
        return round(value - 273.15, 3)
    return value


def decode_endpoint(url: str):
    raw, headers, status = get(url)
    root = parse_xml(raw, url)
    pairs = time_value_pairs(root)
    vals = [v for _, v in pairs]

    times = sorted({
        t for t, _ in pairs
        if DATE_RE.match(t)
    })

    sample_pairs = []
    for t, v in pairs[:8]:
        sample_pairs.append({
            "time": t,
            "raw_value": v,
            "diagnostic_if_kelvin_C": maybe_celsius(v),
        })

    return {
        "url": url,
        "kind": endpoint_kind(url),
        "status": status,
        "content_type": headers.get("Content-Type"),
        "bytes": len(raw),
        "root": local(root.tag),
        "root_attrs": dict(root.attrib),
        "tag_counts": Counter(local(e.tag) for e in root.iter()).most_common(35),
        "unit_candidates": unit_candidates(root),
        "temperature_property_links": temperature_property_links(root)[:60],
        "pair_count": len(pairs),
        "first_time": times[0] if times else None,
        "last_time": times[-1] if times else None,
        "raw_stats": raw_stats(vals),
        "sample_pairs": sample_pairs,
    }


def self_test():
    sample = (
        b'<wml2:MeasurementTVP xmlns:wml2="http://www.opengis.net/waterml/2.0">'
        b'<wml2:time>2020-01-01T00:00:00Z</wml2:time>'
        b'<wml2:value>299.15</wml2:value>'
        b'</wml2:MeasurementTVP>'
    )
    root = ET.fromstring(sample)
    pairs = time_value_pairs(root)
    assert pairs == [("2020-01-01T00:00:00Z", 299.15)]
    assert maybe_celsius(299.15) == 26.0
    assert endpoint_kind("https://x/TemperatureMaximumDailyCLIMAT") == "tmax"
    assert endpoint_kind("https://x/TemperatureMinimumDailyCLIMAT") == "tmin"
    print("ANM Romania probe 6 self-test OK.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()

    if args.self_test:
        self_test()
        return 0

    print("=== ANM RUMÄNIEN PROBE 6 ===")
    print("Tmax/Tmin-Endpunkte, Einheiten und echte tägliche Zeit-Wert-Paare")
    print()

    _, inv = collect_inventory()

    both = [
        (sid, row)
        for sid, row in sorted(inv.items())
        if row["tmax"] and row["tmin"]
    ]
    only_max = [
        sid for sid, row in inv.items()
        if row["tmax"] and not row["tmin"]
    ]
    only_min = [
        sid for sid, row in inv.items()
        if row["tmin"] and not row["tmax"]
    ]

    print()
    print("=== ENDPOINT-INVENTAR ===")
    print(f"Stationen mit mindestens einem CLIMAT-Temperatur-Endpunkt: {len(inv)}")
    print(f"Mit Tmax + Tmin: {len(both)}")
    print(f"Nur Tmax: {len(only_max)}")
    print(f"Nur Tmin: {len(only_min)}")

    print()
    print("=== STATIONEN MIT TMAX + TMIN ===")
    for i, (sid, row) in enumerate(both, 1):
        print(
            f"{i:03d} | {sid} | "
            f"name={'; '.join(row['names']) if row['names'] else '-'}"
        )
        print("   Tmax:", row["tmax"])
        print("   Tmin:", row["tmin"])

    if not both:
        raise RuntimeError("Keine Station mit Tmax+Tmin-Endpunkten gefunden.")

    samples = both[:SAMPLE_STATIONS]

    print()
    print(f"=== DECODE-SAMPLES: {len(samples)} STATIONEN ===")
    decoded = []
    for idx, (sid, row) in enumerate(samples, 1):
        for kind in ("tmax", "tmin"):
            url = row[kind]
            print()
            print(f"--- {idx}/{len(samples)} | {sid} | {kind.upper()} ---")
            result = decode_endpoint(url)
            result["station_id"] = sid
            result["station_names"] = row["names"]
            decoded.append(result)
            print(json.dumps(result, ensure_ascii=False, indent=2)[:18000])

    print()
    print("=== KOMPAKTE DECODE-TABELLE ===")
    for row in decoded:
        stats = row["raw_stats"] or {}
        print(
            f"{row['station_id']} | {row['kind']} | "
            f"{row['pair_count']} Paare | "
            f"{row['first_time']} .. {row['last_time']} | "
            f"min={stats.get('min')} median={stats.get('median')} max={stats.get('max')} | "
            f"units={json.dumps(row['unit_candidates'], ensure_ascii=False)[:500]}"
        )

    print()
    print("=== FAZIT ===")
    good = [r for r in decoded if r["pair_count"] > 1000]
    unit_rows = [r for r in decoded if r["unit_candidates"]]

    if len(good) == len(decoded) and unit_rows:
        print(
            "Tmax/Tmin sind als echte tägliche Zeit-Wert-Reihen dekodierbar und "
            "Einheiten-Metadaten sind vorhanden. Nächster Schritt: vollständiges "
            "Stationsinventar mit Messbeginn/-ende und Datenvollständigkeit bestimmen."
        )
    elif len(good) == len(decoded):
        print(
            "Tmax/Tmin sind als echte tägliche Zeit-Wert-Reihen dekodierbar. "
            "Die Rohwerte liegen offenbar im Kelvin-Bereich; explizite Einheit wurde "
            "im Payload aber noch nicht gefunden. Vor dem Cache wird die Einheit noch "
            "über observedProperty/Schema eindeutig festgezurrt."
        )
    else:
        print(
            "Die Endpunkte existieren, aber nicht alle Samples konnten als vollständige "
            "tägliche Zeit-Wert-Reihen dekodiert werden."
        )

    print("Noch KEIN historischer Cache gebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
