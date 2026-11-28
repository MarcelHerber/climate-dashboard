import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from annual_quality_rules import accepted_value,clean_temperature_fields,valid_count,quality_level
from audit_annual_extremes_quality import audit,identity
from annual_snow_corrections import corrected_snow

class QualityTests(unittest.TestCase):
    def test_quarantine_only_target(self):
        self.assertIsNone(accepted_value("02552","RS",date(1904,1,1),0))
        self.assertEqual(accepted_value("02552","RS",date(1902,1,1),0),0)
        self.assertEqual(accepted_value("02553","RS",date(1904,1,1),0),0)
        self.assertIsNone(accepted_value("01006","TMK",date(1898,8,10),-14))
        self.assertEqual(accepted_value("01006","TMK",date(1898,8,10),14),14)
    def test_snow_manual_and_missing(self):
        self.assertEqual(accepted_value("01975","SHK",date(2026,1,10),corrected_snow("01975",date(2026,1,10),53)),25)
        self.assertIsNone(accepted_value("01975","SHK",date(2026,1,13),43))
        self.assertEqual(accepted_value("05640","SHK",date(2004,11,17),134),134)
    def test_temperature_and_quality(self):
        self.assertEqual(clean_temperature_fields({"TNK":5,"TXK":1,"TMK":2,"SHK":0}),{"SHK":0})
        self.assertEqual(clean_temperature_fields({"TNK":0,"TXK":10,"TMK":-3}),{"TNK":0,"TXK":10})
        self.assertEqual(quality_level({"QN_4":"5"},"TMK"),5)
        self.assertIsNone(quality_level({"QN_4":"-999"},"TMK"))
        self.assertTrue(valid_count(330,2024,date(2025,1,1)))
        self.assertFalse(valid_count(329,2024,date(2025,1,1)))
    def test_flags_exact_entry(self):
        e=[365,"RR:02552:18951112",0,"1903-01-01","1903-12-31",365,365]
        d=dict(metrics={"dry_spell":{"kind":"station_year_series"}},stations={"RR:02552:18951112":{"height":3}},records={"Deutschland":{"1903":{"dry_spell":e}}})
        q=audit([d])
        self.assertEqual(q["checked"],1)
        self.assertEqual(q["flags"]["Deutschland|1903|dry_spell"]["status"],"excluded")
        self.assertEqual(q["flags"]["Deutschland|1903|dry_spell"]["entry"],e)
        self.assertEqual(identity("dry_spell",e,d["metrics"])[0],"02552")

if __name__=="__main__":unittest.main()
