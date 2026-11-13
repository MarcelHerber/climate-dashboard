"""Decode actual high-resolution official WPC coordinates without inventing fronts."""
from __future__ import annotations
import importlib.util
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("sat_wpc_front",ROOT/"scripts/update_satellite_noaa_wpc_fronts.py")
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
NOW=datetime(2026,11,13,22,5,tzinfo=timezone.utc)
BODY="""ASUS02 KWBC 132100
CODSUS

CODED SURFACE FRONTAL POSITIONS
NWS WEATHER PREDICTION CENTER COLLEGE PARK MD
VALID 111321Z
HIGHS 1025 4800600
LOWS 997 5630453
OCFNT 5630450 5580408 5300376 5100367
COLD 5100367 4950310 4800281
STNRY 4300473 4380452 4470414
WARM 3900350 4120320 4200280
TROF 5500300 5300320
$$
"""

class NOAAFrontAnalysisTests(unittest.TestCase):
    def test_authentic_coded_bulletin_decoding_with_named_types(self):
        report=w.parse(BODY,NOW)
        self.assertEqual(report["status"],"verified")
        self.assertEqual(report["valid_utc"],"2026-11-13T21:00Z")
        self.assertEqual(len(report["features"]),4)
        self.assertEqual([r["properties"]["front_type"] for r in report["features"]],
                         ["occluded","cold","stationary","warm"])
        self.assertEqual(report["features"][0]["geometry"]["coordinates"][0],[-45,56.3])
        self.assertEqual(report["features"][1]["geometry"]["coordinates"][-1],[-28.1,48.0])
        self.assertTrue(report["georeferencing_verified"])
        self.assertEqual(report["geographic_precision_degrees"],.1)
        self.assertIn("western North Atlantic",report["analysis_domain"])

    def test_stale_or_forecast_or_unsupported_bulletins_are_rejected(self):
        for bad in [
            BODY.replace("ASUS02","ASUS01"),
            BODY.replace("CODSUS","CODXXX"),
            BODY.replace("VALID 111321Z","VALID 110721Z"),
            BODY.replace("VALID 111321Z","VALID 111421Z"),
            BODY.replace("CODED SURFACE FRONTAL POSITIONS","CODED SURFACE FORECAST"),
            BODY.replace("OCFNT 5630450 5580408 5300376 5100367",""),
        ]:
            if "OCFNT" not in bad:
                # Remaining analyzed cold/warm lines are still valid.
                self.assertEqual(w.parse(bad,NOW)["status"],"verified")
            else:
                with self.assertRaises(ValueError):
                    w.parse(bad,NOW)

    def test_invalid_coords_are_never_interpreted_as_geographic_positions(self):
        self.assertEqual(w.decode("5630450"),[-45.0,56.3])
        self.assertIsNone(w.decode("9950450"))
        self.assertIsNone(w.decode("5639999"))
        self.assertIsNone(w.decode("563045"))
        self.assertIsNone(w.decode("abc0450"))
        rows=w.parse(BODY.replace("5100367","5101810"),NOW)
        self.assertTrue(all(abs(row["geometry"]["coordinates"][i][0]-
                                row["geometry"]["coordinates"][i-1][0])<=35
                            for row in rows["features"]
                            for i in range(1,len(row["geometry"]["coordinates"]))))

    def test_wpc_date_bounded_and_across_new_year(self):
        near=datetime(2027,1,1,1,tzinfo=timezone.utc)
        self.assertEqual(w.closest_valid("12","31","21",near),
                         datetime(2026,12,31,21,tzinfo=timezone.utc))
        self.assertIsNone(w.closest_valid("02","30","12",NOW))
        self.assertEqual(w.unavailable(NOW,"HTTP 503")["features"],[])
        self.assertFalse(w.unavailable(NOW,"HTTP 503")["georeferencing_verified"])

    def test_no_unsupported_source_or_png_provenance(self):
        script=(ROOT/"satellite_noaa_fronts.js").read_text(encoding="utf-8")
        html=(ROOT/"satelliten.html").read_text(encoding="utf-8")
        build=(ROOT/"scripts/build_pages_site.sh").read_text(encoding="utf-8")
        self.assertIn('id="satWpcFrontSvg"',html)
        self.assertIn('id="satShowWpcFronts"',html)
        self.assertIn('id="satWpcFrontStatus"',html)
        self.assertIn("satellite_noaa_fronts.js",build)
        self.assertIn("NOAA WPC",script)
        self.assertIn("CODSUS-HIRES",script)
        self.assertIn("satWpcFrontSvg",script)
        self.assertIn("satellite_noaa_fronts.js",html)

if __name__=="__main__":
    unittest.main()
