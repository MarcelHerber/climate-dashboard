"""Offline checks for HYRAS + ensemble precipitation output."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_state_monthly_precip_outlook as precip


class StateMonthlyPrecipTests(unittest.TestCase):
    def make_observed(self):
        return {
            "schema_version": 1, "forecast": False, "unit": "mm",
            "month": "2026-11", "data_through": "2026-11-02",
            "dates": ["2026-11-01", "2026-11-02"],
            "regions": {r: {"daily": [1.5, 0.5]} for r in precip.REGION_ORDER},
        }

    def test_accumulates_once_and_preserves_future_gap(self):
        doc = self.make_observed()
        model = {"gefs": {
            "label": "GEFS", "api_model": "ncep_gefs_seamless",
            "member_count": 1, "run": None,
            "regions": {r: {
                "dates": ["2026-11-03", "2026-11-04"],
                "member_keys": ["precipitation_sum_member01"],
                "members": {"precipitation_sum_member01": [3.0, 2.0]},
                "support_points": 8,
            } for r in precip.REGION_ORDER},
        }}
        out = precip.build_payload(doc, model, {})
        self.assertEqual(out["parameter"], "precipitation")
        self.assertEqual(out["regions"]["Hessen"]["observed_running"][:4], [1.5, 2.0, None, None])
        self.assertEqual(out["regions"]["Hessen"]["models"]["gefs"]["control"][:5], [None, None, 5.0, 7.0, None])
        self.assertFalse(out["climatology_available"])

    def test_rejects_missing_observed_day(self):
        doc = self.make_observed()
        doc["dates"] = ["2026-11-01", "2026-11-03"]
        doc["data_through"] = "2026-11-03"
        with self.assertRaises(ValueError):
            precip.validate_observed(doc)

    def test_rejects_missing_region_or_negative(self):
        doc = self.make_observed()
        del doc["regions"]["Hessen"]
        with self.assertRaises(ValueError):
            precip.validate_observed(doc)
        doc = self.make_observed()
        doc["regions"]["Hessen"]["daily"][0] = -0.5
        with self.assertRaises(ValueError):
            precip.validate_observed(doc)


if __name__ == "__main__":
    unittest.main()
