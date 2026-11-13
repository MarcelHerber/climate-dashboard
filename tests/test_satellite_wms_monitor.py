"""Network-free regression tests for scheduled MTG WMS monitoring."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mtg = load("scripts/check_satellite_wms.py", "mtg_monitor_test")
guard = load("scripts/check_satellite_status_freshness.py", "mtg_freshness_test")


def stamp(offset):
    return (mtg.NOW + timedelta(minutes=offset)).isoformat(timespec="seconds").replace("+00:00", "Z")


def xml(*layers, include_times=True):
    moments = ",".join((stamp(-40), stamp(-30)))
    parts = [
        "<Layer><Name>" + layer + "</Name>" +
        ("<Dimension name='time'>" + moments + "</Dimension>" if include_times else "") +
        "</Layer>"
        for layer in layers
    ]
    return ("<WMT_MS_Capabilities><Layer>" + "".join(parts) +
            "</Layer></WMT_MS_Capabilities>").encode()


def png(*args, **kwargs):
    return {"ok": True, "bytes": 7200, "http_status": 200,
            "content_type": "image/png", "cors_allow_origin": "*"}


class MTGMonitorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "data" / "satellite_wms_times.json"
        self.paths = patch.object(mtg, "OUT", self.out)
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def fake_capabilities(self, *layers, include_times=True):
        body = xml(*layers, include_times=include_times)
        def fetch(url, size):
            self.assertIn("GetCapabilities", url)
            return body, 200, "text/xml", "*"
        return fetch

    def test_fast_checks_current_and_previous_utc_no_regional_probes(self):
        requested = []
        def probe(layer, moment, **flags):
            requested.append((layer, moment, flags))
            if layer == "mtg_fd:rgb_geocolour" and moment == stamp(-30):
                raise RuntimeError("HTTP 504 newest WMS frame")
            return png()
        with patch.object(mtg, "LAYERS", {"geocolour": "mtg_fd:rgb_geocolour",
                                          "dust": "mtg_fd:rgb_dust"}), \
             patch.object(mtg, "fetch", self.fake_capabilities("mtg_fd:rgb_geocolour", "mtg_fd:rgb_dust")), \
             patch.object(mtg, "test_png", probe):
            self.assertEqual(mtg.main(), 0)
        result = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(result["check_mode"], "fast")
        self.assertTrue(result["capabilities_ok"])
        self.assertTrue(result["products"]["geocolour"]["map_ok"])
        self.assertEqual(result["products"]["geocolour"]["latest_verified_time"], stamp(-40))
        self.assertEqual(result["products"]["geocolour"]["verified_attempts"], 2)
        self.assertIn("HTTP 504", result["products"]["geocolour"]["latest_frame_warning"])
        self.assertEqual(result["products"]["dust"]["latest_verified_time"], stamp(-30))
        self.assertEqual(len(requested), 3)
        self.assertTrue(all(not flags for _, _, flags in requested))
        self.assertEqual(result["healthy_products"], 2)

    def test_missing_advertised_time_never_publishes_unverified_image(self):
        with patch.object(mtg, "LAYERS", {"geocolour": "mtg_fd:rgb_geocolour"}), \
             patch.object(mtg, "fetch", self.fake_capabilities("mtg_fd:rgb_geocolour",include_times=False)), \
             patch.object(mtg, "test_png", side_effect=AssertionError("No unverifiable default WMS images")):
            self.assertEqual(mtg.main(), 0)
        entry = json.loads(self.out.read_text(encoding="utf-8"))["products"]["geocolour"]
        self.assertIsNone(entry["latest_verified_time"])
        self.assertFalse(entry["map_ok"])
        self.assertIn("UTC-Zeitpunkt",entry["error"])

    def test_deep_probe_only_when_requested_and_preserves_exact_timestamp(self):
        samples = []
        def probe(layer, moment, **flags):
            samples.append((moment, flags))
            return png()
        with patch.object(mtg, "LAYERS", {"geocolour": "mtg_fd:rgb_geocolour"}), \
             patch.object(mtg, "fetch", self.fake_capabilities("mtg_fd:rgb_geocolour")), \
             patch.object(mtg, "test_png", probe):
            self.assertEqual(mtg.main(deep=True), 0)
        entry = json.loads(self.out.read_text(encoding="utf-8"))["products"]["geocolour"]
        self.assertTrue(entry["full_disk_ok"])
        self.assertTrue(entry["atlantic_ok"])
        self.assertTrue(entry["southwest_ok"])
        self.assertTrue(entry["film_preview_ok"])
        self.assertEqual(entry["diagnostics_checked_at"], stamp(0))
        self.assertEqual(len(samples), 6)
        self.assertTrue(all(moment in (stamp(-40),stamp(-30)) for moment, _ in samples))

    def test_fast_run_preserves_dated_diagnostics_but_not_a_fake_new_check(self):
        old={"schema":1,"generated_at":stamp(-60),
             "products":{"dust":{"full_disk_ok":True,"full_disk_bytes":8192,
                                 "diagnostics_checked_at":stamp(-60)}}}
        self.out.parent.mkdir(parents=True)
        self.out.write_text(json.dumps(old),encoding="utf-8")
        with patch.object(mtg, "LAYERS", {"dust":"mtg_fd:rgb_dust"}), \
             patch.object(mtg, "fetch", self.fake_capabilities("mtg_fd:rgb_dust")), \
             patch.object(mtg, "test_png", side_effect=png):
            self.assertEqual(mtg.main(),0)
        entry=json.loads(self.out.read_text(encoding="utf-8"))["products"]["dust"]
        self.assertTrue(entry["full_disk_ok"])
        self.assertEqual(entry["diagnostics_checked_at"],stamp(-60))
        self.assertEqual(entry["latest_verified_time"],stamp(-30))


class MTGStatusWatchdogTests(unittest.TestCase):
    def test_recent_verified_frame_and_monitor_pass(self):
        result = guard.diagnose({"generated_at":stamp(-40),
             "products":{"geocolour":{"map_ok":True,"latest_verified_time":stamp(-35)}}},
             now=mtg.NOW)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["recent_products"],["geocolour"])

    def test_stale_monitor_fails_even_when_last_observation_is_new(self):
        result = guard.diagnose({"generated_at":stamp(-190),
             "products":{"geocolour":{"map_ok":True,"latest_verified_time":stamp(-20)}}},
             now=mtg.NOW)
        self.assertFalse(result["healthy"])
        self.assertTrue(any("Monitor" in x for x in result["errors"]))

    def test_stale_automatic_observations_fail_even_when_check_ran(self):
        result = guard.diagnose({"generated_at":stamp(-15),
             "products":{"geocolour":{"map_ok":True,"latest_verified_time":stamp(-240)}}},
             now=mtg.NOW)
        self.assertFalse(result["healthy"])
        self.assertTrue(any("Kein aktuelles" in x for x in result["errors"]))


class MTGWorkflowWiringTests(unittest.TestCase):
    def test_successful_satellite_monitor_triggers_pages_publish(self):
        pages=(ROOT / ".github/workflows/deploy-pages-only.yml").read_text(encoding="utf-8")
        self.assertIn('"MTG EUMETView live data check"',pages)
        self.assertIn('types: [completed]',pages)
        self.assertIn("conclusion == 'success'",pages)

    def test_quick_cadence_independent_watchdog_and_daily_deep(self):
        monitor=(ROOT / ".github/workflows/check-satellite-wms.yml").read_text(encoding="utf-8")
        watchdog=(ROOT / ".github/workflows/check-satellite-freshness.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "23,53 * * * *"',monitor)
        self.assertIn('cron: "31 3 * * *"',monitor)
        self.assertIn('python scripts/check_satellite_wms.py --deep',monitor)
        self.assertIn('git reset --hard origin/main',monitor)
        self.assertIn('generated_at',monitor)
        self.assertIn('cron: "12,42 * * * *"',watchdog)
        self.assertIn('python scripts/check_satellite_status_freshness.py',watchdog)


if __name__ == "__main__":
    unittest.main()
