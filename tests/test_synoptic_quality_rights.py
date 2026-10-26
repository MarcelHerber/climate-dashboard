#!/usr/bin/env python3
"""Regression checks for synoptic source quality and reuse decisions."""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/synoptic_charts/isobaren_quality_rights_2026-10-26.json"
PAGE = ROOT / "isobaren_quellenpruefung.html"
WORLD = ROOT / "weltweite_isobaren.html"
ORIGINAL_JS = ROOT / "isobaren_original.js"
ORIGINAL_HTML = ROOT / "isobaren_original.html"

def parse_array(path, opening, ending):
    content = path.read_text(encoding="utf-8")
    a = content.index(opening) + len(opening)
    b = content.index(ending, a)
    return json.loads(content[a:b] + ("]" if ending == "];" else ""))

class TestSynopticSourceRights(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(DATA.read_text(encoding="utf-8"))
        cls.records = cls.data["sources"]
        cls.world = parse_array(WORLD, "const DATA=", ";const REGIONS=")
        cls.original = parse_array(ORIGINAL_JS, "const CURATED_SOURCES=", "];")
        cls.byurl = {r["url"]: r for r in cls.records}

    def test_all_current_url_targets_are_covered(self):
        urls = set(x["url"] for x in self.world + self.original)
        self.assertEqual(len(self.world) + len(self.original), 169)
        self.assertEqual(urls, set(self.byurl))
        self.assertEqual(len(urls), len(self.records))
        self.assertEqual(len(urls), 119)

    def test_all_records_have_conservative_publication_policy(self):
        for r in self.records:
            with self.subTest(url=r["url"]):
                self.assertTrue(r["url"].startswith(("https://", "http://")))
                self.assertIn("policy_url", r["rights"])
                self.assertIn(r["rights"]["class"], {
                    "bedingungen_erlauben", "nur_originalseite", "produkt_pruefen",
                    "drittanbieter", "ungeklaert"
                })
                self.assertTrue(r["publication_policy"])
                if r["rights"]["class"] != "bedingungen_erlauben":
                    self.assertNotIn("nach_konkreter_utc", r["publication_policy"])

    def test_explicitly_restricted_providers_are_link_only(self):
        for host in ("weather.metoffice.gov.uk", "www.met.ie", "www.metservice.com",
                     "services.metservice.com", "www.meteo.be"):
            matches = [x for x in self.records if x["domain"] == host]
            self.assertGreater(len(matches), 0, host)
            for r in matches:
                self.assertEqual(r["rights"]["class"], "nur_originalseite", r["name"])
                self.assertEqual(r["publication_policy"], "nur_originalseite")
                self.assertTrue(r["rights"]["automatic_crawling_prohibited"])

    def test_official_reuse_and_provider_policy_links_are_grounded(self):
        hosts = ("www.dwd.de", "www.jma.go.jp", "www.aemet.es", "www.knmi.nl")
        for host in hosts:
            records = [x for x in self.records if x["domain"] == host]
            self.assertTrue(records, host)
            for r in records:
                self.assertEqual(r["rights"]["class"], "bedingungen_erlauben")
                self.assertTrue(r["rights"]["policy_url"].startswith("https://"))

    def test_no_independent_official_status_for_mirrors(self):
        for host in ("www.weathercharts.org", "www.wetter3.de", "www.meteociel.fr",
                     "www.vorticity.de", "www.netweather.tv", "asrad.pccu.edu.tw"):
            matches = [x for x in self.records if x["domain"] == host]
            self.assertTrue(matches, host)
            for r in matches:
                self.assertEqual(r["rights"]["class"], "drittanbieter")
                self.assertIn("nein", r["official_independent_analysis"])

    def test_charts_with_verified_time_do_not_guess_others(self):
        known = [x for x in self.records if x["validity_utc_from_inspected_image"]]
        self.assertEqual(len(known), 9)
        self.assertTrue(any("2026-10-26T12:00:00Z" == x["validity_utc_from_inspected_image"] for x in known))
        self.assertEqual(self.byurl["https://www.jma.go.jp/jmh/asas_06_s.html"]["validity_utc_from_inspected_image"],"2026-10-26T06:00:00Z")
        for r in known:
            self.assertRegex(r["validity_utc_from_inspected_image"], r"^20\d\d-\d\d-\d\dT(?:0\d|1\d|2[0-3]):00:00Z$")

    def test_docs_and_frontend_syntax(self):
        page = PAGE.read_text(encoding="utf-8")
        for filename in ("isobaren_quality_rights_2026-10-26.json", "isobaren_browser_quick_latest.json"):
            self.assertIn(filename, page)
        self.assertIn("isobaren_quellenpruefung.html", WORLD.read_text(encoding="utf-8"))
        self.assertIn("isobaren_quellenpruefung.html", ORIGINAL_HTML.read_text(encoding="utf-8"))
        matches = re.findall(r"<script(?:\s[^>]*)?>([\s\S]*?)</script>", page)
        self.assertEqual(len(matches), 1)
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "check_synoptic_qa.js"
            script.write_text(matches[0], encoding="utf-8")
            check = subprocess.run(["node","--check",str(script)], capture_output=True,text=True)
            self.assertEqual(check.returncode, 0, check.stderr)

            world_scripts = re.findall(r"<script(?:\\s[^>]*)?>([\\s\\S]*?)</script>", WORLD.read_text(encoding="utf-8"))
            self.assertTrue(any("const DATA=" in x for x in world_scripts))
            world_script = next(x for x in world_scripts if "const DATA=" in x)
            script.write_text(world_script, encoding="utf-8")
            check = subprocess.run(["node","--check",str(script)], capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, "world catalog JS: " + check.stderr)

if __name__ == "__main__":
    unittest.main()
