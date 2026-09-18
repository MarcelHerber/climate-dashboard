import unittest
from pathlib import Path


class SstFrontendStaticTests(unittest.TestCase):
    def setUp(self):
        self.source = Path("sst_europe.js").read_text(encoding="utf-8")
        self.css = Path("sst_europe.css").read_text(encoding="utf-8")

    def test_manifest_urls_navigation_and_exports_are_contract_driven(self):
        self.assertIn('https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/sst-archive', self.source)
        self.assertIn("manifest.dates?.[date]?.regions?.[region]?.[view]", self.source)
        self.assertIn("sstRenderTimeline", self.source)
        self.assertIn("downloadSstPng", self.source)
        self.assertIn("downloadSstPdf", self.source)
        self.assertIn("composeSstExportCanvas", self.source)

    def test_archive_loading_has_cdn_fallback_for_manifest_and_maps(self):
        self.assertIn('https://cdn.jsdelivr.net/gh/MarcelHerber/climate-dashboard@sst-archive', self.source)
        self.assertIn("SST_ARCHIVE_BASES", self.source)
        self.assertIn("sstLoadManifestFrom", self.source)
        self.assertIn("sstTryImageSource", self.source)
        self.assertIn("Promise.any", self.source)
        self.assertIn("AbortController", self.source)

    def test_sst_mounts_when_tab_becomes_active_programmatically(self):
        self.assertIn("MutationObserver", self.source)
        self.assertIn('attributeFilter:["class"]', self.source)
        self.assertIn('classList.contains("active")', self.source)

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
