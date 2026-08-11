#!/usr/bin/env python3
"""Build the current 2026 UK Met Office MIDAS daily TMIN/TMAX cache.

This uses the ongoing/restricted MIDAS TD yearly file:
  /badc/ukmo-midas/data/TD/yearly_files/midas_tempdrnl_202601-202612.txt

The file is updated by CEDA as newer MIDAS deliveries arrive.  The parser
reuses the 09-09 UTC climate-day reconstruction from the historical MIDAS
Open builder, so 12-hour values are never mistaken for complete daily values.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import os
import pickle
import re
import tempfile
import urllib.error
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import update_metoffice_uk_midas_station_cache as hist

YEAR = 2026
FORMAT_VERSION = 1
SOURCE = "Met Office MIDAS"
COUNTRY = "United Kingdom"
COUNTRY_CODE = "UK"

CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
CURRENT_FILE_NAME = "midas_tempdrnl_202601-202612.txt"
CURRENT_DATA_URL = (
    "https://dap.ceda.ac.uk/badc/ukmo-midas/data/TD/yearly_files/"
    + CURRENT_FILE_NAME
)
CATALOGUE_URL = (
    "https://catalogue.ceda.ac.uk/uuid/"
    "1bb479d3b1e38c339adb9c82c15579d8/"
)

# The restricted TD yearly files use the same TD table schema documented by
# CEDA.  Some snapshots include the header in the file; some historic exports
# rely on the separately published column header.  This fallback matches the
# 22-column TD schema used by the MIDAS daily-temperature table.
CANONICAL_COLUMNS = [
    "ob_end_time",
    "id_type",
    "id",
    "ob_hour_count",
    "version_num",
    "met_domain_name",
    "src_id",
    "rec_st_ind",
    "max_air_temp",
    "min_air_temp",
    "min_grss_temp",
    "min_conc_temp",
    "max_air_temp_q",
    "min_air_temp_q",
    "min_grss_temp_q",
    "min_conc_temp_q",
    "max_air_temp_j",
    "min_air_temp_j",
    "min_grss_temp_j",
    "min_conc_temp_j",
    "meto_stmp_time",
    "midas_stmp_etime",
]


def log(msg: str = "") -> None:
    print(msg, flush=True)


def current_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "metoffice_uk_midas_current_2026_v1.pkl.gz"


def current_status_path(cache_dir: Path) -> Path:
    return cache_dir / "metoffice_uk_midas_current_2026_status.json"


def historical_cache_path(cache_dir: Path) -> Path:
    return cache_dir / (
        "metoffice_uk_midas_daily_baseline_through_2025_v1.pkl.gz"
    )


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


def load_pickle_gzip(path: Path) -> Any:
    with gzip.open(path, "rb") as f:
        return pickle.load(f)


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


def normalize_src_id(value: str) -> str:
    text = str(value).strip()
    try:
        return str(int(float(text)))
    except ValueError:
        return text.lstrip("0") or text


def as_float(value: str) -> float | None:
    text = str(value).strip()
    if text in {"", "NA", "N/A", "-999", "-999.0"}:
        return None
    try:
        x = float(text)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def parse_datetime(value: str) -> datetime | None:
    text = str(value).strip()
    if not text or text in {"NA", "N/A"}:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def looks_like_data_row(row: list[str]) -> bool:
    if len(row) < 10:
        return False
    return parse_datetime(row[0]) is not None


def detect_rows(text: str) -> tuple[list[str], list[list[str]], dict[str, Any]]:
    """Read either headered CSV or the plain TD yearly export."""
    raw_rows = []
    for row in csv.reader(io.StringIO(text)):
        if not row or not any(str(x).strip() for x in row):
            continue
        raw_rows.append([str(x).strip() for x in row])

    if not raw_rows:
        raise RuntimeError("MIDAS-2026-Datei enthält keine CSV-Zeilen.")

    header_index = None
    for i, row in enumerate(raw_rows[:50]):
        normalized = [hist.normalize_ref(x) for x in row]
        if "ob_end_time" in normalized and "src_id" in normalized:
            header_index = i
            break

    if header_index is not None:
        refs = [str(x).strip() for x in raw_rows[header_index]]
        rows = raw_rows[header_index + 1 :]
        mode = "header_in_file"
    else:
        refs = CANONICAL_COLUMNS[:]
        rows = [row for row in raw_rows if looks_like_data_row(row)]
        mode = "canonical_22_column_fallback"

    rows = [r for r in rows if looks_like_data_row(r)]

    return refs, rows, {
        "parse_mode": mode,
        "raw_csv_rows": len(raw_rows),
        "data_rows": len(rows),
        "columns": len(refs),
        "refs": refs,
    }


def baseline_crosswalk(
    baseline: dict[str, Any],
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Map MIDAS src_id -> historical station key."""
    src_to_key: dict[str, str] = {}
    details_by_key: dict[str, dict[str, Any]] = {}

    for key, meta in baseline.get("station_details", {}).items():
        if not isinstance(meta, dict):
            continue
        src = normalize_src_id(meta.get("src_id", ""))
        if not src:
            continue
        # If a duplicate appears, prefer the key which actually has a record.
        if src not in src_to_key or key in baseline.get("records", {}):
            src_to_key[src] = key
            details_by_key[key] = meta

    return src_to_key, details_by_key


