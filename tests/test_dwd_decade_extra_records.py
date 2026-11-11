"""Offline coverage checks for new decade-record aggregations."""
import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from build_dwd_decade_extra_records import Accumulator,expected_days,METRICS
from update_station_records import Observation

def o(day,values):
 return Observation(day=day,station_id="01420",metadata_key="01420:x",
     state="Hessen",values=values,preliminary=False)

class TestCompleteDecades(unittest.TestCase):
 def test_calendar(self):
  self.assertEqual(len(expected_days(2024,2,3)),9)
  self.assertEqual(len(expected_days(2025,2,3)),8)
  self.assertEqual(len(expected_days(2025,4,3)),10)
 def test_kl(self):
  a=Accumulator("kl")
  a.add_archive([o(d,{"tmk":float(d.day),"sdk":0.0 if d.day==2 else 7.0,"fx_kmh":104.4})
                 for d in expected_days(2025,1,1)])
  p="month-01-d1"
  self.assertEqual(a.complete_decades,1)
  for metric,value in (("tmk_high",10.0),("tmk_low",1.0),("sdk_high",7.0),
                       ("sdk_sum_high",63.0),("sdk_sum_low",63.0),("fx_high",104.4)):
   self.assertEqual(a.records[metric]["Hessen"][p]["01420"][0],value)
  a.add_archive([o(date(2026,1,d),{"sdk":24.0}) for d in range(1,10)])
  self.assertEqual(a.records["sdk_sum_high"]["Hessen"][p]["01420"][0],63.0)
 def test_rr_dry_and_gap(self):
  a=Accumulator("rr");p="month-02-d3"
  a.add_archive([o(d,{"rsk_high":0}) for d in expected_days(2024,2,3)])
  self.assertEqual(a.records["rs_sum_low"]["Deutschland"][p]["01420"][0],0)
  missing=[d for d in expected_days(2025,2,3) if d.day!=25]
  a.add_archive([o(d,{"rsk_high":20}) for d in missing])
  self.assertEqual(a.records["rs_sum_high"]["Deutschland"][p]["01420"][0],0)
  a.add_archive([o(d,{"rsk_high":20}) for d in expected_days(2025,2,3)])
  self.assertEqual(a.records["rs_sum_high"]["Deutschland"][p]["01420"][0],160)
if __name__=="__main__":unittest.main()
