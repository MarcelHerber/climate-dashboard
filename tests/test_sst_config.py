import unittest
from datetime import date

from scripts.sst.config import (
    ABSOLUTE_RANGE,
    ANOMALY_RANGE,
    ARCHIVE_START,
    MUR_COLLECTION_ID,
    REGIONS,
    SEA_ICE_THRESHOLD,
)


class SstConfigTests(unittest.TestCase):
    def test_sst_stage1_contract(self):
        self.assertEqual(
            list(REGIONS),
            ["europe", "mediterranean", "north_atlantic", "nordic_seas"],
        )
        self.assertEqual(REGIONS["europe"].bounds, (-30.0, 25.0, 45.0, 72.0))
        self.assertEqual(REGIONS["europe"].download_bounds, (-31.5, 23.5, 46.5, 73.5))
        self.assertEqual(REGIONS["mediterranean"].bounds, (-18.0, 30.0, 36.0, 46.0))
        self.assertEqual(REGIONS["mediterranean"].download_bounds, (-19.5, 28.5, 37.5, 47.5))
        self.assertEqual(REGIONS["north_atlantic"].bounds, (-65.0, 20.0, 25.0, 78.0))
        self.assertEqual(REGIONS["north_atlantic"].download_bounds, (-66.5, 18.5, 26.5, 79.5))
        self.assertEqual(REGIONS["nordic_seas"].bounds, (-35.0, 50.0, 50.0, 84.0))
        self.assertEqual(REGIONS["nordic_seas"].download_bounds, (-36.5, 48.5, 51.5, 85.0))
        self.assertEqual(ABSOLUTE_RANGE, (-2.0, 34.0))
        self.assertEqual(ANOMALY_RANGE, (-6.0, 6.0))
        self.assertEqual(SEA_ICE_THRESHOLD, 0.15)
        self.assertEqual(ARCHIVE_START, date(2020, 1, 1))
        self.assertEqual(MUR_COLLECTION_ID, "C1996881146-POCLOUD")


if __name__ == "__main__":
    unittest.main()
