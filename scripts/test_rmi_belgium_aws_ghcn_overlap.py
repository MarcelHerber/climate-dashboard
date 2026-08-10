#!/usr/bin/env python3
"""
Belgium RMI/KMI AWS vs NOAA GHCN-Daily overlap probe.

Purpose:
- KMI/RMI aws:aws_1day gives official full-day Tmin/Tmax from 2000 onward.
- KMI/RMI SYNOP has different reporting windows and is not a seamless bridge.
- GHCN-Daily contains very long Belgian daily TMAX/TMIN records, including
  Uccle (BE000006447).

This probe maps Belgian RMI station code -> Belgian GHCN station(s) by the
5-digit WMO/local suffix and compares daily AWS Tmin/Tmax with GHCN TMIN/TMAX
during an overlap year.

Only GHCN TMAX/TMIN values with blank Q-FLAG are used.

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
from collections import defaultdict
from datetime import date, datetime
from typing import Any

RMI_WFS = "https://opendata.meteo.be/geoserver/ows"
AWS_STATION = "aws:aws_station"
AWS_DAY = "aws:aws_1day"

GHCN_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
GHCN_STATIONS = f"{GHCN_BASE}/ghcnd-stations.txt"
GHCN_ALL = f"{GHCN_BASE}/all"

UA = "climate-dashboard-rmi-belgium-ghcn-overlap/3.0"
TRIES = 5
TIMEOUT = 120


def log(msg: str = "") -> None:
    print(msg, flush=True)


def request_bytes(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    accept: str = "*/*",
    allow_404: bool = False,
) -> bytes | None:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
            params, doseq=True
        )

    last = None
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
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404 and allow_404:
                return None
            if exc.code in {408, 429, 500, 502, 503, 504} and attempt < TRIES:
                time.sleep(min(20, attempt * 4))
                continue
            raise
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            last = exc
            if attempt >= TRIES:
                break
            time.sleep(min(20, attempt * 4))
    raise RuntimeError(f"Abruf fehlgeschlagen {url}: {last}")


def wfs_features(
    typename: str,
    *,
    count: int,
    cql_filter: str | None = None,
    property_names: tuple[str, ...] | None = None,
    sort_by: str | None = None,
) -> list[dict[str, Any]]:
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
    if property_names:
        params["propertyName"] = ",".join(property_names)
    if sort_by:
        params["sortBy"] = sort_by

    raw = request_bytes(
        RMI_WFS,
        params=params,
        accept="application/json,*/*",
    )
    if not raw:
        return []
    payload = json.loads(raw.decode("utf-8"))
    result = []
    for feature in payload.get("features") or []:
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict):
            result.append(feature["properties"])
    return result


def station_codes() -> set[int]:
    rows = wfs_features(
        AWS_STATION,
        count=1000,
        property_names=("code",),
    )
    out = set()
    for row in rows:
        try:
            out.add(int(row.get("code")))
        except (TypeError, ValueError):
            pass
    return out


def parse_ghcn_station_catalog(raw: bytes) -> dict[str, dict[str, Any]]:
    text = raw.decode("ascii", errors="replace")
    out = {}
    for line in text.splitlines():
        if len(line) < 71:
            continue
        sid = line[0:11].strip()
        if not sid.startswith("BE"):
            continue
        try:
            lat = float(line[12:20])
            lon = float(line[21:30])
            elev = float(line[31:37])
        except ValueError:
            lat = lon = elev = None
        name = line[41:71].strip()
        out[sid] = {
            "id": sid,
            "lat": lat,
            "lon": lon,
            "elev": elev,
            "name": name,
        }
    return out


def suffix5(sid: str) -> str:
    digits = "".join(ch for ch in sid if ch.isdigit())
    return digits[-5:].zfill(5) if digits else ""


def map_rmi_to_ghcn(
    codes: set[int],
    catalog: dict[str, dict[str, Any]],
) -> dict[int, list[str]]:
    by_suffix: dict[str, list[str]] = defaultdict(list)
    for sid in catalog:
        sfx = suffix5(sid)
        if sfx:
            by_suffix[sfx].append(sid)

    out = {}
    for code in sorted(codes):
        key = str(code).zfill(5)
        matches = sorted(by_suffix.get(key, []))
        if matches:
            out[code] = matches
    return out


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


def fetch_aws(code: int, year: int) -> dict[date, tuple[float | None, float | None]]:
    start = f"{year}-01-01T00:00:00Z"
    end = f"{year+1}-01-01T00:00:00Z"
    cql = (
        f"code = {code} AND timestamp >= '{start}' AND timestamp < '{end}'"
    )
    rows = wfs_features(
        AWS_DAY,
        count=500,
        cql_filter=cql,
        property_names=("code", "timestamp", "temp_min", "temp_max"),
        sort_by="timestamp A",
    )
    out = {}
    for row in rows:
        d = parse_iso_day(row.get("timestamp"))
        if d is None or d.year != year:
            continue
        out[d] = (
            fvalue(row.get("temp_min")),
            fvalue(row.get("temp_max")),
        )
    return out


def parse_dly_year(
    raw: bytes,
    year: int,
) -> dict[date, dict[str, float]]:
    text = raw.decode("ascii", errors="replace")
    out: dict[date, dict[str, float]] = defaultdict(dict)

    for line in text.splitlines():
        if len(line) < 269:
            continue
        try:
            y = int(line[11:15])
            month = int(line[15:17])
        except ValueError:
            continue
        if y != year:
            continue

        element = line[17:21]
        if element not in {"TMAX", "TMIN"}:
            continue

        for day in range(1, 32):
            pos = 21 + (day - 1) * 8
            block = line[pos:pos+8]
            if len(block) < 8:
                continue
            raw_value = block[0:5]
            qflag = block[6:7]
            try:
                value = int(raw_value)
            except ValueError:
                continue
            if value == -9999 or qflag.strip():
                continue
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            out[d][element] = value / 10.0

    return out


def fetch_ghcn(sid: str, year: int) -> dict[date, tuple[float | None, float | None]]:
    raw = request_bytes(
        f"{GHCN_ALL}/{sid}.dly",
        allow_404=True,
    )
    if not raw:
        return {}
    parsed = parse_dly_year(raw, year)
    return {
        d: (vals.get("TMIN"), vals.get("TMAX"))
        for d, vals in parsed.items()
    }


def metric(pairs: list[tuple[float, float]]) -> dict[str, Any]:
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

    diffs = [a - b for a, b in pairs]
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
    log(f"  mittlere Differenz AWS-GHCN: {m['mean_signed_diff']:+.3f}°C")
    log(f"  mittlere absolute Differenz: {m['mean_abs_diff']:.3f}°C")
    log(f"  maximale absolute Differenz: {m['max_abs_diff']:.2f}°C")


def compare(
    code: int,
    sid: str,
    year: int,
) -> dict[str, Any]:
    aws = fetch_aws(code, year)
    ghcn = fetch_ghcn(sid, year)

    common = sorted(set(aws) & set(ghcn))
    tmin_pairs = []
    tmax_pairs = []

    for d in common:
        a_tn, a_tx = aws[d]
        g_tn, g_tx = ghcn[d]
        if a_tn is not None and g_tn is not None:
            tmin_pairs.append((a_tn, g_tn))
        if a_tx is not None and g_tx is not None:
            tmax_pairs.append((a_tx, g_tx))

    return {
        "code": code,
        "sid": sid,
        "aws_days": len(aws),
        "ghcn_days": len(ghcn),
        "common_days": len(common),
        "tmin": metric(tmin_pairs),
        "tmax": metric(tmax_pairs),
    }


def run_probe(year: int, max_stations: int) -> None:
    log("=== KMI/RMI BELGIEN AWS-vs-GHCN OVERLAP ===")
    log(f"Vergleichsjahr: {year}")
    log("GHCN: nur TMAX/TMIN mit leerem Q-FLAG.")
    log()

    codes = station_codes()
    catalog_raw = request_bytes(GHCN_STATIONS)
    if not catalog_raw:
        raise RuntimeError("GHCN station catalog leer.")
    catalog = parse_ghcn_station_catalog(catalog_raw)
    mapping = map_rmi_to_ghcn(codes, catalog)

    log(f"KMI/RMI AWS Stationscodes: {len(codes)}")
    log(f"GHCN belgische Stationen: {len(catalog)}")
    log(f"Per 5-stelligem Code gemappte AWS-Stationen: {len(mapping)}")

    if 6447 in mapping:
        log(f"Uccle 06447 Mapping: {mapping[6447]}")

    if not mapping:
        raise RuntimeError("Keine AWS↔GHCN Stationszuordnung gefunden.")

    results = []
    for code, sids in mapping.items():
        best = None
        for sid in sids:
            try:
                candidate = compare(code, sid, year)
            except Exception as exc:
                log(f"WARNUNG {code}/{sid}: {exc}")
                continue
            score = candidate["tmin"]["n"] + candidate["tmax"]["n"]
            if best is None or score > (
                best["tmin"]["n"] + best["tmax"]["n"]
            ):
                best = candidate

        if best is None or (
            best["tmin"]["n"] < 30 and best["tmax"]["n"] < 30
        ):
            continue

        results.append(best)
        meta = catalog.get(best["sid"], {})
        log()
        log(
            f"Station {code} ↔ {best['sid']} "
            f"({meta.get('name','')}) | AWS {best['aws_days']} Tage | "
            f"GHCN {best['ghcn_days']} Tage | gemeinsam {best['common_days']}"
        )
        fmt_metric("TMIN", best["tmin"])
        fmt_metric("TMAX", best["tmax"])

        if len(results) >= max_stations:
            break

    if not results:
        raise RuntimeError("Keine brauchbaren AWS↔GHCN Overlap-Stationen.")

    totals = {
        "tmin": {"n": 0, "exact": 0, "w01": 0, "w05": 0},
        "tmax": {"n": 0, "exact": 0, "w01": 0, "w05": 0},
    }

    for result in results:
        for key in ("tmin", "tmax"):
            m = result[key]
            n = int(m["n"])
            if not n:
                continue
            totals[key]["n"] += n
            totals[key]["exact"] += round(m["exact_0.01"] * n)
            totals[key]["w01"] += round(m["within_0.1"] * n)
            totals[key]["w05"] += round(m["within_0.5"] * n)

    log()
    log("=== BELGIUM GHCN OVERLAP SUMMARY ===")
    log(f"Ausgewertete gemappte Stationen: {len(results)}")
    for key, label in (("tmin", "TMIN"), ("tmax", "TMAX")):
        t = totals[key]
        if not t["n"]:
            continue
        log(
            f"{label} gesamt n={t['n']}: identisch "
            f"{100*t['exact']/t['n']:.1f}% | ±0.1°C "
            f"{100*t['w01']/t['n']:.1f}% | ±0.5°C "
            f"{100*t['w05']/t['n']:.1f}%"
        )

    log()
    log("Interpretation:")
    log(
        "Wenn GHCN deutlich näher an AWS liegt als SYNOP, ist GHCN die "
        "bessere historische Brücke. Falls auch GHCN deutlich abweicht, "
        "bleibt KMI/RMI AWS ab 2000 die einzige nahtlos vergleichbare "
        "nationale Tagesreihe."
    )
    log("KMI/RMI Belgium GHCN overlap probe OK.")


def self_test() -> None:
    sample = (
        b"BE000006447  50.8000    4.3500  100.0    UCCLE                         \n"
    )
    cat = parse_ghcn_station_catalog(sample)
    assert "BE000006447" in cat
    assert suffix5("BE000006447") == "06447"
    mapping = map_rmi_to_ghcn({6447}, cat)
    assert mapping[6447] == ["BE000006447"]

    # Minimal valid .dly line with Jan TMAX day 1 = -14 tenths, blank qflag.
    prefix = "BE000006447202501TMAX"
    blocks = []
    for day in range(1, 32):
        if day == 1:
            blocks.append(f"{-14:5d}   ")
        else:
            blocks.append(f"{-9999:5d}   ")
    raw = (prefix + "".join(blocks) + "\n").encode("ascii")
    parsed = parse_dly_year(raw, 2025)
    assert parsed[date(2025, 1, 1)]["TMAX"] == -1.4

    print("KMI/RMI Belgium GHCN overlap probe self-test OK")


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
