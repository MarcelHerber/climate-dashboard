#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNING_PATH = ROOT / "scripts" / "update_era5_land_europe_running.py"
PALETTE_PATH = ROOT / "scripts" / "update_era5_land_europe_palette.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Modul konnte nicht geladen werden: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    running = load_module(RUNNING_PATH, "era5_running_0p1_core")

    # Laufende Karten in derselben räumlichen Auflösung wie die regulären
    # ERA5-Land-Europakarten. Eigener Cache verhindert die Wiederverwendung
    # alter 0,5°-Dateien.
    running.GRID = [0.1, 0.1]
    running.CACHE_DIR = ROOT / ".era5_running_cache_0p1"

    original_load_core = running.load_core

    def load_core_with_palette():
        core = original_load_core()
        palette = load_module(PALETTE_PATH, "era5_running_0p1_palette")
        # Nur der Kartenrenderer wird ersetzt. Berechnung, Flächenmittel usw.
        # bleiben vollständig im bewährten Running-Core.
        core.render_map = palette.render_map
        return core

    running.load_core = load_core_with_palette
    rc = int(running.main())
    if rc != 0:
        return rc

    # Der bestehende Generator kennt als Metadaten-Text noch 0,5°.
    # Nach erfolgreicher Berechnung wird nur diese Beschreibung korrigiert.
    index_path = ROOT / "era5_land_europe" / "running" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["grid"] = "0,1° (ERA5-Land im CDS; native Modellauflösung ca. 9 km)"
    payload["rendering_note"] = (
        "Laufende Temperaturabweichungen verwenden dieselbe diskrete -8 bis +8 K Skala "
        "wie die vollständigen ERA5-Land-Europakarten."
    )
    index_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print("ERA5 Running: 0,1°-Raster und einheitliche Temperaturanomalieskala aktiv.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
