#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

BASE = "https://inspire.meteoromania.ro"
WFS = BASE + "/WIGOS/WFS"
UA = "climate-dashboard-anm-romania-inventory/1.0"

TIMEOUT = 120
RETRIES = 3
MAX_BYTES = 70 * 1024 * 1024
MAX_PAGES = 100
DEFAULT_WORKERS = 8

MAX_TOKEN = "TemperatureMaximumDailyCLIMAT"
MIN_TOKEN = "TemperatureMinimumDailyCLIMAT"
ALL_VALUES_TOKEN = "AllValuesWML20"

OUT_PATH = Path("romania_anm_station_inventory.json")

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


def all_texts(root, wanted: str):
    out = []
    for elem in root.iter():
        if local(elem.tag) == wanted and elem.text and elem.text.strip():
            out.append(elem.text.strip())
    return out


def first_text(root, wanted: str):
    values = all_texts(root, wanted)
    return values[0] if values else None


def best_name(root):
    # Keep all station-name candidates and prefer the longest readable one.
    candidates = []
    for elem in root.iter():
        if local(elem.tag) != "name":
            continue
        texts = [
            x.text.strip()
            for x in elem.iter()
            if x.text and x.text.strip()
        ]
        for text in texts:
            if len(text) >= 2 and not text.startswith("http"):
                candidates.append(text)

    if not candidates:
        return None

    # Deduplicate, then prefer strings containing letters and more context.
    unique = list(dict.fromkeys(candidates))
    unique.sort(key=lambda s: (sum(ch.isalpha() for ch in s), len(s)), reverse=True)
    return unique[0]


def position(root):
    for elem in root.iter():
        if local(elem.tag) == "pos" and elem.text:
            parts = elem.text.strip().split()
            if len(parts) >= 2:
                try:
                    return float(parts[0]), float(parts[1])
                except ValueError:
                    return None, None
    return None, None


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
    if ALL_VALUES_TOKEN.lower() in low:
        return None
    if MAX_TOKEN.lower() in low:
        return "tmax"
    if MIN_TOKEN.lower() in low:
        return "tmin"
    return None


def station_key_from_url(url: str):
    marker = "/ids/"
    if marker not in url:
        return None
    tail = url.split(marker, 1)[1]
    return tail.split("/", 1)[0]


def facility_meta(member):
    endpoints = []
    for url in hrefs(member):
        kind = endpoint_kind(url)
        if kind:
            endpoints.append((kind, url))

    lat, lon = position(member)

    return {
        "local_id": first_text(member, "localId"),
        "name": best_name(member),
        "lat": lat,
        "lon": lon,
        "endpoints": endpoints,
    }


