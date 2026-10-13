#!/usr/bin/env python3
"""Incremental ERA5 pressure-level expansion, 1940-2025.

One CDS request/parameter/calendar month is cached as a release asset; a small
set of year-month map atlases is then released and verified before activation.
Existing era5_europe archives and indices are never overwritten.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from build_era5_atmos_history import render_triptych
from update_era5_europe import (
    HISTORY_START, REFERENCE_START, REFERENCE_END, MONTH_NAMES,
    cds_client, request_pressure, normalize_dataarray, years_from_times,
    rank_field, area_weighted_mean, area_weighted_fraction,
)

LAST_YEAR = 2025
REFERENCE_TAG = "era5-atmos-extra-reference-1940-2025-v1"
YEAR_TAG_PREFIX = "era5-atmos-extra"
REPO = "MarcelHerber/climate-dashboard"
YEARS = np.arange(HISTORY_START, LAST_YEAR + 1)
VIEWS = ("absolute", "anomaly", "rank")
EXTRA = {
    "t925": dict(label="Temperatur 925 hPa", short_label="T925", variable="temperature",
        aliases=("t", "temperature"), level="925", unit="°C", anomaly_unit="K",
        convert="kelvin", absolute_cmap="coolwarm", anomaly_cmap="RdBu_r",
        anomaly_bounds=[-8,-6,-4,-3,-2,-1,-0.5,0,0.5,1,2,3,4,6,8],
        rank_label="1 = wärmster"),
    "t700": dict(label="Temperatur 700 hPa", short_label="T700", variable="temperature",
        aliases=("t", "temperature"), level="700", unit="°C", anomaly_unit="K",
        convert="kelvin", absolute_cmap="coolwarm", anomaly_cmap="RdBu_r",
        anomaly_bounds=[-8,-6,-4,-3,-2,-1,-0.5,0,0.5,1,2,3,4,6,8],
        rank_label="1 = wärmster"),
    "t500": dict(label="Temperatur 500 hPa", short_label="T500", variable="temperature",
        aliases=("t", "temperature"), level="500", unit="°C", anomaly_unit="K",
        convert="kelvin", absolute_cmap="coolwarm", anomaly_cmap="RdBu_r",
        anomaly_bounds=[-8,-6,-4,-3,-2,-1,-0.5,0,0.5,1,2,3,4,6,8],
        rank_label="1 = wärmster"),
    "rh700": dict(label="Relative Luftfeuchte 700 hPa", short_label="RH700",
        variable="relative_humidity", aliases=("r", "relative_humidity"), level="700",
        unit="%", anomaly_unit="Prozentpunkte", absolute_cmap="YlGnBu",
        anomaly_cmap="BrBG", anomaly_bounds=[-40,-30,-20,-15,-10,-5,-2,0,2,5,10,15,20,30,40],
        rank_label="1 = höchste Feuchte"),
    "omega500": dict(label="Vertikalbewegung 500 hPa", short_label="Omega500",
        variable="vertical_velocity", aliases=("w", "vertical_velocity"), level="500",
        unit="Pa/s", anomaly_unit="Pa/s", absolute_cmap="PuOr",
        anomaly_cmap="PuOr", anomaly_bounds=[-0.12,-0.08,-0.05,-0.03,-0.02,-0.01,-0.005,0,
            0.005,0.01,0.02,0.03,0.05,0.08,0.12],
        rank_label="1 = stärkste Hebung (negatives Omega)", rank_ascending=True),
    "u300": dict(label="Zonaler Wind 300 hPa", short_label="U300",
        variable="u_component_of_wind", aliases=("u", "u_component_of_wind"),
        level="300", unit="m/s", anomaly_unit="m/s",
        absolute_cmap="PuOr", anomaly_cmap="RdBu_r",
        anomaly_bounds=[-24,-18,-12,-8,-5,-3,-1,0,1,3,5,8,12,18,24],
        rank_label="1 = stärkste Westwindkomponente"),
}


def validate_reference(path: Path, key: str, month: int) -> None:
    with np.load(path, allow_pickle=False) as pack:
        if set(pack.files) != {"month", "years", "lat", "lon", "values"}:
            raise RuntimeError(f"Invalid reference keys: {key}/{month}")
        if int(pack["month"]) != month or not np.array_equal(pack["years"], YEARS):
            raise RuntimeError(f"Missing years in {key}/{month}")
        shape = (len(YEARS), len(pack["lat"]), len(pack["lon"]))
        values = pack["values"]
        if values.shape != shape or len(pack["lat"]) < 100 or len(pack["lon"]) < 100:
            raise RuntimeError(f"Unexpected grid: {key}/{month} {values.shape}")
        if not np.isfinite(values).mean() > .95:
            raise RuntimeError(f"Missing ERA5 field values: {key}/{month}")


def make_reference(month: int, key: str, out: Path) -> None:
    if key not in EXTRA or not 1 <= month <= 12:
        raise ValueError(f"Invalid request: {key}/{month}")
    meta = EXTRA[key]
    nc = out.with_suffix(".nc")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file():
        validate_reference(out, key, month)
        return
    request_pressure(cds_client(), variable=[meta["variable"]], level=meta["level"],
        years=YEARS.tolist(), month=month, target=nc)
    try:
        import xarray as xr
        with xr.open_dataset(nc) as ds:
            lat, lon, times, values = normalize_dataarray(ds, tuple(meta["aliases"]))
        years = years_from_times(times)
        order = np.argsort(years)
        years = years[order]
        values = values[order]
        if not np.array_equal(years, YEARS):
            raise RuntimeError(f"Expected {YEARS[0]}-{YEARS[-1]}: {key}/{month}; got {years}")
        if meta.get("convert") == "kelvin":
            values = values - np.float32(273.15)
        tmp = out.with_name(out.name + ".partial.npz")
        np.savez_compressed(tmp, month=np.int16(month), years=years.astype(np.int16),
            lat=lat.astype(np.float32), lon=lon.astype(np.float32),
            values=values.astype(np.float32))
        validate_reference(tmp, key, month)
        tmp.replace(out)
    finally:
        nc.unlink(missing_ok=True)
    print(f"Ready: {key}/{month:02d}, {out.stat().st_size} bytes", flush=True)


def render_month(year: int, month: int, refs: Path, out: Path) -> None:
    if year not in YEARS or not 1 <= month <= 12:
        raise ValueError((year, month))
    out.mkdir(parents=True, exist_ok=True)
    period = f"{year:04d}-{month:02d}"
    products = {}
    for key, meta in EXTRA.items():
        packpath = refs / f"month_{month:02d}_{key}.npz"
        validate_reference(packpath, key, month)
        with np.load(packpath, allow_pickle=False) as pack:
            values = np.asarray(pack["values"], dtype=np.float32)
            lat = np.asarray(pack["lat"], dtype=np.float32)
            lon = np.asarray(pack["lon"], dtype=np.float32)
            current = values[year - HISTORY_START]
            norm = np.nanmean(values[(YEARS >= REFERENCE_START) &
                (YEARS <= REFERENCE_END)], axis=0)
            anomaly = current - norm
            if meta.get("rank_ascending"):
                ranks = rank_field(-current, -values)
            else:
                ranks = rank_field(current, values)
            valid = np.isfinite(ranks)
            label = f"{MONTH_NAMES[month]} {year}"
            atlas = out / f"{period}-{key}.webp"
            render_triptych(current, anomaly, ranks, lat, lon, meta=meta,
                key=key, label=label, destination=atlas)
            asset = (f"https://github.com/{REPO}/releases/download/"
                f"{YEAR_TAG_PREFIX}-{year}-v1/{atlas.name}")
            products[key] = {
                "label": meta["label"], "short_label": meta["short_label"],
                "unit": meta["unit"], "level_hpa": int(meta["level"]),
                "absolute": {"file": asset, "tile_index": 0},
                "anomaly": {"file": asset, "tile_index": 1,
                    "reference_period": "1991–2020"},
                "rank": {"file": asset, "tile_index": 2,
                    "history_start": HISTORY_START, "history_end": LAST_YEAR,
                    "comparison_years": len(YEARS)-1,
                    "total_rank_positions": len(YEARS),
                    "direction": meta["rank_label"],
                    "rank1_area_percent": area_weighted_fraction(ranks <= 1, valid, lat),
                    "top3_area_percent": area_weighted_fraction(ranks <= 3, valid, lat)},
                "stats": {"current_area_mean": area_weighted_mean(current, lat),
                    "reference_area_mean": area_weighted_mean(norm, lat),
                    "anomaly_area_mean": area_weighted_mean(anomaly, lat)},
            }
        print(f"Rendered {period} {key}", flush=True)
    if len(list(out.glob("*.webp"))) != len(EXTRA):
        raise RuntimeError(f"Missing atlases for {period}")
    (out / "manifest.json").write_text(json.dumps({
        "ready": True, "year": year, "month": month, "period": period,
        "reference_period": "1991–2020", "products": products,
    }, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def check_manifest(item: dict) -> None:
    year, month = int(item["year"]), int(item["month"])
    period = f"{year:04d}-{month:02d}"
    if year not in YEARS or not 1 <= month <= 12 or item.get("period") != period:
        raise ValueError(f"Invalid period: {item.get('period')}")
    if not item.get("ready") or set(item.get("products", {})) != set(EXTRA):
        raise ValueError(f"Incomplete manifest: {period}")
    for key, product in item["products"].items():
        url = (f"/{YEAR_TAG_PREFIX}-{year}-v1/{period}-{key}.webp")
        if any(url not in product.get(view, {}).get("file", "")
               for view in VIEWS):
            raise ValueError(f"Invalid asset: {period}/{key}")


def merge_verified(artifacts: Path, repo: Path) -> None:
    target = repo / "era5_europe" / "extra"
    history = target / "history"
    history.mkdir(parents=True, exist_ok=True)
    added = 0
    for f in sorted(artifacts.rglob("manifest.json")):
        entry = json.loads(f.read_text(encoding="utf-8"))
        check_manifest(entry)
        year, period = int(entry["year"]), entry["period"]
        path = history / f"{year}.json"
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "ready": True, "year": year, "periods": {}}
        old["periods"][period] = {
            "ready": True, "period": period, "year": year,
            "month": entry["month"], "label": f"{MONTH_NAMES[entry['month']]} {year}",
            "products": entry["products"],
        }
        path.write_text(json.dumps(old, ensure_ascii=False, indent=2,
            allow_nan=False) + "\n", encoding="utf-8")
        added += 1
    if not added:
        raise RuntimeError("No verified manifests received")
    periods = []
    for path in sorted(history.glob("????.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for period, item in data.get("periods", {}).items():
            check_manifest({"ready": item["ready"], "year": item["year"],
                "month": item["month"], "period": period, "products": item["products"]})
            periods.append(period)
    periods = sorted(set(periods))
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.json").write_text(json.dumps({
        "ready": True, "year_start": HISTORY_START, "year_end": LAST_YEAR,
        "reference_period": "1991–2020", "available_periods": periods,
        "products": {k: {"label": v["label"], "short_label": v["short_label"]}
            for k,v in EXTRA.items()},
        "completed": len(periods), "expected": len(YEARS) * 12,
        "note": "Only verified monthly releases are shown.",
    }, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Published {added} periods; total {len(periods)}/{len(YEARS)*12}", flush=True)


def plan(index_path: Path, output: Path, batch_size: int) -> None:
    data = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    done = set(data.get("available_periods", []))
    selected = None
    for month in range(1, 13):
        for year in YEARS:
            if f"{year}-{month:02d}" not in done:
                selected = (int(month), int(year))
                break
        if selected:
            break
    if selected:
        month, first = selected
        years = [year for year in range(first, min(LAST_YEAR, first+batch_size-1)+1)
            if f"{year}-{month:02d}" not in done]
        payload = (f"has_work=true\nmonth={month:02d}\nyears={json.dumps(years)}\n")
    else:
        payload = "has_work=false\nmonth=00\nyears=[]\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as f:
        f.write(payload)
    print(payload, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("reference")
    p.add_argument("--month", type=int, required=True)
    p.add_argument("--parameter", choices=EXTRA, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("render")
    p.add_argument("--month", type=int, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--references", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("merge")
    p.add_argument("--artifacts", type=Path, required=True)
    p.add_argument("--repo", type=Path, default=Path("."))
    p = sub.add_parser("plan")
    p.add_argument("--index", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()
    if args.command == "reference":
        make_reference(args.month, args.parameter, args.output)
    elif args.command == "render":
        render_month(args.year, args.month, args.references, args.output)
    elif args.command == "merge":
        merge_verified(args.artifacts, args.repo)
    else:
        plan(args.index, args.output, args.batch_size)


if __name__ == "__main__":
    main()
