from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import xarray as xr

from .climatology import regrid_normal, select_daily_normal
from .config import SEA_ICE_THRESHOLD, Region


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


def _visible_region_field(field: xr.DataArray, region: Region) -> xr.DataArray:
    visible = field.where((field["lon"] >= region.west) & (field["lon"] <= region.east), drop=True)
    visible = visible.where((visible["lat"] >= region.south) & (visible["lat"] <= region.north), drop=True)
    return visible


def _field_statistics(field: xr.DataArray, region: Region) -> dict[str, float]:
    visible = _visible_region_field(field, region)
    values = np.asarray(visible.values, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise RuntimeError(f"Keine gültigen SST-Werte im sichtbaren Ausschnitt {region.id}.")

    latitude_weights = xr.DataArray(
        np.cos(np.deg2rad(visible["lat"].astype(float))),
        coords={"lat": visible["lat"]},
        dims=("lat",),
    )
    mean = float(visible.weighted(latitude_weights).mean(skipna=True).item())
    return {
        "mean": mean,
        "min": float(np.nanmin(values)),
        "max": float(np.nanmax(values)),
    }


def summarize_region_statistics(fields: ProcessedFields, region: Region) -> dict[str, dict[str, float]]:
    return {
        "absolute": _field_statistics(fields.absolute_c, region),
        "anomaly": _field_statistics(fields.anomaly_c, region),
    }


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
    abs_anomaly = np.abs(valid_anomaly)
    anomaly_max = float(np.max(abs_anomaly))
    anomaly_p999 = float(np.percentile(abs_anomaly, 99.9))

    # Einzelne Küsten-/Regridding-Randpixel können bei MUR (1 km) gegen die
    # gröbere OISST-Klimatologie lokal knapp über 20 °C Abweichung erreichen.
    # Solche Pixel sollen einen kompletten Tagesbuild nicht stoppen. Weiterhin
    # hart abbrechen bei extremen Einzelwerten oder wenn >0,1 % des Feldes
    # bereits jenseits von 20 °C liegen.
    if anomaly_max > 30.0:
        raise RuntimeError(f"Unplausible SST-Anomalie über 30 °C: {anomaly_max:.2f}")
    if anomaly_p999 > 20.0:
        raise RuntimeError(
            f"Flächig unplausible SST-Anomalie: 99,9%-Perzentil {anomaly_p999:.2f} °C "
            f"(Maximum {anomaly_max:.2f} °C)"
        )
