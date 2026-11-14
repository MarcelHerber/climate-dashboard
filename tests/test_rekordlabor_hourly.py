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
        self.assertEqual(top_events(row,"pressure",1,"down")[0],1)
    def test_invalid_high_pressure_hours_never_become_records(self):
        blob=pack("p0",[
            "STATIONS_ID;MESS_DATUM;QN_8;P;P0;eor",
            "00164;2020010100;3;980;989.7;eor",
            "00164;2020010101;3;981;1090.6;eor",
            "00164;2020010102;3;982;990.2;eor",
            "00164;2020010103;3;983;991.2;eor"])
        data=rows_from_zip(blob,"pressure")
        self.assertNotIn("2020010101",data)
        self.assertEqual(top_events(data,"pressure",2,"up")[0],0)
        self.assertEqual(top_events(data,"pressure",1,"up")[0],1)
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

    def test_integer_hours_preserve_utc_boundaries_and_gaps(self):
        from scripts.build_rekordlabor_hourly import hour_key,hour_stamp,pressure_runs
        a=hour_key("2024022823")
        self.assertEqual(hour_stamp(a+1),"2024022900")
        self.assertEqual(hour_stamp(a+25),"2024030100")
        idx={a:1000.0,a+1:999.0,a+3:995.0,a+4:996.0}
        self.assertEqual(pressure_runs(idx)[a+1],1)
        self.assertEqual(pressure_runs(idx)[a+3],0)
        self.assertEqual(top_events(idx,"pressure",3,"down")[0],0)
        self.assertEqual(top_events(idx,"temperature",3,"down")[0],1)

    def test_official_station_catalogue_and_regional_selection(self):
        from unittest.mock import patch
        from scripts.build_rekordlabor_hourly import (
            historical_inventory,parse_stations_description,discover_stations
        )
        body=(
          "00071 19500101 20251231 100 50.1120 8.6840 Frankfurt am Main Hessen\n"
          "00073 19600101 20251231 200 49.2330 7.0030 Saarbrücken Saarland\n"
          "00078 19500101 20151231 100 50.1000 8.5000 Closed Hessen\n"
          "00091 20100101 20251231 100 50.2000 8.9000 Too Short Hessen\n"
        )
        stations=parse_stations_description(body)
        self.assertEqual(stations["00071"]["name"],"Frankfurt am Main")
        self.assertEqual(stations["00073"]["state"],"Saarland")
        listing={}
        for param,prefix in (("temperature","TU"),("pressure","P0"),("wind_direction","FF")):
            listing[param]="\n".join(
                f"stundenwerte_{prefix}_{sid}_{start}_{end}_hist.zip"
                for sid,start,end in (
                    ("00071","19500101","20251231"),
                    ("00073","19600101","20251231"),
                    ("00078","19500101","20151231"),
                    ("00091","20100101","20251231")
                )
            )
        self.assertIn("00071",historical_inventory(listing["temperature"],"temperature"))
        with patch("scripts.build_rekordlabor_hourly.read_url",return_value=body.encode("latin1")):
            selected=discover_stations(listing,5)
        self.assertEqual(len(selected),5)
        self.assertIn("00071",selected)
        self.assertIn("00073",selected)
        self.assertNotIn("00078",selected)
        self.assertNotIn("00091",selected)

if __name__=="__main__":unittest.main()
