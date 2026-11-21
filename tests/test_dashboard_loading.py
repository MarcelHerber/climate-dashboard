import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/optimize_dashboard_loading.py"


class SnapshotKeyTest(unittest.TestCase):
    def test_stratosphere_index_timestamp_is_a_cache_buster(self):
        # mitmproxy is runner-only; key() itself needs no HTTP flow.
        with tempfile.TemporaryDirectory() as root, patch.dict(
            sys.modules, {"mitmproxy": SimpleNamespace(http=SimpleNamespace(HTTPFlow=object))}
        ), patch.dict("os.environ", {"PERF_SNAPSHOT_ROOT": root}):
            key = runpy.run_path(str(ROOT / "scripts/performance_snapshot_proxy.py"))["key"]
        url = "https://marcelherber.github.io/climate-dashboard/era5_stratosphere/index.json"
        self.assertEqual(key(url + "?ts=1795294683792"), url)
        self.assertEqual(key(url + "?ts=1795294698123&model=ifs"), url + "?model=ifs")
        self.assertEqual(key(url + "?ts=analysis"), url + "?ts=analysis")
        other = "https://marcelherber.github.io/climate-dashboard/data.json?ts=20261121"
        self.assertEqual(key(other), other)


class DashboardLoadingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name)
        self.original = (ROOT / "index.html").read_bytes()
        (self.site / "index.html").write_bytes(self.original)
        if (ROOT / "js").is_dir():
            shutil.copytree(ROOT / "js", self.site / "js")

    def optimize(self, stage):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.site), "--stage", stage],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return (self.site / "index.html").read_bytes()

    def test_split_sources_build_in_order_and_lazy_exports_still_work(self):
        for name in ("core", "uebersicht", "gebietsmittel", "extreme", "stationen-kenntage", "stationen-auswertungen", "schnee", "export-karten-vergleich", "stationsprofil", "hyras", "aktuell", "era5-land", "europa-stationen", "dashboard-state", "hyras-tmin", "bootstrap"):
            self.assertTrue((ROOT / "js" / f"{name}.js").is_file(), name)
        for name in ("dashboard_theme.js", "monthly_frequency.js", "state_monthly_ensemble.js",
                     "t850_ensembles.js", "sst_europe.js", "station_thresholds.js",
                     "gebietsmittel_archiv.js", "mosmix.js", "scientific_vector_actions.js"):
            shutil.copyfile(ROOT / name, self.site / name)
        html = self.optimize("lazy").decode()
        tags = re.findall(r'<script\b[^>]*\bsrc=[^>]*>', html)
        for name in ("js/core.js", "js/uebersicht.js", "js/gebietsmittel.optimized.js", "js/extreme.js", "js/stationen-kenntage.optimized.js", "js/stationen-auswertungen.optimized.js", "js/schnee.js", "js/bootstrap.js"):
            self.assertEqual(sum(name in tag for tag in tags), 1, name)
        joined = "\n".join(tags)
        order = [joined.index(name) for name in ("chartjs-plugin-datalabels", "js/core.js", "js/uebersicht.js", "js/gebietsmittel.optimized.js", "js/extreme.js", "js/stationen-kenntage.optimized.js", "js/stationen-auswertungen.optimized.js", "js/schnee.js", "dashboard_export_libraries.js", "js/export-karten-vergleich", "js/stationsprofil", "js/hyras.optimized.js", "js/aktuell", "js/era5-land", "js/europa-stationen", "js/dashboard-state.js", "js/hyras-tmin.optimized.js", "js/bootstrap.js", "dashboard_export_hq.js")]
        self.assertEqual(order, sorted(order))
        self.assertIn("await window.dashboardExportLibraries.canvas()", (self.site / "js/gebietsmittel.optimized.js").read_text())
        self.assertIn("await window.dashboardExportLibraries.canvas()", (self.site / "js/stationen-auswertungen.optimized.js").read_text())
        for library in ('canvas', 'pdf'):
            self.assertIn(f"await window.dashboardExportLibraries.{library}()", (self.site / "js/stationen-kenntage.optimized.js").read_text())
        self.assertNotIn("npm/html2canvas@", html)
        self.assertNotIn("npm/jspdf@", html)

    def test_extract_preserves_script_bytes_and_position(self):
        matches = list(re.finditer(rb"<script>(\s*(?:// ================= VERSION 9: ZUSTAND, MOBILE NAVIGATION, CSV|// Start-Abrufe).*?)</script>", self.original, re.S))
        self.assertEqual(len(matches), 0)
        html = self.optimize("extract")
        self.assertEqual(html, self.original)
        self.assertFalse((self.site / "dashboard_main.js").exists())

    def test_defer_keeps_dependencies_and_inline_theme(self):
        html = self.optimize("defer").decode()
        tags = re.findall(r"<script\b[^>]*\bsrc=[^>]*>", html)
        self.assertTrue(all(re.search(r"\bdefer\b", tag) and not re.search(r"\basync\b", tag) for tag in tags))
        joined = "\n".join(tags)
        for first, second in [
            ("chart.umd.min.js", "chartjs-plugin-zoom"),
            ("chartjs-plugin-datalabels", "js/core.js"),
            ("leaflet.js", "js/core.js"),
            ("state_monthly_ensemble.js", "js/bootstrap.js"),
            ("js/bootstrap.js", "monthly_frequency.js"),
            ("js/bootstrap.js", "dashboard_export_hq.js"),
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
        self.assertLess(html.index("dashboard_export_libraries.js"), html.index("js/bootstrap.js"))
        for script in self.site.rglob("*.js"):
            result = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        export = (self.site / "js/export-karten-vergleich.optimized.js").read_text()
        self.assertIn("else await exportChartAsPdf(canvas)", export)
        self.assertIn("await window.dashboardExportLibraries.pdf()", export)
        current = (self.site / "js/aktuell.optimized.js").read_text()
        self.assertIn("await window.dashboardExportLibraries.canvas()", current)
        self.assertIn("await window.dashboardExportLibraries.pdf()", current)
        self.assertEqual((self.site / "js/hyras.optimized.js").read_text().count("await window.dashboardExportLibraries.pdf()"), 2)
        self.assertEqual((self.site / "js/hyras-tmin.optimized.js").read_text().count("await window.dashboardExportLibraries.pdf()"), 1)

    def test_hyras_classic_scripts_keep_overrides_at_end(self):
        html = self.original.decode()
        self.assertNotIn('function hyrasNum(', html)
        self.assertNotIn('const hyrasSwitchBeforeTmin=', html)
        self.assertLess(html.index('js/hyras.js?'), html.index('js/aktuell.js?'))
        self.assertFalse('initializeDashboardState();' in html, 'Bootstrap must not start while the Tmin script is still downloading')
        late = (ROOT / 'js/hyras-tmin.js').read_text()
        bootstrap = (ROOT / 'js/bootstrap.js').read_text()
        for call in ('initializeChartExportButtons();', 'preloadEuropeStationData().catch(()=>{});', 'initializeDashboardState();'):
            self.assertNotIn(call, late)
            self.assertEqual(bootstrap.count(call), 1)
        self.assertIn('function initializeDashboardState()', (ROOT / 'js/dashboard-state.js').read_text())
        self.assertLess(html.index('js/dashboard-state.js?'), html.index('js/hyras-tmin.js?'))
        self.assertLess(html.index('js/hyras-tmin.js?'), html.index('js/bootstrap.js?'))
        self.assertLess(html.index('js/bootstrap.js?'), html.index('hyras_historical_temperature_1km.js?'))


if __name__ == "__main__":
    unittest.main()
