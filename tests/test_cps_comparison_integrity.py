"""Check that the 3-model CPS view is completely wired into the Pages site."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class TestCpsThreeModelSite(unittest.TestCase):
    def test_all_elements_and_script_order(self):
        html=(ROOT/"tiefdruck_tracker.html").read_text(encoding="utf-8")
        expected=[
            "cpsCompareMetric","cpsCompareExport","cpsCompareStorm",
            "cpsCompareGfs","cpsCompareIfs","cpsCompareAifs",
            "cpsCompareTogether","cpsCompareSelectedTime","cpsCompareAxes",
            "cpsCompareContent","cpsCompareEmpty",
            "cpsCompareStatusGFS","cpsCompareStatusIFS","cpsCompareStatusAIFS",
            "cpsCompareUnavailableGFS","cpsCompareUnavailableIFS",
            "cpsCompareUnavailableAIFS",
            "cpsCompareNowGFS","cpsCompareNowIFS","cpsCompareNowAIFS"
        ]
        for element in expected:
            with self.subTest(element=element):
                self.assertEqual(html.count('id="'+element+'"'),1)
        self.assertLess(html.index('src="tiefdruck_cps_compare.js'),
                        html.index('src="tiefdruck_tracker.js'))

    def test_on_storm_change_and_forecast_slider(self):
        js=(ROOT/"tiefdruck_tracker.js").read_text(encoding="utf-8")
        self.assertIn("window.CycloneCpsComparison.update(t,allData,chosenHour())",js)
        self.assertIn("window.CycloneCpsComparison.update(null,allData,chosenHour())",js)
        self.assertIn('$("hour").addEventListener("input",()=>repaint(false))',js)

    def test_pages_includes_new_javascript_and_responsive_css(self):
        sh=(ROOT/"scripts/build_pages_site.sh").read_text(encoding="utf-8")
        css=(ROOT/"tiefdruck_tracker.css").read_text(encoding="utf-8")
        self.assertIn("  tiefdruck_cps_compare.js\n",sh)
        self.assertIn(".cps-compare-grid",css)
        self.assertIn("@media(max-width:690px)",css)

if __name__=="__main__":
    unittest.main()
