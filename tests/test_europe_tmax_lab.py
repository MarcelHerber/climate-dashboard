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
    def test_encoded_temperature_raw_raster(self):
        import numpy as np
        original=np.array([-35.5,-10.0,0.0,23.7,44.9,np.nan],dtype=np.float32)
        data=app.encode_temperature_rgba(original)
        self.assertEqual(data.shape,(6,4))
        self.assertEqual(list(data[:,3]),[255,255,255,255,255,0])
        reconstructed=(data[:5,0].astype(int)*256+data[:5,1].astype(int))/10-100
        np.testing.assert_allclose(reconstructed,original[:5],atol=.05)
        self.assertEqual(data[5,:].tolist(),[0,0,0,0])

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
        self.assertEqual(oslo["station_id"],"S0004")
        self.assertAlmostEqual(oslo["tx"]["2026-10-24"],13.0,places=1)
        self.assertNotIn("2026-10-23",oslo["tx"])
        self.assertLessEqual(oslo["distance_km"],app.MAX_DISTANCE_KM)
        issue2,selected2,catalog=app.daily_mos_values(synthetic_kmz(),dates,include_catalog=True)
        self.assertEqual(issue2,issue)
        self.assertEqual(len(selected2),31)
        self.assertEqual(len(catalog),110)
        self.assertTrue(all(item["tx"].get("2026-10-24") is not None for item in catalog))
        self.assertEqual(len(points),31)
        present=[p for p in points if p["station_id"] is not None]
        self.assertEqual(len({p["station_id"] for p in present}),len(present))
        syktywkar=next(p for p in points if p["city"]=="Syktywkar")
        self.assertIsNotNone(syktywkar["station_id"])
        island=next(p for p in points if p["city"]=="Kanaren")
        self.assertIsNone(island["station_id"])
        self.assertEqual(island["tx"],{})

    def test_temperature_colours_and_explicit_output_grid(self):
        self.assertEqual(app.STOPS[0][0],-35)
        self.assertEqual(app.STOPS[-1][0],45)
        self.assertEqual(app.WIDTH,729)
        self.assertEqual(app.HEIGHT,369)
        # Exact places shown on the supplied reference map, without extra cities.
        self.assertEqual(tuple(city for city, _, _ in app.CITIES), (
            "Reykjavík",            "Rovaniemi",            "Syktywkar",            "Helsinki",            "Oslo",
            "Stockholm",            "Moskau",            "Minsk",            "Wolgograd",            "Dublin",
            "London",            "Warschau",            "Kiew",            "Frankfurt",            "Wien",
            "Paris",            "Bordeaux",            "Nizza",            "Belgrad",            "Varna",
            "Ankara",            "Lissabon",            "Madrid",            "Sevilla",            "Rom",
            "Palermo",            "Athen",            "Antalya",            "Algier",            "Azoren",
            "Kanaren",
        ))
        self.assertEqual(len(app.CITIES),31)
        self.assertEqual(len({name for name,_,_ in app.CITIES}),31)
        self.assertGreater(app.LON_MAX,50.82)  # Syktywkar must be on the map
        self.assertLess(app.LON_MIN,-25.67)  # Azores on source grid
        self.assertLess(app.LAT_MIN,28.29)  # Canary Islands on source grid

if __name__=="__main__":
    unittest.main()
