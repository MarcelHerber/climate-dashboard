from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import xarray as xr

from .config import ARCHIVE_START, REGIONS, Region
from .manifest import VIEWS, archive_relpath, read_manifest, register_date, write_manifest_atomic
from .processing import (
    process_mur_region,
    summarize_region_statistics,
    validate_scientific_fields,
)
from .render import render_map, validate_rendered_map
from .sources import download_mur_subset, ensure_oisst_daily_normals


@dataclass(frozen=True)
class BuildResult:
    day: date
    already_present: bool
    file_count: int
    reference_method: str | None


class NetworkSourceAdapter:
    def __init__(self, cache_root: Path, token: str):
        self.cache_root = cache_root
        self.token = token
        self._normal_path: Path | None = None

    def fetch_mur(self, day: date, region: Region, path: Path) -> Path:
        return download_mur_subset(day, region, path, self.token)

    def normal_dataset(self) -> xr.Dataset:
        if self._normal_path is None:
            self._normal_path = ensure_oisst_daily_normals(self.cache_root)
        return xr.open_dataset(self._normal_path, decode_times=False)


def _expected_file_count() -> int:
    return len(REGIONS) * len(VIEWS)


def _date_is_complete(manifest: dict, day: date, archive_root: Path) -> bool:
    entry = manifest.get("dates", {}).get(day.isoformat())
    if not isinstance(entry, dict):
        return False
    regions = entry.get("regions")
    if not isinstance(regions, dict) or set(regions) != set(REGIONS):
        return False
    statistics = entry.get("statistics")
    if not isinstance(statistics, dict) or set(statistics) != set(REGIONS):
        return False
    try:
        for region_id, region in REGIONS.items():
            view_paths = regions.get(region_id)
            if not isinstance(view_paths, dict) or set(view_paths) != set(VIEWS):
                return False
            region_stats = statistics.get(region_id)
            if not isinstance(region_stats, dict) or set(region_stats) != set(VIEWS):
                return False
            for view in VIEWS:
                relpath = view_paths.get(view)
                if not isinstance(relpath, str):
                    return False
                stats = region_stats.get(view)
                if not isinstance(stats, dict) or set(stats) != {"mean", "min", "max"}:
                    return False
                validate_rendered_map(archive_root / relpath, region)
    except (RuntimeError, OSError):
        return False
    return True


def build_date(
    day: date,
    archive_root: Path,
    cache_root: Path,
    earthdata_token: str,
    *,
    source_adapter=None,
) -> BuildResult:
    if day < ARCHIVE_START:
        raise ValueError(f"SST-Archiv beginnt am {ARCHIVE_START.isoformat()}.")

    expected_file_count = _expected_file_count()
    archive_root = Path(archive_root)
    cache_root = Path(cache_root)
    manifest_path = archive_root / "manifest.json"
    manifest = read_manifest(manifest_path)
    if _date_is_complete(manifest, day, archive_root):
        return BuildResult(
            day=day,
            already_present=True,
            file_count=expected_file_count,
            reference_method=manifest["dates"][day.isoformat()].get("reference_method"),
        )

    adapter = source_adapter or NetworkSourceAdapter(cache_root, earthdata_token)
    staging_parent = archive_root.parent if archive_root.parent.exists() else None
    with tempfile.TemporaryDirectory(prefix=f"sst-{day.isoformat()}-", dir=staging_parent) as tmp:
        staging = Path(tmp)
        mur_cache = cache_root / "mur_temp"
        mur_cache.mkdir(parents=True, exist_ok=True)
        outputs: dict[str, dict[str, str]] = {}
        statistics: dict[str, dict] = {}
        reference_method: str | None = None
        normals = adapter.normal_dataset()
        close_normals = getattr(normals, "close", None)
        try:
            for region_id, region in REGIONS.items():
                mur_path = mur_cache / f"mur_{day.isoformat()}_{region_id}.nc"
                try:
                    adapter.fetch_mur(day, region, mur_path)
                    with xr.open_dataset(mur_path) as mur:
                        fields = process_mur_region(mur, normals, day)
                        validate_scientific_fields(fields)
                        statistics[region_id] = summarize_region_statistics(fields, region)
                        if reference_method is None:
                            reference_method = fields.reference_method
                        elif reference_method != fields.reference_method:
                            raise RuntimeError("Uneinheitliche Referenzmethode zwischen SST-Regionen.")
                        outputs[region_id] = {}
                        for view in VIEWS:
                            relpath = archive_relpath(day, region_id, view)
                            staged_path = staging / relpath
                            render_map(fields, region, day, view, staged_path)
                            validate_rendered_map(staged_path, region)
                            outputs[region_id][view] = relpath
                finally:
                    mur_path.unlink(missing_ok=True)

            staged_files = list(staging.rglob("*.webp"))
            if len(staged_files) != expected_file_count:
                raise RuntimeError(
                    f"SST-Tagesbuild erzeugte {len(staged_files)} statt {expected_file_count} WebP-Dateien."
                )
            if reference_method is None:
                raise RuntimeError("SST-Tagesbuild hat keine Referenzmethode ermittelt.")

            for region_id in REGIONS:
                for view in VIEWS:
                    relpath = outputs[region_id][view]
                    source = staging / relpath
                    destination = archive_root / relpath
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)

            updated = register_date(manifest, day, outputs, reference_method, statistics)
            write_manifest_atomic(manifest_path, updated)
            return BuildResult(
                day=day,
                already_present=False,
                file_count=expected_file_count,
                reference_method=reference_method,
            )
        except Exception:
            if day.isoformat() not in manifest.get("dates", {}):
                for region_id in REGIONS:
                    for view in VIEWS:
                        (archive_root / archive_relpath(day, region_id, view)).unlink(missing_ok=True)
            raise
        finally:
            for leftover in mur_cache.glob(f"mur_{day.isoformat()}_*.nc"):
                leftover.unlink(missing_ok=True)
            if callable(close_normals):
                close_normals()
