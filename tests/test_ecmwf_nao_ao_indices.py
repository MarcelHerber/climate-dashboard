"""Pure arithmetic and missing-data safeguards for independent IFS ENS EOF indices."""
from __future__ import annotations

import unittest
from datetime import date

import numpy as np

from scripts.update_ecmwf_nao_ao_indices import (
    baseline_for_date,percentile,precompute,project,summarize,
)


class EOFIndexTest(unittest.TestCase):
    def test_percentiles(self):
        self.assertEqual(percentile([0.,10.],.1),1)
        self.assertEqual(percentile([0.,10.],.9),9)

    def test_reference_daily_calendar_interpolation(self):
        c=np.arange(12,dtype=float).reshape(12,1,1)
        self.assertAlmostEqual(baseline_for_date(c,date(2026,1,15))[0,0],0)
        self.assertAlmostEqual(baseline_for_date(c,date(2026,2,15))[0,0],1)
        self.assertAlmostEqual(baseline_for_date(c,date(2026,1,30))[0,0],15/31)
        self.assertAlmostEqual(baseline_for_date(c,date(2026,12,15))[0,0],11)
        self.assertLess(baseline_for_date(c,date(2026,12,31))[0,0],11)

    def test_projection_uses_physical_height_anomaly(self):
        reference={"name":"ao",
            "climate":np.zeros((12,2,2)),
            "basis":np.array([.5,.5,.5,.5]),"slope":.1,"intercept":0}
        raw=np.array([[20.,10.],[10.,20.]])
        self.assertAlmostEqual(project(raw,reference,date(2026,11,13)),3.)
        with self.assertRaises(RuntimeError):
            project(raw*100,reference,date(2026,11,13))

    def test_full_50_members_probabilities_and_dates(self):
        raw=[{member:(member-25)/20 for member in range(1,51)} for _ in range(16)]
        result=summarize(raw,date(2026,11,12))
        self.assertEqual(result["member_count"],[50]*16)
        self.assertEqual(result["valid_dates"][-1],"2026-11-27")
        self.assertEqual(len(result["members"]),50)
        self.assertEqual(result["probability"]["negative"][0],48.0)
        self.assertEqual(result["probability"]["positive"][0],52.0)
        self.assertEqual(result["probability"]["strong_negative"][0],12.0)
        self.assertEqual(result["probability"]["strong_positive"][0],10.0)

    def test_missing_ensemble_member_not_fabricated(self):
        raw=[{member:1. for member in range(1,51)} for _ in range(16)]
        del raw[0][13]
        with self.assertRaises(RuntimeError):
            summarize(raw,date(2026,11,12))


if __name__=="__main__":
    unittest.main()
