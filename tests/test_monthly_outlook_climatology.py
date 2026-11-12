"""Offline tests for the DWD 1991-2020 1 km climatology builder."""
from __future__ import annotations

import gzip
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_monthly_outlook_climatology as climate


class MonthlyClimatologyTests(unittest.TestCase):
    def test_precip_selects_latest_official_1991_2020_version(self):
        html = '\n'.join([
            '<a href="pr_hyras_1_1961_1990_v6-1_de_NOV.nc">',
            '<a href="pr_hyras_1_1991_2020_v6-0_de_NOV.nc">',
            '<a href="pr_hyras_1_1991_2020_v6-1_de_NOV.nc">',
        ])
        self.assertEqual(climate.precipitation_filename(html, 11),
                         "pr_hyras_1_1991_2020_v6-1_de_NOV.nc")
        with self.assertRaises(RuntimeError):
            climate.precipitation_filename(html, 12)

    def test_fixed_width_ascii_north_first_and_nodata(self):
        ncols, nrows = 654, 866
        with tempfile.TemporaryDirectory() as folder:
            filename = Path(folder) / "test.asc.gz"
            header = ("NCOLS 654\nNROWS 866\nXLLCORNER 3450000\n"
                      "YLLCORNER 5220000\nCELLSIZE 1000\nNODATA_VALUE -999\n")
            ordinary = ("0123" * ncols + "\n").encode("ascii")
            special = ("-999" + "0123" * (ncols-1) + "\n").encode("ascii")
            with gzip.open(filename, "wb") as stream:
                stream.write(header.encode("ascii"))
                stream.write(special)
                for _ in range(nrows-1):
                    stream.write(ordinary)
            x,y,arr = climate.ascii_grid(filename)
            self.assertEqual(arr.shape,(866,654))
            self.assertEqual(x[0],3450500)
            self.assertEqual(y[-1],5220500)
            self.assertEqual(y[0],5220500 + (866-1)*1000)
            self.assertTrue(np.isnan(arr[0,0]))
            self.assertEqual(arr[0,1],123)
            self.assertEqual(arr[-1,-1],123)

    def test_valid_coverage_and_monthly_total(self):
        raster=np.array([[1.0,3.0],[np.nan,4.0]],dtype=float)
        mask={"Deutschland":np.array([[True,True],[False,False]],dtype=bool),
              "Hessen":np.array([[False,False],[False,True]],dtype=bool)}
        with patch.object(climate,"REGIONS",("Deutschland","Hessen")):
            result=climate.area_total(raster,mask)
        self.assertEqual(result["Deutschland"]["month_total"],2.0)
        self.assertEqual(result["Hessen"]["month_total"],4.0)

    def test_low_spatial_coverage_rejected(self):
        raster=np.array([[1.0,np.nan],[np.nan,4.0]],dtype=float)
        mask={"Deutschland":np.ones((2,2),dtype=bool)}
        with patch.object(climate,"REGIONS",("Deutschland",)):
            with self.assertRaises(ValueError):
                climate.area_total(raster,mask)


if __name__=="__main__":
    unittest.main()
