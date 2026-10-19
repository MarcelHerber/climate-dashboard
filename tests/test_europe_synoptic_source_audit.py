import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import audit_europe_synoptic_sources as audit

class EuropeOriginalRightsTests(unittest.TestCase):
    def test_publisher_rights_without_timestamp_never_publish(self):
        self.assertFalse(audit.image_admissible(audit.SOURCES["imo"],False,False))
        self.assertFalse(audit.image_admissible(audit.SOURCES["imo"],True,True))
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
