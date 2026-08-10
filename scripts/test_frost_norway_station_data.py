#!/usr/bin/env python3
"""
Probe MET Norway Frost API for Norwegian daily station temperature extremes.

This is a read-only diagnostic. It does NOT build a historical baseline and
does NOT modify Europe station output files.

Checks:
- authenticated Frost access
- Norwegian SensorSystem station metadata
- stations offering BOTH daily max/min air temperature
- station-holder distribution
- historical daily Tmax/Tmin sample
- current-year daily Tmax/Tmin sample when available
- time offset / resolution / quality metadata

Required environment variable:
    FROST_CLIENT_ID
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any


API = "https://frost.met.no"
SOURCE = "MET Norway Frost"
TMAX = "max(air_temperature P1D)"
TMIN = "min(air_temperature P1D)"
ELEMENTS = f"{TMAX},{TMIN}"
KNOWN_STATION = "SN18700"  # Oslo - Blindern
USER_AGENT = "climate-dashboard-frost-norway-probe/1.0"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def auth_header(client_id: str) -> str:
    token = base64.b64encode(f"{client_id}:".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_json(
    path: str,
    client_id: str,
    params: dict[str, Any] | None = None,
    *,
    allow_404: bool = False,
    timeout: int = 120,
) -> dict[str, Any] | None:
    url = API + path
    if params:
        clean = {
            k: str(v)
            for k, v in params.items()
            if v is not None and str(v) != ""
        }
        url += "?" + urllib.parse.urlencode(clean, safe="(),:*")

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": auth_header(client_id),
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if allow_404 and exc.code in (404, 412):
            return None
        raise RuntimeError(
            f"Frost HTTP {exc.code} für {path}: {body[:1000]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Frost Netzwerkfehler für {path}: {exc}") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Frost-Antwort für {path} ist kein gültiges JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Unerwarteter Frost-Antworttyp für {path}: {type(payload).__name__}"
        )
    return payload


def data_list(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def holder_names(source: dict[str, Any]) -> list[str]:
    values: list[str] = []

    for key in (
        "stationHolders",
        "stationholders",
        "stationHolder",
        "stationholder",
    ):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    values.append(item.strip())
                elif isinstance(item, dict):
                    for subkey in ("name", "id", "shortName"):
                        sub = item.get(subkey)
                        if isinstance(sub, str) and sub.strip():
                            values.append(sub.strip())
                            break

    return values or ["<nicht angegeben>"]


def source_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("sourceId") or "").split(":")[0]


def source_name(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("shortName") or source_id(row))


def geometry_point(row: dict[str, Any]) -> tuple[float | None, float | None]:
    geometry = row.get("geometry")
    if not isinstance(geometry, dict):
        return None, None

    coords = geometry.get("coordinates")
    if (
        isinstance(coords, list)
        and len(coords) >= 2
        and isinstance(coords[0], (int, float))
        and isinstance(coords[1], (int, float))
    ):
        return float(coords[1]), float(coords[0])

    return None, None


def fetch_norway_sources(client_id: str) -> list[dict[str, Any]]:
    # Frost source filtering supports an `elements` filter; requesting both
    # elements means returned sources should offer both daily extrema.
    payload = get_json(
        "/sources/v0.jsonld",
        client_id,
        {
            "types": "SensorSystem",
            "country": "NO",
            "elements": ELEMENTS,
        },
    )
    rows = data_list(payload)
    if not rows:
        raise RuntimeError(
            "Frost lieferte keine norwegischen SensorSystem-Quellen mit "
            "täglichem Tmax UND Tmin."
        )
    return rows


def observation_rows(
    client_id: str,
    station: str,
    start: dt.date,
    end: dt.date,
) -> list[dict[str, Any]]:
    payload = get_json(
        "/observations/v0.jsonld",
        client_id,
        {
            "sources": station,
            "referencetime": f"{start.isoformat()}/{end.isoformat()}",
            "elements": ELEMENTS,
            # Frost documentation recommends defaults to avoid parallel/
            # nonstandard series. For daily temperature extrema this selects
            # the standard daily series, typically PT18H.
            "timeoffsets": "default",
            "levels": "default",
        },
        allow_404=True,
    )
    return data_list(payload)


def flatten_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []

    for row in rows:
        sid = str(row.get("sourceId") or "")
        ref = str(row.get("referenceTime") or "")
        obs = row.get("observations")
        if not isinstance(obs, list):
            continue

        for item in obs:
            if not isinstance(item, dict):
                continue

            element = str(item.get("elementId") or "")
            if element not in (TMAX, TMIN):
                continue

            try:
                value = float(item.get("value"))
            except (TypeError, ValueError):
                continue

            if not math.isfinite(value) or not (-60.0 <= value <= 60.0):
                raise RuntimeError(
                    f"Unplausibler Frost-Temperaturwert {value} für {sid} {ref}."
                )

            flat.append(
                {
                    "sourceId": sid,
                    "referenceTime": ref,
                    "elementId": element,
                    "value": value,
                    "unit": item.get("unit"),
                    "timeOffset": item.get("timeOffset"),
                    "timeResolution": item.get("timeResolution"),
                    "qualityCode": item.get("qualityCode"),
                    "performanceCategory": item.get("performanceCategory"),
                    "exposureCategory": item.get("exposureCategory"),
                }
            )

    return flat


def check_sample(
    client_id: str,
    station: str,
    start: dt.date,
    end: dt.date,
    label: str,
    *,
    required: bool,
) -> list[dict[str, Any]]:
    rows = observation_rows(client_id, station, start, end)
    flat = flatten_observations(rows)

    log(f"\n=== {label} ===")
    log(f"Station: {station} | Zeitraum: {start} bis {end}")
    log(f"Frost-Zeitpunkte: {len(rows)} | Temperaturwerte: {len(flat)}")

    if not flat:
        if required:
            raise RuntimeError(
                f"Keine täglichen Tmax/Tmin-Werte für Pflichtprobe {label}."
            )
        log("WARNUNG: Für diese optionale Probe wurden keine Werte geliefert.")
        return []

    elements = Counter(x["elementId"] for x in flat)
    log(f"Elemente: {dict(elements)}")

    for item in flat[:12]:
        log(
            "  "
            f"{item['referenceTime']} | {item['elementId']}="
            f"{item['value']} {item['unit'] or ''} | "
            f"offset={item['timeOffset']} | "
            f"resolution={item['timeResolution']} | "
            f"quality={item['qualityCode']}"
        )

    if not all(e in elements for e in (TMAX, TMIN)):
        if required:
            raise RuntimeError(
                f"Pflichtprobe enthält nicht beide Tagesextreme: {dict(elements)}"
            )
        log(
            "WARNUNG: Optionale aktuelle Probe enthält derzeit nicht beide "
            "Tagesextreme."
        )

    return flat


def self_test() -> None:
    h = auth_header("abc")
    assert h.startswith("Basic ")
    assert base64.b64decode(h.split()[1]).decode() == "abc:"

    sample = [
        {
            "sourceId": "SN1:0",
            "referenceTime": "2020-01-01T18:00:00.000Z",
            "observations": [
                {
                    "elementId": TMAX,
                    "value": 12.3,
                    "unit": "degC",
                    "timeOffset": "PT18H",
                    "timeResolution": "P1D",
                    "qualityCode": 0,
                },
                {
                    "elementId": TMIN,
                    "value": -4.5,
                    "unit": "degC",
                    "timeOffset": "PT18H",
                    "timeResolution": "P1D",
                    "qualityCode": 1,
                },
            ],
        }
    ]
    flat = flatten_observations(sample)
    assert len(flat) == 2
    assert {x["elementId"] for x in flat} == {TMAX, TMIN}
    assert {x["timeOffset"] for x in flat} == {"PT18H"}
    assert source_id({"id": "SN18700:0"}) == "SN18700"
    print("Frost Norway station probe self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    client_id = os.environ.get("FROST_CLIENT_ID", "").strip()
    if not client_id:
        raise SystemExit(
            "FROST_CLIENT_ID fehlt. Bitte den kostenlosen MET Norway Frost "
            "Client ID als GitHub Actions Repository-Secret anlegen."
        )

    log("=== MET NORWAY / FROST PROBE ===")
    log("Authentifizierung: FROST_CLIENT_ID")
    log(f"Gesuchte Tageswerte: {TMAX} + {TMIN}")

    sources = fetch_norway_sources(client_id)
    ids = [source_id(x) for x in sources if source_id(x)]

    log(f"\nNorwegische SensorSystem-Quellen mit beiden Tagesextremen: {len(ids)}")

    holder_counter: Counter[str] = Counter()
    for row in sources:
        for holder in holder_names(row):
            holder_counter[holder] += 1

    log("Häufigste Stationshalter:")
    for holder, count in holder_counter.most_common(15):
        log(f"  - {holder}: {count}")

    log("\nStationsbeispiele:")
    for row in sources[:15]:
        sid = source_id(row)
        lat, lon = geometry_point(row)
        log(
            f"  - {sid} | {source_name(row)} | "
            f"lat={lat} lon={lon} | "
            f"validFrom={row.get('validFrom')} validTo={row.get('validTo')} | "
            f"holder={', '.join(holder_names(row))}"
        )

    station = KNOWN_STATION if KNOWN_STATION in ids else ids[0]
    log(f"\nTeststation: {station}")

    # Stable historical test period.
    historical = check_sample(
        client_id,
        station,
        dt.date(2024, 7, 1),
        dt.date(2024, 7, 10),
        "Historische Tageswertprobe",
        required=True,
    )

    # Current-year test. Use a recent fixed summer interval in the current year;
    # if the station did not report that interval, this remains a warning only.
    current_year = dt.datetime.now(dt.timezone.utc).year
    current = check_sample(
        client_id,
        station,
        dt.date(current_year, 7, 1),
        dt.date(current_year, 7, 10),
        f"Aktuelles Jahr {current_year}",
        required=False,
    )

    offsets = Counter(
        str(x.get("timeOffset"))
        for x in historical + current
        if x.get("timeOffset") is not None
    )
    resolutions = Counter(
        str(x.get("timeResolution"))
        for x in historical + current
        if x.get("timeResolution") is not None
    )
    qualities = Counter(
        str(x.get("qualityCode"))
        for x in historical + current
        if x.get("qualityCode") is not None
    )

    log("\n=== PROBE-ZUSAMMENFASSUNG ===")
    log(f"Quellen mit Tmax+Tmin: {len(ids)}")
    log(f"Bevorzugte Zeitoffsets im Sample: {dict(offsets)}")
    log(f"Zeitauflösungen im Sample: {dict(resolutions)}")
    log(f"Quality-Codes im Sample: {dict(qualities)}")
    log("Frost Norway Probe OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
