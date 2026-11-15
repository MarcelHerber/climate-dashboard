import unittest
from datetime import datetime, timezone
import numpy as np
from scripts.ifs_weekly_01 import LEADS, valid_times, weekly_mean, era5_expected, normals_from_year, interpolate_reference, validate_forecast_metadata


class WeeklyTests(unittest.TestCase):
    def test_exact_168_hour_trapezoid(self):
        fields = {h: np.array([[float(h)]]) for h in range(0, 169, 6)}
        self.assertEqual(len(LEADS), 29)
        np.testing.assert_allclose(weekly_mean(fields), [[84.]])
        fields.pop(150)
        with self.assertRaises(ValueError):
            weekly_mean(fields)

    def test_valid_times_cross_year(self):
        run = datetime(2026, 12, 30, 12, tzinfo=timezone.utc)
        ts = valid_times(run)
        self.assertEqual(ts[-1], datetime(2027, 1, 6, 12, tzinfo=timezone.utc))
        self.assertEqual(len(ts), 29)

    def test_era5_leap_day_calendar(self):
        self.assertEqual(len(era5_expected(1991, 2)), 112)
        self.assertEqual(len(era5_expected(1992, 2)), 116)
        self.assertEqual(era5_expected(1992, 2)[-1], np.datetime64('1992-02-29T18'))

    def test_missing_or_duplicate_clock_times_rejected(self):
        times = era5_expected(1992, 2)
        values = np.ones((len(times), 2, 2)) * 280.
        result = normals_from_year(1992, 2, times[::-1], values[::-1])
        self.assertEqual(result.shape, (29, 4, 2, 2))
        np.testing.assert_allclose(result, 280.)
        with self.assertRaises(ValueError):
            normals_from_year(1992, 2, times[:-1], values[:-1])
        bad = times.copy(); bad[1] = bad[0]
        with self.assertRaises(ValueError):
            normals_from_year(1992, 2, bad, values)

    def test_bilinear_reference_preserves_linear_gradient(self):
        original = np.array([[10., 20.], [30., 40.]])
        actual = interpolate_reference(original, np.array([1., 0.]), np.array([0., 1.]), np.array([.75, .25]), np.array([.25, .75]))
        np.testing.assert_allclose(actual, [[17.5, 22.5], [27.5, 32.5]])
        with self.assertRaises(ValueError):
            interpolate_reference(original, np.array([1., 0.]), np.array([0., 1.]), np.array([1.1]), np.array([.5]))

    def test_metadata_rejects_mixed_initialization_and_coarse_grid(self):
        run = datetime(2026, 11, 14, 0, tzinfo=timezone.utc)
        times = valid_times(run)
        data = {'schema':1,'type':'ifs_0p1_seven_day_forecast','grid_degrees':.1,'width':1801,'height':601,
                'lat_north':85.,'lat_south':25.,'lon_west':-80.,'lon_east':100.,
                'run_utc':'2026-11-14T00:00:00Z','valid_from_utc':'2026-11-14T00:00:00Z',
                'valid_to_utc':'2026-11-21T00:00:00Z','period_days':7,'sample_count':29,'lead_hours':list(range(0,169,6)),
                'sources':[{'forecast_hour':h,'valid_utc':t.isoformat().replace('+00:00','Z'),'sha256':'a'*64,'bytes':200000} for h,t in zip(range(0,169,6),times)]}
        validate_forecast_metadata(data, run)
        data['sources'][2]['valid_utc']='2026-11-15T12:00:00Z'
        with self.assertRaises(ValueError): validate_forecast_metadata(data, run)
        data['sources'][2]['valid_utc']='2026-11-14T12:00:00Z'
        data['grid_degrees']=.25
        with self.assertRaises(ValueError): validate_forecast_metadata(data, run)


if __name__ == '__main__':
    unittest.main()
