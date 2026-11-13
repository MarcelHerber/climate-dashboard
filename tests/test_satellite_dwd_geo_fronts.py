"""DWD WFS source discovery and fail-closed NinJo-GML conversion."""
from __future__ import annotations
import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("dwd_ninjo_source",ROOT/"scripts/update_satellite_dwd_geo_fronts.py")
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
NOW=datetime(2026,11,13,22,30,tzinfo=timezone.utc)
SOURCE="https://opendata.dwd.de/weather/charts/fronts/analysis_202611132100.gml"
XML=b"""<?xml version="1.0"?>
<gml:FeatureCollection xmlns:gml="http://www.opengis.net/gml" xmlns:fr="https://example.com/front">
  <gml:featureMember><fr:Front>
    <fr:frontType>Kaltfront</fr:frontType><fr:validTime>2026-11-13T21:00Z</fr:validTime>
    <gml:LineString srsName="urn:ogc:def:crs:EPSG::4326" srsDimension="2">
      <gml:posList>56.3 -45.0 55.8 -40.8 53.0 -37.6</gml:posList>
    </gml:LineString>
  </fr:Front></gml:featureMember>
  <gml:featureMember><fr:Front>
    <fr:frontType>Warmfront</fr:frontType><fr:validTime>2026-11-13T21:00Z</fr:validTime>
    <gml:LineString srsName="urn:ogc:def:crs:OGC:1.3:CRS84" srsDimension="2">
      <gml:posList>-24 45 -17 46</gml:posList>
    </gml:LineString>
  </fr:Front></gml:featureMember>
</gml:FeatureCollection>"""
WFS=b"""<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0">
<wfs:FeatureTypeList><wfs:FeatureType><wfs:Name>dwd:WMS_temp</wfs:Name><wfs:Title>Temperatur</wfs:Title></wfs:FeatureType>
<wfs:FeatureType><wfs:Name>dwd:Fronten</wfs:Name><wfs:Title>Wetterfronten</wfs:Title></wfs:FeatureType></wfs:FeatureTypeList></wfs:WFS_Capabilities>"""

class OfficialDwdGMLTests(unittest.TestCase):
 def test_public_wfs_candidate_detection_does_not_pretend_features_verified(self):
    a=mod.discover(WFS)
    self.assertEqual(a,[{"name":"dwd:Fronten","title":"Wetterfronten"}])
 def test_real_ninjo_gml_lonlat_and_latlon_axis_convention(self):
    item=mod.extract_features(XML,NOW,SOURCE)
    self.assertEqual(item["status"],"verified")
    self.assertEqual(item["valid_utc"],"2026-11-13T21:00Z")
    self.assertEqual(len(item["features"]),2)
    self.assertEqual(item["features"][0]["geometry"]["coordinates"][0],[-45.0,56.3])
    self.assertEqual(item["features"][1]["geometry"]["coordinates"][0],[-24,45])
    self.assertEqual(item["features"][0]["properties"]["front_type"],"cold")
    self.assertTrue(item["georeferencing_verified"])
 def test_reject_incorrect_crs_type_validity_or_host(self):
    bads=[
      (XML,SOURCE.replace("opendata.dwd.de","evil.example")),
      (XML.replace(b"2026-11-13T21:00Z",b"2026-08-13T21:00Z"),SOURCE),
      (XML.replace(b"EPSG::4326",b"EPSG::3857").replace(b"OGC:1.3:CRS84",b"EPSG::3857"),SOURCE),
      (XML.replace(b"Kaltfront",b"Grasland").replace(b"Warmfront",b"Tiefdruck"),SOURCE),
      (b"<!DOCTYPE foo>"+XML,SOURCE)
    ]
    for xml,url in bads:
      with self.assertRaises(ValueError):
        mod.extract_features(xml,NOW,url)
    self.assertFalse(mod.official_gml("https://opendata.dwd.de/weather/charts/analysis/a.png"))
 def test_no_live_geodata_claims_without_an_original_feed(self):
    j=mod.empty(NOW,"DWD XML not publicly available")
    self.assertEqual(j["status"],"unavailable")
    self.assertFalse(j["georeferencing_verified"])
    self.assertEqual(j["features"],[])
    self.assertEqual(j["provider"],"DWD")

if __name__=="__main__":unittest.main()
