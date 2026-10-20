"""All European states must have a clearly classified source link, not invented live charts."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import update_synoptic_original_charts as original
import audit_europe_synoptic_sources as audit

EUROPE={
 "Albanien","Andorra","Österreich","Belarus","Belgien",
 "Bosnien und Herzegowina","Bulgarien","Kroatien","Tschechien",
 "Dänemark","Estland","Finnland","Frankreich","Deutschland",
 "Griechenland","Ungarn","Island","Irland","Italien","Lettland",
 "Liechtenstein","Litauen","Luxemburg","Malta","Moldau","Monaco",
 "Montenegro","Niederlande","Nordmazedonien","Norwegen","Polen",
 "Portugal","Rumänien","Russland","San Marino","Serbien",
 "Slowakei","Slowenien","Spanien","Schweden","Schweiz",
 "Ukraine","Großbritannien","Vatikanstadt","Zypern","Türkei","Kosovo"
}
ADJACENT={"Armenien","Aserbaidschan","Georgien","Kasachstan"}
NEW_SOURCE_IDS={
 "albania_igeo","andorra_meteo","belarus_belhydromet",
 "bosnia_fhmz_gfs","liechtenstein_swiss","luxembourg_meteolux",
 "malta_metoffice","moldova_shs","monaco_france","montenegro_zhms",
 "northmacedonia_uhmr","russia_hmc_analysis","russia_hmc_forecast",
 "sanmarino_italy","ukraine_uhmc","vatican_italy","kosovo_ihmk",
 "armenia_hmc","armenia_archive","azerbaijan_nhms","georgia_nea",
 "kazakhstan_synoptic"
}

class EuropeanCoverageTests(unittest.TestCase):
    def test_all_47_european_countries_present(self):
        self.assertEqual(len(EUROPE),47)
        self.assertEqual(len(ADJACENT),4)
        countries={s["country"] for s in original.SOURCES}
        self.assertFalse(EUROPE-countries,sorted(EUROPE-countries))
        self.assertFalse(ADJACENT-countries,sorted(ADJACENT-countries))
    def test_no_duplicate_provider_identifiers(self):
        ids=[s["id"] for s in original.SOURCES]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertFalse(NEW_SOURCE_IDS-set(ids))
    def test_new_sources_are_external_only_and_linked(self):
        by_id={s["id"]:s for s in original.SOURCES}
        for id in NEW_SOURCE_IDS:
            with self.subTest(id=id):
                rec=by_id[id]
                self.assertEqual(rec["type"],"external")
                self.assertTrue(rec["url"].startswith("https://"))
                self.assertIn(id,audit.SOURCES)
                policy=audit.SOURCES[id]
                self.assertEqual(policy["country"],rec["country"])
                self.assertEqual(policy["url"],rec["url"])
                self.assertFalse(audit.image_admissible(policy,True,True))
    def test_regionally_covered_microstates_not_falsely_independent(self):
        names=("liechtenstein_swiss","monaco_france","sanmarino_italy","vatican_italy")
        for id in names:
            self.assertEqual(audit.SOURCES[id]["map"],"regional_coverage")
    def test_promising_viewers_not_unlicensed_auto_charts(self):
        for id in ("russia_hmc_analysis","russia_hmc_forecast","kazakhstan_synoptic",
                   "luxembourg_meteolux","bosnia_fhmz_gfs","montenegro_zhms"):
            with self.subTest(id=id):
                self.assertFalse(audit.image_admissible(audit.SOURCES[id],True,True))

if __name__=="__main__":
    unittest.main()
