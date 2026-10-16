import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import update_synoptic_original_charts as charts

NOW=datetime(2026,10,16,10,tzinfo=timezone.utc)


class OriginalSynopticChartTests(unittest.TestCase):
    def test_dwd_dated_validity_and_strict_kind(self):
        html="""<a href="Z__C_EDZW_20261016043000_tka01%2Cana_bwkman_dwdna_O_000000_000000_202610160000_WV12.png">png</a>
<a href="Z__C_EDZW_20261016043000_tka01%2Cana_bwkman_dwdna_O_000000_000000_202610160000_WV12SW.png">B&amp;W</a>
<a href="Z__C_EDZW_LATEST_tka01%2Cana_bwkman_dwdna_O_000000_000000_LATEST_WV12.png">latest</a>
<a href="Z__C_EDZW_20261015181000_tka01%2Cana_bwkman_dwdna_O_000000_000000_202610151200_WV12.png">png</a>"""
        out=charts.extract_dwd(html,NOW)
        self.assertEqual(len(out),2)
        self.assertEqual(out[0]["valid_utc"],"2026-10-16T00:00+00:00")
        self.assertEqual(out[0]["kind"],"Analyse")

    def test_aemet_compute_true_validity_from_issue_plus_lead(self):
        html="""<img src="/imagenes_d/eltiempo/prediccion/mapa_frentes/2026101512%2B024_ww_g1x0a2d1.gif">
<img src="/imagenes_d/eltiempo/prediccion/mapa_frentes/2026101600%2B000_ww_gpx0a000.gif">
<img src="/imagenes_d/eltiempo/prediccion/mapa_frentes/2026101500%2B036_ww_g1x0a2d1.gif">"""
        out=charts.extract_aemet(html,NOW)
        by_day={p["valid_utc"]:p for p in out}
        self.assertEqual(by_day["2026-10-16T12:00+00:00"]["forecast_hours"],24)
        self.assertEqual(by_day["2026-10-16T12:00+00:00"]["issued_utc"],"2026-10-15T12:00+00:00")
        self.assertEqual(by_day["2026-10-16T00:00+00:00"]["kind"],"Analyse")

    def test_foreign_hosts_cannot_be_recorded(self):
        html='<img src="https://evil.example/imagenes_d/eltiempo/prediccion/mapa_frentes/2026101600%2B000_ww_gpx0a000.gif">'
        self.assertFalse(charts.extract_aemet(html,NOW))
        html='<a href="https://evil.example/ana_bwkman_dwdna_202610160000_WV12.png">A</a>'
        self.assertFalse(charts.extract_dwd(html,NOW))

    def test_noaa_opc_exact_valid_time_from_dated_archive(self):
        html='''<a href="atle_sfcanal_00.2026101602.gif">00 UTC</a>
<a href="atle_sfcanal_06.2026101608.gif">06 UTC</a>
<a href="atle_sfcanal_12.2026101614.gif">12 UTC</a>
<a href="atle_sfcanal_00.2026101603.gif">reissued at 03 UTC</a>
<a href="atlw_sfcanal_00.2026101602.gif">wrong region</a>
<a href="https://evil.example/atle_sfcanal_00.2026101602.gif">wrong host</a>
<a href="atle_sfcanal_18.2026101520.gif">previous day</a>'''
        parsed=charts.extract_opc(html,NOW)
        self.assertEqual(len(parsed),3)  # Future 12 UTC analysis must not appear at 10 UTC
        by_valid={r["valid_utc"]:r for r in parsed}
        self.assertEqual(by_valid["2026-10-16T00:00+00:00"]["issued_utc"],"2026-10-16T03:00+00:00")
        self.assertEqual(by_valid["2026-10-16T06:00+00:00"]["kind"],"Analyse")
        self.assertIn("2026-10-15T18:00+00:00",by_valid)
        self.assertTrue(all(r["source_id"]=="noaa_opc" for r in parsed))

    def test_noaa_opc_rejects_issue_hour_as_validity(self):
        html='<a href="atle_sfcanal_00.2026101602.gif">latest</a>'
        only=charts.extract_opc(html,NOW)
        self.assertEqual(only[0]["valid_utc"],"2026-10-16T00:00+00:00")
        self.assertNotEqual(only[0]["issued_utc"],only[0]["valid_utc"])

    def test_noaa_opc_license_and_external_services(self):
        sources={s["id"]:s for s in charts.SOURCES}
        self.assertEqual(sources["noaa_opc"]["type"],"auto")
        self.assertEqual(sources["eccc"]["type"],"external")
        self.assertEqual(sources["metoffice"]["type"],"external")

    def test_met_office_not_auto_scraped(self):
        providers={x["id"]:x for x in charts.SOURCES}
        self.assertEqual(providers["metoffice"]["type"],"external")
        self.assertEqual(providers["chmi"]["type"],"external")

    def test_no_time_rounding(self):
        v1=datetime(2026,10,16,0,tzinfo=timezone.utc).isoformat(timespec="minutes")
        v2=datetime(2026,10,16,6,tzinfo=timezone.utc).isoformat(timespec="minutes")
        self.assertNotEqual(v1,v2)


if __name__=="__main__":
    unittest.main()
