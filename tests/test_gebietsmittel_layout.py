"""Regression checks for compact Gebietsmittel UI and unchanged chart inputs."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]


class GebietsmittelLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page=(ROOT/"index.html").read_text(encoding="utf-8")
        start=page.index('<div id="monthly" class="tab-content">')
        end=page.index("<!-- ================= KLIMA-INDEX ================= -->",start)
        cls.monthly=page[start:end]
        cls.page=page
        cls.css=(ROOT/"dashboard_cleanup.css").read_text(encoding="utf-8")
        cls.script=(ROOT/"monthly_layout.js").read_text(encoding="utf-8")
        cls.builder=(ROOT/"scripts/build_pages_site.sh").read_text(encoding="utf-8")

    def test_charts_before_optional_comparisons(self):
        m=self.monthly
        for name in ('id="monthlyTimeSeries"','id="monthlyChart"','id="monthlyDeviationChart"',
                     'id="monthlyMapSection"','id="monthlyTablesSection"'):
            self.assertIn(name,m)
        self.assertLess(m.index('id="monthlyChart"'),m.index('id="regionalMap"'))
        self.assertLess(m.index('id="monthlyDeviationChart"'),m.index('id="monthlyMapSection"'))
        self.assertLess(m.index('id="monthlyMapSection"'),m.index('id="monthlyTablesSection"'))

    def test_all_controls_maps_and_tables_preserved(self):
        m=self.monthly
        expected=("monthlyAreaSelect","paramSelect","monthSelect","monthlyReferenceSelect",
                  "monthlyReferenceCustomGroup","monthlyRollingSelect","monthlyRollingCustomGroup",
                  "monthlyChart","monthlyDeviationChart","climateMean","top3High","top3Low",
                  "regionalMap","regionalMapB","regionalMapDiff",
                  "regionalDetailChart","regionalDetailDiffChart","regionalRankingBody",
                  "regionalReportText","monthlyAnomalyTable","monthlyAbsoluteAnomalyCard",
                  "monthlyAbsoluteAnomalyTable")
        ids=re.findall(r'\bid="([^"]+)"',m)
        self.assertEqual(len(ids),len(set(ids)))
        for id in expected:
            with self.subTest(element=id):
                self.assertEqual(ids.count(id),1)
        self.assertIn('id="monthlyMapSection"',m)
        self.assertIn('id="monthlyTablesSection"',m)
        self.assertIn('id="monthlyAdvancedSection"',m)

    def test_html_sections_are_balanced(self):
        m=self.monthly
        for tag in ("div","section","details","nav"):
            with self.subTest(tag=tag):
                self.assertEqual(len(re.findall(r"<"+tag+r"(?:\s|>)",m)),
                                 m.count("</"+tag+">"))
        self.assertEqual(m.count("<details"),3)
        self.assertEqual(m.count("</details>"),3)

    def test_map_refresh_is_wired_for_expansion(self):
        s=self.script
        self.assertIn('addEventListener("toggle"',s)
        self.assertIn('typeof updateRegionalMap==="function"',s)
        for name in ("regionalMap","regionalMapB","regionalMapDiff"):
            self.assertIn(name,s)
        self.assertIn("invalidateSize",s)
        self.assertIn("scrollIntoView",s)

    def test_files_published_by_pages(self):
        self.assertIn('href="dashboard_cleanup.css?v=20261014-gebietsmittel3"',self.page)
        self.assertIn('src="monthly_layout.js?v=20261014-gebietsmittel2"',self.page)
        self.assertIn("  dashboard_cleanup.css\n",self.builder)
        self.assertIn("  monthly_layout.js\n",self.builder)
        self.assertEqual(self.css.count("{"),self.css.count("}"))


if __name__=="__main__":
    unittest.main()
