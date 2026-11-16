import sys
import unittest
import datetime as dt
import json
import tempfile
from unittest.mock import patch
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from satellite_temperature_advection import advection_field, select_markers, interpolate_fields


class TemperatureAdvectionTests(unittest.TestCase):
    def setUp(self):
        self.x = np.arange(-10., 11., .25)
        self.y = np.arange(40., 61., .25)
        self.xx, self.yy = np.meshgrid(self.x, self.y)
        self.t = 280 - (self.yy-50) * 2
        self.zero = np.zeros_like(self.t)
        self.sp = np.full_like(self.t, 100000.)

    def test_southerly_flow_advects_warm_air_in_kelvin_per_six_hours(self):
        a = advection_field(self.x, self.y, self.t, self.zero, self.zero+10, self.sp, 850)
        self.assertAlmostEqual(a[40, 40], 3.885, places=2)
        cold = advection_field(self.x, self.y, self.t, self.zero, self.zero-10, self.sp, 850)
        self.assertAlmostEqual(cold[40, 40], -3.885, places=2)

    def test_zonal_gradient_accounts_for_latitude(self):
        a = advection_field(self.x, self.y, 280-self.xx, self.zero+10, self.zero, self.sp, 850)
        self.assertAlmostEqual(a[40, 40], 3.022, places=2)

    def test_below_ground_and_adjacent_gradient_are_invalid(self):
        self.sp[40, 40] = 80000
        a = advection_field(self.x, self.y, self.t, self.zero, self.zero+10, self.sp, 850)
        self.assertTrue(np.isnan(a[40, 40]))
        self.assertTrue(np.isnan(a[41, 40]))
        self.assertTrue(np.isfinite(a[20, 20]))

    def test_markers_have_significant_advection_and_wind_direction(self):
        a = advection_field(self.x, self.y, self.t, self.zero, self.zero+10, self.sp, 850)
        markers = select_markers(self.x, self.y, a, self.zero, self.zero+10)
        self.assertTrue(markers)
        self.assertTrue(all(m['advection'] >= 2 and m['v'] > 0 and m['u'] == 0 for m in markers))
        self.assertLess(len(markers), 150)
        self.assertEqual(select_markers(self.x, self.y, self.zero, self.zero, self.zero+10), [])

    def test_interpolation_before_diagnosis(self):
        a = (self.x, self.y, self.t, self.zero, self.zero+10, self.sp)
        b = (self.x, self.y, self.t+2, self.zero+4, self.zero+20, self.sp)
        fields = interpolate_fields({0:a,3:b}, 90)
        self.assertEqual(float(fields[2][40,40]), 281.)
        self.assertEqual(float(fields[3][40,40]), 2.)
        self.assertEqual(float(fields[4][40,40]), 15.)
        with self.assertRaises(ValueError):
            interpolate_fields({0:a,3:b}, 190)

    def test_interpolation_does_not_use_extrapolated_below_ground_temperature(self):
        low_sp=self.sp.copy();low_sp[40,40]=84000
        high_sp=self.sp.copy();high_sp[40,40]=88000
        a=(self.x,self.y,self.t,self.zero,self.zero+10,low_sp)
        b=(self.x,self.y,self.t+2,self.zero,self.zero+10,high_sp)
        fields=interpolate_fields({0:a,3:b},90,level=850)
        self.assertTrue(np.isnan(fields[2][40,40]))
        self.assertTrue(np.isfinite(fields[2][20,20]))

    def test_serialized_wind_vectors_keep_minimum_speed(self):
        markers=select_markers(self.x,self.y,self.zero+3,self.zero+1.41,self.zero+1.42)
        self.assertEqual(markers,[])

    def test_coarse_and_fine_pressure_chunks_share_advection(self):
        import build_satellite_mslp_10min as builder
        run = dt.datetime(2026,11,16,0,tzinfo=dt.timezone.utc)
        marker = {'850':[{'lon':0,'lat':50,'advection':3.,'u':0.,'v':10.}], '925':[], '700':[]}
        def pressure(_, run, minute):
            return {'valid_utc':(run+dt.timedelta(minutes=minute)).isoformat(),
                    'forecast_minute':minute,'contours':[{'hpa':1015,'lines':[]}],
                    'fine_contours':[{'hpa':1014,'lines':[]}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(builder,'frame_from_grids',side_effect=pressure), patch('satellite_temperature_advection.frame_markers',return_value=marker):
            manifest=builder.build_10min(dict.fromkeys(builder.MODEL_STEPS_HOURS,None),run,run,Path(tmp),advection_grids={850:{}})
            coarse=json.loads((Path(tmp)/manifest['hours']['h00']).read_text())
            fine=json.loads((Path(tmp)/manifest['fine_hours']['h00']).read_text())
            self.assertEqual(coarse['frames'][0]['temperature_advection'],marker)
            self.assertEqual(fine['frames'][0]['temperature_advection'],marker)
            self.assertEqual(manifest['advection_algorithm'],'ifs_temperature_advection_v1')
