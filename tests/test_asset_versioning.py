"""Regression tests for local content-hash asset versioning."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "version_assets.py"


class AssetVersioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "js").mkdir()
        (self.root / "index.html").write_text(
            '<script src="js/loader.js?v=old"></script>\n'
            '<link rel="stylesheet" href="style.css">\n', encoding="utf-8")
        (self.root / "second.html").write_text(
            '<script src="js/loader.js"></script>\n', encoding="utf-8")
        (self.root / "style.css").write_text("body { color: black }\n", encoding="utf-8")
        (self.root / "js/loader.js").write_text(
            'const MODULES={"hyras":["js/hyras.js","old"]};\n', encoding="utf-8")
        (self.root / "js/hyras.js").write_text(
            "function renderHyras() { return 1; }\n", encoding="utf-8")

    def run_tool(self, *args, success=0):
        result = subprocess.run(
            [sys.executable, str(TOOL), "--root", str(self.root),
             "--html", "index.html", "second.html", *args],
            text=True, capture_output=True)
        self.assertEqual(result.returncode, success, result.stdout + result.stderr)
        return result

    def test_propagation_and_idempotence(self):
        target = self.root / "site"
        self.run_tool("--manifest", str(self.root / "assets.json"),
                      "--copy-to", str(target), "--verify-dir", str(target))
        original_html = (self.root / "index.html").read_text()
        manifest = json.loads((self.root / "assets.json").read_text())
        self.assertIn("js/hyras.js", manifest["assets"])
        self.assertIn("style.css", manifest["assets"])
        self.run_tool("--check")
        (self.root / "js/hyras.js").write_text(
            "function renderHyras() { return 2; }\n", encoding="utf-8")
        self.run_tool("--check", success=1)
        self.run_tool("--verify-dir", str(target), success=1)
        self.run_tool()
        self.assertNotEqual((self.root / "index.html").read_text(), original_html)
        self.run_tool("--check")

    def test_missing_asset_fails(self):
        (self.root / "js/hyras.js").unlink()
        self.run_tool(success=2)

    def test_tampered_html_must_fail_verification(self):
        target = self.root / "site"
        self.run_tool("--copy-to", str(target))
        (target / "index.html").write_text("stale html", encoding="utf-8")
        self.run_tool("--check", "--verify-dir", str(target), success=1)


    def test_static_reference_detects_missing_tampered_and_extra_vendor(self):
        vendor = self.root / "vendor" / "leaflet" / "dist"
        images = vendor / "images"
        images.mkdir(parents=True)
        (vendor / "leaflet.css").write_text(
            "div{background:url(images/marker.png)}\\n", encoding="utf-8")
        (images / "marker.png").write_bytes(b"PNG-TEST")
        (vendor / "leaflet.js").write_bytes(b"/* pinned dependency */")
        site = self.root / "site"
        site.mkdir()
        shutil.copytree(self.root / "vendor", site / "vendor")
        shutil.copytree(self.root / "js", site / "js")
        for path in ("index.html", "second.html", "style.css"):
            shutil.copy2(self.root / path, site / path)
        with (site / "index.html").open("a", encoding="utf-8") as out:
            out.write('<link href="vendor/leaflet/dist/leaflet.css">\\n')

        cmd = [sys.executable, str(TOOL), "--root", str(site), "--html",
               "index.html", "second.html", "--static-dir", "vendor",
               "--static-reference", str(self.root)]

        def run(*extra, expected=0):
            result = subprocess.run(cmd + list(extra), capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            return result.stdout + result.stderr

        run()
        run("--check")
        # Regression: self-comparison (--verify-dir site) falsely passed here.
        (site / "vendor/leaflet/dist/images/marker.png").unlink()
        self.assertIn("fehlt im Build", run("--check", expected=1))
        shutil.copy2(images / "marker.png", site / "vendor/leaflet/dist/images/marker.png")
        (site / "vendor/leaflet/dist/leaflet.css").write_text(
            "div{background:red}\\n", encoding="utf-8")
        self.assertIn("weicht von der Vorlage ab", run("--check", expected=1))
        shutil.copy2(vendor / "leaflet.css", site / "vendor/leaflet/dist/leaflet.css")
        (site / "vendor/leaflet/dist/extra.txt").write_text("unexpected")
        self.assertIn("unerwartete Datei", run("--check", expected=1))
        (site / "vendor/leaflet/dist/extra.txt").unlink()
        run("--check")

        original = (site / "vendor/leaflet/dist/leaflet.js").read_bytes()
        run("--copy-to", str(site))
        self.assertEqual((site / "vendor/leaflet/dist/leaflet.js").read_bytes(), original)
        run("--check")
        run("--static-reference", str(site), "--check", expected=2)


if __name__ == "__main__":
    unittest.main()
