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
UA = "climate-dashboard-anm-romania-probe5/1.0"
TIMEOUT = 75
RETRIES = 3
MAX_BYTES = 45 * 1024 * 1024
MAX_PAGES = 100
SAMPLE_LINKS = 6

DATE_RE = re.compile(
    r"\b(?:18|19|20)\d{2}-\d{2}-\d{2}"
    r"(?:[T ][0-2]\d:[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)

TEMP_WORDS = (
    "temperature", "temperatura", "tmin", "tmax",
    "minimum", "maximum", "minima", "maxima",
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
                    raise RuntimeError(f"Antwort zu groß (> {MAX_BYTES:,} Bytes): {url}")
                return raw, dict(resp.headers.items()), int(resp.status)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(attempt * 1.5)
    raise RuntimeError(f"Request fehlgeschlagen: {url}: {last}")

def parse_xml(raw: bytes, url: str):
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        sample = raw[:700].decode("utf-8", "replace")
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
                out.add(normalize(str(value)))
    return sorted(out)

def next_url(root):
    raw = root.attrib.get("next")
    if raw:
        return normalize(raw)
    return None

def members(root):
    out = []
    for elem in root.iter():
        if local(elem.tag) == "member" and list(elem):
            out.append(list(elem)[0])
    return out

def first_text(root, target: str):
    for elem in root.iter():
        if local(elem.tag) == target and elem.text and elem.text.strip():
            return elem.text.strip()
    return None

def feature_types() -> list[str]:
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

def station_info(member):
    blob = ET.tostring(member, encoding="unicode").lower()
    links = hrefs(member)
    climat_links = [
        u for u in links
        if any(x in u.lower() for x in ("m201", "n201", "climat", "bufr201"))
    ]
    return {
        "id": first_text(member, "localId"),
        "name": first_text(member, "name"),
        "climat_hit": any(x in blob for x in ("m201", "n201", "climat", "bufr201")),
        "links": climat_links,
    }

def collect_climat_links():
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
                f"Facility-Seite {page:02d}: {len(ms)} Features | "
                f"{len(raw):,} Bytes"
            )
            station_rows.extend(station_info(m) for m in ms)

            nxt = next_url(root)
            if not nxt:
                break
            url = nxt
        else:
            raise RuntimeError("Facility-Pagination > MAX_PAGES.")

    pairs = []
    for row in station_rows:
        for link in row["links"]:
            pairs.append({
                "station_id": row["id"],
                "station_name": row["name"],
                "url": link,
            })

    # deterministic unique by URL
    unique = []
    seen = set()
    for pair in pairs:
        if pair["url"] in seen:
            continue
        seen.add(pair["url"])
        unique.append(pair)

    return station_rows, unique

def date_values(raw: bytes):
    return sorted(set(DATE_RE.findall(raw.decode("utf-8", "replace"))))

def child_href(elem):
    for key, value in elem.attrib.items():
        if key.endswith("href") or key == "href":
            return str(value)
    return None

def observation_meta(root):
    rows = []
    for obs in root.iter():
        if local(obs.tag) not in ("OM_Observation", "PointTimeSeriesObservation"):
            continue

        row = {
            "gml_id": None,
            "phenomenon_times": [],
            "result_times": [],
            "observed_property": None,
            "feature_of_interest": None,
            "procedure": None,
        }

        for key, value in obs.attrib.items():
            if key.endswith("}id") or key == "id":
                row["gml_id"] = str(value)

        for elem in obs.iter():
            lname = local(elem.tag)
            if lname == "observedProperty":
                row["observed_property"] = child_href(elem) or (elem.text or "").strip() or None
            elif lname == "featureOfInterest":
                row["feature_of_interest"] = child_href(elem) or (elem.text or "").strip() or None
            elif lname == "procedure":
                row["procedure"] = child_href(elem) or (elem.text or "").strip() or None
            elif lname == "phenomenonTime":
                txt = " ".join(
                    x.text.strip() for x in elem.iter()
                    if x.text and x.text.strip()
                )
                if txt:
                    row["phenomenon_times"].append(txt)
            elif lname == "resultTime":
                txt = " ".join(
                    x.text.strip() for x in elem.iter()
                    if x.text and x.text.strip()
                )
                if txt:
                    row["result_times"].append(txt)

        rows.append(row)
    return rows

def swe_dataarrays(root):
    arrays = []
    for da in root.iter():
        if local(da.tag) != "DataArray":
            continue

        fields = []
        for field in da.iter():
            if local(field.tag) != "field":
                continue
            name = field.attrib.get("name")
            definition = None
            uom = None
            component_type = None

            for sub in field.iter():
                lname = local(sub.tag)
                if lname in ("Quantity", "Time", "Category", "Text", "Count"):
                    if component_type is None:
                        component_type = lname
                    definition = sub.attrib.get("definition") or definition
                if lname == "uom":
                    uom = sub.attrib.get("code") or sub.attrib.get("href") or uom

            fields.append({
                "name": name,
                "type": component_type,
                "definition": definition,
                "uom": uom,
            })

        encoding = {}
        for enc in da.iter():
            if local(enc.tag) == "TextEncoding":
                encoding = {
                    "blockSeparator": enc.attrib.get("blockSeparator"),
                    "tokenSeparator": enc.attrib.get("tokenSeparator"),
                    "decimalSeparator": enc.attrib.get("decimalSeparator"),
                }
                break

        values_text = None
        for val in da.iter():
            if local(val.tag) == "values" and val.text:
                values_text = val.text.strip()
                break

        record_count = None
        for cnt in da.iter():
            if local(cnt.tag) == "Count":
                for val in cnt.iter():
                    if local(val.tag) == "value" and val.text and val.text.strip().isdigit():
                        record_count = int(val.text.strip())
                        break

        arrays.append({
            "fields": fields,
            "encoding": encoding,
            "record_count_declared": record_count,
            "values_chars": len(values_text or ""),
            "values_sample": (values_text or "")[:5000],
        })
    return arrays

def leaf_values(root, limit=160):
    rows = []
    for elem in root.iter():
        if list(elem):
            continue
        text = (elem.text or "").strip()
        if not text:
            continue
        attrs = dict(elem.attrib)
        blob = f"{local(elem.tag)} {text} {attrs}".lower()
        if any(word in blob for word in TEMP_WORDS) or local(elem.tag) in (
            "value", "values", "pos", "timePosition", "beginPosition", "endPosition"
        ):
            rows.append({
                "tag": local(elem.tag),
                "text": text[:1400],
                "attrs": attrs,
            })
        if len(rows) >= limit:
            break
    return rows

def definitions(root):
    out = set()
    for elem in root.iter():
        for key, value in elem.attrib.items():
            if key == "definition" or key.endswith("href"):
                v = str(value)
                if any(w in v.lower() for w in TEMP_WORDS) or "observedproperty" in v.lower():
                    out.add(v)
    return sorted(out)

def decode_url(pair):
    url = pair["url"]
    raw, headers, status = get(url)
    root = parse_xml(raw, url)

    arrays = swe_dataarrays(root)
    obs = observation_meta(root)
    ds = date_values(raw)

    return {
        "station_id": pair["station_id"],
        "station_name": pair["station_name"],
        "url": url,
        "status": status,
        "content_type": headers.get("Content-Type"),
        "bytes": len(raw),
        "root": local(root.tag),
        "root_attributes": dict(root.attrib),
        "tag_counts": Counter(local(e.tag) for e in root.iter()).most_common(45),
        "dates_count": len(ds),
        "first_date": ds[0] if ds else None,
        "last_date": ds[-1] if ds else None,
        "observations_count": len(obs),
        "observations_sample": obs[:8],
        "dataarrays_count": len(arrays),
        "dataarrays": arrays[:8],
        "interesting_definitions": definitions(root)[:100],
        "interesting_leaf_values": leaf_values(root),
    }

def classify_fields(decoded_rows):
    found = []
    for row in decoded_rows:
        for arr in row.get("dataarrays") or []:
            for field in arr.get("fields") or []:
                blob = json.dumps(field, ensure_ascii=False).lower()
                if any(w in blob for w in TEMP_WORDS):
                    found.append({
                        "station_id": row["station_id"],
                        "station_name": row["station_name"],
                        **field,
                    })

        for obs in row.get("observations_sample") or []:
            prop = str(obs.get("observed_property") or "")
            if any(w in prop.lower() for w in TEMP_WORDS):
                found.append({
                    "station_id": row["station_id"],
                    "station_name": row["station_name"],
                    "observed_property": prop,
                })

    # unique JSON representation
    unique = []
    seen = set()
    for item in found:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique

def self_test():
    sample = (
        b'<swe:DataArray xmlns:swe="http://www.opengis.net/swe/2.0">'
        b'<swe:elementType><swe:DataRecord>'
        b'<swe:field name="TMAX"><swe:Quantity definition="daily maximum temperature">'
        b'<swe:uom code="Cel"/></swe:Quantity></swe:field>'
        b'</swe:DataRecord></swe:elementType>'
        b'<swe:encoding><swe:TextEncoding tokenSeparator="," blockSeparator=";"/></swe:encoding>'
        b'<swe:values>2020-01-01,5.2;2020-01-02,6.1</swe:values>'
        b'</swe:DataArray>'
    )
    root = ET.fromstring(sample)
    arr = swe_dataarrays(root)[0]
    assert arr["fields"][0]["name"] == "TMAX"
    assert arr["fields"][0]["uom"] == "Cel"
    assert arr["encoding"]["tokenSeparator"] == ","
    assert date_values(sample)[0] == "2020-01-01"
    print("ANM Romania probe 5 self-test OK.")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()

    if args.self_test:
        self_test()
        return 0

    print("=== ANM RUMÄNIEN PROBE 5 ===")
    print("CLIMAT/M201 Decoder: O&M / SWE / Tmin / Tmax / Einheiten / Zeitabdeckung")
    print()

    station_rows, links = collect_climat_links()

    climat_station_ids = {
        (row["id"], row["name"])
        for row in station_rows
        if row["climat_hit"]
    }

    print()
    print("=== INVENTAR ===")
    print(f"Facility-Features: {len(station_rows)}")
    print(f"CLIMAT-Stationen: {len(climat_station_ids)}")
    print(f"Eindeutige CLIMAT-Links: {len(links)}")

    for i, (sid, name) in enumerate(sorted(climat_station_ids, key=lambda x: str(x)), 1):
        print(f"{i:03d} | {sid} | {name}")

    if not links:
        raise RuntimeError("Keine CLIMAT-Links gefunden.")

    samples = links[:SAMPLE_LINKS]

    print()
    print(f"=== DECODE-SAMPLES ({len(samples)}) ===")
    decoded = []
    for i, pair in enumerate(samples, 1):
        print()
        print(
            f"--- Sample {i}/{len(samples)} | "
            f"{pair['station_id']} | {pair['station_name']} ---"
        )
        row = decode_url(pair)
        decoded.append(row)
        print(json.dumps(row, ensure_ascii=False, indent=2)[:22000])

    print()
    print("=== ERKANNTE TEMPERATUR-FELDER ===")
    temp_fields = classify_fields(decoded)
    print(json.dumps(temp_fields, ensure_ascii=False, indent=2)[:16000])

    print()
    print("=== ZEITABDECKUNG DER SAMPLES ===")
    for row in decoded:
        print(
            f"{row['station_id']} | {row['station_name']} | "
            f"{row['first_date']} .. {row['last_date']} | "
            f"{row['dates_count']} Zeitwerte | "
            f"{row['bytes']:,} Bytes | "
            f"DataArrays={row['dataarrays_count']} | "
            f"Observations={row['observations_count']}"
        )

    print()
    print("=== FAZIT ===")
    blob = json.dumps(decoded, ensure_ascii=False).lower()
    has_temp = any(w in blob for w in TEMP_WORDS)
    has_units = any(
        (field.get("uom") not in (None, ""))
        for item in decoded
        for arr in (item.get("dataarrays") or [])
        for field in (arr.get("fields") or [])
    )

    if temp_fields:
        print(
            "Tmin/Tmax-relevante Felder/ObservedProperties wurden dekodiert. "
            "Nächster Schritt: alle CLIMAT-Stationen inventarisieren und historische "
            "Tmax/Tmin-Zeitabdeckung je Station bestimmen."
        )
    elif has_temp:
        print(
            "Temperaturstruktur ist im Payload vorhanden, aber Tmin/Tmax-Felder sind "
            "noch nicht eindeutig klassifiziert. Die ausgegebenen Definitions-/Leaf-Werte "
            "reichen für einen letzten gezielten Felddecoder."
        )
    else:
        print(
            "Die verfolgten CLIMAT-Links enthalten keine direkt erkennbaren Temperaturfelder. "
            "Dann müssen wir den stationseigenen Observation-Unterlink aus dem Payload wählen."
        )

    print(f"Einheiten in SWE-Feldern erkannt: {'JA' if has_units else 'NEIN'}")
    print("Noch KEIN historischer Cache gebaut.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
