#!/usr/bin/env python3
"""
RMI/KMI Belgium AWS-vs-SYNOP overlap validation.

Purpose:
The official daily AWS layer (aws:aws_1day) starts in 2000 and uses a full
daily aggregation window. The official SYNOP archive reaches back to 1952,
but TEMP_MIN/TEMP_MAX use 18-06 UTC / 06-18 UTC reporting windows.

Before using SYNOP as a 1952-1999 historical bridge, compare both official
products on matching station codes and calendar dates.

No API key / secret is required.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime
from typing import Any

ENDPOINT = "https://opendata.meteo.be/geoserver/ows"
AWS_STATION = "aws:aws_station"
AWS_DAY = "aws:aws_1day"
SYNOP_STATION = "synop:synop_station"
SYNOP_DATA = "synop:synop_data"

UA = "climate-dashboard-rmi-belgium-overlap-probe/2.0"
TRIES = 5
TIMEOUT = 120


def log(msg: str = "") -> None:
    print(msg, flush=True)


def request_bytes(
    *,
    params: dict[str, Any],
    accept: str = "*/*",
) -> bytes:
    query = urllib.parse.urlencode(params, doseq=True)
    url = ENDPOINT + "?" + query
    last: Exception | None = None

    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": accept,
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            last = exc
            retryable = (
                not isinstance(exc, urllib.error.HTTPError)
                or exc.code in {408, 429, 500, 502, 503, 504}
            )
            if attempt >= TRIES or not retryable:
                raise
            wait = min(25, attempt * 4)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)

    raise RuntimeError(str(last))


def get_features(
    typename: str,
    *,
    count: int,
    cql_filter: str | None = None,
    sort_by: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": typename,
        "outputFormat": "application/json",
        "count": count,
    }
    if cql_filter:
        params["CQL_FILTER"] = cql_filter
    if sort_by:
        params["sortBy"] = sort_by

    raw = request_bytes(params=params, accept="application/json,*/*")
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"{typename}: keine GeoJSON-Objektantwort.")
    return obj


def properties(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for feature in payload.get("features") or []:
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict):
            out.append(feature["properties"])
    return out


def station_codes(typename: str) -> set[int]:
    payload = get_features(typename, count=5000)
    result = set()
    for row in properties(payload):
        value = row.get("code")
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def parse_iso_day(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def fvalue(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x < -90 or x > 65:
        return None
    return x


def code_filter(code: int) -> str:
    return f"code = {code}"


def time_filter(start: str, end: str) -> str:
    return f"timestamp DURING {start}T00:00:00Z/{end}T23:59:59Z"


def fetch_aws(
    code: int,
    start: str,
    end: str,
) -> dict[date, tuple[float | None, float | None]]:
    cql = f"{code_filter(code)} AND {time_filter(start, end)}"
    rows = properties(
        get_features(
            AWS_DAY,
            count=2000,
            cql_filter=cql,
            sort_by="timestamp A",
        )
    )

    out = {}
    for row in rows:
        d = parse_iso_day(row.get("timestamp"))
        if d is None:
            continue
        out[d] = (
            fvalue(row.get("temp_min")),
            fvalue(row.get("temp_max")),
        )
    return out


def fetch_synop(
    code: int,
    start: str,
    end: str,
) -> dict[date, tuple[float | None, float | None]]:
    # Filter down to daily extremes so one year remains small.
    cql = (
        f"{code_filter(code)} AND {time_filter(start, end)} AND "
        "(temp_min IS NOT NULL OR temp_max IS NOT NULL)"
    )
    rows = properties(
        get_features(
            SYNOP_DATA,
            count=3000,
            cql_filter=cql,
            sort_by="timestamp A",
        )
    )

    by_day: dict[date, dict[str, float]] = defaultdict(dict)
    for row in rows:
        d = parse_iso_day(row.get("timestamp"))
        if d is None:
            continue
        tn = fvalue(row.get("temp_min"))
        tx = fvalue(row.get("temp_max"))
        if tn is not None:
            by_day[d]["TMIN"] = tn
        if tx is not None:
            by_day[d]["TMAX"] = tx

    return {
        d: (vals.get("TMIN"), vals.get("TMAX"))
        for d, vals in by_day.items()
    }


def metric(
    pairs: list[tuple[float, float]],
) -> dict[str, float | int | None]:
    if not pairs:
        return {
            "n": 0,
            "exact_0.01": None,
            "within_0.1": None,
            "within_0.5": None,
            "mean_signed_diff": None,
            "mean_abs_diff": None,
            "max_abs_diff": None,
        }

    diffs = [a - s for a, s in pairs]
    absdiff = [abs(x) for x in diffs]
    n = len(pairs)
    return {
        "n": n,
        "exact_0.01": sum(x <= 0.011 for x in absdiff) / n,
        "within_0.1": sum(x <= 0.101 for x in absdiff) / n,
        "within_0.5": sum(x <= 0.501 for x in absdiff) / n,
        "mean_signed_diff": statistics.mean(diffs),
        "mean_abs_diff": statistics.mean(absdiff),
        "max_abs_diff": max(absdiff),
    }


def fmt_metric(label: str, m: dict[str, Any]) -> None:
    log(f"{label}: n={m['n']}")
    if not m["n"]:
        return
    log(f"  identisch ±0.01°C: {100*m['exact_0.01']:.1f}%")
    log(f"  innerhalb ±0.1°C: {100*m['within_0.1']:.1f}%")
    log(f"  innerhalb ±0.5°C: {100*m['within_0.5']:.1f}%")
    log(f"  mittlere Differenz AWS-SYNOP: {m['mean_signed_diff']:+.3f}°C")
    log(f"  mittlere absolute Differenz: {m['mean_abs_diff']:.3f}°C")
    log(f"  maximale absolute Differenz: {m['max_abs_diff']:.2f}°C")


def compare_station(
    code: int,
    start: str,
    end: str,
) -> dict[str, Any]:
    aws = fetch_aws(code, start, end)
    syn = fetch_synop(code, start, end)

    common = sorted(set(aws) & set(syn))
    tmin_pairs = []
    tmax_pairs = []

    for d in common:
        a_tn, a_tx = aws[d]
        s_tn, s_tx = syn[d]
        if a_tn is not None and s_tn is not None:
            tmin_pairs.append((a_tn, s_tn))
        if a_tx is not None and s_tx is not None:
            tmax_pairs.append((a_tx, s_tx))

    return {
        "code": code,
        "aws_days": len(aws),
        "synop_days": len(syn),
        "common_days": len(common),
        "tmin": metric(tmin_pairs),
        "tmax": metric(tmax_pairs),
    }


def run_probe(year: int, max_stations: int) -> None:
    log("=== KMI/RMI BELGIEN AWS-vs-SYNOP OVERLAP ===")
    log(f"Vergleichsjahr: {year}")
    log("AWS: Tagesaggregation 00:10 D bis 00:00 D+1.")
    log("SYNOP: Tmin 18–06 UTC, Tmax 06–18 UTC.")
    log()

    aws_codes = station_codes(AWS_STATION)
    syn_codes = station_codes(SYNOP_STATION)
    common_codes = sorted(aws_codes & syn_codes)

    log(f"AWS Stationscodes: {len(aws_codes)}")
    log(f"SYNOP Stationscodes: {len(syn_codes)}")
    log(f"Gemeinsame Stationscodes: {len(common_codes)}")

    if not common_codes:
        raise RuntimeError("Keine gemeinsamen AWS/SYNOP-Stationscodes.")

    start = f"{year}-01-01"
    end = f"{year}-12-31"

    station_results = []
    for code in common_codes:
        try:
            result = compare_station(code, start, end)
        except Exception as exc:
            log(f"WARNUNG Station {code}: {exc}")
            continue

        # only useful overlapping stations
        if result["tmin"]["n"] < 30 and result["tmax"]["n"] < 30:
            continue

        station_results.append(result)
        log()
        log(
            f"Station {code}: AWS {result['aws_days']} Tage | "
            f"SYNOP {result['synop_days']} Tage | "
            f"gemeinsam {result['common_days']}"
        )
        fmt_metric("TMIN", result["tmin"])
        fmt_metric("TMAX", result["tmax"])

        if len(station_results) >= max_stations:
            break

    if not station_results:
        raise RuntimeError(
            "Kein brauchbarer AWS/SYNOP-Überlappungsvergleich gefunden."
        )

    all_tn_exact_num = all_tn_n = 0
    all_tx_exact_num = all_tx_n = 0
    all_tn_w01_num = all_tx_w01_num = 0
    all_tn_w05_num = all_tx_w05_num = 0

    # Aggregate fractions by their underlying n.
    for result in station_results:
        for key, prefix in (("tmin", "tn"), ("tmax", "tx")):
            m = result[key]
            n = int(m["n"])
            if not n:
                continue
            if prefix == "tn":
                all_tn_n += n
                all_tn_exact_num += round(m["exact_0.01"] * n)
                all_tn_w01_num += round(m["within_0.1"] * n)
                all_tn_w05_num += round(m["within_0.5"] * n)
            else:
                all_tx_n += n
                all_tx_exact_num += round(m["exact_0.01"] * n)
                all_tx_w01_num += round(m["within_0.1"] * n)
                all_tx_w05_num += round(m["within_0.5"] * n)

    log()
    log("=== BELGIUM OVERLAP SUMMARY ===")
    log(f"Ausgewertete gemeinsame Stationen: {len(station_results)}")
    if all_tn_n:
        log(
            f"TMIN gesamt n={all_tn_n}: identisch "
            f"{100*all_tn_exact_num/all_tn_n:.1f}% | ±0.1°C "
            f"{100*all_tn_w01_num/all_tn_n:.1f}% | ±0.5°C "
            f"{100*all_tn_w05_num/all_tn_n:.1f}%"
        )
    if all_tx_n:
        log(
            f"TMAX gesamt n={all_tx_n}: identisch "
            f"{100*all_tx_exact_num/all_tx_n:.1f}% | ±0.1°C "
            f"{100*all_tx_w01_num/all_tx_n:.1f}% | ±0.5°C "
            f"{100*all_tx_w05_num/all_tx_n:.1f}%"
        )

    log()
    log("Interpretation:")
    log(
        "Hohe Übereinstimmung → SYNOP kann als transparente historische "
        "1952–1999-Brücke dienen. Größere systematische Unterschiede → "
        "SYNOP nicht blind an AWS-Tagesrekorde anhängen."
    )
    log("KMI/RMI Belgium overlap probe OK.")


def self_test() -> None:
    pairs = [(10.0, 10.0), (11.0, 11.1), (12.0, 11.8)]
    m = metric(pairs)
    assert m["n"] == 3
    assert abs(m["mean_signed_diff"] - (0.0 - 0.1 + 0.2) / 3) < 1e-9

    payload = {
        "features": [
            {"properties": {"code": 6447}},
            {"properties": {"code": "6477"}},
        ]
    }
    assert [x["code"] for x in properties(payload)] == [6447, "6477"]

    assert parse_iso_day("2025-07-01T18:00:00Z") == date(2025, 7, 1)

    print("KMI/RMI Belgium overlap probe self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--max-stations", type=int, default=8)
    args = parser.parse_args()

    if args.self_test:
        self_test()
    else:
        run_probe(args.year, args.max_stations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