def parse_2026_file(
    raw: bytes,
) -> tuple[
    dict[str, dict[tuple[datetime, int], dict[str, Any]]],
    Counter,
    Counter,
    Counter,
    dict[str, Any],
]:
    text = hist.decode_text(raw)
    refs, rows, parse_info = detect_rows(text)

    idx_time = hist.field_index(refs, "ob_end_time")
    idx_hours = hist.field_index(refs, "ob_hour_count")
    idx_version = hist.field_index(refs, "version_num")
    idx_src = hist.field_index(refs, "src_id")
    idx_tmax = hist.field_index(refs, "max_air_temp")
    idx_tmin = hist.field_index(refs, "min_air_temp")
    idx_tmax_q = hist.field_index(refs, "max_air_temp_q")
    idx_tmin_q = hist.field_index(refs, "min_air_temp_q")
    idx_stamp = hist.field_index(refs, "meto_stmp_time")
    idx_id = hist.field_index(refs, "id")
    idx_id_type = hist.field_index(refs, "id_type")
    idx_domain = hist.field_index(refs, "met_domain_name")

    required = {
        "ob_end_time": idx_time,
        "ob_hour_count": idx_hours,
        "version_num": idx_version,
        "src_id": idx_src,
        "max_air_temp": idx_tmax,
        "min_air_temp": idx_tmin,
    }
    missing = [name for name, idx in required.items() if idx is None]
    if missing:
        raise RuntimeError(f"MIDAS-2026-Spalten fehlen: {missing}")

    intervals_by_src: dict[
        str, dict[tuple[datetime, int], dict[str, Any]]
    ] = defaultdict(dict)
    stats = Counter()
    qmax = Counter()
    qmin = Counter()
    identifiers: dict[str, dict[str, Counter]] = defaultdict(
        lambda: {
            "id": Counter(),
            "id_type": Counter(),
            "met_domain_name": Counter(),
        }
    )

    for row in rows:
        stats["raw_rows"] += 1

        version = hist.safe_value(row, idx_version)
        if version != "1":
            stats["rejected_version_not_1"] += 1
            continue

        src_raw = hist.safe_value(row, idx_src)
        src = normalize_src_id(src_raw)
        if not src:
            stats["rejected_missing_src_id"] += 1
            continue
        if src == hist.COMMISSIONING_SRC_ID:
            stats["rejected_commissioning"] += 1
            continue

        end = parse_datetime(hist.safe_value(row, idx_time))
        if end is None:
            stats["rejected_bad_time"] += 1
            continue

        # The yearly file may contain only 2026 at present, but filter explicitly
        # so a future CEDA packaging change cannot pollute the current cache.
        if end.year not in {YEAR, YEAR + 1}:
            stats["ignored_outside_2026_support_window"] += 1
            continue

        try:
            hours = int(float(hist.safe_value(row, idx_hours)))
        except ValueError:
            stats["rejected_bad_hours"] += 1
            continue
        if hours not in {12, 24}:
            stats["ignored_non_12_24_hour_rows"] += 1
            continue

        tmax = as_float(hist.safe_value(row, idx_tmax))
        tmin = as_float(hist.safe_value(row, idx_tmin))

        qmax_code = hist.safe_value(row, idx_tmax_q) or "<leer>"
        qmin_code = hist.safe_value(row, idx_tmin_q) or "<leer>"
        qmax[qmax_code] += 1
        qmin[qmin_code] += 1

        if tmax is not None and not hist.plausible_tmax(tmax):
            stats["qc_rejected_tmax_plausibility"] += 1
            tmax = None
        if tmin is not None and not hist.plausible_tmin(tmin):
            stats["qc_rejected_tmin_plausibility"] += 1
            tmin = None

        if tmax is None and tmin is None:
            stats["rows_without_air_temperature"] += 1
            continue

        stamp = parse_datetime(hist.safe_value(row, idx_stamp))
        candidate = {
            "tmax": tmax,
            "tmin": tmin,
            "stamp": stamp,
            "src_id": src,
            "qmax": qmax_code,
            "qmin": qmin_code,
        }

        key = (end, hours)
        old = intervals_by_src[src].get(key)
        if old is None:
            intervals_by_src[src][key] = candidate
        else:
            old_stamp = old.get("stamp")
            if old_stamp is None or (
                stamp is not None and stamp > old_stamp
            ):
                intervals_by_src[src][key] = candidate
                stats["duplicate_rows_replaced_by_newer_stamp"] += 1
            else:
                stats["duplicate_rows_older_ignored"] += 1

        ident = hist.safe_value(row, idx_id)
        ident_type = hist.safe_value(row, idx_id_type)
        domain = hist.safe_value(row, idx_domain)
        if ident:
            identifiers[src]["id"][ident] += 1
        if ident_type:
            identifiers[src]["id_type"][ident_type] += 1
        if domain:
            identifiers[src]["met_domain_name"][domain] += 1

    identifier_summary: dict[str, dict[str, Any]] = {}
    for src, obj in identifiers.items():
        identifier_summary[src] = {
            k: dict(v.most_common(10)) for k, v in obj.items()
        }

    parse_info["identifier_summary"] = identifier_summary
    return intervals_by_src, stats, qmax, qmin, parse_info


