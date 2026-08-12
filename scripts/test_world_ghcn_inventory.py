#!/usr/bin/env python3
"""Build a lightweight worldwide GHCN-Daily temperature-station inventory.

Step 1 only: download/parse NOAA metadata. No daily observation archive is downloaded.
Outputs are intended for inspection before the historical world-record cache is built.

NOAA metadata files:
- ghcnd-stations.txt: station metadata
- ghcnd-inventory.txt: first/last unflagged year by element
- ghcnd-countries.txt: GHCN FIPS-style country codes
- ghcnd-version.txt: dataset version information
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
FILES = {
    "stations": "ghcnd-stations.txt",
    "inventory": "ghcnd-inventory.txt",
    "countries": "ghcnd-countries.txt",
    "version": "ghcnd-version.txt",
}
TEMPERATURE_ELEMENTS = {"TMAX", "TMIN"}
USER_AGENT = "climate-dashboard-world-ghcn-inventory/1.0"


@dataclass
class StationMeta:
    station_id: str
    latitude: Optional[float]
    longitude: Optional[float]
    elevation_m: Optional[float]
    state: str
    name: str
    gsn_flag: str
    hcn_crn_flag: str
    wmo_id: str
    country_code: str


def parse_float(text: str, missing: Optional[float] = None) -> Optional[float]:
    text = text.strip()
    if not text:
        return None
    value = float(text)
    if missing is not None and value == missing:
        return None
    return value


def parse_int(text: str) -> Optional[int]:
    text = text.strip()
    return int(text) if text else None


def parse_station_line(line: str) -> StationMeta:
    # NOAA readme columns are 1-based; Python slices below are 0-based/end-exclusive.
    station_id = line[0:11].strip()
    return StationMeta(
        station_id=station_id,
        latitude=parse_float(line[12:20]),
        longitude=parse_float(line[21:30]),
        elevation_m=parse_float(line[31:37], missing=-999.9),
        state=line[38:40].strip(),
        name=line[41:71].strip(),
        gsn_flag=line[72:75].strip(),
        hcn_crn_flag=line[76:79].strip(),
        wmo_id=line[80:85].strip(),
        country_code=station_id[:2],
    )


def parse_inventory_line(line: str) -> tuple[str, str, int, int]:
    station_id = line[0:11].strip()
    element = line[31:35].strip()
    first_year = int(line[36:40])
    last_year = int(line[41:45])
    return station_id, element, first_year, last_year


def parse_countries(lines: Iterable[str]) -> Dict[str, str]:
    countries: Dict[str, str] = {}
    for raw in lines:
        line = raw.rstrip("\n\r")
        if not line.strip():
            continue
        code = line[0:2].strip()
        name = line[3:64].strip()
        if code:
            countries[code] = name
    return countries


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, destination: Path, retries: int = 4, timeout: int = 120) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        tmp = destination.with_suffix(destination.suffix + ".part")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response, tmp.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            if tmp.stat().st_size == 0:
                raise RuntimeError(f"Leere Datei von {url}")
            tmp.replace(destination)
            return
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
            last_error = exc
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            if attempt < retries:
                wait = 3 * attempt
                print(f"Downloadversuch {attempt}/{retries} fehlgeschlagen: {exc}; neuer Versuch in {wait}s …")
                time.sleep(wait)
    raise RuntimeError(f"Download fehlgeschlagen: {url}: {last_error}")


def ensure_metadata(cache_dir: Path, refresh: bool) -> Dict[str, Path]:
    paths: Dict[str, Path] = {}
    for key, filename in FILES.items():
        path = cache_dir / filename
        if refresh or not path.exists() or path.stat().st_size == 0:
            print(f"Lade NOAA {filename} …")
            download(f"{BASE_URL}/{filename}", path)
        else:
            print(f"Verwende lokalen Metadaten-Cache: {path}")
        paths[key] = path
    return paths


def span_years(first: Optional[int], last: Optional[int]) -> Optional[int]:
    if first is None or last is None or last < first:
        return None
    return last - first + 1


def overlap_span(tmax: Optional[dict], tmin: Optional[dict]) -> Optional[int]:
    if not tmax or not tmin:
        return None
    first = max(tmax["first_year"], tmin["first_year"])
    last = min(tmax["last_year"], tmin["last_year"])
    return max(0, last - first + 1)


def bool01(value: bool) -> int:
    return 1 if value else 0


def inventory_record_is_current(rec: Optional[dict], current_year: int) -> bool:
    return bool(rec and rec["last_year"] == current_year)


def self_test() -> None:
    station = (
        "USW00094728 40.7789  -73.9692   39.6 NY NEW YORK CNTRL PK TWR        "
        "              72506"
    )
    parsed = parse_station_line(station.ljust(85))
    assert parsed.station_id == "USW00094728"
    assert abs((parsed.latitude or 0) - 40.7789) < 1e-6
    assert abs((parsed.longitude or 0) - (-73.9692)) < 1e-6
    assert parsed.country_code == "US"

    inv = f"{'USW00094728':<11} {40.7789:8.4f} {-73.9692:9.4f} {'TMAX':<4} {1869:4d} {2026:4d}"
    sid, elem, first, last = parse_inventory_line(inv.ljust(45))
    assert sid == "USW00094728"
    assert elem == "TMAX"
    assert first == 1869 and last == 2026

    countries = parse_countries(["US United States\n", "GM Germany\n"])
    assert countries["US"] == "United States"
    assert countries["GM"] == "Germany"
    assert span_years(1991, 2020) == 30
    assert overlap_span({"first_year": 1900, "last_year": 2026}, {"first_year": 1910, "last_year": 2025}) == 116
    print("World GHCN inventory self-test OK")


def build_inventory(metadata: Dict[str, Path], output_dir: Path, current_year: int) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    with metadata["countries"].open("r", encoding="utf-8", errors="replace") as f:
        countries = parse_countries(f)

    stations: Dict[str, StationMeta] = {}
    with metadata["stations"].open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            if not raw.strip():
                continue
            meta = parse_station_line(raw.rstrip("\n\r").ljust(85))
            if meta.station_id:
                stations[meta.station_id] = meta

    elements: Dict[str, Dict[str, dict]] = defaultdict(dict)
    inventory_temp_lines = 0
    with metadata["inventory"].open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            if len(raw) < 45:
                continue
            station_id, element, first_year, last_year = parse_inventory_line(raw.rstrip("\n\r").ljust(45))
            if element not in TEMPERATURE_ELEMENTS:
                continue
            inventory_temp_lines += 1
            existing = elements[station_id].get(element)
            if existing:
                # Defensive merge if NOAA ever contains multiple inventory ranges.
                first_year = min(first_year, existing["first_year"])
                last_year = max(last_year, existing["last_year"])
            elements[station_id][element] = {
                "first_year": first_year,
                "last_year": last_year,
                "span_years": last_year - first_year + 1,
            }

    rows = []
    missing_station_metadata = 0
    for station_id in sorted(elements):
        meta = stations.get(station_id)
        if meta is None:
            missing_station_metadata += 1
            continue
        tmax = elements[station_id].get("TMAX")
        tmin = elements[station_id].get("TMIN")
        country_name = countries.get(meta.country_code, f"Unknown ({meta.country_code})")
        overlap = overlap_span(tmax, tmin)
        rows.append({
            "station_id": station_id,
            "country_code": meta.country_code,
            "country_name": country_name,
            "name": meta.name,
            "state": meta.state,
            "latitude": meta.latitude,
            "longitude": meta.longitude,
            "elevation_m": meta.elevation_m,
            "wmo_id": meta.wmo_id,
            "gsn_flag": meta.gsn_flag,
            "hcn_crn_flag": meta.hcn_crn_flag,
            "has_tmax": bool01(tmax is not None),
            "tmax_first_year": tmax["first_year"] if tmax else None,
            "tmax_last_year": tmax["last_year"] if tmax else None,
            "tmax_span_years": tmax["span_years"] if tmax else None,
            "tmax_current_year": bool01(inventory_record_is_current(tmax, current_year)),
            "has_tmin": bool01(tmin is not None),
            "tmin_first_year": tmin["first_year"] if tmin else None,
            "tmin_last_year": tmin["last_year"] if tmin else None,
            "tmin_span_years": tmin["span_years"] if tmin else None,
            "tmin_current_year": bool01(inventory_record_is_current(tmin, current_year)),
            "has_both": bool01(tmax is not None and tmin is not None),
            "both_current_year": bool01(
                inventory_record_is_current(tmax, current_year)
                and inventory_record_is_current(tmin, current_year)
            ),
            "either_current_year": bool01(
                inventory_record_is_current(tmax, current_year)
                or inventory_record_is_current(tmin, current_year)
            ),
            "tmax_tmin_overlap_span_years": overlap,
        })

    if not rows:
        raise RuntimeError("Keine GHCN-TMAX/TMIN-Stationen gefunden; Parsing oder Quelldatei prüfen.")

    station_fields = list(rows[0].keys())
    station_csv_gz = output_dir / "world_temperature_stations.csv.gz"
    with gzip.open(station_csv_gz, "wt", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=station_fields)
        writer.writeheader()
        writer.writerows(rows)

    by_country: Dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by_country[(row["country_code"], row["country_name"])].append(row)

    country_rows = []
    for (code, name), cr in sorted(by_country.items(), key=lambda item: item[0][1].casefold()):
        def count(predicate):
            return sum(1 for r in cr if predicate(r))

        country_rows.append({
            "country_code": code,
            "country_name": name,
            "temperature_stations": len(cr),
            "tmax_stations": count(lambda r: r["has_tmax"] == 1),
            "tmin_stations": count(lambda r: r["has_tmin"] == 1),
            "both_stations": count(lambda r: r["has_both"] == 1),
            f"tmax_lastyear_{current_year}": count(lambda r: r["tmax_current_year"] == 1),
            f"tmin_lastyear_{current_year}": count(lambda r: r["tmin_current_year"] == 1),
            f"both_lastyear_{current_year}": count(lambda r: r["both_current_year"] == 1),
            f"either_lastyear_{current_year}": count(lambda r: r["either_current_year"] == 1),
            "tmax_span_ge_30": count(lambda r: (r["tmax_span_years"] or 0) >= 30),
            "tmax_span_ge_50": count(lambda r: (r["tmax_span_years"] or 0) >= 50),
            "tmax_span_ge_100": count(lambda r: (r["tmax_span_years"] or 0) >= 100),
            "tmin_span_ge_30": count(lambda r: (r["tmin_span_years"] or 0) >= 30),
            "tmin_span_ge_50": count(lambda r: (r["tmin_span_years"] or 0) >= 50),
            "tmin_span_ge_100": count(lambda r: (r["tmin_span_years"] or 0) >= 100),
            "both_overlap_span_ge_30": count(lambda r: (r["tmax_tmin_overlap_span_years"] or 0) >= 30),
            "both_overlap_span_ge_50": count(lambda r: (r["tmax_tmin_overlap_span_years"] or 0) >= 50),
            "both_overlap_span_ge_100": count(lambda r: (r["tmax_tmin_overlap_span_years"] or 0) >= 100),
        })

    country_csv = output_dir / "countries_summary.csv"
    with country_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(country_rows[0].keys()))
        writer.writeheader()
        writer.writerows(country_rows)

    with metadata["version"].open("r", encoding="utf-8", errors="replace") as f:
        version_text = f.read().strip()

    def n(predicate):
        return sum(1 for r in rows if predicate(r))

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_year_for_probe": current_year,
        "source": "NOAA NCEI GHCN-Daily",
        "base_url": BASE_URL,
        "ghcnd_version_text": version_text,
        "important_note": (
            "FIRSTYEAR/LASTYEAR are first/last years of unflagged data in ghcnd-inventory. "
            "span_years and overlap spans are calendar spans, not counts of complete observation years."
        ),
        "counts": {
            "all_station_metadata_rows": len(stations),
            "temperature_inventory_lines": inventory_temp_lines,
            "temperature_stations": len(rows),
            "with_tmax": n(lambda r: r["has_tmax"] == 1),
            "with_tmin": n(lambda r: r["has_tmin"] == 1),
            "with_both": n(lambda r: r["has_both"] == 1),
            f"tmax_lastyear_{current_year}": n(lambda r: r["tmax_current_year"] == 1),
            f"tmin_lastyear_{current_year}": n(lambda r: r["tmin_current_year"] == 1),
            f"both_lastyear_{current_year}": n(lambda r: r["both_current_year"] == 1),
            f"either_lastyear_{current_year}": n(lambda r: r["either_current_year"] == 1),
            "tmax_span_ge_30": n(lambda r: (r["tmax_span_years"] or 0) >= 30),
            "tmax_span_ge_50": n(lambda r: (r["tmax_span_years"] or 0) >= 50),
            "tmax_span_ge_100": n(lambda r: (r["tmax_span_years"] or 0) >= 100),
            "tmin_span_ge_30": n(lambda r: (r["tmin_span_years"] or 0) >= 30),
            "tmin_span_ge_50": n(lambda r: (r["tmin_span_years"] or 0) >= 50),
            "tmin_span_ge_100": n(lambda r: (r["tmin_span_years"] or 0) >= 100),
            "both_overlap_span_ge_30": n(lambda r: (r["tmax_tmin_overlap_span_years"] or 0) >= 30),
            "both_overlap_span_ge_50": n(lambda r: (r["tmax_tmin_overlap_span_years"] or 0) >= 50),
            "both_overlap_span_ge_100": n(lambda r: (r["tmax_tmin_overlap_span_years"] or 0) >= 100),
            "countries_with_tmax": sum(1 for r in country_rows if r["tmax_stations"] > 0),
            "countries_with_tmin": sum(1 for r in country_rows if r["tmin_stations"] > 0),
            "countries_with_both": sum(1 for r in country_rows if r["both_stations"] > 0),
            f"countries_with_either_lastyear_{current_year}": sum(
                1 for r in country_rows if r[f"either_lastyear_{current_year}"] > 0
            ),
            "missing_station_metadata": missing_station_metadata,
        },
        "source_files": {
            key: {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for key, path in metadata.items()
        },
    }

    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    verification = {
        "schema_version": 1,
        "purpose": (
            "Country-level verification/QC seed for later comparison of GHCN station extremes "
            "with Maxcrc/Wikipedia, WMO and national meteorological services."
        ),
        "rules_note": (
            "This file is only a template. Empty values are not records and must never be used "
            "to reject GHCN observations until a source has been entered and reviewed."
        ),
        "countries": [
            {
                "country_code": row["country_code"],
                "country_name": row["country_name"],
                "verified_extremes": {
                    "tmax_highest": None,
                    "tmax_lowest": None,
                    "tmin_lowest": None,
                    "tmin_highest": None,
                },
                "sources": [],
                "notes": "",
            }
            for row in country_rows
        ],
    }
    (output_dir / "verification_template.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    counts = summary["counts"]
    report_lines = [
        "# GHCN-Daily · Weltweites Temperatur-Stationsinventar",
        "",
        f"Datenstand des Probe-Laufs: **{summary['generated_at_utc']}**  ",
        f"Prüfjahr: **{current_year}**",
        "",
        "## Gesamt",
        "",
        f"- Temperaturstationen (TMAX oder TMIN): **{counts['temperature_stations']:,}**",
        f"- mit TMAX: **{counts['with_tmax']:,}**",
        f"- mit TMIN: **{counts['with_tmin']:,}**",
        f"- mit TMAX + TMIN: **{counts['with_both']:,}**",
        f"- TMAX LASTYEAR = {current_year}: **{counts[f'tmax_lastyear_{current_year}']:,}**",
        f"- TMIN LASTYEAR = {current_year}: **{counts[f'tmin_lastyear_{current_year}']:,}**",
        f"- beide Elemente LASTYEAR = {current_year}: **{counts[f'both_lastyear_{current_year}']:,}**",
        f"- mindestens eines LASTYEAR = {current_year}: **{counts[f'either_lastyear_{current_year}']:,}**",
        "",
        "## Längen der Zeitspanne",
        "",
        f"- TMAX ≥30 Jahre: **{counts['tmax_span_ge_30']:,}**",
        f"- TMAX ≥50 Jahre: **{counts['tmax_span_ge_50']:,}**",
        f"- TMAX ≥100 Jahre: **{counts['tmax_span_ge_100']:,}**",
        f"- TMIN ≥30 Jahre: **{counts['tmin_span_ge_30']:,}**",
        f"- TMIN ≥50 Jahre: **{counts['tmin_span_ge_50']:,}**",
        f"- TMIN ≥100 Jahre: **{counts['tmin_span_ge_100']:,}**",
        f"- gemeinsame TMAX/TMIN-Spanne ≥30 Jahre: **{counts['both_overlap_span_ge_30']:,}**",
        f"- gemeinsame TMAX/TMIN-Spanne ≥50 Jahre: **{counts['both_overlap_span_ge_50']:,}**",
        f"- gemeinsame TMAX/TMIN-Spanne ≥100 Jahre: **{counts['both_overlap_span_ge_100']:,}**",
        "",
        "## Länder/Territorien",
        "",
        f"- mit TMAX: **{counts['countries_with_tmax']}**",
        f"- mit TMIN: **{counts['countries_with_tmin']}**",
        f"- mit beiden: **{counts['countries_with_both']}**",
        f"- mit mindestens einer Temperaturreihe, LASTYEAR = {current_year}: **{counts[f'countries_with_either_lastyear_{current_year}']}**",
        "",
        "> **Wichtig:** `span_years` ist nur die Zeitspanne zwischen erstem und letztem unflagged Jahr im NOAA-Inventar. "
        "Es ist noch **keine** Zählung vollständiger Messjahre. Das machen wir erst beim historischen Tagesdatenlauf.",
        "",
        "## Dateien im Artifact",
        "",
        "- `world_temperature_stations.csv.gz` – eine Zeile pro Temperaturstation",
        "- `countries_summary.csv` – Länder-/Territorienübersicht",
        "- `summary.json` – maschinenlesbare Gesamtstatistik",
        "- `verification_template.json` – leere Vorlage für Maxcrc/WMO/nationale Rekordprüfung",
    ]
    (output_dir / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 68)
    print("GHCN WORLD TEMPERATURE STATION INVENTORY")
    print("=" * 68)
    print(f"Temperaturstationen (TMAX oder TMIN): {counts['temperature_stations']:,}")
    print(f"mit TMAX:                            {counts['with_tmax']:,}")
    print(f"mit TMIN:                            {counts['with_tmin']:,}")
    print(f"mit TMAX + TMIN:                     {counts['with_both']:,}")
    print(f"mind. ein Element LASTYEAR={current_year}:       {counts[f'either_lastyear_{current_year}']:,}")
    print(f"Länder/Territorien mit Temperatur:   {len(country_rows):,}")
    print(f"Ausgabe:                              {output_dir}")
    print("=" * 68)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe worldwide GHCN-Daily TMAX/TMIN station inventory")
    parser.add_argument("--output", default="world_ghcn_inventory", help="Output directory")
    parser.add_argument("--cache", default=".cache/world-ghcn-inventory", help="Metadata cache directory")
    parser.add_argument("--current-year", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--refresh", action="store_true", help="Redownload NOAA metadata even when cached")
    parser.add_argument("--self-test", action="store_true", help="Run parser self-test and exit")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    self_test()
    metadata = ensure_metadata(Path(args.cache), refresh=args.refresh)
    build_inventory(metadata, Path(args.output), args.current_year)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
