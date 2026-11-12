#!/usr/bin/env python3
"""Offline regression tests for cumulative sunshine/precipitation forecasts.

The production temperature product remains a running arithmetic mean.
No live API responses are required to check the aggregation boundary.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_state_monthly_ensemble_outlook as outlook


class CumulativeOutlookTests(unittest.TestCase):
    dates = [f"2026-11-{day:02d}" for day in range(1, 6)]
    observed_dates = dates[:2]
    observed = [0.0, 4.0]
    model = {
        "dates": dates,
        "member_keys": ["member01", "member02"],
        "members": {
            "member01": [100.0, 100.0, 1.5, 2.5, 0.5],
            "member02": [100.0, 100.0, 3.5, 4.5, 1.5],
        },
        "support_points": 8,
    }

    def test_cumulative_members_start_after_observed_day(self):
        result = outlook.merge_running_outlook(
            self.observed_dates, self.observed, self.model, self.dates,
            aggregation="sum",
        )
        # Day 1 and 2 of the model must never double count observations.
        self.assertEqual(result["stats"]["mean"][:2], [None, None])
        self.assertEqual(result["stats"]["mean"][2:], [6.5, 10.0, 11.0])
        self.assertEqual(result["control"][2:], [5.5, 8.0, 8.5])
        self.assertEqual(result["forecast_from"], "2026-11-03")
        self.assertEqual(result["forecast_through"], "2026-11-05")

    def test_existing_temperature_mean_unchanged(self):
        result = outlook.merge_running_outlook(
            self.observed_dates, self.observed, self.model, self.dates,
        )
        self.assertAlmostEqual(result["stats"]["mean"][2], 6.5 / 3, places=3)
        self.assertEqual(result["stats"]["mean"][3], 10.0 / 4)

    def test_missing_observation_not_zero(self):
        self.assertEqual(outlook.running_sum([0, 1.2, None, 0.8]),
                         [0.0, 1.2, None, 2.0])
        with self.assertRaises(ValueError):
            outlook.merge_running_outlook(
                self.observed_dates, [4.0, None], self.model, self.dates,
                aggregation="sum",
            )

    def test_negative_daily_sum_rejected(self):
        with self.assertRaises(ValueError):
            outlook.running_sum([1.0, -0.1])
        with self.assertRaises(ValueError):
            outlook.merge_running_outlook(
                self.observed_dates, [1, -1], self.model, self.dates,
                aggregation="sum",
            )

    def test_model_gap_stops_forecast_and_prevents_fabricated_zero(self):
        model = {
            **self.model,
            "member_keys": ["member01"],
            "members": {"member01": [1, 1, 2.0, None, 8]},
        }
        result = outlook.merge_running_outlook(
            self.observed_dates, self.observed, model, self.dates,
            aggregation="sum",
        )
        self.assertEqual(result["stats"]["mean"], [None, None, 6.0, None, None])


if __name__ == "__main__":
    unittest.main()
