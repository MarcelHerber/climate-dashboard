#!/usr/bin/env python3
"""Metadata and on-disk integrity audit of HYRAS-DE data (no full raster download)."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re

PARAMETERS = ("tmean", "tmax", "tmin")
REFERENCES = {"1991-2020", "1961-1990"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def expected_days(first: str, last: str) -> int:
    return (date.fromisoformat(last) - date.fromisoformat(first)).days + 1


def audit(root: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    summary: dict = {}

    def read(relative: str) -> dict:
        path = root / relative
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{relative}: {exc}")
            return {}

    precip = read("hyras_index.json")
    historic = read("hyras_historical_manifest.json")
    archive = read("daily_archive_1km/index.json")

    try:
        live_day = date.fromisoformat(precip["data_through"])
    except (KeyError, ValueError):
        errors.append("Niederschlag: data_through fehlt oder ist ungültig")
        live_day = None

    years = historic.get("years", [])
    expected_precip = list(range(1931, 2026))
    if years != expected_precip:
        errors.append(f"Niederschlagshistorie: Jahreslücken oder falsche Sortierung ({len(years)} Jahre)")
    if historic.get("first_year") != 1931 or historic.get("last_year") != 2025:
        errors.append("Niederschlagshistorie: unerwartete Jahresgrenzen")
    if historic.get("native_resolution_km") != 1:
        errors.append("Niederschlagshistorie: kein natives 1-km-Raster")
    for reference in REFERENCES:
        if reference not in (historic.get("references") or []):
            errors.append(f"Niederschlagshistorie: Referenz {reference} fehlt")
        months = (historic.get("reference_files_by_period") or {}).get(reference, {})
        if set(months) != {str(m) for m in range(1, 13)}:
            errors.append(f"Niederschlagshistorie: Monatsreferenzen {reference} unvollständig")
    summary["precipitation_years"] = len(years)
    summary["precipitation_data_through"] = str(live_day) if live_day else None

    live_by_parameter = {}
    signatures = set()
    archive_years = {}
    for parameter in PARAMETERS:
        index_path = f"{parameter}/index.json" if parameter == "tmean" else f"{parameter}/regions/index.json"
        live = read(index_path)
        try:
            end = date.fromisoformat(live["data_through"])
            live_by_parameter[parameter] = end
            if live_day and end != live_day:
                warnings.append(f"{parameter}: Datenstand {end} weicht vom Niederschlag {live_day} ab")
        except (KeyError, ValueError):
            errors.append(f"{parameter}: ungültiger Live-Datenstand")
            continue

        if set(live.get("references", [])) != REFERENCES:
            errors.append(f"{parameter}: Referenzperioden unvollständig")

        for period in live.get("periods", []):
            try:
                first = period["start_date"]
                last = period["end_date"]
                if expected_days(first, last) <= 0 or date.fromisoformat(last) > end:
                    errors.append(f"{parameter}: ungültiger Zeitraum {period.get('key', '?')}")
            except (KeyError, ValueError):
                errors.append(f"{parameter}: ungültige Periodendaten")

        entries = (archive.get("parameters") or {}).get(parameter) or {}
        expected = [str(y) for y in range(1951, end.year + 1)]
        archive_years[parameter] = len(entries)
        if sorted(entries) != expected:
            errors.append(f"{parameter}: Archiv-Jahreslücke (erwartet {len(expected)}, vorhanden {len(entries)})")
        for year, meta in entries.items():
            prefix = f"{parameter} {year}"
            try:
                if int(year) != meta["year"] or meta["parameter"] != parameter:
                    errors.append(f"{prefix}: Parameter oder Jahresnummer falsch")
                first = meta["first_date"]
                last = meta["data_through"]
                days = expected_days(first, last)
                if first != f"{year}-01-01" or days != meta["days"]:
                    errors.append(f"{prefix}: Tagesanzahl oder Beginn inkonsistent")
                if int(year) < end.year and (not meta["complete_year"] or last != f"{year}-12-31"):
                    errors.append(f"{prefix}: historisches Jahr nicht vollständig")
                if int(year) == end.year and last < (end.isoformat()):
                    warnings.append(f"{prefix}: Tagesarchiv bis {last}, Live-Daten bis {end}")
                if (meta["resolution_km"] != 1 or meta["width"] != 665
                        or meta["height"] != 890 or meta["archive_bytes"] <= 0):
                    errors.append(f"{prefix}: Rasterformat oder Dateigröße ungültig")
                signatures.add(meta["grid_signature"])
                if not SHA256.fullmatch(meta["archive_sha256"]):
                    errors.append(f"{prefix}: SHA-256-Metadatum ungültig")
                if not meta["release_asset_url"].endswith("/" + meta["archive_file"]):
                    errors.append(f"{prefix}: Release-Asset-Verknüpfung ungültig")
            except (KeyError, ValueError, TypeError) as exc:
                errors.append(f"{prefix}: unvollständige Metadaten ({exc})")

        anomaly_path = f"{parameter}/regions/daily_anomaly_maps.json"
        anomaly = read(anomaly_path)
        days = anomaly.get("available_dates") or []
        if days:
            if days != sorted(set(days)):
                errors.append(f"{parameter}: doppelte oder unsortierte Anomalietage")
            if date.fromisoformat(days[-1]) > end:
                errors.append(f"{parameter}: Anomaliekarte liegt nach Live-Datenstand")
            if set(anomaly.get("references", [])) != REFERENCES:
                errors.append(f"{parameter}: tägliche Anomalie-Referenzen fehlen")
            if anomaly.get("data_through", "") < min(end, date(end.year, 8, 31)).isoformat() and end.month >= 6:
                warnings.append(f"{parameter}: Sommer-Anomaliekarten bei {days[-1]} stehen geblieben")
        else:
            warnings.append(f"{parameter}: keine Tagesanomaliekarten im Index")
    if len(signatures) > 1:
        errors.append("Temperatur-Archiv: unterschiedliche Rasterkennungen")
    if archive.get("archive_entries") != sum(archive_years.values()):
        errors.append("Temperatur-Archiv: archive_entries stimmt nicht mit den Jahreslisten überein")
    summary["temperature_archive_years"] = archive_years
    summary["temperature_archive_entries"] = sum(archive_years.values())
    summary["temperature_grid_signatures"] = sorted(signatures)
    summary["temperature_data_through"] = {key: str(val) for key, val in live_by_parameter.items()}
    return {"ok": not errors, "errors": errors, "warnings": warnings, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = audit(args.data_root)
    report = json.dumps(result, ensure_ascii=False, indent=2)
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
