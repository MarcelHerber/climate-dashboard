from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, Optional

from dwd_common import atomic_write_json, download, read_json

BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/regional_averages_DE/monthly"
PARAMETERS = {
    "temp": ("air_temperature_mean", "tm"),
    "rain": ("precipitation", "rr"),
    "sun": ("sunshine_duration", "sd"),
}

# Die Bezeichnungen links entsprechen exakt den DWD-Spaltennamen.
# Rechts stehen die lesbaren Namen, die im Dashboard angezeigt werden.
DWD_AREAS = {
    "Deutschland": "Deutschland",
    "Baden-Wuerttemberg": "Baden-Württemberg",
    "Bayern": "Bayern",
    "Brandenburg": "Brandenburg",
    "Brandenburg/Berlin": "Brandenburg/Berlin",
    "Hessen": "Hessen",
    "Mecklenburg-Vorpommern": "Mecklenburg-Vorpommern",
    "Niedersachsen": "Niedersachsen",
    "Niedersachsen/Hamburg/Bremen": "Niedersachsen/Hamburg/Bremen",
    "Nordrhein-Westfalen": "Nordrhein-Westfalen",
    "Rheinland-Pfalz": "Rheinland-Pfalz",
    "Saarland": "Saarland",
    "Sachsen": "Sachsen",
    "Sachsen-Anhalt": "Sachsen-Anhalt",
    "Schleswig-Holstein": "Schleswig-Holstein",
    "Thueringen": "Thüringen",
    "Thueringen/Sachsen-Anhalt": "Thüringen/Sachsen-Anhalt",
}

AREA_ORDER = list(DWD_AREAS.values())
AREA_RANK = {area: index for index, area in enumerate(AREA_ORDER)}


def parse_float(value: str) -> Optional[float]:
    value = value.strip().replace(",", ".")
    if not value:
        return None
    number = float(value)
    if number <= -999:
        return None
    return number


def parse_dwd_month_file(content: bytes) -> Dict[str, Dict[str, float]]:
    """Liest eine DWD-Monatsdatei für alle verfügbaren Gebietsspalten."""
    text = content.decode("latin-1")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))

    header_index = next(
        (index for index, row in enumerate(rows) if row and row[0].strip() == "Jahr"),
        None,
    )
    if header_index is None:
        raise ValueError("DWD-Monatsdatei enthält keine Kopfzeile 'Jahr'.")

    header = [column.strip() for column in rows[header_index]]
    try:
        year_index = header.index("Jahr")
        month_index = header.index("Monat")
    except ValueError as exc:
        raise ValueError("Jahr oder Monat fehlt in einer DWD-Monatsdatei.") from exc

    area_indices: dict[str, int] = {}
    for dwd_name, display_name in DWD_AREAS.items():
        if dwd_name in header:
            area_indices[display_name] = header.index(dwd_name)

    if "Deutschland" not in area_indices:
        raise ValueError("Spalte Deutschland fehlt in einer DWD-Monatsdatei.")

    result: Dict[str, Dict[str, float]] = {
        area: {} for area in area_indices
    }

    for row in rows[header_index + 1 :]:
        if len(row) <= max(year_index, month_index):
            continue

        year = row[year_index].strip()
        month = row[month_index].strip().zfill(2)
        if not (year.isdigit() and len(year) == 4 and month.isdigit()):
            continue

        key = f"{year}-{month}"
        for area, column_index in area_indices.items():
            if len(row) <= column_index:
                continue
            value = parse_float(row[column_index])
            if value is not None:
                result[area][key] = value

    return result


def normalize_existing(records: list[dict]) -> list[dict]:
    """Alte Deutschland-only-Dateien bleiben beim ersten Update kompatibel."""
    normalized = []
    for item in records:
        normalized.append(
            {
                "area": item.get("area", "Deutschland"),
                "date": item["date"],
                "rain": item.get("rain"),
                "temp": item.get("temp"),
                "sun": item.get("sun"),
            }
        )
    return normalized


