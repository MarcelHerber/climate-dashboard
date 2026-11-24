import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from scripts import build_state_monthly_ensemble_outlook as app
from scripts import build_data_status as status


class Clock:
    now = 0.0

    def sleep(self, delay):
        self.now += delay


class Reply:
    def __init__(self, status, reason=''):
        self.status_code = status
        self.text = reason
        self.headers = {}

    def raise_for_status(self):
        pass

    def json(self):
        return {'ok': True}


class EnsembleResilienceTest(unittest.TestCase):
    def setUp(self):
        for name, value in [('_ENSEMBLE_STOP_REASON', None), ('_HOURLY_PAUSE_USED', False), ('_SUNSHINE_NEXT_REQUEST', 0)]:
            patcher = patch.object(app, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_temperature_retry_waits_a_full_minute(self):
        clock = Clock()
        calls = []

        def request(*args, **kwargs):
            calls.append(clock.now)
            return Reply(429, 'Minutely API request limit exceeded') if len(calls) == 1 else Reply(200)

        with patch.object(app, '_SUNSHINE_NEXT_REQUEST', 0), patch.object(app.time, 'monotonic', lambda: clock.now), patch.object(app.time, 'sleep', clock.sleep), patch.object(app.requests, 'get', request):
            self.assertEqual(app.fetch_json(app.ENSEMBLE_API, params={'daily': 'temperature_2m_mean'}), {'ok': True})
        self.assertGreaterEqual(calls[1] - calls[0], 65)

    def test_daily_limit_is_not_retried(self):
        with patch.object(app.requests, 'get', return_value=Reply(429, 'Daily API request limit exceeded')) as get, patch.object(app.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Daily API'):
                app.fetch_json(app.ENSEMBLE_API, params={'daily': 'temperature_2m_mean'})
        self.assertEqual(get.call_count, 1)

    def test_hourly_wait_uses_next_hour(self):
        self.assertEqual(app.rate_limit_delay('Hourly API request limit exceeded', datetime(2026, 11, 21, 13, 35, tzinfo=timezone.utc)), 1505)

    def test_month_end_horizon(self):
        self.assertEqual(app.month_forecast_days(date(2026,11,21), 2026, 11), 10)
        self.assertEqual(app.month_forecast_days(date(2026,11,30), 2026, 11), 1)

    def test_partial_publication_and_health_check_are_separate(self):
        models = {'icon_eu': {'run': '2026-11-21T12:00:00Z'}}
        app.validate_available_models(models)
        unhealthy = app.unhealthy_models(models, datetime(2026,11,21,20,tzinfo=timezone.utc))
        self.assertEqual(set(unhealthy), {'gefs', 'ifs', 'aifs'})
        self.assertIn('icon_eu', app.unhealthy_models(models, datetime(2026,11,23,1,tzinfo=timezone.utc)))
        with self.assertRaises(ValueError):
            app.validate_available_models({})

    def test_old_or_future_metadata_is_never_claimed_as_a_model_run(self):
        now = datetime(2026, 11, 24, 7, tzinfo=timezone.utc)
        for stamp in ("2026-10-06T00:00:00Z", "2026-11-24T12:00:00Z"):
            unix = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            with patch.object(app, "fetch_json", return_value={"last_run_initialisation_time": unix}):
                self.assertIsNone(app.model_run_time("icon_eu", now=now))
        valid = datetime(2026, 11, 24, 0, tzinfo=timezone.utc)
        with patch.object(app, "fetch_json", return_value={"last_run_initialisation_time": valid.timestamp()}):
            self.assertEqual(app.model_run_time("icon_eu", now=now), "2026-11-24T00:00:00Z")

    def test_fresh_members_survive_unverified_metadata_but_cache_does_not(self):
        now = datetime(2026, 11, 24, 7, tzinfo=timezone.utc)
        region = {"dates": ["2026-11-23", "2026-11-24"],
                  "member_keys": ["temperature_2m_mean"],
                  "members": {"temperature_2m_mean": [2.0, 3.0]}}
        fresh = {"run": None, "daily_variable": "temperature_2m_mean",
                 "regions": {r: region for r in app.REGION_ORDER}}
        cached = {**fresh, "run": "2026-11-23T12:00:00Z"}
        selected, retained = app.select_temperature_models(
            {"icon_eu": fresh}, {"icon_eu": cached}, "2026-11-22", now)
        self.assertIsNone(selected["icon_eu"]["run"])
        self.assertEqual(retained, [])
        self.assertEqual(app.select_temperature_models(
            {}, {"icon_eu": fresh}, "2026-11-22", now), ({}, []))

    def test_data_status_uses_model_run_age_not_generation_time(self):
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        rows = []
        status.add_state_monthly_model_status(rows, {
            'generated_at': now.isoformat(),
            'regions': {'Deutschland': {'models': {'gefs': {'run': (now-timedelta(hours=40)).isoformat()}, 'ifs': {'run': (now-timedelta(hours=2)).isoformat()}}}},
        })
        states = {r['id']:r['status'] for r in rows}
        self.assertEqual(states, {'state_monthly_gefs':'delayed','state_monthly_ifs':'current','state_monthly_aifs':'delayed','state_monthly_icon_eu':'delayed'})

    def test_recent_unverified_icon_eu_is_yellow_not_red(self):
        from datetime import timedelta
        now = datetime(2026, 11, 24, 8, tzinfo=timezone.utc)
        models = {key: {'run': (now - timedelta(hours=6)).isoformat(),
                        'member_count': 31} for key in app.MODEL_CONFIG}
        models['icon_eu'] = {'run': None, 'member_count': 40,
                             'retrieved_at': (now - timedelta(minutes=15)).isoformat()}
        errors, warnings = app.monthly_model_health(models, now)
        self.assertEqual(errors, {})
        self.assertEqual(set(warnings), {'icon_eu'})
        self.assertNotIn('icon_eu', app.unhealthy_models(models, now))

    def test_missing_or_provably_stale_models_remain_red(self):
        from datetime import timedelta
        now = datetime(2026, 11, 24, 8, tzinfo=timezone.utc)
        examples = {
            'missing': {},
            'old_run': {'run': (now-timedelta(hours=40)).isoformat()},
            'old_retrieval': {'run': None, 'retrieved_at': (now-timedelta(hours=30)).isoformat()},
            'no_member': {'run': (now-timedelta(hours=1)).isoformat(), 'member_count': 0},
            'unverified_without_retrieval': {'run': None},
        }
        for case, model in examples.items():
            with self.subTest(case=case):
                errors, warnings = app.monthly_model_health(
                    {**{k: {'run': (now-timedelta(hours=2)).isoformat()}
                        for k in app.MODEL_CONFIG if k != 'icon_eu'},
                     'icon_eu': model}, now)
                self.assertIn('icon_eu', errors)
                self.assertNotIn('icon_eu', warnings)

    def test_data_status_recent_unverified_is_yellow(self):
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        rows = []
        status.add_state_monthly_model_status(rows, {
            'generated_at': now.isoformat(),
            'regions': {'Deutschland': {'models': {
                'icon_eu': {'run': None, 'retrieved_at': (now-timedelta(minutes=10)).isoformat(),
                            'member_count': 40}}}},
        })
        states = {r['id']: r['status'] for r in rows}
        self.assertEqual(states['state_monthly_icon_eu'], 'incomplete')
        self.assertTrue(next(r for r in rows if r['id']=='state_monthly_icon_eu')['incomplete'])
        self.assertEqual(states['state_monthly_gefs'], 'delayed')

    def test_cached_model_retained_only_when_it_covers_new_observation_anchor(self):
        now = datetime(2026,11,21,20,tzinfo=timezone.utc)
        daily = {'dates':['2026-11-20','2026-11-21','2026-11-22'], 'member_keys':['temperature_2m_mean'], 'members':{'temperature_2m_mean':[1,2,3]}}
        model = {'run':'2026-11-20T12:00:00Z','daily_variable':'temperature_2m_mean','regions':{r:daily for r in app.REGION_ORDER}}
        selected, retained = app.select_temperature_models({}, {'gefs':model}, '2026-11-21', now)
        self.assertEqual(list(selected), ['gefs'])
        self.assertEqual(retained, ['gefs'])
        self.assertEqual(selected['gefs']['run'], model['run'])
        self.assertEqual(app.select_temperature_models({}, {'gefs':model}, '2026-11-22', now), ({}, []))


if __name__ == '__main__':
    unittest.main()
