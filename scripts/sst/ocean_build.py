from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

from .config import ARCHIVE_START, OCEAN_REGIONS
from .manifest import VIEWS, archive_relpath, read_manifest, write_manifest_atomic
from .ocean_sources import download_oisst_daily_subset, download_oisst_normal_subset
from .processing import ProcessedFields, summarize_region_statistics, validate_scientific_fields
from .render import render_map, validate_rendered_map


@dataclass(frozen=True)
class OceanBuildResult:
    day: date
    already_present: bool
    built_regions: tuple[str, ...]
    file_count: int


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _standardize_dataset(dataset: xr.Dataset) -> xr.Dataset:
    rename = {}
    if "latitude" in dataset.dims or "latitude" in dataset.coords:
        rename["latitude"] = "lat"
    if "longitude" in dataset.dims or "longitude" in dataset.coords:
        rename["longitude"] = "lon"
    if rename:
        dataset = dataset.rename(rename)
    if "lat" not in dataset.coords or "lon" not in dataset.coords:
        raise RuntimeError(f"OISST-Datensatz ohne lat/lon: {dataset.dims}")
    lon = np.mod(np.asarray(dataset["lon"].values, dtype=float), 360.0)
    return dataset.assign_coords(lon=lon).sortby("lon").sortby("lat")


def _squeeze_spatial(array: xr.DataArray) -> xr.DataArray:
    result = array
    for dim in list(result.dims):
        if dim not in {"lat", "lon"} and result.sizes.get(dim) == 1:
            result = result.isel({dim: 0}, drop=True)
    return result


def _subset_field(field: xr.DataArray, region) -> xr.DataArray:
    subset = field.where((field["lon"] >= region.west) & (field["lon"] <= region.east), drop=True)
    subset = subset.where((subset["lat"] >= region.south) & (subset["lat"] <= region.north), drop=True)
    return subset


def _processed_fields(actual_dataset: xr.Dataset, normal_dataset: xr.Dataset, region) -> ProcessedFields:
    if "sst" not in actual_dataset or "sst" not in normal_dataset:
        raise RuntimeError("NOAA-OISST-Subset enthält die Variable sst nicht.")

    actual = _subset_field(_squeeze_spatial(actual_dataset["sst"]).astype(float), region)
    normal = _subset_field(_squeeze_spatial(normal_dataset["sst"]).astype(float), region)

    units = str(actual.attrs.get("units", "")).strip().lower()
    if units.startswith("k"):
        actual = actual - 273.15

    normal_units = str(normal.attrs.get("units", "")).strip().lower()
    if normal_units.startswith("k"):
        normal = normal - 273.15

    normal_hi = normal.interp(lat=actual["lat"], lon=actual["lon"], method="linear")
    valid_mask = np.isfinite(actual) & np.isfinite(normal_hi)
    absolute_c = actual.where(valid_mask)
    anomaly_c = (actual - normal_hi).where(valid_mask)

    return ProcessedFields(
        lon=absolute_c["lon"],
        lat=absolute_c["lat"],
        absolute_c=absolute_c,
        anomaly_c=anomaly_c,
        valid_mask=valid_mask,
        reference_method=str(normal_dataset.attrs.get("reference_method", "daily_normal")),
    )


def _region_meta(region) -> dict:
    return {
        "label": region.label,
        "bounds": [region.west, region.south, region.east, region.north],
        "width_px": region.width_px,
        "height_px": region.height_px,
        "source_id": region.source_id,
        "source_label": region.source_label,
    }


def _sync_manifest_metadata(manifest: dict) -> None:
    regions = manifest.setdefault("regions", {})
    for region_id, region in OCEAN_REGIONS.items():
        regions[region_id] = _region_meta(region)

    source = manifest.setdefault("source", {})
    source.setdefault("sst", "MUR-JPL-L4-GLOB-v4.1")
    source.setdefault("reference", "NOAA OISST 1991-2020")
    by_region = source.setdefault("by_region", {})
    for region_id in OCEAN_REGIONS:
        by_region[region_id] = "NOAA OISST v2.1"


def _region_complete(manifest: dict, day: date, archive_root: Path, region_id: str) -> bool:
    region = OCEAN_REGIONS[region_id]
    entry = manifest.get("dates", {}).get(day.isoformat())
    if not isinstance(entry, dict):
        return False
    region_outputs = entry.get("regions", {}).get(region_id)
    region_stats = entry.get("statistics", {}).get(region_id)
    if not isinstance(region_outputs, dict) or set(region_outputs) != set(VIEWS):
        return False
    if not isinstance(region_stats, dict) or set(region_stats) != set(VIEWS):
        return False
    try:
        for view in VIEWS:
            relpath = region_outputs.get(view)
            stats = region_stats.get(view)
            if not isinstance(relpath, str):
                return False
            if not isinstance(stats, dict) or set(stats) != {"mean", "min", "max"}:
                return False
            validate_rendered_map(archive_root / relpath, region)
    except (RuntimeError, OSError):
        return False
    return True


