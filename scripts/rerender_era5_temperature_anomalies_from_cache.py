#!/usr/bin/env python3
from __future__ import annotations

"""Temperatur-Abweichungs-PNGs ausschließlich aus dem vorhandenen ERA5-Cache neu rendern.

Dieser Pfad ist absichtlich netzwerkfrei: Es wird kein CDS-Client erzeugt und
fehlende Cache-Dateien führen zu einem sofortigen Fehler statt zu einem Download.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "era5_land_europe" / "index.json"
CORE_PATH = ROOT / "scripts" / "update_era5_land_europe.py"
PALETTE_PATH = ROOT / "scripts" / "update_era5_land_europe_palette.py"
CACHE_DIR = ROOT / ".era5_cache"


class NoCDSClient:
    """Sicherheitsgurt: selbst bei einem unerwarteten Cache-Miss kein CDS-Zugriff."""

    def retrieve(self, *args, **kwargs):
        raise RuntimeError("CACHE-ONLY: CDS-Zugriff ist für diesen Renderpfad gesperrt.")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Modul konnte nicht geladen werden: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def latest_complete_key(payload: dict) -> tuple[int, int]:
    raw = str(payload.get("latest_month_key") or "")
    match = re.fullmatch(r"(\d{4})-(\d{2})", raw)
    if not match:
        raise RuntimeError("latest_month_key fehlt oder ist ungültig.")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise RuntimeError(f"Ungültiger Monat: {month}")
    return year, month


def target_periods(payload: dict, year: int, latest_month: int) -> list[dict]:
    periods = payload.get("periods") if isinstance(payload.get("periods"), dict) else {}
    ids = ["latest_month", "summer"] + [f"month_{m:02d}" for m in range(1, latest_month + 1)]
    targets: list[dict] = []
    for period_id in ids:
        period = periods.get(period_id)
        if not isinstance(period, dict):
            continue
        if period.get("historical_only"):
            continue
        try:
            period_year = int(period.get("year"))
        except (TypeError, ValueError):
            continue
        months = [int(m) for m in period.get("months", [])]
        anomaly = ((period.get("temperature") or {}).get("anomaly") or {})
        filename = anomaly.get("file")
        if period_year != year or not months or any(m < 1 or m > latest_month for m in months) or not filename:
            continue
        targets.append({
            "id": period_id,
            "label": str(period.get("label") or period_id),
            "year": period_year,
            "months": months,
            "file": str(filename),
        })
    return targets


def _current_cache_file(year: int, months: list[int]) -> Path:
    return CACHE_DIR / f"current_{year}_{'_'.join(f'{m:02d}' for m in months)}.nc"


def _climate_cache_ready(month: int) -> bool:
    merged = CACHE_DIR / f"climatology_1991_2020_{month:02d}.nc"
    if merged.exists():
        return True
    chunks = (
        CACHE_DIR / f"raw_climatology_v4_{month:02d}_1991_2000.nc",
        CACHE_DIR / f"raw_climatology_v4_{month:02d}_2001_2010.nc",
        CACHE_DIR / f"raw_climatology_v4_{month:02d}_2011_2020.nc",
    )
    return all(path.exists() for path in chunks)


def assert_cache_ready(year: int, months: list[int]) -> None:
    current_file = _current_cache_file(year, months)
    missing: list[str] = []
    if not current_file.exists():
        missing.append(current_file.name)
    for month in months:
        if not _climate_cache_ready(month):
            missing.append(f"climatology month {month:02d}")
    if missing:
        raise RuntimeError(
            "CACHE-ONLY: benötigte ERA5-Dateien fehlen; es wird bewusst nichts heruntergeladen: "
            + ", ".join(missing)
        )


def main() -> int:
    if not INDEX_PATH.exists():
        raise RuntimeError(f"Index fehlt: {INDEX_PATH}")
    payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    year, latest_month = latest_complete_key(payload)
    months = list(range(1, latest_month + 1))
    targets = target_periods(payload, year, latest_month)
    if not targets:
        raise RuntimeError("Keine aktuellen Temperatur-Abweichungskarten zum Rendern gefunden.")

    # Entscheidend: erst Cache vollständig prüfen, bevor irgendeine Laderoutine läuft.
    assert_cache_ready(year, months)

    core = load_module(CORE_PATH, "update_era5_land_europe")
    palette = load_module(PALETTE_PATH, "era5_land_europe_palette_cache_only")
    client = NoCDSClient()

    current = core.load_current_months(client, year, months, False)
    climate = {month: core.load_climatology_month(client, month, False) for month in months}

    print("=== ERA5-LAND · TEMPERATUR-PALETTE · CACHE-ONLY ===")
    print(f"Jahr: {year} · Monate im Cache: 01–{latest_month:02d}")
    print("CDS-Zugriff: gesperrt")

    for target in targets:
        pmonths = target["months"]
        lat = np.asarray(current[pmonths[0]][0])
        lon = np.asarray(current[pmonths[0]][1])
        current_temp = core.combine_temperature({m: current[m][2] for m in pmonths}, year, pmonths)
        climate_temp = core.combine_temperature({m: climate[m][2] for m in pmonths}, year, pmonths)
        anomaly = np.asarray(current_temp, dtype=float) - np.asarray(climate_temp, dtype=float)
        filename = ROOT / target["file"]
        print(f"Render: {target['id']} -> {filename.relative_to(ROOT)}")
        palette.render_map(
            anomaly,
            lat,
            lon,
            title=f"ERA5-Land Europa · Temperaturabweichung · {target['label']}",
            subtitle="gegenüber 1991–2020 · Landflächen",
            unit="K",
            filename=filename,
            kind="temp_anomaly",
        )

    print(f"Fertig: {len(targets)} Temperatur-Abweichungs-PNGs neu gerendert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
