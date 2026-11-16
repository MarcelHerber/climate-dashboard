import unittest
import tempfile
import json
from pathlib import Path
import numpy as np
from scripts.build_temperature_contrast import MISSING, quality_flags, decade_bounds, daily_reference


class CombinedQC(unittest.TestCase):
    def check(self, values, daily=None, decade=None, hourly=True, heights=None):
        a=np.asarray(values,dtype=np.int16); n=a.shape[1]
        dist=np.full((n,n),40.); np.fill_diagonal(dist,0.)
        h=np.zeros((n,n)) if heights is None else np.abs(np.asarray(heights)[:,None]-np.asarray(heights))
        return quality_flags(a,a.copy(),dist,h,hourly,daily=daily,decade=decade)[0]

    def test_twenty_degree_spike_below_old_threshold(self):
        a=[[48,50,34,58,37],[250,51,34,58,37],[56,51,34,58,37]]
        f=self.check(a)
        self.assertNotEqual(f[1,0],0)
        self.assertFalse(np.any(f[:,1:]))

    def test_same_station_daily_bounds_catch_subtle_violation(self):
        a=np.full((72,5),100,dtype=np.int16); a[35,0]=180
        hi=np.full((3,5),110,dtype=np.int16); lo=np.full((3,5),50,dtype=np.int16)
        f=self.check(a,daily=(hi,lo))
        self.assertNotEqual(f[35,0],0)
        self.assertFalse(np.any(f[:,1:]))

    def test_record_exceedance_without_spatial_conflict_kept(self):
        a=np.full((24,5),350,dtype=np.int16)
        hi=np.full((1,5),300,dtype=np.int16); lo=np.full((1,5),0,dtype=np.int16)
        self.assertFalse(np.any(self.check(a,decade=(hi,lo))))

    def test_decade_supports_spatial_exclusion(self):
        a=np.full((24,5),100,dtype=np.int16); a[:,0]=250
        hi=np.full((1,5),190,dtype=np.int16); lo=np.full((1,5),-50,dtype=np.int16)
        self.assertTrue(np.all(self.check(a,decade=(hi,lo))[:,0]))

    def test_real_cold_pool_without_other_evidence_kept(self):
        a=np.full((24,5),-80,dtype=np.int16); a[:,0]=-260
        self.assertFalse(np.any(self.check(a)))

    def test_genuine_short_lived_cold_pool_matches_daily_minimum(self):
        a=np.full((72,5),-80,dtype=np.int16); a[30:35,0]=-235
        hi=np.full((3,5),30,dtype=np.int16); lo=np.full((3,5),-100,dtype=np.int16); lo[1,0]=-240
        self.assertFalse(np.any(self.check(a,daily=(hi,lo))[30:35,0]))

    def test_missing_daily_bounds_dont_mean_zero(self):
        a=np.full((72,5),100,dtype=np.int16)
        hi=np.full((3,5),MISSING,dtype=np.int16); lo=hi.copy()
        self.assertFalse(np.any(self.check(a,daily=(hi,lo))))

    def test_national_reference_when_station_has_no_daily_product(self):
        a=np.full((72,5),100,dtype=np.int16); a[24:48,0]=250
        hi=np.full((3,6),MISSING,dtype=np.int16); lo=hi.copy()
        hi[:,-1]=150; lo[:,-1]=0
        self.assertNotEqual(self.check(a,daily=(hi,lo))[35,0],0)

    def test_day_bounds_allow_adjacent_climate_day(self):
        a=np.full((72,5),100,dtype=np.int16); a[35,0]=180
        hi=np.full((3,5),100,dtype=np.int16); hi[2,0]=190
        lo=np.full((3,5),0,dtype=np.int16)
        self.assertEqual(self.check(a,daily=(hi,lo))[35,0],0)

    def test_reference_alignment_uses_station_id_and_calendar_decade(self):
        stations=[{'id':'00002'},{'id':'00001'}]
        days={'20000110':0,'20000111':1}
        data={'stations':{'a':{'id':'00001'},'b':{'id':'00002'}},'station_records':{}}
        for metric,values in [('txk_high',[12,20]),('tnk_low',[-10,-20])]:
            data['station_records'][metric]={'Deutschland':{'month-01-d1':{'a':[values[0],'19900110','a',False],'b':[values[1],'19900110','b',False]},'month-01-d2':{'a':[values[1],'19900111','a',False],'b':[values[0],'19900111','b',False]}}}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'records.json'; path.write_text(json.dumps(data))
            hi,lo=decade_bounds(path,days,stations,True)
            self.assertEqual(hi.tolist(),[[200,120],[120,200]])
            self.assertEqual(lo.tolist(),[[-200,-100],[-100,-200]])
            ref=Path(tmp)/'ref.npz'; np.savez(ref,dates=['20000110','20000111'],ids=['00001','00002'],hot=[[120,200],[200,120]],cold=[[-100,-200],[-200,-100]])
            a,b=daily_reference(ref,days,stations)
            self.assertEqual(a.tolist(),[[200,120,MISSING],[120,200,MISSING]])
            self.assertEqual(b.tolist(),[[-200,-100,MISSING],[-100,-200,MISSING]])
