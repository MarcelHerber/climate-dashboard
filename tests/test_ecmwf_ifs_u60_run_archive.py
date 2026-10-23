import unittest
from datetime import datetime, timezone, timedelta
import numpy as np
from scripts.build_ecmwf_ifs_u60_run_archive import (
  mean_u60, validate_run, cycle_candidates, STEPS, LONGITUDES
)

class IFS60NTests(unittest.TestCase):
    def test_zonal_mean_full_circle(self):
        lons=np.arange(LONGITUDES)/4
        lats=np.full(LONGITUDES,60.)
        values=15+3*np.cos(np.deg2rad(lons))+2*np.sin(3*np.deg2rad(lons))
        self.assertAlmostEqual(mean_u60(lats,lons,values),15.,places=3)
        with self.assertRaises(ValueError):
            mean_u60(lats[:-1],lons[:-1],values[:-1])
        with self.assertRaises(ValueError):
            mean_u60(lats,np.zeros(LONGITUDES),values)
        with self.assertRaises(ValueError):
            mean_u60(lats,lons,np.full(LONGITUDES,np.nan))
        # Mean the signed U wind, not the magnitude/speed.
        self.assertAlmostEqual(mean_u60(lats,lons,-values),-15.,places=3)

    def test_run_30_steps_and_validation(self):
        self.assertEqual(STEPS,list(range(0,361,12)))
        self.assertEqual(len(STEPS),31)
        cycle="2026-10-23T12:00:00Z"
        good={"cycle_utc":cycle,"steps_hours":STEPS,
              "values":[float(x/12) for x in STEPS]}
        self.assertTrue(validate_run(good))
        self.assertFalse(validate_run({**good,"values":good["values"][:-1]}))
        self.assertFalse(validate_run({**good,"steps_hours":[0,12,24]}))
        self.assertFalse(validate_run({**good,"cycle_utc":"2026-10-23T09:00:00Z"}))
        self.assertFalse(validate_run({**good,"values":[float("nan")]*len(STEPS)}))

    def test_cycle_times(self):
        now=datetime(2026,10,23,23,12,tzinfo=timezone.utc)
        cycles=cycle_candidates(now)
        self.assertEqual([x.hour for x in cycles[:4]],[12,0,12,0])
        self.assertEqual(cycles[0],datetime(2026,10,23,12,tzinfo=timezone.utc))
        self.assertEqual(len(cycles),8)

if __name__=="__main__":unittest.main()
