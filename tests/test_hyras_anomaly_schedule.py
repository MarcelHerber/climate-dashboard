"""Tests for seasonal HYRAS daily-anomaly scheduling."""
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.hyras_anomaly_schedule import plan, summer_target


class ScheduleTests(unittest.TestCase):
    def test_window_before_during_after_summer(self):
        self.assertEqual(summer_target(date(2027, 1, 12)), date(2026, 8, 31))
        self.assertEqual(summer_target(date(2026, 6, 10)), date(2026, 6, 10))
        self.assertEqual(summer_target(date(2026, 10, 28)), date(2026, 8, 31))

    def test_missing_days_trigger_rebuild(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for parameter in ("tmean", "tmax", "tmin"):
                d = root / parameter / "regions"
                d.mkdir(parents=True)
                (d / "index.json").write_text(json.dumps({"data_through": "2026-10-28"}))
                (d / "daily_anomaly_maps.json").write_text(json.dumps({
                    "data_through": "2026-08-23",
                    "available_dates": ["2026-06-01", "2026-08-23"],
                    "references": ["1991-2020", "1961-1990"],
                }))
            self.assertEqual(plan(root), (date(2026, 8, 31), True))
            for parameter in ("tmean", "tmax", "tmin"):
                d = root / parameter / "regions"
                (d / "daily_anomaly_maps.json").write_text(json.dumps({
                    "data_through": "2026-08-31",
                    "available_dates": ["2026-06-01", "2026-08-31"],
                    "references": ["1991-2020", "1961-1990"],
                }))
            self.assertEqual(plan(root), (date(2026, 8, 31), False))


if __name__ == "__main__":
    unittest.main()
