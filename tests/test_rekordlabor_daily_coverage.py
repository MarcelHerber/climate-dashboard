#!/usr/bin/env python3
"""Phase 3 DWD KL calendar coverage and source-preservation regressions."""
import io, json, tempfile, unittest, zipfile
from pathlib import Path
from scripts.build_rekordlabor_daily_rain_sun import select_stations, parse, MISSING, PILOT_IDS

class DwdKlCalendarCoverage(unittest.TestCase):
    def test_balanced_selection_keeps_existing_stations_and_rejects_short_inactive(self):
        with tempfile.TemporaryDirectory() as temp:
            index=Path(temp)/"official.json"
            index.write_text(json.dumps({"stations":[
              {"id":"10001","state":"Saarland","history_end_year":2025,"accepted_history_years":60,"reference_years_available":30},
              {"id":"10002","state":"Saarland","history_end_year":2025,"accepted_history_years":55,"reference_years_available":30},
              {"id":"10003","state":"Saarland","history_end_year":1985,"accepted_history_years":90,"reference_years_available":30},
              {"id":"10004","state":"Saarland","history_end_year":2025,"accepted_history_years":8,"reference_years_available":7},
              {"id":"10101","state":"Hessen","history_end_year":2025,"accepted_history_years":65,"reference_years_available":30},
              {"id":"10102","state":"Hessen","history_end_year":2025,"accepted_history_years":62,"reference_years_available":30}
            ]}),encoding="utf8")
            ids,counts=select_stations(index,1)
            self.assertTrue(set(PILOT_IDS).issubset(set(ids)))
            self.assertIn("10001",ids)
            self.assertNotIn("10002",ids)
            self.assertNotIn("10003",ids)
            self.assertNotIn("10004",ids)
            self.assertIn("10101",ids)
            self.assertEqual(counts,{"Hessen":1,"Saarland":1})

    def test_leap_day_and_missing_original_kl_fields_preserved(self):
        io_bytes=io.BytesIO()
        with zipfile.ZipFile(io_bytes,"w") as zipf:
            zipf.writestr("produkt_kl_abc.txt", "\n".join([
              "STATIONS_ID;MESS_DATUM;QN_3;RSK;SDK;eor",
              "01420;20240228;3;1.2;3.0;eor",
              "01420;20240229;3;10.8;0.2;eor",
              "01420;20240301;3;0.0;-999;eor",
              "01420;20230228;3;2.2;7.5;eor",
            ])+"\n")
        days=parse(io_bytes.getvalue())
        self.assertEqual(days[2024]["rain"][58],12)
        self.assertEqual(days[2024]["rain"][59],108)
        self.assertEqual(days[2024]["rain"][60],0)
        self.assertEqual(days[2024]["sun"][59],2)
        self.assertEqual(days[2024]["sun"][60],MISSING)
        self.assertEqual(days[2023]["rain"][58],22)
        self.assertEqual(days[2023]["rain"][59],MISSING)
        self.assertEqual(len(days[2023]["rain"]),366)

    def test_unsupported_or_implausible_values_remain_missing(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,"w") as zipf:
            zipf.writestr("produkt_kl.txt", "\n".join([
              "MESS_DATUM;RSK;SDK",
              "20200101;-999;-999",
              "20200102;502;26",
              "20200103;0;0",
            ])+"\n")
        data=parse(out.getvalue())
        self.assertEqual(data[2020]["rain"][0],MISSING)
        self.assertEqual(data[2020]["sun"][1],MISSING)
        self.assertEqual(data[2020]["rain"][2],0)
        self.assertEqual(data[2020]["sun"][2],0)

if __name__=="__main__":unittest.main()
