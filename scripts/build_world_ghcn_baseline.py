#!/usr/bin/env python3
"""
GHCN-Daily WORLD · historischer Temperatur-Baseline-Cache bis 2025.

Ziel dieses Schritts:
- noch KEINE Dashboard-Aenderung
- noch KEIN laufendes 2026-Update
- einmaliger historischer Basislauf fuer alle GHCN-Temperaturstationen
- vier Stations-Extreme:
    * hoechstes TMAX
    * niedrigstes TMAX
    * niedrigstes TMIN
    * hoechstes TMIN
- nur Tageswerte mit leerem GHCN-QFLAG werden akzeptiert
- sehr weite harte Plausibilitaetsgrenzen dienen nur als Parsing-Sicherung
- das ca. 3,7-GB-grosse ghcnd_all.tar.gz wird HTTP-streamend verarbeitet und
  nicht komplett auf die Platte geschrieben
- Ergebnis wird als kleiner komprimierter Pickle-Cache gespeichert

NOAA-Dokumentation:
https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt
"""

from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import io
import json
import os
import pickle
import shutil
import sys
import tarfile
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO
from urllib.request import Request, urlopen


GHCN_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
ARCHIVE_URL = f"{GHCN_BASE}/ghcnd_all.tar.gz"
STATIONS_URL = f"{GHCN_BASE}/ghcnd-stations.txt"
INVENTORY_URL = f"{GHCN_BASE}/ghcnd-inventory.txt"
COUNTRIES_URL = f"{GHCN_BASE}/ghcnd-countries.txt"
VERSION_URL = f"{GHCN_BASE}/ghcnd-version.txt"

SCHEMA_VERSION = 1
BASELINE_VERSION = 1
DEFAULT_CUTOFF_YEAR = 2025

# Nur Parsing-/Katastrophen-Sicherung, NICHT die spaetere fachliche Rekord-QC.
# Werte sind in Zehntelgrad Celsius.
HARD_TEMP_MIN_TENTHS = -1000   # -100.0 °C
HARD_TEMP_MAX_TENTHS = 600     # +60.0 °C

EXTREME_SAMPLE_LIMIT = 5
REJECT_SAMPLE_LIMIT = 200
HTTP_TIMEOUT_SECONDS = 900
ARCHIVE_ATTEMPTS = 3
PROGRESS_BYTES = 250 * 1024 * 1024

# Grobe Schutzschwellen gegen einen stillen Parser-/Downloadfehler.
MIN_EXPECTED_TEMP_STATIONS = 30000
MIN_EXPECTED_VALID_OBSERVATIONS = 1_000_000
MIN_TARGET_MEMBER_COVERAGE = 0.99

USER_AGENT = (
    "climate-dashboard-world-ghcn-baseline/1.0 "
    "(GHCN-Daily research/cache build)"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def request_url(url: str, timeout: int = HTTP_TIMEOUT_SECONDS):
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        },
    )
    return urlopen(req, timeout=timeout)


