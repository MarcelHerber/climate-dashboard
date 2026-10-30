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


def audit(root: Path, release_assets: dict[str, int] | None = None) -> dict:
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
    # Verify that the 1-km precipitation map archive actually has every month.
    missing_precip = [
        f"{year}-{month:02d}"
        for year in years
        for month in range(1, 13)
        if not (root / "historical_1km" / str(year) / f"month_{month:02d}.png").is_file()
    ]
    if missing_precip:
        errors.append(
            "Niederschlag: historische Monatsraster fehlen "
            + ", ".join(missing_precip[:12])
            + (f" … insgesamt {len(missing_precip)}" if len(missing_precip) > 12 else "")
        )
    summary["precipitation_monthly_maps"] = len(years) * 12 - len(missing_precip)
    # Read the 24-byte PNG header instead of decompressing 1,140 large rasters.
    checked_png = 0
    for year in years:
        for month in range(1, 13):
            path = root / "historical_1km" / str(year) / f"month_{month:02d}.png"
            if not path.is_file():
                continue
            with path.open("rb") as image:
                header = image.read(24)
            if (
                len(header) != 24
                or header[:8] != bytes.fromhex("89504e470d0a1a0a")
                or header[12:16] != b"IHDR"
                or int.from_bytes(header[16:20], "big") != 665
                or int.from_bytes(header[20:24], "big") != 890
            ):
                errors.append(f"Niederschlag {year}-{month:02d}: defekter PNG-Header oder falsche 1-km-Größe")
            else:
                checked_png += 1
    summary["precipitation_png_headers_checked"] = checked_png

    for reference, monthly in (historic.get("reference_files_by_period") or {}).items():
        for month, rel in monthly.items():
            if not (root / rel).is_file():
                errors.append(f"Niederschlag: Klimamittel {reference}/{month} fehlt: {rel}")

    series = read("click_series_5km/manifest.json")
    if series.get("years") != years or series.get("factor") != 5:
        errors.append("Niederschlags-Zeitreihe: Jahresabdeckung oder Rasterfaktor weicht ab")
    expected_pack = len(years) * int(series.get("width", 0)) * int(series.get("height", 0)) * 2
    for month in range(1, 13):
        path = root / "click_series_5km" / f"month_{month:02d}.u16.gz"
        if not path.is_file():
            errors.append(f"Niederschlags-Zeitreihe: Monatsdatei {month:02d} fehlt")
            continue
        with path.open("rb") as stream:
            stream.seek(-4, 2)
            unpacked = int.from_bytes(stream.read(4), "little")
        if unpacked != expected_pack:
            errors.append(f"Niederschlags-Zeitreihe: falsche entpackte Größe bei Monat {month:02d}")
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
                if release_assets is not None and release_assets.get(meta["archive_file"]) != meta["archive_bytes"]:
                    errors.append(f"{prefix}: Release-Asset fehlt oder Dateigröße stimmt nicht")
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
    # Full historical temperature map index is separate from the daily archive.
    sprite_path = root / "historical_temperature_maps_1km" / "index.json"
    if sprite_path.is_file():
        try:
            sprite_index = json.loads(sprite_path.read_text(encoding="utf-8"))
            for parameter in PARAMETERS:
                yrs = (sprite_index.get("parameters") or {}).get(parameter, {})
                expected = {str(y) for y in range(1951, 2026)}
                if not expected.issubset(yrs):
                    errors.append(f"{parameter}: historische Temperatur-Kartenjahre fehlen")
        except (OSError, ValueError) as exc:
            errors.append(f"Temperatur-Kartensprites: Index beschädigt ({exc})")
    else:
        errors.append("Temperatur-Kartensprites: historischer 1-km-Index fehlt")

    if len(signatures) > 1:
        errors.append("Temperatur-Archiv: unterschiedliche Rasterkennungen")
    if archive.get("archive_entries") != sum(archive_years.values()):
        errors.append("Temperatur-Archiv: archive_entries stimmt nicht mit den Jahreslisten überein")
    summary["temperature_archive_years"] = archive_years
    summary["temperature_archive_entries"] = sum(archive_years.values())
    summary["release_assets_checked"] = len(release_assets) if release_assets is not None else None
    summary["temperature_grid_signatures"] = sorted(signatures)
    summary["temperature_data_through"] = {key: str(val) for key, val in live_by_parameter.items()}
    return {"ok": not errors, "errors": errors, "warnings": warnings, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--assets-tsv", type=Path)
    args = parser.parse_args()
    assets = None
    if args.assets_tsv is not None:
        assets = {}
        for line in args.assets_tsv.read_text(encoding="utf-8").splitlines():
            name, size = line.split("\t")
            assets[name] = int(size)
    result = audit(args.data_root, assets)
    report = json.dumps(result, ensure_ascii=False, indent=2)
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
