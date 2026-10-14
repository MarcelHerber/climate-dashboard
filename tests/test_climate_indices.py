"""NOAA CPC atmospheric indices: no fabricated observations or incomplete months."""
import importlib.util
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1] / "scripts/update_climate_indices.py"
spec=importlib.util.spec_from_file_location("update_climate_indices",SCRIPT)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NOAAIndicesTests(unittest.TestCase):
    def test_daily_csv_formats_and_missing(self):
        first="1950-01-01, -1.25\n1950-01-02, -99.0\n1950-01-03, 0.50\n"
        def short_parse(text):
            # Validation needs >=25000 readings: pad using real calendar days
            start=date(1950,1,4)
            extra="\n".join((start+timedelta(days=i)).isoformat()+",0.25" for i in range(28000))
            return mod.parse_daily_csv(text+extra+"\n", "AO")
        rows=short_parse(first)
        self.assertEqual(rows[0],["1950-01-01",-1.25])
        self.assertEqual(rows[1],["1950-01-03",0.5])
        self.assertTrue(rows[-1][0]>"2026-01-01")
        iso_rows=short_parse("year,month,day,AO\n1950,1,1,-0.75\n")
        self.assertEqual(iso_rows[0],["1950-01-01",-0.75])

    def test_season_labels_and_onset(self):
        txt="SEAS YR ANOM\n"
        for y in range(1950,2027):
            for season in mod.SEASONS:
                txt+=f"{season} {y} 0.5\n"
        out=mod.parse_enso_seasons(txt,"RONI")
        self.assertEqual(out[0],["1950-01","DJF",0.5])
        self.assertEqual(out[11],["1950-12","NDJ",0.5])
        self.assertEqual(out[12],["1951-01","DJF",0.5])
        self.assertEqual(out[-1],["2026-12","NDJ",0.5])

    def test_monthly_gaps_are_not_invented(self):
        daily=[[f"2025-01-{n:02d}", 1.] for n in range(1,31)]
        daily.extend([[f"2025-02-{n:02d}",-1.] for n in range(1,8)])
        months=mod.monthly_means(daily)
        self.assertEqual(months,[["2025-01",1.,30]])

    def test_invalid_values(self):
        self.assertIsNone(mod.number("-999"))
        self.assertIsNone(mod.number("nan"))
        self.assertIsNone(mod.number("not measured"))
        self.assertEqual(mod.number("-1.25"),-1.25)


if __name__=="__main__":
    unittest.main()
