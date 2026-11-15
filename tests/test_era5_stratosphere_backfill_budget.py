"""Budget guards for resumable ERA5 backfills; never fetch from CDS in tests."""
import sys
import tempfile
import unittest
import calendar
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_era5_stratosphere as wind
import update_era5_stratosphere_stage2 as temperature


class BackfillBudgetTests(unittest.TestCase):
    def test_reference_backfills_across_years_with_one_shared_chunk_limit(self):
        def fake_wind(client, year, month, days, levels=(10,30,50,100)):
            return {f"{year}-{month:02d}-{day:02d}": {
                "date": f"{year}-{month:02d}-{day:02d}",
                **{f"u60_{level}": 20.0 for level in levels}}
                for day in days}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(wind, "HISTORY", Path(directory)), \
             patch.object(wind, "retrieve_wind_chunk", side_effect=fake_wind):
            rows = [{"date": (date(1991,1,1)+timedelta(days=i)).isoformat(),
                     **{f"u60_{p}": 11.0 for p in (10,30,50,100)}}
                    for i in range(364)]
            rows.append({"date":"1991-12-31", "u60_10":-7.25,
                         "tcap_10":-52.0, "ssw_wind_reversal":1})
            wind.store_rows(1991, rows)
            result = wind.backfill_reference_winds(None, max_chunks=2)
            self.assertEqual(result, (2,False,0))
            final = wind.read_rows(1991)[-1]
            self.assertEqual(final["u60_10"],-7.25)
            self.assertEqual(final["ssw_wind_reversal"],1)
            self.assertEqual(final["tcap_10"],-52.0)
            self.assertEqual(final["u60_100"],20.0)
            self.assertEqual(len(wind.read_rows(1992)),31)
            self.assertEqual(wind.read_rows(1993),[])

    def test_reference_time_budget_shared_across_years(self):
        def fake_wind(client, year, month, days):
            return {f"{year}-{month:02d}-{day:02d}": {
                "date":f"{year}-{month:02d}-{day:02d}",
                **{f"u60_{p}": 2.5 for p in (10,30,50,100)}} for day in days}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(wind, "HISTORY", Path(directory)), \
             patch.object(wind, "retrieve_wind_chunk", side_effect=fake_wind), \
             patch.object(wind.time, "monotonic", side_effect=[0,10,70]):
            rows = [{"date":(date(1991,1,1)+timedelta(days=i)).isoformat(),
                     **{f"u60_{p}": 11.0 for p in (10,30,50,100)}} for i in range(364)]
            wind.store_rows(1991, rows)
            self.assertEqual(wind.backfill_reference_winds(None, max_chunks=60, max_minutes=1),
                             (1,False,0))
            self.assertEqual(len(wind.read_rows(1991)),365)
            self.assertEqual(wind.read_rows(1992),[])

    def test_invalid_reference_chunk_is_not_published(self):
        def malformed(client, year, month, days):
            return {f"{year}-{month:02d}-{day:02d}": {
                "date":f"{year}-{month:02d}-{day:02d}",
                "u60_10":True, "u60_30":4.0, "u60_50":4.0, "u60_100":4.0}
                for day in days}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(wind, "HISTORY", Path(directory)), \
             patch.object(wind, "retrieve_wind_chunk", side_effect=malformed):
            self.assertEqual(wind.backfill_reference_winds(None, max_chunks=2), (0,False,1))
            self.assertEqual(wind.read_rows(1991),[])

    def test_extended_budget_requires_actual_complete_temperature_reference(self):
        rows = {year: [{"date": (date(year,1,1)+timedelta(days=i)).isoformat(),
                        **{f"tcap_{p}": -50.0 for p in (10,30,50,100)}}
                       for i in range(366 if calendar.isleap(year) else 365)]
                for year in range(1991,2021)}
        with patch.object(wind, "read_rows", side_effect=rows.get):
            self.assertTrue(wind.temperature_reference_ready())
            rows[2020][-1]["tcap_100"] = True
            self.assertFalse(wind.temperature_reference_ready())

    def test_duplicate_date_cannot_replace_missing_reference_year(self):
        rows={year:[{"date":f"{year}-01-01", "u60_10": 5.0}]
              for year in range(1991,2021)}
        rows[2020]=[]
        rows[1991].append(dict(rows[1991][0]))
        self.assertNotIn("u60_10", wind.reference_climatology(rows))

    def test_push_only_starts_historical_work_for_verified_reference_gap(self):
        rows = {year: [{"date": (date(year,1,1)+timedelta(days=i)).isoformat(),
                        **{f"tcap_{p}": -50.0 for p in (10,30,50,100)},
                        **{f"u60_{p}": 10.0 for p in (10,30,50,100)}}
                       for i in range(366 if calendar.isleap(year) else 365)]
                for year in range(1991,2021)}
        with patch.object(wind, "read_rows", side_effect=rows.get):
            self.assertEqual(wind.historical_wind_budget("push"),0)
            self.assertEqual(wind.historical_wind_budget("schedule"),85)
            del rows[2020][-1]["u60_100"]
            self.assertEqual(wind.historical_wind_budget("push"),200)
            self.assertEqual(wind.historical_wind_budget("workflow_dispatch"),200)
            del rows[2020][-1]["tcap_100"]
            self.assertEqual(wind.historical_wind_budget("push"),0)
            self.assertEqual(wind.historical_wind_budget("schedule"),85)

    def test_wind_stops_after_one_chunk_when_budget_expires(self):
        calls = []
        def fake_wind(client, year, month, days, levels=(10, 30, 50, 100)):
            calls.append((year, month, tuple(days)))
            return {
                f"{year}-{month:02d}-{day:02d}": {
                    "date": f"{year}-{month:02d}-{day:02d}",
                    **{f"u60_{level}": 20.0 for level in levels}
                } for day in days
            }

        with patch.object(wind, "read_rows", return_value=[]), \
             patch.object(wind, "retrieve_wind_chunk", side_effect=fake_wind), \
             patch.object(wind, "store_rows") as store, \
             patch.object(wind.time, "monotonic", side_effect=[0, 10, 70]):
            saved = wind.update_year(None, 1991, max_chunks=60, max_minutes=1)
        self.assertEqual(saved, 31)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], (1991, 1, tuple(range(1, 32))))
        store.assert_called_once()

    def test_temperature_stops_without_losing_verified_records(self):
        plan = [
            (1991, 1, (1, 2, 3, 4, 5), (10, 30, 50, 100)),
            (1992, 1, (1, 2, 3, 4, 5), (10, 30, 50, 100))
        ]
        def fake_temperature(client, year, month, days, group):
            return {
                f"{year}-{month:02d}-{day:02d}": {
                    "date": f"{year}-{month:02d}-{day:02d}",
                    **{f"tcap_{p}": -50.0 for p in group[1]}
                } for day in days
            }
        with patch.object(temperature.base, "read_rows", return_value=[]), \
             patch.object(temperature.base, "store_rows") as store, \
             patch.object(temperature, "climatology_work_plan", return_value=plan), \
             patch.object(temperature, "retrieve_chunk", side_effect=fake_temperature), \
             patch.object(temperature.time, "monotonic", side_effect=[0, 10, 70]):
            done, complete, failures = temperature.backfill_reference_temperatures(
                None, max_chunks=90, max_minutes=1)
        self.assertEqual((done, complete, failures), (1, False, 0))
        store.assert_called_once()
        year, rows = store.call_args.args
        self.assertEqual(year, 1991)
        self.assertEqual(len(rows), 5)

    def test_history_only_requests_missing_days_of_partially_filled_month(self):
        rows = [{"date": f"2006-01-{day:02d}",
                 "tcap_10": -55.0,
                 **{f"u60_{hpa}": 12.0 for hpa in (10,30,50,100)}}
                for day in range(1,31)]
        calls=[]
        def fake_wind(client, year, month, days, levels=(10,30,50,100)):
            calls.append((year,month,tuple(days)))
            return {f"{year}-{month:02d}-{d:02d}":{
                "date":f"{year}-{month:02d}-{d:02d}",
                **{f"u60_{level}":20.0 for level in levels}
            } for d in days}
        with patch.object(wind, "read_rows", return_value=rows), \
             patch.object(wind, "retrieve_wind_chunk", side_effect=fake_wind), \
             patch.object(wind, "store_rows") as store:
            total=wind.update_year(None,2006,max_chunks=1)
        self.assertEqual(total,31)
        self.assertEqual(calls,[(2006,1,(31,))])
        values={row["date"]:row for row in store.call_args.args[1]}
        self.assertEqual(values["2006-01-01"]["tcap_10"],-55.)
        self.assertEqual(values["2006-01-31"]["u60_10"],20.)

    def test_large_monthly_request_splits_on_cds_cost_limit(self):
        calls=[]
        class FakeCDS:
            def retrieve(self, dataset, request, target):
                days=tuple(int(d) for d in request["day"])
                calls.append(days)
                if len(days)>16:
                    raise RuntimeError("CDS cost limits exceeded")
                Path(target).write_bytes(b"fake-non-production-test")
        def read_fake(_,levels,requested):
            return {stamp:{"date":stamp,
                **{f"u60_{lev}":13. for lev in levels}} for stamp in requested}
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(wind, "CACHE", Path(temp)), \
             patch.object(wind, "open_cds_file", return_value=None), \
             patch.object(wind, "_wind_rows_from_dataset", side_effect=read_fake):
            out=wind.retrieve_wind_chunk(FakeCDS(),2007,1,list(range(1,32)))
        self.assertEqual([len(c) for c in calls],[31,15,16])
        self.assertEqual(len(out),31)
        self.assertEqual(out["2007-01-31"]["u60_100"],13.)

    def test_unlimited_wind_chunk_limit_remains_respected(self):
        def fake_wind(client, year, month, days, levels=(10, 30, 50, 100)):
            return {
                f"{year}-{month:02d}-{day:02d}": {
                    "date": f"{year}-{month:02d}-{day:02d}",
                    **{f"u60_{level}": 20.0 for level in levels}
                } for day in days
            }
        with patch.object(wind, "read_rows", return_value=[]), \
             patch.object(wind, "retrieve_wind_chunk", side_effect=fake_wind), \
             patch.object(wind, "store_rows") as store:
            saved = wind.update_year(None, 1991, max_chunks=2, max_minutes=None)
        self.assertEqual(saved, 59)
        self.assertEqual(store.call_count, 2)


if __name__ == "__main__":
    unittest.main()
