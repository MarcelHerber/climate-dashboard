"""Offline checks for the non-additive DWD KL SDK sunshine comparison."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_duett_station_sun as qc


class StationComparisonTests(unittest.TestCase):
    def test_cross_check_not_applied_as_correction(self):
        duett={"month":"2026-11","dates":["2026-11-01","2026-11-02"],
               "regions":{"Deutschland":{"running":[5.0, 15.0]}, "Hessen":{"running":[4.0, 12.0]}}}
        station={"month":"2026-11","data_through":"2026-11-01",
                 "source":{"sun":"DWD KL daily SDK"},
                 "sun_station_count":96,
                 "areas":{"Deutschland":{"sun":6.0},"Hessen":{"sun":23.0}}}
        result=qc.compare(duett,station)
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["evaluated"]),2)
        self.assertEqual(len(result["warnings"]),1)
        self.assertEqual(result["warnings"][0]["region"],"Hessen")
        self.assertEqual(duett["regions"]["Hessen"]["running"],[4.0,12.0])

    def test_wrong_month_or_missing_cutoff_skipped(self):
        d={"month":"2026-11","dates":["2026-11-01"],"regions":{}}
        s={"month":"2026-10","data_through":"2026-10-30","source":{"sun":"SDK"}}
        self.assertFalse(qc.compare(d,s)["complete"])


if __name__=="__main__":
    unittest.main()
