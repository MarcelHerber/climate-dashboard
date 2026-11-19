import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np

from scripts.sst.regional_years import regional_mean, region_bounds, complete_year, pending_years, publish_series, atomic_csv


class RegionalMeanTests(unittest.TestCase):
    def test_greenwich_and_latitude_weighting(self):
        lat = np.array([0., 60.])
        lon = np.array([5., 30., 355.])
        field = np.array([[10., 99., 20.], [30., 99., np.nan]])
        # (10 + 20 + 30*0.5) / 2.5; NaN land contributes no area.
        self.assertAlmostEqual(regional_mean(field, lat, lon, (-10., -1., 10., 61.)), 18.)

    def test_non_crossing_pacific(self):
        lat = np.array([0.])
        lon = np.array([10., 150., 250., 350.])
        field = np.array([[99., 12., 20., 99.]])
        self.assertAlmostEqual(regional_mean(field, lat, lon, region_bounds()['pacific']), 16.)

    def test_no_ocean_points(self):
        with self.assertRaises(ValueError):
            regional_mean(np.array([[np.nan]]), np.array([0.]), np.array([5.]), (0., -1., 10., 1.))

    def test_complete_leap_year(self):
        dates = {(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(366)}
        self.assertTrue(complete_year(2020, dates))
        dates.remove('2020-02-29')
        self.assertFalse(complete_year(2020, dates))

    def test_resume_only_missing_years(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            keys = list(region_bounds())
            atomic_csv(root / 'annual/2020.csv', ['date', *keys],
                       ([(date(2020, 1, 1) + timedelta(days=i)).isoformat(), *([8.]*len(keys))] for i in range(366)))
            pending = pending_years(root, date(2021, 4, 1))
            self.assertEqual(pending[0], 2021)
            self.assertNotIn(2020, pending)
            self.assertEqual(pending[1], 2019)
            self.assertFalse(publish_series(root))
            self.assertFalse((root/'europe_daily_sst.csv').exists())

    def test_keep_very_warm_but_valid_grid_cells(self):
        self.assertAlmostEqual(regional_mean(np.array([[36.5, 20.]]), np.array([0.]), np.array([5., 6.]), (0., -1., 10., 1.)), 28.25)

if __name__ == '__main__':
    unittest.main()
