"""Real Germany-only MOSMIX map slices, no synthetic grid interpolation."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("mosmix_chunks",ROOT/"scripts/build_mosmix_chunks.py")
mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class MOSMIXChunkTests(unittest.TestCase):
    def test_original_values_missing_data_cloud_layers_and_daily_sun(self):
        start=datetime(2026,10,27,0,tzinfo=timezone.utc)
        ts=[(start+timedelta(hours=i)).isoformat().replace("+00:00","Z") for i in range(48)]
        def station(i):
            return {
                "key":f"k{i}","id":str(i),"name":f"S{i}",
                "lat":50+i*.0001,"lon":8.6,"elev_m":110,
                "values":[12.0]*48,
                "sun1":([None]+[30.0]*47 if i==0 else [30.0]*48),
                "tx12":{"18":19.0,"42":21.0},
                "tn12":{"6":5.0,"30":7.0},
                "map_extra":{"RR1c":[2.0]*48,"RR3c":[8.0]*48,
                             "RR6c":[12.0]*48,"RRhc":[14.0]*48,
                             "RRdc":[16.0]*48,"FX1":[42.0]*48,
                             "FX3":[56.0]*48,"FXh":[70.0]*48,
                             "N":[90.0]*48,"Neff":[85.0]*48,
                             "Nl":[75.0]*48,"Nm":[40.0]*48,"Nh":[25.0]*48}}
        payload={"product":"DWD MOSMIX-L","issue_time":"2026-10-26T21:00:00Z",
                 "generated_at":"2026-10-26T21:05:00Z","timesteps":ts,
                 "station_count":150,"stations":[station(i) for i in range(150)]}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);input=root/"mosmix_ttt.json";dest=root/"out"
            input.write_text(json.dumps(payload),encoding="utf-8")
            meta=mod.build(input,dest)
            self.assertEqual(meta["schema"],2)
            self.assertEqual(len(meta["stations"]),150)
            self.assertNotIn("values",meta["stations"][0])
            self.assertEqual(len(meta["modes"]["hourly"]),48)
            self.assertEqual(len(meta["modes"]["tmax"]),2)
            self.assertEqual(len(meta["modes"]["sun"]),2)
            self.assertEqual(len(meta["modes"]["rainDay"]),2)
            self.assertEqual(len(meta["modes"]["gustDay"]),2)
            for mode in ("rain1","rain3","rain6","rain12","rain24",
                         "gust1","gust3","gust12","cloudN","cloudNeff",
                         "cloudNl","cloudNm","cloudNh"):
                self.assertEqual(len(meta["modes"][mode]),48,mode)
            def val(mode,index,station_index=1):
                frame=meta["modes"][mode][index]
                file=json.loads((dest/frame["path"]).read_text(encoding="utf-8"))
                self.assertEqual(file["issue_time"],meta["issue_time"])
                return file["values"][frame["slot"]][station_index]
            self.assertEqual(val("hourly",0),12.0)
            self.assertEqual(val("rain1",0),2.0)
            self.assertEqual(val("rain3",0),8.0)
            self.assertEqual(val("gust12",0),70.0)
            self.assertEqual(val("cloudNl",0),75.0)
            self.assertEqual(val("tmax",0),19.0)
            self.assertEqual(val("sun",0),12.0)
            self.assertEqual(val("rainDay",0),48.0)
            self.assertEqual(val("gustDay",0),42.0)
            self.assertIsNone(val("sun",0,0))
            self.assertEqual(json.loads((dest/"manifest.json").read_text())["schema"],2)

    def test_daylight_saving_day_lengths(self):
        z=timezone.utc
        def hours(start,count):
            return [(start+timedelta(hours=i)).isoformat().replace("+00:00","Z")
                    for i in range(count)]
        spring=hours(datetime(2026,3,29,0,tzinfo=z),23)
        fall=hours(datetime(2026,10,24,23,tzinfo=z),25)
        self.assertEqual(len(list(mod.local_sun_days(spring))[0][1]),23)
        self.assertEqual(len(list(mod.local_sun_days(fall))[0][1]),25)
        broken=fall[:4]+fall[5:]
        self.assertEqual(list(mod.local_sun_days(broken)),[])


if __name__=="__main__":
    unittest.main()
