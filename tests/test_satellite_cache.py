"""Offline checks for the EUMETSAT last-good snapshot workflow."""
from __future__ import annotations
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts/update_satellite_cache.py"
spec = importlib.util.spec_from_file_location("satellite_cache_module", MODULE)
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class SatelliteCacheTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = Path(self.dir.name)
        self.old_root, self.old_index, self.old_source = cache.ROOT, cache.INDEX, cache.SOURCE
        cache.ROOT = root / "data/satellite_cache"
        cache.INDEX = cache.ROOT / "index.json"
        cache.SOURCE = root / "data/satellite_wms_times.json"
        self.addCleanup(self.restore)

    def restore(self):
        cache.ROOT, cache.INDEX, cache.SOURCE = self.old_root, self.old_index, self.old_source

    def status(self, when):
        cache.SOURCE.parent.mkdir(parents=True, exist_ok=True)
        return {
            "schema": 1,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "capabilities_ok": True,
            "products": {
                "geocolour": {
                    "layer": "mtg_fd:rgb_geocolour",
                    "available_times": [when],
                }
            },
        }

    def write_status(self, doc):
        cache.SOURCE.write_text(json.dumps(doc), encoding="utf-8")

    def test_preserves_old_good_png_on_new_server_errors(self):
        time1 = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=40)).isoformat(timespec="seconds").replace("+00:00", "Z")
        time2 = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)).isoformat(timespec="seconds").replace("+00:00", "Z")
        self.write_status(self.status(time1))
        png = b"\\x89PNG\\r\\n\\x1a\\n" + b"x" * 600
        with patch.object(cache, "request_png", return_value=png):
            self.assertEqual(cache.run(), 0)
        manifest = json.loads(cache.INDEX.read_text(encoding="utf-8"))
        self.assertEqual(manifest["entries"]["geocolour"]["europe"]["time"], time1)
        self.assertEqual((cache.ROOT / "geocolour_europe.png").read_bytes(), png)
        self.write_status(self.status(time2))
        with patch.object(cache, "request_png", side_effect=RuntimeError("HTTP 500")):
            self.assertEqual(cache.run(), 0)
        unchanged = json.loads(cache.INDEX.read_text(encoding="utf-8"))
        self.assertEqual(unchanged, manifest)
        self.assertEqual((cache.ROOT / "geocolour_europe.png").read_bytes(), png)

    def test_rejects_bad_utc(self):
        self.assertIsNone(cache.valid_utc("bad"))
        self.assertIsNone(cache.valid_utc("2026-11-11T19:40:00"))
        self.assertIsNotNone(cache.valid_utc("2026-11-11T19:40:00Z"))

    def test_outdated_manifest_never_overwrites_snapshot(self):
        time1 = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)).isoformat(timespec="seconds").replace("+00:00", "Z")
        data = self.status(time1)
        data["generated_at"] = "2025-01-01T00:00:00Z"
        self.write_status(data)
        with patch.object(cache, "request_png", side_effect=AssertionError("should not fetch")):
            self.assertEqual(cache.run(), 0)
        self.assertFalse(cache.INDEX.exists())


if __name__ == "__main__":
    unittest.main()
