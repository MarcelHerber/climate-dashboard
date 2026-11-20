"""Regression tests for the overview, map scales and chart pixel ratio."""
from html.parser import HTMLParser
from pathlib import Path
import json
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DashboardMarkup(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.stack = []
        self.links = {'overview-quicklink-grid': [], 'overview-more-list': []}
        self.tabs = []
        self.footer = False
        self.footer_after_tabs = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        parents = {c for _, data in self.stack for c in data.get('class', '').split()}
        if 'tab-content' in classes:
            self.tabs.append((attrs.get('id'), 'dashboard-main' in parents))
            self.footer_after_tabs = False
        if tag == 'footer' and 'dashboard-footer' in classes:
            self.footer = 'dashboard-main' in parents
            self.footer_after_tabs = True
        if tag == 'button' and 'overview-quicklink' in classes:
            for key in self.links:
                if key in parents:
                    self.links[key].append(attrs.get('onclick'))
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


class OverviewLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / 'index.html').read_text(encoding='utf-8')
        cls.markup = DashboardMarkup(cls.html)

    def evaluate(self, script):
        return json.loads(subprocess.check_output(['node', '-e', script], text=True))

    def test_zero_is_neutral_and_missing_remains_distinct(self):
        for name, arguments, expected in (
            ('overviewMapScale', '[-2,0,2],"temp"', '#f5f5f3'),
            ('regionalMapScale', '[-2,0,2],"temp","anomaly"', '#f7f7f7'),
            ('regionalMapDifferenceScale', '[-2,0,2],"temp"', '#f7f7f7'),
            ('regionalMapScale', '[-2,0,2],"rain","anomaly"', '#f5f5f5'),
        ):
            with self.subTest(name=name, arguments=arguments):
                source = re.search(r'function '+name+r'\([^\n]*\).*?\n}', self.html, re.S).group()
                result = self.evaluate(f'{source}; const scale={name}({arguments}); console.log(JSON.stringify([-2,0,2,NaN].map(scale.color)));')
                self.assertEqual(result[1], expected)
                self.assertEqual(result[3], '#e5e7eb')
                self.assertEqual(len(set(result)), 4)

    def test_six_direct_links_and_four_disclosure_links(self):
        self.assertEqual(self.markup.links['overview-quicklink-grid'],
                         [f"switchTab('{tab}')" for tab in ('monthly','hyras','stationProfile','current','records','europeHub')])
        self.assertEqual(self.markup.links['overview-more-list'],
                         [f"window.location.href='{page}.html'" for page in ('jahresextremwerte','feiertagsextremwerte','dekadenrekorde')]+["switchTab('compare')"])
        self.assertRegex(self.html, r'<details class="overview-more-links">\s*<summary>Weitere Auswertungen <span>4 Bereiche</span></summary>')

    def test_all_tabs_and_footer_share_the_main_container(self):
        self.assertGreater(len(self.markup.tabs), 10)
        self.assertEqual([name for name, inside in self.markup.tabs if not inside], [])
        self.assertTrue(self.markup.footer and self.markup.footer_after_tabs)

    def test_overview_css_has_responsive_overrides_after_theme(self):
        head = self.html.split('</head>')[0]
        tail = head[head.index('href="dashboard_theme.css'):]
        self.assertRegex(tail, r'\.overview-source-table\s*\{\s*font-size:\s*12px')
        self.assertRegex(tail, r'grid-template-columns:\s*1\.08fr 0\.82fr 1fr')
        self.assertRegex(tail, r'@media\s*\(max-width:\s*800px\)\s*\{[^}]*\.overview-mini-grid\s*\{\s*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)')
        self.assertRegex(tail, r'@media\s*\(max-width:\s*360px\)\s*\{\s*\.overview-mini-grid\s*\{\s*grid-template-columns:\s*1fr')

    def test_canvas_uses_native_pixel_ratio_capped_at_two(self):
        assignment = re.search(r'Chart\.defaults\.devicePixelRatio\s*=.*?;', self.html, re.S).group()
        for ratio, expected in ((1, 1), (1.5, 1.5), (2, 2), (3, 2)):
            with self.subTest(ratio=ratio):
                result = self.evaluate(f'const Chart={{defaults:{{}}}}, window={{devicePixelRatio:{ratio}}}; {assignment} console.log(JSON.stringify(Chart.defaults.devicePixelRatio));')
                self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
