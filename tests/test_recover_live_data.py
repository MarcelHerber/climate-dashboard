import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from recover_live_data import needs_recovery, can_dispatch


class RecoveryTests(unittest.TestCase):
    now = datetime(2026, 11, 15, 17, 30, tzinfo=timezone.utc)

    def test_fast_live_uses_measurement_not_build_time(self):
        manifest = {'station_count': 100, 'latest_measurement_utc': '2026-11-15T10:30:00Z',
                    'generated_at_utc': '2026-11-15T17:29:00Z'}
        self.assertTrue(needs_recovery('fast_live', manifest, self.now))
        manifest['latest_measurement_utc'] = '2026-11-15T17:15:00Z'
        self.assertFalse(needs_recovery('fast_live', manifest, self.now))

    def test_missing_future_and_invalid_are_not_restarted(self):
        for value in (None, 'garbage', '2026-11-16T00:00:00Z'):
            self.assertFalse(needs_recovery('fast_live', {'station_count': 2, 'latest_measurement_utc': value}, self.now))

    def test_opera_uses_latest_of_each_verified_product(self):
        manifest = {'products': {'dbzh': {'frames': [{'utc': '2026-11-15T17:15:00Z'}]},
                                 'rate': {'frames': [{'utc': '2026-11-15T15:00:00Z'}]}}}
        self.assertTrue(needs_recovery('opera', manifest, self.now))
        manifest['products']['rate']['frames'].append({'utc': '2026-11-15T17:00:00Z'})
        self.assertFalse(needs_recovery('opera', manifest, self.now))

    def test_active_and_recent_runs_block_dispatch(self):
        self.assertFalse(can_dispatch([{'status': 'queued', 'createdAt': '2026-11-15T12:00:00Z'}], self.now))
        self.assertFalse(can_dispatch([{'status': 'completed', 'createdAt': '2026-11-15T17:00:00Z'}], self.now))
        self.assertTrue(can_dispatch([{'status': 'completed', 'createdAt': '2026-11-15T16:00:00Z'}], self.now))
        self.assertFalse(can_dispatch([], self.now))
