#!/usr/bin/env python3
"""Probe real 2026 ECA&D non-blended UK TX9/TN9 daily observations.

This is deliberately NOT a production cache.

It:
  * reuses the already validated ECA&D UK metadata probe,
  * selects UK stations with downloadable participant/UKMO TX9 + TN9 series
    extending into 2026,
  * keeps only stations which crosswalk cleanly to the completed MIDAS
    historical cache,
  * queries the official EUMETNET MeteoGate / RODEO EDR API,
  * inspects tx9, tn9 and their quality flags,
  * prints the first/last actual 2026 observations and last available date.

The ECA&D RODEO collection queried here is explicitly "ecad-nonblended".
No blended/GTS infilling is requested.
"""
from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from typing import Any

import test_ecad_uk_2026 as meta_probe

BASE_URL = "https://api.meteogate.eu/eu-eumetnet-climate-observations/v1"
COLLECTION = "ecad-nonblended"
START = "2026-01-01T00:00:00Z"
END = "2026-06-30T23:59:59Z"
UA = "climate-dashboard-ecad-uk-daily-probe/2.0 (+GitHub Actions)"

PREFERRED_NAMES = (
    "HEATHROW",
    "ABERPORTH",
    "GOGERDDAN",
    "YEOVILTON",
    "SWANAGE",
    "PLYMOUTH",
    "BUDE",
    "BRAEMAR",
    "BALMORAL",
    "HILLSBOROUGH",
    "LEUCHARS",
    "ROTHAMSTED",
    "WRITTLE",
    "WELLESBOURNE",
    "OXFORD",
    "ESKDALEMUIR",
)

SAMPLE_LIMIT = 16


def log(msg: str = "") -> None:
    print(msg, flush=True)


