from pathlib import Path
import unittest


class SstProbeWorkflowTests(unittest.TestCase):
    """Guard the pilot workflow against manifest filename drift."""

    def test_pilot_validates_the_manifest_written_by_backfill(self):
        workflow = Path(".github/workflows/probe-sst-seven-days.yml").read_text(encoding="utf-8")
        self.assertIn("test -f /tmp/sst-pilot/manifest.json", workflow)
        self.assertNotIn("test -f /tmp/sst-pilot/index.json", workflow)


if __name__ == "__main__":
    unittest.main()
