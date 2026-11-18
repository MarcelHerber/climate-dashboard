import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from scripts.sst import config, manifest


class HistoricalArchiveTests(unittest.TestCase):
    def test_source_cutoff_and_region_bounds(self):
        self.assertEqual(config.ARCHIVE_START, date(1981, 9, 1))
        self.assertEqual(config.MUR_ARCHIVE_START, date(2002, 6, 1))
        old = config.oisst_regions_for_day(date(2002, 5, 31))
        self.assertEqual(set(old), set(config.ALL_REGIONS))
        self.assertEqual(old["europe"].source_id, "oisst")
        self.assertEqual(old["europe"].bounds, config.REGIONS["europe"].bounds)
        self.assertEqual(set(config.oisst_regions_for_day(date(2002, 6, 1))), set(config.OCEAN_REGIONS))

    def test_old_manifest_migrates_without_losing_dates(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            old = {"schema_version": 1, "archive_start": "2020-01-01", "dates": {"2020-01-01": {}}}
            path.write_text(json.dumps(old), encoding="utf-8")
            new = manifest.read_manifest(path)
            self.assertEqual(new["archive_start"], "1981-09-01")
            self.assertEqual(new["dates"], old["dates"])

    def test_planner_requires_both_views_and_statistics_per_region(self):
        entry = {"regions": {"pacific": {"absolute": "a", "anomaly": "b"}},
                 "statistics": {"pacific": {view: {"mean": 1, "min": 0, "max": 2}
                                           for view in manifest.VIEWS}}}
        self.assertTrue(manifest.manifest_entry_complete(entry, ["pacific"]))
        self.assertFalse(manifest.manifest_entry_complete(entry, config.REGIONS))
        self.assertFalse(manifest.manifest_entry_complete(entry, config.ALL_REGIONS))
        del entry["regions"]["pacific"]["anomaly"]
        self.assertFalse(manifest.manifest_entry_complete(entry, ["pacific"]))


if __name__ == "__main__":
    unittest.main()
