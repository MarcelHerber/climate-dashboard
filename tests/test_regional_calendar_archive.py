import gzip
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from update_station_records import Observation, INTERNAL_UNKNOWN
from build_rekordlabor_regional_calendar import RegionalAccumulator
from build_regional_calendar_archive import archive_files, write_archive, checked_exclusions, namespace_observations
from verify_regional_calendar_archive import verify_archive, verify_daily_coverage


class ArchiveTests(unittest.TestCase):
    def test_foreign_or_unverified_country_is_not_ranked_as_germany(self):
        rows=[Observation(date(2000,1,1),'06288:19000101',INTERNAL_UNKNOWN,'06288',{'rs':90},False),
              Observation(date(2000,1,1),'00001:19000101','Hessen','00001',{'rs':10},False)]
        self.assertEqual([o.station_id for o in namespace_observations(rows,'rr')], ['00001'])
    def test_missing_day_or_network_fails_full_coverage(self):
        with self.assertRaisesRegex(ValueError, '1901-01-02'):
            verify_daily_coverage({'1901-01-01':{'tnk_high','rs_high'},'1901-01-03':{'tnk_high','rs_high'}}, 1901, '1901-01-03')
        with self.assertRaisesRegex(ValueError, 'RR'):
            verify_daily_coverage({'1901-01-01':{'tnk_high'}}, 1901, '1901-01-01')
        verify_daily_coverage({'1901-01-01':{'tnk_high','rs_high'}}, 1901, '1901-01-01')
    def test_range_files(self):
        files = ['tageswerte_KL_00001_19000101_19201231_hist.zip',
                 'tageswerte_KL_00002_19210101_19501231_hist.zip',
                 'tageswerte_KL_00003_18200101_18301231_hist.zip']
        self.assertEqual(archive_files(files, 1920, 1921), files[:2])

    def test_audits_must_be_present_for_covered_years(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, '1901'):
                checked_exclusions(root, 1899, 1901)
            folder = root / '1901'; folder.mkdir()
            (folder / 'quality.json.gz').write_bytes(gzip.compress(json.dumps({'version':'contrast-qc-v2','excluded':[]}).encode()))
            self.assertEqual(checked_exclusions(root, 1899, 1901), set())

    def test_archive_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = RegionalAccumulator(root / 'obs.sqlite')
            key = '00001:19000101'
            a.add_many(namespace_observations([Observation(date(2000,2,29), key, 'Hessen', '00001', {'tnk_low': 12.1}, False)], 'kl'), 'kl')
            a.add_many(namespace_observations([Observation(date(2000,2,29), key, 'Hessen', '00001', {'rs': 90.5}, True)], 'rr'), 'rr')
            a.add_many(namespace_observations([Observation(date(2004,2,29), key, 'Hessen', '00001', {'tnk_low': 14.2}, True)], 'kl'), 'kl')
            metadata = {'kl:'+key:{'id':'00001','name':'KL'},'rr:'+key:{'id':'00001','name':'RR'}}
            manifest = write_archive(a,root/'out',2000,2004,metadata)
            day = json.loads(gzip.decompress((root/'out'/'02-29.json.gz').read_bytes()))
            self.assertEqual(manifest['years'], [2000,2004]); self.assertEqual(manifest['days'], ['02-29'])
            self.assertEqual([row[0] for row in day], [2000,2004])
            dec = lambda r: (r[0]/10, manifest['stations'][r[1]]['name'], r[2])
            self.assertEqual(dec(day[0][1]['tnk_high']['Hessen'][0]), (12.1,'KL',0))
            self.assertEqual(dec(day[0][1]['rs_high']['Hessen'][0]), (90.5,'RR',1))
            self.assertEqual(dec(day[1][1]['tnk_high']['Deutschland'][0]), (14.2,'KL',1))
            manifest['pilot'] = True
            (root/'out'/'manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(verify_archive(root/'out')['candidate_count'], 6)
            with self.assertRaisesRegex(ValueError, 'Pilot'):
                verify_archive(root/'out', full=True)
            (root/'out'/'02-29.json.gz').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'Checksum'):
                verify_archive(root/'out')
            a.close()


if __name__ == '__main__': unittest.main()
