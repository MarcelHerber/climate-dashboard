"""Tests for the generated Pages mobile navigation across all root HTML files."""
from __future__ import annotations
import importlib.util
import tempfile
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("mobile_inject",ROOT/"scripts/inject_mobile_navigation.py")
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MobileNavigationBuildTests(unittest.TestCase):
    def test_inject_head_and_body_once(self):
        raw='<!doctype html><html><head><meta name="viewport" content="width=device-width"></head><body><main><h1>Klima</h1></main></body></html>'
        first=MODULE.inject(raw)
        second=MODULE.inject(first)
        self.assertEqual(first,second)
        self.assertEqual(first.count("mobile_navigation.css"),1)
        self.assertEqual(first.count("mobile_navigation.js"),1)
        self.assertLess(first.index("mobile_navigation.css"),first.index("</head>"))
        self.assertLess(first.index("mobile_navigation.js"),first.index("</body>"))
        self.assertIn("<main><h1>Klima</h1></main>",first)

    def test_case_insensitive_html_and_missing_tags_rejected(self):
        page='<HTML><HEAD><title>Test</title></HEAD><BODY><p>Test</p></BODY></HTML>'
        result=MODULE.inject(page)
        self.assertEqual(result.count("mobile_navigation.css"),1)
        self.assertEqual(result.count("mobile_navigation.js"),1)
        for broken in ("<html><body>no head</body></html>","<html><head></head><body>no close"):
            with self.assertRaises(ValueError):MODULE.inject(broken)

    def test_deploy_every_root_html_including_subpages_and_not_other_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            (base/"mobile_navigation.js").write_text("/* asset */",encoding="utf-8")
            (base/"mobile_navigation.css").write_text("/* asset */",encoding="utf-8")
            original='<html><head></head><body><header>Navigation</header><main>Data</main></body></html>'
            for name in ("index.html","stratosphaere.html","weltweite_isobaren.html"):
                (base/name).write_text(original,encoding="utf-8")
            nested=base/"other";nested.mkdir()
            (nested/"internal.html").write_text(original,encoding="utf-8")
            result=MODULE.deploy(base)
            self.assertEqual(result,sorted(["index.html","stratosphaere.html","weltweite_isobaren.html"]))
            self.assertIn("mobile_navigation.js",(base/"stratosphaere.html").read_text(encoding="utf-8"))
            self.assertNotIn("mobile_navigation.js",(nested/"internal.html").read_text(encoding="utf-8"))
            self.assertEqual(MODULE.deploy(base),result)

    def test_no_partial_publish_if_one_html_malformed(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            (base/"mobile_navigation.js").write_text("x",encoding="utf-8")
            (base/"mobile_navigation.css").write_text("x",encoding="utf-8")
            good="<html><head></head><body>OK</body></html>"
            (base/"index.html").write_text(good,encoding="utf-8")
            (base/"broken.html").write_text("<body>broken",encoding="utf-8")
            with self.assertRaises(ValueError):MODULE.deploy(base)
            self.assertEqual((base/"index.html").read_text(encoding="utf-8"),good)


if __name__=="__main__":
    unittest.main()
