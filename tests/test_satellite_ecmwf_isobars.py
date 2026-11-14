#!/usr/bin/env python3
"""Contract tests for ECMWF satellite isobars; fake fields ONLY in tests."""
from __future__ import annotations
import datetime as dt
import importlib.util
import json
from pathlib import Path
import unittest
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
MODULE=Path(__file__).resolve().parents[1]/"scripts/build_satellite_ecmwf_isobars.py"
spec=importlib.util.spec_from_file_location("satellite_isobars_builder",MODULE)
isobars=importlib.util.module_from_spec(spec)
spec.loader.exec_module(isobars)


class IsobarTests(unittest.TestCase):
    def setUp(self):
        self.lon=np.arange(-75,55.01,.25,dtype=float)
        self.lat=np.arange(12,80.01,.25,dtype=float)
        xx,yy=np.meshgrid(self.lon,self.lat)
        # Analytical, deterministic pressure field for algorithm tests ONLY.
        self.p=1010+0.33*(xx+26)+0.26*(yy-45)+9*np.exp(-((xx+37)**2+(yy-53)**2)/120)
        self.run=dt.datetime(2026,11,11,12,tzinfo=dt.timezone.utc)

    def test_true_geographic_coordinates_and_five_hpa_levels(self):
        levels=isobars.contour_lines(self.lon,self.lat,self.p)
        self.assertTrue(levels)
        self.assertTrue(all(row["hpa"]%5==0 for row in levels))
        self.assertTrue(all(len(line)>=4 for row in levels for line in row["lines"]))
        pts=[pt for v in levels for line in v["lines"] for pt in line]
        self.assertTrue(all(-75.1<=p[0]<=55.1 and 11.9<=p[1]<=80.1 for p in pts))
        self.assertGreater(len(pts),100)

    def test_forecast_validity_preserves_run_and_utc(self):
        grids={h:(self.lon,self.lat,self.p+h/3) for h in isobars.LEADS}
        report=isobars.build_payload(grids,self.run,self.run+dt.timedelta(hours=9))
        self.assertEqual(report["schema_version"],1)
        self.assertEqual(report["resolution_degrees"],.25)
        self.assertEqual(report["interval_hpa"],5)
        self.assertEqual(report["run_utc"],"2026-11-11T12:00:00Z")
        self.assertEqual(report["frames"][0]["valid_utc"],"2026-11-11T12:00:00Z")
        self.assertEqual(report["frames"][-1]["valid_utc"],"2026-11-12T06:00:00Z")
        self.assertEqual([f["forecast_hour"] for f in report["frames"]],[0,3,6,9,12,15,18])
        self.assertTrue(all(f["contours"] for f in report["frames"]))
        json.dumps(report,allow_nan=False)

    def test_absent_data_never_produces_a_fake_forecast(self):
        with self.assertRaisesRegex(ValueError,"missing"):
            isobars.build_payload({},self.run,self.run)
        with self.assertRaisesRegex(ValueError,"mismatch"):
            isobars.contour_lines(self.lon,self.lat,self.p[:-1,:])

    def test_candidates_are_not_unavailable_future_cycles(self):
        now=self.run+dt.timedelta(hours=4)
        runs=isobars.candidate_runs(now)
        self.assertTrue(all(x<=now-dt.timedelta(hours=6) for x in runs))
        self.assertEqual(len(runs),5)


if __name__=="__main__":
    unittest.main()
