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

    def test_broad_closed_1030_high_is_not_missed(self):
        x,y=np.meshgrid(self.lon,self.lat)
        field=1010+24*np.exp(-((x-21)**2+(y-48)**2)/(2*12**2))
        highs=[c for c in detect_pressure_centers(self.lon,self.lat,field) if c['type']=='H']
        self.assertEqual(len(highs),1)
        self.assertEqual((highs[0]['lon'],highs[0]['lat'],highs[0]['pressure_hpa']),(21,48,1034))

    def test_broad_shallow_closed_1025_high_is_not_lost_to_stronger_high(self):
        x,y=np.meshgrid(self.lon,self.lat)
        field=(1020.5+4.84*np.exp(-((x+28)**2+(y-28.5)**2)/(2*8**2))
               +11.5*np.exp(-((x-30)**2+(y-46)**2)/(2*5**2)))
        highs=[c for c in detect_pressure_centers(self.lon,self.lat,field) if c['type']=='H']
        azores=next((c for c in highs if c['lon']==-28 and c['lat']==28.5),None)
        self.assertIsNotNone(azores)
        self.assertEqual(azores['pressure_hpa'],1025.3)
        self.assertTrue(azores['closed_system'])
        self.assertGreater(azores['closed_area_km2'],50000)

    def test_tiny_shallow_closed_speckle_is_not_labeled(self):
        x,y=np.meshgrid(self.lon,self.lat)
        field=1020.5+4.84*np.exp(-((x+28)**2+(y-28.5)**2)/(2*.5**2))
        self.assertEqual(detect_pressure_centers(self.lon,self.lat,field),[])

    def test_two_extrema_inside_same_closed_975_system_get_one_label(self):
        x,y=np.meshgrid(self.lon,self.lat)
        field=(1010-38*np.exp(-((x-5)**2+(y-65)**2)/(2*13**2))
            -4*np.exp(-(x**2+(y-65)**2)/(2*1.7**2))
            -3.5*np.exp(-((x-10)**2+(y-65)**2)/(2*1.7**2)))
        lows=[c for c in detect_pressure_centers(self.lon,self.lat,field) if c['type']=='T']
        self.assertEqual(len(lows),1)
        self.assertEqual((lows[0]['lon'],lows[0]['lat'],lows[0]['pressure_hpa']),(0.75,65,970.3))

    def test_two_separate_closed_970_cores_remain_distinct(self):
        x,y=np.meshgrid(self.lon,self.lat)
        field=(1010-39*np.exp(-((x-5)**2+(y-65)**2)/(2*13**2))
            -5*np.exp(-(x**2+(y-65)**2)/(2*1.7**2))
            -4.5*np.exp(-((x-10)**2+(y-65)**2)/(2*1.7**2)))
        lows=[c for c in detect_pressure_centers(self.lon,self.lat,field) if c['type']=='T']
        self.assertEqual(len(lows),2)
        self.assertEqual(sorted(c['lon'] for c in lows),[0.5,9.25])

    def test_diagonal_saddle_follows_actual_contour_topology(self):
        import contourpy
        lon=np.arange(-40,36.01,.25)
        lat=np.arange(20,66.01,.25)
        for background,peak,want in [(1029,1033,1),(1027,1031,2)]:
            with self.subTest(background=background,peak=peak):
                field=np.full((len(lat),len(lon)),float(background))
                field[80:100,120:140]=peak
                field[100:120,140:160]=peak
                # Independent confirmation of the actual renderer's ring count.
                generator=contourpy.contour_generator(x=lon,y=lat,z=field,name='serial')
                rings=generator.lines(1030)
                self.assertEqual(len(rings),want)
                self.assertEqual(len([c for c in detect_pressure_centers(lon,lat,field) if c['type']=='H']),want)
                low_field=2000-field
                low_rings=contourpy.contour_generator(x=lon,y=lat,z=low_field,name='serial').lines(970)
                self.assertEqual(len(low_rings),want)
                self.assertEqual(len([c for c in detect_pressure_centers(lon,lat,low_field) if c['type']=='T']),want)

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
