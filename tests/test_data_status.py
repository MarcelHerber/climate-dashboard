import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_data_status as status


class DataStatusTests(unittest.TestCase):
    def test_date_and_month_parsing(self):
        self.assertEqual(status.valid_date("2026-09"), date(2026, 9, 1))
        self.assertEqual(status.valid_date("2026-10-13"), date(2026, 10, 13))
        self.assertIsNone(status.valid_date("not-a-date"))

    def test_recent_and_delayed_not_confused(self):
        today = datetime.now(timezone.utc).date()
        recent = status.result("a", "A", "T", (today-timedelta(days=1)).isoformat(),
                               None, "tests", allowed_delay=5)
        late = status.result("b", "B", "T", (today-timedelta(days=20)).isoformat(),
                             None, "tests", allowed_delay=5)
        self.assertEqual(recent["status"], "current")
        self.assertEqual(late["status"], "delayed")
        self.assertEqual(status.result("c", "C", "T", None, None, "none")["status"], "unknown")

    def test_known_missing_backfill_is_visible(self):
        today = datetime.now(timezone.utc).date()
        incomplete = status.result("a", "A", "T", today.isoformat(), None,
                                   "0/30 reference years", incomplete=True)
        self.assertEqual(incomplete["status"], "incomplete")

    def test_derived_archive_status(self):
        today = datetime.now(timezone.utc).date().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "update_status.json").write_text(json.dumps({
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "monthly": {"latest_complete_month": today[:7], "area_count": 17, "records": 100},
                "daily": {"latest_date": today, "records": 10, "latest_station_count": 4}
            }), encoding="utf-8")
            (root / "era5_stratosphere").mkdir()
            (root / "era5_stratosphere/index.json").write_text(json.dumps({
                "ready": True, "data_through": today, "reference_years_completed": 0
            }), encoding="utf-8")
            with patch.object(status, "ROOT", root):
                archive = status.build()
            rows = {row["id"]: row for row in archive["datasets"]}
            self.assertEqual(rows["dwd_monthly"]["status"], "current")
            self.assertEqual(rows["era5_strat"]["status"], "incomplete")
            self.assertEqual(rows["era5_strat"]["coverage"],
                             "Referenz 1991–2020: 0/30 Jahre vollständig")


if __name__ == "__main__":
    unittest.main()
