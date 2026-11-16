"""Tests for DWD historical KL sunshine daily station climatology (not DUETT)."""
from __future__ import annotations
import calendar
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from pyproj import Transformer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import build_monthly_outlook_daily_sun_reference as sun


class HistoricalSunTests(unittest.TestCase):
    def test_daily_sdk_rows_and_missing_hours(self):
        rows=["STATIONS_ID;MESS_DATUM; SDK"]
        rows += [f"12345;{year}1101;5.0" for year in range(1991,2021)]
        rows += ["12345;19911102;-999","12345;19921102;25.0"]
        rows += [f"12345;{year}0229;3.0" for year in (1992,1996,2000,2004,2008,2012,2016,2020)]
        blob=io.BytesIO()
        with zipfile.ZipFile(blob,"w") as archive:
            archive.writestr("produkt_klima_tag_12345_19910101_20201231.txt",
                             "\n".join(rows).encode("latin-1"))
        record=sun.parse_sdk_zip(blob.getvalue())
        template=sun.day_template()
        self.assertEqual(len(template),366)
        self.assertEqual(len(record["daily_h"]),366)
        self.assertEqual(record["daily_h"][template.index((11,1))],5.0)
        self.assertIsNone(record["daily_h"][template.index((11,2))])
        self.assertEqual(record["daily_h"][template.index((2,29))],3.0)
        self.assertEqual(record["year_samples"][template.index((2,29))],8)

    def test_months_calibrated_to_official_grid_total_not_flat_days(self):
        refs={}
        for month in range(1,13):
            days=calendar.monthrange(2000,month)[1]
            weighted=days - (22/30 if month==2 else 0)
            refs[f"{month:02d}"]={"sunshine":{"Deutschland":{"month_total":weighted*2}}}
        monthly={"reference_period":"1991-2020","months":refs}
        # Daily station sunshine is not constant. Preserve day-to-day
        # variations while adjusting only their official monthly sum.
        vals=[]
        for m in range(1,13):
            for d in range(1,calendar.monthrange(2000,m)[1]+1):
                vals.append(1 if d%2 else 3)
        with patch.object(sun,"REGIONS",("Deutschland",)):
            result=sun.build_payload({"Deutschland":vals},monthly,{"stations":90})
        nov=result["months"]["11"]["regions"]["Deutschland"]
        self.assertEqual(nov["running_h"][-1],60)
        self.assertLess(nov["daily_h"][0],nov["daily_h"][1])
        self.assertTrue(result["daily_climatology_available"])
        self.assertIn("reconstruction",result["product"])

    def test_too_large_adjustment_fails_closed(self):
        refs={}
        for month in range(1,13):
            refs[f"{month:02d}"]={"sunshine":{"Deutschland":{"month_total":2000}}}
        with patch.object(sun,"REGIONS",("Deutschland",)):
            with self.assertRaises(ValueError):
                sun.build_payload({"Deutschland":[1]*366},
                                  {"reference_period":"1991-2020","months":refs},{})

    def test_idw_field_is_spatial_and_daywise(self):
        t=Transformer.from_crs(4326,31467,always_xy=True)
        points=[(51.0,10.0),(51.1,10.1),(50.9,9.9)]
        p=[t.transform(lon,lat) for lat,lon in points]
        x=np.linspace(p[0][0]-18000,p[0][0]+18000,24)
        y=np.linspace(p[0][1]-18000,p[0][1]+18000,24)
        station_map={f"s{i}":{"daily_h":[float(1+i)]*366} for i in range(3)}
        coords={f"s{i}":points[i] for i in range(3)}
        masks={"Deutschland":np.ones((24,24),dtype=bool),
               "Hessen":np.ones((24,24),dtype=bool)}
        with patch.object(sun,"REGIONS",("Deutschland","Hessen")):
            result,quality=sun.sun_region_interpolation(station_map,coords,x,y,masks)
        self.assertEqual(len(result["Deutschland"]),366)
        self.assertTrue(all(1<=v<=3 for v in result["Deutschland"]))
        self.assertEqual(quality["grid_km"],6)

    def test_select_historical_files_only(self):
        metadata="00011 19800101 20251231 88 50.123 8.123 ABC\n00012 20010101 20251231 88 50.123 8.123 ABC\n"
        found=sun.stations_metadata(metadata)
        self.assertIn("00011",found)
        self.assertNotIn("00012",found)

    def test_1961_period_uses_only_historical_sdk_and_seven_leap_samples(self):
        rows=["STATIONS_ID;MESS_DATUM; SDK"]
        rows += [f"12345;{year}1101;2.0" for year in range(1961,1991)]
        rows += [f"12345;{year}1101;5.0" for year in range(1991,2021)]
        rows += [f"12345;{year}0229;3.0" for year in range(1964,1989,4)]
        blob=io.BytesIO()
        with zipfile.ZipFile(blob,"w") as archive:
            archive.writestr("produkt_klima_tag_12345_19610101_20201231.txt", "\n".join(rows))
        record=sun.parse_sdk_zip(blob.getvalue(),reference_period="1961-1990")
        self.assertEqual(record["daily_h"][sun.day_template().index((11,1))],2.0)
        self.assertEqual(record["year_samples"][sun.day_template().index((11,1))],30)
        self.assertEqual(record["daily_h"][sun.day_template().index((2,29))],3.0)
        self.assertEqual(record["year_samples"][sun.day_template().index((2,29))],7)

    def test_1961_period_selects_archived_stations_and_excludes_recent_only(self):
        metadata="00011 19500101 19901231 88 50.123 8.123 ABC\n00012 19800101 20251231 88 50.123 8.123 DEF\n"
        found=sun.stations_metadata(metadata,reference_period="1961-1990")
        self.assertEqual(set(found),{"00011"})
        positions={f"{i:05d}":(50.0,8.0) for i in range(100)}
        listing="\n".join(f'<a href="tageswerte_KL_{i:05d}_19500101_19901231_hist.zip">' for i in range(60))
        listing+='\n<a href="tageswerte_KL_00060_19800101_20251231_hist.zip">'
        files=sun.available_station_zips(listing,positions,reference_period="1961-1990")
        self.assertEqual(len(files),60)
        self.assertNotIn("00060",files)

    def test_1961_february_calibration_weights_seven_leap_years(self):
        refs={f"{m:02d}":{"sunshine":{"Deutschland":{"month_total":2*calendar.monthrange(2000,m)[1]}}} for m in range(1,13)}
        refs["02"]["sunshine"]["Deutschland"]["month_total"]=56+14/30
        monthly={"reference_period":"1961-1990","months":refs}
        with patch.object(sun,"REGIONS",("Deutschland",)):
            result=sun.build_payload({"Deutschland":[2]*366},monthly,{"stations":90},reference_period="1961-1990")
            self.assertEqual(result["reference_period"],"1961-1990")
            feb=result["months"]["02"]["regions"]["Deutschland"]
            self.assertEqual(feb["monthly_shape_adjustment_factor"],1)
            self.assertEqual(feb["daily_h"], [2.0]*29)
            self.assertEqual(feb["running_h"][-1],58.0)
            self.assertIn("1961–1990",result["source"])
            self.assertIn("seven",result["leap_day_note"])
            with self.assertRaises(ValueError):
                sun.build_payload({"Deutschland":[2]*366},monthly,{},reference_period="1991-2020")

    def test_1961_station_cache_never_reuses_1991_values(self):
        chosen={f"{i:05d}":f"station-{i}.zip" for i in range(60)}
        with tempfile.TemporaryDirectory() as work:
            cache=Path(work)
            for station,filename in chosen.items():
                (cache/(station+".json")).write_text(json.dumps({"source_file":filename,"daily_h":[5.0]*366,"year_samples":[30]*366}),encoding="utf-8")
            rows=["STATIONS_ID;MESS_DATUM; SDK"]
            rows += [f"12345;{year}{m:02d}{d:02d};2.0" for year in range(1961,1991) for m in range(1,13) for d in range(1,calendar.monthrange(year,m)[1]+1)]
            blob=io.BytesIO()
            with zipfile.ZipFile(blob,"w") as archive:
                archive.writestr("produkt_klima_tag_12345_19610101_19901231.txt", "\n".join(rows))
            with patch.object(sun,"get",return_value=blob.getvalue()):
                old,errors=sun.station_normals(chosen,cache,workers=4,reference_period="1961-1990")
            self.assertEqual(errors,{})
            self.assertTrue(all(row["daily_h"]==[2]*366 for row in old.values()))
            current,errors=sun.station_normals(chosen,cache,workers=4)
            self.assertEqual(errors,{})
            self.assertTrue(all(row["daily_h"]==[5]*366 for row in current.values()))


if __name__=="__main__":
    unittest.main()
