#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from calendar import isleap
from datetime import date
from pathlib import Path

import numpy as np
import xarray as xr

try:
    from build_hyras_temperature_rank_shard import _source_module, _unpack_prepared
    from hyras_temperature_rank import (
        MISSING_I16,
        TEMPERATURE_SCALE,
        quantize_temperature,
    )
except ModuleNotFoundError:
    from scripts.build_hyras_temperature_rank_shard import _source_module, _unpack_prepared
    from scripts.hyras_temperature_rank import (
        MISSING_I16,
        TEMPERATURE_SCALE,
        quantize_temperature,
    )

ARCHIVE_TAG = "hyras-daily-archive-1km"
ARCHIVE_SCHEMA_VERSION = 1
RESOLUTION_KM = 1
PARAMETERS = ("tmean", "tmax", "tmin")
PARAM_LABELS = {
    "tmean": "2-m-Temperaturmittel",
    "tmax": "2-m-Tagesmaximum",
    "tmin": "2-m-Tagesminimum",
}


def _grid_signature(x: np.ndarray, y: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(np.asarray(x, dtype="<f8").tobytes())
    h.update(np.asarray(y, dtype="<f8").tobytes())
    return h.hexdigest()[:20]


def _dates_for_year(times: np.ndarray, year: int) -> tuple[np.ndarray, np.ndarray]:
    dates = np.asarray(times).astype("datetime64[D]")
    start = np.datetime64(f"{year:04d}-01-01")
    stop = np.datetime64(f"{year + 1:04d}-01-01")
    indices = np.flatnonzero((dates >= start) & (dates < stop))
    return indices, dates[indices]


def _validate_dates(dates: np.ndarray, year: int, *, require_complete: bool) -> None:
    dates = np.asarray(dates).astype("datetime64[D]")
    if dates.size == 0:
        raise RuntimeError(f"HYRAS {year}: keine Tagesdaten gefunden")

    expected_start = np.datetime64(f"{year:04d}-01-01")
    if dates[0] != expected_start:
        raise RuntimeError(
            f"HYRAS {year}: Zeitreihe beginnt am {dates[0]} statt am {expected_start}"
        )

    unique = np.unique(dates)
    if unique.size != dates.size:
        raise RuntimeError(f"HYRAS {year}: doppelte Kalendertage in der Tagesdatei")

    if dates.size > 1:
        gaps = np.diff(dates).astype("timedelta64[D]").astype(int)
        if np.any(gaps != 1):
            bad = int(np.flatnonzero(gaps != 1)[0])
            raise RuntimeError(
                f"HYRAS {year}: Lücke zwischen {dates[bad]} und {dates[bad + 1]}"
            )

    if require_complete:
        expected_days = 366 if isleap(year) else 365
        expected_end = np.datetime64(f"{year:04d}-12-31")
        if dates.size != expected_days or dates[-1] != expected_end:
            raise RuntimeError(
                f"HYRAS {year}: Jahr unvollständig ({dates.size}/{expected_days} Tage, "
                f"letzter Tag {dates[-1]})"
            )


def _archive_filename(parameter: str, year: int) -> str:
    return f"hyras-{parameter}-{year}-1km.npz"


def _manifest_filename(parameter: str, year: int) -> str:
    return f"hyras-{parameter}-{year}-1km.json"


def _release_url(repository: str, filename: str) -> str | None:
    repository = repository.strip()
    if not repository:
        return None
    return f"https://github.com/{repository}/releases/download/{ARCHIVE_TAG}/{filename}"


def _source_file(module, year: int) -> str:
    files = module.latest_daily_files(module.daily_listing())
    filename = files.get(year)
    if not filename:
        raise RuntimeError(f"HYRAS: Tagesdatei für {year} fehlt")
    return filename


def build_archive(
    *,
    parameter: str,
    year: int,
    output_dir: Path,
    work: Path,
    repository: str = "",
) -> dict:
    if parameter not in PARAMETERS:
        raise ValueError(f"Unbekannter Parameter: {parameter}")
    if year < 1951:
        raise ValueError("HYRAS-Temperaturarchiv beginnt 1951")

    module = _source_module(parameter)
    filename = _source_file(module, year)
    source_url = f"{module.DAILY_BASE}/{filename}"
    work.mkdir(parents=True, exist_ok=True)
    nc_path = work / filename
    if not nc_path.exists():
        module.download(source_url, nc_path)

    with xr.open_dataset(nc_path, decode_times=True) as ds:
        da, td, ydim, xdim, x, y = _unpack_prepared(module, ds)
        indices, dates = _dates_for_year(np.asarray(da[td].values), year)
        require_complete = year < date.today().year
        _validate_dates(dates, year, require_complete=require_complete)

        sampled = da.isel({td: indices, ydim: slice(None), xdim: slice(None)})
        values = np.asarray(sampled.values, dtype=np.float32)
        values[~np.isfinite(values)] = np.nan

    packed = np.asarray(quantize_temperature(values), dtype="<i2")
    del values

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = _archive_filename(parameter, year)
    archive_path = output_dir / archive_name
    np.savez_compressed(
        archive_path,
        schema_version=np.asarray(ARCHIVE_SCHEMA_VERSION, dtype=np.int16),
        parameter=np.asarray(parameter),
        year=np.asarray(year, dtype=np.int16),
        resolution_km=np.asarray(RESOLUTION_KM, dtype=np.int16),
        value_scale=np.asarray(TEMPERATURE_SCALE, dtype=np.int16),
        missing_value=np.asarray(MISSING_I16, dtype=np.int16),
        date_codes=np.asarray(
            [int(str(value)[5:7]) * 100 + int(str(value)[8:10]) for value in dates],
            dtype=np.uint16,
        ),
        x=np.asarray(x, dtype=np.float64),
        y=np.asarray(y, dtype=np.float64),
        values=np.asarray(packed, dtype=np.int16),
    )

    digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    complete_year = str(dates[-1]) == f"{year:04d}-12-31"
    manifest = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "parameter": parameter,
        "label": PARAM_LABELS[parameter],
        "unit": "°C",
        "year": year,
        "resolution_km": RESOLUTION_KM,
        "width": int(x.size),
        "height": int(y.size),
        "days": int(dates.size),
        "first_date": str(dates[0]),
        "data_through": str(dates[-1]),
        "complete_year": complete_year,
        "grid_signature": _grid_signature(x, y),
        "value_scale": TEMPERATURE_SCALE,
        "missing_value": MISSING_I16,
        "dtype": "int16",
        "endianness": "little",
        "array_order": "time,y,x",
        "date_encoding": "MMDD uint16 in date_codes; year stored separately",
        "archive_file": archive_name,
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": digest.hexdigest(),
        "release_tag": ARCHIVE_TAG,
        "release_asset_url": _release_url(repository, archive_name),
        "source_file": filename,
        "source_url": source_url,
        "note": (
            "Native HYRAS-DE 1-km daily temperature grid, quantized to 0.01 °C. "
            "No spatial downsampling is applied."
        ),
    }
    manifest_path = output_dir / _manifest_filename(parameter, year)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    nc_path.unlink(missing_ok=True)
    print(
        f"HYRAS-Tagesarchiv fertig: {parameter} {year} · {dates.size} Tage · "
        f"{y.size}×{x.size} · {archive_path.stat().st_size / 1024 / 1024:.1f} MB",
        flush=True,
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parameter", choices=PARAMETERS, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--work", default="/tmp/hyras-daily-archive-work")
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="owner/repo für die öffentliche Release-Asset-URL",
    )
    args = parser.parse_args()

    build_archive(
        parameter=args.parameter,
        year=args.year,
        output_dir=Path(args.output_dir),
        work=Path(args.work) / args.parameter / str(args.year),
        repository=args.repository,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
