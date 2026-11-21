import tempfile
import unittest
import subprocess
import re
from pathlib import Path

from scripts import stage_ifs_weekly


class StageTests(unittest.TestCase):
    def test_arctic_html_is_copied_into_pages_artifact(self):
        # Exercise the real root-file staging loop with a minimal site.
        script = (Path(__file__).resolve().parents[1] / 'scripts/build_pages_site.sh').read_text()
        block = script.split('# Phase 2: add source-specific', 1)[0]
        root_files = re.search(r'required_root_files=\(\n(.*?)\n\)', block, re.S).group(1).split()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in root_files:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('stub')
            (root / 'ifs_weekly_arctic.html').write_text('Arctic map page')
            subprocess.run(['bash', '-c', block], cwd=root, check=True, capture_output=True)
            self.assertTrue((root / '_site/ifs_weekly_arctic.html').is_file(),
                            'Arctic page must be included in the public artifact')
            for module in ('core', 'uebersicht', 'gebietsmittel', 'extreme', 'stationen-kenntage', 'stationen-auswertungen', 'schnee', 'export-karten-vergleich', 'stationsprofil', 'hyras', 'aktuell', 'hyras-tmin'):
                self.assertEqual((root / f'_site/js/{module}.js').read_text(), 'stub')
            self.assertEqual((root / '_site/era5_stratosphere.js').read_text(), 'stub')

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
