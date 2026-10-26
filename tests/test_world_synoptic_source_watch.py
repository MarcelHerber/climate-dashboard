import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import watch_world_synoptic_sources as watch
NOW=datetime(2026,10,20,10,tzinfo=timezone.utc)
class WorldSourceWatchTests(unittest.TestCase):
    def test_all_nine_independent_source_pages(self):
        out=watch.collect(fetch=lambda url,host:"<html>surface analysis weather chart</html>",now=NOW)
        self.assertEqual(out["source_count"],9)
        self.assertEqual(len({x["id"] for x in out["sources"]}),9)
        self.assertTrue(out["no_image_copied"] and out["no_automatic_chart_publication"])
        self.assertTrue(all(not x["sync_ready"] for x in out["sources"]))
    def test_restricted_metservice_is_never_requested(self):
        calls=[]
        def fetch(url,host):
            calls.append(host)
            if "metservice.com" in host:raise AssertionError("Restricted site queried")
            return "<html></html>"
        output=watch.collect(fetch=fetch,now=NOW)
        self.assertEqual(len(output["sources"]),9)
        self.assertEqual(len(calls),8)
        self.assertNotIn("services.metservice.com",calls)
        self.assertEqual(next(x for x in output["sources"] if x["id"]=="metservice")["status"],"excluded_provider_terms")
    def test_only_chart_files_same_https_host(self):
        p=watch.Links("https://www.bom.gov.au/australia/charts/","www.bom.gov.au")
        p.feed("""<img src="/images/logo.png">
                <a href="/a/synoptic-20261020.gif">chart</a>
                <a href="http://www.bom.gov.au/a/surface-analysis.png">insecure</a>
                <img src="https://evil.invalid/synoptic-20261020.gif">
                <a href="/a/randomfile.png">other</a>
                <img src="/maps/pressure2026102000.jpg">chart</img>""")
        self.assertEqual(len(p.chart_links),2)
    def test_next_run_only_marks_new_candidates(self):
        link="https://www.bom.gov.au/chart/surface-20261020.gif"
        previous={"sources":[{"id":"bom","reference_image_candidates":[link]}]}
        def fetch(url,host):
            return '<a href="/chart/surface-20261020.gif">old</a><a href="/chart/surface-20261021.gif">new</a>' if host=="www.bom.gov.au" else ""
        out=watch.collect(previous,fetch,now=NOW)
        bom=next(x for x in out["sources"] if x["id"]=="bom")
        self.assertEqual(len(bom["new_candidate_urls"]),1)
        self.assertTrue(bom["new_candidate_urls"][0].endswith("20261021.gif"))
        self.assertFalse(bom["sync_ready"])
    def test_unavailable_provider_does_not_stop_remaining_search(self):
        def fetch(url,host):
            if host=="www.jma.go.jp":raise TimeoutError("offline")
            return "<html></html>"
        result=watch.collect(fetch=fetch,now=NOW)
        self.assertEqual(result["sources"][0]["status"],"unreachable")
        self.assertEqual(sum(x["status"]=="source_html_available" for x in result["sources"]),7)
        self.assertEqual(next(x for x in result["sources"] if x["id"]=="metservice")["status"],"excluded_provider_terms")
if __name__=="__main__":unittest.main()
