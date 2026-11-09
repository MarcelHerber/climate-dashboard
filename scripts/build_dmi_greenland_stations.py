#!/usr/bin/env python3
"""Build an authentic, small Greenland station catalogue and latest daily values from DMI.

No API key (DMI Open Data since 2025-12-02). Exclude invalid observations.
Source: https://www.dmi.dk/friedata/dokumentation/apis/climate-data-api-1
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://opendataapi.dmi.dk/v2/climateData/collections"
BBOX = "-75,59,-10,84"
PARAMS = (
    "mean_temp", "max_temp_w_date", "min_temp", "acc_precip",
    "max_wind_speed_3sec", "mean_wind_speed", "mean_pressure",
)
OUT = Path("data/dmi_greenland_stations.json")


def request(collection: str, params: dict, retries: int = 4):
    url = f"{BASE}/{collection}/items?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers={"Accept": "application/geo+json",
                                                      "User-Agent": "ClimateDashboard-Greenland/1.0"}),
                timeout=85,
            ) as response:
                payload = json.load(response)
            if not isinstance(payload.get("features"), list):
                raise ValueError(f"Unexpected DMI GeoJSON for {collection}")
            return payload
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as ex:
            last = ex
            if isinstance(ex, urllib.error.HTTPError) and ex.code in (400, 401, 403, 404):
                raise
            if attempt + 1 < retries:
                time.sleep(min(2**attempt * 2, 15))
    raise RuntimeError(f"DMI {collection} request failed: {last}")


def pages(collection: str, params: dict, limit: int):
    offset = 0
    for _ in range(20):
        data = request(collection, {**params, "limit": limit, "offset": offset})
        features = data["features"]
        yield from features
        next_link = any(link.get("rel") == "next" for link in data.get("links", []))
        if not next_link and len(features) < limit:
            break
        if not features:
            break
        offset += len(features)
    else:
        raise RuntimeError("DMI API station pagination exceeded guard")


def parse_stations(features):
    by_id = {}
    for f in features:
        p = f.get("properties") or {}
        c = (f.get("geometry") or {}).get("coordinates") or []
        sid = str(p.get("stationId") or "")
        if p.get("country") != "GRL" or len(c) < 2 or not sid:
            continue
        lon, lat = c[:2]
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (lon, lat)):
            continue
        if not (-75 <= lon <= -10 and 59 <= lat <= 84):
            continue
        candidate = {
            "id": sid, "name": str(p.get("name") or sid).strip(),
            "lat": round(lat, 5), "lon": round(lon, 5),
            "status": str(p.get("status") or ""),
            "type": str(p.get("type") or ""),
            "from": str(p.get("operationFrom") or "")[:10],
            "to": str(p.get("operationTo") or "")[:10],
            "height_m": p.get("stationHeight") if isinstance(p.get("stationHeight"), (int, float)) else None,
            "parameters": [str(x) for x in (p.get("parameterId") or []) if isinstance(x, str)],
        }
        prior = by_id.get(sid)
        if prior is None or (candidate["from"], candidate["status"] == "Active") > (
            prior["from"], prior["status"] == "Active"
        ):
            by_id[sid] = candidate
    return sorted(by_id.values(), key=lambda x: (x["name"].casefold(), x["id"]))


def latest_values(features, allowed_ids: set[str]):
    found = {}
    for feature in features:
        p = feature.get("properties") or {}
        sid = str(p.get("stationId") or "")
        param = p.get("parameterId")
        val = p.get("value")
        if sid not in allowed_ids or param not in PARAMS or p.get("validity") is False:
            continue
        if not isinstance(val, (float, int)) or not math.isfinite(val):
            continue
        if param == "acc_precip" and val < -0.1:
            continue
        at = str(p.get("from") or "")[:10]
        created = str(p.get("created") or "")
        if len(at) != 10 or at[4] != "-" or at[7] != "-":
            continue
        entry = (at, created, round(float(val), 3), str(p.get("qcStatus") or ""))
        key = (sid, param)
        if key not in found or entry[:2] > found[key][:2]:
            found[key] = entry
    return {sid: {p: {"date": v[0], "value": v[2], "qc": v[3]}
                  for (s, p), v in found.items() if s == sid}
            for sid in allowed_ids}


def build(today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    stations = parse_stations(pages("station", {"bbox": BBOX}, 5000))
    if len(stations) < 10:
        raise RuntimeError(f"Expected >=10 real Greenland DMI stations; got {len(stations)}")
    # One compact, truthful latest-day window per parameter; no substitutions.
    start = today - dt.timedelta(days=22)
    query = {"bbox": BBOX, "timeResolution": "day",
             "datetime": f"{start.isoformat()}T00:00:00Z/{today.isoformat()}T23:59:59Z"}
    collected = []
    failures = []
    for param in PARAMS:
        try:
            rows = list(pages("stationValue", {**query, "parameterId": param}, 25000))
            collected.extend(rows)
            print(f"DMI {param}: {len(rows)} original stationValue rows", flush=True)
        except Exception as ex:
            failures.append(f"{param}: {ex}")
            print(f"WARN {param}: {ex}", flush=True)
    if not collected:
        raise RuntimeError("No real DMI Greenland stationValue data returned; refusing to publish a fake snapshot")
    snapshot = latest_values(collected, {s["id"] for s in stations})
    if not any(snapshot.values()):
        raise RuntimeError("No valid Greenland data in DMI snapshot")
    result = {
        "schema": 1, "source": "DMI Climate Data API station / stationValue",
        "source_url": BASE, "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "window_start": start.isoformat(), "window_end": today.isoformat(),
        "stations": stations, "latest": {k: v for k, v in snapshot.items() if v},
        "parameters": list(PARAMS), "fetch_errors": failures,
        "note": "Original DMI stationValue; validity=false excluded; no interpolation. Daily intervals may differ by parameter."
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(OUT)
    print(f"Greenland DMI validated: {len(stations)} stations, {len(result['latest'])} with recent values, {OUT.stat().st_size} bytes", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate existing cache without HTTP")
    args = parser.parse_args()
    if args.check:
        doc = json.loads(OUT.read_text(encoding="utf-8"))
        assert doc["schema"] == 1 and len(doc["stations"]) >= 10 and len(doc["latest"]) >= 1
        assert all(-75 <= s["lon"] <= -10 and 59 <= s["lat"] <= 84 for s in doc["stations"])
        assert all(s["id"] and s["name"] for s in doc["stations"])
        print("DMI Greenland station cache OK")
    else:
        build()
