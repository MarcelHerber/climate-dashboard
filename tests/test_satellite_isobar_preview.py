"""Regression tests for compact real-source ECMWF display contours."""
from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts/build_satellite_isobar_preview.py"
spec = importlib.util.spec_from_file_location("satellite_preview", MODULE)
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class SatellitePreviewTests(unittest.TestCase):
    def test_retains_timestamp_level_and_model_provenance(self):
        original = {
            "schema_version": 1, "model": "ECMWF IFS Open Data",
            "run_utc": "2026-11-12T00:00:00Z",
            "generated_at": "2026-11-12T09:04:00Z",
            "frames": [{"valid_utc": "2026-11-12T06:00:00Z",
                        "forecast_hour": 6,
                        "contours": [{"hpa": 1010, "lines": [
                            [[-60, 50], [-55, 50.03], [-50, 50.01], [-45, 50.02]]
                        ]}]}],
        }
        d = preview.build(original)
        self.assertEqual(d["run_utc"], original["run_utc"])
        self.assertEqual(d["frames"][0]["valid_utc"], original["frames"][0]["valid_utc"])
        self.assertEqual(d["frames"][0]["contours"][0]["hpa"], 1010)
        self.assertTrue(d["display_optimized"])
        self.assertEqual(len(d["frames"][0]["contours"][0]["lines"][0]), 2)

    def test_does_not_join_independent_out_of_region_paths(self):
        line = [
            [-74, 22], [-70, 22], [-65, 22],
            [-75, 10], [-77, 9],
            [-61, 40], [-60, 41],
        ]
        chunks = list(preview.relevant_runs(line))
        self.assertTrue(chunks)
        self.assertTrue(all(len(x) >= 2 for x in chunks))

    def test_rejects_unverified_source_identity(self):
        with self.assertRaises(ValueError):
            preview.build({"schema_version": 1, "model": "Fabricated pressure map"})


if __name__ == "__main__":
    unittest.main()