def build_current(cache_dir: Path, force: bool = False) -> Path:
    baseline_file = historical_cache_path(cache_dir)
    if not baseline_file.exists():
        raise RuntimeError(
            "Historischer UK-Cache fehlt. Zuerst Workflow "
            "'Build Met Office UK historical cache' vollständig abschließen."
        )

    baseline = load_pickle_gzip(baseline_file)
    if not isinstance(baseline, dict) or not baseline.get("complete"):
        raise RuntimeError(
            "Historischer UK-Cache ist noch nicht vollständig. "
            "2026-Workflow erst danach ausführen."
        )

    src_to_key, baseline_details = baseline_crosswalk(baseline)
    log(f"Historischer MIDAS-Crosswalk: {len(src_to_key):,} src_ids")

    token = hist.get_ceda_token()

    log()
    log("=== MET OFFICE UK MIDAS CURRENT 2026 ===")
    log(f"Quelle: {CURRENT_DATA_URL}")
    log("Tagesdefinition: dieselbe 09-09-UTC-Logik wie Historie")
    log("version_num=1; src_id=99999 ausgeschlossen")
    log()

    try:
        raw = hist.request_bytes(
            CURRENT_DATA_URL,
            token=token,
            timeout=180,
            attempts=3,
        )
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise RuntimeError(
                "CEDA-Zugriff auf den laufenden/restricted MIDAS-Datensatz "
                f"wurde mit HTTP {exc.code} abgelehnt. Im CEDA-Katalog beim "
                "Datensatz 'MIDAS: UK Daily Temperature Data' zuerst "
                "'Request Access' ausführen und die MIDAS-Lizenz akzeptieren. "
                "Danach einen neuen CEDA_ACCESS_TOKEN erzeugen und den Workflow "
                "erneut starten."
            ) from exc
        raise

    log(f"2026-Jahresdatei heruntergeladen: {len(raw):,} Bytes")

    (
        intervals_by_src,
        parse_stats,
        qmax,
        qmin,
        parse_info,
    ) = parse_2026_file(raw)

    records: dict[str, dict[str, Any]] = {}
    station_details: dict[str, dict[str, Any]] = {}
    reconstruction = Counter()
    unmatched_src_ids = []

    for src in sorted(intervals_by_src, key=lambda x: (len(x), x)):
        intervals = intervals_by_src[src]
        local_stats = Counter()
        daily = hist.reconstruct_daily(intervals, YEAR, local_stats)
        reconstruction.update(local_stats)

        rec = hist.empty_record()
        for d in sorted(daily):
            if d.year != YEAR:
                continue
            vals = daily[d]
            provenance = [
                p
                for p in (vals.get("tmin_prov"), vals.get("tmax_prov"))
                if p
            ]
            hist.consume_day(
                rec,
                d,
                vals.get("tmin"),
                vals.get("tmax"),
                provenance,
            )

        if rec.get("tmax_abs") is None and rec.get("tmin_abs") is None:
            continue

        key = src_to_key.get(src)
        if key is None:
            key = f"midas_src_{src}"
            unmatched_src_ids.append(src)
            detail = {
                "station_id": None,
                "src_id": src,
                "name": f"MIDAS src_id {src}",
                "county": None,
                "dirname": key,
                "current_only_2026": True,
            }
        else:
            detail = dict(baseline_details.get(key, {}))
            detail["current_only_2026"] = False

        detail["current_2026_identifiers"] = (
            parse_info["identifier_summary"].get(src, {})
        )
        records[key] = rec
        station_details[key] = detail

    if not records:
        raise RuntimeError("MIDAS-2026-Datei ergab keine täglichen TMAX/TMIN-Reihen.")

    first_dates = [
        rec["first_date"] for rec in records.values() if rec.get("first_date")
    ]
    last_dates = [
        rec["last_date"] for rec in records.values() if rec.get("last_date")
    ]

    first_date = min(first_dates) if first_dates else None
    last_date = max(last_dates) if last_dates else None

    payload = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "year": YEAR,
        "complete": True,
        "calendar_year_complete": last_date == f"{YEAR}-12-31",
        "partial_year": last_date != f"{YEAR}-12-31",
        "data_file": CURRENT_FILE_NAME,
        "data_url": CURRENT_DATA_URL,
        "catalogue_url": CATALOGUE_URL,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "records": records,
        "station_details": station_details,
        "station_count": len(records),
        "matched_historical_station_count": (
            len(records) - len(unmatched_src_ids)
        ),
        "unmatched_current_src_ids": unmatched_src_ids,
        "first_date": first_date,
        "last_date": last_date,
        "observation_days": sum(
            int(rec.get("observation_days", 0)) for rec in records.values()
        ),
        "tmax_days": sum(
            int(rec.get("tmax_days", 0)) for rec in records.values()
        ),
        "tmin_days": sum(
            int(rec.get("tmin_days", 0)) for rec in records.values()
        ),
        "parse_info": {
            k: v
            for k, v in parse_info.items()
            if k != "identifier_summary"
        },
        "stats": dict(parse_stats),
        "reconstruction_stats": dict(reconstruction),
        "q_tmax": dict(qmax),
        "q_tmin": dict(qmin),
        "quality_note": (
            "Current 2026 values come from the ongoing Met Office MIDAS TD "
            "yearly file. Only version_num=1 is used; src_id=99999 is excluded. "
            "The same 09-09 UTC reconstruction as the historical MIDAS Open "
            "cache is applied. Single 12-hour rows are never treated as daily "
            "records. This current cache is refreshed by replacing it from the "
            "latest CEDA yearly file, so later MIDAS deliveries can add or revise "
            "2026 values."
        ),
    }

    out = current_cache_path(cache_dir)
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
        "year": YEAR,
        "complete": True,
        "calendar_year_complete": payload["calendar_year_complete"],
        "station_count": len(records),
        "matched_historical_station_count": payload[
            "matched_historical_station_count"
        ],
        "unmatched_current_src_ids": unmatched_src_ids,
        "first_date": first_date,
        "last_date": last_date,
        "observation_days": payload["observation_days"],
        "tmax_days": payload["tmax_days"],
        "tmin_days": payload["tmin_days"],
        "download_bytes": len(raw),
        "parse_mode": payload["parse_info"].get("parse_mode"),
        "raw_rows": parse_stats.get("raw_rows", 0),
        "reconstruction_stats": dict(reconstruction),
        "q_tmax": dict(qmax),
        "q_tmin": dict(qmin),
        "hottest": hottest,
        "coldest": coldest,
    }
    atomic_json(current_status_path(cache_dir), status)

    log()
    log("=== MET OFFICE UK CURRENT 2026 SUMMARY ===")
    log(f"Stationsreihen: {len(records):,}")
    log(
        "Mit historischem Stations-Crosswalk: "
        f"{payload['matched_historical_station_count']:,}"
    )
    log(f"Neue/unmatched src_ids: {len(unmatched_src_ids):,}")
    log(f"Tage: {payload['observation_days']:,}")
    log(f"TMAX-Tage: {payload['tmax_days']:,}")
    log(f"TMIN-Tage: {payload['tmin_days']:,}")
    log(f"Datenzeitraum: {first_date} bis {last_date}")
    log(f"Kalenderjahr vollständig: {payload['calendar_year_complete']}")
    log(
        "TMAX Rekonstruktion: "
        f"24h={reconstruction.get('daily_tmax_from_24h', 0):,} | "
        f"12h-Paare={reconstruction.get('daily_tmax_from_12h_pair', 0):,}"
    )
    log(
        "TMIN Rekonstruktion: "
        f"24h={reconstruction.get('daily_tmin_from_24h', 0):,} | "
        f"12h-Paare={reconstruction.get('daily_tmin_from_12h_pair', 0):,}"
    )
    log("TMAX _q Codes:", dict(qmax.most_common()))
    log("TMIN _q Codes:", dict(qmin.most_common()))
    log(f"Output: {out}")
    log("Met Office UK Current-2026-Cache OK.")

    return out


def self_test() -> None:
    header = ",".join(CANONICAL_COLUMNS)
    row = [
        "2026-01-02 09:00:00",
        "DCNN",
        "708",
        "24",
        "1",
        "NCM",
        "145",
        "1011",
        "12.3",
        "1.2",
        "NA",
        "NA",
        "6",
        "6",
        "NA",
        "NA",
        "NA",
        "NA",
        "NA",
        "NA",
        "2026-01-02 09:05:00",
        "0.0",
    ]
    text = header + "\n" + ",".join(row) + "\n"
    refs, rows, info = detect_rows(text)
    assert info["parse_mode"] == "header_in_file"
    assert len(rows) == 1
    assert hist.field_index(refs, "src_id") == 6

    # Headerless fallback.
    refs, rows, info = detect_rows(",".join(row) + "\n")
    assert info["parse_mode"] == "canonical_22_column_fallback"
    assert len(rows) == 1

    print("Met Office UK current 2026 self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_current(Path(args.cache_dir), force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
