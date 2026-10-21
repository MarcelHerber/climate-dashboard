import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import dwd_tkb_individual_charts as tkb

class DWDOriginalTKBTests(unittest.TestCase):
    def test_five_single_map_leads_and_publisher(self):
        self.assertEqual(tkb.PRODUCTS,(36,48,60,84,108))
        self.assertEqual(tkb.source_url(36),
           "https://www.dwd.de/DWD/wetter/wv_spez/hobbymet/wetterkarten/ico_tkboden_na_036.png")
        with self.assertRaises(ValueError):tkb.source_url(72)

    def test_manifest_has_real_products_and_no_fake_single_utc(self):
        with tempfile.TemporaryDirectory() as work:
            def fetch(url,**kwargs):return b"fake-png"
            def webp(data,path):
                path.write_bytes(b"RIFF"+bytes(20001))
            out=tkb.publish(Path(work),datetime(2026,10,21,10,tzinfo=timezone.utc),fetch,webp)
            self.assertEqual(out["map_count"],5)
            self.assertTrue(out["single_map_per_lead"])
            self.assertFalse(any("valid_utc" in m for m in out["maps"]))
            self.assertEqual([m["lead_hours"] for m in out["maps"]],[36,48,60,84,108])
            self.assertEqual(out,json.loads((Path(work)/"dwd_tkb.json").read_text()))

    def test_unavailable_charts_are_not_fabricated(self):
        with tempfile.TemporaryDirectory() as work:
            def fetch(url,**kwargs):raise ValueError("HTTP 403")
            def converter(data,path):raise AssertionError("must not convert")
            out=tkb.publish(Path(work),datetime.now(timezone.utc),fetch,converter)
            self.assertEqual(out["maps"],[])
            self.assertEqual(out["map_count"],0)
