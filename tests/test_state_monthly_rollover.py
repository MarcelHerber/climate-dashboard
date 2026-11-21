import unittest
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from scripts import build_state_monthly_ensemble_outlook as app
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_state_monthly_precip_outlook as rain
import build_state_monthly_sun_outlook as sun


def model_region(dates, values):
    return {'dates': dates, 'member_keys': ['m'], 'members': {'m': values}, 'support_points': 1}


def model(dates, values, key='gefs'):
    return {'label': key, 'api_model': key, 'daily_variable': 'temperature_2m_mean',
            'run': '2026-11-30T12:00:00Z', 'regions': {r: model_region(dates, values) for r in app.REGION_ORDER}}


class CalendarRolloverTests(unittest.TestCase):
    def test_next_month_leap_year_and_year_boundary(self):
        self.assertEqual(app.next_month(2026, 12), (2027, 1))
        self.assertEqual(app.next_month(2028, 1), (2028, 2))
        self.assertEqual(len(app.month_dates(2028, 2)), 29)

    def test_forecast_only_mean(self):
        days = ['2026-12-01', '2026-12-02', '2026-12-03']
        r = app.merge_running_outlook([], [], model_region(days, [2, 4, None]), days)
        self.assertEqual(r['stats']['mean'], [2, 3, None])
        self.assertEqual(r['forecast_from'], days[0])

    def test_forecast_only_sum_and_gap(self):
        days = ['2026-12-01', '2026-12-02', '2026-12-03', '2026-12-04']
        r = app.merge_running_outlook([], [], model_region(days, [2, 4, None, 8]), days, aggregation='sum')
        self.assertEqual(r['stats']['mean'], [2, 6, None, None])

    def test_forecast_only_missing_first_day(self):
        days = ['2026-12-01', '2026-12-02']
        r = app.merge_running_outlook([], [], model_region(days[1:], [4]), days)
        self.assertEqual(r['stats']['mean'], [None, None])
        self.assertIsNone(r['forecast_from'])

    def test_observation_replaces_first_forecast(self):
        days = ['2026-12-01', '2026-12-02']
        r = app.merge_running_outlook(days[:1], [6], model_region(days, [2, 4]), days)
        self.assertEqual(r['stats']['mean'], [None, 5])

    def test_temperature_calendar_rollover(self):
        dates = app.dates_between(date(2026, 1, 1), date(2026, 11, 30))
        current = {'dates': dates, 'data_through': dates[-1], 'regions': {r: [10]*len(dates) for r in app.REGION_ORDER}}
        daily_climate = {d[5:]: 3 for d in app.dates_between(date(2024, 1, 1), date(2024, 12, 31))}
        climate = {'regions': {r: daily_climate for r in app.REGION_ORDER}}
        m = model(['2026-11-30', '2026-12-01', '2026-12-02'], [100, 2, 4])
        support = {r: [] for r in app.REGION_ORDER}
        out = app.build_payload(current, climate, {'gefs': m}, 2026, 12, dates[-1], support)
        r = out['regions']['Deutschland']
        self.assertIsNone(r['observed_current'])
        self.assertIsNone(r['observed_through'])
        self.assertEqual(r['observed_running'], [None]*31)
        self.assertEqual(r['climatology_running'][:2], [3, 3])
        self.assertEqual(r['models']['gefs']['stats']['mean'][:3], [2, 3, None])
        self.assertEqual(out['periods']['season']['start_date'], '2026-12-01')
        self.assertEqual(r['periods']['year']['observed_current'], 10)

    def test_temperature_two_months_share_member_data(self):
        dates = app.dates_between(date(2026, 1, 1), date(2026, 11, 29))
        current = {'dates': dates, 'data_through': dates[-1], 'regions': {r: [10]*len(dates) for r in app.REGION_ORDER}}
        climate = {'regions': {r: {d[5:]: 3 for d in app.dates_between(date(2024, 1, 1), date(2024, 12, 31))} for r in app.REGION_ORDER}}
        models = {'gefs': model(['2026-11-30', '2026-12-01', '2026-12-02'], [20, 2, 4]),
                  'icon_eu': model(['2026-11-30'], [20], 'icon_eu')}
        support = {r: [] for r in app.REGION_ORDER}
        out = app.build_temperature_documents(current, climate, models, {}, date(2026,11,30), support, datetime(2026,11,30,19,tzinfo=timezone.utc))
        root, preview = out[0], out[0]['next_month']
        self.assertEqual(root['models_order'], ['gefs', 'icon_eu'])
        self.assertEqual(preview['models_order'], ['gefs'])
        self.assertEqual(preview['regions']['Deutschland']['models']['gefs']['stats']['mean'][:2], [2, 3])
        self.assertIsNone(preview['observation_data_through'])

    def test_hydro_forecast_only_then_observation_replacement(self):
        m = model(['2026-12-01', '2026-12-02', '2026-12-03'], [2, 4, None])
        previous = {'schema_version': 1, 'forecast': False, 'unit': 'mm', 'month': '2026-11',
                    'dates': [f'2026-11-{d:02}' for d in range(1,31)], 'data_through': '2026-11-30',
                    'regions': {r: {'daily': [1]*30} for r in app.REGION_ORDER}}
        for builder, doc in [(rain, previous), (sun, {**previous, 'unit':'h', 'product':'state_monthly_duett_sunshine_observations'})]:
            kwargs = {'support':{}} if builder is rain else {}
            out = builder.build_payload(doc, {'gefs': m}, target=(2026,12), **kwargs)
            r = out['regions']['Deutschland']
            self.assertEqual(out['month'], 12)
            self.assertIsNone(r['observed_current'])
            self.assertEqual(r['observed_running'], [None]*31)
            self.assertEqual(r['models']['gefs']['stats']['mean'][:3], [2,6,None])
            observed = {**doc, 'month':'2026-12','dates':['2026-12-01'], 'data_through':'2026-12-01',
                        'regions': {r: {'daily':[7]} for r in app.REGION_ORDER}}
            out = builder.build_payload(observed, {'gefs':m}, target=(2026,12), **kwargs)
            self.assertEqual(out['regions']['Deutschland']['models']['gefs']['stats']['mean'][:3], [None,11,None])

    def test_distinct_current_and_preview_runs_survive_outage(self):
        dates = app.dates_between(date(2026,1,1),date(2026,11,29))
        current={'dates':dates,'data_through':dates[-1],'regions':{r:[10]*len(dates) for r in app.REGION_ORDER}}
        climate={'regions':{r:{d[5:]:3 for d in app.dates_between(date(2024,1,1),date(2024,12,31))} for r in app.REGION_ORDER}}
        support={r:[] for r in app.REGION_ORDER}
        fresh=model(['2026-11-30'],[20]); old={**model(['2026-11-30','2026-12-01'],[20,2]),'run':'2026-11-29T18:00:00Z'}
        now=datetime(2026,11,30,19,tzinfo=timezone.utc); today=date(2026,11,30)
        out, cache=app.build_temperature_documents(current,climate,{'gefs':fresh},{'gefs':old},today,support,now)
        self.assertEqual(out['next_month']['models_order'],['gefs'])
        out,_=app.build_temperature_documents(current,climate,{},cache,today,support,now)
        self.assertEqual(out['next_month']['models_order'],['gefs'])
        obs={'schema_version':1,'forecast':False,'unit':'mm','month':'2026-11','dates':dates[-29:],'data_through':dates[-1],'regions':{r:{'daily':[1]*29} for r in app.REGION_ORDER}}
        out,cache=rain.build_precip_documents(obs,{'gefs':fresh},{'gefs':old},None,{},now,today)
        self.assertEqual(out['next_month']['models_order'],['gefs'])
        out,_=rain.build_precip_documents(obs,{},cache,None,{},now,today)
        self.assertEqual(out['next_month']['models_order'],['gefs'])

    def test_rain_preview_after_complete_previous_month(self):
        doc = {'schema_version': 1, 'forecast': False, 'unit': 'mm', 'month': '2026-11',
               'dates': [f'2026-11-{d:02}' for d in range(1,31)], 'data_through': '2026-11-30',
               'regions': {r: {'daily': [1]*30} for r in app.REGION_ORDER}}
        m = model(['2026-12-01','2026-12-02'], [2,4])
        now = datetime(2026,11,30,19,tzinfo=timezone.utc)
        out, cache = rain.build_precip_documents(doc, {'gefs':m}, {}, None, {}, now, date(2026,11,30))
        self.assertTrue(out['observation_complete'])
        self.assertEqual(out['next_month']['models_order'], ['gefs'])
        self.assertEqual(out['next_month']['regions']['Deutschland']['models']['gefs']['stats']['mean'][:2], [2,6])
        self.assertIn('gefs',cache)
        expired, _ = rain.build_precip_documents(doc, {}, {'gefs':m}, None, {}, datetime(2026,12,3,tzinfo=timezone.utc), date(2026,12,3))
        self.assertEqual(expired['models_order'], [])

    def test_sun_preview_omits_model_without_first_day(self):
        doc = {'schema_version':1, 'forecast':False, 'unit':'h', 'product':'state_monthly_duett_sunshine_observations',
               'month':'2026-11','dates':['2026-11-01'], 'data_through':'2026-11-01',
               'regions':{r:{'daily':[1]} for r in app.REGION_ORDER}}
        models = {'gefs':model(['2026-12-01','2026-12-02'], [2,4]), 'icon_eu':model(['2026-12-02'], [4], 'icon_eu')}
        out = sun.build_sun_documents(doc, models, date(2026,11,30))
        self.assertEqual(out['next_month']['models_order'], ['gefs'])
        self.assertEqual(out['next_month']['regions']['Deutschland']['models']['gefs']['stats']['mean'][:2], [2,6])

    def test_publication_accepts_empty_observations_but_rejects_fabricated_zero(self):
        doc = {'schema_version':1, 'forecast':False, 'unit':'h', 'product':'state_monthly_duett_sunshine_observations',
               'month':'2026-11','dates':[], 'data_through':None,
               'regions':{r:{'daily':[]} for r in app.REGION_ORDER}}
        m = model(['2026-12-01','2026-12-02'], [2,4])
        payload = sun.build_sun_documents(doc, {'gefs':m}, date(2026,12,1))
        app.validate_monthly_document(payload)
        payload['regions']['Deutschland']['observed_running'][0] = 0
        with self.assertRaises(ValueError):
            app.validate_monthly_document(payload)

    def test_rain_cannot_replace_first_real_observation_with_no_data(self):
        doc = {'schema_version':1, 'forecast':False, 'unit':'mm','month':'2026-12','dates':['2026-12-01'], 'data_through':'2026-12-01',
               'regions':{r:{'daily':[2]} for r in app.REGION_ORDER}}
        previous = rain.build_payload(doc, {}, {})
        missing = {**doc,'dates':[], 'data_through':None,'regions':{r:{'daily':[]} for r in app.REGION_ORDER}}
        with self.assertRaises(ValueError):
            rain.build_resilient_payload(missing, {}, {}, previous, {}, datetime(2026,12,2,tzinfo=timezone.utc))


if __name__ == '__main__':
    unittest.main()
