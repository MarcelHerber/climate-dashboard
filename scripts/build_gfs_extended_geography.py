#!/usr/bin/env python3
"""Build coastline/country outlines and country-centre mask from Natural Earth 50m.

For the expanded NOAA 0.5° GFS/CFSR weekly anomaly domain only.
The static geometries are used for geographic outlines and land-country means;
they do not change or interpolate original temperature values.
"""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path

import numpy as np

H,W=121,361
NORTH=84.75
SOUTH=24.75
WEST=-80.25
EAST=99.75
OUT=Path("gfs_analysis_europe/extended_geography.json")
GERMAN_NAMES={
 "Germany":"Deutschland","France":"Frankreich","United Kingdom":"Großbritannien",
 "Norway":"Norwegen","Sweden":"Schweden","Finland":"Finnland",
 "Denmark":"Dänemark","Iceland":"Island","Greenland":"Grönland",
 "Russia":"Russland","Ukraine":"Ukraine","Belarus":"Belarus",
 "Poland":"Polen","Austria":"Österreich","Switzerland":"Schweiz",
 "Spain":"Spanien","Portugal":"Portugal","Italy":"Italien",
 "Greece":"Griechenland","Turkey":"Türkei","Türkiye":"Türkei",
 "Canada":"Kanada","United States of America":"USA","Netherlands":"Niederlande",
 "Belgium":"Belgien","Czechia":"Tschechien","Czech Republic":"Tschechien",
 "Estonia":"Estland","Latvia":"Lettland","Lithuania":"Litauen",
 "Croatia":"Kroatien","Serbia":"Serbien","Slovakia":"Slowakei",
 "Slovenia":"Slowenien","Hungary":"Ungarn","Romania":"Rumänien",
 "Bulgaria":"Bulgarien","Ireland":"Irland","Bosnia and Herzegovina":"Bosnien-Herzegowina",
 "Montenegro":"Montenegro","North Macedonia":"Nordmazedonien",
 "Albania":"Albanien","Georgia":"Georgien","Armenia":"Armenien",
 "Azerbaijan":"Aserbaidschan","Kazakhstan":"Kasachstan",
 "Uzbekistan":"Usbekistan","Turkmenistan":"Turkmenistan",
 "Kyrgyzstan":"Kirgisistan","Tajikistan":"Tadschikistan",
 "Moldova":"Moldau","Algeria":"Algerien","Morocco":"Marokko",
 "Tunisia":"Tunesien","Libya":"Libyen","Egypt":"Ägypten",
}


def source_boundaries(output:Path=OUT)->dict:
    from cartopy.io import shapereader
    from shapely import contains_xy
    from shapely.geometry import Polygon,MultiPolygon,box

    file=shapereader.natural_earth(resolution="50m",category="cultural",name="admin_0_countries")
    frame=box(WEST,SOUTH,EAST,NORTH)
    ys=NORTH-np.arange(H,dtype=np.float64)*.5
    xs=WEST+np.arange(W,dtype=np.float64)*.5
    longitude,latitude=np.meshgrid(xs,ys)
    mask=np.full((H,W),-1,dtype="<i2")
    country=[]
    rings=[]

    def iter_rings(geometry):
        if isinstance(geometry,Polygon):
            yield geometry.exterior
            for item in geometry.interiors:
                yield item
        elif isinstance(geometry,MultiPolygon) or hasattr(geometry,"geoms"):
            for part in geometry.geoms:
                yield from iter_rings(part)

    for record in shapereader.Reader(file).records():
        name=record.attributes.get("ADMIN") or record.attributes.get("NAME_EN")
        if not isinstance(name,str) or not name.strip():
            continue
        geom=record.geometry
        if not geom.is_valid:
            geom=geom.buffer(0)
        if not geom.intersects(frame):
            continue
        clipped=geom.intersection(frame)
        for ring in iter_rings(clipped.simplify(0.035,preserve_topology=True)):
            coords=[[round(float(x),3),round(float(y),3)] for x,y in ring.coords]
            if len(coords)>1:
                rings.append(coords)
        inside=contains_xy(geom,longitude,latitude)
        count=int(np.count_nonzero(inside))
        if count==0:
            continue
        i=len(country)
        mask[inside]=i
        country.append({
            "id":i,
            "name":GERMAN_NAMES.get(name,name),
            "source_name":name,
            "cells":count
        })

    if len(country)<60 or len(rings)<100 or np.count_nonzero(mask>=0)<5000:
        raise RuntimeError("Natural Earth 50m source has incomplete countries/geographic polygons")
    country_names=[x["name"] for x in country]
    for essential in ("Deutschland","Island","Norwegen","Russland","Grönland"):
        if essential not in country_names:
            raise ValueError("Natural Earth 50m missing expanded-country coverage: "+essential)
    body={
        "schema":1,
        "source":"Natural Earth admin_0_countries 50m; public domain",
        "type":"geographic_country_boundaries_not_temperature",
        "width":W,"height":H,
        "lat_north":NORTH,"lat_south":SOUTH,
        "lon_west":WEST,"lon_east":EAST,
        "grid_degrees":.5,
        "countries":country,
        "country_mask_b64":base64.b64encode(mask.tobytes(order="C")).decode("ascii"),
        "rings":rings,
        "coordinates":"longitude/latitude, decimal degrees",
        "simplification":"0.035 degree for map line display only; country-cell mask from original polygons"
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(body,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print("Validated expanded countries",len(country),"outlines",len(rings),
          "size",output.stat().st_size,flush=True)
    return body


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=OUT)
    args=parser.parse_args()
    source_boundaries(args.output)
