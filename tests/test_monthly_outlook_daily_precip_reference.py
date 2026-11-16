"""Regression tests for a true daily HYRAS 1991–2020 regional climate curve."""
import calendar
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import xarray as xr

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import build_monthly_outlook_daily_precip_reference as builder


class DailyPrecipClimateTests(unittest.TestCase):
    def test_1961_leap_weight_and_period_validation(self):
        values = [1.0] * 366
        values[59] = 10.0
        reference = {}
        for month in range(1, 13):
            days = calendar.monthrange(2000, month)[1]
            actual = 28 + 70/30 if month == 2 else days
            reference[f"{month:02d}"] = {"precipitation":{"Deutschland":{"month_total":actual}}}
        monthly = {"reference_period":"1961-1990","months":reference}
        with patch.object(builder, "REGIONS", ("Deutschland",)):
            result = builder.build_payload({"Deutschland":values}, monthly, "1961-1990")
            self.assertEqual(result["reference_period"], "1961-1990")
            self.assertIn("1961", result["underlying_data"])
            february = result["months"]["02"]["regions"]["Deutschland"]
            self.assertEqual(february["running_mm"][-1], 38.0)
            self.assertEqual(february["difference_vs_official_pct"], 0.0)
            with self.assertRaises(ValueError):
                builder.build_payload({"Deutschland":values}, monthly, "1991-2020")

    def test_v2_1961_cache_georeferenced_from_official_monthly_grid(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            legacy_file = root / "hyras_daily_reference_1961_1990_web2_v1.npz"
            calendar_days = [(month,day) for month in range(1,13)
                             for day in range(1,calendar.monthrange(2000,month)[1]+1)]
            np.savez_compressed(legacy_file, daily_mean=np.ones((366,101,101), dtype=np.float32),
                months=[m for m,d in calendar_days], days=[d for m,d in calendar_days])
            # Daily builder samples every second grid point, then reverses to
            # north-up/west-left. Test that same convention on real NetCDF.
            x = 4_000_000 + np.arange(201)*1000
            y = 3_000_000 + np.arange(201)*1000
            xr.Dataset({"pr": (("y","x"), np.ones((201,201),dtype=np.float32),
                              {"units":"mm","crs":"EPSG:3035"})},
                       coords={"x":x,"y":y}).to_netcdf(
                root / "pr_hyras_1_1961_1990_v6-1_de_JAN.nc")
            with self.assertRaises(ValueError):
                builder.load_reference(legacy_file,"1961-1990",root)
            climate_file = root / "hyras_daily_reference_1961_1990_web2_v2.npz"
            np.savez_compressed(climate_file, daily_mean=np.ones((366,101,101),dtype=np.float32),
                months=[m for m,d in calendar_days], days=[d for m,d in calendar_days],
                x=x[::2], y=y[::2][::-1], crs="EPSG:3035",
                reference_period="1961-1990", method_version=2,
                source_files=[f"pr_hyras_1_{year}_v6-1_de.nc" for year in range(1961,1991)])
            grid,gx,gy,dates = builder.load_reference(climate_file,"1961-1990",root)
            self.assertEqual(grid.shape,(366,101,101))
            self.assertEqual(gx.tolist(),x[::2].tolist())
            self.assertEqual(gy.tolist(),y[::2][::-1].tolist())
            self.assertEqual(dates,calendar_days)
            with self.assertRaises(ValueError):
                builder.load_reference(climate_file,"1991-2020",root)

    def test_year_calendar_and_grid_checked_before_accumulation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pr_hyras_1_1964_v6-1_de.nc"
            x = 4_000_000 + np.arange(5)*1000
            y = 3_000_000 + np.arange(5)*1000
            time = np.arange("1964-01-01", "1965-01-01", dtype="datetime64[D]")
            ds = xr.Dataset({"pr": (("time","y","x"),np.ones((366,5,5),dtype=np.float32),
                                     {"units":"mm","crs":"EPSG:3035"})},
                            coords={"x":x,"y":y,"time":time})
            ds.to_netcdf(path)
            values, dates = builder.validated_annual_sample(path,1964,x[::2],y[::2][::-1])
            self.assertEqual(values.shape,(366,3,3))
            self.assertEqual(dates[59],"1964-02-29")
            with self.assertRaises(ValueError):
                builder.validated_annual_sample(path,1964,x[::2]+1000,y[::2][::-1])
            ds.isel(time=slice(0,-1)).to_netcdf(path)
            with self.assertRaises(ValueError):
                builder.validated_annual_sample(path,1964,x[::2],y[::2][::-1])

    def test_v2_cache_build_accumulates_all_thirty_verified_source_years(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "original_daily"
            source.mkdir()
            x = 4_000_000 + np.arange(5)*1000
            y = 3_000_000 + np.arange(5)*1000
            attrs = {"units":"mm","crs":"EPSG:3035"}
            xr.Dataset({"pr": (("y","x"),np.ones((5,5),dtype=np.float32),attrs)},
                       coords={"x":x,"y":y}).to_netcdf(root/"pr_hyras_1_1961_1990_v6-1_de_JAN.nc")
            files = []
            for year in range(1961,1991):
                time = np.arange(f"{year}-01-01",f"{year+1}-01-01",dtype="datetime64[D]")
                name = f"pr_hyras_1_{year}_v6-1_de.nc"
                files.append(name)
                values = np.full((len(time),5,5),year-1960,dtype=np.float32)
                xr.Dataset({"pr": (("time","y","x"),values,attrs)},
                           coords={"x":x,"y":y,"time":time}).to_netcdf(source/name)
            listing = "\n".join(f'<a href="{name}">' for name in files)
            path = root / "hyras_daily_reference_1961_1990_web2_v2.npz"
            with patch.object(builder,"directory_text",return_value=listing):
                builder.build_verified_cache(path,root,root)
            with np.load(path, allow_pickle=False) as result:
                self.assertEqual(result["daily_mean"].shape, (366,3,3))
                self.assertAlmostEqual(float(result["daily_mean"][0,0,0]),15.5)
                self.assertAlmostEqual(float(result["daily_mean"][59,0,0]),16.0)
                self.assertEqual(result["source_files"].tolist(),files)
                self.assertEqual(result["method_version"].item(),2)
    def test_daily_region_means_and_coverage(self):
        grid=np.array([
            [[0,2],[4,6]],
            [[2,4],[6,8]],
        ],dtype=np.float32)
        masks={"Deutschland":np.array([[True,True],[True,True]]),
               "Hessen":np.array([[True,False],[True,False]])}
        with patch.object(builder,"REGIONS",("Deutschland","Hessen")):
            out=builder.region_daily_series(grid,masks)
        self.assertEqual(out["Deutschland"],[3,5])
        self.assertEqual(out["Hessen"],[2,4])
        grid[0,1,0]=np.nan
        with patch.object(builder,"REGIONS",("Deutschland","Hessen")):
            with self.assertRaises(ValueError):
                builder.region_daily_series(grid,masks)

    def test_full_366_day_calendar_and_february_leap(self):
        values=[1.0]*366
        reference={}
        for month in range(1,13):
            days=calendar.monthrange(2000,month)[1]
            actual=28 + 8/30 if month==2 else days
            reference[f"{month:02d}"]={"precipitation":{"Deutschland":{"month_total":actual}}}
        monthly={"reference_period":"1991-2020","months":reference}
        with patch.object(builder,"REGIONS",("Deutschland",)):
            result=builder.build_payload({"Deutschland":values},monthly)
        self.assertTrue(result["daily_climatology_available"])
        self.assertEqual(result["months"]["02"]["dates"][-1],"02-29")
        self.assertEqual(result["months"]["02"]["regions"]["Deutschland"]["running_mm"][-1],29.0)
        self.assertEqual(result["months"]["02"]["regions"]["Deutschland"]["difference_vs_official_pct"],0.0)
        self.assertEqual(result["months"]["11"]["regions"]["Deutschland"]["running_mm"][-1],30.0)
        self.assertEqual(len(result["months"]),12)

    def test_inconsistent_official_month_is_rejected(self):
        reference={}
        for month in range(1,13):
            days=calendar.monthrange(2000,month)[1]
            reference[f"{month:02d}"]={"precipitation":{"Deutschland":{"month_total":2 if month==11 else days}}}
        with patch.object(builder,"REGIONS",("Deutschland",)):
            with self.assertRaises(ValueError):
                builder.build_payload({"Deutschland":[1.0]*366},
                                      {"reference_period":"1991-2020","months":reference})

    def test_cache_missing_is_fatal(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                builder.load_reference(Path(folder)/"no-actual-climate-cache.npz")


if __name__=="__main__":
    unittest.main()
