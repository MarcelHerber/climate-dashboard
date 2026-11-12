"""Offline tests of DUETT hourly minutes -> valid daily regional sunshine hours."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_monthly_outlook_duett as duett


class DuettTests(unittest.TestCase):
    def listing(self, dates):
        return "<html>" + "".join(
            f'<a href="SDU_duett_1km_DE_60min_{stamp}_008d.nc">SDU</a>'
            for day in dates for stamp in duett.hour_keys(day)
        ) + "</html>"

    def test_index_requires_exact_1km_sdu_file_and_latest_revision(self):
        html = self.listing([date(2026, 11, 1)])
        html += '<a href="SDU_duett_1km_DE_60min_202611010050_009a.nc">NEW</a>'
        html += '<a href="SDU_duett_2km_DE_60min_202611010050_010a.nc">OLD</a>'
        listing = duett.source_index(html, "202611")
        self.assertEqual(len(listing), 24)
        self.assertTrue(listing["202611010050"].endswith("_009a.nc"))

    def test_incomplete_hour_blocks_day_not_zero(self):
        html = self.listing([date(2026, 11, 1), date(2026, 11, 3)])
        index = duett.source_index(html, "202611")
        self.assertEqual(duett.consecutive_days(index, date(2026, 11, 3)),
                         ["2026-11-01"])
        self.assertEqual(len(duett.hour_keys(date(2026, 11, 1))), 24)

    def test_coverage_rejects_missing_even_when_dark(self):
        masks = {"Deutschland": np.ones((2, 2), dtype=bool)}
        with self.assertRaises(ValueError):
            duett.area_hourly_minutes(np.array([[0, np.nan], [0, 0]]), masks)
        self.assertEqual(duett.area_hourly_minutes(np.zeros((2, 2)), masks),
                         {"Deutschland": 0.0})

    def test_previous_observations_must_be_contiguous(self):
        old = {
            "schema_version": 1, "forecast": False, "month": "2026-11",
            "data_through": "2026-11-03",
            "dates": ["2026-11-01", "2026-11-03"],
            "regions": {"Deutschland": {"daily": [2, 4]}},
        }
        with patch.object(duett, "REGIONS", ("Deutschland",)):
            with self.assertRaises(ValueError):
                duett.validate_previous(old, "2026-11")

    def test_24_sdu_hours_make_12h_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            shapes = {"Deutschland": np.ones((2, 2), dtype=bool),
                      "Hessen": np.array([[True, False], [False, False]])}
            x = np.array([0, 1000], dtype=float)
            y = np.array([0, 1000], dtype=float)
            with patch.object(duett, "REGIONS", ("Deutschland", "Hessen")), \
                 patch.object(duett, "get", return_value=self.listing([date(2026, 11, 1)]).encode()), \
                 patch.object(duett, "load_sdu", return_value=(x, y, np.ones((2, 2))*30)), \
                 patch.object(duett, "build_masks", return_value=shapes), \
                 patch.object(duett, "load_states", return_value={}):
                payload = duett.build(today=date(2026, 11, 2), previous=None,
                                      work=Path(tmp), workers=2)
            self.assertEqual(payload["dates"], ["2026-11-01"])
            self.assertEqual(payload["regions"]["Deutschland"]["daily"], [12.0])
            self.assertEqual(payload["regions"]["Hessen"]["running"], [12.0])
            self.assertFalse(payload["forecast"])


if __name__ == "__main__":
    unittest.main()
