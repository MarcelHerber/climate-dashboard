import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import numpy as np
import xarray as xr

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import build_polar_vortex_map as vortex


class PolarVortexMapTests(unittest.TestCase):
    def test_request_is_verified_utc_daily_z10_not_forecast(self):
        request=vortex.request_for(date(2026,10,7))
        self.assertEqual(request["variable"],["geopotential"])
        self.assertEqual(request["pressure_level"],["10"])
        self.assertEqual(request["daily_statistic"],"daily_mean")
        self.assertEqual(request["frequency"],"6_hourly")
        self.assertEqual(request["area"],[90,-180,25,180])
        self.assertEqual(request["product_type"],"reanalysis")

    def dataset(self, stamp="2026-10-07", gap=False):
        lats=np.arange(90,24,-1)
        lons=np.arange(-180,181)
        lon_term=400*np.cos(np.deg2rad(lons))
        lat_term=(90-lats)[:,None]*30
        field=np.full((lats.size,lons.size),29200.)+lon_term[None,:]+lat_term
        if gap:
            field[0,0]=float("nan")
        return xr.Dataset(
            {"z":(("valid_time","pressure_level","latitude","longitude"),
                  (field*vortex.GRAVITY)[None,None,:,:])},
            coords={"valid_time":[np.datetime64(stamp)],"pressure_level":[10],
                    "latitude":lats,"longitude":lons})

    def test_validated_grid_converts_geopotential_to_height(self):
        lat,lon,z=vortex.validated_field(self.dataset(),date(2026,10,7))
        self.assertEqual(z.shape,(66,360))
        self.assertEqual(len(lon),360)
        self.assertEqual(len(lat),66)
        self.assertGreater(z.min(),25000)
        self.assertLess(z.max(),36000)

    def test_png_renderer_with_synthetic_test_grid(self):
        # Purely internal test data, NEVER published as a real ERA5 map.
        with tempfile.TemporaryDirectory() as tmp:
            lats,lons,z=vortex.validated_field(self.dataset(),date(2026,10,7))
            png=Path(tmp)/"render_test.png"
            vortex.plot_map(lats,lons,z,date(2026,10,7),png)
            self.assertTrue(png.exists())
            self.assertGreater(png.stat().st_size,25000)
            self.assertEqual(png.read_bytes()[:8],bytes.fromhex("89504e470d0a1a0a"))

    def test_wrong_day_rejected(self):
        with self.assertRaisesRegex(ValueError,"instead"):
            vortex.validated_field(self.dataset(),date(2026,10,8))

    def test_missing_grid_cell_rejected(self):
        with self.assertRaisesRegex(ValueError,"Nonfinite|Missing"):
            vortex.validated_field(self.dataset(gap=True),date(2026,10,7))


if __name__=="__main__":
    unittest.main()
