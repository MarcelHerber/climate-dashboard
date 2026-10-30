import unittest
from datetime import datetime, timezone, timedelta
import numpy as np
from scripts.build_ecmwf_ens_u60 import mean_u60, validate, request, STEPS, MEMBERS, EXPECTED_LONS

class ENSU60Tests(unittest.TestCase):
    def test_signed_zonal_wind(self):
        lon=np.arange(EXPECTED_LONS,dtype=float)/4
        lat=np.full(EXPECTED_LONS,60.)
        u=-15+5*np.sin(np.deg2rad(lon))
        self.assertAlmostEqual(mean_u60(lat,lon,u),-15,places=3)
        with self.assertRaises(ValueError):mean_u60(lat[:-1],lon[:-1],u[:-1])
        with self.assertRaises(ValueError):mean_u60(lat,np.zeros(EXPECTED_LONS),u)

    def test_full_member_contract(self):
        self.assertEqual(STEPS,list(range(0,361,24)))
        self.assertEqual(len(MEMBERS),51)
        cycle=datetime(2026,10,29,tzinfo=timezone.utc)
        dates=[(cycle+timedelta(hours=h)).strftime("%Y-%m-%d") for h in STEPS]
        good={"schema_version":1,"provider":"ECMWF IFS ENS","level_hpa":10,"latitude_deg":60,"units":"m/s",
              "forecast_step_hours":STEPS,"member_count":51,"perturbed_count":50,
              "cycle_utc":"2026-10-29T00:00:00Z","valid_dates":dates,
              "members":{k:[3.]*len(dates) for k in MEMBERS}}
        now=cycle+timedelta(hours=12)
        self.assertTrue(validate(good,now))
        self.assertFalse(validate({**good,"member_count":50},now))
        self.assertFalse(validate({**good,"members":{"c00":[3.]*len(dates)}},now))
        self.assertFalse(validate({**good,"members":{**good["members"],"p01":[None]*len(dates)}},now))
        self.assertFalse(validate({**good,"cycle_utc":"2026-10-20T00:00:00Z"},now))

    def test_post_50r1_sources(self):
        class Mock:
            def __init__(self):self.calls=[]
            def retrieve(self,**kwargs):self.calls.append(kwargs)
        c=Mock()
        cycle=datetime(2026,10,29,tzinfo=timezone.utc)
        request(c,cycle,240,"/tmp/eps.grib2",True)
        request(c,cycle,240,"/tmp/control.grib2",False)
        e,o=c.calls
        self.assertEqual((e["stream"],e["type"]),("enfo","ef"))
        self.assertEqual(e["number"],list(range(1,51)))
        self.assertEqual((o["stream"],o["type"]),("oper","fc"))
        self.assertNotIn("number",o)
        self.assertEqual((e["param"],e["levelist"],e["step"]),("u",10,240))

if __name__=="__main__":unittest.main()
