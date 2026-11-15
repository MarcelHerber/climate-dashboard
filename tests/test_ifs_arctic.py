import unittest
import numpy as np
from scripts import ifs_weekly_01 as ifs


class ArcticTests(unittest.TestCase):
    def tearDown(self):
        ifs.configure_domain("europe")

    def test_grid_and_reference(self):
        ifs.configure_domain("arctic")
        self.assertEqual((len(ifs.LAT), len(ifs.LON)), (301, 3600))
        self.assertEqual((len(ifs.REF_LAT), len(ifs.REF_LON)), (121, 1440))
        self.assertEqual((ifs.LAT[0], ifs.LAT[-1], ifs.LON[0], ifs.LON[-1]), (90,60,-180,179.9))
        self.assertIn("arctic", ifs.VERSION)
        ifs.configure_domain("europe")
        self.assertEqual((len(ifs.LAT), len(ifs.LON)), (601,1801))
        self.assertEqual(ifs.VERSION, "era5-t2m-calendar-hour-1991-2020-v1")

    def test_periodic_interpolation(self):
        lat=np.array([90.,60.])
        lon=np.arange(-180.,180.,90.)
        field=np.array([[10.,20.,30.,40.],[10.,20.,30.,40.]])
        result=ifs.interpolate_reference(field,lat,lon,np.array([75.]),np.array([-180.,135.,179.]),periodic=True)
        np.testing.assert_allclose(result,[[10.,25.,10.+30./90.]])
