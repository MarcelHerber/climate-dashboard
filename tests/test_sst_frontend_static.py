import unittest
from pathlib import Path


class SstFrontendStaticTests(unittest.TestCase):
    def test_manifest_urls_navigation_and_exports_are_contract_driven(self):
        text = Path("sst_europe.js").read_text(encoding="utf-8")
        self.assertIn('const SST_ARCHIVE_BASE="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/sst-archive"', text)
        self.assertIn("manifest.dates?.[date]?.regions?.[region]?.[view]", text)
        self.assertTrue('crossOrigin="anonymous"' in text or "crossOrigin='anonymous'" in text)
        self.assertIn("composeSstExportCanvas", text)
        self.assertIn('toDataURL("image/png")', text)
        self.assertIn("window.jspdf", text)
        self.assertIn("SST_", text)
        self.assertNotIn("2026/", text)
        self.assertIn("for(let offset=29;offset>=0;offset--)", text)


if __name__ == "__main__":
    unittest.main()
