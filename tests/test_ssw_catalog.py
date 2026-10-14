import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_ssw_catalog as ssw


def wind_season(year=2020):
    first, last = date(year,10,31), date(year+1,4,30)
    d, result = first, {}
    while d<=last:
        result[d]=20.0
        d += timedelta(days=1)
    return result


def reverse(wind, start, duration):
    for k in range(duration):
        wind[start+timedelta(days=k)] = -8.0


class SSWCatalogTests(unittest.TestCase):
    def test_nasa_parser_ignores_forecasts(self):
        rows = ("2021-01-04 12 1 2 3 4 5 6 7\n"
                "2021-01-05 -8 1 2 3 4 5 6 7 0\n"
                "2021-01-06 -9 1 2 3 4 5 6 7 24\n")
        data=ssw.parse_nasa(rows)
        self.assertEqual(data[date(2021,1,5)], -8)
        self.assertNotIn(date(2021,1,6), data)

    def test_classifies_major_after_recovery(self):
        wind=wind_season()
        reverse(wind,date(2021,1,5),6)
        season,events,final=ssw.classify(2020,wind,date(2021,5,1))
        self.assertEqual(season["status"],"complete")
        self.assertEqual([e["date"] for e in events],["2021-01-05"])
        self.assertEqual(events[0]["return_west_10d"],"2021-01-11")
        self.assertEqual(len(final),0)

    def test_final_warming_is_excluded(self):
        wind=wind_season()
        reverse(wind,date(2021,3,25),37)
        _,events,final=ssw.classify(2020,wind,date(2021,5,1))
        self.assertEqual(len(events),0)
        self.assertEqual(len(final),1)

    def test_20_consecutive_westerlies_required_between_events(self):
        wind=wind_season()
        reverse(wind,date(2021,1,5),5)
        reverse(wind,date(2021,1,19),5)
        reverse(wind,date(2021,2,20),5)
        _,events,_=ssw.classify(2020,wind,date(2021,5,1))
        self.assertEqual([e["date"] for e in events],["2021-01-05","2021-02-20"])

    def test_missing_days_prevent_false_confirmations(self):
        wind=wind_season()
        reverse(wind,date(2021,1,5),5)
        del wind[date(2021,2,1)]
        season,events,final=ssw.classify(2020,wind,date(2021,5,1))
        self.assertEqual(season["status"],"incomplete")
        self.assertEqual(events,[])
        self.assertEqual(final,[])

    def test_only_missing_feb29_does_not_discard_winter(self):
        wind = wind_season(2019)
        del wind[date(2020,2,29)]
        reverse(wind,date(2020,1,10),5)
        season,events,_=ssw.classify(2019,wind,date(2020,5,1))
        self.assertEqual(season["status"],"leap_gap")
        self.assertEqual(len(events),1)
        self.assertTrue(season["missing_feb29"])

    def test_ongoing_season_not_confirmed(self):
        wind=wind_season(2026)
        season,events,_=ssw.classify(2026,wind,date(2026,12,1))
        self.assertEqual(season["status"],"in_progress")
        self.assertEqual(events,[])


if __name__=="__main__":
    unittest.main()
