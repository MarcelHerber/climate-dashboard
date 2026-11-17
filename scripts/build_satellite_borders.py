#!/usr/bin/env python3
"""Generate compact, global Natural Earth 1:50m coast and national boundaries.

Public-domain line data; no polygon duplicates or artificial clipping-box edges.
The geostationary viewer clips the actual horizon in projected space.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

BASE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
FILES = ("ne_50m_coastline.geojson", "ne_50m_admin_0_boundary_lines_land.geojson")


def segments(geometry):
    """Yield original line segments; splitting at the antimeridian is explicit."""
    if not geometry:
        return
    kind = geometry.get("type")
    if kind == "LineString":
        yield geometry["coordinates"]
    elif kind == "MultiLineString":
        yield from geometry["coordinates"]
    elif kind == "GeometryCollection":
        for component in geometry["geometries"]:
            yield from segments(component)


def compact_line(line):
    """Simplify below a 4K projected pixel and round source precision to 0.001°."""
    # Douglas-Peucker, endpoints/shared-country-boundary junctions untouched.
    if len(line) > 2:
        keep = {0, len(line)-1}
        tasks = [(0,len(line)-1)]
        tolerance2 = .025**2
        while tasks:
            start, stop = tasks.pop()
            ax, ay = line[start][:2]
            bx, by = line[stop][:2]
            dx,dy = bx-ax,by-ay
            length2 = dx*dx+dy*dy
            max_distance,index=0.,None
            for i in range(start+1,stop):
                px,py=line[i][:2]
                t=max(0.,min(1.,((px-ax)*dx+(py-ay)*dy)/length2)) if length2 else 0.
                dist=(px-ax-t*dx)**2+(py-ay-t*dy)**2
                if dist>max_distance:
                    max_distance,index=dist,i
            if max_distance>tolerance2 and index is not None:
                keep.add(index)
                tasks.extend(((start,index),(index,stop)))
        line = [line[i] for i in sorted(keep)]
    out = []
    for coord in line:
        point = [round(coord[0], 3), round(coord[1], 3)]
        if not out or point != out[-1]:
            out.append(point)
    return out


def build(documents):
    lines = []
    for doc in documents:
        for feature in doc["features"]:
            for line in segments(feature["geometry"]):
                compact = compact_line(line)
                if len(compact) >= 2:
                    lines.append(compact)
    if len(lines) < 1000:
        raise ValueError("Unexpected Natural Earth geometry coverage")
    return {"schema_version": 1, "source": "Natural Earth 1:50m coastline and admin-0 land boundaries (public domain)",
            "source_urls": [BASE_URL + name for name in FILES], "coverage_bbox": [-180, -90, 180, 90], "lines": lines}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/satellite_borders_50m.json"))
    args = parser.parse_args()
    documents = []
    for name in FILES:
        with urlopen(Request(BASE_URL + name, headers={"User-Agent": "ClimateDashboard-Satellite/1.0"}), timeout=60) as response:
            documents.append(json.load(response))
    result = build(documents)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(result['lines'])} Natural Earth lines, {args.out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
