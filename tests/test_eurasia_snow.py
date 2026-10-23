#!/usr/bin/env python3
"""No fabricated observations: test geographic mask, area sum and climatology."""
import datetime as dt
import gzip
import unittest
import numpy as np
from scripts.update_eurasia_snow import (
    COLUMNS, ROWS, ROW, FILENAME, HISTORY_YEARS,
    geographic_mask_and_weights, area_for_day, calculate_climatology,
    calculate_month_climatology, calendar_dates_for_season, WINTER_MONTHS, parse_ascii,
)


class IMSChecks(unittest.TestCase):
    def test_ascii_strict(self):
        rows = [b"2" * COLUMNS for _ in range(ROWS)]
        rows[0] = b"4" * COLUMNS
        raw = gzip.compress(b"IMS 24 km header\n" + b"\n".join(rows) + b"\n")
        parsed = parse_ascii(raw)
        self.assertEqual(parsed.shape, (ROWS, COLUMNS))
        self.assertEqual(int(parsed[0, 30]), 4)
        self.assertEqual(int(parsed[1, 30]), 2)
        with self.assertRaises(ValueError):
            parse_ascii(gzip.compress(b"\n".join(rows[:-1])))

    def test_region_and_area(self):
        mask, weights = geographic_mask_and_weights()
        self.assertEqual(mask.shape, (ROWS, COLUMNS))
        self.assertGreater(np.count_nonzero(mask), 50000)
        self.assertLess(np.count_nonzero(mask), 500000)
        self.assertTrue(np.isfinite(weights).all())
        fake = np.full((ROWS, COLUMNS), 2, dtype=np.uint8)
        positions = np.flatnonzero(mask)
        fake.flat[positions[:3000]] = 4
        result = area_for_day(fake, mask, weights)
        expected = round(float(weights.flat[positions[:3000]].sum()), 5)
        self.assertEqual(result, expected)
        fake.fill(3)
        with self.assertRaises(ValueError):
            area_for_day(fake, mask, weights)

    def test_period(self):
        self.assertEqual(len(HISTORY_YEARS), 26)
        self.assertNotIn(2014, HISTORY_YEARS)
        daily = {f"{y}-10-01": float(y-1990) for y in HISTORY_YEARS[:11]}
        series = calculate_climatology(daily)
        self.assertIsNotNone(series[0]["mean"])
        self.assertEqual(series[0]["years"], 11)
        self.assertIsNone(series[1]["mean"])

    def test_winter_seasons(self):
        self.assertEqual(WINTER_MONTHS, (10, 11, 12, 1, 2, 3))
        winter = calendar_dates_for_season(2023)
        self.assertEqual(winter[0], dt.date(2023, 10, 1))
        self.assertEqual(winter[-1], dt.date(2024, 3, 31))
        self.assertIn(dt.date(2024, 2, 29), winter)
        self.assertEqual(len(winter), 183)
        regular = calendar_dates_for_season(2024)
        self.assertEqual(len(regular), 182)
        self.assertNotIn(dt.date(2025, 2, 29), regular)

    def test_month_reference_and_february_29(self):
        daily = {f"{year}-02-29": float(year) for year in (2000,2004,2008,2012,2016,2020)}
        daily.update({f"{year}-11-30": float(year) for year in HISTORY_YEARS[:12]})
        feb = calculate_month_climatology(daily, 2)
        self.assertEqual(len(feb), 29)
        self.assertEqual(feb[28]["years"], 6)
        self.assertEqual(feb[28]["min_years"], 5)
        self.assertIsNotNone(feb[28]["mean"])
        november = calculate_month_climatology(daily, 11)
        self.assertEqual(len(november), 30)
        self.assertEqual(november[-1]["years"], 12)
        self.assertIsNotNone(november[-1]["stddev"])
        for month, length in ((10,31),(11,30),(12,31),(1,31),(2,29),(3,31)):
            self.assertEqual(len(calculate_month_climatology({},month)), length)

    def test_filename(self):
        m = FILENAME.fullmatch("ims2026296_00UTC_24km_v1.3.asc.gz")
        self.assertIsNotNone(m)
        self.assertEqual((m.group(1), m.group(2)), ("2026", "296"))


if __name__ == "__main__":
    unittest.main()
