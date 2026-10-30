"""Gregorian date-axis coverage for year-round HYRAS anomaly references."""
import unittest
from datetime import date
import numpy as np

from scripts.build_hyras_full_year_anomaly_reference import (
    calendar_codes, day_codes, reference_index,
)


class FullYearReferenceTests(unittest.TestCase):
    def test_leap_day_axis(self):
        codes = calendar_codes()
        self.assertEqual(len(codes), 366)
        self.assertEqual(len(np.unique(codes)), 366)
        self.assertEqual(int(codes[0]), 101)
        self.assertIn(229, codes)
        self.assertEqual(int(codes[-1]), 1231)

    def test_non_leap_day_codes(self):
        days = np.arange("2026-01-01", "2027-01-01", dtype="datetime64[D]")
        codes = day_codes(days)
        self.assertEqual(len(codes), 365)
        self.assertNotIn(229, codes)
        self.assertEqual(len(set(codes).difference(set(calendar_codes()))), 0)

    def test_reference_periods(self):
        self.assertEqual(reference_index(1961), 0)
        self.assertEqual(reference_index(1990), 0)
        self.assertEqual(reference_index(1991), 1)
        self.assertEqual(reference_index(2020), 1)
        with self.assertRaises(ValueError):
            reference_index(2026)


if __name__ == "__main__":
    unittest.main()
