#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cdsapi
import numpy as np
import xarray as xr

DATASET = "reanalysis-era5-pressure-levels-monthly-means"
REFERENCE_START = 1991
REFERENCE_END = 2020
PRESSURE_LEVEL = "850"
HOURS = [0, 6, 12, 18]
AREA = [80.0, -40.0, 20.0, 50.0]
GRID = [1.0, 1.0]


def retrieve(target: Path) -> None:
    client = cdsapi.Client(quiet=False, progress=False)
    request = {
        "product_type": ["monthly_averaged_reanalysis_by_hour_of_day"],
        "variable": ["temperature"],
        "pressure_level": [PRESSURE_LEVEL],
        "year": [f"{year:04d}" for year in range(REFERENCE_START, REFERENCE_END + 1)],
        "month": [f"{month:02d}" for month in range(1, 13)],
        "time": [f"{hour:02d}:00" for hour in HOURS],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA,
        "grid": GRID,
    }
    print(
        f"CDS: ERA5 T850 {REFERENCE_START}–{REFERENCE_END}, "
        f"00/06/12/18 UTC, {GRID[0]:.1f}° Raster",
        flush=True,
    )
    client.retrieve(DATASET, request, str(target))


def find_name(container, candidates: tuple[str, ...]) -> str:
    lower = {str(name).lower(): str(name) for name in container}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    raise RuntimeError(f"Nicht gefunden: {candidates}; vorhanden: {list(container)[:20]}")


def find_time_name(ds: xr.Dataset, da: xr.DataArray) -> str:
    for candidate in ("valid_time", "time", "date"):
        if candidate in da.coords or candidate in ds.coords:
            return candidate
    for name in da.dims:
        coord = da.coords.get(name)
        if coord is not None and np.issubdtype(coord.dtype, np.datetime64):
            return str(name)
    raise RuntimeError(f"Keine Zeitdimension gefunden. Dimensionen: {da.dims}")


def timestamp_parts(value) -> tuple[int, int, int]:
    text = np.datetime_as_string(np.datetime64(value), unit="m")
    date_part, time_part = text.split("T", 1)
    year, month, _day = [int(piece) for piece in date_part.split("-")]
    return year, month, int(time_part[:2])


def build_payload(path: Path) -> dict:
    ds = xr.open_dataset(path)
    try:
        temp_name = find_name(ds.variables, ("t", "temperature"))
        lat_name = find_name(ds.coords, ("latitude", "lat"))
        lon_name = find_name(ds.coords, ("longitude", "lon"))
        da = ds[temp_name]
        time_name = find_time_name(ds, da)

        for dim in list(da.dims):
            if dim not in {time_name, lat_name, lon_name} and da.sizes.get(dim, 0) == 1:
                da = da.isel({dim: 0}, drop=True)

        extra = [dim for dim in da.dims if dim not in {time_name, lat_name, lon_name}]
        if extra:
            raise RuntimeError(f"Unerwartete Dimensionen: {extra}")

        da = da.transpose(time_name, lat_name, lon_name).sortby(lat_name).sortby(lon_name)
        lat = np.asarray(da[lat_name].values, dtype=float)
        lon = np.asarray(da[lon_name].values, dtype=float)
        if lat.ndim != 1 or lon.ndim != 1:
            raise RuntimeError("ERA5-Raster ist nicht eindimensional.")

        step_lat = float(np.median(np.diff(lat)))
        step_lon = float(np.median(np.diff(lon)))
        if not (0.9 <= step_lat <= 1.1 and 0.9 <= step_lon <= 1.1):
            raise RuntimeError(f"Unerwartete Rasterweite: lat={step_lat}, lon={step_lon}")

        sums = np.zeros((lat.size, lon.size, 12, len(HOURS)), dtype=np.float64)
        counts = np.zeros((12, len(HOURS)), dtype=np.int16)

        for index, stamp in enumerate(np.asarray(da[time_name].values)):
            year, month, hour = timestamp_parts(stamp)
            if not (REFERENCE_START <= year <= REFERENCE_END) or hour not in HOURS:
                continue
            hi = HOURS.index(hour)
            field = np.asarray(da.isel({time_name: index}).values, dtype=np.float64) - 273.15
            if field.shape != (lat.size, lon.size):
                raise RuntimeError(f"Falsche Feldform: {field.shape}")
            if not np.isfinite(field).all():
                raise RuntimeError(f"Nicht-endliche ERA5-Werte bei {stamp}")
            sums[:, :, month - 1, hi] += field
            counts[month - 1, hi] += 1

        expected = REFERENCE_END - REFERENCE_START + 1
        bad = np.argwhere(counts != expected)
        if bad.size:
            details = [f"M{m+1:02d}/{HOURS[h]:02d}Z={counts[m,h]}" for m, h in bad[:12]]
            raise RuntimeError("Unvollständige ERA5-Klimatologie: " + ", ".join(details))

        values = np.round(sums / counts[None, None, :, :], 2).astype(np.float32)
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "ERA5 monthly averaged data on pressure levels",
            "dataset": DATASET,
            "variable": "temperature",
            "pressure_level_hpa": 850,
            "reference_period": "1991-2020",
            "product_type": "monthly_averaged_reanalysis_by_hour_of_day",
            "method": "30-year mean of synoptic monthly T850 values; browser linearly interpolates between mid-month anchors",
            "hours": HOURS,
            "months": list(range(1, 13)),
            "grid": {
                "lat_min": round(float(lat[0]), 6),
                "lat_max": round(float(lat[-1]), 6),
                "lon_min": round(float(lon[0]), 6),
                "lon_max": round(float(lon[-1]), 6),
                "step": round(float((step_lat + step_lon) / 2), 6),
                "nlat": int(lat.size),
                "nlon": int(lon.size),
            },
            "flatten_order": "latitude,longitude,month,hour",
            "values": values.reshape(-1).tolist(),
        }
    finally:
        ds.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("t850_climatology_1991_2020.json"))
    parser.add_argument("--input", type=Path, help="Vorhandene NetCDF-Datei statt CDS-Download verwenden")
    args = parser.parse_args()

    if args.input:
        if not args.input.is_file():
            raise SystemExit(f"Eingabedatei fehlt: {args.input}")
        payload = build_payload(args.input)
    else:
        with tempfile.TemporaryDirectory(prefix="t850-era5-") as tmp:
            source = Path(tmp) / "era5_t850_monthly_synoptic.nc"
            retrieve(source)
            payload = build_payload(source)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"Fertig: {args.output} · Raster {payload['grid']['nlat']} × {payload['grid']['nlon']} · "
        f"{len(payload['values']):,} Klimawerte",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
