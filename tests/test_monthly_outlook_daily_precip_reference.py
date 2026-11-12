"""Regression tests for a true daily HYRAS 1991–2020 regional climate curve."""
import calendar
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import build_monthly_outlook_daily_precip_reference as builder


class DailyPrecipClimateTests(unittest.TestCase):
    def test_daily_region_means_and_coverage(self):
        grid=np.array([
            [[0,2],[4,6]],
            [[2,4],[6,8]],
        ],dtype=np.float32)
        masks={"Deutschland":np.array([[True,True],[True,True]]),
               "Hessen":np.array([[True,False],[True,False]])}
        with patch.object(builder,"REGIONS",("Deutschland","Hessen")):
            out=builder.region_daily_series(grid,masks)
        self.assertEqual(out["Deutschland"],[3,5])
        self.assertEqual(out["Hessen"],[2,4])
        grid[0,1,0]=np.nan
        with patch.object(builder,"REGIONS",("Deutschland","Hessen")):
            with self.assertRaises(ValueError):
                builder.region_daily_series(grid,masks)

    def test_full_366_day_calendar_and_february_leap(self):
        values=[1.0]*366
        reference={}
        for month in range(1,13):
            days=calendar.monthrange(2000,month)[1]
            actual=28 + 8/30 if month==2 else days
            reference[f"{month:02d}"]={"precipitation":{"Deutschland":{"month_total":actual}}}
        monthly={"reference_period":"1991-2020","months":reference}
        with patch.object(builder,"REGIONS",("Deutschland",)):
            result=builder.build_payload({"Deutschland":values},monthly)
        self.assertTrue(result["daily_climatology_available"])
        self.assertEqual(result["months"]["02"]["dates"][-1],"02-29")
        self.assertEqual(result["months"]["02"]["regions"]["Deutschland"]["running_mm"][-1],29.0)
        self.assertEqual(result["months"]["02"]["regions"]["Deutschland"]["difference_vs_official_pct"],0.0)
        self.assertEqual(result["months"]["11"]["regions"]["Deutschland"]["running_mm"][-1],30.0)
        self.assertEqual(len(result["months"]),12)

    def test_inconsistent_official_month_is_rejected(self):
        reference={}
        for month in range(1,13):
            days=calendar.monthrange(2000,month)[1]
            reference[f"{month:02d}"]={"precipitation":{"Deutschland":{"month_total":2 if month==11 else days}}}
        with patch.object(builder,"REGIONS",("Deutschland",)):
            with self.assertRaises(ValueError):
                builder.build_payload({"Deutschland":[1.0]*366},
                                      {"reference_period":"1991-2020","months":reference})

    def test_cache_missing_is_fatal(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                builder.load_reference(Path(folder)/"no-actual-climate-cache.npz")


if __name__=="__main__":
    unittest.main()
