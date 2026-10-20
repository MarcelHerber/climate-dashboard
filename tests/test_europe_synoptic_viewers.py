import sys,unittest
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import probe_europe_synoptic_viewers as mod

class OfficialViewerTests(unittest.TestCase):
    def test_parses_only_official_host_images_and_explicit_utc_attributes(self):
        html='''<img src="/chart/20261019.png" data-valid-utc="2026-10-19T12:00Z">
        <img src="https://evil.com/20261019.png">
        <a href="/chart/202610191800.gif"></a>
        <a href="/20261019.pdf">PDF</a> Surface pressure Europe'''
        r=mod.parse_viewer(html,"https://www.emy.gr/en/marine","www.emy.gr")
        self.assertEqual(len(r["same_host_image_candidates"]),2)
        self.assertEqual(r["explicit_utc_attributes"],["2026-10-19T12:00Z"])
        self.assertTrue(r["mentions_isobars"])
        self.assertFalse(r["ready_for_image_reuse"])
    def test_bad_date_or_host_not_accepted(self):
        self.assertIsNone(mod.known_image("http://www.emy.gr/image.png","https://www.emy.gr/en/marine","www.emy.gr"))
        self.assertIsNone(mod.known_image("https://www.emy.gr.bad.com/a.png","https://www.emy.gr/en/marine","www.emy.gr"))
        self.assertFalse(mod.DATE_VALID.fullmatch("2026-19-99T14:00Z"))
    def test_nineteen_worldwide_official_sources_are_audited_fail_closed(self):
        def f(url,host):return '<div data-valid-utc="2026-10-19T00:00Z">surface pressure</div>'
        r=mod.collect(fetch=f,now=datetime(2026,10,19,15,tzinfo=timezone.utc))
        self.assertEqual(len(r["sources"]),19)
        self.assertEqual(len({x["id"] for x in r["sources"]}),19)
        self.assertTrue(all(x["state"]=="html_inspected" for x in r["sources"]))
        self.assertTrue(all(not x["ready_for_automatic_charts"] for x in r["sources"]))
    def test_failed_source_does_not_stop_other_checks(self):
        def f(url,host):
            if "emy.gr" in host:raise TimeoutError("not responding")
            return '<html></html>'
        r=mod.collect(fetch=f)
        self.assertEqual(r["sources"][0]["state"],"not_reachable")
        self.assertEqual(sum(x["state"]=="html_inspected" for x in r["sources"]),18)

if __name__=="__main__":unittest.main()
