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

    def test_live_imports_recover_before_an_hour(self):
        self.assertTrue(needs_recovery('fast_live', {'station_count': 459, 'latest_measurement_utc': '2026-11-15T16:40:00Z'}, self.now))
        self.assertTrue(needs_recovery('opera', {'products': {'dbzh': {'frames': [{'utc': '2026-11-15T16:40:00Z'}]}}}, self.now))

    def test_satellite_checks_oldest_verified_core_image(self):
        products = {name: {'map_ok': True, 'latest_verified_time': '2026-11-15T17:15:00Z'} for name in ('geocolour','dust','ir105','firetemperature')}
        products['dust']['latest_verified_time'] = '2026-11-15T15:00:00Z'
        self.assertTrue(needs_recovery('satellite_mtg', {'products': products}, self.now))
        products['dust']['map_ok'] = False
        self.assertFalse(needs_recovery('satellite_mtg', {'products': products}, self.now))

    def test_model_cycle_not_forecast_validity(self):
        self.assertTrue(needs_recovery('icon_hazards', {'run_utc': '2026-11-15T00:00:00Z', 'periods': [{}]}, self.now))
        self.assertFalse(needs_recovery('icon_hazards', {'run_utc': '2026-11-15T12:00:00Z', 'periods': [{}]}, self.now))
        self.assertTrue(needs_recovery('mosmix', {'issue_time': '2026-11-15T00:00:00Z', 'station_count': 100}, self.now))

    def test_daily_archive_uses_observed_date(self):
        self.assertTrue(needs_recovery('snow_europe', {'daily': {'2026-11-10': 4}, 'observed_latest': '2026-11-10'}, self.now))
        self.assertFalse(needs_recovery('snow_europe', {'daily': {'2026-11-14': 4}, 'observed_latest': '2026-11-14'}, self.now))
        self.assertFalse(needs_recovery('snow_europe', {'observed_latest': '2026-11-10'}, self.now))

    def test_snow_maps_need_all_four_published_views(self):
        manifest = {'latest':'2026-11-10','maps':[{'date':'2026-11-10','cover':'a.png','anomaly':'b.png','europe_cover':'c.png','europe_anomaly':'d.png'}]}
        self.assertTrue(needs_recovery('snow_maps', manifest, self.now))
        del manifest['maps'][0]['europe_anomaly']
        self.assertFalse(needs_recovery('snow_maps', manifest, self.now))

    def test_greenland_uses_active_station_observations(self):
        manifest = {'stations':[{'id':'a','status':'Active'},{'id':'b','status':'Inactive'}], 'latest':{'a':{'temp':{'date':'2026-11-10','value':-10}},'b':{'temp':{'date':'2026-11-15','value':2}}}}
        self.assertTrue(needs_recovery('dmi_greenland', manifest, self.now))
        manifest['latest']['a']['temp']['date']='2026-11-15'
        self.assertFalse(needs_recovery('dmi_greenland', manifest, self.now))

    def test_wind_reference_continues_only_verified_incomplete_reference(self):
        ref = {'years_complete_four_temperatures': 30, 'complete_temperature_calendar_days': 366,'years_complete_four_winds':17,'complete_wind_calendar_days':0}
        self.assertTrue(needs_recovery('wind_reference', {'schema_version':1,'reference_1991_2020':ref}, self.now))
        ref.update(years_complete_four_winds=30,complete_wind_calendar_days=366)
        self.assertFalse(needs_recovery('wind_reference', {'schema_version':1,'reference_1991_2020':ref}, self.now))
        self.assertFalse(needs_recovery('wind_reference', {'reference_1991_2020':{}}, self.now))

    def test_per_source_cooldown_and_failed_run_backoff(self):
        completed = {'status':'completed','createdAt':'2026-11-15T17:00:00Z','updatedAt':'2026-11-15T17:10:00Z','conclusion':'success'}
        self.assertTrue(can_dispatch([completed], self.now, cooldown_minutes=25))
        self.assertFalse(can_dispatch([completed], self.now, cooldown_minutes=180))
        completed.update(conclusion='failure')
        self.assertFalse(can_dispatch([completed], self.now, cooldown_minutes=25))
        self.assertFalse(can_dispatch([dict(completed,status='in_progress')], self.now, cooldown_minutes=0))
