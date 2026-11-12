#!/usr/bin/env python3
"""Ten-minute ECMWF isobar interpolation contracts: synthetic grids ONLY in tests."""
from __future__ import annotations
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tenminute", ROOT/"scripts/build_satellite_mslp_10min.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
UTC = dt.timezone.utc


class TenMinuteMSLPTests(unittest.TestCase):
    def setUp(self):
        self.run = dt.datetime(2026, 11, 12, 0, tzinfo=UTC)
        x = np.array([-30.0,-29.5,-29.0])
        y = np.array([40.0,40.5,41.0])
        self.fields = {h:(x,y,np.full((3,3),1000.0+h)) for h in (0,3,6,9,12,15,18)}

    def test_grid_interpolated_before_contouring(self):
        x,y,p,steps,fraction = m.interpolate_field(self.fields, 10)
        self.assertEqual(steps,(0,3))
        self.assertAlmostEqual(fraction,1/18)
        self.assertAlmostEqual(p[0,0],1000+3/18)
        self.assertEqual(m.interpolate_field(self.fields,180)[3],(3,6))
        self.assertEqual(m.interpolate_field(self.fields,720)[3],(12,15))
        self.assertEqual(m.interpolate_field(self.fields,1080)[3],(18,18))
        for minute in (-10,725,730,11):
            with self.assertRaises(ValueError):
                m.interpolate_field(self.fields,minute)

    def test_incompatible_original_grids_rejected(self):
        broken = dict(self.fields)
        x,y,p = broken[3]
        broken[3] = (x+.1,y,p)
        with self.assertRaisesRegex(ValueError,"incompatible"):
            m.interpolate_field(broken,10)

    def test_contour_moves_when_pressure_field_changes(self):
        import contourpy
        xx=np.linspace(-65,45,221)
        yy=np.linspace(18,75,115)
        xgrid,ygrid=np.meshgrid(xx,yy)
        base=1000+.25*xgrid+.13*ygrid
        field2=base+2
        grids = {h:(xx,yy,base+h*field2*0+2*h/3) for h in (0,3,6,9,12,15,18)}
        # 0 and +3 fields differ; 10-minute interpolated contour must shift.
        p0=m.interpolate_field(grids,0)[2]
        p1=m.interpolate_field(grids,10)[2]
        self.assertFalse(np.array_equal(p0,p1))
        first=m.concise_contours(xx,yy,p0)
        second=m.concise_contours(xx,yy,p1)
        self.assertTrue(first and second)
        self.assertNotEqual(json.dumps(first),json.dumps(second))
        self.assertTrue(all(x["hpa"]%5==0 for x in first))

    def test_genuine_two_hpa_contours_are_computed_from_the_pressure_grid(self):
        # A pressure gradient with 1010, 1012 and 1014 hPa contours.
        # 1015 hPa is never invented in the 2-hPa mode.
        x=np.linspace(-40,50,181)
        y=np.linspace(20,76,113)
        xx,yy=np.meshgrid(x,y)
        pressure=1012+0.16*xx+0.045*yy
        fine=m.concise_contours(x,y,pressure,spacing=2,bbox=m.EUROPE_BBOX)
        coarse=m.concise_contours(x,y,pressure,spacing=5)
        fine_levels={g["hpa"] for g in fine}
        self.assertTrue(fine_levels)
        self.assertTrue(all(level%2==0 for level in fine_levels))
        self.assertNotIn(1015,fine_levels)
        self.assertTrue(any(level%5!=0 for level in fine_levels))
        self.assertTrue(coarse)
        self.assertTrue(all(g["hpa"]%5==0 for g in coarse))
        self.assertEqual(m.FINE_REGIONS,("europe","southwest","central","germany"))
        with self.assertRaises(ValueError):
            m.concise_contours(x,y,pressure,spacing=3)

    def test_index_has_73_correct_utc_frames_and_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            def synthetic(_, run, minute):
                return {
                    "valid_utc":(run+dt.timedelta(minutes=minute)).isoformat(timespec="seconds").replace("+00:00","Z"),
                    "forecast_minute":minute,
                    "interpolated":minute%180!=0,
                    "contours":[{"hpa":1010,"lines":[[[-30,40],[-29,41]]]}],
                    "fine_contours":[{"hpa":1012,"lines":[[[-30,40],[-29,41]]]}]
                }
            with patch.object(m,"frame_from_grids",side_effect=synthetic):
                index=m.build_10min(self.fields,self.run,self.run+dt.timedelta(hours=7),Path(tmp))
            self.assertEqual(index["time_resolution_minutes"],10)
            self.assertEqual(index["source_interval_hours"],3)
            self.assertEqual(len(index["hours"]),19)
            self.assertEqual(index["fine_interval_hpa"],2)
            self.assertEqual(set(index["fine_regions"]),{"europe","southwest","central","germany"})
            self.assertEqual(len(index["fine_hours"]),19)
            self.assertIn("interpolated",index["note"])
            frames=[]
            for path in index["hours"].values():
                blob=json.loads((Path(tmp)/path).read_text(encoding="utf-8"))
                self.assertEqual(blob["run_utc"],index["run_utc"])
                frames.extend(blob["frames"])
            self.assertEqual(len(frames),109)
            self.assertEqual(frames[0]["valid_utc"],"2026-11-12T00:00:00Z")
            self.assertEqual(frames[1]["valid_utc"],"2026-11-12T00:10:00Z")
            self.assertEqual(frames[-1]["valid_utc"],"2026-11-12T18:00:00Z")
            self.assertEqual(sum(not f["interpolated"] for f in frames),7)
            fine_frames=[]
            for path in index["fine_hours"].values():
                blob=json.loads((Path(tmp)/path).read_text(encoding="utf-8"))
                self.assertEqual(blob["interval_hpa"],2)
                self.assertEqual(blob["run_utc"],index["run_utc"])
                fine_frames.extend(blob["frames"])
            self.assertEqual(len(fine_frames),109)
            self.assertEqual(fine_frames[1]["valid_utc"],"2026-11-12T00:10:00Z")
            self.assertEqual(fine_frames[-1]["valid_utc"],"2026-11-12T18:00:00Z")
            self.assertTrue(all(group["hpa"]%2==0 for frame in fine_frames for group in frame["contours"]))


if __name__ == "__main__":
    unittest.main()
