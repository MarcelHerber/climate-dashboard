import unittest
from datetime import date

import numpy as np
import xarray as xr

from scripts.sst.config import oisst_regions_for_day
from scripts.sst.ocean_build import _processed_fields, _standardize_dataset
from scripts.sst.ocean_sources import ocean_union_bounds


class HistoricalOceanGeographyTests(unittest.TestCase):
    def test_historical_europe_crosses_greenwich(self):
        coords = {"lat": [31., 40.], "lon": [0.125, 10.125, 340.125, 350.125]}
        actual = _standardize_dataset(xr.Dataset({"sst": (("lat", "lon"), np.full((2, 4), 17.))}, coords=coords))
        normal = _standardize_dataset(xr.Dataset({"sst": (("lat", "lon"), np.full((2, 4), 15.))}, coords=coords))
        region = oisst_regions_for_day(date(1981, 9, 1))["europe"]
        fields = _processed_fields(actual, normal, region)
        np.testing.assert_allclose(fields.lon, [-19.875, -9.875, 0.125, 10.125])
        np.testing.assert_allclose(fields.absolute_c, 17.)
        np.testing.assert_allclose(fields.anomaly_c, 2.)
        actual["ice"] = xr.DataArray([[0., .2, 0., 0.], [0., 0., 0., 0.]], dims=("lat", "lon"), coords=actual.coords)
        masked = _processed_fields(actual, normal, region)
        self.assertTrue(np.isnan(masked.absolute_c.sel(lat=31., lon=10.125)))
        self.assertEqual(float(masked.absolute_c.sel(lat=40., lon=10.125)), 17.)

    def test_normals_cover_historical_europe(self):
        self.assertEqual(ocean_union_bounds(include_europe=True), (0., -61.5, 360., 85.))
        self.assertGreater(ocean_union_bounds()[0], 0.)


if __name__ == "__main__":
    unittest.main()
