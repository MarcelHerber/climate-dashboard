#!/usr/bin/env python3
"""Build the UK 2026 current cache from ECA&D non-blended UKMO TX9/TN9.

Historical authority:
    Met Office MIDAS Open through 2025.

Current-year source:
    ECA&D non-blended participant/UKMO observations via MeteoGate/RODEO EDR.

Strict production rules:
  * UK stations only.
  * TX9 and TN9 only (same 09-09 convention as MIDAS project logic).
  * participant/UKMO source only (PARID=35 / PARNAME contains UKMO).
  * source must occur in the downloadable non-blended inventory.
  * station must crosswalk cleanly to the completed MIDAS historical cache.
  * only ECA&D quality flag q=0 is accepted.
  * q=1 suspect and q=9 missing are counted but never used as records.
  * no blended/GTS infilling.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import pickle
import tempfile
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import test_ecad_uk_2026 as meta_probe
import update_metoffice_uk_midas_station_cache as hist

YEAR = 2026
FORMAT_VERSION = 1
SOURCE = "ECA&D non-blended participant/UKMO TX9/TN9"
HISTORICAL_SOURCE = "Met Office MIDAS Open through 2025"
COUNTRY = "United Kingdom"
COUNTRY_CODE = "UK"

BASE_URL = "https://api.meteogate.eu/eu-eumetnet-climate-observations/v1"
COLLECTION = "ecad-nonblended"

QUERY_START = "2026-01-01T00:00:00Z"
QUERY_END = "2026-12-31T23:59:59Z"

CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
UA = "climate-dashboard-ecad-uk-current-2026/1.0 (+GitHub Actions)"

MIDAS_BASELINE_NAME = (
    "metoffice_uk_midas_daily_baseline_through_2025_v1.pkl.gz"
)
OUTPUT_NAME = "metoffice_uk_ecad_current_2026_v1.pkl.gz"
STATUS_NAME = "metoffice_uk_ecad_current_2026_status.json"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def historical_path(cache_dir: Path) -> Path:
    return cache_dir / MIDAS_BASELINE_NAME


def output_path(cache_dir: Path) -> Path:
    return cache_dir / OUTPUT_NAME


def status_path(cache_dir: Path) -> Path:
    return cache_dir / STATUS_NAME


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_pickle_gzip(path: Path) -> Any:
    with gzip.open(path, "rb") as f:
        return pickle.load(f)


def api_station_id(staid: int) -> str:
    return f"ecad_{staid:07d}"


def request_json(
    url: str,
    params: dict[str, str] | None = None,
    *,
    attempts: int = 4,
) -> dict[str, Any]:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                raw = response.read()
            if not raw:
                raise RuntimeError("leere API-Antwort")
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            last = exc
            if attempt >= attempts:
                break
            import time
            time.sleep(min(15, attempt * 2))

    raise RuntimeError(f"API-Abruf fehlgeschlagen: {url}: {last}")


def flatten_coverage_values(
    obj: dict[str, Any],
) -> dict[str, dict[str, list[Any]]]:
    out: dict[str, dict[str, list[Any]]] = {}

    coverages = obj.get("coverages", [])
    if not isinstance(coverages, list):
        return out

    for coverage in coverages:
        if not isinstance(coverage, dict):
            continue

        times = (
            coverage.get("domain", {})
            .get("axes", {})
            .get("t", {})
            .get("values", [])
        )
        ranges = coverage.get("ranges", {})

        if not isinstance(times, list) or not isinstance(ranges, dict):
            continue

        for key, robj in ranges.items():
            if not isinstance(robj, dict):
                continue
            values = robj.get("values", [])
            if not isinstance(values, list):
                continue
            if len(values) != len(times):
                continue

            target = out.setdefault(
                key,
                {"times": [], "values": []},
            )
            target["times"].extend(times)
            target["values"].extend(values)

    return out


def time_value_map(
    flat: dict[str, dict[str, list[Any]]],
    key: str,
) -> dict[str, Any]:
    obj = flat.get(key, {})
    return {
        str(t): v
        for t, v in zip(obj.get("times", []), obj.get("values", []))
    }


def q_to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def parse_api_date(value: str) -> date | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        # API timestamps are UTC ISO strings.
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def collect_exact_pairs() -> list[dict[str, Any]]:
    """Return downloadable UKMO TX9+TN9 stations cleanly matched to MIDAS."""
    targets = {
        "blend_station_tx": (meta_probe.BLEND_STATION_TX, "STAID"),
        "blend_station_tn": (meta_probe.BLEND_STATION_TN, "STAID"),
        "blend_source_tx": (meta_probe.BLEND_SOURCE_TX, "STAID"),
        "blend_source_tn": (meta_probe.BLEND_SOURCE_TN, "STAID"),
        "nonblend_info_tx": (meta_probe.NONBLEND_INFO_TX, "SOUID"),
        "nonblend_info_tn": (meta_probe.NONBLEND_INFO_TN, "SOUID"),
    }

    parsed: dict[str, list[dict[str, str]]] = {}
    created: dict[str, str] = {}

    for key, (url, header) in targets.items():
        rows, stamp = meta_probe.parse_table(
            meta_probe.request_text(url),
            header,
        )
        parsed[key] = rows
        created[key] = stamp

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
            "Historischer UK-MIDAS-Cache fehlt oder ist unvollständig."
        )

    pairs = []
    uncertain = []

    for staid in sorted(set(tx_stations) & set(tn_stations)):
        tx = meta_probe.best_exact_source(
            tx_by_station.get(staid, []),
            "TX9",
        )
        tn = meta_probe.best_exact_source(
            tn_by_station.get(staid, []),
            "TN9",
        )

        if tx is None or tn is None:
            continue

        # Exact participant source must be downloadable in the non-blended set.
        if tx["souid"] not in nb_tx or tn["souid"] not in nb_tn:
            continue

        station = tx_stations.get(staid) or tn_stations[staid]
        cw = meta_probe.crosswalk_ecad_to_midas(station, midas)

        item = {
            "staid": staid,
            "station": station,
            "tx": tx,
            "tn": tn,
            "crosswalk": cw,
        }

        if cw.get("matched"):
            pairs.append(item)
        else:
            uncertain.append(item)

    return pairs, uncertain, created


def build_record_from_api(
    item: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    staid = item["staid"]
    api_id = api_station_id(staid)

    obj = request_json(
        f"{BASE_URL}/collections/{COLLECTION}/locations/{api_id}",
        params={
            "datetime": f"{QUERY_START}/{QUERY_END}",
            "standard_name": "air_temperature",
        },
    )

    flat = flatten_coverage_values(obj)
    tx = time_value_map(flat, "tx9")
    txq = time_value_map(flat, "tx9_q")
    tn = time_value_map(flat, "tn9")
    tnq = time_value_map(flat, "tn9_q")

    all_times = sorted(set(tx) | set(tn) | set(txq) | set(tnq))

    rec = hist.empty_record()
    stats = Counter()
    tx_q = Counter()
    tn_q = Counter()

    for t in all_times:
        d = parse_api_date(t)
        if d is None or d.year != YEAR:
            continue

        raw_tx = finite_number(tx.get(t))
        raw_tn = finite_number(tn.get(t))
        q_tx = q_to_int(txq.get(t))
        q_tn = q_to_int(tnq.get(t))

        if raw_tx is not None:
            tx_q[str(q_tx) if q_tx is not None else "<null>"] += 1
        if raw_tn is not None:
            tn_q[str(q_tn) if q_tn is not None else "<null>"] += 1

        good_tx = None
        good_tn = None

        if raw_tx is not None:
            if q_tx == 0:
                if hist.plausible_tmax(raw_tx):
                    good_tx = raw_tx
                    stats["accepted_tx_q0"] += 1
                else:
                    stats["rejected_tx_plausibility"] += 1
            elif q_tx == 1:
                stats["rejected_tx_q1_suspect"] += 1
            elif q_tx == 9:
                stats["rejected_tx_q9_missing"] += 1
            else:
                stats["rejected_tx_other_q"] += 1

        if raw_tn is not None:
            if q_tn == 0:
                if hist.plausible_tmin(raw_tn):
                    good_tn = raw_tn
                    stats["accepted_tn_q0"] += 1
                else:
                    stats["rejected_tn_plausibility"] += 1
            elif q_tn == 1:
                stats["rejected_tn_q1_suspect"] += 1
            elif q_tn == 9:
                stats["rejected_tn_q9_missing"] += 1
            else:
                stats["rejected_tn_other_q"] += 1

        if good_tx is None and good_tn is None:
            continue

        hist.consume_day(
            rec,
            d,
            good_tn,
            good_tx,
            ["ECAD_NONBLENDED_UKMO_TX9_TN9_Q0"],
        )

    detail = {
        "api_id": api_id,
        "ranges": sorted(flat),
        "stats": dict(stats),
        "q_tx": dict(tx_q),
        "q_tn": dict(tn_q),
    }
    return rec, detail


def build_current(cache_dir: Path) -> Path:
    baseline_file = historical_path(cache_dir)
    if not baseline_file.exists():
        raise RuntimeError(
            "Historischer UK-MIDAS-Cache fehlt. Erst den historischen "
            "UK-Workflow vollständig abschließen."
        )

    baseline = load_pickle_gzip(baseline_file)
    if not isinstance(baseline, dict) or baseline.get("complete") is not True:
        raise RuntimeError("Historischer UK-MIDAS-Cache ist nicht vollständig.")

    log("=== UK CURRENT 2026 · ECA&D NON-BLENDED ===")
    log("Historie: Met Office MIDAS Open bis 2025")
    log("Current: ECA&D participant/UKMO TX9 + TN9")
    log("QC: ausschließlich q=0; q=1/q=9 ausgeschlossen")
    log("Blending/GTS: ausgeschlossen")
    log()

    pairs, uncertain, metadata_created = collect_exact_pairs()

    log(f"Sauber gematchte TX9+TN9-Stationen: {len(pairs):,}")
    log(f"Unsichere Crosswalks ausgeschlossen: {len(uncertain):,}")

    records: dict[str, dict[str, Any]] = {}
    station_details: dict[str, dict[str, Any]] = {}
    crosswalk: list[dict[str, Any]] = []
    errors: dict[str, str] = {}

    global_stats = Counter()
    global_q_tx = Counter()
    global_q_tn = Counter()

    for i, item in enumerate(pairs, 1):
        staid = item["staid"]
        midas_key = item["crosswalk"]["midas_key"]

        try:
            rec, detail = build_record_from_api(item)
        except Exception as exc:
            errors[str(staid)] = str(exc)
            continue

        global_stats.update(detail["stats"])
        global_q_tx.update(detail["q_tx"])
        global_q_tn.update(detail["q_tn"])

        if rec.get("tmax_abs") is None and rec.get("tmin_abs") is None:
            global_stats["stations_without_q0_2026_values"] += 1
            continue

        if midas_key in records:
            raise RuntimeError(
                f"Crosswalk-Kollision: mehrere ECA&D-Stationen -> {midas_key}"
            )

        records[midas_key] = rec

        base_meta = dict(
            baseline.get("station_details", {}).get(midas_key, {})
        )
        station_details[midas_key] = {
            **base_meta,
            "current_source": SOURCE,
            "eca_staid": staid,
            "eca_name": item["station"]["name"],
            "eca_lat": item["station"]["lat"],
            "eca_lon": item["station"]["lon"],
            "tx_souid": item["tx"]["souid"],
            "tn_souid": item["tn"]["souid"],
            "tx_eleid": item["tx"]["eleid"],
            "tn_eleid": item["tn"]["eleid"],
            "tx_metadata_start": item["tx"]["start"],
            "tx_metadata_stop": item["tx"]["stop"],
            "tn_metadata_start": item["tn"]["start"],
            "tn_metadata_stop": item["tn"]["stop"],
            "crosswalk": item["crosswalk"],
            "api_ranges": detail["ranges"],
        }

        crosswalk.append(
            {
                "eca_staid": staid,
                "eca_name": item["station"]["name"],
                "midas_key": midas_key,
                "method": item["crosswalk"]["method"],
                "distance_km": item["crosswalk"].get("distance_km"),
                "name_similarity": item["crosswalk"].get("name_similarity"),
                "tx_souid": item["tx"]["souid"],
                "tn_souid": item["tn"]["souid"],
            }
        )

        if i % 10 == 0 or i == len(pairs):
            log(
                f"Fortschritt: {i}/{len(pairs)} | "
                f"2026-Reihen {len(records)} | API-Fehler {len(errors)}"
            )

    if errors:
        sample = "; ".join(
            f"{k}: {v[:120]}" for k, v in list(errors.items())[:8]
        )
        raise RuntimeError(
            f"{len(errors)} ECA&D-Stationen konnten nicht vollständig "
            f"abgerufen werden. Kein unvollständiger Produktionscache wird "
            f"veröffentlicht. Beispiele: {sample}"
        )

    if not records:
        raise RuntimeError("Keine gültigen q=0 UK-2026-Daten gefunden.")

    first_dates = [
        r["first_date"] for r in records.values() if r.get("first_date")
    ]
    last_dates = [
        r["last_date"] for r in records.values() if r.get("last_date")
    ]
    first_date = min(first_dates) if first_dates else None
    last_date = max(last_dates) if last_dates else None

    payload = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "historical_source": HISTORICAL_SOURCE,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "year": YEAR,
        "complete": True,
        "partial_year": last_date != f"{YEAR}-12-31",
        "query_start": QUERY_START,
        "query_end": QUERY_END,
        "collection": COLLECTION,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "records": records,
        "station_details": station_details,
        "crosswalk": crosswalk,
        "station_count": len(records),
        "candidate_station_count": len(pairs),
        "excluded_uncertain_crosswalk_count": len(uncertain),
        "first_date": first_date,
        "last_date": last_date,
        "observation_days": sum(
            int(r.get("observation_days", 0)) for r in records.values()
        ),
        "tmax_days": sum(
            int(r.get("tmax_days", 0)) for r in records.values()
        ),
        "tmin_days": sum(
            int(r.get("tmin_days", 0)) for r in records.values()
        ),
        "stats": dict(global_stats),
        "q_tx": dict(global_q_tx),
        "q_tn": dict(global_q_tn),
        "metadata_file_stamps": metadata_created,
        "quality_note": (
            "2026 current UK temperatures use only ECA&D non-blended "
            "participant/UKMO TX9 and TN9 series which can be cleanly "
            "crosswalked to the Met Office MIDAS historical cache. "
            "Only ECA&D quality flag 0 (valid) is accepted. Flag 1 (suspect), "
            "flag 9 (missing), null/unknown quality flags and implausible "
            "values are excluded. No blended series, SYNOP/GTS infilling, "
            "nearby-station substitution or modelled values are used."
        ),
    }

    out = output_path(cache_dir)
    atomic_pickle_gzip(out, payload)

    hottest = None
    coldest = None

    for key, rec in records.items():
        tx = rec.get("tmax_abs")
        tn = rec.get("tmin_abs")

        if tx is not None and (
            hottest is None or float(tx[0]) > hottest["value"]
        ):
            hottest = {
                "station": key,
                "value": float(tx[0]),
                "date": tx[1],
            }

        if tn is not None and (
            coldest is None or float(tn[0]) < coldest["value"]
        ):
            coldest = {
                "station": key,
                "value": float(tn[0]),
                "date": tn[1],
            }

    status = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "historical_source": HISTORICAL_SOURCE,
        "year": YEAR,
        "complete": True,
        "partial_year": payload["partial_year"],
        "candidate_station_count": len(pairs),
        "station_count": len(records),
        "excluded_uncertain_crosswalk_count": len(uncertain),
        "first_date": first_date,
        "last_date": last_date,
        "observation_days": payload["observation_days"],
        "tmax_days": payload["tmax_days"],
        "tmin_days": payload["tmin_days"],
        "q_tx": dict(global_q_tx),
        "q_tn": dict(global_q_tn),
        "stats": dict(global_stats),
        "hottest": hottest,
        "coldest": coldest,
        "crosswalk": crosswalk,
    }
    atomic_json(status_path(cache_dir), status)

    log()
    log("=== UK CURRENT 2026 SUMMARY · ECA&D ===")
    log(f"TX9+TN9 Kandidaten / MIDAS-Match: {len(pairs):,}")
    log(f"2026-Stationen mit q=0 Daten: {len(records):,}")
    log(f"Unsichere Crosswalks ausgeschlossen: {len(uncertain):,}")
    log(f"Stationstage: {payload['observation_days']:,}")
    log(f"TMAX-Tage q=0: {payload['tmax_days']:,}")
    log(f"TMIN-Tage q=0: {payload['tmin_days']:,}")
    log(f"Datenzeitraum: {first_date} bis {last_date}")
    log(f"TX9 QFLAG-Verteilung roh: {dict(global_q_tx.most_common())}")
    log(f"TN9 QFLAG-Verteilung roh: {dict(global_q_tn.most_common())}")
    log(
        "Suspect verworfen: "
        f"TX={global_stats.get('rejected_tx_q1_suspect', 0):,} | "
        f"TN={global_stats.get('rejected_tn_q1_suspect', 0):,}"
    )
    log(f"Höchstes gültiges TMAX 2026: {hottest}")
    log(f"Niedrigstes gültiges TMIN 2026: {coldest}")
    log(f"Output: {out}")
    log("UK Current-2026 ECA&D-Cache vollständig OK.")
    return out


def self_test() -> None:
    assert api_station_id(272) == "ecad_0000272"
    assert q_to_int(0) == 0
    assert q_to_int("1") == 1
    assert q_to_int(None) is None
    assert finite_number(18.2) == 18.2
    assert finite_number(float("nan")) is None
    assert parse_api_date("2026-06-30T00:00:00Z") == date(2026, 6, 30)

    sample = {
        "coverages": [
            {
                "domain": {
                    "axes": {
                        "t": {
                            "values": [
                                "2026-06-29T00:00:00Z",
                                "2026-06-30T00:00:00Z",
                            ]
                        }
                    }
                },
                "ranges": {
                    "tx9": {"values": [16.0, 18.2]},
                    "tx9_q": {"values": [0, 1]},
                    "tn9": {"values": [13.6, 10.0]},
                    "tn9_q": {"values": [0, 0]},
                },
            }
        ]
    }
    flat = flatten_coverage_values(sample)
    assert time_value_map(flat, "tx9")[
        "2026-06-30T00:00:00Z"
    ] == 18.2
    assert q_to_int(
        time_value_map(flat, "tx9_q")["2026-06-30T00:00:00Z"]
    ) == 1

    print("UK ECA&D current 2026 self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_current(Path(args.cache_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
