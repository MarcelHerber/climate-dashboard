#!/usr/bin/env python3
"""Build ERA5 1940-2025 monthly references once and publish annual map archives.

The 12 reference packs are stored in a GitHub Release; annual maps are held in
separate year releases so GitHub Pages does not grow by multiple gigabytes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from update_era5_europe import (
    HISTORY_START,
    REFERENCE_START,
    REFERENCE_END,
    AREA,
    PRODUCTS,
    MONTH_NAMES,
    area_weighted_fraction,
    area_weighted_mean,
    cds_client,
    load_product,
    rank_field,
    render_field,
    robust_range,
)

HISTORY_END = 2025
REPO = "MarcelHerber/climate-dashboard"
REFERENCE_TAG = "era5-atmos-history-reference-1940-2025-v1"
EXPECTED_YEARS = np.arange(HISTORY_START, HISTORY_END + 1, dtype=np.int16)
VIEWS = ("absolute", "anomaly", "rank")


def reference_month(month: int, destination: Path) -> None:
    """Download the four parameter histories for one calendar month only once."""
    if not (1 <= month <= 12):
        raise ValueError(month)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = cds_client()
    payload: dict[str, np.ndarray] = {}
    lat_ref = lon_ref = None
    for key in PRODUCTS:
        lat, lon, years, values = load_product(source, key, HISTORY_END, month, False)
        if not np.array_equal(years, EXPECTED_YEARS):
            raise RuntimeError(f"{month:02d}/{key}: incomplete historical years")
        if lat_ref is None:
            lat_ref, lon_ref = lat, lon
        elif not np.array_equal(lat_ref, lat) or not np.array_equal(lon_ref, lon):
            raise RuntimeError(f"{month:02d}/{key}: inconsistent ERA5 grids")
        payload[key] = values.astype(np.float32)
        print(f"Reference {month:02d}/{key}: {values.shape}", flush=True)

    if lat_ref is None or lon_ref is None:
        raise RuntimeError("Empty reference")
    np.savez_compressed(
        destination,
        month=np.asarray(month, dtype=np.int16),
        years=EXPECTED_YEARS,
        lat=lat_ref.astype(np.float32),
        lon=lon_ref.astype(np.float32),
        **payload,
    )
    # Fail fast on missing keys, damaged archive, or partial CDS output.
    with np.load(destination, allow_pickle=False) as data:
        if int(data["month"]) != month or not np.array_equal(data["years"], EXPECTED_YEARS):
            raise RuntimeError("Reference manifest check failed")
        expected_shape = (len(EXPECTED_YEARS), len(lat_ref), len(lon_ref))
        for key in PRODUCTS:
            if data[key].shape != expected_shape:
                raise RuntimeError(f"{key}: {data[key].shape} != {expected_shape}")
    print(f"Reference {month:02d} ready: {destination.stat().st_size / 1048576:.1f} MiB", flush=True)


def render_map_webp(
    values: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    *,
    title: str,
    subtitle: str,
    unit: str,
    destination: Path,
    cmap: str,
    bounds: list[float] | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
) -> None:
    png = destination.with_suffix(".png")
    try:
        render_field(
            values, lat, lon, title=title, subtitle=subtitle, unit=unit,
            filename=png, cmap=cmap, bounds=bounds, vmin=vmin, vmax=vmax
        )
        with Image.open(png) as image:
            image.convert("RGB").save(destination, format="WEBP", quality=78, method=4)
        if destination.stat().st_size < 1000:
            raise RuntimeError(f"Image suspiciously small: {destination}")
    finally:
        png.unlink(missing_ok=True)


def render_year(year: int, reference_dir: Path, output: Path) -> None:
    """Render 12 x 4 x 3 maps with a fixed 1940-2025 rank population."""
    if year < HISTORY_START or year > HISTORY_END:
        raise ValueError(year)
    output.mkdir(parents=True, exist_ok=True)
    periods = {}

    for month in range(1, 13):
        reference = reference_dir / f"month_{month:02d}.npz"
        if not reference.is_file():
            raise FileNotFoundError(reference)
        period = f"{year:04d}-{month:02d}"
        period_products = {}
        with np.load(reference, allow_pickle=False) as data:
            years = np.asarray(data["years"], dtype=int)
            if not np.array_equal(years, EXPECTED_YEARS) or int(data["month"]) != month:
                raise RuntimeError(f"Reference mismatch for {period}")
            lat = np.asarray(data["lat"], dtype=np.float32)
            lon = np.asarray(data["lon"], dtype=np.float32)
            year_pos = int(np.flatnonzero(years == year)[0])
            ref_mask = (years >= REFERENCE_START) & (years <= REFERENCE_END)
            label = f"{MONTH_NAMES[month]} {year}"

            for key, meta in PRODUCTS.items():
                values = np.asarray(data[key], dtype=np.float32)
                current = values[year_pos]
                normal = np.nanmean(values[ref_mask], axis=0).astype(np.float32)
                anomaly = (current - normal).astype(np.float32)
                rank = rank_field(current, values)
                valid = np.isfinite(rank)
                range_lo, range_hi = robust_range(current)

                basename = f"{period}-{key}"
                images = {
                    view: output / f"{basename}-{view}.webp"
                    for view in VIEWS
                }
                render_map_webp(
                    current, lat, lon, title=f"{meta['label']} · {label}",
                    subtitle="ERA5 Monatsmittel", unit=meta["unit"],
                    destination=images["absolute"],
                    cmap=meta["absolute_cmap"],
                    vmin=range_lo, vmax=range_hi,
                )
                render_map_webp(
                    anomaly, lat, lon, title=f"{meta['label']} · Abweichung {label}",
                    subtitle="gegenüber 1991–2020",
                    unit="K" if key == "t850" else meta["unit"],
                    destination=images["anomaly"], cmap=meta["anomaly_cmap"],
                    bounds=meta["anomaly_bounds"],
                )
                render_map_webp(
                    rank, lat, lon, title=f"{meta['label']} · Rang {label}",
                    subtitle=f"{HISTORY_START}–{HISTORY_END} · {meta['rank_label']}",
                    unit="Rang 1–86", destination=images["rank"],
                    cmap="Spectral", vmin=1, vmax=len(EXPECTED_YEARS),
                )

                url_base = (
                    f"https://github.com/{REPO}/releases/download/"
                    f"era5-atmos-history-{year}-v1/"
                )
                period_products[key] = {
                    "label": meta["label"],
                    "short_label": meta["short_label"],
                    "unit": meta["unit"],
                    "level_hpa": int(meta["level"]) if "level" in meta else None,
                    "absolute": {"file": url_base + images["absolute"].name},
                    "anomaly": {
                        "file": url_base + images["anomaly"].name,
                        "reference_period": "1991–2020"
                    },
                    "rank": {
                        "file": url_base + images["rank"].name,
                        "history_start": HISTORY_START,
                        "history_end": HISTORY_END,
                        "comparison_years": len(EXPECTED_YEARS) - 1,
                        "total_rank_positions": len(EXPECTED_YEARS),
                        "direction": meta["rank_label"],
                        "rank1_area_percent": area_weighted_fraction(rank <= 1, valid, lat),
                        "top3_area_percent": area_weighted_fraction(rank <= 3, valid, lat),
                    },
                    "stats": {
                        "current_area_mean": area_weighted_mean(current, lat),
                        "reference_area_mean": area_weighted_mean(normal, lat),
                        "anomaly_area_mean": area_weighted_mean(anomaly, lat),
                    },
                }
                print(f"Rendered: {period} {key}", flush=True)

        periods[period] = {
            "ready": True,
            "period": period,
            "year": year,
            "month": month,
            "label": label,
            "products": period_products,
        }

    manifest = {
        "ready": True,
        "year": year,
        "history_start": HISTORY_START,
        "history_end": HISTORY_END,
        "reference_period": "1991–2020",
        "source": "ERA5 monthly means on pressure and single levels",
        "periods": periods,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    actual_images = list(output.glob("*.webp"))
    if len(actual_images) != 12 * len(PRODUCTS) * len(VIEWS):
        raise RuntimeError(f"Only {len(actual_images)} of 144 images ready")
    print(f"Historical year {year}: 144 WEBP maps verified", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="ERA5 atmospheric history 1940-2025")
    sub = parser.add_subparsers(dest="mode", required=True)
    ref = sub.add_parser("reference")
    ref.add_argument("--month", required=True, type=int)
    ref.add_argument("--output", required=True, type=Path)
    renderer = sub.add_parser("render")
    renderer.add_argument("--year", required=True, type=int)
    renderer.add_argument("--reference-dir", required=True, type=Path)
    renderer.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.mode == "reference":
        reference_month(args.month, args.output)
    else:
        render_year(args.year, args.reference_dir, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
