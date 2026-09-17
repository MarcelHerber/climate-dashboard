import unittest
from datetime import date

import numpy as np
import xarray as xr

from scripts.sst.climatology import regrid_normal, select_daily_normal


def make_normals(days: int) -> xr.Dataset:
    lat = xr.DataArray([50.0, 51.0], dims="lat")
    lon = xr.DataArray([350.0, 351.0, 10.0], dims="lon")
    values = np.zeros((days, 2, 3), dtype=float)
    for index in range(days):
        values[index, :, :] = index
    return xr.Dataset({"sst": (("time", "lat", "lon"), values)}, coords={"time": np.arange(days), "lat": lat, "lon": lon})


class SstClimatologyTests(unittest.TestCase):
    def test_non_leap_day_maps_to_correct_daily_normal(self):
        normals = make_normals(365)
        selected, method = select_daily_normal(normals, date(2025, 3, 1))
        self.assertEqual(method, "daily_normal")
        self.assertTrue(np.all(selected.values == 59.0))

    def test_leap_year_date_after_feb29_maps_back_on_365_day_reference(self):
        normals = make_normals(365)
        selected, _ = select_daily_normal(normals, date(2024, 3, 1))
        self.assertTrue(np.all(selected.values == 59.0))

    def test_feb29_uses_explicit_366th_climatology_when_present(self):
        normals = make_normals(366)
        selected, method = select_daily_normal(normals, date(2024, 2, 29))
        self.assertEqual(method, "daily_normal")
        self.assertTrue(np.all(selected.values == 59.0))

    def test_feb29_averages_feb28_and_mar1_for_365_day_reference(self):
        normals = make_normals(365)
        selected, method = select_daily_normal(normals, date(2024, 2, 29))
        self.assertEqual(method, "feb29_interpolated")
        self.assertTrue(np.all(selected.values == 58.5))

    def test_regrid_normal_normalizes_longitudes(self):
        normal = xr.DataArray(
            [[1.0, 2.0], [3.0, 4.0]],
            dims=("lat", "lon"),
            coords={"lat": [50.0, 51.0], "lon": [350.0, 10.0]},
        )
        result = regrid_normal(
            normal,
            xr.DataArray([50.0, 51.0], dims="lat"),
            xr.DataArray([-10.0, 10.0], dims="lon"),
        )
        self.assertEqual(result.dims, ("lat", "lon"))
        self.assertTrue(np.isfinite(result.sel(lon=-10.0)).all())


if __name__ == "__main__":
    unittest.main()
