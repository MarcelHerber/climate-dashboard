#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
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

CLIMATE_TMAX = "max_temp_w_date"
CLIMATE_TMIN = "min_temp"
METOBS_TMAX = "temp_max_past1h"
METOBS_TMIN = "temp_min_past1h"

DENMARK_BBOX = "7,54,16,58"
UA = "climate-dashboard-dmi-probe/1.0"
TRIES = 5


def log(text: str = "") -> None:
    print(text, flush=True)


def request_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if params:
        query = urllib.parse.urlencode(params, doseq=True, safe=",:/+")
        url = f"{url}?{query}"

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
            with urllib.request.urlopen(req, timeout=90) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError(f"Unerwartete JSON-Struktur von {url}")
            return payload
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
            wait = min(20, attempt * 3)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(str(last))


def paged_features(
    url: str,
    params: dict[str, Any] | None = None,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    payload = request_json(url, params)
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
        payload = request_json(str(next_url))
        features.extend(payload.get("features") or [])
        pages += 1

    return [x for x in features if isinstance(x, dict)]


def prop(feature: dict[str, Any], key: str, default: Any = None) -> Any:
    p = feature.get("properties")
    return p.get(key, default) if isinstance(p, dict) else default


def station_id(feature: dict[str, Any]) -> str:
    return str(prop(feature, "stationId", "")).strip()


def station_country(feature: dict[str, Any]) -> str:
    return str(prop(feature, "country", "")).upper().strip()


def parameter_set(feature: dict[str, Any]) -> set[str]:
    values = prop(feature, "parameterId", [])
    if isinstance(values, str):
        return {values}
    if isinstance(values, list):
        return {str(x) for x in values}
    return set()


def iso_date_prefix(value: Any) -> str | None:
    if value in (None, ""):
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value))
    return m.group(1) if m else None


def operation_start(feature: dict[str, Any]) -> date:
    raw = prop(feature, "operationFrom") or prop(feature, "validFrom")
    day = iso_date_prefix(raw)
    if day:
        try:
            return date.fromisoformat(day)
        except ValueError:
            pass
    return date(9999, 12, 31)