def update_monthly(root: Path) -> dict:
    target = root / "data.json"
    existing_raw = read_json(target)
    if not isinstance(existing_raw, list) or not existing_raw:
        raise ValueError("data.json ist leer oder kein JSON-Array.")

    existing = normalize_existing(existing_raw)

    old_non_null: dict[str, dict[str, int]] = defaultdict(dict)
    existing_areas = sorted({item["area"] for item in existing})
    for area in existing_areas:
        area_records = [item for item in existing if item["area"] == area]
        for parameter in PARAMETERS:
            old_non_null[area][parameter] = sum(
                item.get(parameter) is not None for item in area_records
            )

    # parameter -> Gebiet -> YYYY-MM -> Wert
    source_data: dict[str, dict[str, dict[str, float]]] = {
        parameter: defaultdict(dict) for parameter in PARAMETERS
    }

    for parameter, (directory, abbreviation) in PARAMETERS.items():
        print(f"Monatsdaten: {parameter}")
        for month in range(1, 13):
            url = (
                f"{BASE_URL}/{directory}/"
                f"regional_averages_{abbreviation}_{month:02d}.txt"
            )
            parsed = parse_dwd_month_file(download(url))
            for area, values in parsed.items():
                source_data[parameter][area].update(values)
            print(
                f"  Monat {month:02d}: "
                f"{len(parsed.get('Deutschland', {}))} Jahreswerte, "
                f"{len(parsed)} Gebiete"
            )

    areas = [
        area
        for area in AREA_ORDER
        if all(area in source_data[parameter] for parameter in PARAMETERS)
    ]
    if "Deutschland" not in areas:
        raise RuntimeError("Deutschland fehlt nach dem DWD-Abruf.")
    if len(areas) < 10:
        raise RuntimeError(
            f"Unerwartet wenige DWD-Gebiete gefunden: {len(areas)}."
        )

    current_year = date.today().year
    first_year = min(int(item["date"][:4]) for item in existing)

    updated: list[dict] = []
    for area in areas:
        for year in range(first_year, current_year + 1):
            for month in range(1, 13):
                key = f"{year:04d}-{month:02d}"
                updated.append(
                    {
                        "area": area,
                        "date": key,
                        "rain": source_data["rain"][area].get(key),
                        "temp": source_data["temp"][area].get(key),
                        "sun": source_data["sun"][area].get(key),
                    }
                )

    updated.sort(key=lambda item: (AREA_RANK.get(item["area"], 999), item["date"]))

    # Bestehende Gebiete dürfen nicht plötzlich große Datenverluste haben.
    for area in existing_areas:
        if area not in areas:
            raise RuntimeError(f"Vorhandenes Gebiet fehlt nach dem Update: {area}")
        area_records = [item for item in updated if item["area"] == area]
        for parameter in PARAMETERS:
            new_count = sum(item[parameter] is not None for item in area_records)
            old_count = old_non_null[area][parameter]
            minimum = max(1, int(old_count * 0.98))
            if new_count < minimum:
                raise RuntimeError(
                    f"Zu viele fehlende {parameter}-Werte für {area}: "
                    f"alt={old_count}, neu={new_count}."
                )

    atomic_write_json(target, updated)

    germany = [item for item in updated if item["area"] == "Deutschland"]
    latest_by_parameter = {}
    for parameter in PARAMETERS:
        dates = [item["date"] for item in germany if item[parameter] is not None]
        latest_by_parameter[parameter] = max(dates) if dates else None

    complete_dates = [
        item["date"]
        for item in germany
        if all(item[parameter] is not None for parameter in PARAMETERS)
    ]

    total_non_null = {
        parameter: sum(item[parameter] is not None for item in updated)
        for parameter in PARAMETERS
    }

    return {
        "records": len(updated),
        "areas": areas,
        "area_count": len(areas),
        "latest_complete_month": max(complete_dates) if complete_dates else None,
        "latest_by_parameter": latest_by_parameter,
        "non_null": total_non_null,
    }