def request_json(url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        raw = response.read()
    if not raw:
        raise RuntimeError(f"Leere API-Antwort: {url}")
    return json.loads(raw.decode("utf-8"))


def collect_exact_pairs() -> list[dict[str, Any]]:
    targets = {
        "blend_station_tx": (meta_probe.BLEND_STATION_TX, "STAID"),
        "blend_station_tn": (meta_probe.BLEND_STATION_TN, "STAID"),
        "blend_source_tx": (meta_probe.BLEND_SOURCE_TX, "STAID"),
        "blend_source_tn": (meta_probe.BLEND_SOURCE_TN, "STAID"),
        "nonblend_info_tx": (meta_probe.NONBLEND_INFO_TX, "SOUID"),
        "nonblend_info_tn": (meta_probe.NONBLEND_INFO_TN, "SOUID"),
    }

    parsed = {}
    for key, (url, header) in targets.items():
        rows, _ = meta_probe.parse_table(meta_probe.request_text(url), header)
        parsed[key] = rows

    tx_stations = meta_probe.uk_station_map(parsed["blend_station_tx"])
    tn_stations = meta_probe.uk_station_map(parsed["blend_station_tn"])
    tx_sources = meta_probe.uk_blend_sources(parsed["blend_source_tx"])
    tn_sources = meta_probe.uk_blend_sources(parsed["blend_source_tn"])
    nb_tx = meta_probe.uk_nonblend_sources(parsed["nonblend_info_tx"])
    nb_tn = meta_probe.uk_nonblend_sources(parsed["nonblend_info_tn"])

    tx_by_station = meta_probe.group_by_station(tx_sources)
    tn_by_station = meta_probe.group_by_station(tn_sources)

    midas = meta_probe.load_midas_candidates()
    if not midas:
        raise RuntimeError(
            "Vollständiger historischer MIDAS-Cache fehlt im Run. "
            "Der ECA&D-Tagesprobe-Workflow muss den UK-Historiencache "
            "wiederherstellen."
        )

    out = []
    for sid in sorted(set(tx_stations) & set(tn_stations)):
        tx = meta_probe.best_exact_source(tx_by_station.get(sid, []), "TX9")
        tn = meta_probe.best_exact_source(tn_by_station.get(sid, []), "TN9")
        if tx is None or tn is None:
            continue
        if tx["souid"] not in nb_tx or tn["souid"] not in nb_tn:
            continue

        station = tx_stations.get(sid) or tn_stations[sid]
        cw = meta_probe.crosswalk_ecad_to_midas(station, midas)
        if not cw.get("matched"):
            continue

        out.append(
            {
                "staid": sid,
                "station": station,
                "tx": tx,
                "tn": tn,
                "crosswalk": cw,
            }
        )

    return out


def select_samples(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    used = set()

    for wanted in PREFERRED_NAMES:
        for item in pairs:
            if item["staid"] in used:
                continue
            if wanted in meta_probe.normalize_name(item["station"]["name"]):
                selected.append(item)
                used.add(item["staid"])
                break
        if len(selected) >= SAMPLE_LIMIT:
            return selected

    for item in sorted(
        pairs,
        key=lambda x: (
            min(x["tx"].get("stop") or 0, x["tn"].get("stop") or 0),
            x["staid"],
        ),
        reverse=True,
    ):
        if item["staid"] in used:
            continue
        selected.append(item)
        used.add(item["staid"])
        if len(selected) >= SAMPLE_LIMIT:
            break

    return selected


def api_station_id(staid: int) -> str:
    return f"ecad_{staid:07d}"


def flatten_coverage_values(
    obj: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Collect every range from every Coverage in one time-indexed structure."""
    result: dict[str, dict[str, Any]] = {}

    coverages = obj.get("coverages", [])
    if not isinstance(coverages, list):
        return result

    for coverage in coverages:
        if not isinstance(coverage, dict):
            continue

        axes = (
            coverage.get("domain", {})
            .get("axes", {})
        )
        times = axes.get("t", {}).get("values", [])
        ranges = coverage.get("ranges", {})

        if not isinstance(times, list) or not isinstance(ranges, dict):
            continue

        for param, robj in ranges.items():
            if not isinstance(robj, dict):
                continue
            values = robj.get("values", [])
            if not isinstance(values, list):
                continue

            # PointSeries responses are expected to have one value per time.
            if len(values) != len(times):
                continue

            target = result.setdefault(
                param,
                {
                    "times": [],
                    "values": [],
                },
            )
            target["times"].extend(times)
            target["values"].extend(values)

    return result


def normalize_qflag(value: Any) -> str:
    if value is None:
        return "<null>"
    return str(value)


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def pair_rows(
    flat: dict[str, dict[str, Any]],
    value_key: str,
    q_key: str,
) -> list[dict[str, Any]]:
    values = flat.get(value_key, {})
    qvals = flat.get(q_key, {})

    value_map = {
        str(t): v
        for t, v in zip(values.get("times", []), values.get("values", []))
    }
    q_map = {
        str(t): v
        for t, v in zip(qvals.get("times", []), qvals.get("values", []))
    }

    times = sorted(set(value_map) | set(q_map))
    out = []
    for t in times:
        out.append(
            {
                "time": t,
                "value": value_map.get(t),
                "q": q_map.get(t),
            }
        )
    return out


def usable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Probe only: do not decide production QC yet.
    # Keep finite observations and report their flags separately.
    return [row for row in rows if finite(row.get("value"))]


def print_series(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = usable(rows)
    q_counts = Counter(normalize_qflag(row.get("q")) for row in valid)

    log(f"{label}: API-Zeitpunkte={len(rows):,} | numerisch={len(valid):,}")
    log(f"{label} QFLAG-Verteilung: {dict(q_counts.most_common())}")

    if valid:
        log(
            f"{label} erster Wert: "
            f"{valid[0]['time']} | {valid[0]['value']} | q={valid[0].get('q')}"
        )
        log(
            f"{label} letzter Wert: "
            f"{valid[-1]['time']} | {valid[-1]['value']} | q={valid[-1].get('q')}"
        )
        log(f"{label} letzte 3:")
        for row in valid[-3:]:
            log(
                f"  {row['time']} | {row['value']} | q={row.get('q')}"
            )

    return {
        "count": len(valid),
        "first": valid[0]["time"] if valid else None,
        "last": valid[-1]["time"] if valid else None,
        "q_counts": dict(q_counts),
    }


def inspect_station(item: dict[str, Any]) -> dict[str, Any]:
    staid = item["staid"]
    sid = api_station_id(staid)

    params = {
        "datetime": f"{START}/{END}",
        "standard_name": "air_temperature",
    }

    obj = request_json(
        f"{BASE_URL}/collections/{COLLECTION}/locations/{sid}",
        params=params,
    )
    flat = flatten_coverage_values(obj)

    keys = sorted(flat)
    tx_rows = pair_rows(flat, "tx9", "tx9_q")
    tn_rows = pair_rows(flat, "tn9", "tn9_q")

    log()
    log("-" * 86)
    log(
        f"ECA STAID {staid} | {item['station']['name']} | "
        f"MIDAS {item['crosswalk']['midas_key']}"
    )
    log(
        f"Crosswalk: {item['crosswalk']['method']} | "
        f"dist={item['crosswalk'].get('distance_km')} km | "
        f"name_sim={item['crosswalk'].get('name_similarity')}"
    )
    log(
        f"Metadaten: TX SOUID={item['tx']['souid']} "
        f"STOP={item['tx']['stop']} ELEID={item['tx']['eleid']} | "
        f"TN SOUID={item['tn']['souid']} "
        f"STOP={item['tn']['stop']} ELEID={item['tn']['eleid']}"
    )
    log(f"API-ID: {sid}")
    log(f"API-Ranges für air_temperature: {keys}")

    tx = print_series("TX9", tx_rows)
    tn = print_series("TN9", tn_rows)

    return {
        "staid": staid,
        "name": item["station"]["name"],
        "midas_key": item["crosswalk"]["midas_key"],
        "tx_souid": item["tx"]["souid"],
        "tn_souid": item["tn"]["souid"],
        "tx_metadata_stop": item["tx"]["stop"],
        "tn_metadata_stop": item["tn"]["stop"],
        "ranges": keys,
        "tx": tx,
        "tn": tn,
    }


def main() -> int:
    log("=== ECA&D UK 2026 DAILY DATA PROBE ===")
    log("Collection: ecad-nonblended")
    log("Zeitraum: 2026-01-01 bis 2026-06-30")
    log("Gesucht: ausschließlich TX9 / TN9")
    log("Noch kein Produktionscache.")
    log()

    pairs = collect_exact_pairs()
    samples = select_samples(pairs)

    log(f"Saubere downloadbare TX9+TN9/MIDAS-Paare: {len(pairs):,}")
    log(f"Tagesdaten-Stichprobe: {len(samples):,} Stationen")

    if not samples:
        raise RuntimeError("Keine ECA&D/MIDAS-Samples gefunden.")

    results = []
    errors = {}

    for item in samples:
        try:
            results.append(inspect_station(item))
        except Exception as exc:
            errors[str(item["staid"])] = str(exc)
            log()
            log(
                f"FEHLER STAID {item['staid']} {item['station']['name']}: {exc}"
            )

    log()
    log("=" * 86)
    log("DAILY PROBE SUMMARY")
    log("=" * 86)
    log(f"Samples geplant: {len(samples):,}")
    log(f"Samples erfolgreich: {len(results):,}")
    log(f"Samples Fehler: {len(errors):,}")

    tx_numeric = sum(x["tx"]["count"] for x in results)
    tn_numeric = sum(x["tn"]["count"] for x in results)
    log(f"Numerische TX9-Werte gesamt: {tx_numeric:,}")
    log(f"Numerische TN9-Werte gesamt: {tn_numeric:,}")

    tx_last = Counter(x["tx"]["last"] for x in results if x["tx"]["last"])
    tn_last = Counter(x["tn"]["last"] for x in results if x["tn"]["last"])
    log(f"TX9 letzte API-Zeitpunkte: {dict(tx_last.most_common())}")
    log(f"TN9 letzte API-Zeitpunkte: {dict(tn_last.most_common())}")

    tx_q = Counter()
    tn_q = Counter()
    for x in results:
        tx_q.update(x["tx"]["q_counts"])
        tn_q.update(x["tn"]["q_counts"])

    log(f"TX9 QFLAG gesamt: {dict(tx_q.most_common())}")
    log(f"TN9 QFLAG gesamt: {dict(tn_q.most_common())}")

    log()
    log("Bitte den vollständigen GitHub-Log schicken, besonders:")
    log("1. API-Ranges für air_temperature")
    log("2. TX9/TN9 erster + letzter Wert")
    log("3. TX9/TN9 QFLAG-Verteilungen")
    log("4. DAILY PROBE SUMMARY")

    if errors:
        log()
        log("Fehlerdetails:")
        for staid, error in errors.items():
            log(f"  {staid}: {error}")

    # A partial sample is useful for diagnosis, but the workflow should signal
    # a problem if the API fails for most selected stations.
    if len(results) < max(3, len(samples) // 2):
        raise RuntimeError(
            "Zu wenige ECA&D-RODEO-Stationsabfragen erfolgreich."
        )

    return 0


def self_test() -> None:
    obj = {
        "coverages": [
            {
                "domain": {
                    "axes": {
                        "t": {
                            "values": [
                                "2026-01-01T00:00:00Z",
                                "2026-01-02T00:00:00Z",
                            ]
                        }
                    }
                },
                "ranges": {
                    "tx9": {
                        "values": [7.1, 8.2],
                    },
                    "tx9_q": {
                        "values": [0, 1],
                    },
                    "tn9": {
                        "values": [1.1, 0.2],
                    },
                    "tn9_q": {
                        "values": [0, 0],
                    },
                },
            }
        ]
    }

    flat = flatten_coverage_values(obj)
    assert sorted(flat) == ["tn9", "tn9_q", "tx9", "tx9_q"]

    tx = pair_rows(flat, "tx9", "tx9_q")
    tn = pair_rows(flat, "tn9", "tn9_q")
    assert len(tx) == 2
    assert tx[1]["value"] == 8.2
    assert tx[1]["q"] == 1
    assert tn[0]["value"] == 1.1
    assert api_station_id(1810) == "ecad_0001810"

    print("ECA&D UK daily probe self-test OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
