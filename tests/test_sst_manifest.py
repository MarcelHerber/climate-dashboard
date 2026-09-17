import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.sst.config import REGIONS
from scripts.sst.manifest import archive_relpath, empty_manifest, register_date, write_manifest_atomic


class SstManifestTests(unittest.TestCase):
    def complete_outputs(self, day):
        return {
            region_id: {
                view: archive_relpath(day, region_id, view)
                for view in ("absolute", "anomaly")
            }
            for region_id in REGIONS
        }

    def complete_statistics(self):
        return {
            region_id: {
                "absolute": {"mean": 20.1, "min": 10.2, "max": 29.3},
                "anomaly": {"mean": 0.8, "min": -2.1, "max": 4.3},
            }
            for region_id in REGIONS
        }

    def test_empty_manifest_has_stable_public_contract(self):
        manifest = empty_manifest()
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["archive_start"], "2020-01-01")
        self.assertIsNone(manifest["data_through"])
        self.assertEqual(manifest["available_dates"], [])
        self.assertEqual(set(manifest["regions"]), set(REGIONS))
        self.assertEqual(manifest["scales"]["absolute"], [-2.0, 34.0])
        self.assertEqual(manifest["scales"]["anomaly"], [-6.0, 6.0])

    def test_archive_relpath_is_date_region_view_partitioned(self):
        self.assertEqual(
            archive_relpath(date(2026, 9, 14), "europe", "anomaly"),
            "2026/09/europe/anomaly/2026-09-14.webp",
        )

    def test_register_date_requires_exactly_all_eight_urls(self):
        day = date(2026, 9, 14)
        outputs = self.complete_outputs(day)
        outputs["europe"].pop("anomaly")
        with self.assertRaisesRegex(ValueError, "8"):
            register_date(empty_manifest(), day, outputs, "daily_normal", self.complete_statistics())

    def test_register_date_stores_statistics_for_every_region_and_view(self):
        day = date(2026, 9, 14)
        manifest = empty_manifest()
        register_date(
            manifest,
            day,
            self.complete_outputs(day),
            "daily_normal",
            self.complete_statistics(),
        )
        entry = manifest["dates"][day.isoformat()]
        self.assertEqual(entry["statistics"]["europe"]["anomaly"]["mean"], 0.8)
        self.assertEqual(entry["statistics"]["europe"]["anomaly"]["min"], -2.1)
        self.assertEqual(entry["statistics"]["europe"]["anomaly"]["max"], 4.3)

    def test_register_date_sorts_and_deduplicates_available_dates(self):
        manifest = empty_manifest()
        later = date(2026, 9, 14)
        earlier = date(2026, 9, 13)
        stats = self.complete_statistics()
        register_date(manifest, later, self.complete_outputs(later), "daily_normal", stats)
        register_date(manifest, earlier, self.complete_outputs(earlier), "daily_normal", stats)
        register_date(manifest, later, self.complete_outputs(later), "daily_normal", stats)
        self.assertEqual(manifest["available_dates"], ["2026-09-13", "2026-09-14"])
        self.assertEqual(manifest["data_through"], "2026-09-14")
        self.assertEqual(
            manifest["dates"]["2026-09-14"]["regions"]["europe"]["anomaly"],
            "2026/09/europe/anomaly/2026-09-14.webp",
        )

    def test_write_manifest_atomic_writes_valid_json_without_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            payload = empty_manifest()
            write_manifest_atomic(path, payload)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], 1)
            self.assertFalse((Path(tmp) / "manifest.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
