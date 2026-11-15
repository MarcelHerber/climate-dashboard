import tempfile
import unittest
from pathlib import Path

from scripts import stage_ifs_weekly


class StageTests(unittest.TestCase):
    def test_nav_link_only_once_in_desktop_and_mobile(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'index.html').write_text('<a class="tab-button" data-nav-group="misc" href="gfs_weekly_europe.html">GFS</a>')
            (root / 'mobile_navigation.js').write_text('[ ["gfs_weekly_europe.html","GFS · 7-Tage-Temperaturanomalie"] ]')
            stage_ifs_weekly.add_navigation(root)
            stage_ifs_weekly.add_navigation(root)
            for file in ('index.html', 'mobile_navigation.js'):
                self.assertEqual((root / file).read_text().count('ifs_weekly_europe.html'), 1)

    def test_missing_data_fails_before_publishing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(FileNotFoundError):
                stage_ifs_weekly.validate(root)


if __name__ == '__main__':
    unittest.main()
