import unittest
from datetime import datetime, timezone, timedelta
import numpy as np
from scripts.strato_height_data import sector_means, reference_means, validate_forecast, NOAA_LEVELS, REGIONS

class HeightTests(unittest.TestCase):
    def test_wrap_and_weight(self):
        lat = np.array([60., 60., 60., 60., 75., 75., 75., 75.])
        lon = np.array([0., 180., 350., 90., 0., 180., 350., 90.])
        height = np.array([10., 80., 20., 50., 30., 80., 40., 50.])
        a = sector_means(lat, lon, height)
        self.assertAlmostEqual(a['atlantic'], (15*.5 + 35*np.cos(np.deg2rad(75)))/(.5+np.cos(np.deg2rad(75))), places=5)
        self.assertAlmostEqual(a['pacific'], 80.)
    def test_reference_needs_all_thirty_years(self):
        days = {f'{year}-11-19': {r: {'10': float(year-1990)} for r in REGIONS} for year in range(1991,2021)}
        self.assertEqual(reference_means(days)['11-19']['atlantic']['10'],15.5)
        days.pop('1991-11-19')
        self.assertNotIn('11-19',reference_means(days))
    def test_forecast_rejects_missing_day_or_level(self):
        cycle = datetime(2026,11,19,tzinfo=timezone.utc)
        dates={(cycle+timedelta(days=i)).strftime('%Y-%m-%d'): {r: {str(p): 3000. for p in NOAA_LEVELS} for r in REGIONS} for i in range(16)}
        payload={'model':'gefs','cycle':'2026-11-19T00:00:00Z','levels':NOAA_LEVELS,'days':dates}
        self.assertTrue(validate_forecast(payload,'gefs',cycle+timedelta(hours=9)))
        del dates['2026-11-21']['atlantic']['10']
        self.assertFalse(validate_forecast(payload,'gefs',cycle+timedelta(hours=9)))

if __name__=='__main__': unittest.main()
