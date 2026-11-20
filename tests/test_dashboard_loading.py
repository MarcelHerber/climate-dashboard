import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/optimize_dashboard_loading.py"


class DashboardLoadingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name)
        self.original = (ROOT / "index.html").read_bytes()
        (self.site / "index.html").write_bytes(self.original)

    def optimize(self, stage):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.site), "--stage", stage],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return (self.site / "index.html").read_bytes()

    def test_extract_preserves_script_bytes_and_position(self):
        match = re.search(rb"<script>(\s*Chart\.register\(ChartDataLabels\);.*?)</script>", self.original, re.S)
        self.assertIsNotNone(match)
        html = self.optimize("extract")
        self.assertEqual((self.site / "dashboard_main.js").read_bytes(), match[1])
        self.assertEqual(re.sub(rb'<script src="dashboard_main\.js\?v=[a-f0-9]+"></script>', lambda _: match[0], html), self.original)

    def test_defer_keeps_dependencies_and_inline_theme(self):
        html = self.optimize("defer").decode()
        tags = re.findall(r"<script\b[^>]*\bsrc=[^>]*>", html)
        self.assertTrue(all(re.search(r"\bdefer\b", tag) and not re.search(r"\basync\b", tag) for tag in tags))
        joined = "\n".join(tags)
        for first, second in [
            ("chart.umd.min.js", "chartjs-plugin-zoom"),
            ("chartjs-plugin-datalabels", "dashboard_main.js"),
            ("leaflet.js", "dashboard_main.js"),
            ("state_monthly_ensemble.js", "dashboard_main.js"),
            ("dashboard_main.js", "monthly_frequency.js"),
            ("dashboard_main.js", "dashboard_export_hq.js"),
        ]:
            self.assertLess(joined.index(first), joined.index(second))
        self.assertEqual(len(re.findall(r"<script>", html)), 1)

    def test_lazy_removes_eager_libraries_and_keeps_export_consumers_awaitable(self):
        for name in ("dashboard_theme.js", "monthly_frequency.js", "state_monthly_ensemble.js",
                     "t850_ensembles.js", "sst_europe.js", "station_thresholds.js",
                     "gebietsmittel_archiv.js", "mosmix.js", "scientific_vector_actions.js"):
            shutil.copyfile(ROOT / name, self.site / name)
        html = self.optimize("lazy").decode()
        self.assertNotIn("npm/jspdf@", html)
        self.assertNotIn("npm/html2canvas@", html)
        self.assertLess(html.index("dashboard_export_libraries.js"), html.index("dashboard_main.js"))
        for script in self.site.glob("*.js"):
            result = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        main = (self.site / "dashboard_main.js").read_text()
        self.assertIn("else await exportChartAsPdf(canvas)", main)
        self.assertIn("await window.dashboardExportLibraries.canvas()", main)
        self.assertIn("await window.dashboardExportLibraries.pdf()", main)


if __name__ == "__main__":
    unittest.main()
