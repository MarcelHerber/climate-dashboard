"""Geographic coverage and native-grid cropping shared by full-disc IFS data."""
from __future__ import annotations

import numpy as np

# Meteosat-12 at 0 degrees longitude has a geometric Earth horizon near
# 81.3 degrees central angle. Retain a small limb margin and four additional
# degrees of source-grid padding for gradient and center diagnostics.
DISK_BBOX = (-83., -83., 83., 83.)
WIDE_GRID_BBOX = (-87., -87., 87., 87.)


def disk_candidate_visible(lon, lat):
    """Conservative geographic screening; the client clips to exact ellipsoid."""
    return np.cos(np.deg2rad(lat))*np.cos(np.deg2rad(lon)) > .145


def crop_grid(grid, bbox):
    """Subset complete original sorted native axes, preserving all grid values."""
    x, y, *fields = grid
    west, south, east, north = bbox
    c = np.flatnonzero((x >= west) & (x <= east))
    r = np.flatnonzero((y >= south) & (y <= north))
    if not len(r) or not len(c) or not np.allclose(
            (x[c[0]], y[r[0]], x[c[-1]], y[r[-1]]), bbox, atol=.001):
        raise ValueError("Incomplete native IFS grid coverage for geographic crop")
    rows = slice(r[0], r[-1]+1)
    cols = slice(c[0], c[-1]+1)
    return x[cols], y[rows], *(field[rows, cols] for field in fields)
