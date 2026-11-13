"""Original DWD surface front-analysis discovery and temporal provenance tests."""
from __future__ import annotations
import importlib.util
import json
import struct
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("dwd_fronts_phase1",ROOT/"scripts/update_satellite_dwd_fronts.py")
dwd=importlib.util.module_from_spec(spec)
spec.loader.exec_module(dwd)
NOW=datetime(2026,11,13,16,20,tzinfo=timezone.utc)
INDEX=dwd.INDEX

def fname(date,kind="dwdna",published="20261113153000",suffix="WV12SW.png"):
    return f"Z__C_EDZW_{published}_tka01,ana_bwkman_{kind}_O_000000_000000_{date}_{suffix}"

def html(*names):
    return "<html><body>"+"".join(f'<a href="{item}">DWD</a>' for item in names)+"</body></html>"

def png(width=1000,height=710):
    return dwd.PNG+b"\x00\x00\x00\x0dIHDR"+struct.pack(">II",width,height)+b"\x08\x02\x00\x00\x00"+b"\x00"*95000+b"\x00\x00\x00\x00IEND\xaeB\x60\x82"


class OfficialDWDFrontTests(unittest.TestCase):
    def test_dwd_surface_analysis_only_no_forecast_or_latest_alias(self):
        official_atl=fname("202611131200",published="20261113145500")
        official_ctr=fname("202611130000","dwdc",published="20261113013630")
        invalid=[
            fname("202611131200",suffix="WV12.png"),  # only reduced original PNG
            "Z__C_EDZW_20261113145500_nwv01,ico_p00_na_N_000000_999999.png",
            "ico_tkboden_na_036.png",
            "Z__C_EDZW_LATEST_tka01,ana_bwkman_dwdna_O_000000_000000_202611131200_WV12SW.png",
            fname("202611141200",published="20261114145500"), # future
            fname("202611101200",published="20261110145500"), # >42h stale
            fname("202611131800",published="20261113145500"), # published before analysis
            "https://evil.example/"+official_atl
        ]
        candidates=dwd.candidate_maps(html(official_atl,official_ctr,*invalid),NOW)
        self.assertEqual(len(candidates["atlantic"]),1)
        self.assertEqual(len(candidates["central"]),1)
        self.assertEqual(candidates["atlantic"][0]["valid_utc"],"2026-11-13T12:00Z")
        self.assertEqual(candidates["central"][0]["valid_utc"],"2026-11-13T00:00Z")
        self.assertEqual(candidates["atlantic"][0]["kind"],"analysis")
        self.assertIn("opendata.dwd.de",candidates["atlantic"][0]["source_url"])

    def test_choose_latest_actually_verified_png_and_explicit_fallback(self):
        newest=fname("202611131200",published="20261113145500")
        prev=fname("202611130600",published="20261113092812")
        c=dwd.candidate_maps(html(newest,prev),NOW)
        requested=[]
        def fetch(url):
            requested.append(url)
            if "202611131200" in url:
                raise RuntimeError("DWD HTTP 504")
            return png()
        maps,err=dwd.select_verified(c,NOW,fetch=fetch)
        self.assertEqual(maps["atlantic"]["valid_utc"],"2026-11-13T06:00Z")
        self.assertEqual(len(requested),2)
        self.assertTrue(maps["atlantic"]["fresh"])
        self.assertTrue(maps["atlantic"]["image_verified"])
        self.assertNotIn("central",maps)

    def test_no_unverified_or_forecast_image_can_be_published(self):
        wrong=fname("202611131200",published="20261113145500")
        result=dwd.build_report(html(wrong),NOW,fetch=lambda _:b"service unavailable")
        self.assertEqual(result["status"],"unavailable")
        self.assertEqual(result["maps"],{})
        self.assertIn("atlantic",result["errors"])

    def test_stale_preserved_chart_is_never_mislabeled_as_current(self):
        earlier={
            "maps":{"atlantic":{
                "valid_utc":"2026-11-13T00:00Z",
                "kind":"analysis","image_verified":True,
                "source_url":INDEX+fname("202611130000",published="20261113013630"),
                "fresh":True
            }}
        }
        current=dwd.build_report("",NOW,previous=earlier)
        self.assertEqual(current["status"],"degraded")
        self.assertFalse(current["maps"]["atlantic"]["fresh"])
        self.assertTrue(current["maps"]["atlantic"]["previously_verified"])
        future=NOW+timedelta(hours=50)
        later=dwd.build_report("",future,previous=earlier)
        self.assertEqual(later["status"],"unavailable")
        self.assertEqual(later["maps"],{})

    def test_reject_unexpected_png_dimensions_or_incomplete_image(self):
        self.assertEqual(dwd.validate_png(png()),(1000,710))
        for broken in [b"<html>bad gateway</html>",png(120,710),png(1000,200),png()[:-12]]:
            with self.assertRaises(ValueError):
                dwd.validate_png(broken)

    def test_report_keeps_real_validity_and_publication_different(self):
        two=[
            fname("202611131200",published="20261113145500"),
            fname("202611131200","dwdc",published="20261113150300")
        ]
        report=dwd.build_report(html(*two),NOW,fetch=lambda _:png())
        self.assertEqual(report["status"],"healthy")
        self.assertEqual(report["maps"]["atlantic"]["valid_utc"],"2026-11-13T12:00Z")
        self.assertEqual(report["maps"]["atlantic"]["published_utc"],"2026-11-13T14:55Z")
        self.assertTrue(report["maps"]["central"]["fresh"])
        self.assertEqual(report["fresh_hours"],18)
        self.assertIn("unmodified",report["image_policy"])

    def test_page_and_build_include_dwd_phase1_not_false_overlay(self):
        page=(ROOT/"satelliten.html").read_text(encoding="utf-8")
        js=(ROOT/"satellite_dwd_fronts.js").read_text(encoding="utf-8")
        build=(ROOT/"scripts/build_pages_site.sh").read_text(encoding="utf-8")
        self.assertIn('id="satDwdFrontAnalysisSection"',page)
        for item in ("satFrontImage","satFrontOpen","satFrontRegion","satFrontStatus","satFrontValid"):
            self.assertIn(f'id="{item}"',page)
        self.assertIn("  satellite_dwd_fronts.js\n",build)
        self.assertIn('href="https://opendata.dwd.de/weather/charts/analysis/"',page)
        self.assertNotIn("satIsobarSvg",js,"No DWD manual fronts on ECMWF WMS without proven geo coordinates")


if __name__=="__main__":
    unittest.main()
