from pathlib import Path
import unittest


class SstProbeWorkflowTests(unittest.TestCase):
    """Guard the SST pilot workflow against regressions."""

    def test_pilot_validates_the_manifest_written_by_backfill(self):
        workflow = Path(".github/workflows/probe-sst-seven-days.yml").read_text(encoding="utf-8")
        self.assertIn("test -f /tmp/sst-pilot/manifest.json", workflow)
        self.assertNotIn("test -f /tmp/sst-pilot/index.json", workflow)

    def test_long_backfill_emits_periodic_heartbeat(self):
        workflow = Path(".github/workflows/probe-sst-seven-days.yml").read_text(encoding="utf-8")
        self.assertIn("SST-Pilot läuft weiter", workflow)
        self.assertIn("sleep 60", workflow)
        self.assertIn("wait \"$BACKFILL_PID\"", workflow)


if __name__ == "__main__":
    unittest.main()
