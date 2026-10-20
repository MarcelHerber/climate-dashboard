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

    def test_noaa_full_atlantic_date_and_same_office(self):
        html='''<a href="atl00_sfcfcst_00.2026101602.gif">north atlantic 0h</a>
<a href="atl00_sfcfcst_06.2026101608.gif">north atlantic 06h</a>
<a href="atl00_sfcfcst_00.2026101603.gif">reissue</a>
<a href="pac00_sfcfcst_00.2026101602.gif">Pacific ignored</a>'''
        parsed=charts.extract_opc_full(html,NOW)
        self.assertEqual(len(parsed),2)
        self.assertEqual(parsed[0]["source_id"],"noaa_full")
        self.assertEqual(parsed[0]["kind"],"0-h-Bodenkarte")
        self.assertEqual(next(p for p in parsed if p["valid_utc"]=="2026-10-16T00:00+00:00")["issued_utc"],"2026-10-16T03:00+00:00")
        self.assertTrue(all(p["publisher_id"]=="noaa" for p in parsed))
        self.assertEqual({p["source_id"] for p in charts.extract_opc(html,NOW)},set())

    def test_noaa_forecast_leads_use_run_plus_hours_not_issue_clock(self):
        html='''<a href="watl24_sfcfcst_12.2026101617.gif">24h</a>
<a href="atl48_sfcfcst_00.2026101705.gif">48h</a>
<a href="atl96_sfcfcst_12.2026101618.gif">96h</a>
<a href="atl48_sfcfcst_00.2026101722.gif">bad issue delay</a>
<a href="https://evil.example/atl48_sfcfcst_00.2026101705.gif">unsafe</a>'''
        a=charts.extract_opc_24(html,NOW)
        b=charts.extract_opc_48(html,NOW)
        c=charts.extract_opc_96(html,NOW)
        self.assertEqual(a[0]["valid_utc"],"2026-10-17T12:00+00:00")
        self.assertEqual(a[0]["forecast_hours"],24)
        self.assertEqual(b[0]["valid_utc"],"2026-10-19T00:00+00:00")
        self.assertEqual(b[0]["issued_utc"],"2026-10-17T05:00+00:00")
        self.assertEqual(b[0]["run_utc"],"2026-10-17T00:00+00:00")
        self.assertEqual(c[0]["valid_utc"],"2026-10-20T12:00+00:00")
        self.assertEqual(c[0]["forecast_hours"],96)
        self.assertEqual(len(b),1)

    def test_noaa_pacific_independent_regions_but_one_noaa_publisher(self):
        html='''<a href="pace_sfcanal_00.2026101602.gif">Northeast Pacific</a>
<a href="pace_sfcanal_00.2026101604.gif">Northeast Pacific revised</a>
<a href="pacw_sfcanal_00.2026101602.gif">Northwest Pacific</a>
<a href="pacsfc00Z.2026101602.gif">North Pacific hemispheric</a>
<a href="pacw_sfcanal_12.2026101614.gif">future at 10 UTC</a>
<a href="https://evil.invalid/ncdc/pacw_sfcanal_00.2026101602.gif">host spoof</a>
<a href="pace_sfcanal_00.2026100602.gif">stale</a>'''
        east=charts.extract_opc_pace(html,NOW)
        west=charts.extract_opc_pacw(html,NOW)
        hemi=charts.extract_opc_pachemi(html,NOW)
        self.assertEqual(len(east),1)
        self.assertEqual(len(west),1)
        self.assertEqual(len(hemi),1)
        self.assertEqual(east[0]["valid_utc"],"2026-10-16T00:00+00:00")
        self.assertEqual(east[0]["issued_utc"],"2026-10-16T04:00+00:00")
        self.assertEqual({x["publisher_id"] for x in east+west+hemi},{"noaa"})
        self.assertTrue(all("Pac_tab.php" in x["source_page"] for x in east+west+hemi))
        self.assertEqual({x["source_id"] for x in east+west+hemi},
                         {"noaa_pace","noaa_pacw","noaa_pachemi"})

    def test_pacific_forecast_lead_utc_not_publication_utc(self):
        html='''<a href="epac24_sfcfcst_00.2026101603.gif">24h</a>
<a href="pac48_sfcfcst_12.2026101616.gif">48h</a>
<a href="pac96_sfcfcst_12.2026101618.gif">96h</a>
<a href="pac48_sfcfcst_12.2026101623.gif">invalid issue</a>
<a href="epac24_sfcfcst_00.2026101403.gif">expired</a>
<a href="watl24_sfcfcst_12.2026101616.gif">Atlantic excluded</a>'''
        a=charts.extract_opc_pac24(html,NOW)
        b=charts.extract_opc_pac48(html,NOW)
        c=charts.extract_opc_pac96(html,NOW)
        self.assertEqual([x["forecast_hours"] for x in a+b+c],[24,48,96])
        self.assertEqual([x["valid_utc"] for x in a+b+c],
                         ["2026-10-17T00:00+00:00",
                          "2026-10-18T12:00+00:00",
                          "2026-10-20T12:00+00:00"])
        self.assertTrue(all(x["publisher_id"]=="noaa" for x in a+b+c))
        self.assertEqual(len(b),1)

    def test_noaa_west_analysis_is_not_an_independent_agency(self):
        html='<a href="atlw_sfcanal_06.2026101608.gif">west</a>'
        rec=charts.extract_opc_west(html,NOW)
        self.assertEqual(len(rec),1)
        self.assertEqual(rec[0]["valid_utc"],"2026-10-16T06:00+00:00")
        self.assertEqual(rec[0]["publisher_id"],"noaa")

    def test_noaa_opc_license_and_external_services(self):
        sources={s["id"]:s for s in charts.SOURCES}
        self.assertEqual(sources["noaa_opc"]["type"],"auto")
        self.assertEqual(sources["noaa_full"]["type"],"auto")
        for id in ("noaa_west","noaa_24","noaa_48","noaa_96","noaa_pace","noaa_pacw","noaa_pachemi","noaa_pac24","noaa_pac48","noaa_pac96"):
            self.assertEqual(sources[id]["type"],"auto")
        self.assertEqual(len(sources),len({s["id"] for s in charts.SOURCES}))
        self.assertEqual(sources["eccc"]["type"],"external")
        self.assertEqual(sources["metoffice"]["type"],"external")

    def test_new_european_front_services_and_license_controls(self):
        providers={s["id"]:s for s in charts.SOURCES}
        self.assertEqual(providers["dhmz"]["type"],"auto")
        self.assertEqual(providers["dmi"]["type"],"external")
        self.assertEqual(providers["shmu"]["type"],"external")
        self.assertEqual(providers["meteoswiss"]["type"],"external")
        self.assertEqual(providers["metie"]["type"],"external")
        self.assertEqual(providers["metie_forecast"]["type"],"external")
        self.assertEqual(len(charts.SOURCES),len(providers))
        self.assertTrue(providers["dhmz"]["url"].startswith("https://meteo.hr/"))


    def test_knmi_parses_official_dated_gif_links_not_legend(self):
        now=datetime(2026,10,19,10,tzinfo=timezone.utc)
        html='''<ul>
<a href="https://cdn.knmi.nl/knmi/map/page/weer/waarschuwingen_verwachtingen/weerkaarten/AL1906_large.gif">Analyse maandag 19-10-2026 06 UTC</a>
<a href="https://cdn.knmi.nl/knmi/map/page/weer/waarschuwingen_verwachtingen/weerkaarten/PL1912_large.gif">Prognose voor maandag 19-10-2026 12 UTC</a>
<a href="https://cdn.knmi.nl/knmi/map/page/weer/waarschuwingen_verwachtingen/weerkaarten/PL2000_large.gif">Prognose voor dinsdag 20-10-2026 00 UTC</a>
<a href="https://cdn.knmi.nl/knmi/map/page/weer/waarschuwingen_verwachtingen/weerkaarten/PL2012_large.gif">Prognose voor dinsdag 20-10-2026 12 UTC</a>
<a href="https://evil.example/knmi/map/page/weer/waarschuwingen_verwachtingen/weerkaarten/AL1906_large.gif">Analyse maandag 19-10-2026 06 UTC</a>
<a href="https://cdn.knmi.nl/knmi/map/page/weer/waarschuwingen_verwachtingen/weerkaarten/PL1906_large.gif">Analyse maandag 19-10-2026 06 UTC</a>
<a href="https://cdn.knmi.nl/knmi/map/page/weer/waarschuwingen_verwachtingen/weerkaarten/legend_large.gif">Uitleg symbolen</a>
</ul>'''
        records=charts.extract_knmi(html,now)
        self.assertEqual(len(records),4)
        self.assertEqual([x["valid_utc"] for x in records],[
            "2026-10-19T06:00+00:00",
            "2026-10-19T12:00+00:00",
            "2026-10-20T00:00+00:00",
            "2026-10-20T12:00+00:00"])
        self.assertEqual(records[0]["kind"],"Analyse")
        self.assertTrue(all(r["source_url"].startswith("https://cdn.knmi.nl/") for r in records))
        self.assertTrue(all(r["publisher_id"]=="knmi" for r in records))
        self.assertEqual({r["kind"] for r in records},{"Analyse","Prognose"})

    def test_no_unlicensed_dmi_shmu_or_metie_image_ingestion(self):
        providers={s["id"]:s for s in charts.SOURCES}
        for provider in ("dmi","metie","metoffice"):
            self.assertEqual(providers[provider]["type"],"external")
        self.assertNotIn("shmu",[provider_id for provider_id,_,_ in [
            ("dwd",charts.DWD_INDEX,charts.extract_dwd),
            ("aemet",charts.AEMET_PAGE,charts.extract_aemet),
            ("knmi",charts.KNMI_PAGE,charts.extract_knmi)]])

    def test_met_office_not_auto_scraped(self):
        providers={x["id"]:x for x in charts.SOURCES}
        self.assertEqual(providers["metoffice"]["type"],"external")
        self.assertEqual(providers["chmi"]["type"],"auto")

    def test_no_time_rounding(self):
        v1=datetime(2026,10,16,0,tzinfo=timezone.utc).isoformat(timespec="minutes")
        v2=datetime(2026,10,16,6,tzinfo=timezone.utc).isoformat(timespec="minutes")
        self.assertNotEqual(v1,v2)


if __name__=="__main__":
    unittest.main()
