#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

BASE = "https://opendataapi.dmi.dk/v2"
CLIMATE_STATIONS = f"{BASE}/climateData/collections/station/items"
CLIMATE_VALUES = f"{BASE}/climateData/collections/stationValue/items"
METOBS_STATIONS = f"{BASE}/metObs/collections/station/items"
METOBS_VALUES = f"{BASE}/metObs/collections/observation/items"

BBOX = "7,54,16,58"
UA = "climate-dashboard-dmi-bridge-probe/1.0"
TRIES = 5

PARAMETERS = (
    "temp_max_past1h",
    "temp_min_past1h",
    "temp_max_past12h",
    "temp_min_past12h",
    "temp_dry",
)

YEARS = (1984, 1985, 1990, 1995, 1999, 2000, 2005, 2010, 2011)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def req_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True, safe=",:/+")
    last = None
    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/geo+json, application/json",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            last = exc
            retryable = (
                not isinstance(exc, urllib.error.HTTPError)
                or exc.code in {408, 429, 500, 502, 503, 504}
            )
            if attempt == TRIES or not retryable:
                raise
            time.sleep(min(20, attempt * 3))
    raise RuntimeError(str(last))


def paged(url: str, params: dict[str, Any], max_pages: int = 8) -> list[dict[str, Any]]:
    payload = req_json(url, params)
    features = list(payload.get("features") or [])
    pages = 1
    while pages < max_pages:
        next_url = None
        for link in payload.get("links") or []:
            if isinstance(link, dict) and link.get("rel") == "next":
                next_url = link.get("href")
                break
        if not next_url:
            break
        payload = req_json(str(next_url))
        features.extend(payload.get("features") or [])
        pages += 1
    return [x for x in features if isinstance(x, dict)]


def prop(f: dict[str, Any], key: str, default=None):
    p = f.get("properties")
    return p.get(key, default) if isinstance(p, dict) else default


