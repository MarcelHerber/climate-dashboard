import unittest
from datetime import date

import numpy as np
import xarray as xr

from scripts.sst.processing import process_mur_region, validate_scientific_fields


def make_normals() -> xr.Dataset:
    values = np.full((365, 2, 3), 20.0, dtype=float)
    return xr.Dataset(
        {"sst": (("time", "lat", "lon"), values)},
        coords={"time": np.arange(365), "lat": [50.0, 51.0], "lon": [-1.0, 0.0, 1.0]},
    )


def make_mur() -> xr.Dataset:
    sst = np.array([[[293.15, 294.15, np.nan], [295.15, 296.15, 297.15]]])
    ice = np.array([[[0.0, 0.15, 0.0], [0.14, np.nan, 0.0]]])
    return xr.Dataset(
        {
            "analysed_sst": (("time", "lat", "lon"), sst, {"units": "K"}),
            "sea_ice_fraction": (("time", "lat", "lon"), ice),
        },
        coords={"time": [0], "lat": [50.0, 51.0], "lon": [-1.0, 0.0, 1.0]},
    )


class SstProcessingTests(unittest.TestCase):
    def test_kelvin_to_celsius_and_anomaly(self):
        fields = process_mur_region(make_mur(), make_normals(), date(2025, 1, 1))
        self.assertAlmostEqual(float(fields.absolute_c.sel(lat=50.0, lon=-1.0)), 20.0, places=6)
        self.assertAlmostEqual(float(fields.anomaly_c.sel(lat=50.0, lon=-1.0)), 0.0, places=6)

    def test_ice_at_015_is_masked(self):
        fields = process_mur_region(make_mur(), make_normals(), date(2025, 1, 1))
        self.assertTrue(np.isnan(fields.absolute_c.sel(lat=50.0, lon=0.0)))
        self.assertFalse(bool(fields.valid_mask.sel(lat=50.0, lon=0.0)))

    def test_land_nan_remains_nan_after_regridding_and_final_mask(self):
        fields = process_mur_region(make_mur(), make_normals(), date(2025, 1, 1))
        self.assertTrue(np.isnan(fields.absolute_c.sel(lat=50.0, lon=1.0)))
        self.assertTrue(np.isnan(fields.anomaly_c.sel(lat=50.0, lon=1.0)))

    def test_validation_accepts_plausible_fields(self):
        fields = process_mur_region(make_mur(), make_normals(), date(2025, 1, 1))
        validate_scientific_fields(fields)

    def test_implausible_absolute_sst_is_rejected(self):
        mur = make_mur()
        mur["analysed_sst"].loc[dict(lat=51.0, lon=1.0)] = 320.0
        fields = process_mur_region(mur, make_normals(), date(2025, 1, 1))
        with self.assertRaisesRegex(RuntimeError, "40"):
            validate_scientific_fields(fields)


if __name__ == "__main__":
    unittest.main()
