#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "era5_land_europe" / "index.json"

# Muss zu render_history_base_map() in update_era5_land_europe.py passen.
# Cartopy lässt GeoAxes standardmäßig mit gleichem Kartenmaßstab laufen und
# verkleinert deshalb die tatsächlich sichtbare Kartenfläche innerhalb dieses
# angeforderten Rechtecks. Das Browser-Canvas muss die *effektive* Achsenbox
# verwenden, nicht das ursprünglich an Matplotlib übergebene Rechteck.
FIGURE_WIDTH_IN = 13.2
FIGURE_HEIGHT_IN = 8.1
AX_LEFT = 0.07
AX_BOTTOM = 0.18
AX_WIDTH = 0.89
AX_HEIGHT = 0.66


def effective_platecarree_geometry(coverage: dict) -> dict[str, float]:
    west = float(coverage["west"])
    east = float(coverage["east"])
    south = float(coverage["south"])
    north = float(coverage["north"])

    lon_span = east - west
    lat_span = north - south
    if lon_span <= 0 or lat_span <= 0:
        raise ValueError(f"Ungültige ERA5-Abdeckung: {coverage}")

    # PlateCarree: x/y liegen direkt in Grad. Cartopy hält die Achse auf
    # aspect='equal'. Je nach Seitenverhältnis wird daher Breite oder Höhe des
    # angeforderten Matplotlib-Achsenrechtecks zentriert verkleinert.
    map_ratio = lon_span / lat_span
    requested_ratio = (AX_WIDTH * FIGURE_WIDTH_IN) / (AX_HEIGHT * FIGURE_HEIGHT_IN)

    if requested_ratio > map_ratio:
        # Angefordertes Rechteck ist zu breit -> Cartopy verkleinert die Breite.
        effective_width = map_ratio * (AX_HEIGHT * FIGURE_HEIGHT_IN) / FIGURE_WIDTH_IN
        effective_height = AX_HEIGHT
        effective_left = AX_LEFT + (AX_WIDTH - effective_width) / 2.0
        effective_bottom = AX_BOTTOM
    else:
        # Angefordertes Rechteck ist zu hoch -> Cartopy verkleinert die Höhe.
        effective_width = AX_WIDTH
        effective_height = (AX_WIDTH * FIGURE_WIDTH_IN) / map_ratio / FIGURE_HEIGHT_IN
        effective_left = AX_LEFT
        effective_bottom = AX_BOTTOM + (AX_HEIGHT - effective_height) / 2.0

    return {
        "left": round(effective_left, 12),
        "top": round(1.0 - (effective_bottom + effective_height), 12),
        "right": round(effective_left + effective_width, 12),
        "bottom": round(1.0 - effective_bottom, 12),
    }


def main() -> None:
    if not INDEX_PATH.exists():
        raise SystemExit(f"FEHLER: {INDEX_PATH.relative_to(ROOT)} fehlt.")

    payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        raise SystemExit("FEHLER: coverage fehlt in era5_land_europe/index.json.")

    geometry = effective_platecarree_geometry(coverage)
    previous = payload.get("click_geometry")

    print("ERA5-Land Historienkarte · Geometrie")
    print(f"  bisher: {previous}")
    print(f"  korrekt: {geometry}")

    if previous == geometry:
        print("  Keine Änderung nötig.")
        return

    payload["click_geometry"] = geometry
    INDEX_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print("  index.json aktualisiert.")


if __name__ == "__main__":
    main()
