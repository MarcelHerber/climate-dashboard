import gzip
import io
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from update_station_records import MetadataIndex, MetadataSegment, Observation, INTERNAL_UNKNOWN
from build_rekordlabor_regional_calendar import (
    calendar_metrics, calendar_key, parse_kl_zip, parse_rr_zip,
    RegionalAccumulator, load_temperature_exclusions,
)


def archive(header, rows):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('produkt_klima_tag_test.txt', header + '\n' + '\n'.join(rows) + '\n')
    return stream.getvalue()


def segment(sid, state='Hessen', lat=50.0):
    return MetadataSegment(f'{sid}:19000101', sid, date(1900,1,1), date(2100,12,31), 100, lat, 8.0, f'Station {sid}', state)


class Records(unittest.TestCase):
    def test_overlap_preserves_valid_supplementary_fields_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=RegionalAccumulator(Path(tmp)/'obs.sqlite')
            day=date(2025,6,1); key='00001:19000101'
            a.add(Observation(day,key,'Hessen','00001',{'txk_high':30,'tmk':20},False),'kl')
            a.add(Observation(day,key,'Hessen','00001',{'txk_high':40,'tnk_low':10,'fx_kmh':80},True),'kl')
            r=a.records(2025)['06-01']
            self.assertEqual(r['txk_low']['Hessen'][0], [30,'2025-06-01',key,0])
            self.assertEqual(r['tnk_high']['Hessen'][0], [10,'2025-06-01',key,1])
            self.assertEqual(r['amplitude_high']['Hessen'][0], [20,'2025-06-01',key,1])
            self.assertEqual(r['tmk_high']['Hessen'][0], [20,'2025-06-01',key,0])
            self.assertEqual(r['fx_high']['Hessen'][0], [80,'2025-06-01',key,1])
            a.close()
    def test_metrics_same_day_and_missing(self):
        self.assertEqual(calendar_metrics({'txk_high':20,'tnk_low':5,'tmk':12,'sdk':9,'fx_kmh':80}),
                         {'txk_low':20,'tnk_high':5,'tmk_high':12,'tmk_low':12,'amplitude_high':15,'sdk_high':9,'fx_high':80})
        self.assertNotIn('amplitude_high', calendar_metrics({'txk_high':20}))
        self.assertEqual(calendar_metrics({'txk_high':-7.8,'tnk_low':-5}), {})
        self.assertEqual(calendar_metrics({'txk_high':20,'tnk_low':5,'tmk':40})['amplitude_high'],15)
        self.assertNotIn('tmk_high',calendar_metrics({'txk_high':20,'tnk_low':5,'tmk':40}))
        self.assertEqual(calendar_metrics({'rs':0}),{'rs_high':0})
        self.assertEqual(calendar_metrics({'rs':-999,'sdk':25,'fx_kmh':-2,'txk_high':100}),{})

    def test_quality_columns_and_wind_once(self):
        data=archive('STATIONS_ID;MESS_DATUM;QN_3;FX;QN_4;TXK;TNK;TMK;SDK',[
            '00001;20000229;10;20;10;11;-3;5;6',
            '00001;20000301;0;30;10;12;1;6;5',
            '00001;20000302;10;25;0;20;5;9;4',
            '00001;20000303;10;25;10;-999;1;5;-999',
        ])
        m=MetadataIndex([segment('00001')]); rows=parse_kl_zip(data,'00001',m,date(2000,1,1),date(2000,12,31),False)
        self.assertEqual(rows[0].values,{'txk_high':11.,'tnk_low':-3.,'tmk':5.,'sdk':6.,'fx_kmh':72.})
        self.assertNotIn('fx_kmh',rows[1].values)
        self.assertEqual(rows[2].values,{'fx_kmh':90.})
        self.assertNotIn('txk_high',rows[3].values)
        self.assertEqual(calendar_key(rows[0].day),'02-29')

    def test_rr_network_zero_valid_and_quality_required(self):
        data=archive('STATIONS_ID;MESS_DATUM;QN_6;RS',[
            '00001;20000229;10;0','00001;20000301;0;200','00001;20000302;10;-999','00001;20000303;10;80.1'])
        m=MetadataIndex([segment('00001')]); rows=parse_rr_zip(data,'00001',m,date(2000,1,1),date(2000,12,31),True)
        self.assertEqual([(x.day.isoformat(),x.values,x.preliminary) for x in rows], [('2000-02-29',{'rs':0.},True),('2000-03-03',{'rs':80.1},True)])

    def test_partition_top50_unique_events_and_historical_priority(self):
        with tempfile.TemporaryDirectory() as temp:
            a=RegionalAccumulator(Path(temp)/'obs.sqlite')
            day=date(2000,2,29)
            for i in range(60):
                sid=f'{i+1:05d}'; s=segment(sid)
                a.add(Observation(day,s.key,s.state,sid,{'tnk_low':i/10},False),'kl')
            a.add(Observation(day,'00001:19000101','Hessen','00001',{'tnk_low':45},True),'kl')
            a.add(Observation(day,'99999:unknown',INTERNAL_UNKNOWN,'99999',{'tnk_low':8},False),'kl')
            a.add(Observation(date(2001,2,28),'00001:19000101','Hessen','00001',{'tnk_low':20},False),'kl')
            data=a.records(2000)
            h=data['02-29']['tnk_high']['Hessen']; de=data['02-29']['tnk_high']['Deutschland']
            self.assertEqual(len(h),50); self.assertEqual(h[0],[5.9,'2000-02-29','00060:19000101',0]); self.assertEqual(h[-1][0],1.0)
            self.assertEqual(de[0],[8,'2000-02-29','99999:unknown',0]); self.assertEqual(len(de),50)
            self.assertNotIn('02-28',data); self.assertIn('02-28',a.records(2001))
            a.close()

    def test_archived_qc_exclusion_cannot_enter_amplitude(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'1924';folder.mkdir()
            payload={'version':'contrast-qc-v2','excluded':[['19240103',None,'00880','TXK',-78,5],['19240103',None,'00880','TNK',-50,5]]}
            (folder/'quality.json.gz').write_bytes(gzip.compress(json.dumps(payload).encode()))
            excluded=load_temperature_exclusions(Path(temp),1924,1924)
            self.assertEqual(excluded,{('1924-01-03','00880','TXK'),('1924-01-03','00880','TNK')})
            a=RegionalAccumulator(Path(temp)/'obs.sqlite',excluded)
            a.add(Observation(date(1924,1,3),'00880:19000101','Hessen','00880',{'txk_high':-7.8,'tnk_low':-5,'tmk':-6},False),'kl')
            r=a.records(1924)['01-03']; self.assertNotIn('amplitude_high',r);self.assertNotIn('tnk_high',r);self.assertIn('tmk_low',r);a.close()


if __name__=='__main__': unittest.main()
