"""Publish numeric HYRAS temperature planes from the same arrays as the maps."""
import gzip
from pathlib import Path

import numpy as np


def publish(root: Path, entry: dict, key: str, reference: str, array: np.ndarray, start: str, end: str) -> None:
    """Array is north-up, west-to-east; the manifest binds raster to dates and reference."""
    a = np.asarray(array)
    if a.ndim != 2 or not all(a.shape):
        raise ValueError("Expected a nonempty two-dimensional HYRAS raster")
    grid = {"width": int(a.shape[1]), "height": int(a.shape[0])}
    if entry.get("raster_grid", grid) != grid:
        raise ValueError("HYRAS temperature grid mismatch")
    q = np.full(a.shape, -32768, dtype="<i2")
    valid = np.isfinite(a)
    q[valid] = np.clip(np.rint(a[valid] * 100), -32767, 32767).astype("<i2")
    rel = f"current/{key}_anomaly_{reference.replace('-', '_')}.i16.gz"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(q.tobytes(order="C"), compresslevel=6, mtime=0))
    entry["raster_grid"] = grid
    entry.setdefault("raster_by_reference", {})[reference] = rel
    entry.setdefault("raster_dates_by_reference", {})[reference] = [start, end]
