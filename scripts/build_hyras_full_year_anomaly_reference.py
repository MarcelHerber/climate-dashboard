#!/usr/bin/env python3
"""Calendar-year HYRAS daily climatology from 1961–1990 and 1991–2020."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import hashlib
import json

import numpy as np
import requests

try:
    from hyras_temperature_rank import dequantize_temperature
except ModuleNotFoundError:
    from scripts.hyras_temperature_rank import dequantize_temperature

REFERENCES = (("1961-1990", 1961, 1990), ("1991-2020", 1991, 2020))


def calendar_codes() -> np.ndarray:
    """366 calendar codes, including 29 February, in a fixed leap-year axis."""
    start = date(2000, 1, 1)
    return np.asarray(
        [(start + timedelta(days=offset)).month * 100
         + (start + timedelta(days=offset)).day for offset in range(366)],
        dtype=np.uint16,
    )


def reference_index(year: int) -> int:
    for index, (_, beginning, end) in enumerate(REFERENCES):
        if beginning <= year <= end:
            return index
    raise ValueError(f"Year outside climatology: {year}")


def day_codes(times: np.ndarray) -> np.ndarray:
    values = np.asarray(times).astype("datetime64[D]").astype(str)
    return np.asarray([int(v[5:7]) * 100 + int(v[8:10]) for v in values], dtype=np.uint16)


def build_contribution(*, parameter: str, start_year: int, end_year: int,
                       display_factor: int, cache_root: Path, work: Path,
                       output: Path) -> None:
    if display_factor < 1:
        raise ValueError("display_factor must be positive")
    # Re-use published, checksummed native 1-km daily archives instead of
    # transferring the larger DWD source NetCDF files for all 60 reference years.
    index_file = cache_root / "daily_archive_index.json"
    cache_root.mkdir(parents=True, exist_ok=True)
    if not index_file.exists():
        index_url = (
            "https://raw.githubusercontent.com/MarcelHerber/"
            "climate-dashboard/hyras-data/daily_archive_1km/index.json"
        )
        response = requests.get(index_url, timeout=120)
        response.raise_for_status()
        index_file.write_bytes(response.content)
    index = json.loads(index_file.read_text(encoding="utf-8"))
    archives = index["parameters"][parameter]
    codes = calendar_codes()
    lookup = {int(code): i for i, code in enumerate(codes)}
    ref_x = ref_y = sums = counts = None
    used_years = []

    for year in range(start_year, end_year + 1):
        which = reference_index(year)
        meta = archives.get(str(year))
        if not meta or not meta.get("complete_year"):
            raise RuntimeError(f"HYRAS {parameter} {year}: complete release archive missing")
        work.mkdir(parents=True, exist_ok=True)
        archive = work / meta["archive_file"]
        if not archive.exists():
            response = requests.get(meta["release_asset_url"], stream=True, timeout=(30, 480))
            response.raise_for_status()
            with archive.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != meta["archive_sha256"]:
            raise RuntimeError(f"HYRAS {parameter} {year}: archive SHA-256 mismatch")
        try:
            with np.load(archive, allow_pickle=False) as data:
                days = np.asarray(data["date_codes"], dtype=np.uint16)
                x = np.asarray(data["x"], dtype=np.float64)
                y = np.asarray(data["y"], dtype=np.float64)
                # Crop after decompression. The file is 1 km; output uses 5 km.
                packed = np.asarray(
                    data["values"][:, ::display_factor, ::display_factor],
                    dtype=np.int16,
                )
                values = dequantize_temperature(packed)
            start = np.datetime64(f"{year}-01-01")
            stop = np.datetime64(f"{year + 1}-01-01")
            expected = day_codes(np.arange(start, stop, dtype="datetime64[D]"))
            if not np.array_equal(days, expected):
                raise RuntimeError(f"HYRAS {parameter} {year}: missing or duplicate days")
            sx = x[::display_factor]
            sy = y[::display_factor]
            if values.shape != (len(days), len(sy), len(sx)):
                raise RuntimeError(f"HYRAS {parameter} {year}: invalid archive raster shape")
            if sums is None:
                ref_x, ref_y = sx, sy
                shape = (2, len(codes), len(sy), len(sx))
                sums = np.zeros(shape, dtype=np.float64)
                counts = np.zeros(shape, dtype=np.uint8)
            elif (sx.shape != ref_x.shape or sy.shape != ref_y.shape
                  or not np.allclose(sx, ref_x) or not np.allclose(sy, ref_y)):
                raise RuntimeError(f"HYRAS {parameter} {year}: grid changed")
            for i, code in enumerate(days):
                layer = values[i]
                valid = np.isfinite(layer)
                pos = lookup[int(code)]
                sums[which, pos] += np.where(valid, layer, 0.0)
                counts[which, pos] += valid.astype(np.uint8)
            used_years.append(year)
        finally:
            archive.unlink(missing_ok=True)
        print(f"{parameter}: checked release climatology {year}", flush=True)

    if sums is None or counts is None or ref_x is None or ref_y is None:
        raise RuntimeError("Empty daily reference shard")
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        parameter=np.asarray(parameter),
        years=np.asarray(used_years, dtype=np.int16),
        references=np.asarray([item[0] for item in REFERENCES]),
        date_codes=codes,
        x=ref_x,
        y=ref_y,
        display_factor=np.asarray(display_factor, dtype=np.int16),
        sums=sums.astype(np.float32),
        counts=counts,
        calendar_version=np.asarray(2, dtype=np.int16),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parameter", required=True, choices=("tmean", "tmax", "tmin"))
    parser.add_argument("--start-year", required=True, type=int)
    parser.add_argument("--end-year", required=True, type=int)
    parser.add_argument("--display-factor", type=int, default=5)
    parser.add_argument("--cache-root", type=Path, default=Path("/tmp/hyras-full-year-cache"))
    parser.add_argument("--work", type=Path, default=Path("/tmp/hyras-full-year-work"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_contribution(
        parameter=args.parameter, start_year=args.start_year,
        end_year=args.end_year, display_factor=args.display_factor,
        cache_root=args.cache_root, work=args.work / args.parameter,
        output=args.output,
    )


if __name__ == "__main__":
    main()
