"""Ensure the DWD daily-map browser always refreshes old CDC publication state."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DailyMapFreshnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js=(ROOT/"dwd_station_daily_map.js").read_text(encoding="utf-8")
        cls.loader=(ROOT/"monthly_frequency.js").read_text(encoding="utf-8")
        cls.page=(ROOT/"index.html").read_text(encoding="utf-8")
        cls.workflow=(ROOT/".github/workflows/update-dwd-daily-map.yml").read_text(encoding="utf-8")

    def test_cdc_index_is_rechecked_not_frozen(self):
        self.assertIn("idxCheckedAt",self.js)
        self.assertIn("idxRequest",self.js)
        self.assertIn('await index({force:true})',self.js)
        self.assertIn('cache.clear();climateCache=null;selected=null;',self.js)
        self.assertIn('cache:"no-store"',self.js)

    def test_latest_date_moves_forward_only_when_following_latest(self):
        self.assertIn("const oldThrough=idx?.data_through",self.js)
        self.assertIn("d.value===oldThrough",self.js)
        self.assertIn("d.value=idx.data_through",self.js)

    def test_publication_timestamp_and_manual_refresh(self):
        self.assertIn('id="dwdDailyRefresh"',self.js)
        self.assertIn('id="dwdDailyFreshness"',self.js)
        self.assertIn('idx.generated_at',self.js)
        self.assertIn('idx.data_through',self.js)
        self.assertIn('onclick=()=>load()',self.js)

    def test_cache_busting_and_workflow(self):
        self.assertIn("dwd_station_daily_map.js?v=20261014-freshness1",self.loader)
        self.assertIn("monthly_frequency.js?v=20261014-freshness1",self.page)
        self.assertIn('cron: "35 5 * * *"',self.workflow)


if __name__ == "__main__":
    unittest.main()
