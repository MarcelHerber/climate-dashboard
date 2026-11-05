"""Prüft feste ICON-ART-EU-Staublegenden ohne Datenabruf."""
import importlib.util
import pathlib
import unittest
import numpy as np
path=pathlib.Path(__file__).resolve().parents[1]/"scripts"/"update_saharastaub.py"
spec=importlib.util.spec_from_file_location("update_saharastaub",path)
dust=importlib.util.module_from_spec(spec)
spec.loader.exec_module(dust)

class TestSaharastaub(unittest.TestCase):
    def test_scales(self):
        self.assertEqual(dust.PALETTES["taod"]["breaks"],
                         [0.05,0.1,0.2,0.35,0.5,0.75,1,1.5,2.5])
        self.assertEqual(dust.PALETTES["column"]["breaks"],
                         [25,50,100,200,400,800,1600,2500,4000])
        self.assertEqual(len(dust.COLORS),10)
        self.assertEqual(dust.GRID["step"],0.2)

    def test_exact_thresholds(self):
        self.assertEqual(dust.quantize(
            np.array([0,.049999,.05,.1,.2,2.5,5]),
            dust.PALETTES["taod"]["breaks"]).tolist(),[0,0,1,2,3,9,9])
        self.assertEqual(dust.quantize(
            np.array([0,24.999999,25,50,4000]),
            dust.PALETTES["column"]["breaks"]).tolist(),[0,0,1,2,9])

    def test_rle_preserves_nodata_and_long_runs(self):
        data=np.array([255]*70000+[0]*70000+[1,3,6,9,255]*300,dtype=np.uint8)
        packed=dust.rle_encode(data)
        np.testing.assert_array_equal(dust.rle_decode(packed,len(data)),data)
        with self.assertRaises(ValueError):
            dust.rle_decode(packed,len(data)+1)

    def test_grib_url(self):
        import datetime as dt
        run=dt.datetime(2026,11,5,12,tzinfo=dt.timezone.utc)
        self.assertTrue(dust.url_for(run,"TAOD_DUST",72).endswith(
            "/TAOD_DUST/r/2026-11-05T12:00/s/PT072H00M.grib2"))

    def test_missing_fake_coverage_fails(self):
        aggregator=dust.Aggregator()
        points=np.full(12000,0.1)
        with self.assertRaises(RuntimeError):
            aggregator.convert(points,np.full(12000,49.0),
                               np.full(12000,9.0),"unstructured","taod")

if __name__=="__main__":
    unittest.main()
