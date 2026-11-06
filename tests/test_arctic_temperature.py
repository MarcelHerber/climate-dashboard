"""Offline tests for DMI +80N temperature indexing, leap dates and anomalies."""
from __future__ import annotations
from datetime import date, timedelta
import io
import math
import sys
import tarfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_arctic_temperature as dmi


def lines(year: int, temp: float = 248.15):
    start = date(year, 1, 1)
    days = (date(year + 1, 1, 1) - start).days
    return "Date Day of year Temp\n" + "\n".join(
        f"{(start + timedelta(days=i)):%Y%m%d} {i+1} {temp + 5*math.sin(i/40):.6f}"
        for i in range(days)
    ) + "\n"


def archive(first=1958, last=2002):
    buff = io.BytesIO()
    with tarfile.open(fileobj=buff, mode="w") as tar:
        for year in range(first, last + 1):
            # Historical DMI archive may contain an extra fourth baseline column.
            payload = lines(year).replace("248.15", "248.15").encode("utf-8")
            info = tarfile.TarInfo(f"temp_clim_plus80_{year}.txt")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return buff.getvalue()


class ArcticTemperatureTests(unittest.TestCase):
    def test_running_format_and_conversion(self):
        value = dmi.parse_daily("Date Day of year Temp\n20260101 1 249.319931\n"
                                "20260102 2 248.064682\n", 2026)
        self.assertAlmostEqual(value["01-01"], -23.830069, places=3)
        self.assertIn("01-02", value)

    def test_reject_wrong_day_number_and_outliers(self):
        vals = dmi.parse_daily("20260101 2 249\n20260102 2 999\n"
                               "20260103 3 250.000\n", 2026)
        self.assertEqual(list(vals), ["01-03"])

    def test_archive_and_reference(self):
        history = dmi.archive_years(archive())
        self.assertEqual(len(history), 45)
        self.assertIn("02-29", history[1960])
        self.assertNotIn("02-29", history[1959])
        reference, counts = dmi.reference_series(history)
        self.assertEqual(len(reference), 366)
        self.assertEqual(counts[dmi.DAYS.index("02-29")], 11)
        self.assertIsNotNone(reference[dmi.DAYS.index("02-29")])

    def test_build_calendar_alignment_and_latest_date(self):
        result = dmi.build(archive(), {
            2026: lines(2026, temp=258.15).encode("utf-8")
        }, now=date(2026, 11, 6))
        self.assertEqual(result["reference"]["label"], "DMI/ERA-40 1958–2002")
        self.assertEqual(len(result["years"]["1959"]), 366)
        leap = dmi.DAYS.index("02-29")
        self.assertIsNone(result["years"]["1959"][leap])
        self.assertIsNotNone(result["years"]["1960"][leap])
        self.assertIsNone(result["years"]["2026"][dmi.DAYS.index("11-07")])
        self.assertEqual(result["last_date"], "2026-11-06")
        self.assertFalse("forecast" in result)

    def test_missing_archive_fails_loudly(self):
        with self.assertRaises(RuntimeError):
            dmi.archive_years(archive(1958, 1960))


if __name__ == "__main__":
    unittest.main()