def build_ocean_date(
    day: date,
    archive_root: Path,
    cache_root: Path,
    *,
    region_ids: tuple[str, ...] | list[str] | None = None,
) -> OceanBuildResult:
    if day < ARCHIVE_START:
        raise ValueError(f"SST-Archiv beginnt am {ARCHIVE_START.isoformat()}.")

    archive_root = Path(archive_root)
    cache_root = Path(cache_root)
    requested = tuple(region_ids or OCEAN_REGIONS.keys())
    unknown = [region_id for region_id in requested if region_id not in OCEAN_REGIONS]
    if unknown:
        raise ValueError(f"Unbekannte Ozean-SST-Regionen: {unknown}")

    manifest_path = archive_root / "manifest.json"
    manifest = read_manifest(manifest_path)
    _sync_manifest_metadata(manifest)

    to_build = tuple(
        region_id
        for region_id in requested
        if not _region_complete(manifest, day, archive_root, region_id)
    )
    if not to_build:
        write_manifest_atomic(manifest_path, manifest)
        return OceanBuildResult(
            day=day,
            already_present=True,
            built_regions=(),
            file_count=0,
        )

    staging_parent = archive_root.parent if archive_root.parent.exists() else None
    with tempfile.TemporaryDirectory(prefix=f"sst-ocean-{day.isoformat()}-", dir=staging_parent) as tmp:
        staging = Path(tmp)
        source_dir = cache_root / "ocean_temp"
        source_dir.mkdir(parents=True, exist_ok=True)
        actual_path = source_dir / f"oisst_actual_{day.isoformat()}.nc"
        normal_path = source_dir / f"oisst_normal_{day.isoformat()}.nc"

        outputs: dict[str, dict[str, str]] = {}
        statistics: dict[str, dict] = {}
        reference_methods: dict[str, str] = {}

        try:
            download_oisst_daily_subset(day, actual_path)
            download_oisst_normal_subset(day, normal_path)

            with xr.open_dataset(actual_path) as actual_raw, xr.open_dataset(normal_path) as normal_raw:
                actual = _standardize_dataset(actual_raw.load())
                normal = _standardize_dataset(normal_raw.load())

            for region_id in to_build:
                region = OCEAN_REGIONS[region_id]
                fields = _processed_fields(actual, normal, region)
                validate_scientific_fields(fields)
                statistics[region_id] = summarize_region_statistics(fields, region)
                reference_methods[region_id] = fields.reference_method
                outputs[region_id] = {}
                for view in VIEWS:
                    relpath = archive_relpath(day, region_id, view)
                    staged_path = staging / relpath
                    render_map(fields, region, day, view, staged_path)
                    validate_rendered_map(staged_path, region)
                    outputs[region_id][view] = relpath

            staged_files = list(staging.rglob("*.webp"))
            expected = len(to_build) * len(VIEWS)
            if len(staged_files) != expected:
                raise RuntimeError(
                    f"Ozean-SST-Tagesbuild erzeugte {len(staged_files)} statt {expected} WebP-Dateien."
                )

            for region_id in to_build:
                for view in VIEWS:
                    relpath = outputs[region_id][view]
                    destination = archive_root / relpath
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(staging / relpath, destination)

            dates = manifest.setdefault("dates", {})
            day_key = day.isoformat()
            previous = dates.get(day_key, {}) if isinstance(dates.get(day_key), dict) else {}
            merged_regions = copy.deepcopy(previous.get("regions", {})) if isinstance(previous.get("regions"), dict) else {}
            merged_stats = copy.deepcopy(previous.get("statistics", {})) if isinstance(previous.get("statistics"), dict) else {}
            merged_refs = copy.deepcopy(previous.get("reference_methods", {})) if isinstance(previous.get("reference_methods"), dict) else {}

            merged_regions.update(copy.deepcopy(outputs))
            merged_stats.update(copy.deepcopy(statistics))
            merged_refs.update(reference_methods)

            dates[day_key] = {
                **{key: value for key, value in previous.items() if key not in {"regions", "statistics", "reference_methods"}},
                "reference_method": previous.get("reference_method") or next(iter(reference_methods.values()), "daily_normal"),
                "reference_methods": merged_refs,
                "regions": merged_regions,
                "statistics": merged_stats,
            }

            available = sorted(set(manifest.get("available_dates", [])) | {day_key})
            manifest["available_dates"] = available
            manifest["data_through"] = available[-1] if available else None
            manifest["generated_at"] = _generated_at()
            write_manifest_atomic(manifest_path, manifest)

            return OceanBuildResult(
                day=day,
                already_present=False,
                built_regions=to_build,
                file_count=expected,
            )
        finally:
            actual_path.unlink(missing_ok=True)
            normal_path.unlink(missing_ok=True)
