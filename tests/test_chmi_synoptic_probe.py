import json
import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import probe_chmi_synoptic as p


class ChmiProbeTests(unittest.TestCase):
    NOW=datetime(2026,10,17,6,tzinfo=timezone.utc)

    def test_only_verifiable_candidate_paths_no_false_publication(self):
        html='''<html><script src="/o/chmi/js/frontend.js"></script>
<img src="/documents/d/chmi.cz/synop-bez-dat">
<a href="/predpoved-pocasi/synopticka-situace">SYNOP</a>
<img src="/documents/d/chmi.cz/synopticka_2026101700.png?token=private">
<img src="https://evil.example/front_2026101700.png">External</html>'''
        result=p.probe(now=self.NOW,fetch=lambda:html)
        self.assertEqual(result["state"],"static_metadata_only")
        self.assertEqual(result["dated_synoptic_images"],1)
        self.assertEqual(result["verified_utc_charts"],0)
        self.assertTrue(all("token=" not in json.dumps(result) for _ in [0]))
        self.assertFalse(any("evil.example" in x for x in result["dated_image_paths"]))

    def test_no_data_placeholder_not_a_chart(self):
        html='<img src="/documents/d/chmi.cz/synop-bez-dat">'
        result=p.probe(now=self.NOW,fetch=lambda:html)
        self.assertEqual(result["dated_synoptic_images"],0)
        self.assertEqual(result["verified_utc_charts"],0)
        self.assertEqual(result["synoptic_image_links"],[])

    def test_fetch_failure_returns_status_not_fake_chart(self):
        def fail():
            raise RuntimeError("temporary unavailable")
        data=p.probe(now=self.NOW,fetch=fail)
        self.assertEqual(data["state"],"fetch_error")
        self.assertEqual(data["verified_utc_charts"],0)


if __name__=="__main__":
    unittest.main()
