"""Synthetic scientific regression tests for North Atlantic Hart-CPS engine.

No downloaded data; tests assert sign and continuity invariants and must pass
before an operational data refresh.
"""
import importlib.util
from pathlib import Path
import unittest

import numpy as np


spec=importlib.util.spec_from_file_location(
    "gfs_cps", Path(__file__).resolve().parents[1]/"scripts"/"update_north_atlantic_cps.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestHartNorthAtlantic(unittest.TestCase):
    def test_thermal_wind_sign_and_neutral(self):
        levels=[900,850,700,600]
        self.assertGreater(mod.thermal_wind(levels,[100,90,75,60]),0)
        self.assertLess(mod.thermal_wind(levels,[60,75,90,100]),0)
        self.assertAlmostEqual(mod.thermal_wind(levels,[80,80,80,80]),0,places=5)

    def test_storm_motion_relative_asymmetry(self):
        lats=np.linspace(32,38,81,dtype=float)
        lons=np.linspace(-44,-36,81,dtype=float)
        lon,lat=np.meshgrid(lons,lats)
        field={"sp":np.full(lat.shape,1020,dtype=float)}
        # A pressure-layer thickness increasing toward north means a lower
        # 900-600 thickness to the RIGHT of an eastbound storm.
        thickness=3200+10*(lat-35)
        for p,zbase in [(900,900),(850,1400),(700,3000),(600,4100),
                        (500,5550),(400,7100),(300,9250)]:
            ring=((lon+40)**2+(lat-35)**2)
            # Distinct smooth amplitude at each pressure surface.
            core=-(120+(900-p)*.08)*np.exp(-ring/2)
            field[f"z{p}"]=zbase+core+(thickness-3200 if p==600 else 0)
        point={"lat":35.0,"lon":-40.0}
        result=mod.calculate_cps(field,lat,lon,point,(200,0))
        self.assertIsNotNone(result)
        self.assertLess(result["b"],-5)
        self.assertEqual(result["radius_km"],500)

    def test_tracker_requires_three_times_and_contrast(self):
        run=mod.dt.datetime(2026,10,12,0,tzinfo=mod.UTC)
        obs=lambda lat,lon,p:{"lat":lat,"lon":lon,"mslp_hpa":p,"contrast_hpa":7}
        detected={h:[] for h in mod.HOURS}
        detected[0]=[obs(45,-40,986)]
        detected[6]=[obs(46,-39,983)]
        detected[12]=[obs(47,-38,980)]
        tracks=mod.tracks_from_centers(detected,run)
        self.assertEqual(len(tracks),1)
        self.assertEqual(len(tracks[0]["points"]),3)
        self.assertEqual(tracks[0]["points"][-1]["h"],12)


if __name__=="__main__":
    unittest.main()
