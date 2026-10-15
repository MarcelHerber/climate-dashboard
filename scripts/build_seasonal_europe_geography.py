#!/usr/bin/env python3
"""Create a repeatable, clipped Natural Earth 1:50m Europe outline bundle.

No forecasts are touched. The result is saved on the seasonal data branch and
reused by subsequent runs; avoids external tile services on static charts.
"""
import argparse
import json
import logging
from pathlib import Path
import time
from urllib.request import Request, urlopen
from shapely.geometry import box, shape, Polygon, MultiPolygon, GeometryCollection

SOURCE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
# Cover the ACTUAL Lambert rectangle, not only its nominal geographic extent.
# Upper map corners reach approximately 70W / 90E at ~60N.
BBOX = (-78.0, 20.0, 99.0, 86.0)
LOG = logging.getLogger("seasonal-geography")


def polygons(geometry):
    if isinstance(geometry, Polygon):
        if not geometry.is_empty and geometry.area >= 0.0001:
            yield geometry
    elif isinstance(geometry, (MultiPolygon, GeometryCollection)):
        for subgeom in geometry.geoms:
            yield from polygons(subgeom)


def compact_ring(ring):
    points = [[round(float(x), 3), round(float(y), 3)] for x, y in ring.coords]
    return points if len(points) >= 4 else None


def download_geography():
    req = Request(SOURCE, headers={"User-Agent": "ClimateDashboardSeasonalCharts/1.1 (Natural Earth public data)"})
    for attempt in range(4):
        try:
            with urlopen(req, timeout=65) as handle:
                payload = json.load(handle)
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt * 3)
    clip = box(*BBOX)
    countries = []
    total_rings = 0
    for feature in payload.get("features", []):
        if not feature.get("geometry"):
            continue
        geom = shape(feature["geometry"])
        if not geom.intersects(clip):
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        clipped = geom.intersection(clip)
        polygons_out = []
        for polygon in polygons(clipped):
            simplified = polygon.simplify(0.012, preserve_topology=True)
            if simplified.is_empty:
                continue
            if isinstance(simplified, MultiPolygon):
                pieces = simplified.geoms
            else:
                pieces = [simplified]
            for part in pieces:
                rings = [compact_ring(part.exterior)]
                rings += [compact_ring(ring) for ring in part.interiors]
                rings = [ring for ring in rings if ring]
                if rings:
                    polygons_out.append(rings)
                    total_rings += len(rings)
        if polygons_out:
            countries.append({"n": feature.get("properties", {}).get("ADMIN", "Country"), "p": polygons_out})
    if len(countries) < 35 or total_rings < 80:
        raise RuntimeError("Unexpectedly few 1:50m country/costal outlines")
    result = {
        "source": "Natural Earth ne_50m_admin_0_countries, Public Domain",
        "source_url": SOURCE,
        "bbox": list(BBOX),
        "projection_input": "EPSG:4326 lon/lat; clipped, simplified to 0.012 degrees",
        "countries": countries,
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.output.exists():
        try:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
            if (existing.get("source", "").startswith("Natural Earth ne_50m") and
                    tuple(existing.get("bbox", ())) == BBOX and
                    len(existing.get("countries", [])) >= 35):
                LOG.info("Bestehende 50m-Europageografie wiederverwendet: %s", args.output)
                return
        except (ValueError, OSError):
            pass
    content = download_geography()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(content, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    LOG.info("Natural Earth 50m: %d Länder / %.1f KiB",len(content["countries"]),args.output.stat().st_size/1024)


if __name__=="__main__":
    main()
