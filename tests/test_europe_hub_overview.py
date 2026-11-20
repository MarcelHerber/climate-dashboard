"""Regression checks for the three Europa direct entries."""
import re
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "index.html"
START = '<!-- ================= EUROPA-HUB ================= -->'
END = '<!-- ================= ERA5 ATMOSPHÄRE EUROPA ================= -->'
TARGETS = ("europeStations", "era5Europe", "era5Atmosphere")
GRID_RULE = '.europe-hub-grid .europe-hub-card:nth-child(3){grid-column:1/-1}'


class EuropeHubOverview(unittest.TestCase):
    def setUp(self):
        self.source = SOURCE.read_text(encoding="utf-8")
        self.hub = self.source.split(START, 1)[1].split(END, 1)[0]

    def test_pills_and_direct_entries(self):
        self.assertNotIn(r'\n', self.hub)
        self.assertEqual(re.findall(r'<section class="europe-hub-card">\s*<h3>([^<]+)</h3>', self.hub),
                         ["Europa-Stationen", "ERA5-Land Europa", "ERA5 Atmosphäre"])
        self.assertEqual(re.findall(r"onclick=\"switchTab\('([^']+)'\)\"", self.hub), list(TARGETS))
        for target in TARGETS:
            self.assertEqual(len(re.findall(rf'<div id="{target}" class="tab-content"', self.source)), 1)
        self.assertIn(GRID_RULE, self.source)

    def test_final_descriptions(self):
        self.assertIn('unter einer einheitlichen Oberfläche', self.hub)
        self.assertIn('Direkteinstiege</span><span class="europe-hub-statvalue">3', self.hub)
        self.assertIn('Reanalysequelle</span><span class="europe-hub-statvalue">Copernicus / ECMWF', self.hub)
        self.assertIn('Hinweis zu den Daten', self.hub)
        for development_text in ('sauberer Einstieg vorbereitet', 'im nächsten Schritt', 'Geplanter Aufbau', 'Europa-Status'):
            self.assertNotIn(development_text, self.hub)


if __name__ == '__main__':
    unittest.main()
