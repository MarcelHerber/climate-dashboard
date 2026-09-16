import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from scripts.sst.backfill import backfill, iter_dates, storage_report
from scripts.sst.build_daily import BuildResult
from scripts.sst.config import ARCHIVE_START, REGIONS
from scripts.sst.manifest import archive_relpath, empty_manifest, register_date, write_manifest_atomic


class SstBackfillTests(unittest.TestCase):
    def test_iter_dates_is_inclusive(self):
        self.assertEqual(
            list(iter_dates(date(2026, 9, 1), date(2026, 9, 3))),
            [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)],
        )
        with self.assertRaises(ValueError):
            list(iter_dates(date(2026, 9, 3), date(2026, 9, 1)))

    def test_storage_report_counts_only_requested_date_files_and_projects_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            days = [date(2026, 9, 1), date(2026, 9, 2)]
            for day in days:
                for region_id in REGIONS:
                    for view in ("absolute", "anomaly"):
                        path = root / archive_relpath(day, region_id, view)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b"x" * 10)
            unrelated = root / archive_relpath(date(2026, 8, 31), "europe", "absolute")
            unrelated.parent.mkdir(parents=True, exist_ok=True)
            unrelated.write_bytes(b"x" * 999)

            report = storage_report(root, days)
            self.assertEqual(report["date_count"], 2)
            self.assertEqual(report["file_count"], 20)
            self.assertEqual(report["total_bytes"], 200)
            self.assertEqual(report["mean_bytes_per_day"], 100.0)
            projected_days = (date.today() - ARCHIVE_START).days + 1
            self.assertAlmostEqual(report["projected_archive_gib_from_2020"], 100.0 * projected_days / (1024 ** 3))

    def test_backfill_delegates_each_date_and_writes_storage_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            cache = Path(tmp) / "cache"
            calls = []

            def fake_build(day, archive_root, cache_root, token):
                calls.append(day)
                for region_id in REGIONS:
                    for view in ("absolute", "anomaly"):
                        path = archive_root / archive_relpath(day, region_id, view)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b"x" * 11)
                manifest_path = archive_root / "manifest.json"
                manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else empty_manifest()
                outputs = {
                    region_id: {view: archive_relpath(day, region_id, view) for view in ("absolute", "anomaly")}
                    for region_id in REGIONS
                }
                register_date(manifest, day, outputs, "daily_normal")
                write_manifest_atomic(manifest_path, manifest)
                return BuildResult(day, False, 10, "daily_normal")

            with mock.patch("scripts.sst.backfill.build_date", side_effect=fake_build):
                result = backfill(date(2026, 9, 1), date(2026, 9, 3), archive, cache, "token")
            self.assertEqual(calls, [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)])
            self.assertEqual(result["built"], 3)
            self.assertEqual(result["skipped"], 0)
            disk = json.loads((archive / "storage_report.json").read_text())
            self.assertEqual(disk["file_count"], 30)

    def test_backfill_reports_complete_dates_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            cache = Path(tmp) / "cache"
            sequence = [
                BuildResult(date(2026, 9, 1), True, 10, "daily_normal"),
                BuildResult(date(2026, 9, 2), False, 10, "daily_normal"),
            ]
            with mock.patch("scripts.sst.backfill.build_date", side_effect=sequence), \
                 mock.patch("scripts.sst.backfill.storage_report", return_value={"date_count": 2, "file_count": 20, "total_bytes": 200, "mean_bytes_per_day": 100, "projected_archive_gib_from_2020": 1.0}):
                result = backfill(date(2026, 9, 1), date(2026, 9, 2), archive, cache, "token")
            self.assertEqual(result["built"], 1)
            self.assertEqual(result["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
