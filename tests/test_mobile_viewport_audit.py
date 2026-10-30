"""Offline tests of the Chromium viewport audit's real repository page prep."""
from pathlib import Path
import importlib.util
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("mobile_viewport_audit",ROOT/"tests/audit_mobile_viewports.py")
M=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class MobileViewportPreparationTests(unittest.TestCase):
    def test_all_target_pages_exist_and_are_original_source(self):
        self.assertEqual(M.WIDTHS,(320,360,390,430))
        self.assertGreaterEqual(len(M.TARGETS),4)
        for _,page,_ in M.TARGETS:
            self.assertTrue((ROOT/page).is_file(),page)
            original=(ROOT/page).read_text(encoding="utf-8")
            self.assertIn("</head>",original.lower())
            self.assertIn("</body>",original.lower())

    def test_original_layout_and_mobile_assets_are_inlined_without_data_scripts(self):
        for _,page,_ in M.TARGETS:
            with self.subTest(page=page):
                cleaned=M.static_document(ROOT,page)
                self.assertIn("cdm-root",cleaned,"mobile menu code present")
                self.assertIn("Mobile-readable meteorological charts",cleaned)
                self.assertIn("Climate Dashboard Deutschland",cleaned)
                self.assertEqual(len(M.SCRIPTS.findall(cleaned)),2)
                self.assertIn("<main",cleaned)

    def test_index_ensemble_tab_and_mosmix_source_identifiable(self):
        index=M.static_document(ROOT,"index.html")
        self.assertIn('id="t850-ensembles"',index)
        self.assertIn('id="mobileTabSelect"',index)
        mosmix=M.static_document(ROOT,"mosmix.html")
        self.assertIn('data-mosmix-standalone="1"',mosmix)
        strato=M.static_document(ROOT,"stratosphaere.html")
        self.assertIn('id="stratoHeatmap"',strato)

    def test_explanatory_limitations_always_reported(self):
        code=(ROOT/"tests/audit_mobile_viewports.py").read_text(encoding="utf-8")
        self.assertIn("dynamic",code.lower())
        self.assertIn("not physical",code.lower())


if __name__=="__main__":
    unittest.main()
