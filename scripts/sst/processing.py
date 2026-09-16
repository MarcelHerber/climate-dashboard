from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import xarray as xr

from .climatology import regrid_normal, select_daily_normal
from .config import SEA_ICE_THRESHOLD


@dataclass(frozen=True)
class ProcessedFields:
    lon: xr.DataArray
    lat: xr.DataArray
    absolute_c: xr.DataArray
    anomaly_c: xr.DataArray
    valid_mask: xr.DataArray
    reference_method: str


def _squeeze_time(array: xr.DataArray) -> xr.DataArray:
    result = array
    for dim in list(result.dims):
        if dim not in {"lat", "lon"} and result.sizes.get(dim) == 1:
            result = result.isel({dim: 0}, drop=True)
    return result


def process_mur_region(mur: xr.Dataset, normals: xr.Dataset, day: date) -> ProcessedFields:
    if "analysed_sst" not in mur:
        raise RuntimeError("MUR-Datei enthält analysed_sst nicht.")
    mur_sst = _squeeze_time(mur["analysed_sst"])
    units = str(mur_sst.attrs.get("units", "")).strip().lower()
    if units.startswith("k"):
        mur_sst_c = mur_sst.astype(float) - 273.15
    else:
        mur_sst_c = mur_sst.astype(float)

    absolute_c = mur_sst_c.where(np.isfinite(mur_sst_c))
    if "sea_ice_fraction" in mur:
        ice = _squeeze_time(mur["sea_ice_fraction"])
        ice_ok = (ice < SEA_ICE_THRESHOLD) | ice.isnull()
    else:
        ice_ok = xr.ones_like(absolute_c, dtype=bool)

    valid_mask = np.isfinite(absolute_c) & ice_ok
    normal, reference_method = select_daily_normal(normals, day)
    normal_hi = regrid_normal(normal, absolute_c["lat"], absolute_c["lon"])
    anomaly_c = (absolute_c - normal_hi).where(valid_mask)
    absolute_c = absolute_c.where(valid_mask)

    return ProcessedFields(
        lon=absolute_c["lon"],
        lat=absolute_c["lat"],
        absolute_c=absolute_c,
        anomaly_c=anomaly_c,
        valid_mask=valid_mask,
        reference_method=reference_method,
    )


def validate_scientific_fields(fields: ProcessedFields) -> None:
    absolute = np.asarray(fields.absolute_c.values, dtype=float)
    anomaly = np.asarray(fields.anomaly_c.values, dtype=float)
    valid_absolute = absolute[np.isfinite(absolute)]
    valid_anomaly = anomaly[np.isfinite(anomaly)]

    if valid_absolute.size == 0:
        raise RuntimeError("Keine gültigen Ozeanpixel in der Region.")
    minimum = float(valid_absolute.min())
    maximum = float(valid_absolute.max())
    if minimum < -3.0:
        raise RuntimeError(f"Unplausible SST unter -3 °C: {minimum:.2f}")
    if maximum > 40.0:
        raise RuntimeError(f"Unplausible SST über 40 °C: {maximum:.2f}")
    if valid_anomaly.size == 0:
        raise RuntimeError("Keine endlichen SST-Anomalien in der Region.")
    anomaly_max = float(np.max(np.abs(valid_anomaly)))
    if anomaly_max > 20.0:
        raise RuntimeError(f"Unplausible SST-Anomalie über 20 °C: {anomaly_max:.2f}")
