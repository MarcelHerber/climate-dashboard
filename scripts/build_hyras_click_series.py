#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import numpy as np
from PIL import Image

SCHEMA_VERSION = 1
MISSING_U16 = 65535
VALUE_SCALE = 10  # 0.1 mm


def decode_precip_png(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Decode HYRAS RGB precipitation PNG (tenths of mm + alpha mask)."""
    rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)
    q = (
        rgba[..., 0].astype(np.uint32) * 65536
        + rgba[..., 1].astype(np.uint32) * 256
        + rgba[..., 2].astype(np.uint32)
    )
    valid = rgba[..., 3] > 0
    return q, valid


def expected_pack_bytes(year_count: int, height: int, width: int) -> int:
    return year_count * height * width * 2


def gzip_uncompressed_size(path: Path) -> int | None:
    """Read gzip ISIZE (mod 2^32); packs here are far below 4 GiB."""
    try:
        with path.open("rb") as f:
            f.seek(-4, 2)
            return int.from_bytes(f.read(4), "little")
    except OSError:
        return None


def package_complete(root: Path, manifest: dict, years: list[int], factor: int) -> bool:
    if not manifest:
        return False
    if manifest.get("schema_version") != SCHEMA_VERSION:
        return False
    if manifest.get("years") != years or int(manifest.get("factor", 0)) != factor:
        return False
    width = int(manifest.get("width", 0))
    height = int(manifest.get("height", 0))
    if width <= 0 or height <= 0:
        return False
    expected = expected_pack_bytes(len(years), height, width)
    for month in range(1, 13):
        path = root / f"month_{month:02d}.u16.gz"
        if not path.exists() or gzip_uncompressed_size(path) != expected:
            return False
    return True


def build(data_root: Path, factor: int) -> dict:
    historical_manifest_path = data_root / "hyras_historical_manifest.json"
    if not historical_manifest_path.exists():
        raise RuntimeError(f"Historisches HYRAS-Manifest fehlt: {historical_manifest_path}")
    historical = json.loads(historical_manifest_path.read_text(encoding="utf-8"))
    years = [int(y) for y in historical.get("years", [])]
    if not years:
        raise RuntimeError("Historisches HYRAS-Manifest enthält keine Jahre")

    first_path = data_root / "historical_1km" / str(years[0]) / "month_01.png"
    if not first_path.exists():
        raise RuntimeError(f"Erstes historisches Monatsraster fehlt: {first_path}")
    first_q, _first_valid = decode_precip_png(first_path)
    source_height, source_width = first_q.shape
    row_idx = np.arange(0, source_height, factor, dtype=np.int32)
    col_idx = np.arange(0, source_width, factor, dtype=np.int32)
    height, width = len(row_idx), len(col_idx)

    root = data_root / f"click_series_{factor}km"
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    existing = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    if package_complete(root, existing, years, factor):
        print(
            f"HYRAS Klick-Zeitreihen bereits vollständig: {years[0]}–{years[-1]} · "
            f"{factor} km · {width}×{height}."
        )
        return existing

    print(
        f"Baue HYRAS Klick-Zeitreihen {years[0]}–{years[-1]} auf {factor}-km-Raster "
        f"({width}×{height}; Quelle {source_width}×{source_height})."
    )

    for month in range(1, 13):
        cube = np.full((len(years), height, width), MISSING_U16, dtype="<u2")
        for pos, year in enumerate(years):
            path = data_root / "historical_1km" / str(year) / f"month_{month:02d}.png"
            if not path.exists():
                raise RuntimeError(f"Historisches HYRAS-Raster fehlt: {path}")
            q, valid = decode_precip_png(path)
            if q.shape != (source_height, source_width):
                raise RuntimeError(
                    f"Rastergröße von {path} ist {q.shape}, erwartet {(source_height, source_width)}"
                )
            sampled_q = q[np.ix_(row_idx, col_idx)]
            sampled_valid = valid[np.ix_(row_idx, col_idx)]
            # Monthly precipitation in Germany is safely within uint16 tenths of mm.
            too_large = sampled_valid & (sampled_q >= MISSING_U16)
            if np.any(too_large):
                count = int(np.count_nonzero(too_large))
                raise RuntimeError(
                    f"{path}: {count} Werte überschreiten den uint16-Bereich des Klick-Archivs"
                )
            layer = cube[pos]
            layer[sampled_valid] = sampled_q[sampled_valid].astype(np.uint16)
            if (pos + 1) % 20 == 0 or pos + 1 == len(years):
                print(f"  Monat {month:02d}: {pos + 1}/{len(years)} Jahre")

        target = root / f"month_{month:02d}.u16.gz"
        with gzip.open(target, "wb", compresslevel=6) as gz:
            gz.write(cube.tobytes(order="C"))
        print(f"  -> {target.name}: {target.stat().st_size / 1024 / 1024:.2f} MB")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "product": "DWD HYRAS-DE-PR click time series",
        "first_year": years[0],
        "last_year": years[-1],
        "years": years,
        "factor": factor,
        "resolution_km": factor,
        "source_resolution_km": int(historical.get("web_sampling_km", 1) or 1),
        "source_width": source_width,
        "source_height": source_height,
        "width": width,
        "height": height,
        "value_scale": VALUE_SCALE,
        "missing_value": MISSING_U16,
        "dtype": "uint16",
        "endianness": "little",
        "layout": "year,row,column",
        "file_pattern": f"click_series_{factor}km/month_{{month}}.u16.gz",
        "reference": "1991-2020",
        "note": (
            "Monatliche HYRAS-Niederschlagssummen seit 1931 auf jedem fünften 1-km-Rasterpunkt. "
            "Die sichtbaren Karten bleiben hochaufgelöst; dieses kompakte Raster dient nur der "
            "Klick-Zeitreihe und historischen Rangberechnung."
        ),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(
        f"HYRAS Klick-Zeitreihenpaket bereit: {years[0]}–{years[-1]} · "
        f"12 Monats-Packs · {factor} km."
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="hyras_output")
    parser.add_argument("--factor", type=int, default=5)
    args = parser.parse_args()
    if args.factor < 1:
        raise SystemExit("--factor muss >= 1 sein")
    build(Path(args.data_root), args.factor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
