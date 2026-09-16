import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image

from scripts.sst.config import REGIONS
from scripts.sst.processing import ProcessedFields
from scripts.sst.render import render_map, validate_rendered_map, view_scale


class SstRenderTests(unittest.TestCase):
    def test_fixed_view_scales(self):
        self.assertEqual(view_scale("absolute")[:2], (-2.0, 34.0))
        self.assertEqual(view_scale("anomaly")[:2], (-6.0, 6.0))
        with self.assertRaises(ValueError):
            view_scale("other")

    @unittest.skipUnless(importlib.util.find_spec("cartopy"), "cartopy not installed in local harness")
    def test_rendered_webp_has_fixed_geometry(self):
        lat = xr.DataArray([50.0, 51.0, 52.0], dims="lat", coords={"lat": [50.0, 51.0, 52.0]})
        lon = xr.DataArray([-2.0, 0.0, 2.0, 4.0], dims="lon", coords={"lon": [-2.0, 0.0, 2.0, 4.0]})
        absolute = xr.DataArray(
            np.array([[10, 11, 12, 13], [11, 12, 13, 14], [12, 13, 14, 15]], dtype=float),
            dims=("lat", "lon"), coords={"lat": lat, "lon": lon},
        )
        fields = ProcessedFields(
            lon=lon,
            lat=lat,
            absolute_c=absolute,
            anomaly_c=absolute - 12.0,
            valid_mask=xr.ones_like(absolute, dtype=bool),
            reference_method="daily_normal",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.webp"
            render_map(fields, REGIONS["europe"], date(2026, 9, 14), "absolute", path)
            validate_rendered_map(path, REGIONS["europe"])
            with Image.open(path) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.size, (1600, 1050))
            self.assertGreater(path.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
