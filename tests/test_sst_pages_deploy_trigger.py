from pathlib import Path
import unittest


class PagesDeployTriggerTests(unittest.TestCase):
    def test_archive_and_test_only_commits_do_not_redeploy_live_pages(self):
        workflow = Path(".github/workflows/deploy-pages-only.yml").read_text(encoding="utf-8")

        self.assertIn("paths-ignore:", workflow)
        self.assertIn('      - ".github/workflows/**"', workflow)
        self.assertIn('      - "tests/**"', workflow)
        self.assertIn('      - "docs/**"', workflow)


if __name__ == "__main__":
    unittest.main()
