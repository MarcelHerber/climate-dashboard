"""Regressions: ECMWF real Hart CPS and GEFS unique-center track linking."""
import datetime as dt
import importlib.util
from pathlib import Path
import subprocess
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

ec=load("ecmwf_hart", "scripts/update_ecmwf_atlantic_cps.py")
gefs=load("gefs_unique", "scripts/update_gefs_cps.py")


class TestRealIFSAndAIFSHart(unittest.TestCase):
    def test_925_850_log_pressure_height(self):
        z925=np.full((5,5),900.0)
        z850=np.full((5,5),1500.0)
        z900=z925+(z850-z925)*np.log(900/925)/np.log(850/925)
        self.assertTrue(np.all((z900>900)&(z900<1500)))

    def test_motion_vector_eastward(self):
        pts=[{"lat":44,"lon":-43},{"lat":44.5,"lon":-42},{"lat":45,"lon":-40.5}]
        dx,dy=ec.motion_vector(pts,1)
        self.assertGreater(dx,0)
        self.assertGreater(dy,0)

    def test_geopotential_cps_accepts_real_3d_fields_for_matching_run(self):
        lats=np.linspace(40,50,101)
        lons=np.linspace(-45,-35,101)
        lon,lat=np.meshgrid(lons,lats)
        levels=[925,850,700,600,500,400,300]
        fields={}
        for level in levels:
            height=11000*(1000-level)/700
            cyclone=-120*np.exp(-((lat-45)**2+(lon+40)**2)/7)
            fields[f"z{level}"]=np.asarray(height+cyclone+(lon+40)*(level/70),dtype=float)
        z925,z850=fields["z925"],fields["z850"]
        fields["z900"]=z925+(z850-z925)*np.log(900/925)/np.log(850/925)
        run=dt.datetime(2026,10,12,0,tzinfo=dt.timezone.utc)
        p1={"h":0,"time":"2026-10-12T00:00:00Z","lat":45,"lon":-40,
            "mslp_hpa":982}
        p2={"h":12,"time":"2026-10-12T12:00:00Z","lat":45.2,"lon":-39.7,
            "mslp_hpa":980}
        archive=[{"id":"ifs-atl-test-1","model":"ifs-atl",
                  "run":"2026-10-12T00:00:00Z","points":[p1,p2]}]
        z={0:fields,12:fields}
        sp={0:{"sp":np.full(lat.shape,1010.0)},
            12:{"sp":np.full(lat.shape,1010.0)}}
        actual,n=ec.diagnose_tracks(archive,z,sp,lat,lon,"ifs-atl",run)
        self.assertEqual(n,2)
        self.assertEqual(len(actual[0]["points"]),2)
        self.assertEqual(actual[0]["points"][0]["cps"]["interpolated_levels_hpa"],[900])
        shifted=run+dt.timedelta(hours=12)
        wrong,count=ec.diagnose_tracks(archive,z,sp,lat,lon,"ifs-atl",shifted)
        self.assertEqual((len(wrong),count),(0,0))
        # Undersurface 900hPa: no silently fabricated CPS points.
        underground={0:{"sp":np.full(lat.shape,850.0)},
                     12:{"sp":np.full(lat.shape,850.0)}}
        wrong,n=ec.diagnose_tracks(archive,z,underground,lat,lon,"ifs-atl",run)
        self.assertEqual(n,0)


class TestGEFSCenterContinuity(unittest.TestCase):
    def test_unique_local_minimum_and_movement_gate(self):
        latitude=np.linspace(39,49,101)
        longitude=np.linspace(-45,-35,101)
        lon,lat=np.meshgrid(longitude,latitude)
        p=980+0.7*(lat-44)**2+0.4*(lon+40)**2
        f={"msl":p}
        reference={"lat":44,"lon":-40,"mslp_hpa":980}
        choices=gefs.potential_member_centers(f,lat,lon,reference)
        self.assertGreaterEqual(len(choices),1)
        self.assertLess(choices[0][0],50)
        near={"lat":44,"lon":-40,"mslp_hpa":981}
        nearChoices=gefs.potential_member_centers(
            f,lat,lon,reference,previous=near,hours_after_last=12)
        self.assertTrue(nearChoices)
        veryFar={"lat":60,"lon":-10,"mslp_hpa":980}
        no=gefs.potential_member_centers(
            f,lat,lon,reference,previous=veryFar,hours_after_last=12)
        self.assertFalse(no)

    def test_frontend_scripts_parse(self):
        for name in ("tiefdruck_tracker.js","tiefdruck_phase.js"):
            with self.subTest(name=name):
                subprocess.run(["node","--check",str(ROOT/name)],
                               check=True,capture_output=True)
        h=(ROOT/"tiefdruck_tracker.html").read_text()
        s=(ROOT/"tiefdruck_tracker.js").read_text()
        self.assertIn('value="single"',h)
        self.assertIn("ECMWF_CPS_URL",s)

if __name__=="__main__":
    unittest.main()
