import sys
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import build_blocking_monitor as blocking


class BlockingMonitorTests(unittest.TestCase):
    def setUp(self):
        self.lat=np.arange(85,24,-1,dtype=float)
        self.lon=np.arange(-90,66,dtype=float)
        # Fixed elevated central ridge, lower north geopotential -> TM block.
        self.z=np.full((len(self.lat),len(self.lon)),5550.0)
        for phi in (35,40,45):
            self.z[np.where(self.lat==phi)[0][0],:]=5400
        for phi in (55,60,65):
            self.z[np.where(self.lat==phi)[0][0],:]=5650
        for phi in (75,80,85):
            self.z[np.where(self.lat==phi)[0][0],:]=5250

    def test_real_era5_daily_request_shape(self):
        req=blocking.request([date(2026,10,3),date(2026,10,4)])
        self.assertEqual(req["pressure_level"],["500"])
        self.assertEqual(req["variable"],["geopotential"])
        self.assertEqual(req["frequency"],"6_hourly")
        self.assertEqual(req["area"],[85,-90,25,65])
        self.assertEqual(req["daily_statistic"],"daily_mean")

    def test_month_boundary_requires_split(self):
        with self.assertRaises(ValueError):
            blocking.request([date(2026,9,30),date(2026,10,1)])

    def test_gradient_reversal_all_footprint(self):
        mask=blocking.blocking_mask(self.lat,self.lon,self.z)
        self.assertTrue(mask.all())
        sectors=blocking.regions(self.lon,mask)
        self.assertEqual(len(sectors),1)
        self.assertEqual(sectors[0]["west"],-90)
        self.assertEqual(sectors[0]["east"],65)

    def test_normal_westerly_gradient_is_not_blocking(self):
        z=np.full_like(self.z,5300.0)
        for phi in (35,40,45):z[np.where(self.lat==phi)[0][0]]=5700
        for phi in (55,60,65):z[np.where(self.lat==phi)[0][0]]=5500
        for phi in (75,80,85):z[np.where(self.lat==phi)[0][0]]=5300
        self.assertFalse(blocking.blocking_mask(self.lat,self.lon,z).any())

    def test_minimum_sector_width(self):
        v=np.zeros(len(self.lon),dtype=bool)
        v[20:28]=True
        self.assertEqual(blocking.regions(self.lon,v),[])
        v[20:30]=True
        self.assertEqual(blocking.regions(self.lon,v)[0]["width_degrees"],10)

    def test_five_day_persistence(self):
        start=date(2026,10,1)
        days=[start+timedelta(days=i) for i in range(5)]
        fields=np.stack([self.z]*5)
        d=blocking.diagnostics(self.lat,self.lon,fields,days)
        self.assertTrue(d["history_complete"])
        self.assertEqual(len(d["instantaneous"]),1)
        self.assertEqual(len(d["persistent"]),1)
        fields[2]=5300
        # A missing reversal day must suppress persistent signal.
        d=blocking.diagnostics(self.lat,self.lon,fields,days)
        self.assertEqual(d["persistent"],[])

    def test_no_five_day_claim_with_date_gap(self):
        start=date(2026,10,1)
        days=[start+timedelta(days=i) for i in (0,1,3,4,5)]
        d=blocking.diagnostics(self.lat,self.lon,np.stack([self.z]*5),days)
        self.assertFalse(d["history_complete"])
        self.assertEqual(d["persistent"],[])

    def test_png_renderer_on_synthetic_test_field(self):
        # Only a deployment smoke test: synthetic fields must never be published.
        first=date(2026,10,1)
        ds=blocking.diagnostics(self.lat,self.lon,np.stack([self.z]*5),
                                [first+timedelta(days=i) for i in range(5)])
        with tempfile.TemporaryDirectory() as temp:
            png=Path(temp)/"test_only.png"
            blocking.render_map(self.lat,self.lon,self.z,date(2026,10,5),ds,png)
            self.assertGreater(png.stat().st_size,25000)
            self.assertEqual(png.read_bytes()[:8],bytes.fromhex("89504e470d0a1a0a"))

    def test_invalid_partial_grid(self):
        bad=self.z.copy()
        bad[1,1]=np.nan
        with self.assertRaises(ValueError):
            blocking.blocking_mask(self.lat,self.lon,bad)


if __name__=="__main__":
    unittest.main()
