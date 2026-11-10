#!/usr/bin/env python3
"""Build a validated Greenland stations record map from actual DMI yearly extremes.

This indexes the best *available* annual extreme by station, not nationwide
records and not alleged complete all-time records. No interpolation or estimates.
"""
from __future__ import annotations
import concurrent.futures
import datetime as dt
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

SOURCE = Path("data/dmi_greenland_stations.json")
OUT = Path("data/dmi_greenland_records.json")
API = "https://opendataapi.dmi.dk/v2/climateData/collections/stationValue/items"
PARAMS = {
    "high": ("max_temp_w_date", "max"),
    "low": ("min_temp", "min"),
    "gust": ("max_wind_speed_3sec", "max"),
    "rain": ("max_precip_24h", "max"),
}
BBOX = "-75,59,-10,84"
LIMIT = 12000
NOW = dt.datetime.now(dt.timezone.utc)
YEAR = NOW.year


def get_json(query):
    url = API + "?" + urllib.parse.urlencode(query)
    for retry in range(4):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/geo+json",
                "User-Agent": "ClimateDashboard/1.0 Greenland historical extrema",
            })
            with urllib.request.urlopen(req, timeout=90) as response:
                data = json.load(response)
            assert isinstance(data.get("features"), list)
            return data
        except (urllib.error.URLError, TimeoutError, ValueError, AssertionError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 401, 403, 404):
                raise
            if retry == 3:
                raise
            print("DMI retry", retry+1, type(exc).__name__, flush=True)
            time.sleep((retry + 1) * 3)


def load_parameter(param):
    features = []
    offset = 0
    for _ in range(8):
        data = get_json({
            "bbox": BBOX, "parameterId": param, "timeResolution": "year",
            "datetime": f"1953-01-01T00:00:00Z/{YEAR}-12-31T23:59:59Z",
            "limit": LIMIT, "offset": offset,
        })
        rows = data["features"]
        features.extend(rows)
        print(f"DMI year {param}: batch {len(rows)}, total {len(features)}", flush=True)
        if len(rows) < LIMIT:
            break
        offset += len(rows)
    else:
        raise RuntimeError(f"DMI pagination exhausted for {param}")
    return features


def summarize(rows, ids, param, direction):
    # The newest created value supersedes old duplicates, including invalidations.
    unique = {}
    for feature in rows:
        p = feature.get("properties") or {}
        sid = str(p.get("stationId") or "")
        date = str(p.get("from") or "")[:10]
        value = p.get("value")
        if sid not in ids or p.get("parameterId") != param:
            continue
        if p.get("timeResolution") != "year" or len(date) < 10:
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        if param == "max_precip_24h" and value < 0:
            continue
        year = date[:4]
        if not year.isdigit() or not 1953 <= int(year) <= YEAR:
            continue
        key = sid, year
        stamp = str(p.get("created") or "")
        if key not in unique or stamp >= unique[key][0]:
            unique[key] = (stamp, p)
    by_id = {}
    for (sid, year), (_, p) in unique.items():
        if p.get("validity") is False:
            continue
        by_id.setdefault(sid, []).append({
            "year": int(year),
            "value": round(float(p["value"]), 3),
            "qc": str(p.get("qcStatus") or "none"),
        })
    output = {}
    for sid, points in by_id.items():
        ranked = sorted(points, key=lambda d: (
            d["value"] if direction == "min" else -d["value"], d["year"]
        ))
        winner = ranked[0]
        output[sid] = {
            "value": winner["value"], "year": winner["year"], "qc": winner["qc"],
            "count": len(ranked), "first": min(x["year"] for x in ranked),
            "last": max(x["year"] for x in ranked),
            "top": ranked[:10],
        }
    return output


def build():
    stations_json = json.loads(SOURCE.read_text(encoding="utf-8"))
    ids = {s["id"] for s in stations_json["stations"]}
    if len(ids) < 10:
        raise RuntimeError("DMI Greenland stations cache is too small")
    by_mode = {}
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(load_parameter, param): (key, param, direction)
                   for key, (param, direction) in PARAMS.items()}
        for fut in concurrent.futures.as_completed(futures):
            key, param, direction = futures[fut]
            try:
                by_mode[key] = summarize(fut.result(), ids, param, direction)
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                print("DMI data unavailable", errors[-1], flush=True)
    available = sum(len(v) for v in by_mode.values())
    if len(by_mode) < 3 or available < 60:
        raise RuntimeError(f"Not enough official records to update map: modes={list(by_mode)}, pairs={available}, errors={errors}")
    payload = {
        "schema": 1, "source": "DMI Climate Data API stationValue (year)",
        "generated_utc": NOW.isoformat(),
        "first_query_year": 1953, "last_query_year": YEAR,
        "scope": "Best annual extremes among available valid DMI station years; not nationwide records",
        "station_count": len(ids), "modes": by_mode, "errors": errors,
        "metadata": {key: {"parameterId": param, "direction": direction}
                     for key, (param, direction) in PARAMS.items()},
    }
    OUT.parent.mkdir(exist_ok=True, parents=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
                   encoding="utf-8")
    print("Greenland DMI record map OK:",
          ", ".join(f"{key} {len(value)} stations" for key, value in by_mode.items()), flush=True)


def check():
    obj = json.loads(OUT.read_text(encoding="utf-8"))
    assert obj["schema"] == 1 and len(obj["modes"]) >= 3
    assert sum(len(v) for v in obj["modes"].values()) >= 60
    for mode, group in obj["modes"].items():
        assert mode in PARAMS
        for sid, v in group.items():
            assert isinstance(sid, str) and isinstance(v["value"], (int, float))
            assert 1953 <= v["first"] <= v["year"] <= v["last"] <= YEAR
            assert v["count"] >= 1
            assert len(v["top"]) == min(10, v["count"])
            assert v["qc"] in ("manual", "none")
    print("Validated record map:", {k: len(v) for k, v in obj["modes"].items()})


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        check()
    else:
        build()
