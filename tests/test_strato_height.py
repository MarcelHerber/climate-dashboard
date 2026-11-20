import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch
import numpy as np
from scripts import strato_height_data as height
from scripts.strato_height_data import sector_means, reference_means, validate_forecast, NOAA_LEVELS, REGIONS

class HeightTests(unittest.TestCase):
    def test_wrap_and_weight(self):
        lat = np.array([60., 60., 60., 60., 75., 75., 75., 75.])
        lon = np.array([0., 180., 350., 90., 0., 180., 350., 90.])
        height = np.array([10., 80., 20., 50., 30., 80., 40., 50.])
        a = sector_means(lat, lon, height)
        self.assertAlmostEqual(a['atlantic'], (15*.5 + 35*np.cos(np.deg2rad(75)))/(.5+np.cos(np.deg2rad(75))), places=5)
        self.assertAlmostEqual(a['pacific'], 80.)
    def test_reference_needs_all_thirty_years(self):
        days = {f'{year}-11-19': {r: {'10': float(year-1990)} for r in REGIONS} for year in range(1991,2021)}
        self.assertEqual(reference_means(days)['11-19']['atlantic']['10'],15.5)
        days.pop('1991-11-19')
        self.assertNotIn('11-19',reference_means(days))
    def test_forecast_rejects_missing_day_or_level(self):
        cycle = datetime(2026,11,19,tzinfo=timezone.utc)
        dates={(cycle+timedelta(days=i)).strftime('%Y-%m-%d'): {r: {str(p): 3000. for p in NOAA_LEVELS} for r in REGIONS} for i in range(16)}
        payload={'model':'gefs','cycle':'2026-11-19T00:00:00Z','levels':NOAA_LEVELS,'days':dates}
        self.assertTrue(validate_forecast(payload,'gefs',cycle+timedelta(hours=9)))
        del dates['2026-11-21']['atlantic']['10']
        self.assertFalse(validate_forecast(payload,'gefs',cycle+timedelta(hours=9)))

    def test_nomads_requests_full_gfs_analysis_file(self):
        cycle=datetime(2026,11,13,tzinfo=timezone.utc)
        query=parse_qs(urlparse(height.noaa_url(cycle,0,height.ECMWF_LEVELS,analysis=True)).query)
        self.assertEqual(query['file'],['gfs.t00z.pgrb2full.0p50.f000'])
        self.assertEqual(query['dir'],['/gfs.20261113/00/atmos'])

    def test_archive_only_selects_exact_analysis_height_records(self):
        idx='1:0:d=2026111300:TMP:10 mb:anl:\n2:100:d=2026111300:HGT:10 mb:anl:\n3:300:d=2026111300:HGT:50 mb:anl:\n4:600:d=2026111300:HGT:100 mb:6 hour fcst:\n5:900:d=2026111300:TMP:100 mb:anl:\n'
        cycle=datetime(2026,11,13,tzinfo=timezone.utc)
        self.assertEqual(height.archive_ranges(idx,cycle,[10,50,100]),{10:(100,299),50:(300,599)})
        self.assertEqual(height.archive_ranges(idx,cycle+timedelta(days=1),[10,50]),{})

    def test_gfs_bridge_falls_back_to_archive(self):
        cycle=datetime(2026,11,13,tzinfo=timezone.utc)
        expected={r:{str(p):123. for p in height.ECMWF_LEVELS} for r in REGIONS}
        with patch.object(height,'download',side_effect=OSError('NOMADS unavailable')), patch.object(height,'gfs_archive_step',return_value=expected,create=True):
            self.assertEqual(height.gefs_step(cycle,0,height.ECMWF_LEVELS,analysis=True),expected)

    def test_invalid_bridge_checkpoint_is_repaired_and_partial_success_saved(self):
        today=datetime.now(timezone.utc).date()
        dates=[(today-timedelta(days=d)).isoformat() for d in range(1,11)]
        expected={r:{str(p):123. for p in height.ECMWF_LEVELS} for r in REGIONS}
        with TemporaryDirectory() as td:
            root=Path(td)
            height.write_json(root/'bridge.json',{'days':{d:{} for d in dates}})
            def source(cycle,*args,**kwargs):
                if cycle.date().isoformat()==dates[0]: raise OSError('Missing day')
                return expected
            with patch.object(height,'gefs_step',side_effect=source):
                with self.assertRaisesRegex(ValueError,'Missing required GFS analysis bridge dates'):
                    height.build_bridge(root)
            days=height.read_json(root/'bridge.json')['days']
            self.assertNotIn(dates[0],days)
            self.assertEqual(days[dates[1]],expected)

if __name__=='__main__': unittest.main()

