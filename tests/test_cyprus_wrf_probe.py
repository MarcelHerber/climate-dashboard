import io,sys,unittest
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import probe_cyprus_wrf as c

NOW=datetime(2026,10,20,7,tzinfo=timezone.utc)
def gif():
    out=io.BytesIO()
    Image.new("RGB",(700,420),"white").save(out,format="GIF")
    return out.getvalue()
def source_html(run):
    base=f"/WRF4/{run}Z/01/SLP_W10m_T2m/"
    return ('<a href="'+base+'SLP_W10m_T2m_d01-000.gif">image</a>'+
            '<img src="'+base+'SLP_W10m_T2m_d01-006.gif">'+
            '<img src="https://evil.invalid/chart.gif">'+
            '<a href="'+base+'SLP_W10m_T2m_d01-006.gif">repeated</a>')

class CyprusWRFTests(unittest.TestCase):
    def test_only_official_gifs_from_correct_run(self):
        expected=c.frames_from_html(source_html("00"),c.PAGES["00"],"00")
        self.assertEqual([x["frame"] for x in expected],[0,6])
        self.assertTrue(all(x["url"].startswith("https://www.dom.org.cy/") for x in expected))
    def test_mismatched_12_run_images_are_excluded(self):
        self.assertFalse(c.frames_from_html(source_html("00"),c.PAGES["12"],"12"))
        with self.assertRaises(ValueError):
            c.frames_from_html("",c.PAGES["00"],"12")
    def test_frame_numbers_and_crawl_time_are_not_utc(self):
        for caption in ("WRF 00Z frame 006", "VALID 2026-10-20 06:00 UTC",
                        "INIT 2026-10-20 00:00 UTC"):
            with self.assertRaises(ValueError):
                c.parse_printed_times(caption,"00",NOW)
    def test_labeled_image_times_accepted(self):
        caption="INIT: 2026-10-20 00:00 UTC\nVALID: 2026-10-20 06:00 UTC"
        r=c.parse_printed_times(caption,"00",NOW)
        self.assertEqual(r["run_utc"],"2026-10-20T00:00+00:00")
        self.assertEqual(r["valid_utc"],"2026-10-20T06:00+00:00")
    def test_stale_run_and_mismatched_hour_rejected(self):
        for caption,run in [
            ("INIT: 2026-10-01 00:00 UTC\nVALID: 2026-10-01 03:00 UTC","00"),
            ("INIT: 2026-10-20 00:00 UTC\nVALID: 2026-10-20 06:00 UTC","12")]:
            with self.assertRaises(ValueError):
                c.parse_printed_times(caption,run,NOW)
    def test_an_image_with_verified_time_still_has_no_republication_license(self):
        def html_fetch(url):
            run="00" if "/00Z/" in url else "12"
            return source_html(run)
        def img_fetch(url):return gif()
        def image_clock(raw):
            return ("INIT: 2026-10-20 00:00 UTC\nVALID: 2026-10-20 06:00 UTC",[700,420])
        result=c.check(NOW,html_fetch,img_fetch,image_clock)
        self.assertEqual(len(result["reports"]),2)
        self.assertEqual([x["frame_count"] for x in result["reports"]],[2,2])
        self.assertEqual(result["reports"][0]["sample_maps"][0]["state"],
                         "printed_init_and_valid_utc_verified")
        self.assertEqual(result["reports"][1]["sample_maps"][0]["state"],"timestamp_unverified")
        self.assertFalse(result["ready_for_automatic_image_reuse"])
        self.assertTrue(result["no_images_persisted"])
        self.assertTrue(all(not r["ready_for_image_reuse"] for r in result["reports"]))
    def test_cant_be_faked_by_external_link_or_foreign_id(self):
        html='<img src="http://www.dom.org.cy/WRF4/00Z/01/SLP_W10m_T2m/SLP_W10m_T2m_d01-000.gif">'
        self.assertEqual(c.frames_from_html(html,c.PAGES["00"],"00"),[])
    def test_zero_images_fail_closed(self):
        def fetch(_):return "<html>No GIFs</html>"
        result=c.check(NOW,html_fetch=fetch)
        self.assertTrue(all(x["state"]=="no_verified_gif_links" for x in result["reports"]))
        self.assertTrue(all(not x["sample_maps"] for x in result["reports"]))

if __name__=="__main__":unittest.main()
