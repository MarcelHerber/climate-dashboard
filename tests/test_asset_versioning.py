"""Regression tests for local content-hash asset versioning."""
import json
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


if __name__ == "__main__":
    unittest.main()
