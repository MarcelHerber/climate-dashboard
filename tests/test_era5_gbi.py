import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


class Era5GbiTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.find_spec('update_era5_gbi')
        self.assertIsNotNone(spec, 'ERA5 GBI producer is missing')
        import update_era5_gbi as gbi
        self.gbi = gbi

    def test_grid_area_weighting_and_unit_conversion(self):
        lat = np.arange(80, 59.75, -.25)
        lon = np.arange(-80, -19.75, .25)
        heights = np.broadcast_to(np.where(lat[:, None] >= 70, 5400., 5300.), (81, 241))
        mean = self.gbi.area_mean(heights[None] * 9.80665, lat, lon)
        self.assertAlmostEqual(mean[0], 5338.452698, places=4)

    def test_incomplete_and_nan_grid_is_rejected(self):
        lat = np.arange(80, 59.75, -.25)
        lon = np.arange(-80, -19.75, .25)
        data = np.full((1, 81, 241), 5300 * 9.80665)
        with self.assertRaises(ValueError):
            self.gbi.area_mean(data[:, :-1], lat[:-1], lon)
        data[0, 0, 0] = np.nan
        with self.assertRaises(ValueError):
            self.gbi.area_mean(data, lat, lon)

    def sample(self):
        return {f'{y}-{m:02}': 5300 + y - 1991 + m * 10
                for y in range(1940, 2022) for m in range(1, 13)}

    def test_archive_contains_seasonal_standardization_and_complete_reference(self):
        archive = self.gbi.build_archive(self.sample())
        self.gbi.validate_archive(archive)
        self.assertEqual(archive['first_month'], '1940-01')
        self.assertEqual(archive['latest_month'], '2021-12')
        self.assertEqual(archive['reference_months'], 360)
        values = dict(archive['monthly'])
        self.assertAlmostEqual(values['2021-01'], 1.761, places=3)
        self.assertEqual(values['2021-01'], values['2021-12'])

    def test_reference_missing_month_and_bad_archive_are_rejected(self):
        values = self.sample()
        del values['2005-03']
        with self.assertRaises(ValueError):
            self.gbi.build_archive(values)
        archive = self.gbi.build_archive(self.sample())
        archive['reference_months'] = 359
        with self.assertRaises(ValueError):
            self.gbi.validate_archive(archive)


if __name__ == '__main__':
    unittest.main()
