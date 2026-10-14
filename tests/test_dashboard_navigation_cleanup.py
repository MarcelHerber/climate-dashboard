"""Regression checks for the compact navigation; no chart or data changes."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DashboardCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "dashboard_cleanup.css").read_text(encoding="utf-8")
        cls.builder = (ROOT / "scripts/build_pages_site.sh").read_text(encoding="utf-8")

    def test_stylesheet_is_part_of_pages_artifact(self):
        self.assertIn('href="dashboard_cleanup.css?v=20261014-gebietsmittel3"', self.page)
        self.assertIn("  dashboard_cleanup.css\n", self.builder)

    def test_all_europe_modules_still_accessible(self):
        start = self.page.index('data-nav-group="europe"')
        end = self.page.index('onclick="openAlpenwetter()"', start)
        menu = self.page[start:end]
        for tab in ("europeHub", "europeStations", "era5Europe",
                    "era5Atmosphere", "sst-europe", "t850-ensembles",
                    "state-monthly-ensemble"):
            with self.subTest(tab=tab):
                self.assertIn("switchTab('" + tab + "')", menu)
                self.assertIn('id="' + tab + '"', self.page)
        self.assertIn("stratosphaere.html", menu)
        self.assertIn("Beobachtung &amp; Reanalyse", menu)
        self.assertIn("Vorhersage", menu)

    def test_no_duplicate_decade_record_navigation(self):
        self.assertEqual(self.page.count(">Dekadenrekorde</button>"), 1)
        self.assertIn("window.location.href='dekadenrekorde.html'", self.page)

    def test_responsive_navigation_is_available(self):
        self.assertIn('id="mobileTabSelect"', self.page)
        self.assertIn(".mobile-tab-navigation{display:block}", self.css)
        self.assertIn(".primary-nav{display:none}", self.css)
        self.assertEqual(self.css.count("{"), self.css.count("}"))


if __name__ == "__main__":
    unittest.main()
