#!/usr/bin/env python3
"""Build a lightweight, geographically clipped display-only ECMWF vector payload.

Use the original verified GRIB-derived latest.json for scientific precision.
This derived file retains all real contour levels, run UTC and valid UTC
but omits segments outside the five satellite map regions and simplifies
sub-pixel vertices (0.04 degrees) for responsive mobile SVG rendering.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

# Union of the five supported EPSG:4326 satellite extents, plus 0.5 degree
# padding to let SVG clipping end paths naturally at the map boundary.
BOX = (-70.5, 14.5, 49.5, 75.5)
TOLERANCE = 0.04


def segment_touches(a, b):
    return (max(a[0], b[0]) >= BOX[0] and min(a[0], b[0]) <= BOX[2] and
            max(a[1], b[1]) >= BOX[1] and min(a[1], b[1]) <= BOX[3])


def relevant_runs(points):
    run = []
    for left, right in zip(points, points[1:]):
        if segment_touches(left, right):
            if not run:
                run = [left]
            if run[-1] != right:
                run.append(right)
        elif run:
            if len(run) >= 2:
                yield run
            run = []
    if len(run) >= 2:
        yield run


def point_distance_sq(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return (p[0] - a[0])**2 + (p[1] - a[1])**2
    t = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return (p[0]-a[0]-t*dx)**2 + (p[1]-a[1]-t*dy)**2


def simplify(points, tolerance=TOLERANCE):
    if len(points) <= 2:
        return [[round(x, 3), round(y, 3)] for x, y in points]
    accepted = {0, len(points)-1}
    stack = [(0, len(points)-1)]
    limit = tolerance*tolerance
    while stack:
        start, stop = stack.pop()
        maximum, index = -1.0, None
        for i in range(start+1, stop):
            distance = point_distance_sq(points[i], points[start], points[stop])
            if distance > maximum:
                maximum, index = distance, i
        if maximum > limit and index is not None:
            accepted.add(index)
            stack.append((start, index))
            stack.append((index, stop))
    return [[round(points[i][0], 3), round(points[i][1], 3)] for i in sorted(accepted)]


def build(src):
    if src.get("schema_version") != 1 or src.get("model") != "ECMWF IFS Open Data":
        raise ValueError("Only actual ECMWF source contours may be optimized")
    doc = {k: v for k, v in src.items() if k != "frames"}
    doc["display_optimized"] = True
    doc["simplification_degrees"] = TOLERANCE
    doc["frames"] = []
    for frame in src["frames"]:
        groups = []
        for item in frame["contours"]:
            runs = []
            for line in item["lines"]:
                for segment in relevant_runs(line):
                    reduced = simplify(segment)
                    if len(reduced) >= 2:
                        runs.append(reduced)
            if runs:
                groups.append({"hpa": item["hpa"], "lines": runs})
        if not groups:
            raise ValueError("A verified ECMWF frame lost all visible paths")
        doc["frames"].append({k: v for k, v in frame.items() if k != "contours"} | {"contours": groups})
    return doc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/satellite_mslp/latest.json"))
    parser.add_argument("--output", type=Path, default=Path("_site/data/satellite_mslp/preview.json"))
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    result = build(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":"))+"\n", encoding="utf-8")
    print(f"ECMWF responsive contours: {args.input.stat().st_size} -> {args.output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
