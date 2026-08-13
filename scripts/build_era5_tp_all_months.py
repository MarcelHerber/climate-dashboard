#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import gzip
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "update_era5_land_europe.py"
OUT_DIR = ROOT / "era5_land_europe"
INDEX_PATH = OUT_DIR / "index.json"
HISTORY_DIR = OUT_DIR / "history_0p1"
HISTORY_INDEX = HISTORY_DIR / "index.json"
CACHE_DIR = ROOT / ".era5_cache"
MONTH_NAMES = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}
TP_KEYS = ("temperature", "precipitation")
BATCH_YEARS = 5
PATCH_VERSION = 1


def load_core():
    if not CORE_PATH.exists():
        raise RuntimeError(f"Hauptskript fehlt: {CORE_PATH}")
    spec = importlib.util.spec_from_file_location("era5_update_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("ERA5-Hauptskript konnte nicht importiert werden.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


def request_tp_batch(core, client, years: list[int], months: list[int], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": ["2m_temperature", "total_precipitation"],
        "year": [f"{year:04d}" for year in years],
        "month": [f"{month:02d}" for month in months],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": core.AREA,
    }
    label = f"T/P 0.1° months {','.join(f'{m:02d}' for m in months)} years {years[0]}–{years[-1]}"
    print(f"CDS T/P-Batch: {years[0]}–{years[-1]} · Monate {', '.join(MONTH_NAMES[m] for m in months)}")
    core.retrieve_with_retry(client, request, target, label, attempts=3)


def ordered_month_values(core, ds, aliases: tuple[str, ...], expected_years: list[int], month: int,
                         lat_name: str, lon_name: str) -> np.ndarray:
    name = core.variable_name(ds, aliases)
    da = ds[name]
    tdim = core.time_dim(da, lat_name, lon_name)
    if tdim is None:
        raise RuntimeError(f"Zeitdimension für {name} fehlt.")
    da = da.transpose(tdim, lat_name, lon_name)
    try:
        years = np.asarray(ds[tdim].dt.year.values, dtype=int)
        months = np.asarray(ds[tdim].dt.month.values, dtype=int)
    except Exception as exc:
        raise RuntimeError(f"Zeitachse von {name} konnte nicht als Jahr/Monat gelesen werden: {exc}") from exc

    indices: list[int] = []
    for year in expected_years:
        hits = np.where((years == int(year)) & (months == int(month)))[0]
        if hits.size != 1:
            raise RuntimeError(
                f"{name}: erwartet genau ein Feld für {year}-{month:02d}, gefunden {hits.size}."
            )
        indices.append(int(hits[0]))
    return np.asarray(da.isel({tdim: indices}).values, dtype=np.float32)


def decode_tp_month(core, ds, years: list[int], month: int, lat_name: str, lon_name: str) -> tuple[np.ndarray, np.ndarray]:
    temp = ordered_month_values(core, ds, core.TEMP_ALIASES, years, month, lat_name, lon_name) - 273.15
    precip = ordered_month_values(core, ds, core.PRECIP_ALIASES, years, month, lat_name, lon_name)
    days = np.asarray([calendar.monthrange(int(year), month)[1] for year in years], dtype=np.float32)[:, None, None]
    precip = precip * days * 1000.0
    return temp.astype(np.float32), precip.astype(np.float32)


def meta_ready(core, variables: dict, key: str, month: int, year_end: int) -> bool:
    meta = (variables.get(key) or {}).get(f"{month:02d}")
    return core._hires_pack_meta_ready(meta, core.HISTORY_START, year_end)


def build_missing_tp(core, client, archive: dict, year_end: int, force: bool) -> tuple[dict, list[int]]:
    variables = archive.get("variables") if isinstance(archive.get("variables"), dict) else {}
    variables = {key: dict(value) for key, value in variables.items() if isinstance(value, dict)}

    ready_before = [
        month for month in range(1, 13)
        if all(meta_ready(core, variables, key, month, year_end) for key in TP_KEYS)
    ]
    missing = list(range(1, 13)) if force else [month for month in range(1, 13) if month not in ready_before]
    print(f"T/P-Monate bereits vollständig: {len(ready_before)}/12"
          + (f" ({', '.join(MONTH_NAMES[m] for m in ready_before)})" if ready_before else ""))
    if not missing:
        return variables, ready_before

    print(f"Neu aufzubauen: {len(missing)} Monate · {', '.join(MONTH_NAMES[m] for m in missing)}")
    years = list(range(core.HISTORY_START, year_end + 1))
    year_chunks = chunks(years, BATCH_YEARS)
    signature = "".join(f"{m:02d}" for m in missing)
    raw_files = [
        CACHE_DIR / f"raw_history_tp_allmonths_v9_{chunk[0]}_{chunk[-1]}_m{signature}.nc"
        for chunk in year_chunks
    ]

    if force:
        for raw in raw_files:
            try:
                raw.unlink()
            except FileNotFoundError:
                pass

    mins = {(key, month): math.inf for key in TP_KEYS for month in missing}
    maxs = {(key, month): -math.inf for key in TP_KEYS for month in missing}
    lat = lon = None

    # Pass 1: wenige größere CDS-Jobs statt eines Jobs pro Monat/Jahrblock.
    for chunk, raw in zip(year_chunks, raw_files):
        if not raw.exists():
            request_tp_batch(core, client, chunk, missing, raw)
        ds = core.open_download(raw)
        lat_name, lon_name = core.spatial_names(ds)
        ds = core.normalize_lon(ds, lon_name)
        lat_here = np.asarray(ds[lat_name].values, dtype=float)
        lon_here = np.asarray(ds[lon_name].values, dtype=float)
        if lat is None:
            lat, lon = lat_here, lon_here
        elif not (np.array_equal(lat, lat_here) and np.array_equal(lon, lon_here)):
            ds.close()
            raise RuntimeError("T/P-Backfill: 0,1°-Gitter stimmt zwischen CDS-Blöcken nicht überein.")
        for month in missing:
            temp, precip = decode_tp_month(core, ds, chunk, month, lat_name, lon_name)
            for key, values in (("temperature", temp), ("precipitation", precip)):
                finite = values[np.isfinite(values)]
                if finite.size:
                    mins[(key, month)] = min(mins[(key, month)], float(np.min(finite)))
                    maxs[(key, month)] = max(maxs[(key, month)], float(np.max(finite)))
        ds.close()

    assert lat is not None and lon is not None
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    quant = {
        (key, month): core._hires_quant_params(mins[(key, month)], maxs[(key, month)])
        for key in TP_KEYS for month in missing
    }
    finals = {
        (key, month): HISTORY_DIR / f"{key}_m{month:02d}.u8.gz"
        for key in TP_KEYS for month in missing
    }
    temps = {(key, month): path.with_suffix(path.suffix + ".tmp") for (key, month), path in finals.items()}
    handles: dict[tuple[str, int], gzip.GzipFile] = {}

    try:
        for km, tmp in temps.items():
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            handles[km] = gzip.open(tmp, "wb", compresslevel=6)

        for chunk, raw in zip(year_chunks, raw_files):
            ds = core.open_download(raw)
            lat_name, lon_name = core.spatial_names(ds)
            ds = core.normalize_lon(ds, lon_name)
            for month in missing:
                temp, precip = decode_tp_month(core, ds, chunk, month, lat_name, lon_name)
                for key, values in (("temperature", temp), ("precipitation", precip)):
                    offset, step = quant[(key, month)]
                    packed = core._hires_delta_x(core._hires_quantize(values, offset, step))
                    handles[(key, month)].write(packed.tobytes(order="C"))
            ds.close()

        for handle in handles.values():
            handle.close()
        handles.clear()
        for km, final in finals.items():
            os.replace(temps[km], final)
    except Exception:
        for handle in handles.values():
            try:
                handle.close()
            except Exception:
                pass
        for tmp in temps.values():
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
        raise

    for key in TP_KEYS:
        variables.setdefault(key, {})
    for key in TP_KEYS:
        for month in missing:
            offset, step = quant[(key, month)]
            variables[key][f"{month:02d}"] = core._hires_meta(
                finals[(key, month)], month=month,
                year_start=core.HISTORY_START, year_end=year_end,
                lat=lat, lon=lon, offset=offset, step=step,
            )

    # Nach erfolgreichem Packen sind die großen Rohblöcke entbehrlich.
    for raw in raw_files:
        try:
            raw.unlink()
        except FileNotFoundError:
            pass

    return variables, [
        month for month in range(1, 13)
        if all(meta_ready(core, variables, key, month, year_end) for key in TP_KEYS)
    ]


def patch_archive(core, archive: dict, variables: dict, ready_months: list[int], year_end: int) -> dict:
    archive = dict(archive)
    archive["ready"] = True
    archive["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    archive["variables"] = variables
    archive["temperature_precipitation_months"] = ready_months
    archive["available_months_by_variable"] = {
        key: sorted(int(m) for m, meta in group.items() if str(m).isdigit() and isinstance(meta, dict))
        for key, group in variables.items() if isinstance(group, dict)
    }
    archive["available_months"] = sorted({
        month for group in archive["available_months_by_variable"].values() for month in group
    })
    archive["tp_all_months_version"] = PATCH_VERSION
    archive["tp_all_months_note"] = (
        "Temperatur und Niederschlag sind für Januar bis Dezember als sichtbare 0,1°-Historienkarten verfügbar. "
        "Weitere ERA5-Land-Parameter bleiben zunächst auf den bereits aufgebauten Monaten/Perioden."
    )
    archive["year_end"] = int(year_end)
    return archive


def patch_top_index(payload: dict, ready_months: list[int], year_end: int) -> dict:
    payload = dict(payload)
    payload["payload_version"] = max(9, int(payload.get("payload_version", 0) or 0))
    payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    periods = dict(payload.get("periods") or {})
    month_period_ids = []
    for month in ready_months:
        pid = f"month_{month:02d}"
        month_period_ids.append(pid)
        periods[pid] = {
            "id": pid,
            "label": MONTH_NAMES[month],
            "year": int(year_end),
            "months": [int(month)],
            "historical_only": True,
            "parameters": ["temperature", "precipitation"],
        }
    payload["periods"] = periods
    history_map = dict(payload.get("history_map") or {})
    old_periods = [str(v) for v in history_map.get("periods", [])]
    history_map["periods"] = list(dict.fromkeys([*old_periods, *month_period_ids]))
    history_map["temperature_precipitation_months"] = ready_months
    history_map["tp_all_months_ready"] = ready_months == list(range(1, 13))
    history_map["tp_all_months_note"] = (
        "Temperatur und Niederschlag: historische Monatskarten Januar–Dezember auf 0,1°; "
        "Zusatzparameter werden schrittweise ergänzt."
    )
    payload["history_map"] = history_map
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="ERA5-Land 0,1°-Historienarchiv: Temperatur und Niederschlag für alle Monate ergänzen.")
    parser.add_argument("--force", action="store_true", help="Auch vorhandene T/P-Monatspacks neu aufbauen")
    args = parser.parse_args()

    if not INDEX_PATH.exists() or not HISTORY_INDEX.exists():
        raise RuntimeError(
            "ERA5-Land-Basis fehlt. Zuerst den normalen Workflow 'ERA5-Land Europa aktualisieren' ausführen."
        )
    core = load_core()
    top = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    archive = json.loads(HISTORY_INDEX.read_text(encoding="utf-8"))
    history_meta = top.get("history_map") or {}
    year_end = int(history_meta.get("year_end") or archive.get("year_end") or 0)
    if year_end < core.HISTORY_START:
        raise RuntimeError(f"Ungültiges Historien-Endjahr: {year_end}")

    print("=== ERA5-LAND EUROPA · T/P-MONATSARCHIV ===")
    print(f"Historie: {core.HISTORY_START}–{year_end}")
    print("Ziel: Januar bis Dezember · nur 2-m-Temperatur + Niederschlag")

    client = core.cds_client()
    variables, ready_months = build_missing_tp(core, client, archive, year_end, args.force)
    archive = patch_archive(core, archive, variables, ready_months, year_end)
    top = patch_top_index(top, ready_months, year_end)
    atomic_json(HISTORY_INDEX, archive)
    atomic_json(INDEX_PATH, top)

    print("=== SUMMARY ===")
    print(f"T/P-Monate bereit: {len(ready_months)}/12")
    print("Monate:", ", ".join(MONTH_NAMES[m] for m in ready_months) or "keine")
    if ready_months != list(range(1, 13)):
        raise RuntimeError("T/P-Monatsarchiv ist nach dem Lauf nicht vollständig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
