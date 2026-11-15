#!/usr/bin/env python3
"""Conservative high/low diagnostics from actual ECMWF IFS MSLP grid values.

A center is a grid-point local extremum, NOT a centroid of drawn contours.
3-hour source steps use decoded operational 0.25° MSLP. Ten-minute frames
use the already documented linearly interpolated MSLP *grid*, so those centers
are explicitly forecast interpolation, not new ECMWF model runs or observations.
No artificial centers, pressure values, or timestamps can be synthesized.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

ALGORITHM = "ifs_mslp_grid_extrema_v2"
MODEL_BBOX = (-70.5, 14.5, 49.5, 75.5)
_OFFSETS = ((4, 0), (-4, 0), (0, 4), (0, -4),
            (3, 3), (3, -3), (-3, 3), (-3, -3))
_RING = ((16, 0), (-16, 0), (0, 16), (0, -16),
         (11, 11), (-11, -11), (11, -11), (-11, 11))


def _smooth(z):
    """Light separable binomial filter, latitude/longitude grid in native axes."""
    out = np.asarray(z, dtype=np.float64)
    for axis in (0, 1, 0, 1):
        before = np.take(out, np.maximum(np.arange(out.shape[axis]) - 1, 0), axis=axis)
        after = np.take(out, np.minimum(np.arange(out.shape[axis]) + 1, out.shape[axis] - 1), axis=axis)
        out = (before + 2 * out + after) / 4
    return out


def _closed_systems(z, type_):
    """Track nested closed 5-hPa level sets, strictly on the native grid.

    Starting at the deepest/strongest level retains separate closed cores,
    but does not add a second label when they are merely local extrema in
    the same core. Connected regions touching the source boundary are open.
    """
    direction = 1 if type_ == "H" else -1
    values = direction * z
    top = int(np.floor((values.max() - 1e-6) / 5) * 5)
    bottom = 1015 if type_ == "H" else -1015
    selected = []
    covered = np.zeros(z.shape, dtype=bool)
    for level in range(top, bottom - 1, -5):
        labels, _ = ndimage.label(values > level)
        edge = set(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
        for label_id, region in enumerate(ndimage.find_objects(labels), 1):
            if region is None or label_id in edge:
                continue
            mask = labels[region] == label_id
            # Do not elevate one-pixel pressure speckles into synoptic systems.
            if np.count_nonzero(mask) < 16:
                continue
            patch = np.where(mask, values[region], -np.inf)
            iy, ix = np.unravel_index(np.argmax(patch), patch.shape)
            depth = float(patch[iy, ix] - level)
            if depth < 0.6:
                continue
            row, col = region[0].start + iy, region[1].start + ix
            covered[region] |= mask
            members = [m for m in selected if labels[m[0], m[1]] == label_id]
            if not members:
                selected.append([row, col, depth])
            elif len(members) == 1:
                # A broader closed ring confirms the same center's prominence.
                m = members[0]
                m[2] = max(m[2], float(values[m[0], m[1]] - level))
    return selected, covered


def detect_pressure_centers(lons, lats, pressure):
    """Return ranked, well-separated *native-grid* minima/maxima.

    Screens and exports apply geographic viewport filters; this operation
    does not depend on whether the contours are at 2 or 5 hPa.
    Closed pressure-level components identify broad systems and distinguish
    separate cores from secondary extrema within the same closed isobar.
    The conservative directional test is retained for open systems only.
    """
    xx, yy = np.asarray(lons, dtype=float), np.asarray(lats, dtype=float)
    z = np.asarray(pressure, dtype=float)
    if (xx.ndim != 1 or yy.ndim != 1 or z.shape != (len(yy), len(xx))
            or len(xx) < 60 or len(yy) < 55
            or not np.isfinite(z).all()
            or np.any(np.diff(xx) <= 0) or np.any(np.diff(yy) <= 0)
            or not (np.allclose(np.diff(xx), .25, atol=.01)
                    and np.allclose(np.diff(yy), .25, atol=.01))
            or z.min() < 800 or z.max() > 1120):
        raise ValueError("Expected finite georeferenced original IFS 0.25-degree MSLP grid (hPa)")

    smoothed = _smooth(z)
    radius = 16
    core = smoothed[radius:-radius, radius:-radius]
    low = np.ones(core.shape, dtype=bool)
    high = np.ones(core.shape, dtype=bool)
    strict_low = np.zeros(core.shape, dtype=bool)
    strict_high = np.zeros(core.shape, dtype=bool)
    for dy, dx in _OFFSETS:
        peer = smoothed[radius + dy:len(yy) - radius + dy,
                        radius + dx:len(xx) - radius + dx]
        low &= core <= peer
        high &= core >= peer
        strict_low |= core < peer
        strict_high |= core > peer
    low &= strict_low & (core <= 1014)
    high &= strict_high & (core >= 1017)
    choices = []

    def add(type_, iy, ix, prominence, closed):
        lon, lat = float(xx[ix]), float(yy[iy])
        if not (MODEL_BBOX[0] + 1 <= lon <= MODEL_BBOX[2] - 1
                and MODEL_BBOX[1] + 1 <= lat <= MODEL_BBOX[3] - 1):
            return
        value = float(z[iy, ix])
        if (type_ == "T" and value > 1014) or (type_ == "H" and value < 1017):
            return
        departure = (1013.25 - value) if type_ == "T" else (value - 1013.25)
        score = min(300, prominence * 3 + max(0, departure) * .45 + (8 if closed else 0))
        choices.append({"type": type_, "lon": round(lon, 3), "lat": round(lat, 3),
                        "pressure_hpa": round(value, 1), "prominence_hpa": round(prominence, 1),
                        "score": round(score, 2), "closed_system": closed})

    for type_, selector in (("T", low), ("H", high)):
        systems, covered = _closed_systems(z, type_)
        for row, col, prominence in systems:
            add(type_, row, col, prominence, True)
        for row_, col_ in np.argwhere(selector):
            row, col = int(row_ + radius), int(col_ + radius)
            lon, lat = float(xx[col]), float(yy[row])
            if not (MODEL_BBOX[0] + 1 <= lon <= MODEL_BBOX[2] - 1
                    and MODEL_BBOX[1] + 1 <= lat <= MODEL_BBOX[3] - 1):
                continue
            local = smoothed[row, col]
            diffs = np.asarray([
                float(smoothed[row + dy, col + dx] - local) * (1 if type_ == "T" else -1)
                for dy, dx in _RING
            ])
            # At least six of eight directions should oppose the central extremum;
            # reject long trough axes and mere saddles, including shallow 1015 hPa.
            if np.count_nonzero(diffs > .8) < 6:
                continue
            prominence = float(np.median(diffs))
            if prominence < 2.0:
                continue
            # Actual minimum/maximum from UNSMOOTHED decoded grid in the
            # immediate 3x3 vicinity; no contour midpoint or 2-D interpolation.
            patch = z[row - 1:row + 2, col - 1:col + 2]
            offset = np.unravel_index(np.argmin(patch) if type_ == "T" else np.argmax(patch), patch.shape)
            iy, ix = row + int(offset[0]) - 1, col + int(offset[1]) - 1
            if covered[iy, ix]:
                continue
            add(type_, iy, ix, prominence, False)
    choices.sort(key=lambda entry: (-entry["score"], entry["type"], entry["lon"], entry["lat"]))
    kept = []
    for item in choices:
        # Geographic physical separation prevents duplicate candidates that
        # lie close together despite varying screen zoom.
        if any(not (item["closed_system"] and old["closed_system"]) and
               (111 * (item["lat"] - old["lat"])) ** 2 +
               (111 * np.cos(np.deg2rad((item["lat"] + old["lat"]) / 2)) *
                (item["lon"] - old["lon"])) ** 2 < 360 ** 2 for old in kept):
            continue
        kept.append(item)
        if len(kept) >= 40:
            break
    return kept
