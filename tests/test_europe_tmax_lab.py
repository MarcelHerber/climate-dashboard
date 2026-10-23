"""Offline integrity tests for private Europe Tmax (genuine 06–18 UTC extrema)."""
import io
import sys
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_europe_tmax_lab as app


def synthetic_kmz():
    times=["2026-10-24T06:00:00Z","2026-10-24T12:00:00Z",
           "2026-10-24T18:00:00Z","2026-10-25T18:00:00Z",
           "2026-10-26T18:00:00Z","2026-10-27T18:00:00Z",
           "2026-10-28T18:00:00Z"]
    steps="".join(f"<dwd:TimeStep>{t}</dwd:TimeStep>" for t in times)
    points=[]
    # More than 100 actual station-shaped records; only those near reference
    # cities may be assigned to their labels. No interpolation is permitted.
    city_points=app.CITIES[:25]
    for i in range(110):
        city,lon,lat=city_points[i % len(city_points)]
        sid=f"S{i:04d}"
        offset=i//len(city_points)
        values=f"- - {286.15+offset} {285.15+offset} 280.15 278.15 276.15"
        points.append(
          f'<Placemark><name>{sid}</name><description>STATION {i}</description>'
          f'<Point><coordinates>{lon+offset*.03},{lat+offset*.03},30</coordinates></Point>'
          f'<ExtendedData><dwd:Forecast dwd:elementName="TX">'
          f'<dwd:value>{values}</dwd:value></dwd:Forecast></ExtendedData></Placemark>'
        )
    xml=(
        '<kml xmlns:dwd="https://opendata.dwd.de/weather/lib/pointforecast_dwd_extension_V1_0.xsd">'
        '<Document><dwd:IssueTime>2026-10-23T09:00:00Z</dwd:IssueTime>'
        '<dwd:ForecastTimeSteps>'+steps+'</dwd:ForecastTimeSteps>'
        + "".join(points) + '</Document></kml>'
    )
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("original.kml",xml)
    return buffer.getvalue()


class EuropeTmaxTests(unittest.TestCase):
    def test_icon_main_cycle_five_days(self):
        run=datetime(2026,10,23,0,tzinfo=timezone.utc)
        self.assertTrue(app.icon_url(run,114).endswith(
            "_2026102300_114_TMAX_2M.grib2.bz2"))
        self.assertEqual([i*24+18 for i in range(5)],[18,42,66,90,114])
        self.assertEqual((run.isoformat()),"2026-10-23T00:00:00+00:00")

    def test_real_mos_tx_18utc_nested_kml(self):
        dates=["2026-10-24","2026-10-25","2026-10-26","2026-10-27","2026-10-28"]
        issue,points=app.daily_mos_values(synthetic_kmz(),dates)
        self.assertEqual(issue,"2026-10-23T09:00:00Z")
        self.assertGreaterEqual(len(points),18)
        oslo=next(p for p in points if p["city"]=="Oslo")
        self.assertEqual(oslo["station_id"],"S0003")
        self.assertAlmostEqual(oslo["tx"]["2026-10-24"],13.0,places=1)
        self.assertNotIn("2026-10-23",oslo["tx"])
        self.assertLessEqual(oslo["distance_km"],app.MAX_DISTANCE_KM)
        self.assertEqual(len({p["station_id"] for p in points}),len(points))

    def test_temperature_colours_and_explicit_output_grid(self):
        self.assertEqual(app.STOPS[0][0],-35)
        self.assertEqual(app.STOPS[-1][0],45)
        self.assertEqual(app.WIDTH,609)
        self.assertEqual(app.HEIGHT,369)
        self.assertEqual(len(app.CITIES)>25,True)

if __name__=="__main__":
    unittest.main()
