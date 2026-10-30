from scripts.check_hyras_integrity import expected_days
import unittest


class HyrasIntegrityTests(unittest.TestCase):
    def test_leap_and_normal_year(self):
        self.assertEqual(expected_days("2024-01-01", "2024-12-31"), 366)
        self.assertEqual(expected_days("2025-01-01", "2025-12-31"), 365)
        self.assertEqual(expected_days("2026-01-01", "2026-10-28"), 301)


if __name__ == "__main__":
    unittest.main()
