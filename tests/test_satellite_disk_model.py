"""Wide-disc IFS vectors extend the regional product without replacing it."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_satellite_mslp_10min as builder
import build_satellite_ecmwf_isobars as pressure
import satellite_temperature_advection as advection


class DiskModelTests(unittest.TestCase):
    def setUp(self):
        self.run = dt.datetime(2026, 11, 17, tzinfo=dt.timezone.utc)
        self.x = np.arange(-87., 87.01, .25)
        self.y = self.x.copy()

    def test_pressure_frame_contains_native_southern_high_and_eastern_low(self):
        x, y = np.meshgrid(self.x, self.y)
        p = (1013. + 19*np.exp(-((x-15)**2+(y+35)**2)/80)
             - 20*np.exp(-((x-65)**2+(y-12)**2)/60))
        grids = {h: (self.x, self.y, p+.02*h) for h in pressure.LEADS}
        frame = builder.frame_from_disk_grids(grids, self.run, 10)
        self.assertEqual(frame["valid_utc"], "2026-11-17T00:10:00Z")
        centers = [(c["type"], c["lon"], c["lat"]) for c in frame["pressure_centers"]]
        self.assertIn(("H", 15., -35.), centers)
        self.assertIn(("T", 65., 12.), centers)
        self.assertTrue(all(c["hpa"]%5 == 0 for c in frame["contours"]))
        self.assertTrue(any(pt[1] < -30 for g in frame["contours"] for line in g["lines"] for pt in line))

    def test_disc_markers_share_budget_across_hemispheres(self):
        x, y = np.meshgrid(self.x, self.y)
        # Northern advection stronger than southern advection everywhere:
        # the global strongest-first list would starve southern midlatitudes.
        a = np.where(y >= 0, 8., -3.)
        markers = advection.select_markers(self.x, self.y, a, x*0+10, y*0, disk=True)
        self.assertLessEqual(len(markers), 220)
        self.assertTrue(any(m["lat"] < -20 for m in markers))
        self.assertTrue(any(m["lat"] > 20 for m in markers))
        self.assertTrue(any(m["lon"] < -20 for m in markers))
        self.assertTrue(any(m["lon"] > 20 for m in markers))
        self.assertTrue(all(np.cos(np.deg2rad(m["lat"]))*np.cos(np.deg2rad(m["lon"])) > .14 for m in markers))

    def test_regional_crop_is_exact_subset_of_same_wide_grid(self):
        x,y=np.meshgrid(self.x,self.y)
        p=1010+x*.1+y*.1
        grids={h:(self.x,self.y,p+h) for h in pressure.LEADS}
        regional=pressure.crop_grids(grids)
        lon,lat,z=regional[3]
        self.assertEqual((lon[0],lat[0],lon[-1],lat[-1]), pressure.BBOX)
        self.assertEqual(z.shape,(273,521))
        np.testing.assert_array_equal(z, p[(self.y>=12)&(self.y<=80)][:,(self.x>=-75)&(self.x<=55)]+3)

    def test_separate_disk_hourly_manifest_preserves_regional_chunks(self):
        def regional(_, run, minute):
            return {
                "valid_utc": (run+dt.timedelta(minutes=minute)).isoformat(),
                "forecast_minute": minute, "interpolated": minute%180!=0,
                "contours": [{"hpa":1010,"lines":[[[-30,40],[-29,41]]]}],
                "fine_contours": [{"hpa":1012,"lines":[[[-30,40],[-29,41]]]}]
            }
        def disk(_, run, minute):
            frame=regional(_,run,minute)
            frame["contours"]=[{"hpa":1015,"lines":[[[-30,-40],[-29,-41]]]}]
            del frame["fine_contours"]
            return frame
        markers={"850":[], "925":[], "700":[]}
        fields=dict.fromkeys(builder.MODEL_STEPS_HOURS,None)
        with tempfile.TemporaryDirectory() as tmp, patch.object(builder,"frame_from_grids",side_effect=regional), patch.object(builder,"frame_from_disk_grids",side_effect=disk), patch("satellite_temperature_advection.frame_markers",return_value=markers):
            manifest=builder.build_10min(fields,self.run,self.run,Path(tmp),disk_grids=fields,disk_advection_grids={850:{}})
            self.assertEqual(manifest["disk_bbox"],[-83.,-83.,83.,83.])
            self.assertEqual(len(manifest["disk_hours"]),19)
            self.assertEqual(manifest["disk_advection_algorithm"],advection.METHOD)
            self.assertEqual(manifest["disk_interval_hpa"],5)
            self.assertNotIn("advection_algorithm",manifest)
            frames=[]
            for path in manifest["disk_hours"].values():
                self.assertTrue(path.endswith("_disk.json"))
                data=json.loads((Path(tmp)/path).read_text())
                self.assertEqual(data["run_utc"],manifest["run_utc"])
                self.assertEqual(data["interval_hpa"],5)
                frames.extend(data["frames"])
            self.assertEqual(len(frames),109)
            self.assertEqual(frames[-1]["forecast_minute"],1080)
            self.assertEqual(frames[0]["temperature_advection"],markers)
            original=json.loads((Path(tmp)/manifest["hours"]["h00"]).read_text())["frames"][0]
            self.assertNotIn("temperature_advection",original)
            self.assertEqual(original["contours"][0]["hpa"],1010)


if __name__ == "__main__":
    unittest.main()
