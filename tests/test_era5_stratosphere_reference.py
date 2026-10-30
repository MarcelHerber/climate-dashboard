"""Offline checks: strict 1991–2020 ERA5 wind/temperature reference.

No network calls or fabricated values enter the published data archive.
"""
import calendar
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_era5_stratosphere as app


class StratosphereReferenceTests(unittest.TestCase):
    def test_temperature_only_year_cannot_be_counted_as_wind_complete(self):
        rows = [{"date": (date(1991,1,1)+timedelta(days=i)).isoformat(),
                 **{f"tcap_{p}": -55. for p in (10,30,50,100)}}
                for i in range(365)]
        self.assertTrue(app.full_year_coverage(1991,rows,
                        tuple(f"tcap_{p}" for p in (10,30,50,100))))
        self.assertFalse(app.full_year_coverage(1991,rows,
                         tuple(f"u60_{p}" for p in (10,30,50,100))))
        with patch.object(app, "read_rows", return_value=rows):
            self.assertEqual(app.choose_backfill_year(),1991)

    def test_leap_year_and_missing_date_rejected(self):
        values=[{"date": (date(2000,1,1)+timedelta(days=i)).isoformat(),
                 "u60_10":10.0} for i in range(366)]
        self.assertTrue(app.full_year_coverage(2000,values,("u60_10",)))
        self.assertFalse(app.full_year_coverage(2000,values[:-1],("u60_10",)))
        values[-1]["u60_10"]=float("nan")
        self.assertFalse(app.full_year_coverage(2000,values,("u60_10",)))

    def test_reference_climatology_never_uses_partial_sample(self):
        rows={}
        for year in range(1991,2021):
            rows[year]=[{"date":f"{year}-01-01","tcap_10":-50.0}]
            if calendar.isleap(year):
                rows[year].append({"date":f"{year}-02-29","tcap_10":-45.0})
        reference=app.reference_climatology(rows)
        self.assertEqual(set(reference["tcap_10"]),{"01-01","02-29"})
        self.assertEqual(reference["tcap_10"]["01-01"]["mean"],-50.0)
        rows[2000]=[r for r in rows[2000] if r["date"]!="2000-02-29"]
        reference=app.reference_climatology(rows)
        self.assertEqual(set(reference["tcap_10"]),{"01-01"})

if __name__ == "__main__":
    unittest.main()
