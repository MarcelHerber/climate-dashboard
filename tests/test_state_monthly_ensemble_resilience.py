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

    def test_data_status_uses_model_run_age_not_generation_time(self):
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        rows = []
        status.add_state_monthly_model_status(rows, {
            'generated_at': now.isoformat(),
            'regions': {'Deutschland': {'models': {'gefs': {'run': (now-timedelta(hours=40)).isoformat()}, 'ifs': {'run': (now-timedelta(hours=2)).isoformat()}}}},
        })
        states = {r['id']:r['status'] for r in rows}
        self.assertEqual(states, {'state_monthly_gefs':'delayed','state_monthly_ifs':'current','state_monthly_aifs':'unknown','state_monthly_icon_eu':'unknown'})

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
