"""CDS daily freshness safeguards: use real data, preserve already-verified days."""
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_era5_stratosphere as wind
import update_era5_stratosphere_stage2 as polar


class StratosphereFreshnessTests(unittest.TestCase):
    def test_candidate_cutoff_d5_is_only_a_probe(self):
        with patch.object(wind, "datetime") as clock:
            clock.now.return_value = datetime(2026, 11, 13, tzinfo=timezone.utc)
            self.assertEqual(wind.last_available_date(), date(2026, 11, 8))

    def test_newest_days_are_individual_not_a_mixed_unavailable_chunk(self):
        chunks = wind.daily_chunks(2026, 11, 8,
                                    current=True, cutoff=date(2026, 11, 8))
        self.assertEqual(chunks, [[8], [7], [6], [1, 2, 3, 4, 5]])
        self.assertEqual(wind.daily_chunks(1991, 1, 11), [
            list(range(1, 12))])

    def test_wind_unpublished_d5_does_not_block_d6_and_d7(self):
        requested = []
        saved = []

        def retrieve(client, year, month, days, levels=(10, 30, 50, 100)):
            requested.append(tuple(days))
            if tuple(days) == (8,):
                raise RuntimeError(
                    "None of the data you have requested is available yet. "
                    "The latest date available for this dataset is: 2026-11-07")
            return {
                f"{year}-{month:02d}-{d:02d}": {
                    "date": f"{year}-{month:02d}-{d:02d}",
                    **{f"u60_{level}": 20.0 for level in levels}
                } for d in days
            }

        prior = [{"date": "2026-11-05", "u60_10": 19.0}]
        with patch.object(wind, "last_available_date", return_value=date(2026, 11, 8)), \
             patch.object(wind, "read_rows", return_value=prior), \
             patch.object(wind, "retrieve_wind_chunk", side_effect=retrieve), \
             patch.object(wind, "store_rows", side_effect=lambda year, rows: saved.append(rows)):
            count = wind.update_year(None, 2026, current=True, max_chunks=2)

        self.assertEqual(requested[:3], [(8,), (7,), (6,)])
        self.assertEqual(count, 3)
        self.assertEqual({row["date"] for row in saved[-1]}, {
            "2026-11-05", "2026-11-06", "2026-11-07"})
        self.assertFalse(any(row["date"] == "2026-11-08" for row in saved[-1]))

    def test_polar_unpublished_d5_does_not_block_d6(self):
        requests = []
        stores = []

        def retrieve(client, year, month, days, group):
            requests.append((tuple(days), group[2]))
            if days == [8]:
                raise RuntimeError("The latest date available for this dataset is 2026-11-07")
            stamp = f"{year}-{month:02d}-{days[0]:02d}"
            if group[2] == "t":
                values = {f"tcap_{level}": -50.0 for level in group[1]}
            elif group[2] == "z":
                values = {"zcap_10": 31000.0, "wave1_10": 12.0, "wave2_10": 6.0}
            else:
                values = {"o3cap_50": 4.0}
            return {stamp: {"date": stamp, **values}}

        with patch.object(wind, "last_available_date", return_value=date(2026, 11, 8)), \
             patch.object(wind, "read_rows", return_value=[]), \
             patch.object(polar, "retrieve_chunk", side_effect=retrieve), \
             patch.object(wind, "store_rows", side_effect=lambda year, rows: stores.append(rows)):
            chunks = polar.update_year_polar(None, 2026, current=True, max_chunks=1)

        self.assertEqual(chunks, 1)
        self.assertEqual(requests[0], ((8,), "t"))
        self.assertEqual(requests[1], ((7,), "t"))
        self.assertEqual({row["date"] for row in stores[-1]}, {"2026-11-07"})
        self.assertEqual(stores[-1][0]["tcap_10"], -50.0)

    def test_transient_errors_are_not_treated_as_unpublished_data(self):
        self.assertTrue(wind.cds_day_unavailable(
            RuntimeError("None of the data you have requested is available yet")))
        self.assertFalse(wind.cds_day_unavailable(RuntimeError("503 Service Unavailable")))
        self.assertFalse(wind.cds_day_unavailable(RuntimeError("Connection timed out")))


if __name__ == "__main__":
    unittest.main()
