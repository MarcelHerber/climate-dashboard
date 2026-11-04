"""Scientific checks for IMS maps; no fabricated values enter published maps."""
import datetime as dt
import gzip
import importlib.util
from pathlib import Path
import unittest

import numpy as np

PATH = Path(__file__).resolve().parents[1] / 'scripts/update_snow_maps.py'


class SnowMapChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = None
        if PATH.exists():
            spec = importlib.util.spec_from_file_location('snow_maps', PATH)
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)

    def maps(self):
        self.assertIsNotNone(self.module, 'IMS map calculation has not been implemented')
        return self.module

    def test_departure_sign_land_mask_and_real_sample_count(self):
        m = self.maps()
        reference = np.array([[4, 2, 1, 4, 4], [2, 2, 3, 0, 2]], dtype=np.uint8)
        snow, count = m.reference_counts([reference] * 15)
        current = np.array([[2, 4, 4, 3, 0], [2, 2, 2, 2, 4]], dtype=np.uint8)
        departure = m.snow_departure(current, snow, count, minimum=15)
        np.testing.assert_allclose(departure[0, :2], [-100, 100])
        self.assertTrue(np.isnan(departure[0, 2:]).all())
        np.testing.assert_allclose(departure[1, [0, 1, 4]], [0, 0, 100])
        self.assertTrue(np.isnan(departure[1, 2:4]).all())
        self.assertEqual(int(count[0, 2]), 0)

    def test_reference_is_occurrence_not_mean_snow_code(self):
        m = self.maps()
        grids = [np.array([[4, 2]], dtype=np.uint8)] * 5
        grids += [np.array([[2, 4]], dtype=np.uint8)] * 15
        snow, count = m.reference_counts(grids)
        actual = m.snow_departure(np.array([[4, 2]], dtype=np.uint8), snow, count)
        np.testing.assert_allclose(actual, [[75, -75]])
        snow, count = m.reference_counts(grids[:14])
        self.assertTrue(np.isnan(m.snow_departure(grids[0], snow, count)).all())

    def test_ascii_formats_and_incomplete_rejected(self):
        m = self.maps()
        packed = b'2' * 1024 + b'\n'
        parsed = m.parse_grid(gzip.compress(b'header\n' + packed * 1024))
        self.assertEqual(parsed.shape, (1024, 1024))
        expanded = b'   2' * 16 + b'\n'
        parsed = m.parse_grid(gzip.compress(b'header\n' + expanded * 65536))
        self.assertTrue((parsed == 2).all())
        with self.assertRaises(ValueError):
            m.parse_grid(gzip.compress(b'2' * 1024))
        with self.assertRaises(ValueError):
            m.parse_grid(gzip.compress(b'<html>2</html>'))

    def test_reference_dates_use_calendar_date_and_real_leap_years(self):
        m = self.maps()
        dates, minimum = m.reference_dates(dt.date(2026, 11, 3))
        self.assertEqual([d.year for d in dates], list(range(2001, 2021)))
        self.assertTrue(all((d.month, d.day) == (11, 3) for d in dates))
        self.assertEqual(minimum, 15)
        leap, minimum = m.reference_dates(dt.date(2024, 2, 29))
        self.assertEqual([d.year for d in leap], [2004, 2008, 2012, 2016, 2020])
        self.assertEqual(minimum, 4)

    def test_projection_ascii_rows_start_in_the_south(self):
        m = self.maps()
        # NSIDC lower-left origin; 80 W is below pole, 100 E above pole.
        row_south, col_south = m.ascii_indices(np.array([60.]), np.array([-80.]))
        row_north, col_north = m.ascii_indices(np.array([60.]), np.array([100.]))
        self.assertLess(int(row_south[0]), 512)
        self.assertGreater(int(row_north[0]), 512)
        self.assertLess(abs(int(col_south[0]) - 512), 2)
        self.assertLess(abs(int(col_north[0]) - 512), 2)

    def test_seven_available_days_include_latest_not_yet_arrived_today(self):
        m = self.maps()
        today = dt.date(2026, 11, 4)
        catalog = {2026: {dt.date(2026, 10, 27) + dt.timedelta(days=i): 'source' for i in range(9)}}
        dates = m.available_dates(catalog, today, 7)
        self.assertEqual(dates[0], dt.date(2026, 11, 4))
        self.assertEqual(len(dates), 7)
        catalog[2026].pop(today)
        dates = m.available_dates(catalog, today, 7)
        self.assertEqual(dates[0], dt.date(2026, 11, 3))
        self.assertEqual(dates[-1], dt.date(2026, 10, 28))

    def test_pair_validation_requires_both_opaque_full_size_images(self):
        m = self.maps()
        from PIL import Image
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            cover, anomaly = directory / 'cover.png', directory / 'anomaly.png'
            Image.new('RGB', (3520, 1188), 'white').save(cover)
            self.assertFalse(m.complete_pair(directory, {'cover': cover.name, 'anomaly': anomaly.name}))
            Image.new('RGBA', (3520, 1188), (255, 255, 255, 0)).save(anomaly)
            self.assertFalse(m.complete_pair(directory, {'cover': cover.name, 'anomaly': anomaly.name}))
            Image.new('RGB', (3520, 1188), 'white').save(anomaly)
            self.assertTrue(m.complete_pair(directory, {'cover': cover.name, 'anomaly': anomaly.name}))

    def test_failed_second_render_preserves_both_previous_images(self):
        m = self.maps()
        import json
        import tempfile
        from unittest.mock import patch
        from PIL import Image
        date = dt.date(2026, 11, 3)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'maps'
            (root / 'images').mkdir(parents=True)
            old = {'date': str(date), 'cover': f'images/{date}_cover.png',
                   'anomaly': f'images/{date}_anomaly.png', 'version': -1}
            for kind in ('cover', 'anomaly'):
                Image.new('RGB', (3520, 1188), 'white').save(root / old[kind])
            original = {kind: (root / old[kind]).read_bytes() for kind in ('cover', 'anomaly')}
            (root / 'index.json').write_text(json.dumps({'maps': [old]}))
            def inventory(archive, year):
                archive.catalogs[year] = {dt.date(year, 11, 3): 'https://example.org/ims.asc.gz'}
                return archive.catalogs[year]
            def fail_second(path, field, date, countries, **kwargs):
                if kwargs['anomaly']:
                    raise OSError('Injected second-render failure')
                Image.new('RGB', (3520, 1188), 'blue').save(path)
            row = np.zeros((280, 1440), dtype=int)
            with patch.object(m.Archive, 'inventory', inventory), \
                 patch.object(m.Archive, 'grid', return_value=np.full((1024, 1024), 2, dtype=np.uint8)), \
                 patch.object(m, 'geography', return_value={}), \
                 patch.object(m, 'display_indices', return_value=(row, row)), \
                 patch.object(m, 'render', side_effect=fail_second):
                result = m.update(root, Path(tmp) / 'cache', days=1, today=date)
            self.assertEqual(result['maps'][0], old)
            for kind in ('cover', 'anomaly'):
                self.assertEqual((root / old[kind]).read_bytes(), original[kind])


if __name__ == '__main__':
    unittest.main()