def finite_values(features: list[dict[str, Any]]) -> list[float]:
    result = []
    for f in features:
        try:
            x = float(prop(f, "value"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and -100 <= x <= 100:
            result.append(x)
    return result


def station_ids() -> list[str]:
    features = paged(
        METOBS_STATIONS,
        {"limit": 1000, "bbox": BBOX},
        max_pages=5,
    )
    rows = []
    for f in features:
        if str(prop(f, "country", "")).upper() != "DNK":
            continue
        sid = str(prop(f, "stationId", "")).strip()
        if sid:
            rows.append(sid)
    return sorted(set(rows))


def observations(sid: str, parameter: str, year: int) -> list[dict[str, Any]]:
    start = f"{year}-07-01T00:00:00Z"
    end = f"{year}-07-03T23:59:59Z"
    return paged(
        METOBS_VALUES,
        {
            "stationId": sid,
            "parameterId": parameter,
            "datetime": f"{start}/{end}",
            "limit": 10000,
        },
        max_pages=5,
    )


def climate_daily(sid: str, parameter: str, year: int) -> list[dict[str, Any]]:
    return paged(
        CLIMATE_VALUES,
        {
            "stationId": sid,
            "parameterId": parameter,
            "timeResolution": "day",
            "datetime": (
                f"{year}-07-01T00:00:00Z/"
                f"{year}-07-03T23:59:59Z"
            ),
            "limit": 1000,
        },
        max_pages=3,
    )


def best_station_for_year(ids: list[str], year: int) -> tuple[str, dict[str, int]] | None:
    # Prefer well-known long-running Danish synoptic IDs first.
    preferred = ["06030", "06079", "06180", "06181", "06190", "06080", "06120"]
    candidates = preferred + [x for x in ids if x not in preferred]

    for sid in candidates[:80]:
        counts = {}
        useful = False
        for parameter in PARAMETERS:
            try:
                n = len(finite_values(observations(sid, parameter, year)))
            except urllib.error.HTTPError as exc:
                if exc.code in {400, 404}:
                    n = 0
                else:
                    raise
            counts[parameter] = n
            useful |= n > 0
        if useful:
            return sid, counts
    return None


def summarize_times(features: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for f in features:
        text = str(prop(f, "observed", ""))
        if len(text) >= 13:
            result[text[11:13]] += 1
    return dict(sorted(result.items()))


def compare_2011(sid: str) -> None:
    log()
    log("=== ÜBERLAPPUNGSTEST 2011 ===")

    c_tx = climate_daily(sid, "max_temp_w_date", 2011)
    c_tn = climate_daily(sid, "min_temp", 2011)
    log(
        f"climateData {sid}: "
        f"TMAX={finite_values(c_tx)} | TMIN={finite_values(c_tn)}"
    )

    for parameter in PARAMETERS:
        obs = observations(sid, parameter, 2011)
        vals = finite_values(obs)
        if not vals:
            continue
        log(
            f"metObs {parameter}: n={len(vals)} | "
            f"min={min(vals):.1f} | max={max(vals):.1f} | "
            f"Stunden={summarize_times(obs)}"
        )


def run_probe() -> None:
    log("=== DMI DÄNEMARK BRÜCKEN-PROBE 1984–2010 ===")
    ids = station_ids()
    log(f"Dänische metObs-Stations-IDs im Inventar: {len(ids)}")
    log()

    earliest_by_param: dict[str, int | None] = {p: None for p in PARAMETERS}
    representative: dict[int, str] = {}

    for year in YEARS:
        found = best_station_for_year(ids, year)
        if found is None:
            log(f"{year}: kein Temperaturparameter im Probe-Sample gefunden.")
            continue

        sid, counts = found
        representative[year] = sid
        log(f"{year}: Station {sid}")
        for p in PARAMETERS:
            log(f"  {p}: {counts[p]} Werte")
            if counts[p] > 0 and earliest_by_param[p] is None:
                earliest_by_param[p] = year

    log()
    log("=== FRÜHESTER TREFFER PRO PARAMETER ===")
    for p in PARAMETERS:
        log(f"{p}: {earliest_by_param[p] or 'kein Treffer'}")

    # Compare modern climateData and raw metObs on a station that works in 2011.
    sid_2011 = representative.get(2011)
    if sid_2011:
        compare_2011(sid_2011)

    log()
    log("=== ENTSCHEIDUNGSHILFE ===")
    one_hour_start = max(
        earliest_by_param["temp_max_past1h"] or 9999,
        earliest_by_param["temp_min_past1h"] or 9999,
    )
    twelve_hour_start = max(
        earliest_by_param["temp_max_past12h"] or 9999,
        earliest_by_param["temp_min_past12h"] or 9999,
    )
    dry_start = earliest_by_param["temp_dry"] or 9999

    if one_hour_start <= 1984:
        log(
            "Die offiziellen 1h-Extrema reichen bis 1984 zurück. "
            "Damit lässt sich die Brücke DMI-konform direkt bauen."
        )
    elif twelve_hour_start <= 1984:
        log(
            "12h-Extrema reichen bis 1984 zurück, 1h-Extrema aber nicht. "
            "Vor Verwendung als Tagesrekord muss die Tagesgrenzen-Logik "
            "gegen climateData validiert werden."
        )
    elif dry_start <= 1984:
        log(
            "Nur temp_dry reicht bis 1984 zurück. Momentanwerte werden NICHT "
            "automatisch als Tages-Tmax/Tmin verwendet; das wäre für "
            "Rekordanalysen methodisch zu unsicher."
        )
    else:
        log(
            "Keiner der geprüften metObs-Temperaturparameter reicht bis 1984. "
            "Dann bleibt zwischen Jahrbuch und climateData eine echte Lücke, "
            "die separat gelöst werden muss."
        )

    log("DMI Denmark Bridge Probe OK.")


def self_test() -> None:
    fake = [
        {"properties": {"value": "12.3", "observed": "2011-07-01T06:00:00Z"}},
        {"properties": {"value": None, "observed": "2011-07-01T18:00:00Z"}},
    ]
    assert finite_values(fake) == [12.3]
    assert summarize_times(fake) == {"06": 1, "18": 1}
    print("DMI Denmark bridge probe self-test OK")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
    else:
        run_probe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
