#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_PATH = Path("data/dwd_annual_extremes.json")

METRIC_ORDER = [
    "tnn",
    "txx",
    "summer_days_max",
    "hot_days_max",
    "tropical_nights_max",
    "rr24x",
    "snox_ge_400",
    "snox_lt_400",
]

EXCEL_BW = {
    2003: {
        "tnn": -22.5,
        "txx": 40.2,
        "summer_days_max": 112,
        "hot_days_max": 60,
        "tropical_nights_max": 31,
        "rr24x": 97.0,
        "snox_ge_400": 170.0,
        "snox_lt_400": 65.0,
    },
    2015: {
        "tnn": -20.4,
        "txx": 40.2,
        "summer_days_max": 71,
        "hot_days_max": 37,
        "tropical_nights_max": 15,
        "rr24x": 147.3,
        "snox_ge_400": 95.0,
        "snox_lt_400": 23.0,
    },
    2024: {
        "tnn": -19.5,
        "txx": 35.4,
        "summer_days_max": 54,
        "hot_days_max": 13,
        "tropical_nights_max": 5,
        "rr24x": 129.7,
        "snox_ge_400": 93.0,
        "snox_lt_400": 7.0,
    },
}


def station_for_entry(data: dict[str, Any], metric: str, entry: list[Any] | None):
    if not entry:
        return None, None

    # Extremwerte: [value, date, metadata_key, preliminary]
    # Kenntage:    [count, metadata_key, preliminary]
    metadata_key = (
        entry[2]
        if data["metrics"][metric]["kind"] == "extreme"
        else entry[1]
    )
    station = data.get("stations", {}).get(str(metadata_key))
    return str(metadata_key), station


def fmt_entry(data: dict[str, Any], metric: str, entry: list[Any] | None) -> str:
    if not entry:
        return "KEIN WERT"

    metadata_key, station = station_for_entry(data, metric, entry)
    kind = data["metrics"][metric]["kind"]

    if kind == "extreme":
        value, day, _, preliminary = entry
        date_text = str(day)
    else:
        value, _, preliminary = entry
        date_text = "–"

    if station:
        sid = str(station.get("id") or "").zfill(5)
        name = station.get("name") or "?"
        height = station.get("height")
        state = station.get("state") or "?"
    else:
        sid = str(metadata_key).split(":", 1)[0] if metadata_key else "?"
        name = "Metadaten nicht gefunden"
        height = None
        state = "?"

    return (
        f"Wert={value} | Datum={date_text} | "
        f"Station={name} ({sid}) | Höhe={height} m | "
        f"Bundesland={state} | vorläufig={bool(preliminary)} | "
        f"metadata={metadata_key}"
    )


def earliest_non_null_year(years: dict[str, Any]) -> int | None:
    available: list[int] = []
    for year_text, row in years.items():
        if not isinstance(row, dict):
            continue
        if any(value is not None for value in row.values()):
            try:
                available.append(int(year_text))
            except ValueError:
                pass
    return min(available) if available else None


def main() -> int:
    if not DATA_PATH.is_file():
        raise SystemExit(f"Fehlt: {DATA_PATH}")

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    print("=== DIAGNOSE · JÄHRLICHE EXTREMWERTE ===")
    print(
        "Datenzeitraum:",
        data.get("data_start"),
        "bis",
        data.get("data_through"),
    )
    print()

    print("=== BADEN-WÜRTTEMBERG · DWD vs. EXCEL ===")
    bw = data["records"]["Baden-Württemberg"]

    for year in (2003, 2015, 2024):
        print()
        print(f"--- {year} ---")
        row = bw[str(year)]
        for metric in METRIC_ORDER:
            entry = row.get(metric)
            dwd_value = entry[0] if entry else None
            excel_value = EXCEL_BW[year][metric]
            diff = (
                None
                if dwd_value is None
                else float(dwd_value) - float(excel_value)
            )
            diff_text = "–" if diff is None else f"{diff:+.1f}"
            print(
                f"{metric:22s} "
                f"DWD={str(dwd_value):>7s} | "
                f"Excel={str(excel_value):>7s} | "
                f"Diff={diff_text}"
            )
            print("  " + fmt_entry(data, metric, entry))

    print()
    print("=== KANDIDATEN FÜR REGIONALE STARTJAHRE ===")
    print(
        "Regel: erstes Jahr mit mindestens einem tatsächlich vorhandenen "
        "Jahreswert, anschließend frühestens 1881."
    )

    starts: dict[str, int | None] = {}
    for area in data["areas"]:
        first = earliest_non_null_year(data["records"][area])
        start = max(1881, first) if first is not None else None
        starts[area] = start
        print(
            f"{area:28s} "
            f"erster vorhandener Wert={first} | "
            f"Listenstart={start}"
        )

    print()
    print("=== STARTJAHR-MAPPING ===")
    print(
        json.dumps(
            starts,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