def download_text(url: str) -> str:
    print(f"Lade Metadaten: {url}", flush=True)
    with request_url(url) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def safe_int(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def safe_float(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value == -999.9:
        return None
    return value


def parse_countries(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if len(line) < 4:
            continue
        code = line[0:2].strip()
        name = line[3:].strip()
        if code and name:
            result[code] = name
    return result


def parse_stations(text: str, countries: dict[str, str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for line in text.splitlines():
        if len(line) < 71:
            continue
        station_id = line[0:11].strip()
        if len(station_id) != 11:
            continue
        country_code = station_id[:2]
        result[station_id] = {
            "id": station_id,
            "country_code": country_code,
            "country": countries.get(country_code, country_code),
            "latitude": safe_float(line[12:20]),
            "longitude": safe_float(line[21:30]),
            "elevation_m": safe_float(line[31:37]),
            "state": line[38:40].strip() or None,
            "name": line[41:71].strip(),
            "gsn_flag": line[72:75].strip() if len(line) >= 75 else "",
            "hcn_crn_flag": line[76:79].strip() if len(line) >= 79 else "",
            "wmo_id": line[80:85].strip() if len(line) >= 85 else "",
        }
    return result


def parse_inventory(text: str) -> dict[str, dict[str, dict[str, int]]]:
    """
    NOAA fixed-width:
      ID 1-11, ELEMENT 32-35, FIRSTYEAR 37-40, LASTYEAR 42-45.
    """
    result: dict[str, dict[str, dict[str, int]]] = {}
    for line in text.splitlines():
        if len(line) < 45:
            continue
        station_id = line[0:11].strip()
        element = line[31:35].strip()
        if element not in {"TMAX", "TMIN"}:
            continue
        first_year = safe_int(line[36:40])
        last_year = safe_int(line[41:45])
        if len(station_id) != 11 or first_year is None or last_year is None:
            continue
        result.setdefault(station_id, {})[element] = {
            "first_year": first_year,
            "last_year": last_year,
        }
    return result


def new_extreme() -> None:
    return None


def new_element_stats() -> dict:
    return {
        "valid_count": 0,
        "qflag_rejected": 0,
        "hard_rejected": 0,
        "invalid_calendar_day": 0,
        "first_valid_date": None,
        "last_valid_date": None,
        "highest": None,
        "lowest": None,
    }


def new_station_stats() -> dict:
    return {
        "TMAX": new_element_stats(),
        "TMIN": new_element_stats(),
    }


def occurrence(date_iso: str, mflag: str, sflag: str) -> dict:
    return {
        "date": date_iso,
        "mflag": mflag or "",
        "sflag": sflag or "",
    }


def update_extreme(
    current: dict | None,
    value_tenths: int,
    date_iso: str,
    mflag: str,
    sflag: str,
    mode: str,
) -> dict:
    assert mode in {"max", "min"}
    better = (
        current is None
        or (mode == "max" and value_tenths > current["value_tenths"])
        or (mode == "min" and value_tenths < current["value_tenths"])
    )

    if better:
        return {
            "value_tenths": value_tenths,
            "value_c": round(value_tenths / 10.0, 1),
            "date": date_iso,
            "first_date": date_iso,
            "last_date": date_iso,
            "tie_count": 1,
            "occurrences_sample": [occurrence(date_iso, mflag, sflag)],
            "qc": "ghcn_qflag_blank",
        }

    if value_tenths == current["value_tenths"]:
        current["tie_count"] += 1
        if date_iso < current["first_date"]:
            current["first_date"] = date_iso
            current["date"] = date_iso
        if date_iso > current["last_date"]:
            current["last_date"] = date_iso
        if len(current["occurrences_sample"]) < EXTREME_SAMPLE_LIMIT:
            current["occurrences_sample"].append(occurrence(date_iso, mflag, sflag))
    return current


def parse_dly_file(
    fileobj: BinaryIO,
    station_id: str,
    cutoff_year: int,
    station_stats: dict,
    global_qflags: dict[str, Counter],
    global_counts: Counter,
    reject_samples: list[dict],
    malformed_samples: list[dict],
) -> None:
    for raw_line in fileobj:
        line = raw_line.rstrip(b"\r\n")
        if len(line) < 269:
            global_counts["malformed_lines"] += 1
            if len(malformed_samples) < REJECT_SAMPLE_LIMIT:
                malformed_samples.append({
                    "station_id": station_id,
                    "reason": "line_too_short",
                    "length": len(line),
                })
            continue

        line_station = line[0:11].decode("ascii", errors="replace").strip()
        if line_station != station_id:
            global_counts["station_id_mismatch_lines"] += 1
            if len(malformed_samples) < REJECT_SAMPLE_LIMIT:
                malformed_samples.append({
                    "station_id": station_id,
                    "line_station_id": line_station,
                    "reason": "station_id_mismatch",
                })
            continue

        try:
            year = int(line[11:15])
            month = int(line[15:17])
        except ValueError:
            global_counts["malformed_lines"] += 1
            continue

        if year > cutoff_year:
            global_counts["future_year_lines_skipped"] += 1
            continue
        if year < 1700 or not (1 <= month <= 12):
            global_counts["malformed_lines"] += 1
            continue

        element = line[17:21].decode("ascii", errors="replace")
        if element not in {"TMAX", "TMIN"}:
            continue

        element_stats = station_stats[element]
        days_in_month = calendar.monthrange(year, month)[1]

        for day in range(1, 32):
            offset = 21 + (day - 1) * 8
            try:
                value = int(line[offset:offset + 5])
            except ValueError:
                global_counts["malformed_value_fields"] += 1
                continue

            if value == -9999:
                continue

            mflag = chr(line[offset + 5]).strip()
            qflag = chr(line[offset + 6]).strip()
            sflag = chr(line[offset + 7]).strip()

            if day > days_in_month:
                element_stats["invalid_calendar_day"] += 1
                global_counts[f"{element}_invalid_calendar_day"] += 1
                if len(reject_samples) < REJECT_SAMPLE_LIMIT:
                    reject_samples.append({
                        "station_id": station_id,
                        "element": element,
                        "date": f"{year:04d}-{month:02d}-{day:02d}",
                        "value_c": value / 10.0,
                        "reason": "invalid_calendar_day",
                    })
                continue

            date_iso = f"{year:04d}-{month:02d}-{day:02d}"

            # NOAA: leerer QFLAG = kein QA-Check fehlgeschlagen.
            if qflag:
                element_stats["qflag_rejected"] += 1
                global_counts[f"{element}_qflag_rejected"] += 1
                global_qflags[element][qflag] += 1
                continue

            # Extra-breite Plausibilitaetsgrenze nur gegen Parser-/Einheitenfehler.
            if not (HARD_TEMP_MIN_TENTHS <= value <= HARD_TEMP_MAX_TENTHS):
                element_stats["hard_rejected"] += 1
                global_counts[f"{element}_hard_rejected"] += 1
                if len(reject_samples) < REJECT_SAMPLE_LIMIT:
                    reject_samples.append({
                        "station_id": station_id,
                        "element": element,
                        "date": date_iso,
                        "value_c": value / 10.0,
                        "mflag": mflag,
                        "sflag": sflag,
                        "reason": "outside_hard_temperature_bounds",
                    })
                continue

            element_stats["valid_count"] += 1
            global_counts[f"{element}_valid"] += 1
            if element_stats["first_valid_date"] is None or date_iso < element_stats["first_valid_date"]:
                element_stats["first_valid_date"] = date_iso
            if element_stats["last_valid_date"] is None or date_iso > element_stats["last_valid_date"]:
                element_stats["last_valid_date"] = date_iso

            element_stats["highest"] = update_extreme(
                element_stats["highest"], value, date_iso, mflag, sflag, "max"
            )
            element_stats["lowest"] = update_extreme(
                element_stats["lowest"], value, date_iso, mflag, sflag, "min"
            )


class ProgressReader:
    """Zaehlt komprimierte HTTP-Bytes, ohne den Stream auf Platte zu schreiben."""

    def __init__(self, raw, total_bytes: int | None):
        self.raw = raw
        self.total_bytes = total_bytes
        self.bytes_read = 0
        self.next_report = PROGRESS_BYTES
        self.started = time.monotonic()

    def read(self, size: int = -1) -> bytes:
        data = self.raw.read(size)
        if data:
            self.bytes_read += len(data)
            if self.bytes_read >= self.next_report:
                elapsed = max(time.monotonic() - self.started, 0.001)
                mb = self.bytes_read / (1024 * 1024)
                rate = mb / elapsed
                if self.total_bytes:
                    pct = self.bytes_read / self.total_bytes * 100.0
                    print(
                        f"  GHCN-Archiv: {mb:,.0f} MiB / "
                        f"{self.total_bytes / (1024*1024):,.0f} MiB "
                        f"({pct:5.1f} %), {rate:,.1f} MiB/s komprimiert",
                        flush=True,
                    )
                else:
                    print(
                        f"  GHCN-Archiv: {mb:,.0f} MiB gelesen, "
                        f"{rate:,.1f} MiB/s komprimiert",
                        flush=True,
                    )
                while self.next_report <= self.bytes_read:
                    self.next_report += PROGRESS_BYTES
        return data


def stream_archive_once(
    archive_url: str,
    target_ids: set[str],
    cutoff_year: int,
) -> tuple[dict[str, dict], dict]:
    station_results: dict[str, dict] = {}
    seen_target_ids: set[str] = set()
    global_qflags = {"TMAX": Counter(), "TMIN": Counter()}
    global_counts: Counter = Counter()
    reject_samples: list[dict] = []
    malformed_samples: list[dict] = []

    req = Request(
        archive_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/gzip, application/octet-stream, */*",
            "Accept-Encoding": "identity",
        },
    )

    print(f"\nStreame grosses GHCN-Archiv:\n{archive_url}", flush=True)
    with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
        total_header = response.headers.get("Content-Length")
        total_bytes = int(total_header) if total_header and total_header.isdigit() else None
        if total_bytes:
            print(
                f"Komprimierte Groesse laut Server: "
                f"{total_bytes / (1024**3):.2f} GiB",
                flush=True,
            )
        reader = ProgressReader(response, total_bytes)

        # r|gz = sequenzielles Streaming. Keine temporaere 3,7-GB-Datei.
        with tarfile.open(fileobj=reader, mode="r|gz") as archive:
            for member in archive:
                global_counts["tar_members"] += 1
                if not member.isfile() or not member.name.lower().endswith(".dly"):
                    continue

                station_id = Path(member.name).stem
                if station_id not in target_ids:
                    continue

                seen_target_ids.add(station_id)
                stats = station_results.setdefault(station_id, new_station_stats())
                extracted = archive.extractfile(member)
                if extracted is None:
                    global_counts["target_extract_failures"] += 1
                    continue

                parse_dly_file(
                    extracted,
                    station_id=station_id,
                    cutoff_year=cutoff_year,
                    station_stats=stats,
                    global_qflags=global_qflags,
                    global_counts=global_counts,
                    reject_samples=reject_samples,
                    malformed_samples=malformed_samples,
                )
                global_counts["target_members_processed"] += 1

                processed = global_counts["target_members_processed"]
                if processed % 1000 == 0:
                    print(
                        f"  Temperaturstationen verarbeitet: "
                        f"{processed:,}/{len(target_ids):,}",
                        flush=True,
                    )

        compressed_bytes_read = reader.bytes_read
        compressed_total = reader.total_bytes

    info = {
        "seen_target_ids": seen_target_ids,
        "global_qflags": {
            element: dict(counter)
            for element, counter in global_qflags.items()
        },
        "global_counts": dict(global_counts),
        "reject_samples": reject_samples,
        "malformed_samples": malformed_samples,
        "compressed_bytes_read": compressed_bytes_read,
        "compressed_total_bytes": compressed_total,
    }
    return station_results, info


def stream_archive_with_retries(
    archive_url: str,
    target_ids: set[str],
    cutoff_year: int,
) -> tuple[dict[str, dict], dict]:
    last_error: Exception | None = None
    for attempt in range(1, ARCHIVE_ATTEMPTS + 1):
        try:
            print(
                f"\n=== Archiv-Versuch {attempt}/{ARCHIVE_ATTEMPTS} ===",
                flush=True,
            )
            return stream_archive_once(archive_url, target_ids, cutoff_year)
        except (OSError, EOFError, tarfile.TarError) as exc:
            last_error = exc
            print(
                f"WARNUNG: Archiv-Streaming fehlgeschlagen: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            if attempt < ARCHIVE_ATTEMPTS:
                wait = 20 * attempt
                print(f"Neuer Vollversuch in {wait} s ...", flush=True)
                time.sleep(wait)
    raise RuntimeError(
        f"GHCN-Archiv konnte nach {ARCHIVE_ATTEMPTS} Versuchen nicht "
        f"vollstaendig verarbeitet werden: {last_error}"
    )


def build_station_payload(
    stations_meta: dict[str, dict],
    inventory: dict[str, dict[str, dict[str, int]]],
    station_results: dict[str, dict],
) -> dict[str, dict]:
    payload: dict[str, dict] = {}
    for station_id, elements in inventory.items():
        meta = stations_meta.get(station_id, {
            "id": station_id,
            "country_code": station_id[:2],
            "country": station_id[:2],
            "latitude": None,
            "longitude": None,
            "elevation_m": None,
            "state": None,
            "name": station_id,
            "gsn_flag": "",
            "hcn_crn_flag": "",
            "wmo_id": "",
        })
        result = station_results.get(station_id, new_station_stats())
        payload[station_id] = {
            **meta,
            "inventory": {
                "TMAX": elements.get("TMAX"),
                "TMIN": elements.get("TMIN"),
            },
            "tmax": {
                **result["TMAX"],
                "highest_record": result["TMAX"]["highest"],
                "lowest_record": result["TMAX"]["lowest"],
            },
            "tmin": {
                **result["TMIN"],
                "lowest_record": result["TMIN"]["lowest"],
                "highest_record": result["TMIN"]["highest"],
            },
        }
        # Interne Alias-Felder nicht doppelt im Cache halten.
        payload[station_id]["tmax"].pop("highest", None)
        payload[station_id]["tmax"].pop("lowest", None)
        payload[station_id]["tmin"].pop("highest", None)
        payload[station_id]["tmin"].pop("lowest", None)
    return payload


def coverage_count(stations: dict[str, dict], path: tuple[str, str]) -> int:
    section, key = path
    return sum(1 for item in stations.values() if item[section].get(key) is not None)


def build_summary(
    stations: dict[str, dict],
    inventory: dict[str, dict],
    target_ids: set[str],
    stream_info: dict,
    cutoff_year: int,
    ghcn_version: str,
    started_monotonic: float,
) -> dict:
    counts = stream_info["global_counts"]
    seen_target_ids = stream_info["seen_target_ids"]
    missing_target_ids = sorted(target_ids - seen_target_ids)

    temp_station_count = len(inventory)
    with_tmax = sum("TMAX" in x for x in inventory.values())
    with_tmin = sum("TMIN" in x for x in inventory.values())
    with_both = sum(
        "TMAX" in x and "TMIN" in x
        for x in inventory.values()
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_version": BASELINE_VERSION,
        "cutoff_year": cutoff_year,
        "generated_at_utc": utc_now_iso(),
        "ghcn_version": ghcn_version.strip(),
        "source_archive": ARCHIVE_URL,
        "temperature_station_count": temp_station_count,
        "stations_with_tmax_inventory": with_tmax,
        "stations_with_tmin_inventory": with_tmin,
        "stations_with_both_inventory": with_both,
        "historical_target_station_count": len(target_ids),
        "historical_target_members_seen": len(seen_target_ids),
        "historical_target_member_coverage": (
            len(seen_target_ids) / len(target_ids) if target_ids else 1.0
        ),
        "missing_target_station_count": len(missing_target_ids),
        "missing_target_station_sample": missing_target_ids[:100],
        "valid_observations": {
            "TMAX": counts.get("TMAX_valid", 0),
            "TMIN": counts.get("TMIN_valid", 0),
        },
        "qflag_rejected_observations": {
            "TMAX": counts.get("TMAX_qflag_rejected", 0),
            "TMIN": counts.get("TMIN_qflag_rejected", 0),
        },
        "qflag_counts": stream_info["global_qflags"],
        "hard_rejected_observations": {
            "TMAX": counts.get("TMAX_hard_rejected", 0),
            "TMIN": counts.get("TMIN_hard_rejected", 0),
        },
        "invalid_calendar_day_observations": {
            "TMAX": counts.get("TMAX_invalid_calendar_day", 0),
            "TMIN": counts.get("TMIN_invalid_calendar_day", 0),
        },
        "malformed_lines": counts.get("malformed_lines", 0),
        "malformed_value_fields": counts.get("malformed_value_fields", 0),
        "station_id_mismatch_lines": counts.get("station_id_mismatch_lines", 0),
        "target_extract_failures": counts.get("target_extract_failures", 0),
        "future_year_lines_skipped": counts.get("future_year_lines_skipped", 0),
        "tar_members": counts.get("tar_members", 0),
        "target_members_processed": counts.get("target_members_processed", 0),
        "compressed_archive_bytes_read": stream_info.get("compressed_bytes_read"),
        "compressed_archive_total_bytes": stream_info.get("compressed_total_bytes"),
        "extreme_station_coverage": {
            "tmax_highest": coverage_count(stations, ("tmax", "highest_record")),
            "tmax_lowest": coverage_count(stations, ("tmax", "lowest_record")),
            "tmin_lowest": coverage_count(stations, ("tmin", "lowest_record")),
            "tmin_highest": coverage_count(stations, ("tmin", "highest_record")),
        },
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 1),
        "qc_policy": {
            "accepted_qflag": "blank only",
            "hard_temperature_min_c": HARD_TEMP_MIN_TENTHS / 10.0,
            "hard_temperature_max_c": HARD_TEMP_MAX_TENTHS / 10.0,
            "note": (
                "Die harte Temperaturgrenze ist nur eine Parsing-/Katastrophen-"
                "Sicherung. Fachliche Rekordverifikation (Maxcrc/WMO/nationale "
                "Wetterdienste) folgt in einem spaeteren Schritt."
            ),
        },
    }


def validate_baseline(summary: dict) -> None:
    errors: list[str] = []

    if summary["temperature_station_count"] < MIN_EXPECTED_TEMP_STATIONS:
        errors.append(
            f"Nur {summary['temperature_station_count']:,} Temperaturstationen "
            f"(erwartet mindestens {MIN_EXPECTED_TEMP_STATIONS:,})."
        )

    coverage = summary["historical_target_member_coverage"]
    if coverage < MIN_TARGET_MEMBER_COVERAGE:
        errors.append(
            f"Nur {coverage*100:.2f} % der historischen Temperaturstationen "
            "wurden im TAR-Archiv gefunden."
        )

    for element in ("TMAX", "TMIN"):
        valid = summary["valid_observations"][element]
        if valid < MIN_EXPECTED_VALID_OBSERVATIONS:
            errors.append(
                f"Nur {valid:,} gueltige {element}-Tageswerte verarbeitet."
            )

    if summary["target_extract_failures"] > 0:
        errors.append(
            f"{summary['target_extract_failures']} Ziel-Stationsdateien konnten "
            "nicht aus dem TAR gelesen werden."
        )

    if errors:
        raise RuntimeError(
            "Baseline-Plausibilitaetspruefung fehlgeschlagen:\n- "
            + "\n- ".join(errors)
        )


METRICS = {
    "tmax_highest": ("tmax", "highest_record", True),
    "tmax_lowest": ("tmax", "lowest_record", False),
    "tmin_lowest": ("tmin", "lowest_record", False),
    "tmin_highest": ("tmin", "highest_record", True),
}


def write_country_candidates(
    stations: dict[str, dict],
    path: Path,
    top_n: int,
) -> None:
    grouped: dict[tuple[str, str], list[dict]] = {}

    for station in stations.values():
        country_code = station["country_code"]
        for metric, (section, key, descending) in METRICS.items():
            record = station[section].get(key)
            if record is None:
                continue
            grouped.setdefault((country_code, metric), []).append({
                "station": station,
                "record": record,
                "descending": descending,
            })

    fieldnames = [
        "country_code", "country", "metric", "rank",
        "station_id", "station_name",
        "value_c", "date", "first_date", "last_date", "tie_count",
        "latitude", "longitude", "elevation_m",
        "mflag_first_sample", "sflag_first_sample",
        "qc",
    ]

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for country_metric in sorted(grouped):
            rows = grouped[country_metric]
            descending = rows[0]["descending"]
            rows.sort(
                key=lambda x: (
                    x["record"]["value_tenths"],
                    x["station"]["id"],
                ),
                reverse=descending,
            )
            for rank, entry in enumerate(rows[:top_n], start=1):
                station = entry["station"]
                record = entry["record"]
                first_occ = (
                    record["occurrences_sample"][0]
                    if record.get("occurrences_sample")
                    else {}
                )
                writer.writerow({
                    "country_code": station["country_code"],
                    "country": station["country"],
                    "metric": country_metric[1],
                    "rank": rank,
                    "station_id": station["id"],
                    "station_name": station["name"],
                    "value_c": f"{record['value_c']:.1f}",
                    "date": record["date"],
                    "first_date": record["first_date"],
                    "last_date": record["last_date"],
                    "tie_count": record["tie_count"],
                    "latitude": station["latitude"],
                    "longitude": station["longitude"],
                    "elevation_m": station["elevation_m"],
                    "mflag_first_sample": first_occ.get("mflag", ""),
                    "sflag_first_sample": first_occ.get("sflag", ""),
                    "qc": record.get("qc", ""),
                })


def write_station_qc_summary(stations: dict[str, dict], path: Path) -> None:
    fieldnames = [
        "station_id", "country_code", "country", "station_name",
        "tmax_valid", "tmax_qflag_rejected", "tmax_hard_rejected",
        "tmax_first_valid", "tmax_last_valid",
        "tmin_valid", "tmin_qflag_rejected", "tmin_hard_rejected",
        "tmin_first_valid", "tmin_last_valid",
    ]
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for station_id in sorted(stations):
            s = stations[station_id]
            writer.writerow({
                "station_id": station_id,
                "country_code": s["country_code"],
                "country": s["country"],
                "station_name": s["name"],
                "tmax_valid": s["tmax"]["valid_count"],
                "tmax_qflag_rejected": s["tmax"]["qflag_rejected"],
                "tmax_hard_rejected": s["tmax"]["hard_rejected"],
                "tmax_first_valid": s["tmax"]["first_valid_date"],
                "tmax_last_valid": s["tmax"]["last_valid_date"],
                "tmin_valid": s["tmin"]["valid_count"],
                "tmin_qflag_rejected": s["tmin"]["qflag_rejected"],
                "tmin_hard_rejected": s["tmin"]["hard_rejected"],
                "tmin_first_valid": s["tmin"]["first_valid_date"],
                "tmin_last_valid": s["tmin"]["last_valid_date"],
            })


def format_int(value: int | None) -> str:
    if value is None:
        return "–"
    return f"{value:,}"


def write_report(payload: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = payload["summary"]
    stations = payload["stations"]

    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (output_dir / "rejected_samples.json").write_text(
        json.dumps(payload.get("rejected_samples", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "malformed_samples.json").write_text(
        json.dumps(payload.get("malformed_samples", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    write_country_candidates(
        stations,
        output_dir / "world_country_extreme_candidates_top10.csv",
        top_n=10,
    )
    write_station_qc_summary(
        stations,
        output_dir / "world_station_qc_summary.csv.gz",
    )

    qflag_lines = []
    for element in ("TMAX", "TMIN"):
        flags = summary["qflag_counts"].get(element, {})
        details = ", ".join(
            f"{flag}={count:,}"
            for flag, count in sorted(flags.items())
        ) or "keine"
        qflag_lines.append(f"- {element}: {details}")

    report = f"""# GHCN World Historical Temperature Baseline

**Baseline:** V{summary['baseline_version']} · bis einschließlich {summary['cutoff_year']}  
**Erstellt:** {summary['generated_at_utc']}  
**GHCN-Version:** {summary['ghcn_version']}

## Stationsnetz

- Temperaturstationen im GHCN-Inventar: {summary['temperature_station_count']:,}
- mit TMAX: {summary['stations_with_tmax_inventory']:,}
- mit TMIN: {summary['stations_with_tmin_inventory']:,}
- mit TMAX + TMIN: {summary['stations_with_both_inventory']:,}
- historische Zielstationen bis {summary['cutoff_year']}: {summary['historical_target_station_count']:,}
- davon im TAR gefunden: {summary['historical_target_members_seen']:,} ({summary['historical_target_member_coverage']*100:.2f} %)
- fehlende Zielstationen: {summary['missing_target_station_count']:,}

## Gültige Tageswerte

- TMAX: {summary['valid_observations']['TMAX']:,}
- TMIN: {summary['valid_observations']['TMIN']:,}

## Durch GHCN-QFLAG verworfen

- TMAX: {summary['qflag_rejected_observations']['TMAX']:,}
- TMIN: {summary['qflag_rejected_observations']['TMIN']:,}

### QFLAG-Verteilung

{chr(10).join(qflag_lines)}

## Zusätzliche harte Parsing-Sicherung

Akzeptierter Temperaturbereich: {summary['qc_policy']['hard_temperature_min_c']:.1f} bis {summary['qc_policy']['hard_temperature_max_c']:.1f} °C

- TMAX dadurch verworfen: {summary['hard_rejected_observations']['TMAX']:,}
- TMIN dadurch verworfen: {summary['hard_rejected_observations']['TMIN']:,}

Diese Grenze ist **keine fachliche Weltrekorddefinition**. Sie schützt nur vor groben
Einheiten-/Parsingfehlern. Die fachliche Verifikation gegen Maxcrc/Wikipedia,
WMO und nationale Wetterdienste kommt in einem späteren Schritt.

## Stationen mit berechnetem Allzeit-Extrem

- höchstes TMAX: {summary['extreme_station_coverage']['tmax_highest']:,}
- niedrigstes TMAX: {summary['extreme_station_coverage']['tmax_lowest']:,}
- niedrigstes TMIN: {summary['extreme_station_coverage']['tmin_lowest']:,}
- höchstes TMIN: {summary['extreme_station_coverage']['tmin_highest']:,}

## Technische Kontrolle

- TAR-Mitglieder gelesen: {summary['tar_members']:,}
- Temperatur-Stationsdateien verarbeitet: {summary['target_members_processed']:,}
- malformed lines: {summary['malformed_lines']:,}
- malformed value fields: {summary['malformed_value_fields']:,}
- Stations-ID-Mismatches: {summary['station_id_mismatch_lines']:,}
- Extract-Fehler: {summary['target_extract_failures']:,}
- Laufzeit: {summary['elapsed_seconds']/60:.1f} Minuten

## Dateien

- `world_ghcn_baseline_through_{summary['cutoff_year']}_v{summary['baseline_version']}.pkl.gz` – historischer Cache für den nächsten Schritt
- `world_country_extreme_candidates_top10.csv` – Top-10-Kandidaten je Land und Extremtyp; Grundlage für Maxcrc/WMO-QC
- `world_station_qc_summary.csv.gz` – Stationsweise Zählung gültiger und verworfener Werte
- `rejected_samples.json` – Stichprobe der zusätzlich hart verworfenen Werte
- `malformed_samples.json` – Stichprobe struktureller Parser-Auffälligkeiten

"""
    (output_dir / "report.md").write_text(report, encoding="utf-8")


def cache_filename(cutoff_year: int) -> str:
    return (
        f"world_ghcn_baseline_through_{cutoff_year}_"
        f"v{BASELINE_VERSION}.pkl.gz"
    )


def save_cache(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def load_cache(path: Path) -> dict:
    with gzip.open(path, "rb") as handle:
        payload = pickle.load(handle)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("Cache-Schema passt nicht zur aktuellen Skriptversion.")
    if payload.get("baseline_version") != BASELINE_VERSION:
        raise RuntimeError("Baseline-Version im Cache passt nicht.")
    return payload


def create_baseline(
    cutoff_year: int,
    archive_url: str,
) -> dict:
    started = time.monotonic()

    countries_text = download_text(COUNTRIES_URL)
    stations_text = download_text(STATIONS_URL)
    inventory_text = download_text(INVENTORY_URL)
    ghcn_version = download_text(VERSION_URL).strip()

    countries = parse_countries(countries_text)
    stations_meta = parse_stations(stations_text, countries)
    inventory = parse_inventory(inventory_text)

    if len(inventory) < MIN_EXPECTED_TEMP_STATIONS:
        raise RuntimeError(
            f"GHCN-Inventar enthält nur {len(inventory):,} Temperaturstationen."
        )

    target_ids = {
        station_id
        for station_id, elements in inventory.items()
        if any(
            details["first_year"] <= cutoff_year
            for details in elements.values()
        )
    }

    print("\n====================================================================")
    print("GHCN WORLD HISTORICAL TEMPERATURE BASELINE")
    print("====================================================================")
    print(f"Temperaturstationen im Inventar:       {len(inventory):,}")
    print(f"Historische Zielstationen <= {cutoff_year}:    {len(target_ids):,}")
    print(f"GHCN-Version:                         {ghcn_version}")
    print("QC: nur leerer QFLAG + harte Parsing-Sicherung")
    print("====================================================================", flush=True)

    station_results, stream_info = stream_archive_with_retries(
        archive_url=archive_url,
        target_ids=target_ids,
        cutoff_year=cutoff_year,
    )

    stations = build_station_payload(
        stations_meta=stations_meta,
        inventory=inventory,
        station_results=station_results,
    )

    summary = build_summary(
        stations=stations,
        inventory=inventory,
        target_ids=target_ids,
        stream_info=stream_info,
        cutoff_year=cutoff_year,
        ghcn_version=ghcn_version,
        started_monotonic=started,
    )
    validate_baseline(summary)

    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_version": BASELINE_VERSION,
        "cutoff_year": cutoff_year,
        "summary": summary,
        "stations": stations,
        "rejected_samples": stream_info["reject_samples"],
        "malformed_samples": stream_info["malformed_samples"],
    }


def make_dly_line(
    station_id: str,
    year: int,
    month: int,
    element: str,
    values: dict[int, tuple[int, str, str, str]],
) -> bytes:
    assert len(station_id) == 11
    chunks = [f"{station_id}{year:04d}{month:02d}{element}"]
    for day in range(1, 32):
        value, mflag, qflag, sflag = values.get(day, (-9999, " ", " ", " "))
        chunks.append(f"{value:5d}{mflag[:1] or ' '}{qflag[:1] or ' '}{sflag[:1] or ' '}")
    line = "".join(chunks)
    assert len(line) == 269
    return (line + "\n").encode("ascii")


def run_self_test() -> None:
    sid = "XX000000001"
    tmax_2020 = make_dly_line(
        sid, 2020, 1, "TMAX",
        {
            1: (100, " ", " ", "G"),
            2: (150, " ", " ", "G"),
            3: (150, "H", " ", "G"),
            4: (700, " ", " ", "G"),   # harte Grenze -> raus
            5: (200, " ", "X", "G"),   # QFLAG -> raus
            6: (-200, " ", " ", "G"),
        },
    )
    tmin_2020 = make_dly_line(
        sid, 2020, 1, "TMIN",
        {
            1: (-300, " ", " ", "G"),
            2: (-300, " ", " ", "G"),
            3: (250, " ", " ", "G"),
            4: (260, " ", "S", "G"),   # QFLAG -> raus
            5: (700, " ", " ", "G"),   # harte Grenze -> raus
        },
    )
    tmax_2026 = make_dly_line(
        sid, 2026, 1, "TMAX",
        {1: (500, " ", " ", "G")},     # nach cutoff -> raus
    )

    stats = new_station_stats()
    qflags = {"TMAX": Counter(), "TMIN": Counter()}
    counts = Counter()
    rejects: list[dict] = []
    malformed: list[dict] = []

    parse_dly_file(
        io.BytesIO(tmax_2020 + tmin_2020 + tmax_2026),
        sid, 2025, stats, qflags, counts, rejects, malformed,
    )

    assert stats["TMAX"]["highest"]["value_tenths"] == 150
    assert stats["TMAX"]["highest"]["tie_count"] == 2
    assert stats["TMAX"]["lowest"]["value_tenths"] == -200
    assert stats["TMIN"]["lowest"]["value_tenths"] == -300
    assert stats["TMIN"]["lowest"]["tie_count"] == 2
    assert stats["TMIN"]["highest"]["value_tenths"] == 250
    assert stats["TMAX"]["qflag_rejected"] == 1
    assert stats["TMIN"]["qflag_rejected"] == 1
    assert stats["TMAX"]["hard_rejected"] == 1
    assert stats["TMIN"]["hard_rejected"] == 1
    assert counts["future_year_lines_skipped"] == 1
    assert qflags["TMAX"]["X"] == 1
    assert qflags["TMIN"]["S"] == 1
    assert not malformed

    # Auch die NOAA-Fixed-Width-Metadaten-Slices absichern.
    country_text = "XX Testland\n"
    countries = parse_countries(country_text)
    assert countries["XX"] == "Testland"

    inv_line = f"{sid} {12.3456:8.4f} {23.4567:9.4f} TMAX 1901 2026"
    assert len(inv_line) >= 45
    parsed_inv = parse_inventory(inv_line + "\n")
    assert parsed_inv[sid]["TMAX"]["first_year"] == 1901
    assert parsed_inv[sid]["TMAX"]["last_year"] == 2026

    print("Self-test OK")
    print("  QFLAG-Filter OK")
    print("  TMAX high/low OK")
    print("  TMIN low/high OK")
    print("  Gleichstandszaehlung OK")
    print("  cutoff 2025 OK")
    print("  harte Parsing-Grenze OK")
    print("  Inventory-Fixed-Width OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff-year", type=int, default=DEFAULT_CUTOFF_YEAR)
    parser.add_argument("--cache-dir", default=".cache/world-ghcn")
    parser.add_argument("--output", default="world_ghcn_baseline")
    parser.add_argument("--archive-url", default=ARCHIVE_URL)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return 0

    if args.cutoff_year < 1800 or args.cutoff_year > datetime.now(timezone.utc).year:
        raise SystemExit("Unplausibles --cutoff-year.")

    cache_dir = Path(args.cache_dir)
    output_dir = Path(args.output)
    cache_path = cache_dir / cache_filename(args.cutoff_year)

    if cache_path.exists() and not args.force:
        print(f"Verwende vorhandenen historischen Welt-GHCN-Cache: {cache_path}")
        payload = load_cache(cache_path)
    else:
        payload = create_baseline(
            cutoff_year=args.cutoff_year,
            archive_url=args.archive_url,
        )
        save_cache(payload, cache_path)
        print(f"\nHistorischer Cache gespeichert: {cache_path}")

    # Reports bei jedem Lauf neu erzeugen, damit ein Cache-Hit trotzdem
    # ein vollstaendiges GitHub-Artifact liefert.
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_report(payload, output_dir)

    artifact_cache = output_dir / cache_path.name
    shutil.copy2(cache_path, artifact_cache)

    summary = payload["summary"]
    print("\n====================================================================")
    print("GHCN WORLD BASELINE · FERTIG")
    print("====================================================================")
    print(f"Temperaturstationen:                   {summary['temperature_station_count']:,}")
    print(f"Historische Zielstationen:             {summary['historical_target_station_count']:,}")
    print(f"Im TAR gefunden:                       {summary['historical_target_members_seen']:,}")
    print(f"Gueltige TMAX-Tageswerte:              {summary['valid_observations']['TMAX']:,}")
    print(f"Gueltige TMIN-Tageswerte:              {summary['valid_observations']['TMIN']:,}")
    print(f"QFLAG verworfen TMAX:                  {summary['qflag_rejected_observations']['TMAX']:,}")
    print(f"QFLAG verworfen TMIN:                  {summary['qflag_rejected_observations']['TMIN']:,}")
    print(f"Stationen mit hoechstem TMAX:          {summary['extreme_station_coverage']['tmax_highest']:,}")
    print(f"Stationen mit niedrigstem TMAX:        {summary['extreme_station_coverage']['tmax_lowest']:,}")
    print(f"Stationen mit niedrigstem TMIN:        {summary['extreme_station_coverage']['tmin_lowest']:,}")
    print(f"Stationen mit hoechstem TMIN:          {summary['extreme_station_coverage']['tmin_highest']:,}")
    print(f"Cache:                                  {cache_path}")
    print(f"Artifact-Ausgabe:                       {output_dir}")
    print("====================================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
