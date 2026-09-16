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
            ["europe", "mediterranean", "north_baltic", "north_atlantic", "nordic_seas"],
        )
        self.assertEqual(REGIONS["europe"].bounds, (-30.0, 30.0, 45.0, 72.0))
        self.assertEqual(REGIONS["mediterranean"].bounds, (-6.0, 29.0, 38.0, 47.0))
        self.assertEqual(REGIONS["north_baltic"].bounds, (-12.0, 48.0, 32.0, 66.0))
        self.assertEqual(REGIONS["north_atlantic"].bounds, (-60.0, 25.0, 20.0, 70.0))
        self.assertEqual(REGIONS["nordic_seas"].bounds, (-45.0, 55.0, 50.0, 82.0))
        self.assertEqual(ABSOLUTE_RANGE, (-2.0, 34.0))
        self.assertEqual(ANOMALY_RANGE, (-6.0, 6.0))
        self.assertEqual(SEA_ICE_THRESHOLD, 0.15)
        self.assertEqual(ARCHIVE_START, date(2020, 1, 1))
        self.assertEqual(MUR_COLLECTION_ID, "C1996881146-POCLOUD")


if __name__ == "__main__":
    unittest.main()
