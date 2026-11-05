"""Offline regression tests: provisional month uses only observed daily data."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import xarray as xr

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import build_monthly_provisional as provisional


class MonthlyProvisionalTests(unittest.TestCase):
    def test_dates_current_partial_month(self):
        self.assertEqual(provisional.dates_for_month(2026,11,"2026-11-03"),
                         ["2026-11-01","2026-11-02","2026-11-03"])
        with self.assertRaises(ValueError):
            provisional.dates_for_month(2026,11,"2026-12-01")

    def test_temperature_mean_and_precipitation_cumulative(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"data"
            work=Path(temp)/"work"
            (root/"tmean/regions").mkdir(parents=True)
            work.mkdir(parents=True)
            (root/"tmean/regions/index.json").write_text(
                json.dumps({"year":2026,"current_file":"current_2026.json"}))
            (root/"tmean/regions/current_2026.json").write_text(json.dumps({
                "dates":["2026-11-01","2026-11-02","2026-11-03"],
                "data_through":"2026-11-03",
                "regions":{"Deutschland":[5,7,9],"Hessen":[5,7,9]},
            }))
            (root/"hyras_index.json").write_text(json.dumps({
                "data_through":"2026-11-03","daily_source_file":"pr.nc",
            }))
            field=xr.DataArray(
                np.asarray([[[1,2],[3,4]],[[1,1],[1,1]],[[0,0],[0,0]]],dtype=np.float32),
                dims=["time","y","x"],coords={
                    "time":pd.date_range("2026-11-01",periods=3),
                    "y":[0,1],"x":[0,1],
                })
            xr.Dataset({"pr":field}).to_netcdf(work/"pr.nc")
            masks={
                "Deutschland":np.ones((2,2),dtype=bool),
                "Hessen":np.array([[True,False],[False,False]]),
            }
            with patch.object(provisional,"load_states",return_value={}),\
                 patch.object(provisional,"build_masks",return_value=masks),\
                 patch.object(provisional,"COMBINED",{}):
                data=provisional.build(root,work)
            self.assertEqual(data["data_through"],"2026-11-03")
            self.assertEqual(data["days_observed"],3)
            self.assertFalse(data["forecast"])
            self.assertEqual(data["areas"]["Deutschland"]["temp"],7)
            self.assertEqual(data["areas"]["Deutschland"]["rain"],3.5)
            self.assertEqual(data["areas"]["Hessen"]["rain"],2.0)


if __name__=="__main__":
    unittest.main()
