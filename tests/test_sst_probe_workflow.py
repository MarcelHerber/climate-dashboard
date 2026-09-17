from pathlib import Path
import unittest


class SstProbeWorkflowTests(unittest.TestCase):
    """Guard the SST pilot workflow against regressions."""

    def test_pilot_validates_the_manifest_written_by_backfill(self):
        workflow = Path(".github/workflows/probe-sst-seven-days.yml").read_text(encoding="utf-8")
        self.assertIn("test -f /tmp/sst-pilot/manifest.json", workflow)
        self.assertNotIn("test -f /tmp/sst-pilot/index.json", workflow)

    def test_pilot_splits_days_into_short_matrix_jobs_and_combines_them(self):
        workflow = Path(".github/workflows/probe-sst-seven-days.yml").read_text(encoding="utf-8")

        for day in (
            "2026-09-01",
            "2026-09-02",
            "2026-09-03",
            "2026-09-04",
            "2026-09-05",
            "2026-09-06",
            "2026-09-07",
        ):
            self.assertIn(f'- "{day}"', workflow)

        self.assertIn("max-parallel: 2", workflow)
        self.assertIn(' --start "${{ matrix.day }}"', workflow)
        self.assertIn(' --end "${{ matrix.day }}"', workflow)
        self.assertIn('test "$COUNT" -eq 8', workflow)
        self.assertIn("needs: pilot_day", workflow)
        self.assertIn("pattern: sst-europe-pilot-day-*-v4", workflow)
        self.assertIn('test "$COUNT" -eq 56', workflow)
        self.assertIn("sst-europe-pilot-2026-09-01-to-07-v4", workflow)
        self.assertNotIn("SST-Pilot läuft weiter", workflow)
        self.assertNotIn("BACKFILL_PID", workflow)

    def test_combiner_does_not_mutate_first_day_manifest_before_reading_dates(self):
        workflow = Path(".github/workflows/probe-sst-seven-days.yml").read_text(encoding="utf-8")
        self.assertIn("import copy", workflow)
        self.assertIn("merged = copy.deepcopy(payload)", workflow)


if __name__ == "__main__":
    unittest.main()
