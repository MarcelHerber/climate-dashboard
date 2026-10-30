"""Regression tests for exact NOAA OISST daily URL construction."""
from datetime import date
from scripts.sst.ocean_sources import _ncei_daily_url
import unittest

class NOAAUrlTests(unittest.TestCase):
    def test_preliminary_only_changes_filename(self):
        url = _ncei_daily_url(date(2026, 10, 29), preliminary=True)
        self.assertEqual(url,
            "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/"
            "v2.1/access/avhrr/202610/oisst-avhrr-v02r01.20261029_preliminary.nc")
        self.assertEqual(url.count("_preliminary"), 1)
    def test_final_file_unchanged(self):
        self.assertEqual(_ncei_daily_url(date(2026, 10, 29)),
            "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/"
            "v2.1/access/avhrr/202610/oisst-avhrr-v02r01.20261029.nc")

if __name__ == "__main__":
    unittest.main()
