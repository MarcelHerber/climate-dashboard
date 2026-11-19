import unittest
from pathlib import Path
import gzip, json
from build_regional_year import reduce_day

FIXTURES = Path(__file__).resolve().parent.parent / "regional-calendar-ui" / "fixtures"
class AnnualRecordTests(unittest.TestCase):
    def test_minimum_ties_year_and_current_separate(self):
        m={"metrics":{"txk_low":{"direction":"asc"}},"areas":["Deutschland"],"stations":[{"id":"2","key":"b","name":"B"},{"id":"1","key":"a","name":"A"}]}
        rows=[[2025,{"txk_low":{"Deutschland":[[50,0,0],[50,1,0]]}}],[2024,{"txk_low":{"Deutschland":[[50,0,0]]}}],[2026,{"txk_low":{"Deutschland":[[-20,1,1]]}}]]
        got=reduce_day([(m,rows)],"11-14",2026)
        self.assertEqual(got["txk_low"]["Deutschland"],[[50,2024,"2","B",0],[-20,2026,"1","A",1]])
    def test_leap_day_and_missing(self):
        m={"metrics":{"tnk_high":{"direction":"desc"}},"areas":["Deutschland","Hessen"],"stations":[{"id":"1","key":"a","name":"A"}]}
        rows=[[2025,{"tnk_high":{"Deutschland":[[999,0,0]]}}],[2024,{"tnk_high":{"Deutschland":[[-10,0,0]]}}]]
        got=reduce_day([(m,rows)],"02-29",2026)
        self.assertEqual(got["tnk_high"]["Deutschland"],[[-10,2024,"1","A",0],None])
        self.assertEqual(got["tnk_high"]["Hessen"],[None,None])
    @unittest.skipUnless(FIXTURES.exists(),"local sample unavailable")
    def test_real_all_partitions_november(self):
        parts=[]
        for folder in sorted(FIXTURES.iterdir()):
            parts.append((json.loads((folder/"manifest.json").read_text()),json.loads(gzip.decompress((folder/"11-14.json.gz").read_bytes()))))
        got=reduce_day(parts,"11-14",2026)
        self.assertEqual(got["rs_high"]["Deutschland"][0][:4],[832,1994,"02357","Hückeswagen"])
        self.assertEqual(got["txk_low"]["Deutschland"][0][0],-168)
        self.assertEqual(got["tmk_high"]["Deutschland"][0][0],166)

if __name__ == "__main__": unittest.main()
