from pathlib import Path
import unittest


class SstBackfillChainWorkflowTests(unittest.TestCase):
    def test_workflow_can_bootstrap_and_chain_months_sequentially(self):
        workflow = Path(".github/workflows/backfill-sst-europe.yml").read_text(encoding="utf-8")

        self.assertIn('branches: ["main"]', workflow)
        self.assertIn('paths:\n      - ".github/workflows/backfill-sst-europe.yml"', workflow)
        self.assertIn('[start-sst-archive]', workflow)
        self.assertIn('chain:', workflow)
        self.assertIn('actions: write', workflow)
        self.assertIn('2020-01', workflow)
        self.assertIn('NEXT_MONTH', workflow)
        self.assertIn('gh workflow run backfill-sst-europe.yml', workflow)
        self.assertIn('-f chain=true', workflow)
        self.assertIn('cancel-in-progress: false', workflow)


if __name__ == "__main__":
    unittest.main()
