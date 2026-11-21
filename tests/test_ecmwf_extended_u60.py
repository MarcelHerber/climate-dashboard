import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np


class ExtendedTests(unittest.TestCase):
    def module(self):
        self.assertTrue(Path('scripts/build_ecmwf_extended_u60.py').is_file(), '46-day importer missing')
        from scripts import build_ecmwf_extended_u60 as m
        return m

    def test_complete_ring_even_with_wrapped_endpoint(self):
        m = self.module()
        lon = np.arange(-180, 181, 1.5)
        self.assertAlmostEqual(m.mean_u60(np.full(len(lon), 60), lon, np.full(len(lon), 12.5)), 12.5)
        with self.assertRaises(ValueError):
            m.mean_u60(np.full(len(lon)-2, 60), lon[1:-1], np.ones(len(lon)-2))

    def test_request_for_all_members_and_days(self):
        m = self.module()
        req = m.retrieval_request(datetime(2026, 11, 19, tzinfo=timezone.utc), True)
        self.assertEqual(req['origin'], 'ecmwf')
        self.assertEqual(req['level_value'], ['10_hpa'])
        self.assertEqual(req['forecast_type'], 'perturbed_forecast')
        self.assertEqual(len(req['leadtime_hour']), 47)
        self.assertEqual(req['leadtime_hour'][-1], '1104')

    def test_complete_run_only(self):
        m = self.module()
        cycle = datetime(2026, 11, 19, tzinfo=timezone.utc)
        members = {'c00': [5.0]*47, **{f'p{i:03d}': [i/10]*47 for i in range(1, 101)}}
        result = m.payload(cycle, members)
        self.assertEqual(result['valid_dates'][-1], '2027-01-04')
        self.assertEqual(result['member_count'], 101)
        self.assertTrue(m.validate(result))
        del result['members']['p100']
        self.assertFalse(m.validate(result))

    def test_archive_fills_gaps_without_replacing_latest(self):
        m = self.module()
        newest = datetime(2026, 11, 19, tzinfo=timezone.utc)
        members = {'c00': [5.0]*47, **{f'p{i:03d}': [i/10]*47 for i in range(1, 101)}}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            m.publish(root, m.payload(newest, members))
            self.assertEqual(m.next_cycle(root, newest), newest-timedelta(days=1))
            for day in range(1, 8):
                m.publish(root, m.payload(newest-timedelta(days=day), members))
            import json
            self.assertEqual(json.loads((root/'current.json').read_text())['cycle_utc'], '2026-11-19T00:00:00Z')
            self.assertEqual(len(json.loads((root/'index.json').read_text())['runs']), 8)
            self.assertIsNone(m.next_cycle(root, newest))


if __name__ == '__main__':
    unittest.main()
