import sys
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
import io
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import build_annual_extremes_extra as x

def zip_rows(text):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w") as z:
        z.writestr("produkt_test.txt",text)
    return buf.getvalue()

class Metadata:
    def segment_for(self,sid,day):
        return SimpleNamespace(key=sid+":test",state="Hessen",height=400)

class AnnualExtraTests(unittest.TestCase):
    def test_threshold_boundaries(self):
        self.assertFalse(x.passes(0,"<",0))
        self.assertTrue(x.passes(-5,"<=",-5))
        self.assertTrue(x.passes(-10,"<=",-10))
        self.assertTrue(x.passes(75,">=",75))
        self.assertFalse(x.passes(74.9,">=",75))

    def test_leap_coverage(self):
        today=date(2025,1,10)
        self.assertEqual(x.expected_days(2024,today),366)
        self.assertFalse(x.count_eligible(329,2024,today))
        self.assertTrue(x.count_eligible(330,2024,today))
        self.assertTrue(x.count_eligible(9,2025,today))
        self.assertFalse(x.count_eligible(8,2025,today))

    def test_series_gap_and_rolling(self):
        day=date(2024,1,1)
        a=[(day+timedelta(days=i),10,"s",False) for i in (0,1,3,4,5)]
        self.assertEqual(x.longest(a,">=",10),(3,day+timedelta(days=3),day+timedelta(days=5)))
        self.assertEqual(x.rolling(a,3)[0],30)
        self.assertIsNone(x.rolling(a,4))

    def test_original_history_wins_and_missing_is_not_zero(self):
        a=zip_rows("MESS_DATUM;TNK;TXK;TMK;SHK_TAG;FX\n20240101;-10;1;-5;-999;25\n")
        b=zip_rows("MESS_DATUM;TNK;TXK;TMK;SHK_TAG;FX\n20240101;-9;1;-5;0;25\n20240102;-999;2;1;-999;-999\n")
        with patch.object(x.dwd,"download_station_zip",side_effect=[a,b]):
            d=x.read_station([("hist","a",False),("recent","b",True)],"00001","KL",date(2024,1,3))
        self.assertEqual(d[date(2024,1,1)]["TNK"],(-10,False))
        self.assertEqual(d[date(2024,1,1)]["SHK"],(0,True))
        self.assertEqual(d[date(2024,1,1)]["FX"],(90,False))
        self.assertNotIn("TNK",d[date(2024,1,2)])
        self.assertNotIn("SHK",d[date(2024,1,2)])

    def test_tropical_nights_require_all_hours_across_midnight(self):
        rows=["MESS_DATUM;TT_TU"]
        rows += [f"20240701{h:02d};21" for h in range(18,24)]
        rows += [f"20240702{h:02d};20" for h in range(7)]
        rows += [f"20240702{h:02d};22" for h in range(18,24)]
        rows += [f"20240703{h:02d};22" for h in range(6)]
        with patch.object(x.dwd,"download_station_zip",return_value=zip_rows("\n".join(rows))):
            d=x.read_station([("hist","a",False)],"00001","TU",date(2024,7,4))
        self.assertEqual(d[date(2024,7,2)]["night"],(20,False))
        self.assertNotIn(date(2024,7,3),d)

    def test_records_station_not_sum_and_height_split(self):
        start=date(2024,1,1)
        days={start+timedelta(days=i):{"TNK":(-10,False),"TXK":(-1,False),"TMK":(-5,False),"SHK":(10,False),"FX":(90,False)} for i in range(366)}
        result={(a,y,k):v for a,y,k,v in x.station_records(days,"00001","KL",Metadata(),date(2025,1,1))}
        for area in ("Deutschland","Hessen"):
            self.assertEqual(result[area,2024,"severe_frost_days_max"][0],366)
            self.assertEqual(result[area,2024,"ice_spell"][0],366)
            self.assertEqual(result[area,2024,"snow10_days_ge_400"][0],366)
            self.assertNotIn((area,2024,"snow10_days_lt_400"),result)
            self.assertEqual(result[area,2024,"dtrx"][0],9)
            self.assertEqual(result[area,2024,"wind89_days_max"][0],366)
        self.assertNotIn(("Bayern",2024,"frost_days_max"),result)

    def test_no_counts_from_short_record(self):
        d={date(2024,1,1):{"TNK":(-15,False),"TXK":(-3,False)}}
        r={k:v for _,_,k,v in x.station_records(d,"00001","KL",Metadata(),date(2025,1,1))}
        self.assertNotIn("frost_days_max",r)
        self.assertEqual(r["tnx"][0],-15)

if __name__=="__main__":
    unittest.main()
