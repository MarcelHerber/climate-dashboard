"""Offline regression tests for 60N/10hPa NOAA GEFS ensemble ingestion."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import build_gefs_60n_10hpa_ensemble as mod
from datetime import datetime,timezone


class GefsWindTests(unittest.TestCase):
    def test_control_and_perturbed_naming(self):
        cycle=datetime(2026,10,21,0,tzinfo=timezone.utc)
        control=parse_qs(urlparse(mod.url_for(cycle,"c00",840)).query)
        perturbed=parse_qs(urlparse(mod.url_for(cycle,"p30",384)).query)
        self.assertEqual(control["file"],["gec00.t00z.pgrb2a.0p50.f840"])
        self.assertEqual(perturbed["file"],["gep30.t00z.pgrb2a.0p50.f384"])
        self.assertEqual(control["lev_10_mb"],["on"])
        self.assertEqual(control["var_UGRD"],["on"])
        self.assertEqual(control["toplat"],["60.5"])
        self.assertEqual(control["bottomlat"],["59.5"])
        self.assertIn("/gefs.20261021/00/atmos/pgrb2ap5",control["dir"][0])

    def test_all_real_members(self):
        self.assertEqual(len(mod.MEMBERS),31)
        self.assertEqual(mod.MEMBERS[0],"c00")
        self.assertEqual(mod.MEMBERS[-1],"p30")
        self.assertEqual(len(set(mod.MEMBERS)),31)

    def test_sample_only_exact_latitude(self):
        # 720 longitudes at latitude 60.0 are averaged; the neighbouring
        # 59.5 and 60.5 bands must not affect the result.
        lat=np.concatenate([np.full(720,v,dtype=np.float32) for v in (60.5,60.,59.5)])
        lon=np.tile(np.arange(720,dtype=np.float32)/2,3)
        speed=np.concatenate([np.full(720,99,dtype=np.float32),
                              np.arange(720,dtype=np.float32)/10,
                              np.full(720,-40,dtype=np.float32)])
        class FakeFile:
            def write(self,*args):return None
            def seek(self,*args):return None
            def __enter__(self):return self
            def __exit__(self,*args):return False
        with patch.object(mod.tempfile,"TemporaryFile",return_value=FakeFile()), \
             patch.object(mod.eccodes,"codes_grib_new_from_file",return_value=11), \
             patch.object(mod.eccodes,"codes_get",side_effect=lambda _h,k:{
                 "shortName":"u","level":10,"typeOfLevel":"isobaricInhPa","units":"m s**-1"}[k]), \
             patch.object(mod.eccodes,"codes_get_array",side_effect=lambda _h,k:{
                 "latitudes":lat,"longitudes":lon,"values":speed}[k]), \
             patch.object(mod.eccodes,"codes_release"):
            result=mod.zonal_wind(b"GRIB")
        self.assertAlmostEqual(result,35.95,places=3)

    def test_missing_longitude_rejected(self):
        lon=np.arange(719,dtype=np.float32)/2
        lat=np.full(719,60,dtype=np.float32)
        values=np.full(719,20,dtype=np.float32)
        class FakeFile:
            def write(self,*args):return None
            def seek(self,*args):return None
            def __enter__(self):return self
            def __exit__(self,*args):return False
        with patch.object(mod.tempfile,"TemporaryFile",return_value=FakeFile()), \
             patch.object(mod.eccodes,"codes_grib_new_from_file",return_value=11), \
             patch.object(mod.eccodes,"codes_get",side_effect=lambda _h,k:{
                 "shortName":"u","level":10,"typeOfLevel":"isobaricInhPa","units":"m s**-1"}[k]), \
             patch.object(mod.eccodes,"codes_get_array",side_effect=lambda _h,k:{
                 "latitudes":lat,"longitudes":lon,"values":values}[k]), \
             patch.object(mod.eccodes,"codes_release"):
            with self.assertRaisesRegex(ValueError,"incomplete"):
                mod.zonal_wind(b"GRIB")


if __name__=="__main__":
    unittest.main()
