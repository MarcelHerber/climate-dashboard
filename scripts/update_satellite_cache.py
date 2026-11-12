#!/usr/bin/env python3
"""Preserve the last *successfully downloaded* EUMETSAT WMS PNG per product/region.

This best-effort job does not synthesize imagery, replace verified timestamps,
or erase an older good image if the current EUMETView server is unavailable.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import struct
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path("data/satellite_cache")
INDEX = ROOT / "index.json"
SOURCE = Path("data/satellite_wms_times.json")
WMS = "https://view.eumetsat.int/geoserver/wms"
REGIONS = {
    "europe": ([-27, 24, 49, 73], [1300, 850], "EPSG:4326"),
    "atlantic": ([-70, 15, 35, 75], [1400, 850], "EPSG:4326"),
    "southwest": ([-37, 24, 19, 53], [1200, 620], "EPSG:4326"),
}
PRODUCTS = {
    "geocolour": "mtg_fd:rgb_geocolour",
    "dust": "mtg_fd:rgb_dust",
    "cloudtype": "mtg_fd:rgb_cloudtype",
    "ir105": "mtg_fd:ir105_hrfi",
    "firetemperature": "mtg_fd:rgb_firetemperature",
}
WIDTH = 400
TIMEOUT = 14
LIMIT = 1_500_000
UTC = dt.timezone.utc


def valid_utc(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo and parsed.utcoffset() == dt.timedelta(0) else None
    except (ValueError, AttributeError, TypeError):
        return None


def request_png(product: str, region: str, timestamp: str) -> bytes:
    bbox, native, srs = REGIONS[region]
    height = round(WIDTH * native[1] / native[0])
    args = {
        "service": "WMS", "version": "1.1.1", "request": "GetMap",
        "layers": PRODUCTS[product], "styles": "", "format": "image/png",
        "transparent": "false", "srs": srs,
        "bbox": ",".join(str(x) for x in bbox),
        "width": str(WIDTH), "height": str(height),
        "bgcolor": "0x000000", "time": timestamp,
    }
    url = WMS + "?" + urlencode(args)
    req = Request(url, headers={"User-Agent": "ClimateDashboard-satellite-cache/1.0"})
    with urlopen(req, timeout=TIMEOUT) as res:
        mime = res.headers.get("Content-Type", "")
        payload = res.read(LIMIT + 1)
    if not mime.lower().startswith("image/png"):
        raise ValueError("Server did not return image/png")
    if len(payload) < 512 or len(payload) > LIMIT or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid or oversized PNG")
    if len(payload) < 40 or payload[12:16] != b"IHDR" or payload[-8:-4] != b"IEND":
        raise ValueError("PNG structure incomplete")
    actual_width, actual_height = struct.unpack(">II", payload[16:24])
    if (actual_width, actual_height) != (WIDTH, height):
        raise ValueError("Unexpected PNG dimensions")
    return payload


def run() -> int:
    if not SOURCE.is_file():
        print("No EUMETSAT status available; retain existing cache.")
        return 0
    status = json.loads(SOURCE.read_text(encoding="utf-8"))
    generated = valid_utc(status.get("generated_at"))
    now = dt.datetime.now(UTC)
    if not generated or not status.get("capabilities_ok") or abs((now - generated).total_seconds()) > 6 * 3600:
        print("Status outdated or invalid; retain existing cache.")
        return 0
    archive = {"schema": 1, "provider": "EUMETSAT WMS", "entries": {}}
    if INDEX.is_file():
        old = json.loads(INDEX.read_text(encoding="utf-8"))
        if old.get("schema") == 1:
            archive = old
    entries = archive.setdefault("entries", {})
    jobs = []
    for product, layer in PRODUCTS.items():
        metadata = status.get("products", {}).get(product, {})
        if metadata.get("layer") != layer:
            continue
        # "available_times" is metadata only. Archive the last image that
        # was actually decoded and checked by the independent WMS monitor.
        # This avoids wasting retries on advertised-but-broken newest frames.
        verified = metadata.get("latest_verified_time")
        moments = set(metadata.get("available_times", []))
        if (not metadata.get("map_ok") or verified not in moments
                or not valid_utc(verified) or valid_utc(verified) > now):
            continue
        latest = verified
        # WMS may advertise a good timestamp while a region-specific render
        # fails. After one failed verified frame, try up to three earlier
        # advertised timestamps, accepting only a fully validated real PNG.
        older = sorted(
            (t for t in moments if valid_utc(t) and t < latest
             and valid_utc(latest) - valid_utc(t) <= dt.timedelta(minutes=90)),
            reverse=True,
        )[:3]
        for region in REGIONS:
            previous = entries.get(product, {}).get(region, {})
            candidates = [
                t for t in [latest, *older]
                if not previous.get("time") or t > previous["time"]
            ]
            if candidates:
                jobs.append((product, region, candidates))

    def download(job):
        product, region, candidates = job
        last_error = None
        for timestamp in candidates:
            try:
                payload = request_png(product, region, timestamp)
                return (product, region, timestamp, payload, None)
            except Exception as exc:
                last_error = str(exc)
        return (product, region, candidates[0], None, last_error)

    updated = 0
    ROOT.mkdir(parents=True, exist_ok=True)
    # Do not overwhelm an upstream service already returning 500/504.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for product, region, timestamp, payload, error in pool.map(download, jobs):
            if not payload:
                print(f"{product}/{region}: keeping last good image ({error})")
                continue
            # Immutable timestamped filenames prevent stale browser/CDN bytes
            # being displayed under a newer observation time.
            filename = f"{product}_{region}_{timestamp.replace('-', '').replace(':', '')}.png"
            former = entries.get(product, {}).get(region, {}).get("url", "")
            (ROOT / filename).write_bytes(payload)
            entries.setdefault(product, {})[region] = {
                "time": timestamp,
                "url": "./data/satellite_cache/" + filename,
                "width": WIDTH,
                "height": round(WIDTH * REGIONS[region][1][1] / REGIONS[region][1][0]),
                "source": "EUMETSAT WMS",
                "saved_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            }
            if former.startswith(f"./data/satellite_cache/{product}_{region}_") and former.endswith(".png"):
                previous = ROOT / former.rsplit("/", 1)[-1]
                if previous.name != filename:
                    previous.unlink(missing_ok=True)
            updated += 1
            print(f"{product}/{region}: archived {timestamp} ({len(payload)} bytes)")
    if updated:
        INDEX.write_text(json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Archived {updated} PNG images; retained existing images on failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
