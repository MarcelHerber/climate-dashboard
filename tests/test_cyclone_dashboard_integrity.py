#!/usr/bin/env python3
"""Source-level checks to prevent publishing incomplete cyclone dashboard assets."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestCycloneAdvancedDashboard(unittest.TestCase):
    def test_pages_includes_advanced_js(self):
        script=(ROOT/"scripts/build_pages_site.sh").read_text()
        for name in ["tiefdruck_diagnostics.js","tiefdruck_phase.js",
                     "tiefdruck_tracker.js","tiefdruck_tracker.html"]:
            self.assertIn("  "+name+"\n",script)

    def test_ui_elements_are_present(self):
        html=(ROOT/"tiefdruck_tracker.html").read_text()
        for ident in ["cpsSource","cpsWarmProbability","advPressure","advBergeron",
                      "advGale","advStorm","windOverlay","advComparison",
                      "advDeepeningChart"]:
            self.assertIn('id="'+ident+'"',html)
        self.assertIn('src="tiefdruck_diagnostics.js',html)
        self.assertLess(html.index('src="tiefdruck_diagnostics.js'),
                        html.index('src="tiefdruck_tracker.js'))

    def test_javascript_parses_with_node(self):
        for js in ["tiefdruck_tracker.js","tiefdruck_phase.js","tiefdruck_diagnostics.js"]:
            with self.subTest(js=js):
                subprocess.run(["node","--check",str(ROOT/js)],check=True,capture_output=True)

if __name__=="__main__":
    unittest.main()
