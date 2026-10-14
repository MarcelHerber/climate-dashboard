"""Synthetic tests for compact DWD station daily temperature history."""
import base64
import importlib.util
from datetime import date
from pathlib import Path
import struct
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "station_threshold_history", ROOT / "scripts/station_threshold_history.py"
)
thresholds = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(thresholds)


class ThresholdArchiveTests(unittest.TestCase):
    def test_leap_day_and_missing_values_keep_calendar_positions(self):
        values = {
            date(2020, 2, 28): (17.5, -1.1, 8.8, None, None),
            date(2020, 2, 29): (None, -2.0, 6.3, None, None),
            date(2020, 3, 1): (16.0, 1.0, None, None, None),
            date(2021, 3, 1): (18.0, None, None, None, None),
        }
        packed = thresholds.build_temperature_history("01234", values)
        self.assertEqual(packed["format"], "dwd-tx-tn-tm-zlib16-v1")
        self.assertEqual(packed["years"], [2020, 2021])
        decoded = zlib.decompress(base64.b64decode(packed["data"]))
        self.assertEqual(len(decoded), 2 * 366 * 3 * 2)
        numbers = struct.unpack("<2196h", decoded)
        def value(year_index, day_index, field):
            return numbers[year_index * 1098 + day_index * 3 + field]
        self.assertEqual(value(0, 58, 0), 175)
        self.assertEqual(value(0, 59, 0), thresholds.MISSING)
        self.assertEqual(value(0, 59, 1), -20)
        self.assertEqual(value(0, 60, 0), 160)
        self.assertEqual(value(1, 59, 0), 180)
        self.assertEqual(value(1, 59, 1), thresholds.MISSING)
        self.assertEqual(packed["counts"], [[2020, 2, 3, 2], [2021, 1, 0, 0]])

    def test_unusable_daily_measurements_do_not_create_year(self):
        self.assertEqual(
            thresholds.build_temperature_history("00001", {
                date(1999, 1, 1): (None, None, None, None, None)
            })["years"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
