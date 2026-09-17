import unittest
from pathlib import Path


class SstFrontendStaticTests(unittest.TestCase):
    def setUp(self):
        self.source = Path("sst_europe.js").read_text(encoding="utf-8")
        self.css = Path("sst_europe.css").read_text(encoding="utf-8")

    def test_manifest_urls_navigation_and_exports_are_contract_driven(self):
        self.assertIn('const SST_ARCHIVE_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/sst-archive"', self.source)
        self.assertIn("manifest.dates?.[date]?.regions?.[region]?.[view]", self.source)
        self.assertIn("sstRenderTimeline", self.source)
        self.assertIn("downloadSstPng", self.source)
        self.assertIn("downloadSstPdf", self.source)
        self.assertIn("composeSstExportCanvas", self.source)

    def test_current_region_statistics_are_shown_below_map_and_exported(self):
        self.assertIn("statistics?.[region]?.[view]", self.source)
        self.assertIn('sstEl("sstStats")', self.source)
        self.assertIn("Mittel", self.source)
        self.assertIn("Minimum", self.source)
        self.assertIn("Maximum", self.source)
        self.assertIn('toLocaleString("de-DE"', self.source)
        self.assertIn("sst-europe-stats", self.css)


if __name__ == "__main__":
    unittest.main()
