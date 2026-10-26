"""Official DWD MOSMIX TX/TN versus sampled TTT: 12 h at 18/06 UTC."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("update_mosmix",ROOT/"scripts/update_mosmix.py")
mos=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mos)

KML="""<?xml version="1.0" encoding="UTF-8"?>
<kml:kml xmlns:kml="http://www.opengis.net/kml/2.2" xmlns:dwd="https://example.test/dwd">
  <kml:Document>
    <dwd:IssueTime>2026-10-14T03:00:00Z</dwd:IssueTime>
    <dwd:ForecastTimeSteps>
      <dwd:TimeStep>2026-10-14T06:00:00Z</dwd:TimeStep>
      <dwd:TimeStep>2026-10-14T09:00:00Z</dwd:TimeStep>
      <dwd:TimeStep>2026-10-14T18:00:00Z</dwd:TimeStep>
      <dwd:TimeStep>2026-10-15T06:00:00Z</dwd:TimeStep>
    </dwd:ForecastTimeSteps>
    <kml:Placemark>
      <kml:name>TEST1</kml:name>
      <kml:description>FRANKFURT TEST</kml:description>
      <kml:Point><kml:coordinates>8.65,50.12,120</kml:coordinates></kml:Point>
      <kml:ExtendedData>
        <dwd:Forecast dwd:elementName="TTT">286.15 287.15 289.15 282.15</dwd:Forecast>
        <dwd:Forecast dwd:elementName="TX">299.15 305.15 295.15 -</dwd:Forecast>
        <dwd:Forecast dwd:elementName="TN">281.15 274.15 230.15 280.15</dwd:Forecast>
        <dwd:Forecast dwd:elementName="RR1c">0.1 0.2 0.3 0.4</dwd:Forecast>
        <dwd:Forecast dwd:elementName="RR3c">- 0.8 - 1.2</dwd:Forecast>
        <dwd:Forecast dwd:elementName="RR6c">- - 2.4 -</dwd:Forecast>
        <dwd:Forecast dwd:elementName="RRhc">- - 5.3 -</dwd:Forecast>
        <dwd:Forecast dwd:elementName="RRdc">- - 7.8 -</dwd:Forecast>
        <dwd:Forecast dwd:elementName="FF">3 4 5 6</dwd:Forecast>
        <dwd:Forecast dwd:elementName="FX1">7 8 9 10</dwd:Forecast>
        <dwd:Forecast dwd:elementName="FX3">8 9 10 11</dwd:Forecast>
        <dwd:Forecast dwd:elementName="FFXh">- - 13 -</dwd:Forecast>
        <dwd:Forecast dwd:elementName="SunD1">0 600 3600 -</dwd:Forecast>
        <dwd:Forecast dwd:elementName="Rad1h">0 120 2500 -</dwd:Forecast>
      </kml:ExtendedData>
    </kml:Placemark>
    <kml:Placemark>
      <kml:name>GLOBAL-001</kml:name>
      <kml:description>SYDNEY TEST AUSTRALIA</kml:description>
      <kml:Point><kml:coordinates>151.2093,-33.8688,40</kml:coordinates></kml:Point>
      <kml:ExtendedData>
        <dwd:Forecast dwd:elementName="TTT">302.15 305.15 300.15 299.15</dwd:Forecast>
        <dwd:Forecast dwd:elementName="SunD1">900 1800 3600 0</dwd:Forecast>
        <dwd:Forecast dwd:elementName="Rad1h">200 800 3000 0</dwd:Forecast>
      </kml:ExtendedData>
    </kml:Placemark>
  </kml:Document>
</kml:kml>"""


class MOSMIXExtremaTests(unittest.TestCase):
    def test_unit_conversion(self):
        self.assertEqual(mos.convert_values("TX",[293.15,None]),[20.0,None])
        self.assertEqual(mos.convert_values("TN",[271.15]),[-2.0])
        self.assertEqual(mos.convert_values("FX3",[5.0,None]),[18.0,None])
        self.assertEqual(mos.convert_values("FXh",[10.0]),[36.0])
        self.assertEqual(mos.convert_values("FFXh",[10.0]),[36.0])
        self.assertEqual(mos.convert_values("RRdc",[6.789]),[6.79])
        self.assertEqual(mos.convert_values("SunD1",[0,600,3600,None]),[0.0,10.0,60.0,None])
        self.assertEqual(mos.convert_values("Rad1h",[950.7,None]),[950.7,None])

    def test_daily_extrema_use_only_dwd_standard_synop_times(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"test.kmz"
            with zipfile.ZipFile(path,"w") as kmz:
                kmz.writestr("test.kml",KML)
            details=Path(folder)/"stations"
            data=mos.parse_kmz(path,"synthetic-test",details)
            self.assertEqual(len(data["stations"]),1)
            station=data["stations"][0]
            # Despite higher raw 'TX' at 09 UTC, only 18 UTC is eligible.
            self.assertEqual(station["tx12"],{"2":22.0})
            # TN at 18 UTC is irrelevant; the selected nights end at 06 UTC.
            self.assertEqual(station["tn12"],{"0":8.0,"3":7.0})
            self.assertEqual(station["values"][2],16.0)
            self.assertEqual(data["extrema_reference"]["TX"]["valid_hour_utc"],18)
            self.assertEqual(data["extrema_reference"]["TN"]["valid_hour_utc"],6)
            saved=json.loads((details/(station["key"]+".json")).read_text())
            self.assertEqual(saved["parameters"]["TX"][2],22.0)
            self.assertEqual(saved["parameters"]["TN"][0],8.0)
            self.assertEqual(saved["parameters"]["RR1c"][0],0.1)
            self.assertEqual(saved["parameters"]["RR3c"][1],0.8)
            self.assertEqual(saved["parameters"]["RR6c"][2],2.4)
            self.assertEqual(saved["parameters"]["RRhc"][2],5.3)
            self.assertEqual(saved["parameters"]["RRdc"][2],7.8)
            self.assertEqual(saved["parameters"]["FX3"][2],36.0)
            self.assertEqual(saved["parameters"]["FXh"][2],46.8)
            self.assertNotIn("FFXh",saved["parameters"])
            self.assertEqual(saved["parameters"]["SunD1"],[0.0,10.0,60.0,None])
            self.assertEqual(saved["parameters"]["Rad1h"][2],2500.0)
            # The Australian record in the test KMZ must not be processed
            # or exposed in the Germany-only MOSMIX output.
            self.assertEqual(len(data["stations"]),1)
            self.assertEqual(station["name"],"FRANKFURT TEST")
            self.assertNotIn("world_index",data)
            self.assertNotIn("world_station_count",data)
            self.assertFalse((Path(folder)/"world_stations.json").exists())
            self.assertFalse((Path(folder)/"world").exists())
            self.assertEqual(len(list(details.glob("*.json"))),1)

    def test_sparse_original_extrema_not_hourly_maximum(self):
        # The DWD 12-h maximum differs from the hourly 2-m temperatures.
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"test.kmz"
            with zipfile.ZipFile(path,"w") as kmz:
                kmz.writestr("test.kml",KML)
            station=mos.parse_kmz(path,"synthetic-test",Path(folder)/"stations")["stations"][0]
            self.assertNotEqual(max(v for v in station["values"] if v is not None),
                                station["tx12"]["2"])


if __name__=="__main__":
    unittest.main()
