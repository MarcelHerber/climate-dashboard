"""Checks SST daily archive recovery and user-visible region-specific status."""
import re
import unittest
from pathlib import Path

from scripts.patch_sst_frontend import CSS_TAG, JS_TAG, patch_html


class SstRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.workflow=Path(".github/workflows/update-sst-europe.yml").read_text(encoding="utf-8")
        self.page_workflow=Path(".github/workflows/publish-state-monthly-ensemble.yml").read_text(encoding="utf-8")
        self.frontend=Path("sst_europe.js").read_text(encoding="utf-8")

    def test_existing_panel_busts_js_cache_without_duplicating_script(self):
        old=(
            CSS_TAG + "\n"
            '<div id="sst-europe">x</div>\n'
            '<button onclick="switchTab(\'sst-europe\')">SST</button>\n'
            '<script src="sst_europe.js"></script>\n'
        )
        first=patch_html(old)
        self.assertIn(JS_TAG,first)
        self.assertEqual(first.count('src="sst_europe.js'),1)
        self.assertEqual(patch_html(first),first)

    def test_versioned_script_replaced_once(self):
        old=(
            CSS_TAG + "\n" +
            '<div id="sst-europe">x</div>\n' +
            '<button onclick="switchTab(\'sst-europe\')">SST</button>\n' +
            '<script src="sst_europe.js?v=20261001-old"></script>\n'
        )
        first=patch_html(old)
        self.assertIn(JS_TAG,first)
        self.assertEqual(first.count('src="sst_europe.js'),1)
        self.assertEqual(patch_html(first),first)

    def test_frontend_has_regional_latest_date_and_raw_manifest_precedence(self):
        self.assertIn('sstLatestDateForRegion(region,view)',self.frontend)
        self.assertIn('Datenstand ${sstRegionLabel(region)}',self.frontend)
        self.assertIn('input.max=sstLatestDateForRegion()',self.frontend)
        self.assertIn('sstLoadManifestFrom(SST_ARCHIVE_BASES[0])',self.frontend)
        self.assertIn('Promise.any(SST_ARCHIVE_BASES.slice(1)',self.frontend)

    def test_workflow_checkpoints_and_only_triggers_next_after_success(self):
        self.assertIn("max_new_dates = 2",self.workflow)
        self.assertIn("if len(built) >= max_new_dates:",self.workflow)
        self.assertIn("Path('/tmp/sst-europe-continue.flag').write_text(",self.workflow)
        self.assertIn("archive_root / regions[region][view]",self.workflow)
        self.assertIn("actions: write",self.workflow)
        self.assertIn("if: ${{ success() }}",self.workflow)
        self.assertIn("if (( CONTINUATION_INDEX >= 10 )); then",self.workflow)
        self.assertIn("gh workflow run update-sst-europe.yml --ref main",self.workflow)
        self.assertLess(
            self.workflow.index("SST Archiv als einzelnen Snapshot veröffentlichen"),
            self.workflow.index("Weitere fehlende MUR-Tage in einem neuen, begrenzten Lauf nachholen"),
        )
        self.assertIn('if [[ -s /tmp/sst-backfill-failures.txt ]]',self.workflow)

    def test_pages_deploy_runs_for_sst_changes(self):
        self.assertIn('"sst_europe.js"',self.page_workflow)
        self.assertIn('"scripts/patch_sst_frontend.py"',self.page_workflow)
        self.assertIn("python scripts/patch_sst_frontend.py --file index.html",self.page_workflow)
        self.assertIn("node --check sst_europe.js",self.page_workflow)


if __name__=="__main__":
    unittest.main()
