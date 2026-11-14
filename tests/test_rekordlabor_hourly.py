#!/usr/bin/env python3
import io,zipfile,unittest
from scripts.build_rekordlabor_hourly import (
    rows_from_zip, top_events, record_events, delta, step, iso, STATIONS, HOURS
)

def pack(name,lines):
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("produkt_"+name+"_stunde_2020.txt","\n".join(lines)+"\n")
    return out.getvalue()

class RecordLaborHourlyTests(unittest.TestCase):
    def test_dwd_tu_fields_and_gaps(self):
        blob=pack("tu",[
           "STATIONS_ID;MESS_DATUM;QN_9;TT_TU;RF_TU;eor",
           "00164;2020010100;3;4.5;80;eor",
           "00164;2020010101;3;-999;70;eor",
           "00164;2020010102;3;12.8;60;eor"])
        row=rows_from_zip(blob,"temperature")
        self.assertEqual(row,{"2020010100":4.5,"2020010102":12.8})
        self.assertEqual(top_events(row,"temperature",1,"up")[0],0)
        self.assertEqual(top_events(row,"temperature",2,"up")[0],1)
    def test_dwd_pressure_no_invalid_sentinel(self):
        blob=pack("p0",[
            "STATIONS_ID;MESS_DATUM;QN_8;P;P0;eor",
            "00164;2020010100;3;980.5;1003.7;eor",
            "00164;2020010101;3;979.8;1002.9;eor",
            "00164;2020010102;3;999;2000;eor"])
        row=rows_from_zip(blob,"pressure")
        self.assertEqual(len(row),2)
        self.assertAlmostEqual(row["2020010101"],1002.9)
    def test_dwd_wind_direction_threshold(self):
        blob=pack("ff",[
           "STATIONS_ID;MESS_DATUM;QN_3;F;D;eor",
           "00164;2020010100;3;4.2;350;eor",
           "00164;2020010101;3;4.9;10;eor",
           "00164;2020010102;3;1.1;180;eor"])
        row=rows_from_zip(blob,"wind_direction")
        self.assertEqual(delta("wind_direction",row["2020010100"],row["2020010101"]),20)
        self.assertIsNone(delta("wind_direction",row["2020010101"],row["2020010102"]))
        self.assertEqual(top_events(row,"wind_direction",1,"up")[0],1)
    def test_exact_utc_steps_and_nonoverlapping_events(self):
        self.assertEqual(step("2024022823",1),"2024022900")
        self.assertEqual(step("2024022923",1),"2024030100")
        self.assertEqual(iso("2024022906"),"2024-02-29T06:00Z")
        data={"20200101"+str(h).zfill(2):float(h) for h in range(24)}
        result=record_events(data,"temperature",3,"up")
        self.assertEqual(result["coverage"]["pairs"],21)
        self.assertTrue(all(item["delta"]==3 for item in result["events"]))
        self.assertGreater(len(result["events"][0]["trace"]),24)
if __name__=="__main__":unittest.main()
