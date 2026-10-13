"""Fast sanity tests for real ECMWF extratropical tracker and GEFS batching."""
from pathlib import Path
import importlib.util
import datetime as dt
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

ec=load("ecmwf_atlantic","scripts/update_ecmwf_atlantic_lows.py")
gefs=load("gefs31","scripts/update_gefs_cps.py")


class TestNewModelFeeds(unittest.TestCase):
    def test_ecmwf_model_types_and_forecast_steps(self):
        self.assertEqual(ec.MODELS["ifs-atl"][0],"ifs")
        self.assertEqual(ec.MODELS["aifs-atl"][0],"aifs-single")
        self.assertIn(48,ec.STEPS)
        self.assertEqual(ec.STEPS[1]-ec.STEPS[0],6)

    def test_ecmwf_24h_deepening(self):
        run=dt.datetime(2026,10,12,12,tzinfo=dt.timezone.utc)
        points=[{"h":h,"lat":60,"mslp_hpa":1008-h} for h in [0,6,12,18,24]]
        t={"points":points,"model":"ifs-atl"}
        ec.attach_deepening([t])
        self.assertIsNone(points[0]["cyclogenesis_24h"])
        self.assertEqual(points[-1]["cyclogenesis_24h"]["pressure_drop_hpa_24h"],24)
        self.assertTrue(points[-1]["cyclogenesis_24h"]["explosive"])

    def test_gefs_native_vs_interpolated_pressure_levels(self):
        self.assertEqual(gefs.LEVELS,[925,850,700,500,300])
        z=gefs.interpolate_height(600,700,500,100,300)
        self.assertGreater(z,100)
        self.assertLess(z,300)

    def test_frontend_and_workflow_static_integrity(self):
        h=(ROOT/"tiefdruck_tracker.html").read_text()
        js=(ROOT/"tiefdruck_tracker.js").read_text()
        diagnostics=(ROOT/"tiefdruck_diagnostics.js").read_text()
        sh=(ROOT/"scripts/build_pages_site.sh").read_text()
        for model in ("ifs-atl","aifs-atl"):
            self.assertIn('value="'+model+'"',h)
            self.assertIn(model,js)
        self.assertIn("ECMWF_LOW_URL",js)
        self.assertIn("ifs-atl",diagnostics)
        self.assertIn("tiefdruck_diagnostics.js",sh)
        for file in ("tiefdruck_tracker.js","tiefdruck_phase.js","tiefdruck_diagnostics.js"):
            subprocess.run(["node","--check",str(ROOT/file)],check=True,capture_output=True)

if __name__=="__main__":
    unittest.main()
