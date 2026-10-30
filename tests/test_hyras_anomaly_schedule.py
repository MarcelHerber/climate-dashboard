"""Tests for year-round HYRAS daily-anomaly scheduling."""
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.hyras_anomaly_schedule import plan, full_year_target


class ScheduleTests(unittest.TestCase):
    def test_window_before_during_after_summer(self):
        self.assertEqual(full_year_target(date(2027, 1, 12)), date(2027, 1, 12))
        self.assertEqual(full_year_target(date(2026, 6, 10)), date(2026, 6, 10))
        self.assertEqual(full_year_target(date(2026, 10, 28)), date(2026, 10, 28))

    def test_missing_or_legacy_days_trigger_rebuild(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            dates = [
                d.isoformat() for d in
                [date(2026, 1, 1), date(2026, 10, 28)]
            ]
            for parameter in ("tmean", "tmax", "tmin"):
                d = root / parameter / "regions"
                d.mkdir(parents=True)
                (d / "index.json").write_text(json.dumps({"data_through": "2026-10-28"}))
                (d / "daily_anomaly_maps.json").write_text(json.dumps({
                    "data_through": "2026-08-31",
                    "available_dates": ["2026-06-01", "2026-08-31"],
                    "references": ["1991-2020", "1961-1990"],
                }))
            self.assertEqual(plan(root), (date(2026, 10, 28), True))
            from datetime import timedelta
            full = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(301)]
            for parameter in ("tmean", "tmax", "tmin"):
                d = root / parameter / "regions"
                (d / "daily_anomaly_maps.json").write_text(json.dumps({
                    "calendar_version": 2,
                    "data_through": "2026-10-28",
                    "available_dates": full,
                    "references": ["1991-2020", "1961-1990"],
                }))
            self.assertEqual(plan(root), (date(2026, 10, 28), False))
            # A missing day must not be silently considered complete.
            d = root / "tmin" / "regions"
            index = json.loads((d / "daily_anomaly_maps.json").read_text())
            index["available_dates"].pop(50)
            (d / "daily_anomaly_maps.json").write_text(json.dumps(index))
            self.assertEqual(plan(root), (date(2026, 10, 28), True))


if __name__ == "__main__":
    unittest.main()
