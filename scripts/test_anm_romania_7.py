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
UA = "climate-dashboard-anm-romania-probe7/1.0"

TIMEOUT = 120
RETRIES = 3
MAX_BYTES = 60 * 1024 * 1024
MAX_PAGES = 100
SAMPLE_STATIONS = 3

MAX_TOKEN = "TemperatureMaximumDailyCLIMAT"
MIN_TOKEN = "TemperatureMinimumDailyCLIMAT"
ALL_VALUES_TOKEN = "AllValuesWML20"

DATE_PREFIX_RE = re.compile(r"^((?:18|19|20)\d{2}-\d{2}-\d{2})")


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
                time.sleep(attempt * 2.0)
    raise RuntimeError(f"Request fehlgeschlagen: {url}: {last}")


def parse_xml(raw: bytes, url: str):
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        sample = raw[:800].decode("utf-8", "replace")
        raise RuntimeError(f"XML-Parsefehler {url}: {exc}; sample={sample!r}")


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
                val = str(value).strip()
                if val:
                    out.add(normalize(val))
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
    if MAX_TOKEN.lower() in low and ALL_VALUES_TOKEN.lower() not in low:
        return "tmax"
    if MIN_TOKEN.lower() in low and ALL_VALUES_TOKEN.lower() not in low:
        return "tmin"
    return None


def station_key_from_url(url: str):
    marker = "/ids/"
    if marker not in url:
        return None
    tail = url.split(marker, 1)[1]
    return tail.split("/", 1)[0]


def station_meta(member):
    all_urls = hrefs(member)
    temp_urls = [u for u in all_urls if endpoint_kind(u)]
    return {
        "local_id": first_text(member, "localId"),
        "name": first_text(member, "name"),
        "urls": temp_urls,
    }


def collect_inventory():
    types = feature_types()
    facility_types = [t for t in types if "EnvironmentalMonitoringFacility" in t]
    if not facility_types:
        raise RuntimeError("Kein EnvironmentalMonitoringFacility-FeatureType.")

    inv = defaultdict(lambda: {
        "tmax": None,
        "tmin": None,
        "names": set(),
        "local_ids": set(),
    })

    feature_count = 0

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
            feature_count += len(ms)

            print(
                f"Facility-Seite {page:02d}: "
                f"{len(ms)} Features | {len(raw):,} Bytes"
            )

            for member in ms:
                row = station_meta(member)
                for endpoint in row["urls"]:
                    sid = station_key_from_url(endpoint) or row["local_id"] or endpoint
                    kind = endpoint_kind(endpoint)
                    if kind:
                        inv[sid][kind] = endpoint
                    if row["name"]:
                        inv[sid]["names"].add(row["name"])
                    if row["local_id"]:
                        inv[sid]["local_ids"].add(row["local_id"])

            nxt = next_url(root)
            if not nxt:
                break
            url = nxt
        else:
            raise RuntimeError("Zu viele Facility-Seiten.")

    clean = {}
    for sid, row in inv.items():
        clean[sid] = {
            "tmax": row["tmax"],
            "tmin": row["tmin"],
            "names": sorted(row["names"]),
            "local_ids": sorted(row["local_ids"]),
        }

    return feature_count, clean


def all_values_link(metadata_root, kind: str):
    wanted = MAX_TOKEN if kind == "tmax" else MIN_TOKEN
    candidates = []

    for u in hrefs(metadata_root):
        low = u.lower()
        if ALL_VALUES_TOKEN.lower() not in low:
            continue
        if wanted.lower() in low:
            candidates.append(u)

    if candidates:
        return candidates[0]

    # Fallback: any AllValuesWML20 link from the metadata.
    candidates = [
        u for u in hrefs(metadata_root)
        if ALL_VALUES_TOKEN.lower() in u.lower()
    ]
    return candidates[0] if candidates else None


def find_desc_text(elem, names):
    for sub in elem.iter():
        if local(sub.tag) in names and sub.text and sub.text.strip():
            return sub.text.strip()
    return None


def time_value_pairs(root):
    pairs = []

    # Standard WaterML 2:
    # wml2:point / wml2:MeasurementTVP / wml2:time + wml2:value
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

    # Some services put time/value directly below point.
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

    # Dedupe but preserve order.
    out = []
    seen = set()
    for item in pairs:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def unit_candidates(root):
    rows = []

    for elem in root.iter():
        lname = local(elem.tag)
        if lname.lower() in ("uom", "unitofmeasure", "unit"):
            rows.append({
                "tag": lname,
                "text": (elem.text or "").strip() or None,
                "attrs": dict(elem.attrib),
            })

        for key, value in elem.attrib.items():
            lowk = key.lower()
            lowv = str(value).lower()
            if (
                "uom" in lowk
                or "unit" in lowk
                or lowv.endswith("/k")
                or "kelvin" in lowv
                or "ucum" in lowv
            ):
                rows.append({
                    "tag": lname,
                    "attribute": key,
                    "value": str(value),
                })

    unique = []
    seen = set()
    for row in rows:
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(row)

    return unique[:100]


