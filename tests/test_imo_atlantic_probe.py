import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import probe_imo_atlantic as imo

FIXED=datetime(2026,10,19,14,tzinfo=timezone.utc)
BASE="https://en.vedur.is/weather/shipping/atlantic/"
GOOD="https://en.vedur.is/static/imo/atlantic_2026101912.png"

class IMOChartProbeTests(unittest.TestCase):
    def test_date_utc_must_have_full_year_month_day_and_hour(self):
        self.assertEqual(imo.exact_utc("2026-10-19 12:00 UTC"),"2026-10-19T12:00+00:00")
        self.assertEqual(imo.exact_utc("atlantic_2026101912.png"),"2026-10-19T12:00+00:00")
        self.assertIsNone(imo.exact_utc("day-2-12"))
        self.assertIsNone(imo.exact_utc("2026-19-91 12:00 UTC"))
        self.assertIsNone(imo.exact_utc("2026101913xx99"))
    def test_foreign_host_and_insecure_protocol_rejected(self):
        self.assertIsNone(imo.allowed_url("https://example.org/2026101912.png",BASE))
        self.assertIsNone(imo.allowed_url("http://en.vedur.is/map.png",BASE))
        self.assertIsNone(imo.allowed_url("https://en.vedur.is.evil.org/map.png",BASE))
        self.assertEqual(imo.allowed_url(GOOD,BASE),GOOD)
    def test_html_exposes_candidate_but_does_not_self_certify_map(self):
        html='<img src="/static/imo/atlantic_2026101912.png" data-valid-utc="2026-10-19 12:00 UTC" alt="Isobaren">'
        assets=imo.document_assets(html,BASE)
        self.assertEqual(len(assets["images"]),1)
        self.assertTrue(assets["images"][0]["strong_timestamp_match"])
        bad=imo.document_assets('<img src="/static/imo/atlantic_2026101912.png" data-valid-utc="2026-10-19 06:00 UTC">',BASE)
        self.assertFalse(bad["images"][0]["strong_timestamp_match"])
    def test_no_filename_only_or_page_crawl_time_timestamp(self):
        a=imo.document_assets('<img src="/static/imo/atlantic_2026101912.png">',BASE)
        self.assertFalse(a["images"][0]["strong_timestamp_match"])
        a=imo.document_assets('<img src="/static/imo/placeholder.png" data-valid-utc="2026-10-19 12:00 UTC">',BASE)
        self.assertFalse(a["images"][0]["strong_timestamp_match"])
    def test_probe_never_marks_chart_ingestion_ready_from_html(self):
        html='<img src="/static/imo/atlantic_2026101912.png" data-valid-utc="2026-10-19 12:00 UTC">'
        def fake(url):
            return html if "atlantshafskort" not in url else ""
        result=imo.probe(FIXED,fake)
        self.assertFalse(result["ready_for_automated_chart_ingestion"])
        self.assertEqual(result["matching_metadata_candidates"],1)
    def test_diagnostic_handles_unreachable_imo_source(self):
        def unreachable(_):raise TimeoutError("source offline")
        result=imo.probe(FIXED,unreachable)
        self.assertEqual(result["state"],"source_unreachable")
        self.assertFalse(result["ready_for_automated_chart_ingestion"])

if __name__=="__main__":unittest.main()