def collect_facilities():
    types = feature_types()
    facility_types = [t for t in types if "EnvironmentalMonitoringFacility" in t]
    if not facility_types:
        raise RuntimeError("Kein EnvironmentalMonitoringFacility-FeatureType.")

    inv = defaultdict(lambda: {
        "tmax_meta": None,
        "tmin_meta": None,
        "names": set(),
        "local_ids": set(),
        "lat": None,
        "lon": None,
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
                raise RuntimeError("Pagination-Schleife erkannt.")
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
                meta = facility_meta(member)
                for kind, endpoint in meta["endpoints"]:
                    sid = (
                        station_key_from_url(endpoint)
                        or meta["local_id"]
                        or endpoint
                    )
                    inv[sid][f"{kind}_meta"] = endpoint

                    if meta["name"]:
                        inv[sid]["names"].add(meta["name"])
                    if meta["local_id"]:
                        inv[sid]["local_ids"].add(meta["local_id"])
                    if meta["lat"] is not None:
                        inv[sid]["lat"] = meta["lat"]
                    if meta["lon"] is not None:
                        inv[sid]["lon"] = meta["lon"]

            nxt = next_url(root)
            if not nxt:
                break
            url = nxt
        else:
            raise RuntimeError("Zu viele Facility-Seiten.")

    clean = {}
    for sid, row in inv.items():
        clean[sid] = {
            "tmax_meta": row["tmax_meta"],
            "tmin_meta": row["tmin_meta"],
            "names": sorted(row["names"]),
            "local_ids": sorted(row["local_ids"]),
            "lat": row["lat"],
            "lon": row["lon"],
        }

    return feature_count, clean


def all_values_link(meta_url: str, kind: str):
    raw, _, _ = get(meta_url)
    root = parse_xml(raw, meta_url)

    wanted = MAX_TOKEN if kind == "tmax" else MIN_TOKEN

    exact = [
        u for u in hrefs(root)
        if ALL_VALUES_TOKEN.lower() in u.lower()
        and wanted.lower() in u.lower()
    ]
    if exact:
        return exact[0]

    fallback = [
        u for u in hrefs(root)
        if ALL_VALUES_TOKEN.lower() in u.lower()
    ]
    return fallback[0] if fallback else None


def find_desc_text(elem, names):
    for sub in elem.iter():
        if local(sub.tag) in names and sub.text and sub.text.strip():
            return sub.text.strip()
    return None


def time_value_pairs(root):
    pairs = []

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
                or "kelvin" in lowv
                or lowv.endswith("/k")
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

    return unique[:80]


def explicit_kelvin(units):
    blob = json.dumps(units, ensure_ascii=False).lower()
    return (
        "kelvin" in blob
        or '"k"' in blob
        or "/k" in blob
        or "unit:k" in blob
    )


def daily_series_from_values_url(url: str):
    raw, _, _ = get(url)
    root = parse_xml(raw, url)
    pairs = time_value_pairs(root)
    units = unit_candidates(root)

    daily = {}
    for stamp, value in pairs:
        m = DATE_PREFIX_RE.match(stamp)
        if not m:
            continue
        daily[m.group(1)] = value

    values = list(daily.values())

    return {
        "url": url,
        "daily": daily,
        "daily_count": len(daily),
        "first_day": min(daily) if daily else None,
        "last_day": max(daily) if daily else None,
        "explicit_kelvin": explicit_kelvin(units),
        "raw_min": min(values) if values else None,
        "raw_median": statistics.median(values) if values else None,
        "raw_max": max(values) if values else None,
        "bytes": len(raw),
    }


def calendar_days_inclusive(first_day: str | None, last_day: str | None):
    if not first_day or not last_day:
        return None
    a = dt.date.fromisoformat(first_day)
    b = dt.date.fromisoformat(last_day)
    return (b - a).days + 1


def decode_station(item):
    sid, row = item

    result = {
        "station_id": sid,
        "names": row["names"],
        "local_ids": row["local_ids"],
        "lat": row["lat"],
        "lon": row["lon"],
        "tmax_meta": row["tmax_meta"],
        "tmin_meta": row["tmin_meta"],
        "ok": False,
        "error": None,
    }

    try:
        if not row["tmax_meta"] or not row["tmin_meta"]:
            result["error"] = "Tmax- oder Tmin-Metadatenendpunkt fehlt."
            return result

        tmax_values_url = all_values_link(row["tmax_meta"], "tmax")
        tmin_values_url = all_values_link(row["tmin_meta"], "tmin")

        if not tmax_values_url or not tmin_values_url:
            result["error"] = "AllValuesWML20-Link fehlt."
            return result

        tmax = daily_series_from_values_url(tmax_values_url)
        tmin = daily_series_from_values_url(tmin_values_url)

        common = sorted(set(tmax["daily"]).intersection(tmin["daily"]))
        violations = sum(
            1
            for day in common
            if tmax["daily"][day] < tmin["daily"][day]
        )

        first_common = common[0] if common else None
        last_common = common[-1] if common else None
        possible = calendar_days_inclusive(first_common, last_common)
        completeness = (
            len(common) / possible
            if possible and possible > 0
            else None
        )

        latest_year = None
        if last_common:
            latest_year = int(last_common[:4])

        result.update({
            "ok": (
                tmax["daily_count"] > 0
                and tmin["daily_count"] > 0
                and violations == 0
                and tmax["explicit_kelvin"]
                and tmin["explicit_kelvin"]
            ),
            "tmax_values_url": tmax_values_url,
            "tmin_values_url": tmin_values_url,
            "tmax_count": tmax["daily_count"],
            "tmin_count": tmin["daily_count"],
            "tmax_first": tmax["first_day"],
            "tmax_last": tmax["last_day"],
            "tmin_first": tmin["first_day"],
            "tmin_last": tmin["last_day"],
            "common_count": len(common),
            "common_first": first_common,
            "common_last": last_common,
            "common_possible_days": possible,
            "common_completeness": completeness,
            "latest_year": latest_year,
            "tmax_lt_tmin_days": violations,
            "tmax_explicit_kelvin": tmax["explicit_kelvin"],
            "tmin_explicit_kelvin": tmin["explicit_kelvin"],
            "tmax_raw_min": tmax["raw_min"],
            "tmax_raw_max": tmax["raw_max"],
            "tmin_raw_min": tmin["raw_min"],
            "tmin_raw_max": tmin["raw_max"],
            "download_bytes": tmax["bytes"] + tmin["bytes"],
        })

    except Exception as exc:
        result["error"] = str(exc)

    return result


def self_test():
    assert calendar_days_inclusive("2020-01-01", "2020-01-03") == 3
    assert explicit_kelvin([{"attrs": {"code": "K"}}]) is True
    print("ANM Romania inventory self-test OK.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--output", default=str(OUT_PATH))
    args = p.parse_args()

    if args.self_test:
        self_test()
        return 0

    workers = max(1, min(args.workers, 12))

    print("=== ANM RUMÄNIEN STATIONSINVENTAR ===")
    print("Vollständige Tmax/Tmin-CLIMAT-Abdeckung je Station")
    print()

    feature_count, inv = collect_facilities()

    both = [
        (sid, row)
        for sid, row in sorted(inv.items())
        if row["tmax_meta"] and row["tmin_meta"]
    ]

    print()
    print("=== AUSGANGSNETZ ===")
    print(f"EnvironmentalMonitoringFacility-Features: {feature_count}")
    print(f"Stationen mit mindestens einem Temperatur-CLIMAT-Endpunkt: {len(inv)}")
    print(f"Stationen mit Tmax + Tmin-Endpunkt: {len(both)}")
    print(f"Parallelität: {workers}")

    results = []

    print()
    print("=== ZEITREIHEN PRÜFEN ===")
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(decode_station, item): item[0]
            for item in both
        }

        done_count = 0
        for fut in cf.as_completed(future_map):
            sid = future_map[fut]
            done_count += 1
            try:
                row = fut.result()
            except Exception as exc:
                row = {
                    "station_id": sid,
                    "ok": False,
                    "error": str(exc),
                }

            results.append(row)

            print(
                f"{done_count:03d}/{len(both):03d} | "
                f"{sid} | "
                f"OK={'JA' if row.get('ok') else 'NEIN'} | "
                f"{row.get('common_first')} .. {row.get('common_last')} | "
                f"gemeinsam={row.get('common_count')} | "
                f"vollst={row.get('common_completeness')} | "
                f"Tmax<Tmin={row.get('tmax_lt_tmin_days')} | "
                f"Fehler={row.get('error')}"
            )

    results.sort(key=lambda r: r.get("station_id") or "")

    ok_rows = [r for r in results if r.get("ok")]
    latest_2026 = [
        r for r in ok_rows
        if r.get("common_last") and r["common_last"].startswith("2026-")
    ]
    start_before_1961 = [
        r for r in ok_rows
        if r.get("common_first") and r["common_first"] < "1961-01-01"
    ]
    start_1961 = [
        r for r in ok_rows
        if r.get("common_first") == "1961-01-01"
    ]
    at_least_30y = [
        r for r in ok_rows
        if r.get("common_first")
        and r.get("common_last")
        and (
            dt.date.fromisoformat(r["common_last"])
            - dt.date.fromisoformat(r["common_first"])
        ).days >= int(29.5 * 365.25)
    ]

    print()
    print("=== INVENTAR-TABELLE ===")
    for i, row in enumerate(results, 1):
        completeness = row.get("common_completeness")
        comp_txt = (
            f"{100.0 * completeness:.2f}%"
            if isinstance(completeness, (int, float))
            else "-"
        )

        print(
            f"{i:03d} | {row.get('station_id')} | "
            f"name={'; '.join(row.get('names') or []) or '-'} | "
            f"{row.get('common_first')} .. {row.get('common_last')} | "
            f"Tmax={row.get('tmax_count')} | Tmin={row.get('tmin_count')} | "
            f"gemeinsam={row.get('common_count')} | "
            f"Vollständigkeit={comp_txt} | "
            f"Kelvin={row.get('tmax_explicit_kelvin') and row.get('tmin_explicit_kelvin')} | "
            f"Tmax<Tmin={row.get('tmax_lt_tmin_days')} | "
            f"OK={'JA' if row.get('ok') else 'NEIN'}"
        )

    payload = {
        "format_version": 1,
        "source": "Administrația Națională de Meteorologie (ANM România) INSPIRE/WFS",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "facility_feature_count": feature_count,
        "temperature_endpoint_station_count": len(inv),
        "tmax_tmin_endpoint_station_count": len(both),
        "valid_station_count": len(ok_rows),
        "valid_through_2026_station_count": len(latest_2026),
        "valid_at_least_30_year_station_count": len(at_least_30y),
        "start_before_1961_station_count": len(start_before_1961),
        "start_1961_station_count": len(start_1961),
        "stations": results,
    }

    out_path = Path(args.output)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print()
    print("=== ZUSAMMENFASSUNG ===")
    print(f"Stationen mit Tmax + Tmin-Endpunkt: {len(both)}")
    print(f"Vollständig dekodierbar/valide: {len(ok_rows)}")
    print(f"Davon Daten bis 2026: {len(latest_2026)}")
    print(f"Davon mindestens ca. 30 Jahre: {len(at_least_30y)}")
    print(f"Messbeginn vor 1961: {len(start_before_1961)}")
    print(f"Messbeginn exakt 1961-01-01: {len(start_1961)}")
    print(f"Inventar-Datei: {out_path}")

    if len(ok_rows) == 0:
        raise RuntimeError("Keine valide ANM Tmax+Tmin-Station.")

    print()
    print("FAZIT: Rumänisches Stationsinventar bestimmt. Noch KEIN Historical-Cache gebaut.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
