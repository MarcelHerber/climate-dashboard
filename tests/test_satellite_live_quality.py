"""Offline integrity tests for the live MTG page + fair 800/2K/4K WMS comparison."""
from __future__ import annotations
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("mtg_live_quality", ROOT/"scripts/audit_satellite_live_quality.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
NOW=datetime(2026,11,13,9,20,tzinfo=timezone.utc)


def stamp(offset):
    return (NOW+timedelta(minutes=offset)).isoformat(timespec="seconds").replace("+00:00","Z")


def sample():
    return {name:{
        "map_ok":True,
        "latest_verified_time":stamp(-10 if name=="geocolour" else -5),
        "available_times":[stamp(-40),stamp(-30),stamp(-20),stamp(-10),stamp(-5)]
    } for name in mod.TARGETS}


class SatelliteLiveQualityTests(TestCase):
    def test_latest_utc_requires_all_advertised_and_confirmed_products(self):
        self.assertEqual(mod.latest_common_utc(sample()),stamp(-10))
        data=sample()
        data["cloudtype"]["map_ok"]=False
        self.assertIsNone(mod.latest_common_utc(data))
        data=sample()
        data["geocolour"]["available_times"]=[stamp(-20)]
        self.assertEqual(mod.latest_common_utc(data),stamp(-20))

    def test_identical_geographic_crop_and_real_pixel_density(self):
        bbox=mod.crop_bbox()
        self.assertEqual(len(bbox),4)
        self.assertAlmostEqual(bbox[0],2.64)
        self.assertAlmostEqual(bbox[1],43.11)
        self.assertAlmostEqual(bbox[2],19.36)
        self.assertAlmostEqual(bbox[3],53.89)
        grids=[mod.pixel_grid(v) for v in (800,2048,4096)]
        self.assertEqual(grids,[(176,115),(451,295),(901,589)])
        for w,h in grids:
            self.assertGreater(w,0)
            self.assertGreater(h,0)
        self.assertEqual(mod.TARGETS["ir105"],"mtg_fd:ir105_hrfi")

    def test_quality_requests_include_identical_verified_utc_and_all_three_densities(self):
        jobs=mod.source_jobs(stamp(-10))
        self.assertEqual(len(jobs),9)
        self.assertTrue(all(len(job)==4 and job[2]==stamp(-10) for job in jobs))
        self.assertEqual(set(job[3] for job in jobs),{800,2048,4096})
        self.assertEqual(set(job[0] for job in jobs),set(mod.TARGETS))

    def test_chromium_wait_functions_use_keyword_args_to_avoid_immediate_typeerror(self):
        import ast
        script=(ROOT/"scripts/test_satellite_published_browser.py").read_text(encoding="utf-8")
        tree=ast.parse(script)
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)
               and isinstance(n.func,ast.Attribute)
               and n.func.attr=="wait_for_function"]
        self.assertGreaterEqual(len(calls),3)
        self.assertTrue(all(len(c.args)==1 for c in calls),
                        "Playwright page.wait_for_function must use arg= keyword")

    def test_li_interval_must_be_finished_before_satellite_and_recent(self):
        li={"lightning":{"map_ok":True,"latest_verified_time":stamp(-5),
                         "available_times":[stamp(-25),stamp(-20),stamp(-15),stamp(-10),stamp(-5)]}}
        a=mod.align_li(li,stamp(-5))
        self.assertTrue(a["aligned"])
        self.assertEqual(a["delay_minutes"],0)
        later=mod.align_li(li,stamp(20))
        self.assertFalse(later["aligned"])
        older=mod.align_li(li,stamp(-31))
        self.assertFalse(older["aligned"])

    def test_published_html_is_queried_independently_from_repository(self):
        html=('<script defer src="satelliten.js?v=1"></script>'
              '<script defer src="satellite_lightning.js?v=1"></script>'
              '<script defer src="satellite_radar.js?v=1"></script>'
              '<script defer src="satellite_hd.js?v=1"></script>'
              '<script defer src="satellite_quality_comparison.js?v=1"></script>'
              +''.join(f'<div id="{key}"></div>' for key in (
                "satShowLightning","satShowRadar","satStillQuality",
                "satCompareGrid","satImage","satQualityCompareSection")))
        manifest={"generated_at":stamp(-10),"monitor_status":"healthy",
                  "capabilities_ok":True,"products":sample()}
        seen=[]
        def fake(url,**_):
            seen.append(url)
            if url.endswith("satelliten.html"):payload=html.encode()
            elif url.endswith("satellite_wms_times.json"):payload=__import__("json").dumps(manifest).encode()
            elif ".js?v=" in url:payload=b"window.SatelliteQA=true;"
            else:raise RuntimeError("unexpected URL "+url)
            return payload,{"http":200,"content_type":"text/html","bytes":len(payload)}
        with patch.object(mod,"get",side_effect=fake):
            report=mod.page_version("https://example.com/climate-dashboard/")
        self.assertTrue(report["html_ok"],report.get("error"))
        self.assertEqual(len(report["asset_checks"]),5)
        self.assertEqual(report["published_report"]["generated_at"],stamp(-10))
        self.assertTrue(all("/climate-dashboard/" in x for x in seen))

    def test_bad_or_malformed_web_status_does_not_claim_success(self):
        with patch.object(mod,"get",side_effect=RuntimeError("HTTP 502")):
            report=mod.page_version()
        self.assertFalse(report["html_ok"])
        self.assertIn("502",report["error"])


if __name__=="__main__":
    import unittest
    unittest.main()