def explicit_kelvin(unit_rows):
    blob = json.dumps(unit_rows, ensure_ascii=False).lower()
    return (
        "kelvin" in blob
        or '"k"' in blob
        or "/k" in blob
        or "unit:k" in blob
        or "ucum/0/k" in blob
    )


def to_celsius(value: float, kelvin: bool):
    return value - 273.15 if kelvin else value


def raw_stats(values):
    if not values:
        return None
    vals = sorted(values)
    return {
        "count": len(vals),
        "min": min(vals),
        "median": statistics.median(vals),
        "max": max(vals),
    }


def decode_kind(metadata_url: str, kind: str):
    meta_raw, meta_headers, meta_status = get(metadata_url)
    meta_root = parse_xml(meta_raw, metadata_url)
    values_url = all_values_link(meta_root, kind)

    if not values_url:
        return {
            "metadata_url": metadata_url,
            "kind": kind,
            "metadata_status": meta_status,
            "metadata_bytes": len(meta_raw),
            "metadata_content_type": meta_headers.get("Content-Type"),
            "error": "Kein AllValuesWML20-Link im Metadaten-Payload.",
            "metadata_hrefs": hrefs(meta_root)[:100],
        }

    raw, headers, status = get(values_url)
    root = parse_xml(raw, values_url)
    pairs = time_value_pairs(root)
    units = unit_candidates(root)
    is_kelvin = explicit_kelvin(units)

    # Diagnostic fallback only for reporting. We do NOT silently use this
    # for the final cache without explicit metadata confirmation.
    numeric_values = [v for _, v in pairs]
    kelvin_like_range = bool(numeric_values) and statistics.median(numeric_values) > 150

    converted_sample = []
    for t, v in pairs[:8]:
        converted_sample.append({
            "time": t,
            "raw": v,
            "celsius_if_K": round(v - 273.15, 3),
        })

    daily = {}
    for t, v in pairs:
        m = DATE_PREFIX_RE.match(t)
        if not m:
            continue
        day = m.group(1)
        daily[day] = v

    return {
        "metadata_url": metadata_url,
        "all_values_url": values_url,
        "kind": kind,
        "metadata_status": meta_status,
        "metadata_bytes": len(meta_raw),
        "status": status,
        "content_type": headers.get("Content-Type"),
        "bytes": len(raw),
        "root": local(root.tag),
        "root_attrs": dict(root.attrib),
        "tag_counts": Counter(local(e.tag) for e in root.iter()).most_common(40),
        "unit_candidates": units,
        "explicit_kelvin": is_kelvin,
        "kelvin_like_numeric_range": kelvin_like_range,
        "pair_count": len(pairs),
        "daily_count": len(daily),
        "first_day": min(daily) if daily else None,
        "last_day": max(daily) if daily else None,
        "raw_stats": raw_stats(numeric_values),
        "sample_pairs": converted_sample,
        "_daily": daily,
    }


def compare_station(tmax_result, tmin_result):
    tmax = tmax_result.get("_daily") or {}
    tmin = tmin_result.get("_daily") or {}

    common = sorted(set(tmax).intersection(tmin))
    violations_raw = 0
    examples = []

    for day in common:
        vmax = tmax[day]
        vmin = tmin[day]
        if vmax < vmin:
            violations_raw += 1
            if len(examples) < 10:
                examples.append({
                    "date": day,
                    "tmax_raw": vmax,
                    "tmin_raw": vmin,
                })

    return {
        "common_days": len(common),
        "tmax_lt_tmin_days": violations_raw,
        "violation_examples": examples,
        "first_common_day": common[0] if common else None,
        "last_common_day": common[-1] if common else None,
    }


def strip_private(result):
    return {k: v for k, v in result.items() if not k.startswith("_")}


