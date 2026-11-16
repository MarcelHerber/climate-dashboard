import unittest
import io
import gzip
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import numpy as np
from scripts.build_temperature_contrast import quality_flags, read_station, build, MISSING


class QualityTests(unittest.TestCase):
    def check(self, a, hourly=True, cold=None, heights=None):
        a=np.array(a,dtype=np.int16)
        b=a.copy() if cold is None else np.array(cold,dtype=np.int16)
        n=a.shape[1]
        d=np.full((n,n),30.)
        np.fill_diagonal(d,0)
        h=np.zeros((n,n)) if heights is None else np.abs(np.array(heights)[:,None]-np.array(heights))
        return quality_flags(a,b,d,h,hourly)

    def test_summer_sensor_failure_and_october_heat_spike(self):
        a=[[150,140,160,155,145],[-398,150,160,155,145],[150,140,160,155,145],[420,100,110,105,120],[110,110,120,105,100]]
        flags,_=self.check(a)
        self.assertNotEqual(flags[1,0],0)
        self.assertNotEqual(flags[3,0],0)
        self.assertEqual(np.count_nonzero(flags[:,1:]),0)

    def test_persistent_fault_and_genuine_cold_pool(self):
        a=[[150,140,160,155,145]]*2+[[-201,140,160,155,145]]*12+[[150,140,160,155,145]]*2
        flags,_=self.check(a)
        self.assertTrue(np.all(flags[2:14,0]))
        cold=[[-260,-80,-100,-90,-90]]*12
        flags,_=self.check(cold)
        self.assertFalse(np.any(flags))

    def test_mountain_and_regional_front_are_preserved(self):
        a=[[200,190,210,205,-100],[-50,-60,-70,-50,-250]]
        f,_=self.check(a,heights=[100,120,150,200,3000])
        self.assertFalse(np.any(f))

    def test_daily_impossible_order_is_flagged_but_missing_is_not(self):
        a=[[50,150,150,150,150],[MISSING,150,150,150,150]]
        b=[[100,50,50,50,50],[10,50,50,50,50]]
        h,c=self.check(a,False,b)
        self.assertNotEqual(h[0,0],0)
        self.assertNotEqual(c[0,0],0)
        self.assertEqual(c[1,0],0)

    def test_cold_pool_with_diurnal_change_and_invalid_adjacent_value_is_preserved(self):
        a=[[0,10,20,10,20],[-200,0,0,10,0],[-999,0,0,10,0],[-200,0,0,10,0]]
        flags,_=self.check(a)
        self.assertEqual(flags[1,0],0)
        self.assertEqual(flags[3,0],0)
        self.assertNotEqual(flags[2,0],0)

    def test_raw_zip_retains_implausible_values_and_ignores_missing(self):
        data=io.BytesIO()
        with ZipFile(data,'w') as z:
            z.writestr('Metadaten_Parameter_TU.txt','Header\n00001;2000-01-01;2000-01-02;;TT_TU;;;;Stundenwerte in UTC\n')
            z.writestr('produkt_tu_stunde.txt','STATIONS_ID;MESS_DATUM;QN_9;TT_TU\n1;2000010100;10;99.9\n1;2000010101;10;-999\n1;2000010102;10;nan\n')
        with patch('scripts.build_temperature_contrast.fetch',return_value=data.getvalue()):
            a,b=read_station({'id':'00001'},['test'],{'20000101':0},True)
        self.assertEqual(a[:3].tolist(),[999,MISSING,MISSING])

    def test_audit_preserves_excluded_reading_and_recalculates_winner(self):
        inv=[(dict(id=str(i),name=str(i),lat=50.,lon=8.+i*.1,height=100.,state='Hessen'),[]) for i in range(5)]
        def read(station,urls,days,hourly):
            a=np.full(len(days)*24,MISSING,np.int16)
            i=int(station['id']); a[:3]=[150,[-398,140,160,155,145][i],150]
            return a,a.copy()
        with tempfile.TemporaryDirectory() as tmp,patch('scripts.build_temperature_contrast.inventory',return_value=inv),patch('scripts.build_temperature_contrast.read_station',side_effect=read):
            build(Path(tmp),'hourly',2000,2000,limit=5)
            path=Path(tmp)/'hourly'/'2000'
            audit=json.loads(gzip.decompress((path/'quality.json.gz').read_bytes()))
            self.assertEqual(audit['excluded'],[['20000101',1,'0','TT_TU',-398,2]])
            pack=json.loads(gzip.decompress((path/'DE.json.gz').read_bytes()))
            self.assertEqual(pack['results']['9999-9999-9999'][0][1],20)
            matrix=np.frombuffer(gzip.decompress((path/'hour-01.bin.gz').read_bytes()),dtype='<i2').reshape(-1,5)
            self.assertEqual(matrix[1,0],MISSING)
