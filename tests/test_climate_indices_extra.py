import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from update_climate_indices_extra import (parse_tele,parse_year_matrix,parse_gbi,parse_mjo)

class ExtraIndexTest(unittest.TestCase):
    def test_cpc_fixed_width_tele_noaa_missing(self):
        input_text=("1950  1   0.56 -2.71 -1.69  0.91 -3.65  2.29  0.78  0.55 -0.71-99.90 86.0\n"
                    "1950  2   0.01  0.66 -1.36 -1.13 -1.69 -0.57 -0.94 -1.07 1.25-99.90 58.6\n")*460
        # Dict preserves repeated labels, but input has the right NOAA columns.
        t=parse_tele(input_text)
        self.assertEqual(t["ea"][0],["1950-01",-2.71])
        self.assertEqual(t["eawr"][0],["1950-01",2.29])
        self.assertEqual(t["scand"][1],["1950-02",-0.94])
    def test_cpc_soi_monthly_matrix(self):
        m="YEAR JAN FEB\n"+"\n".join(
            f"{y} "+(" ".join("2.5" for _ in range(12)))
            for y in range(1951,2027))
        v=parse_year_matrix(m,1951,15,"SOI")
        self.assertEqual(v[0],["1951-01",2.5])
        self.assertEqual(v[-1],["2026-12",2.5])
        self.assertEqual(len(v),912)
    def test_gbi_monthly_from_daily_standardized(self):
        from datetime import date,timedelta
        first=date(1948,1,1);last=date(2026,1,1)
        rows=[]
        x=first
        while x<last:
            rows.append(f"{x.year} {x.month} {x.day} {5300+(x.year-1981)*3+x.month}")
            x+=timedelta(days=1)
        # Add a sufficiently long later period for validation
        x=last
        while x<date(2027,1,1):
            rows.append(f"{x.year} {x.month} {x.day} 5450")
            x+=timedelta(days=1)
        g=parse_gbi("\n".join(rows))
        self.assertTrue(len(g)>=750)
        self.assertEqual(g[0][0],"1948-01")
    def test_mjo_bom_fields_and_missing(self):
        from datetime import date,timedelta
        start=date(1974,6,1);lines=[]
        for i in range(17600):
            d=start+timedelta(days=i)
            lines.append(f"{d.year} {d.month} {d.day} 1.0 0.0 4 1.0 WHE")
        r=parse_mjo("\n".join(lines))
        self.assertEqual(r[0],["1974-06-01",1.0,0.0,4,1.0])
        self.assertTrue(len(r)>17000)
if __name__=="__main__":unittest.main()
