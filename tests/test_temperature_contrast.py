import unittest
import tempfile
import json
import io
from zipfile import ZipFile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scripts.build_temperature_contrast import build, read_station, scan, MISSING


class ContrastTests(unittest.TestCase):
    def test_historical_time_reference_metadata_is_applied_per_day(self):
        data=io.BytesIO()
        with ZipFile(data,'w') as z:
            z.writestr('Metadaten_Parameter_TU.txt','Header\n00001;1961-01-01;1961-01-01;;TT_TU;;;;Stundenwerte in MEZ\n00001;1961-01-02;1961-01-02;;TT_TU;;;;Stundenwerte in UTC\n00001;1961-01-03;;;TT_TU;;;;Stundenwerte in MEZ\n')
            z.writestr('produkt_tu_stunde.txt','STATIONS_ID;MESS_DATUM;QN_9;TT_TU\n1;1961010100;10;1.0\n1;1961010200;10;2.0\n1;1961010300;10;3.0\n')
        with patch('scripts.build_temperature_contrast.fetch',return_value=data.getvalue()):
            a,b=read_station({'id':'00001'},['test'],{'19610101':0,'19610102':1,'19610103':2},True)
        self.assertEqual(list(a[::24]),[MISSING,20,MISSING])
        np.testing.assert_array_equal(a,b)
    def test_early_hourly_year_without_simultaneous_pair_is_not_published(self):
        inv=[(dict(id=str(i),name=str(i),lat=50.,lon=8.+i,height=100.,state='Hessen'),[]) for i in range(2)]
        def read(station, urls, days, hourly):
            a=np.full(len(days)*24,MISSING,np.int16)
            a[int(station['id'])]=100
            return a,a.copy()
        with tempfile.TemporaryDirectory() as tmp, patch('scripts.build_temperature_contrast.inventory',return_value=inv), patch('scripts.build_temperature_contrast.read_station',side_effect=read):
            build(Path(tmp),'hourly',1961,1961)
            p=Path(tmp)/'hourly'/'1961'
            self.assertFalse((p/'ready.json').exists())
            self.assertEqual(json.loads((p/'unavailable.json').read_text())['year'],1961)

    def test_early_single_station_is_unavailable_not_a_batch_failure(self):
        inv=[(dict(id='1',name='1',lat=50.,lon=8.,height=100.,state='Hessen'),[])]
        def read(station, urls, days, hourly):
            a=np.full(len(days)*24,100,np.int16)
            return a,a.copy()
        with tempfile.TemporaryDirectory() as tmp, patch('scripts.build_temperature_contrast.inventory',return_value=inv), patch('scripts.build_temperature_contrast.read_station',side_effect=read):
            build(Path(tmp),'hourly',1961,1961)
            self.assertTrue((Path(tmp)/'hourly'/'1961'/'unavailable.json').exists())

    def test_early_hourly_year_with_sparse_valid_pair_is_published(self):
        inv=[(dict(id=str(i),name=str(i),lat=50.,lon=8.+i,height=100.,state='Hessen'),[]) for i in range(2)]
        def read(station, urls, days, hourly):
            a=np.full(len(days)*24,MISSING,np.int16)
            a[1]=100+int(station['id'])*30
            return a,a.copy()
        with tempfile.TemporaryDirectory() as tmp, patch('scripts.build_temperature_contrast.inventory',return_value=inv), patch('scripts.build_temperature_contrast.read_station',side_effect=read):
            build(Path(tmp),'hourly',1986,1986)
            p=Path(tmp)/'hourly'/'1986'
            self.assertEqual(json.loads((p/'ready.json').read_text())['days'],1)
            self.assertFalse((p/'unavailable.json').exists())

    def test_exact_constraints_and_simultaneity(self):
        hot = np.array([[200, 0, 130], [100, -100, 120]], dtype=np.int16)
        cold = hot.copy()
        dist = np.array([[0, 300, 20], [300, 0, 40], [20, 40, 0]], dtype=float)
        height = np.array([[0, 0, 500], [0, 0, 500], [500, 500, 0]], dtype=float)
        result = scan(hot, cold, dist, height, np.array([25., 9999.]), np.array([200., 9999.]), 2)
        self.assertEqual(result[0, 0, 0, 0], MISSING)
        self.assertEqual(result[0, 0, 1, 0], 70)
        self.assertEqual(result[0, 1, 1, 0], 220)
        self.assertEqual(result[0, 1, 1, 3], 1)

    def test_daily_distinct_stations_and_missing(self):
        hot = np.array([[300, 140, MISSING]], dtype=np.int16)
        cold = np.array([[-200, 0, MISSING]], dtype=np.int16)
        dist = np.zeros((3, 3))
        result = scan(hot, cold, dist, dist, np.array([100.]), np.array([100.]), 1)
        self.assertEqual(list(result[0, 0, 0, :3]), [340, 1, 0])

    def test_random_against_brute_force(self):
        rng = np.random.default_rng(17)
        hot = rng.integers(-200, 400, (12, 7), dtype=np.int16)
        cold = rng.integers(-300, 150, (12, 7), dtype=np.int16)
        hot[2, 1] = cold[4, 2] = MISSING
        d = rng.integers(0, 200, (7, 7)).astype(float)
        h = rng.integers(0, 500, (7, 7)).astype(float)
        radii, heights = np.array([25., 100., 9999.]), np.array([200., 9999.])
        result = scan(hot, cold, d, h, radii, heights, 3)
        for day in range(4):
            for r, radius in enumerate(radii):
                for k, height in enumerate(heights):
                    candidates = [int(hot[t,i])-int(cold[t,j]) for t in range(day*3,day*3+3) for i in range(7) for j in range(7) if i!=j and d[i,j]<=radius and h[i,j]<=height and hot[t,i]!=MISSING and cold[t,j]!=MISSING]
                    self.assertEqual(result[day,r,k,0], max(candidates,default=MISSING))

    def test_negative_valid_daily_pair(self):
        hot=np.array([[0,MISSING]],dtype=np.int16)
        cold=np.array([[MISSING,20]],dtype=np.int16)
        d=np.zeros((2,2))
        self.assertEqual(scan(hot,cold,d,d,np.array([25.]),np.array([200.]),1)[0,0,0,0],-20)

