#!/usr/bin/env python3
"""Publish six additional ERA5 monthly pressure-level maps from 2026 onward.

Historical 1940-2025 reference packages are reused verbatim. Each new calendar
month is published only after all six real CDS fields and three map views pass
validation. Do not alter the complete historical ERA5 archive.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import xarray as xr

from build_era5_atmos_history import render_triptych
from era5_atmos_extra import EXTRA, HISTORY_START, LAST_YEAR, REFERENCE_START, REFERENCE_END, REPO, validate_reference
from update_era5_europe import (
    MONTH_NAMES, area_weighted_fraction, area_weighted_mean, cds_client,
    normalize_dataarray, rank_field, request_pressure, years_from_times,
)

BASELINE_YEARS = np.arange(HISTORY_START, LAST_YEAR + 1)
RANK_TOTAL = len(BASELINE_YEARS) + 1
VIEWS = ("absolute", "anomaly", "rank")
CURRENT_TAG_PREFIX = "era5-atmos-extra-current"


def parse_period(period: str) -> tuple[int, int]:
    try:
        year, month = map(int, period.split("-"))
    except ValueError as exc:
        raise ValueError(f"Ungültiger Zeitraum: {period}") from exc
    if year < 2026 or not 1 <= month <= 12 or period != f"{year:04d}-{month:02d}":
        raise ValueError(f"Ungültiger Zeitraum: {period}")
    return year, month


def release_tag(year: int) -> str:
    return f"{CURRENT_TAG_PREFIX}-{year}-v1"


def build(period: str, references: Path, output: Path) -> None:
    year, month = parse_period(period)
    output.mkdir(parents=True, exist_ok=True)
    products: dict[str, dict] = {}
    client = cds_client()
    for key, meta in EXTRA.items():
        reference_path = references / f"month_{month:02d}_{key}.npz"
        validate_reference(reference_path, key, month)
        with np.load(reference_path, allow_pickle=False) as pack:
            ref_values = np.asarray(pack["values"], dtype=np.float32)
            ref_lat = np.asarray(pack["lat"], dtype=np.float32)
            ref_lon = np.asarray(pack["lon"], dtype=np.float32)
        source = output / f"{period}-{key}.nc"
        for attempt in range(1, 4):
            try:
                request_pressure(client, variable=[meta["variable"]],
                                 level=str(meta["level"]), years=[year], month=month, target=source)
                if not source.is_file() or source.stat().st_size < 1024:
                    raise RuntimeError(f"{period}/{key}: ERA5 NetCDF fehlt oder ist leer")
                break
            except Exception:
                source.unlink(missing_ok=True)
                if attempt == 3:
                    raise
                print(f"ERA5 CDS request {period}/{key}: attempt {attempt}/3 failed; retrying", flush=True)
                time.sleep(10 * attempt)
        try:
            with xr.open_dataset(source) as ds:
                lat, lon, times, current_cube = normalize_dataarray(ds, tuple(meta["aliases"]))
            current_years = years_from_times(times)
            if current_cube.shape != (1, len(lat), len(lon)) or not np.array_equal(current_years, [year]):
                raise RuntimeError(f"{period}/{key}: Monatsmittel unvollständig")
            if not (np.allclose(lat, ref_lat) and np.allclose(lon, ref_lon)):
                raise RuntimeError(f"{period}/{key}: ERA5-Raster passt nicht zur Referenz")
            current = np.asarray(current_cube[0], dtype=np.float32)
            if meta.get("convert") == "kelvin":
                current -= np.float32(273.15)
            if np.isfinite(current).mean() < 0.95:
                raise RuntimeError(f"{period}/{key}: zu viele fehlende Gitterwerte")
            normal = np.nanmean(ref_values[(BASELINE_YEARS >= REFERENCE_START) &
                                          (BASELINE_YEARS <= REFERENCE_END)], axis=0).astype(np.float32)
            anomaly = (current - normal).astype(np.float32)
            if meta.get("rank_ascending"):
                ranks = rank_field(-current, -ref_values)
            else:
                ranks = rank_field(current, ref_values)
            ranks = ranks.astype(np.float32)
            atlas = output / f"{period}-{key}.webp"
            render_triptych(current, anomaly, ranks, ref_lat, ref_lon,
                            meta=meta, key=key, label=f"{MONTH_NAMES[month]} {year}",
                            destination=atlas, rank_total=RANK_TOTAL, rank_end=LAST_YEAR)
            asset = (f"https://github.com/{REPO}/releases/download/"
                     f"{release_tag(year)}/{atlas.name}")
            valid = np.isfinite(ranks)
            products[key] = {
                "label": meta["label"], "short_label": meta["short_label"],
                "unit": meta["unit"], "level_hpa": int(meta["level"]),
                "absolute": {"file": asset, "tile_index": 0},
                "anomaly": {"file": asset, "tile_index": 1,
                            "unit": meta.get("anomaly_unit", meta["unit"]),
                            "reference_period": "1991–2020"},
                "rank": {"file": asset, "tile_index": 2,
                         "history_start": HISTORY_START, "history_end": LAST_YEAR,
                         "comparison_years": len(BASELINE_YEARS),
                         "total_rank_positions": RANK_TOTAL,
                         "direction": meta["rank_label"],
                         "rank1_area_percent": area_weighted_fraction(ranks <= 1, valid, ref_lat),
                         "top3_area_percent": area_weighted_fraction(ranks <= 3, valid, ref_lat)},
                "stats": {"current_area_mean": area_weighted_mean(current, ref_lat),
                          "reference_area_mean": area_weighted_mean(normal, ref_lat),
                          "anomaly_area_mean": area_weighted_mean(anomaly, ref_lat)},
            }
            print(f"ERA5 monthly current {period}/{key} rendered", flush=True)
        finally:
            source.unlink(missing_ok=True)
    manifest = {"ready": True, "year": year, "month": month, "period": period,
                "label": f"{MONTH_NAMES[month]} {year}",
                "reference_period": "1991–2020", "rank_reference": "1940–2025",
                "products": products}
    validate_manifest(manifest)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def validate_manifest(entry: dict) -> None:
    year, month = parse_period(entry["period"])
    if not entry.get("ready") or int(entry["year"]) != year or int(entry["month"]) != month:
        raise ValueError(f"Manifest nicht bereit: {entry.get('period')}")
    if set(entry.get("products", {})) != set(EXTRA):
        raise ValueError(f"Fehlende Zusatzparameter: {entry['period']}")
    for key, p in entry["products"].items():
        expected = f"/{release_tag(year)}/{entry['period']}-{key}.webp"
        for view in VIEWS:
            if expected not in p.get(view, {}).get("file", ""):
                raise ValueError(f"Falscher Kartenpfad {entry['period']}/{key}/{view}")


def plan(main_index: Path, extra_index: Path, output: Path, batch_size: int) -> None:
    main = json.loads(main_index.read_text(encoding="utf-8"))
    extra = json.loads(extra_index.read_text(encoding="utf-8"))
    latest = main.get("latest_month_key")
    parse_period(latest)
    recent = sorted(set(main.get("available_periods", [])))
    done = set(extra.get("current_periods", []))
    backlog = [p for p in recent if p >= "2026-01" and p <= latest and p not in done]
    # Keep every batch in the same yearly Release; at most two months in parallel.
    if backlog:
        first_year = backlog[0][:4]
        backlog = [p for p in backlog if p.startswith(first_year + "-")]
    todo = backlog[:batch_size]
    result = {
        "has_work": "true" if todo else "false",
        "periods": json.dumps(todo, separators=(",", ":")),
        "year": todo[0][:4] if todo else "0000",
    }
    with output.open("a", encoding="utf-8") as handle:
        for k, v in result.items():
            handle.write(f"{k}={v}\n")
    print(f"Backfill: {todo}; bislang {len(done)} aktuelle Zusatzmonate")


def merge(artifacts: Path, root: Path) -> None:
    extra_root = root / "era5_europe" / "extra"
    current = extra_root / "current"
    current.mkdir(parents=True, exist_ok=True)
    added = []
    for f in sorted(artifacts.rglob("manifest.json")):
        entry = json.loads(f.read_text(encoding="utf-8"))
        validate_manifest(entry)
        period = entry["period"]
        target = current / f"{period}.json"
        target.write_text(json.dumps(entry, indent=2, ensure_ascii=False,
                                     allow_nan=False) + "\n", encoding="utf-8")
        added.append(period)
    if not added:
        raise RuntimeError("Keine bestätigten ERA5-Zusatzmonate vorhanden")
    index_file = extra_root / "index.json"
    idx = json.loads(index_file.read_text(encoding="utf-8"))
    verified = []
    for item in sorted(current.glob("????-??.json")):
        entry = json.loads(item.read_text(encoding="utf-8"))
        validate_manifest(entry)
        verified.append(entry["period"])
    idx["current_periods"] = sorted(set(verified))
    idx["current_through"] = max(verified)
    idx["current_note"] = (
        "Six pressure-level additions from 2026, using ERA5 monthly means; "
        "1991-2020 anomalies; rank against 1940-2025 plus target year."
    )
    index_file.write_text(json.dumps(idx, indent=2, ensure_ascii=False,
                                     allow_nan=False) + "\n", encoding="utf-8")
    print(f"Published new ERA5 months {added}; latest {idx['current_through']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build")
    p.add_argument("--period", required=True)
    p.add_argument("--references", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("plan")
    p.add_argument("--main", type=Path, required=True)
    p.add_argument("--extra", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--batch-size", type=int, default=2)
    p = sub.add_parser("merge")
    p.add_argument("--artifacts", type=Path, required=True)
    p.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    if args.command == "build":
        build(args.period, args.references, args.output)
    elif args.command == "plan":
        plan(args.main, args.extra, args.output, args.batch_size)
    else:
        merge(args.artifacts, args.root)


if __name__ == "__main__":
    main()
