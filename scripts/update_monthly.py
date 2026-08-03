from __future__ import annotations

import csv
import io
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


def parse_float(value: str) -> Optional[float]:
    value = value.strip().replace(",", ".")
    if not value:
        return None
    number = float(value)
    if number <= -999:
        return None
    return number


def parse_dwd_month_file(content: bytes) -> Dict[str, float]:
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
        germany_index = header.index("Deutschland")
    except ValueError as exc:
        raise ValueError("Spalte Deutschland fehlt in einer DWD-Monatsdatei.") from exc

    result: Dict[str, float] = {}
    for row in rows[header_index + 1 :]:
        if len(row) <= germany_index:
            continue
        year = row[year_index].strip()
        month = row[month_index].strip().zfill(2)
        if not (year.isdigit() and len(year) == 4 and month.isdigit()):
            continue
        value = parse_float(row[germany_index])
        if value is not None:
            result[f"{year}-{month}"] = value
    return result


def update_monthly(root: Path) -> dict:
    target = root / "data.json"
    existing = read_json(target)
    if not isinstance(existing, list) or not existing:
        raise ValueError("data.json ist leer oder kein JSON-Array.")

    old_non_null = {
        parameter: sum(item.get(parameter) is not None for item in existing)
        for parameter in PARAMETERS
    }

    source_data: dict[str, dict[str, float]] = {key: {} for key in PARAMETERS}

    for parameter, (directory, abbreviation) in PARAMETERS.items():
        print(f"Monatsdaten: {parameter}")
        for month in range(1, 13):
            url = (
                f"{BASE_URL}/{directory}/"
                f"regional_averages_{abbreviation}_{month:02d}.txt"
            )
            parsed = parse_dwd_month_file(download(url))
            source_data[parameter].update(parsed)
            print(f"  Monat {month:02d}: {len(parsed)} Jahreswerte")

    current_year = date.today().year
    first_year = min(int(item["date"][:4]) for item in existing)

    updated = []
    for year in range(first_year, current_year + 1):
        for month in range(1, 13):
            key = f"{year:04d}-{month:02d}"
            updated.append(
                {
                    "date": key,
                    "rain": source_data["rain"].get(key),
                    "temp": source_data["temp"].get(key),
                    "sun": source_data["sun"].get(key),
                }
            )

    if len(updated) < len(existing):
        raise RuntimeError(
            f"Neue data.json wäre kürzer ({len(updated)}) als die vorhandene ({len(existing)})."
        )

    new_non_null = {
        parameter: sum(item[parameter] is not None for item in updated)
        for parameter in PARAMETERS
    }
    for parameter in PARAMETERS:
        # DWD revisions are allowed, but a sudden loss of many values is not.
        minimum = max(1, int(old_non_null[parameter] * 0.98))
        if new_non_null[parameter] < minimum:
            raise RuntimeError(
                f"Zu viele fehlende {parameter}-Werte: "
                f"alt={old_non_null[parameter]}, neu={new_non_null[parameter]}."
            )

    atomic_write_json(target, updated)

    latest_by_parameter = {}
    for parameter in PARAMETERS:
        dates = [item["date"] for item in updated if item[parameter] is not None]
        latest_by_parameter[parameter] = max(dates) if dates else None

    complete_dates = [
        item["date"]
        for item in updated
        if all(item[parameter] is not None for parameter in PARAMETERS)
    ]

    return {
        "records": len(updated),
        "latest_complete_month": max(complete_dates) if complete_dates else None,
        "latest_by_parameter": latest_by_parameter,
        "non_null": new_non_null,
    }
