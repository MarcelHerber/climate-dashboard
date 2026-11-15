import io
import unittest
from zipfile import ZipFile
from scripts.build_rekordlabor_newyear import extract_newyear, merge_records


def archive(rows, metadata):
    buffer=io.BytesIO()
    with ZipFile(buffer,"w") as z:
        z.writestr("produkt_tu_stunde.txt","STATIONS_ID;MESS_DATUM;QN_9;TT_TU;RF_TU;eor\n"+"\n".join(rows))
        z.writestr("Metadaten_Parameter_01420.txt","Stations_id;Von_Datum;Bis_Datum;Parameter_id;Parameter;Einheit;Messhoehe;Datenquelle;Zusatz-Info\n"+"\n".join(metadata))
    return buffer.getvalue()


class NewYearTest(unittest.TestCase):
    def test_utc_december_is_next_january_and_only_exact_stamp(self):
        blob=archive(["1420;2022123122;10;9;70;eor","1420;2022123123;10;12.4;70;eor","1420;2023010100;10;11;70;eor"],
          ["1420;2000-01-01;;1;TT_TU;°C;2;SYNOP;Stundenwerte in UTC"])
        self.assertEqual(extract_newyear(blob,"01420"),[[2023,12.4,"2022123123","UTC",10]])

    def test_mez_md_uses_january_00_but_plain_mez_is_ambiguous(self):
        blob=archive(["1420;1980123123;5;5;70;eor","1420;1981010100;5;-8;70;eor","1420;1982010100;5;-9;70;eor"],
          ["1420;1970-01-01;1981-06-01;1;TT_TU;°C;2;eMD;Stundenwerte in MEZ (MD)","1420;1981-06-02;;1;TT_TU;°C;2;analog;Stundenwerte in MEZ"])
        self.assertEqual(extract_newyear(blob,"01420"),[[1981,-8.0,"1981010100","MEZ (MD)",5]])

    def test_missing_duplicate_conflicting_and_humidity_metadata(self):
        blob=archive(["1420;2020123123;10;-999;70;eor","1420;2021123123;10;6;70;eor","1420;2021123123;10;7;70;eor","1420;2022123123;10;9;70;eor"],
          ["1420;2000-01-01;2022-01-01;1;TT_TU;°C;2;SYNOP;Stundenwerte in UTC","1420;2000-01-01;;2;RF_TU;%;2;SYNOP;Stundenwerte in UTC"])
        self.assertEqual(extract_newyear(blob,"01420"),[])

    def test_historical_preferred_and_recent_provisional(self):
        hist=[[2025,4.0,"2024123123","UTC",10]]
        recent=[[2025,5.0,"2024123123","UTC",3],[2026,-2.0,"2025123123","UTC",3]]
        self.assertEqual(merge_records(hist,recent),[hist[0]+["historical"],recent[1]+["recent"]])

    def test_known_local_mean_time_is_not_a_midnight_observation(self):
        blob=archive(["3987;1974010100;5;1;70;eor","3987;1976010100;5;3;70;eor"],
          ["3987;1970-01-01;;1;TT_TU;°C;2;eMD;Stundenwerte in MEZ (MD)"])
        self.assertEqual(extract_newyear(blob,"03987"),[[1976,3.0,"1976010100","MEZ (MD)",5]])
