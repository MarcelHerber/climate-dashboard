"""Synthetic NSIDC v4 CSV tests: correct year/day alignment and 1991–2020 SD."""
from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_sea_ice as ice


class SeaIceIndexTest(unittest.TestCase):
    def test_csv_units_and_bad_nsidc_day(self):
        raw = ("Year, Month, Day, Extent, Missing, Source Data\n"
               "YYYY, MM, DD, 10^6 sq km, 10^6 sq km, Source\n"
               "1984, 9, 14, 12.300, 0, source\n"
               "2026, 10, 12, 10.123, 0.000, source\n")
        result = ice.parse_daily(raw)
        self.assertEqual(result, {date(2026, 10, 12): 10.123})

    def test_doy_alignment_std_and_missing(self):
        values = {}
        start = date(1979, 1, 1)
        end = date(2026, 10, 12)
        d = start
        while d <= end:
            # Odd historical dates are absent before Aug 1987, as in SMMR.
            if d.year >= 1988 or d.toordinal() % 2 == 0:
                values[d] = 12.0 + (d.year - 1991) * 0.01
            d += timedelta(days=1)
        sample = ice.build_hemisphere(values, "north", now=date(2026, 10, 14))
        self.assertEqual(len(sample["normal"]), 366)
        self.assertEqual(sample["normal"][ice.DAY_INDEX["02-29"]][2], 8)
        self.assertEqual(sample["normal"][ice.DAY_INDEX["03-01"]][2], 30)
        self.assertEqual(sample["years"]["2023"][ice.DAY_INDEX["02-29"]], None)
        self.assertEqual(sample["years"]["2024"][ice.DAY_INDEX["03-01"]], values[date(2024, 3, 1)])
        self.assertGreater(sample["normal"][ice.DAY_INDEX["03-01"]][1], 0.08)
        self.assertEqual(sample["latest_date"], "2026-10-12")

    def test_old_file_rejected(self):
        with self.assertRaisesRegex(ValueError, "insufficient"):
            ice.build_hemisphere({date(2024, 1, 1): 14.2}, "south")

    def test_nsidc_calendar_has_366_unique_entries(self):
        self.assertEqual(ice.DAYS[59], "02-29")
        self.assertEqual(ice.DAYS[60], "03-01")
        self.assertEqual(len(set(ice.DAYS)), 366)


if __name__ == "__main__":
    unittest.main()
