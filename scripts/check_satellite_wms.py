#!/usr/bin/env python3
"""Check live MTG EUMETView WMS capabilities and image responses.

Reports are factual: only a verified PNG with an advertised timestamp is
described as a timestamp-verified image. Failures never become fabricated data.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

SERVICE = "https://view.eumetsat.int/geoserver/wms"
LAYERS = {
    "geocolour": "mtg_fd:rgb_geocolour",
    "dust": "mtg_fd:rgb_dust",
    "cloudtype": "mtg_fd:rgb_cloudtype",
}
TIMEOUT = 45
MAX_XML = 64 * 1024 * 1024
NOW = datetime.now(timezone.utc)
OUT = Path("data/satellite_wms_times.json")


def url(params):
    return SERVICE + "?" + urlencode(params)


def fetch(url_string, cap):
    request = Request(url_string, headers={"User-Agent": "ClimateDashboard-WMS-healthcheck/1.0", "Origin":"https://marcelherber.github.io"})
    with urlopen(request, timeout=TIMEOUT) as response:
        payload = response.read(cap + 1)
        if len(payload) > cap:
            raise ValueError(f"Antwort größer als {cap} Bytes")
        return (payload, response.status, response.headers.get("Content-Type", ""),
                response.headers.get("Access-Control-Allow-Origin"))


def localname(tag):
    return tag.split("}")[-1]


def parse_date(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_duration(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return None
    seconds = int(match[1] or 0) * 3600 + int(match[2] or 0) * 60 + int(match[3] or 0)
    return timedelta(seconds=seconds) if seconds >= 30 else None


def parse_times(value):
    known = set()
    for raw in value.strip().split(","):
        part = raw.strip()
        if not part:
            continue
        if "/" in part:
            segments = part.split("/")
            if len(segments) != 3:
                continue
            start, end, delta = parse_date(segments[0]), parse_date(segments[1]), parse_duration(segments[2])
            if not (start and end and delta and end >= start):
                continue
            for j in range(72):
                t = end - delta * j
                if t < start:
                    break
                if t <= NOW + timedelta(minutes=10):
                    known.add(t)
        else:
            t = parse_date(part)
            if t and t <= NOW + timedelta(minutes=10):
                known.add(t)
    return [t.isoformat(timespec="seconds").replace("+00:00", "Z") for t in sorted(known)[-48:]]


def dimensions_for_layer(root, target):
    parent = {child: node for node in root.iter() for child in node}
    for node in root.iter():
        if localname(node.tag) != "Layer":
            continue
        direct = next((child for child in node if localname(child.tag) == "Name"), None)
        if direct is None or (direct.text or "").strip() != target:
            continue
        while node is not None and localname(node.tag) == "Layer":
            times = []
            for child in node:
                if localname(child.tag) in ("Extent", "Dimension") and child.get("name", "").lower() == "time":
                    if child.text and child.text.strip():
                        times.extend(parse_times(child.text))
            if times:
                return sorted(set(times))[-48:]
            node = parent.get(node)
    return []


def test_png(layer, timestamp, full_disk=False):
    params = {
        "service": "WMS", "version": "1.1.1", "request": "GetMap",
        "layers": layer, "styles": "", "format": "image/png",
        "srs": "EPSG:4326", "bbox": "-2,43,25,58",
        "width": "600", "height": "360",
    }
    if full_disk:
        params.update({"srs":"AUTO:97004,9001,0,0",
                       "bbox":"-6500000,-6500000,6500000,6500000",
                       "width":"500", "height":"500"})
    if timestamp:
        params["time"] = timestamp
    payload, code, mime, cors = fetch(url(params), 8 * 1024 * 1024)
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"Keine PNG-Daten (HTTP {code}, Content-Type {mime}, Bytes {len(payload)})")
    if len(payload) < 512:
        raise ValueError("PNG ist ungewöhnlich klein")
    return {"ok": True, "bytes": len(payload), "http_status": code, "content_type": mime,
            "cors_allow_origin": cors}


def main():
    result = {
        "schema": 1, "generated_at": NOW.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "provider": "EUMETSAT", "service": SERVICE, "capabilities_ok": False,
        "products": {}, "errors": [],
    }
    root = None
    try:
        xml, _, content_type, cors = fetch(url({"service": "WMS", "version": "1.1.1", "request": "GetCapabilities"}), MAX_XML)
        result["capabilities_cors_allow_origin"] = cors
        result["capabilities_cors_ok"] = cors in ("*", "https://marcelherber.github.io")
        root = ET.fromstring(xml)
        if localname(root.tag) not in ("WMT_MS_Capabilities", "WMS_Capabilities"):
            raise ValueError("Unbekanntes WMS-Capabilities-Format")
        result["capabilities_ok"] = True
        result["capabilities_bytes"] = len(xml)
    except Exception as error:
        result["errors"].append("GetCapabilities: " + str(error)[:350])
    for key, layer in LAYERS.items():
        available = dimensions_for_layer(root, layer) if root is not None else []
        entry = {
            "layer": layer, "available_times": available,
            "latest_advertised_time": available[-1] if available else None,
            "latest_verified_time": None, "map_ok": False, "error": None,
        }
        try:
            check = test_png(layer, available[-1] if available else None)
            entry.update(check)
            entry["map_ok"] = bool(check.get("ok"))
            if available:
                entry["latest_verified_time"] = available[-1]
                age = (NOW - parse_date(available[-1])).total_seconds() / 60
                entry["age_minutes"] = round(age, 1)
                entry["fresh"] = 0 <= age <= 90
        except Exception as error:
            entry["error"] = str(error)[:350]
        try:
            native = test_png(layer, available[-1] if available else None, full_disk=True)
            entry["full_disk_ok"] = bool(native.get("ok"))
            entry["full_disk_bytes"] = native["bytes"]
        except Exception as error:
            entry["full_disk_ok"] = False
            entry["full_disk_error"] = str(error)[:350]
        result["products"][key] = entry
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"generated_at": result["generated_at"], "capabilities_ok": result["capabilities_ok"],
                      "products": {k: {"map_ok": v["map_ok"], "fresh": v.get("fresh"),
                                       "timestamp": v["latest_verified_time"], "error": v["error"]}
                                   for k, v in result["products"].items()},
                      "errors": result["errors"]}, ensure_ascii=False, indent=2))
    # Reports failures in the manifest; do not fail or block unrelated Pages deployments.
    return 0


if __name__ == "__main__":
    sys.exit(main())
