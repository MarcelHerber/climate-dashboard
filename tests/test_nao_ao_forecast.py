"""Contract checks for the NOAA/CPC forecast schema and ensemble statistics."""
from __future__ import annotations

import csv
import io
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from scripts.update_nao_ao_forecast import (
    SOURCE, build, parse_model_csv, percentile, summarize_run,
)


def fixture(index="nao", model="gefs", count=8, end=date(2026, 11, 11)):
    output = io.StringIO()
    fields = ["lead"] + (["member"] if model == "gefs" else []) + ["time", f"{index}_index", "valid_time"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for shift in range(count):
        day = end - timedelta(days=shift)
        for lead in range(16):
            for member in range(31 if model == "gefs" else 1):
                row = {
                    "lead": lead, "time": day.isoformat(),
                    f"{index}_index": (member - 15) / 15 + lead * .01 if model == "gefs" else 0.7,
                    "valid_time": (day + timedelta(days=lead)).isoformat(),
                }
                if model == "gefs":
                    row["member"] = member
                writer.writerow(row)
    return output.getvalue()


class ForecastTest(unittest.TestCase):
    def test_cpc_csv_column_format_exact(self):
        rows = parse_model_csv(fixture(), "nao", "gefs")
        self.assertIn("2026-11-11", rows)
        self.assertEqual(len(rows["2026-11-11"][15]), 31)
        self.assertEqual(len(parse_model_csv(fixture(model="gfs"), "nao", "gfs")["2026-11-11"][0]), 1)

    def test_reject_malformed_valid_date(self):
        text = "lead,member,time,nao_index,valid_time\n1,0,2026-11-11,2.0,2026-11-11\n"
        with self.assertRaises(ValueError):
            parse_model_csv(text, "nao", "gefs")

    def test_quantiles(self):
        self.assertEqual(percentile([0., 10.], .1), 1.)
        self.assertEqual(percentile([0., 10.], .9), 9.)

    def test_mean_probability_and_member_count(self):
        run = parse_model_csv(fixture(count=1), "nao", "gefs")["2026-11-11"]
        result = summarize_run("2026-11-11", run, full=True)
        self.assertEqual(result["member_count"], [31] * 16)
        self.assertAlmostEqual(result["mean"][0], 0)
        self.assertAlmostEqual(result["probability"]["positive"][0], round(100 * 16 / 31, 1))
        self.assertAlmostEqual(result["probability"]["negative"][0], round(100 * 15 / 31, 1))
        self.assertEqual(len(result["members"]), 31)
        self.assertEqual(result["valid_dates"][15], "2026-11-26")

    def test_incomplete_run_is_rejected_not_filled(self):
        run = parse_model_csv(fixture(count=1), "nao", "gefs")["2026-11-11"]
        run[9] = {0: 0.5}
        with self.assertRaises(ValueError):
            summarize_run("2026-11-11", run, full=True)

    def test_build_uses_real_source_columns_and_run_history(self):
        inputs = {}
        for index in ("nao", "ao"):
            for model in ("gefs", "gfs"):
                inputs[SOURCE[index][model]] = fixture(index, model)
            inputs[SOURCE[index]["obs"]] = "not used here"
        with patch("scripts.update_nao_ao_forecast.parse_observations", return_value=[
            ["2026-11-10", -.4], ["2026-11-11", -.3]
        ]):
            result = build(fetch=inputs.__getitem__, today=date(2026, 11, 12))
        self.assertTrue(result["ready"])
        self.assertEqual(result["indices"]["nao"]["latest"]["gfs"]["init_date"], "2026-11-11")
        self.assertEqual(len(result["indices"]["ao"]["previous_runs"]), 7)

    def test_stale_gefs_is_not_published(self):
        inputs = {}
        for index in ("nao", "ao"):
            for model in ("gefs", "gfs"):
                inputs[SOURCE[index][model]] = fixture(index, model, end=date(2026, 10, 1))
            inputs[SOURCE[index]["obs"]] = "not used"
        with self.assertRaisesRegex(RuntimeError, "zu alt"):
            build(fetch=inputs.__getitem__, today=date(2026, 11, 12))


if __name__ == "__main__":
    unittest.main()
