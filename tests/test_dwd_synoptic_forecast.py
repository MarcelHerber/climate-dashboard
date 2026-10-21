import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import dwd_synoptic_forecast as dwd

NOW=datetime(2026,10,21,11,18,tzinfo=timezone.utc)

class DWDICONForecastSheetTests(unittest.TestCase):
    def test_original_file_ranges_and_dated_issue_only(self):
        html='''<a href="Z__C_EDZW_20261021033500_nwv01,ico_hptfg_na_N_000036_9900_202610210000_WV12.png">short</a>
        <a href="Z__C_EDZW_20261021033500_nwv01%2Cico_hptfg_na_N_096168_9900_202610210000_WV12.png">long</a>
        <a href="Z__C_EDZW_20261020033500_nwv01,ico_hptfg_na_N_096168_9900_202610200000_WV12.png">older</a>
        <a href="Z__C_EDZW_LATEST_nwv01,ico_hptfg_na_N_132168_9900_202610210000_WV12.png">undated</a>
        <a href="Z__C_EDZW_20261021033500_nwv01,ico_htp_na_N_096168_9900_202610210000_WV12.png">other product</a>'''
        a=dwd.extract(html,NOW)
        self.assertEqual([(x["forecast_from_hours"],x["forecast_to_hours"]) for x in a],[(0,36),(96,168)])
        self.assertEqual(a[1]["generated_utc"],"2026-10-21T03:35:00+00:00")
        self.assertEqual(a[1]["source_page"],dwd.INDEX)
        self.assertTrue(a[1]["multiple_valid_times"])
        self.assertNotIn("valid_utc",a[1])
        self.assertNotIn("run_utc",a[1])
        self.assertEqual(a[1]["publisher_id"],"dwd")
    def test_no_spoofed_hosts_stale_or_fictional_lead_times(self):
        html='''<a href="https://evil.example/weather/charts/forecasts/icon/global/na/Z__C_EDZW_20261021033500_nwv01,ico_hptfg_na_N_096168_9900_202610210000_WV12.png">spoof</a>
        <a href="Z__C_EDZW_20261021033500_nwv01,ico_hptfg_na_N_168192_9900_202610210000_WV12.png">beyond 168</a>
        <a href="Z__C_EDZW_20260921033500_nwv01,ico_hptfg_na_N_000036_9900_202609210000_WV12.png">stale</a>
        <a href="Z__C_EDZW_20261022123500_nwv01,ico_hptfg_na_N_096168_9900_202610220000_WV12.png">future</a>'''
        self.assertEqual(dwd.extract(html,NOW),[])
    def test_uses_single_model_cycle_and_prefers_latest_complete_seven_day_cycle(self):
        html='''<a href="Z__C_EDZW_20261021033500_nwv01,ico_hptfg_na_N_000036_9900_202610210000_WV1.png">00Z short</a>
        <a href="Z__C_EDZW_20261021033500_nwv01,ico_hptfg_na_N_096168_9900_202610210000_WV1.png">00Z full</a>
        <a href="Z__C_EDZW_20261021094500_nwv01,ico_hptfg_na_N_000036_9900_202610210600_WV1.png">06Z short</a>'''
        items=dwd.extract(html,NOW)
        self.assertEqual({x["run_utc"] for x in items},{"2026-10-21T00:00:00+00:00"})
        self.assertEqual([(x["forecast_from_hours"],x["forecast_to_hours"]) for x in items],[(0,36),(96,168)])

    def test_valid_utc_is_not_taken_from_file_issue_time(self):
        html='<a href="Z__C_EDZW_20261021094500_nwv01,ico_hptfg_na_N_000036_9900_202610210600_WV1.png">06Z</a>'
        items=dwd.extract(html,NOW)
        self.assertEqual(items[0]["run_utc"],"2026-10-21T06:00:00+00:00")
        self.assertNotEqual(items[0]["generated_utc"],items[0]["run_utc"])
        self.assertNotIn("valid_utc",items[0])

    def test_later_reissue_wins_same_interval(self):
        html='''<a href="Z__C_EDZW_20261021033500_nwv01,ico_hptfg_na_N_132168_9900_202610210000_WV12.png">old</a>
        <a href="Z__C_EDZW_20261021094500_nwv01,ico_hptfg_na_N_132168_9900_202610210600_WV12.png">new</a>'''
        a=dwd.extract(html,NOW)
        self.assertEqual(len(a),1)
        self.assertEqual(a[0]["generated_utc"],"2026-10-21T09:45:00+00:00")

if __name__=="__main__":
    unittest.main()
