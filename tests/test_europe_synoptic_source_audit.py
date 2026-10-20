import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import audit_europe_synoptic_sources as audit

class EuropeOriginalRightsTests(unittest.TestCase):
    def test_publisher_rights_without_timestamp_never_publish(self):
        self.assertFalse(audit.image_admissible(audit.SOURCES["imo"],False,False))
        self.assertTrue(audit.image_admissible(audit.SOURCES["imo"],True,True))
        self.assertFalse(audit.image_admissible(audit.SOURCES["imo"],True,False))
    def test_model_open_data_not_same_as_copyright_on_original_chart(self):
        self.assertFalse(audit.image_admissible(audit.SOURCES["meteoswiss"],True,True))
    def test_restricted_publication_must_remain_external(self):
        for provider in ("dmi","shmu","kmi","hungaromet","metoffice","metie"):
            self.assertFalse(audit.image_admissible(audit.SOURCES[provider],True,True),provider)
    def test_original_archive_maps_are_not_current_live_feed(self):
        x=audit.SOURCES["smhi"]
        self.assertEqual(x["map"],"archive")
        self.assertEqual(x["rights"],"original_unmodified_only")
        self.assertFalse(audit.image_admissible(x,True,True))
    def test_imgw_analysis_forecast_and_bulletin_have_separate_reuse_gates(self):
        imgw=("imgw","imgw_synoptic_forecast","imgw_synoptic_archive")
        for identifier in imgw:
            with self.subTest(identifier=identifier):
                provider=audit.SOURCES[identifier]
                self.assertEqual(provider["rights"],"chart_specific_clearance_required")
                self.assertEqual(provider["country"],"Polen")
                self.assertEqual(provider["terms_url"],"https://danepubliczne.imgw.pl/regulations")
                self.assertFalse(audit.image_admissible(provider,True,True))
        self.assertIn("00_12",audit.SOURCES["imgw"]["timestamp"])
        self.assertEqual(audit.SOURCES["imgw_synoptic_archive"]["map"],
                         "historical_selected_analyses_in_monthly_pdf")

    def test_cyprus_ccby_for_point_values_does_not_license_wrf_image_gifs(self):
        p=audit.SOURCES["cyprus_dom_wrf"]
        self.assertEqual(p["rights"],"chart_specific_clearance_required")
        self.assertEqual(p["timestamp"],"pending_exact_init_and_valid_utc_image_ocr")
        self.assertFalse(audit.image_admissible(p,True,True))

    def test_russia_and_kazakhstan_images_stay_external_until_licensed(self):
        for id in ("russia_hmc_analysis","russia_hmc_forecast","kazakhstan_synoptic"):
            with self.subTest(id=id):
                self.assertFalse(audit.image_admissible(audit.SOURCES[id],True,True))
        self.assertEqual(audit.SOURCES["russia_hmc_analysis"]["timestamp"],
                         "four_utc_slots_no_image_verified")

    def test_new_national_services_are_not_inadvertently_republished(self):
        names=("italiameteo_isobars","italiameteo_opendata",
               "cyprus_dom_wrf","arso_synoptic_archive","lvgmc_front_archive")
        for name in names:
            with self.subTest(name=name):
                self.assertFalse(audit.image_admissible(audit.SOURCES[name],True,True))
        self.assertEqual(audit.SOURCES["italiameteo_opendata"]["rights"],"open_model_data_ccby")
        self.assertEqual(audit.SOURCES["cyprus_dom_wrf"]["map"],
                         "wrf_pressure_wind_temperature_no_fronts")
        self.assertNotEqual(audit.SOURCES["arso_synoptic_archive"]["map"],
                            "synoptic_live_chart")

    def test_positive_gate_requires_explicit_provider_rights_and_utc(self):
        p={"rights":"open_chart_license","timestamp":"verified_in_filename"}
        self.assertTrue(audit.image_admissible(p,True,True))
        self.assertFalse(audit.image_admissible(p,True,False))
    def test_audit_contains_unambiguous_source_ids(self):
        x=audit.build(datetime(2026,10,19,12,tzinfo=timezone.utc))
        self.assertEqual(len(x["providers"]),len({r["id"] for r in x["providers"]}))
        self.assertTrue(x["no_live_check"])
        self.assertTrue(all(not r["reproduction_ready"] for r in x["providers"]))

if __name__=="__main__":unittest.main()
