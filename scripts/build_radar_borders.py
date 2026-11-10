#!/usr/bin/env python3
"""Prepare simplified Natural Earth 1:10m borders clipped to the radar extent.

GeoJSON output is vector, not a raster, and remains crisp when zooming.
Attribution: Natural Earth public domain; no fonts or tiles included.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import requests
from shapely.geometry import shape,mapping,box
from shapely.validation import explain_validity

SRC="https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson"
BOUND=box(-32,27,52,74)

def create(target:Path):
    if target.exists() and target.stat().st_size>250_000:
        try:
            prev=json.loads(target.read_text(encoding="utf-8"))
            if prev.get("type")=="FeatureCollection" and len(prev.get("features",[]))>=30:
                print("Existing verified 1:10m vector boundaries used")
                return
        except ValueError:pass
    r=requests.get(SRC,timeout=95,headers={"User-Agent":"ClimateDashboard-Radar-Lab/1.0"})
    r.raise_for_status()
    data=r.json()
    features=[]
    for f in data.get("features",[]):
        g=shape(f["geometry"])
        if not g.is_valid:g=g.buffer(0)
        if not g.intersects(BOUND):continue
        g=g.intersection(BOUND).simplify(.007, preserve_topology=True)
        if g.is_empty:continue
        if not g.is_valid:raise ValueError("Invalid geometry "+str(f.get("properties",{}).get("NAME")))
        properties=f.get("properties",{})
        features.append({"type":"Feature","properties":{"name":properties.get("NAME",properties.get("ADMIN",""))},
                         "geometry":mapping(g)})
    assert len(features)>=35,("Too few European countries",len(features))
    raw=json.dumps({"type":"FeatureCollection","features":features},separators=(",",":"),ensure_ascii=False)
    assert 250_000<len(raw)<9_000_000,("Unexpected border size",len(raw))
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(raw,encoding="utf-8")
    print("Natural Earth 1:10m borders clipped to Europe",len(features),"regions",len(raw),"bytes")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,required=True)
    create(ap.parse_args().out)
