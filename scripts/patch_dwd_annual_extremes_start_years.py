#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BUILDER = Path("scripts/build_dwd_annual_extremes.py")
DATA = Path("data/dwd_annual_extremes.json")

LIST_MIN_YEAR = 1881


def first_available_year(years: dict[str, Any]) -> int | None:
    found: list[int] = []

    for year_text, row in years.items():
        if not isinstance(row, dict):
            continue
        if not any(value is not None for value in row.values()):
            continue
        try:
            found.append(int(year_text))
        except ValueError:
            continue

    return min(found) if found else None


def derive_area_start_years(records: dict[str, Any]) -> dict[str, int | None]:
    result: dict[str, int | None] = {}

    for area, years in records.items():
        first = first_available_year(years)
        result[area] = (
            max(LIST_MIN_YEAR, first)
            if first is not None
            else None
        )

    return result


def patch_builder() -> None:
    text = BUILDER.read_text(encoding="utf-8")
    original = text

    if "LIST_MIN_YEAR = 1881" not in text:
        needle = 'START_YEAR = 1861\n'
        replacement = (
            'START_YEAR = 1861\n'
            'LIST_MIN_YEAR = 1881\n'
        )
        if needle not in text:
            raise RuntimeError("START_YEAR-Marker im Builder nicht gefunden.")
        text = text.replace(needle, replacement, 1)

    if "def derive_area_start_years(" not in text:
        marker = '\ndef reference_value(\n'
        helper = r'''

def first_available_year(years: dict[str, Any]) -> int | None:
    found: list[int] = []

    for year_text, row in years.items():
        if not isinstance(row, dict):
            continue
        if not any(value is not None for value in row.values()):
            continue
        try:
            found.append(int(year_text))
        except ValueError:
            continue

    return min(found) if found else None


def derive_area_start_years(
    records: dict[str, Any],
) -> dict[str, int | None]:
    result: dict[str, int | None] = {}

    for area in AREAS:
        first = first_available_year(records.get(area, {}))
        result[area] = (
            max(LIST_MIN_YEAR, first)
            if first is not None
            else None
        )

    return result

'''
        if marker not in text:
            raise RuntimeError("Einfügepunkt vor reference_value nicht gefunden.")
        text = text.replace(marker, helper + marker, 1)

    if "area_start_years = derive_area_start_years(records)" not in text:
        needle = (
            '    records = acc.public_records(today.year)\n'
            '    stations = merge_station_metadata(\n'
        )
        replacement = (
            '    records = acc.public_records(today.year)\n'
            '    area_start_years = derive_area_start_years(records)\n'
            '    stations = merge_station_metadata(\n'
        )
        if needle not in text:
            raise RuntimeError("records/stations-Marker im Builder nicht gefunden.")
        text = text.replace(needle, replacement, 1)

    if '"area_start_years": area_start_years' not in text:
        needle = (
            '        "start_year": START_YEAR,\n'
            '        "end_year": today.year,\n'
        )
        replacement = (
            '        "start_year": START_YEAR,\n'
            '        "list_min_year": LIST_MIN_YEAR,\n'
            '        "area_start_years": area_start_years,\n'
            '        "end_year": today.year,\n'
        )
        if needle not in text:
            raise RuntimeError("Payload-Startjahr-Marker nicht gefunden.")
        text = text.replace(needle, replacement, 1)

    old_note = (
        '"Kalenderjahre ab 1861. TNn und TXx stammen aus TNK/TXK. "'
    )
    new_note = (
        '"Rohdaten werden ab 1861 ausgewertet. Für spätere Jahreslisten "'
        '"beginnt jedes Gebiet frühestens 1881; liegt der erste tatsächlich "'
        '"vorhandene Jahreswert später, wird dieses spätere Jahr verwendet. "'
        '"TNn und TXx stammen aus TNK/TXK. "'
    )
    if old_note in text and "Rohdaten werden ab 1861 ausgewertet." not in text:
        text = text.replace(old_note, new_note, 1)

    if text != original:
        BUILDER.write_text(text, encoding="utf-8")
        print("Builder dauerhaft um regionale Listen-Startjahre ergänzt.")
    else:
        print("Builder war bereits gepatcht.")


def patch_current_json() -> dict[str, int | None]:
    data = json.loads(DATA.read_text(encoding="utf-8"))

    records = data["records"]
    starts = derive_area_start_years(records)

    data["list_min_year"] = LIST_MIN_YEAR
    data["area_start_years"] = starts

    note = str(data.get("method_note") or "")
    prefix = (
        "Rohdaten werden ab 1861 ausgewertet. Für spätere Jahreslisten "
        "beginnt jedes Gebiet frühestens 1881; liegt der erste tatsächlich "
        "vorhandene Jahreswert später, wird dieses spätere Jahr verwendet. "
    )
    if not note.startswith("Rohdaten werden ab 1861 ausgewertet."):
        if note.startswith("Kalenderjahre ab 1861. "):
            note = note[len("Kalenderjahre ab 1861. "):]
        data["method_note"] = prefix + note

    DATA.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )

    return starts


def main() -> int:
    if not BUILDER.is_file():
        raise SystemExit(f"Fehlt: {BUILDER}")
    if not DATA.is_file():
        raise SystemExit(f"Fehlt: {DATA}")

    patch_builder()
    starts = patch_current_json()

    expected = {
        "Deutschland": 1881,
        "Baden-Württemberg": 1881,
        "Bayern": 1881,
        "Berlin": 1881,
        "Brandenburg": 1887,
        "Bremen": 1890,
        "Hamburg": 1891,
        "Hessen": 1881,
        "Mecklenburg-Vorpommern": 1881,
        "Niedersachsen": 1881,
        "Nordrhein-Westfalen": 1881,
        "Rheinland-Pfalz": 1881,
        "Saarland": 1931,
        "Sachsen": 1881,
        "Sachsen-Anhalt": 1881,
        "Schleswig-Holstein": 1881,
        "Thüringen": 1881,
    }

    if starts != expected:
        raise RuntimeError(
            "Startjahre weichen von der geprüften Diagnose ab:\n"
            + json.dumps(starts, ensure_ascii=False, indent=2)
        )

    print()
    print("=== REGIONALE LISTEN-STARTJAHRE ===")
    for area, year in starts.items():
        print(f"{area:28s} {year}")

    print()
    print("Rohdaten ab 1861 bleiben vollständig erhalten.")
    print("Es wurde KEIN neuer DWD-Download gestartet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