def self_test():
    sample = (
        b'<root xmlns:wml2="http://www.opengis.net/waterml/2.0" '
        b'xmlns:xlink="http://www.w3.org/1999/xlink">'
        b'<a xlink:href="https://x/TemperatureMaximumDailyCLIMAT.AllValuesWML20"/>'
        b'<wml2:MeasurementTVP>'
        b'<wml2:time>2020-01-01T00:00:00Z</wml2:time>'
        b'<wml2:value>299.15</wml2:value>'
        b'</wml2:MeasurementTVP>'
        b'<wml2:uom code="K"/>'
        b'</root>'
    )
    root = ET.fromstring(sample)
    assert all_values_link(root, "tmax").endswith("AllValuesWML20")
    assert time_value_pairs(root) == [("2020-01-01T00:00:00Z", 299.15)]
    units = unit_candidates(root)
    assert explicit_kelvin(units) is True
    print("ANM Romania probe 7 self-test OK.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()

    if args.self_test:
        self_test()
        return 0

    print("=== ANM RUMÄNIEN PROBE 7 ===")
    print("AllValuesWML20: echte Tmax/Tmin-Tageswerte + Einheit + Plausibilität")
    print()

    feature_count, inv = collect_inventory()

    both = [
        (sid, row)
        for sid, row in sorted(inv.items())
        if row["tmax"] and row["tmin"]
    ]

    print()
    print("=== INVENTAR ===")
    print(f"EnvironmentalMonitoringFacility-Features: {feature_count}")
    print(f"Stationen mit Temperatur-CLIMAT-Endpunkt: {len(inv)}")
    print(f"Stationen mit Tmax + Tmin: {len(both)}")

    for i, (sid, row) in enumerate(both, 1):
        print(
            f"{i:03d} | {sid} | "
            f"name={'; '.join(row['names']) if row['names'] else '-'}"
        )

    if not both:
        raise RuntimeError("Keine Station mit Tmax+Tmin.")

    samples = both[:SAMPLE_STATIONS]

    print()
    print(f"=== ALLVALUES-DECODE: {len(samples)} STATIONEN ===")

    reports = []
    for idx, (sid, row) in enumerate(samples, 1):
        print()
        print(f"### Station {idx}/{len(samples)}: {sid}")

        tmax = decode_kind(row["tmax"], "tmax")
        print("--- TMAX ---")
        print(json.dumps(strip_private(tmax), ensure_ascii=False, indent=2)[:18000])

        tmin = decode_kind(row["tmin"], "tmin")
        print("--- TMIN ---")
        print(json.dumps(strip_private(tmin), ensure_ascii=False, indent=2)[:18000])

        comparison = compare_station(tmax, tmin)
        print("--- TMAX/TMIN-PLAUSIBILITÄT ---")
        print(json.dumps(comparison, ensure_ascii=False, indent=2))

        reports.append({
            "station_id": sid,
            "station_names": row["names"],
            "tmax": strip_private(tmax),
            "tmin": strip_private(tmin),
            "comparison": comparison,
        })

    print()
    print("=== KOMPAKT ===")
    for report in reports:
        for kind in ("tmax", "tmin"):
            row = report[kind]
            print(
                f"{report['station_id']} | {kind} | "
                f"pairs={row.get('pair_count')} | daily={row.get('daily_count')} | "
                f"{row.get('first_day')} .. {row.get('last_day')} | "
                f"explicit_K={row.get('explicit_kelvin')} | "
                f"kelvin_like={row.get('kelvin_like_numeric_range')} | "
                f"raw={row.get('raw_stats')}"
            )
        comp = report["comparison"]
        print(
            f"{report['station_id']} | common={comp['common_days']} | "
            f"Tmax<Tmin={comp['tmax_lt_tmin_days']}"
        )

    print()
    print("=== FAZIT ===")
    all_series_ok = all(
        report[kind].get("daily_count", 0) > 1000
        for report in reports
        for kind in ("tmax", "tmin")
    )
    all_plausible = all(
        report["comparison"].get("tmax_lt_tmin_days", 1) == 0
        for report in reports
    )
    explicit_k_count = sum(
        1
        for report in reports
        for kind in ("tmax", "tmin")
        if report[kind].get("explicit_kelvin") is True
    )
    total_series = len(reports) * 2

    if all_series_ok and all_plausible and explicit_k_count == total_series:
        print(
            "ERFOLG: AllValuesWML20 liefert vollständige tägliche Tmax/Tmin-Reihen, "
            "Kelvin ist explizit bestätigt und Tmax>=Tmin ist in allen Sample-Überlappungen erfüllt. "
            "Nächster Schritt: vollständiges rumänisches Stationsinventar mit Messbeginn/-ende."
        )
    elif all_series_ok and all_plausible:
        print(
            "ERFOLG: AllValuesWML20 liefert vollständige tägliche Tmax/Tmin-Reihen und "
            "die Zuordnung ist durch Tmax>=Tmin plausibel. Kelvin-artige Rohwerte sind erkennbar; "
            "falls die UOM nicht explizit im XML steht, prüfen wir noch die verlinkte "
            "ObservedProperty/Process-Definition bevor der Cache gebaut wird."
        )
    else:
        print(
            "AllValuesWML20 wurde erreicht, aber mindestens eine Sample-Reihe oder "
            "Tmax/Tmin-Plausibilitätsprüfung ist noch nicht sauber."
        )

    print("Noch KEIN historischer Cache gebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
