#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

MAIN_PATH = Path("data/dwd_annual_extremes.json")
WIND_PATH = Path("data/dwd_annual_wind_extremes.json")

WIND_METRICS = ("fgx_ge_400", "fgx_lt_400")


def main() -> int:
    if not MAIN_PATH.is_file():
        raise SystemExit(f"Fehlt: {MAIN_PATH}")
    if not WIND_PATH.is_file():
        raise SystemExit(f"Fehlt: {WIND_PATH}")

    main_data = json.loads(MAIN_PATH.read_text(encoding="utf-8"))
    wind_data = json.loads(WIND_PATH.read_text(encoding="utf-8"))

    assert len(main_data["areas"]) == 17
    assert len(wind_data["areas"]) == 17
    assert main_data["areas"] == wind_data["areas"]
    assert main_data["area_start_years"] == wind_data["area_start_years"]
    assert set(wind_data["metrics"]) == set(WIND_METRICS)
    assert "desert_days_max" in main_data["metrics"]

    for metric in WIND_METRICS:
        main_data["metrics"][metric] = wind_data["metrics"][metric]

    for area in main_data["areas"]:
        main_years = main_data["records"][area]
        wind_years = wind_data["records"][area]

        for year, row in main_years.items():
            wind_row = wind_years.get(year, {})
            row["fgx_ge_400"] = wind_row.get("fgx_ge_400")
            row["fgx_lt_400"] = wind_row.get("fgx_lt_400")

    stations = dict(main_data.get("stations", {}))
    for key, value in wind_data.get("stations", {}).items():
        stations.setdefault(key, value)
    main_data["stations"] = stations

    main_data["version"] = max(int(main_data.get("version", 1)), 2)

    data_sources = dict(main_data.get("data_sources", {}))
    data_sources["wind"] = wind_data.get(
        "source",
        "DWD CDC observations_germany/climate/daily/kl · FX",
    )
    main_data["data_sources"] = data_sources

    entry_schema = dict(main_data.get("entry_schema", {}))
    entry_schema["wind_extreme"] = [
        "value_kmh",
        "date",
        "metadata_key",
        "preliminary",
        "raw_value_ms",
    ]
    main_data["entry_schema"] = entry_schema

    stats = dict(main_data.get("stats", {}))
    stats["wind_observations_ge_75_kmh"] = wind_data["stats"][
        "valid_gust_observations_ge_75_kmh"
    ]
    main_data["stats"] = stats

    main_data["wind_data_start"] = wind_data.get("data_start")
    main_data["wind_data_through"] = wind_data.get("data_through")

    note = str(main_data.get("method_note") or "")
    wind_note = (
        " FGx verwendet DWD daily/kl, Spalte FX = Tagesmaximum der "
        "Windspitze. FX wird von m/s in km/h umgerechnet. Entsprechend "
        "der Excel-Vorlage werden nur Windspitzen ab 75 km/h (9 Bft.) "
        "berücksichtigt und nach Stationshöhe in >=400 m und <400 m "
        "getrennt."
    )
    if "FGx verwendet DWD daily/kl" not in note:
        main_data["method_note"] = note.rstrip() + wind_note

    assert len(main_data["metrics"]) == 11
    assert "desert_days_max" in main_data["metrics"]
    assert set(WIND_METRICS).issubset(main_data["metrics"])

    for area in main_data["areas"]:
        for row in main_data["records"][area].values():
            assert "desert_days_max" in row
            assert "fgx_ge_400" in row
            assert "fgx_lt_400" in row

    bw = main_data["records"]["Baden-Württemberg"]
    expected_ranges = {
        "2003": {
            "fgx_ge_400": (194.0, 195.0),
            "fgx_lt_400": (113.0, 114.0),
        },
        "2015": {
            "fgx_ge_400": (157.0, 158.0),
            "fgx_lt_400": (118.0, 119.0),
        },
        "2024": {
            "fgx_ge_400": (157.0, 159.0),
            "fgx_lt_400": (108.0, 110.0),
        },
    }

    for year, metrics in expected_ranges.items():
        for metric, (lo, hi) in metrics.items():
            entry = bw[year][metric]
            assert entry is not None, f"BW {year} ohne {metric}"
            value = float(entry[0])
            assert lo <= value <= hi, (year, metric, value)

    MAIN_PATH.write_text(
        json.dumps(
            main_data,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )

    print("=== JÄHRLICHE EXTREMWERTE · WIND ZUSAMMENGEFÜHRT ===")
    print("Version:", main_data["version"])
    print("Gebiete:", len(main_data["areas"]))
    print("Parameter:", len(main_data["metrics"]))
    print(
        "Windzeitraum:",
        main_data["wind_data_start"],
        "bis",
        main_data["wind_data_through"],
    )
    print(
        "Windspitzen >=75 km/h:",
        f'{main_data["stats"]["wind_observations_ge_75_kmh"]:,}',
    )

    for year in ("2003", "2015", "2024"):
        print(
            "BW",
            year,
            {
                metric: bw[year][metric][0]
                if bw[year][metric]
                else None
                for metric in WIND_METRICS
            },
        )

    print("Hauptdatei aktualisiert:", MAIN_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
