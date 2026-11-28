import unittest
from datetime import date
from urllib.parse import unquote
import numpy as np
import xarray as xr

from scripts.sst.mur_mirror import _tile_query, _validated_tile


class MurMirrorTest(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 11, 27)
        self.lat = np.array([50., 50.01])
        self.lon = np.array([-1., -.99])
        self.ds = xr.Dataset(
            {"analysed_sst": (("time", "latitude", "longitude"), np.ones((1,2,2))*12, {"units":"degree_C"}),
             "sea_ice_fraction": (("time", "latitude", "longitude"), np.zeros((1,2,2)))},
            coords={"time": [np.datetime64("2026-11-27T09:00:00")],
                    "latitude":self.lat, "longitude":self.lon})

    def test_native_request_and_variables(self):
        q = unquote(_tile_query(self.day, -1, 50, -.99, 50.01))
        self.assertIn("analysed_sst[(2026-11-27T09:00:00Z)][(50.00):1:(50.01)]", q)
        self.assertIn("sea_ice_fraction", q)
        self.assertIn("jplMURSST41.nc?", q)

    def test_date_and_native_grid(self):
        out = _validated_tile(self.ds, self.day, self.lat, self.lon)
        self.assertEqual(out.analysed_sst.dims, ("time","lat","lon"))
        self.assertAlmostEqual(float(out.analysed_sst.mean()),12.)
        with self.assertRaises(RuntimeError):
            _validated_tile(self.ds, date(2026,11,26), self.lat, self.lon)
        with self.assertRaises(RuntimeError):
            _validated_tile(self.ds, self.day, self.lat, np.array([-1.,-.98]))
