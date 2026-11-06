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


    def test_month_rollover_keeps_november_until_dwd_replacement(self):
        def snapshot(month, last_day, temperature):
            return {
                "schema": 1, "month": month, "data_through": last_day,
                "forecast": False,
                "areas": {"Deutschland": {"temp": temperature, "rain": 4.0}},
            }

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            november_early = snapshot("2026-11", "2026-11-04", 5.94)
            november_late = snapshot("2026-11", "2026-11-30", 5.12)
            december = snapshot("2026-12", "2026-12-02", 3.2)
            provisional.persist_provisional(root, november_early)
            provisional.persist_provisional(root, november_late)
            provisional.persist_provisional(root, december)

            history = json.loads((root / "monthly_provisional_history.json").read_text())
            self.assertEqual([s["month"] for s in history["months"]],
                             ["2026-11", "2026-12"])
            self.assertEqual(history["months"][0]["data_through"], "2026-11-30")
            self.assertEqual(history["months"][0]["areas"]["Deutschland"]["temp"], 5.12)
            self.assertEqual(history["months"][1]["data_through"], "2026-12-02")

            # A delayed older update must not overwrite a newer observation.
            provisional.persist_provisional(root, november_early)
            history = json.loads((root / "monthly_provisional_history.json").read_text())
            self.assertEqual(history["months"][0]["data_through"], "2026-11-30")


    def test_sunshine_enrichment_replaces_equal_day_not_previous_month(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ordinary = {
                "schema": 1, "forecast": False, "month": "2026-12",
                "data_through": "2026-12-01",
                "areas": {"Deutschland": {"temp": 2.5, "rain": 0.3}},
            }
            provisional.persist_provisional(root, ordinary)
            ordinary["areas"]["Deutschland"]["sun"] = 0.4
            provisional.persist_provisional(root, ordinary)
            history = json.loads((root / "monthly_provisional_history.json").read_text())
            self.assertEqual(history["months"][0]["areas"]["Deutschland"]["sun"], 0.4)


if __name__=="__main__":
    unittest.main()
