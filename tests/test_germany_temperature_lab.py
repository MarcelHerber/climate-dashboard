import sys,unittest
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from build_germany_temperature_lab import windows,url
class TestGermany(unittest.TestCase):
    def test_day_window(self):
        c=datetime(2026,11,24,0,tzinfo=timezone.utc)
        n=datetime(2026,11,24,4,tzinfo=timezone.utc)
        self.assertEqual(windows(c,n,"tmax"),[("2026-11-24",6,18),("2026-11-25",30,42)])
    def test_night_window(self):
        c=datetime(2026,11,24,12,tzinfo=timezone.utc)
        n=datetime(2026,11,24,15,tzinfo=timezone.utc)
        self.assertEqual(windows(c,n,"tmin"),[("2026-11-25",6,18),("2026-11-26",30,42)])
    def test_no_incomplete_window(self):
        c=datetime(2026,11,24,12,tzinfo=timezone.utc)
        n=datetime(2026,11,24,19,tzinfo=timezone.utc)
        self.assertEqual(windows(c,n,"tmin"),[("2026-11-26",30,42)])
    def test_url(self):
        c=datetime(2026,11,24,12,tzinfo=timezone.utc)
        self.assertTrue(url(c,18,"tmin").endswith("2026112412_018_2d_tmin_2m.grib2.bz2"))
if __name__=="__main__":unittest.main()
