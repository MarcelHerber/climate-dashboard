#!/usr/bin/env python3
"""Unit tests: native/interpolated IFS grid extrema; never contour centroids."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import sys
import unittest

import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from satellite_mslp_grid_centers import ALGORITHM,detect_pressure_centers
from build_satellite_mslp_10min import frame_from_grids
from build_satellite_ecmwf_isobars import build_payload,LEADS

class PressureGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lon=np.arange(-75,55.01,.25)
        cls.lat=np.arange(12,80.01,.25)
        x,y=np.meshgrid(cls.lon,cls.lat)
        cls.base=1013+0.012*x+0.01*y
        cls.low=-23*np.exp(-((x+18)**2+(y-50)**2)/(2*3.4**2))
        cls.high=23*np.exp(-((x-11)**2+(y-54)**2)/(2*3.8**2))
        cls.cycle=dt.datetime(2026,11,14,tzinfo=dt.timezone.utc)

    def test_mslp_grid_extrema_are_real_grid_locations_and_values(self):
        field=self.base+self.low+self.high
        rows=detect_pressure_centers(self.lon,self.lat,field)
        self.assertTrue(rows)
        low=min((c for c in rows if c["type"]=="T"),key=lambda c:abs(c["lon"]+18))
        high=min((c for c in rows if c["type"]=="H"),key=lambda c:abs(c["lon"]-11))
        self.assertLess(abs(low["lon"]+18),1.0)
        self.assertLess(abs(low["lat"]-50),1.0)
        self.assertLess(abs(high["lon"]-11),1.0)
        self.assertLess(abs(high["lat"]-54),1.0)
        self.assertAlmostEqual(field[np.argmin(abs(self.lat-low["lat"])),
            np.argmin(abs(self.lon-low["lon"]))],low["pressure_hpa"],delta=.051)
        self.assertAlmostEqual(field[np.argmin(abs(self.lat-high["lat"])),
            np.argmin(abs(self.lon-high["lon"]))],high["pressure_hpa"],delta=.051)

    def test_shallow_saddle_not_labeled(self):
        field=self.base+0.7*np.exp(-((np.meshgrid(self.lon,self.lat)[0]+25)**2)/30)
        self.assertEqual(detect_pressure_centers(self.lon,self.lat,field),[])

    def test_bad_and_coarse_grids_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"0.25-degree"):
            detect_pressure_centers(self.lon[::2],self.lat,self.base[:,::2])
        with self.assertRaisesRegex(ValueError,"0.25-degree"):
            detect_pressure_centers(self.lon,self.lat,np.full(self.base.shape,np.nan))

    def test_original_model_steps_and_10min_interpolation_are_labeled(self):
        grids={lead:(self.lon,self.lat,self.base+self.low+self.high+lead*.15)
               for lead in LEADS}
        first=frame_from_grids(grids,self.cycle,0)
        between=frame_from_grids(grids,self.cycle,10)
        self.assertEqual(first["pressure_centers_method"],ALGORITHM)
        self.assertEqual(between["pressure_centers_method"],ALGORITHM)
        self.assertFalse(first["interpolated"])
        self.assertTrue(between["interpolated"])
        self.assertEqual(first["interpolation_method"],"original_ifs_grid")
        self.assertEqual(between["interpolation_method"],"linear_mslp_grid_then_contours")
        self.assertTrue(first["pressure_centers"])
        self.assertTrue(between["pressure_centers"])
        self.assertTrue(all(c["lon"] in self.lon and c["lat"] in self.lat
            for c in between["pressure_centers"]))
        self.assertIn("source_valid_utc",between)

    def test_original_payload_contains_grid_based_centers_with_utc(self):
        grids={h:(self.lon,self.lat,self.base+self.low+self.high+h*.1) for h in LEADS}
        doc=build_payload(grids,self.cycle,self.cycle+dt.timedelta(hours=7))
        self.assertEqual(doc["pressure_centers_algorithm"],ALGORITHM)
        self.assertEqual(doc["frames"][0]["pressure_centers_method"],ALGORITHM)
        self.assertTrue(all("pressure_centers" in f and "valid_utc" in f
                            for f in doc["frames"]))
        self.assertEqual(doc["frames"][0]["pressure_centers"][0]["type"],
                         doc["frames"][0]["pressure_centers"][0]["type"])

if __name__=="__main__":
    unittest.main()
