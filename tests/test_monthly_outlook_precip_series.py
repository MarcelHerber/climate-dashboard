"""Offline tests for daily HYRAS-DE-PRE regional observations."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_monthly_outlook_precip_series as obs


class PrecipObservationTests(unittest.TestCase):
    def test_partial_coverage_is_not_a_dry_day(self):
        field = np.asarray([[0, np.nan], [1, 1]], dtype=float)
        mask = np.ones((2, 2), dtype=bool)
        self.assertEqual(obs.daily_area_mean(field, mask), (None, 0.75))
        self.assertEqual(obs.daily_area_mean(field, mask, threshold=0.7), (round(2/3, 4), 0.75))

    def test_negative_and_shape_mismatch_rejected_or_masked(self):
        field = np.asarray([[-1, 5], [5, 5]], dtype=float)
        result, coverage = obs.daily_area_mean(field, np.ones((2, 2), dtype=bool))
        self.assertIsNone(result)
        self.assertEqual(coverage, .75)
        with self.assertRaises(ValueError):
            obs.daily_area_mean(field, np.ones((3, 3), dtype=bool))

    def test_daily_region_and_running_month_sum(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "data"
            work = Path(folder) / "work"
            root.mkdir()
            work.mkdir()
            (root / "hyras_index.json").write_text(json.dumps({
                "data_through": "2026-11-03", "daily_source_file": "pr.nc",
            }))
            arr = np.asarray([
                [[1, 2], [3, 4]],
                [[1, 1], [1, 1]],
                [[0, 0], [0, 0]],
            ], dtype=np.float32)
            xr.Dataset({"pr": (("time", "y", "x"), arr)}, coords={
                "time": pd.date_range("2026-11-01", periods=3),
                "x": [0, 1], "y": [0, 1],
            }).to_netcdf(work / "pr.nc")
            masks = {
                "Deutschland": np.ones((2, 2), dtype=bool),
                "Hessen": np.asarray([[True, False], [False, False]]),
            }
            with patch.object(obs, "REGIONS", ("Deutschland", "Hessen")), \
                 patch.object(obs, "load_states", return_value={}), \
                 patch.object(obs, "build_masks", return_value=masks):
                result = obs.build(root, work)
            self.assertEqual(result["data_through"], "2026-11-03")
            self.assertEqual(result["regions"]["Deutschland"]["daily"], [2.5, 1.0, 0.0])
            self.assertEqual(result["regions"]["Deutschland"]["running"], [2.5, 3.5, 3.5])
            self.assertEqual(result["regions"]["Hessen"]["running"], [1, 2, 2])
            self.assertFalse(result["complete"])
            self.assertFalse(result["forecast"])


if __name__ == "__main__":
    unittest.main()
