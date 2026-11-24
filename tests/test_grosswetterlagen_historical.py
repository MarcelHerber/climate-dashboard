import calendar
import unittest
from datetime import date
from scripts.update_grosswetterlagen_historical import parse_layout, MONTHS, CODES

class HistoricalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines=[]
        for month in range(1,13):
            cls.lines.append(next(k for k,v in MONTHS.items() if v==month))
            for year in range(1881,2010):
                n=calendar.monthrange(year,month)[1]
                types=sorted(CODES)
                codes=[types[(year+month+d)%len(types)] for d in range(n)]
                if month==1 and year==1881: codes[0]="HM"
                if month==1 and year==1882: codes[0]="WA"
                cls.lines.append(f"{year}  {' '.join(codes)}  {year}")
    def test_full_coverage(self):
        rows=parse_layout("\n".join(self.lines))
        self.assertEqual(len(rows),47116)
        self.assertIn(date(2000,2,29),rows)
        self.assertEqual(rows[date(1881,1,1)],"HM")
    def test_missing_row(self):
        with self.assertRaises(ValueError): parse_layout("\n".join(self.lines[:3]+self.lines[4:]))
    def test_duplicate_row(self):
        with self.assertRaises(ValueError): parse_layout("\n".join(self.lines[:2]+self.lines[1:]))
    def test_unknown_code(self):
        lines=self.lines.copy()
        lines[1]=lines[1].replace("HM","INVALID",1)
        with self.assertRaises(ValueError): parse_layout("\n".join(lines))

    def test_rotated_page_number_in_margin(self):
        lines=self.lines.copy()
        # Detached digits as well as a page number merged into a year label.
        for idx, prefix, suffix in [(22,"1 0 5 ",""),(67,"105",""),(112,""," 1 0 7")]:
            self.assertRegex(lines[idx],r"^\d{4}")
            lines[idx]=prefix+lines[idx]+suffix
        rows=parse_layout("\n".join(lines))
        self.assertEqual(rows,parse_layout("\n".join(self.lines)))
