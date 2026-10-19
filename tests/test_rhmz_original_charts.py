import io
import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from PIL import Image
import probe_rhmz_original_charts as rhmz

NOW=datetime(2026,10,19,16,tzinfo=timezone.utc)
def image():
    f=io.BytesIO()
    Image.new("RGB",(1000,590),"white").save(f,format="JPEG",quality=95)
    return f.getvalue()

class RHMZOriginalAnalysisTests(unittest.TestCase):
    def test_printed_europe_timestamp(self):
        self.assertEqual(rhmz.printed_utc("EVROPA PRIZEMNI PODACI 19-10-2026 12 UTC"),
                         datetime(2026,10,19,12,tzinfo=timezone.utc))
    def test_both_slots_require_image_date(self):
        self.assertEqual(rhmz.verified_time("europe00",rhmz.PRODUCTS["europe00"],
                          "EVROPA PRIZEMNI PODACI 19-10-2026 00 UTC",NOW).hour,0)
        self.assertEqual(rhmz.verified_time("europe12",rhmz.PRODUCTS["europe12"],
                          "EVROPA PRIZEMNI PODACI 19-10-2026 12 UTC",NOW).hour,12)
    def test_just_an_hour_is_not_a_date(self):
        for caption in ("Analiza za 12:00 UTC","EVROPA 12 UTC","19-10-2026 12 UTC"):
            with self.assertRaises(ValueError):
                rhmz.printed_utc(caption)
    def test_balkan_chart_printed_utc_and_stale_rejection(self):
        checks={
          "balkan06":"EVROPA PRIZEMNI PODACI 19-10-2026 06 UTC",
          "balkan09":"PRIZEMNI PODACI 19-10-2026 09 UTC",
        }
        for key,caption in checks.items():
            result=rhmz.verified_time(key,rhmz.PRODUCTS[key],caption,NOW)
            self.assertEqual(result.year,2026)
        for key,hr in (("balkan12","12"),("balkan15","15")):
            with self.assertRaises(ValueError):
                rhmz.verified_time(key,rhmz.PRODUCTS[key],
                    "PRIZEMNI PODACI 29-10-2025 "+hr+" UTC",NOW)

    def test_mismatched_hour_rejected(self):
        with self.assertRaises(ValueError):
            rhmz.verified_time("europe12",rhmz.PRODUCTS["europe12"],
                               "EVROPA PRIZEMNI PODACI 19-10-2026 00 UTC",NOW)
    def test_stale_date_rejected(self):
        with self.assertRaises(ValueError):
            rhmz.verified_time("europe00",rhmz.PRODUCTS["europe00"],
                               "EVROPA PRIZEMNI PODACI 01-08-2026 00 UTC",NOW)
    def test_foreign_url_rejected(self):
        with self.assertRaises(ValueError):
            rhmz.verified_time("europe12","https://other.test/x.jpg",
                               "EVROPA PRIZEMNI PODACI 19-10-2026 12 UTC",NOW)
    def test_no_images_persisted_and_all_credits_external(self):
        caption={rhmz.PRODUCTS["europe00"]:"EVROPA PRIZEMNI PODACI 19-10-2026 00 UTC",
                 rhmz.PRODUCTS["europe12"]:"EVROPA PRIZEMNI PODACI 19-10-2026 12 UTC"}
        got=rhmz.check(now=NOW,fetch_image=lambda url:image(),
                       header_reader=lambda raw:caption[rhmz.PRODUCTS["europe00"]] if False else
                        "EVROPA PRIZEMNI PODACI 19-10-2026 12 UTC")
        self.assertTrue(got["only_external_links"])
        self.assertTrue(got["no_images_persisted"])
        self.assertTrue(all(r["image_reuse_permitted"] is False for r in got["records"]))
        self.assertEqual(got["records"][0]["state"],"unverified")
        self.assertEqual(got["records"][1]["state"],"printed_utc_verified")
        self.assertEqual(len(got["records"]),6)
        self.assertEqual(got["records"][2]["state"],"unverified")
    def test_unavailable_image_does_not_claim_verified_utc(self):
        def bad(_):raise OSError("offline")
        out=rhmz.check(now=NOW,fetch_image=bad)
        self.assertTrue(all("valid_utc" not in r for r in out["records"]))

if __name__=="__main__":unittest.main()
