import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import xarray as xr

from scripts.sst.daily_normals import ensure_daily_normal
from scripts.sst.climatology import select_daily_normal


class DailyNormalsTest(unittest.TestCase):
    def fake_download(self, day, path, **kwargs):
        lat = -89.875 + np.arange(720) * .25
        lon = .125 + np.arange(1440) * .25
        value = 12. if day.month == 2 else 14.
        xr.Dataset({"sst": (("lat", "lon"), np.full((720, 1440), value, dtype=np.float32))},
                   coords={"lat": lat, "lon": lon}).to_netcdf(path, engine="netcdf4")
        return path

    def test_calendar_day_is_cached_across_years(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
                "scripts.sst.daily_normals.download_oisst_normal_subset",
                side_effect=self.fake_download) as download:
            root = Path(tmp)
            day = date(2026, 11, 25)
            path = ensure_daily_normal(day, root)
            self.assertEqual(path, ensure_daily_normal(date(2027, 11, 25), root))
            self.assertEqual(download.call_count, 1)
            with xr.open_dataset(path) as ds:
                field, method = select_daily_normal(ds, day)
                self.assertEqual(method, "daily_normal")
                self.assertEqual(field.shape, (266, 472))
                self.assertAlmostEqual(float(field.mean()), 14.)
                with self.assertRaises(RuntimeError):
                    select_daily_normal(ds, date(2026, 11, 26))

    def test_leap_day_uses_two_references(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
                "scripts.sst.daily_normals.download_oisst_normal_subset",
                side_effect=self.fake_download) as download:
            day = date(2028, 2, 29)
            path = ensure_daily_normal(day, Path(tmp))
            self.assertEqual(download.call_count, 2)
            with xr.open_dataset(path) as ds:
                field, method = select_daily_normal(ds, day)
                self.assertEqual(method, "feb29_interpolated")
                self.assertAlmostEqual(float(field.mean()), 13.)

    def test_corrupt_file_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
                "scripts.sst.daily_normals.download_oisst_normal_subset",
                side_effect=self.fake_download) as download:
            root = Path(tmp)
            (root / "11-25.nc").write_bytes(b"broken")
            ensure_daily_normal(date(2026, 11, 25), root)
            self.assertEqual(download.call_count, 1)
