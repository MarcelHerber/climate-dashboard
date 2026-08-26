#!/usr/bin/env python3
from __future__ import annotations

"""Aktuelle ERA5-Land-T/P-Monatskarten mit einheitlicher Temperaturanomalieskala.

Der bestehende Monats-Builder bleibt unverändert. Nur der von ihm geladene
ERA5-Kern erhält für Temperaturabweichungen den abgestimmten diskreten
Europa-Renderer (-8 bis +8 K).
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "scripts" / "add_era5_current_tp_months.py"
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
    helper = load_module(HELPER_PATH, "era5_current_tp_palette_helper")
    original_load_core = helper.load_core

    def load_core_with_palette():
        core = original_load_core()
        palette = load_module(PALETTE_PATH, "era5_current_tp_palette")
        # Nur der Renderer wird ersetzt. Datenabruf, Berechnung und Statistiken
        # bleiben vollständig im bestehenden Monats-Builder.
        core.render_map = palette.render_map
        return core

    helper.load_core = load_core_with_palette
    return int(helper.main())


if __name__ == "__main__":
    raise SystemExit(main())