def canonical_station_rows(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feature in features:
        sid = station_id(feature)
        if sid:
            grouped[sid].append(feature)

    out: dict[str, dict[str, Any]] = {}
    for sid, rows in grouped.items():
        parameters: set[str] = set()
        active = False
        starts: list[date] = []
        names: list[str] = []

        for row in rows:
            parameters |= parameter_set(row)
            active = active or str(prop(row, "status", "")).lower() == "active"
            start = operation_start(row)
            if start.year < 9999:
                starts.append(start)
            name = str(prop(row, "name", "")).strip()
            if name:
                names.append(name)

        chosen = sorted(
            rows,
            key=lambda r: (
                str(prop(r, "status", "")).lower() != "active",
                str(prop(r, "validTo", "") or "") != "",
                str(prop(r, "validFrom", "") or ""),
            ),
        )[0]
        coords = (chosen.get("geometry") or {}).get("coordinates") or []

        out[sid] = {
            "id": sid,
            "name": names[-1] if names else sid,
            "active": active,
            "operation_from": min(starts).isoformat() if starts else None,
            "parameters": parameters,
            "lon": coords[0] if len(coords) >= 2 else None,
            "lat": coords[1] if len(coords) >= 2 else None,
            "rows": len(rows),
        }
    return out


def value_features(
    url: str,
    *,
    station: str,
    parameter: str,
    start: date,
    end: date,
    daily: bool,
) -> list[dict[str, Any]]:
    params = {
        "stationId": station,
        "parameterId": parameter,
        "datetime": (
            f"{start.isoformat()}T00:00:00Z/"
            f"{end.isoformat()}T23:59:59Z"
        ),
        "limit": 5000,
    }
    if daily:
        params["timeResolution"] = "day"
    return paged_features(url, params, max_pages=5)


def finite_values(features: list[dict[str, Any]]) -> list[float]:
    result = []
    for f in features:
        try:
            value = float(prop(f, "value"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            result.append(value)
    return result


def summarize_climate_pair(sid: str, start: date, end: date) -> tuple[int, int]:
    tx = value_features(
        CLIMATE_VALUES, station=sid, parameter=CLIMATE_TMAX,
        start=start, end=end, daily=True
    )
    tn = value_features(
        CLIMATE_VALUES, station=sid, parameter=CLIMATE_TMIN,
        start=start, end=end, daily=True
    )
    return len(finite_values(tx)), len(finite_values(tn))


def find_climate_sample(
    stations: dict[str, dict[str, Any]],
    start: date,
    end: date,
    max_candidates: int = 25,
) -> tuple[str, int, int] | None:
    required = {CLIMATE_TMAX, CLIMATE_TMIN}
    candidates = [
        s for s in stations.values()
        if required <= s["parameters"]
        and (s["operation_from"] is None or s["operation_from"] <= end.isoformat())
    ]
    candidates.sort(
        key=lambda s: (
            not s["active"],
            s["operation_from"] or "9999-12-31",
            s["id"],
        )
    )
    for station in candidates[:max_candidates]:
        ntx, ntn = summarize_climate_pair(station["id"], start, end)
        if ntx and ntn:
            return station["id"], ntx, ntn
    return None


def find_metobs_sample(
    stations: dict[str, dict[str, Any]],
    year: int,
    max_candidates: int = 20,
) -> tuple[str, int, int] | None:
    required = {METOBS_TMAX, METOBS_TMIN}
    candidates = [
        s for s in stations.values()
        if required <= s["parameters"]
        and s["operation_from"] is not None
        and s["operation_from"] <= f"{year}-07-03"
    ]
    candidates.sort(key=lambda s: (s["operation_from"], s["id"]))

    start = date(year, 7, 1)
    end = date(year, 7, 3)
    for station in candidates[:max_candidates]:
        tx = value_features(
            METOBS_VALUES, station=station["id"], parameter=METOBS_TMAX,
            start=start, end=end, daily=False
        )
        tn = value_features(
            METOBS_VALUES, station=station["id"], parameter=METOBS_TMIN,
            start=start, end=end, daily=False
        )
        ntx = len(finite_values(tx))
        ntn = len(finite_values(tn))
        if ntx and ntn:
            return station["id"], ntx, ntn
    return None


def head_exists(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return 200 <= response.status < 400, str(response.status)
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, type(exc).__name__


def discover_historical_listing() -> list[str]:
    url = "https://download.dmi.dk/public/opendata/"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            text = response.read(2_000_000).decode("utf-8", errors="replace")
    except Exception as exc:
        log(f"Historische Download-Liste nicht lesbar: {exc}")
        return []

    hrefs = re.findall(r'href=["\']([^"\']+)["\']', text, flags=re.I)
    interesting = sorted({
        urllib.parse.urljoin(url, href)
        for href in hrefs
        if any(token in href.lower() for token in ("histor", "yearbook", "meteor"))
    })
    return interesting[:30]


def run_probe() -> None:
    log("=== DMI DÄNEMARK PROBE ===")
    log("Keine API-Keys/Secrets erforderlich.")
    log()

    climate_features = paged_features(
        CLIMATE_STATIONS,
        {"limit": 1000, "bbox": DENMARK_BBOX},
        max_pages=10,
    )
    climate_dnk = [f for f in climate_features if station_country(f) == "DNK"]
    climate_stations = canonical_station_rows(climate_dnk)

    required = {CLIMATE_TMAX, CLIMATE_TMIN}
    daily_capable = [
        s for s in climate_stations.values() if required <= s["parameters"]
    ]
    active_daily = [s for s in daily_capable if s["active"]]

    log(
        f"climateData: {len(climate_dnk)} Metadatenzeilen | "
        f"{len(climate_stations)} eindeutige DNK-Stationen | "
        f"{len(daily_capable)} mit Tmax+Tmin | "
        f"{len(active_daily)} davon aktiv."
    )
    if not active_daily:
        raise RuntimeError("Keine aktive DNK-Station mit täglichem Tmax+Tmin gefunden.")

    today = datetime.now(timezone.utc).date()
    recent_end = today - timedelta(days=10)
    recent_start = recent_end - timedelta(days=9)

    recent = find_climate_sample(
        climate_stations, recent_start, recent_end, max_candidates=30
    )
    if recent is None:
        raise RuntimeError(
            f"Keine täglichen DMI-Werte für {recent_start}–{recent_end} gefunden."
        )
    recent_sid, recent_tx, recent_tn = recent
    log(
        f"climateData aktuell: Station {recent_sid} | "
        f"{recent_start}–{recent_end} | "
        f"TMAX {recent_tx} Tageswerte | TMIN {recent_tn} Tageswerte."
    )

    old_climate = find_climate_sample(
        climate_stations, date(2011, 7, 1), date(2011, 7, 10), max_candidates=40
    )
    if old_climate is None:
        raise RuntimeError("Im Juli 2011 keine täglichen TMAX+TMIN-Werte gefunden.")
    old_sid, old_tx, old_tn = old_climate
    log(
        f"climateData Historie: Station {old_sid} | Juli 2011 | "
        f"TMAX {old_tx} | TMIN {old_tn}."
    )

    met_features = paged_features(
        METOBS_STATIONS,
        {"limit": 1000, "bbox": DENMARK_BBOX},
        max_pages=10,
    )
    met_dnk = [f for f in met_features if station_country(f) == "DNK"]
    met_stations = canonical_station_rows(met_dnk)

    raw_required = {METOBS_TMAX, METOBS_TMIN}
    raw_capable = [
        s for s in met_stations.values() if raw_required <= s["parameters"]
    ]
    log(
        f"metObs: {len(met_dnk)} Metadatenzeilen | "
        f"{len(met_stations)} eindeutige DNK-Stationen | "
        f"{len(raw_capable)} mit beiden 1h-Extremparametern."
    )

    found_old = None
    for year in (1960, 1970, 1980, 1990, 2000):
        sample = find_metobs_sample(met_stations, year, max_candidates=30)
        if sample:
            sid, ntx, ntn = sample
            log(
                f"metObs Altbestand: {year} erfolgreich | Station {sid} | "
                f"TMAX-1h {ntx} Werte | TMIN-1h {ntn} Werte."
            )
            found_old = (year, sid)
            break
        log(f"metObs Altbestand: {year} im Probe-Sample noch ohne Treffer.")

    if found_old is None:
        raise RuntimeError(
            "Kein historischer metObs-Probe-Treffer 1960–2000 für beide "
            "Extremparameter gefunden."
        )

    bulk_tests = [
        ("metObs 1953", f"{BASE}/metObs/bulk/1953/1953.zip"),
        ("metObs 2025", f"{BASE}/metObs/bulk/2025/2025.zip"),
        (
            "climateData stationValue 2011",
            f"{BASE}/climateData/bulk/stationValue/2011/2011.zip",
        ),
        (
            "climateData stationValue 2025",
            f"{BASE}/climateData/bulk/stationValue/2025/2025.zip",
        ),
    ]
    bulk_ok = 0
    for label, url in bulk_tests:
        ok, status = head_exists(url)
        log(f"Bulk {label}: {'OK' if ok else 'nicht bestätigt'} ({status})")
        bulk_ok += int(ok)

    if bulk_ok < 2:
        log("WARNUNG: Bulk per HEAD nur teilweise bestätigt; API-Proben sind separat.")

    historical_links = discover_historical_listing()
    if historical_links:
        log("Historische 1867–1983-Downloadhinweise gefunden:")
        for link in historical_links:
            log(f"  {link}")
    else:
        log(
            "Historische 1867–1983-Dateien im Root nicht automatisch erkannt; "
            "für die 1953+-Baseline ist das optional."
        )

    log()
    log("=== DMI DENMARK PROBE SUMMARY ===")
    log(f"climateData DNK eindeutig: {len(climate_stations)}")
    log(f"climateData TMAX+TMIN-fähig: {len(daily_capable)}")
    log(f"climateData aktiv TMAX+TMIN: {len(active_daily)}")
    log(f"metObs DNK eindeutig: {len(met_stations)}")
    log(f"metObs beide 1h-Extremparameter: {len(raw_capable)}")
    log(f"ältester erfolgreicher Probe-Jahrgang: {found_old[0]}")
    log(f"aktueller Tagesdaten-Test: Station {recent_sid}")
    log("DMI Denmark Probe OK.")


def self_test() -> None:
    fake = [
        {
            "geometry": {"coordinates": [12.0, 55.0]},
            "properties": {
                "stationId": "06180",
                "name": "Test",
                "country": "DNK",
                "status": "Active",
                "parameterId": [CLIMATE_TMAX],
                "operationFrom": "1983-06-16T00:00:00Z",
                "validFrom": "1983-06-16T00:00:00Z",
                "validTo": "2019-01-01T00:00:00Z",
            },
        },
        {
            "geometry": {"coordinates": [12.1, 55.1]},
            "properties": {
                "stationId": "06180",
                "name": "Test",
                "country": "DNK",
                "status": "Active",
                "parameterId": [CLIMATE_TMIN],
                "operationFrom": "1983-06-16T00:00:00Z",
                "validFrom": "2019-01-01T00:00:00Z",
                "validTo": None,
            },
        },
    ]
    combined = canonical_station_rows(fake)
    assert set(combined) == {"06180"}
    assert combined["06180"]["active"] is True
    assert {CLIMATE_TMAX, CLIMATE_TMIN} <= combined["06180"]["parameters"]
    assert combined["06180"]["operation_from"] == "1983-06-16"

    vals = finite_values([
        {"properties": {"value": 20}},
        {"properties": {"value": "21.5"}},
        {"properties": {"value": None}},
    ])
    assert vals == [20.0, 21.5]
    print("DMI Denmark probe self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
    else:
        run_probe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
