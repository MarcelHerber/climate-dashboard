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


    def test_sst_region_completeness_excludes_partial_days(self):
        today = datetime.now(timezone.utc).date()
        full = {"absolute": "maps/a.webp", "anomaly": "maps/b.webp"}
        fixture = {"dates": {
            (today - timedelta(days=2)).isoformat(): {"regions": {"europe": full, "mediterranean": full}},
            (today - timedelta(days=1)).isoformat(): {"regions": {"europe": full}},
            today.isoformat(): {"regions": {"europe": full, "mediterranean": full}},
        }}
        latest, count, recent = status.sst_region_status(fixture, ("europe", "mediterranean"))
        self.assertEqual(latest, today.isoformat())
        self.assertEqual(count, 2)
        self.assertEqual(recent, 2)

    def test_forecasts_do_not_use_valid_end_as_last_observation(self):
        now = datetime.now(timezone.utc)
        run_date = now.date().isoformat()
        forecast = {
            "mosmix": {"product": "DWD MOSMIX-L", "issue_time": run_date + "T06:00:00Z",
                       "generated_at": now.isoformat(), "station_count": 120,
                       "timesteps": [run_date] * 60},
            "icon": {"schema": 1, "run_utc": run_date + "T06:00:00Z",
                     "generated_utc": now.isoformat(), "grid": {"rows": 90},
                     "periods": [{"start_h": i, "end_h": i + 24}
                                 for i in range(0,120,24)]}
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(status, "ROOT", Path(tmp)):
                rows = {r["id"]: r for r in status.build(forecast)["datasets"]}
        self.assertEqual(rows["mosmix"]["status"], "current")
        self.assertEqual(rows["icon_hazards"]["status"], "current")
        self.assertEqual(rows["ensembles"]["status"], "unknown")

    def test_noaa_index_freshness_uses_older_subproduct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "climate_indices").mkdir()
            today = datetime.now(timezone.utc).date()
            p = {
                "ready": True, "generated_at": datetime.now(timezone.utc).isoformat(),
                "teleconnections": {
                    "nao": {"latest_date": today.isoformat(), "daily": [[str(i), 0] for i in range(2100)]},
                    "ao": {"latest_date": (today-timedelta(days=20)).isoformat(), "daily": [[str(i), 0] for i in range(2100)]}
                }
            }
            (root / "climate_indices/index.json").write_text(json.dumps(p), encoding="utf-8")
            with patch.object(status, "ROOT", root):
                rows = {r["id"]: r for r in status.build()["datasets"]}
            self.assertEqual(rows["nao"]["status"], "current")
            self.assertEqual(rows["ao"]["status"], "delayed")
            self.assertEqual(rows["enso"]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
