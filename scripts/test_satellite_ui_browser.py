#!/usr/bin/env python3
"""Desktop/mobile Chromium acceptance test for the Meteosat satellite page.

External image requests are real. If CORS prevents capabilities retrieval, the
official capabilities XML is forwarded only for the test so UI features can be
tested independently of the browser's CORS policy. Both facts are reported.
"""
from __future__ import annotations
import http.server
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/satellite_browser_check_latest.json"
SHOTS = ROOT / "_satellite_test_screenshots"
SHOTS.mkdir(exist_ok=True)
WMS = "https://view.eumetsat.int/geoserver/wms"
PROD = ("geocolour", "dust", "cloudtype")
REMOTE = "https://marcelherber.github.io/climate-dashboard/satelliten.html"


class Server(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=str(ROOT), **kw)
    def log_message(self, *_):
        pass


def source_xml():
    request = Request(WMS + "?"+urlencode({
        "service":"WMS", "version":"1.1.1", "request":"GetCapabilities"
    }), headers={"User-Agent":"ClimateDashboard-UI-test/1.0"})
    with urlopen(request, timeout=50) as res:
        data = res.read(6_000_000)
    if b"mtg_fd:rgb_geocolour" not in data:
        raise ValueError("EUMETSAT GetCapabilities has no expected GeoColour layer")
    return data


def safe_check(callback):
    try:
        return callback()
    except Exception as err:
        return {"error": str(err)[:300]}


def check_remote():
    try:
        with urlopen(Request(REMOTE, headers={"User-Agent":"ClimateDashboard-UI-test/1.0"}), timeout=25) as res:
            head = res.read(32_000)
            return {"http_status":res.status,
                    "satellite_markup":b'id="satSource"' in head,
                    "content_type":res.headers.get("Content-Type", "")}
    except Exception as error:
        return {"error":str(error)[:300]}


def exercise(page, viewport_label, official_xml):
    evidence = {"viewport": viewport_label}
    # Only replace the capabilities XML response. Satellite PNGs are loaded
    # directly from the actual EUMETSAT host by Chromium.
    def intercept(route):
        if "GetCapabilities" in route.request.url or "getcapabilities" in route.request.url.lower():
            route.fulfill(status=200, body=official_xml, content_type="text/xml",
                          headers={"Access-Control-Allow-Origin":"*"})
        else:
            route.continue_()
    page.route("**/geoserver/wms?*", intercept)
    page.goto("http://127.0.0.1:18873/satelliten.html",wait_until="domcontentloaded",timeout=30000)
    page.wait_for_function(
        "() => document.getElementById('satTime').options.length > 1 || document.getElementById('satStatus').textContent.includes('nicht')",
        timeout=25000
    )
    evidence["initial_product"]="geocolour"
    evidence["times"]=page.locator("#satTime option").count()
    evidence["time_select_enabled"]=page.locator("#satTime").is_enabled()
    evidence["image_initial_loaded"]=safe_check(lambda: page.wait_for_function(
        "() => document.getElementById('satImage').naturalWidth > 0",timeout=35000) is not None)
    evidence["image_status"]=page.locator("#satStatus").inner_text()
    evidence["image_url"]=page.locator("#satImage").get_attribute("src")
    evidence["viewport_overflow"]=page.evaluate(
        "()=>document.documentElement.scrollWidth > window.innerWidth+3"
    )
    evidence["mobile_menu_visible"]=page.locator("#cdMobileMenuButton").is_visible()
    if evidence["times"] >= 2:
        evidence["time_before"]=page.locator("#satTime").input_value()
        page.locator("#satPrev").click()
        evidence["time_after_prev"]=page.locator("#satTime").input_value()
        assert evidence["time_before"]!=evidence["time_after_prev"], "Back navigation did not change UTC frame"
        page.locator("#satNext").click()
    # Select the native geostationary projection for full disk.
    page.locator("#satRegion").select_option("disk")
    page.wait_for_timeout(350)
    evidence["full_disk_native_projection"]="AUTO%3A97004" in page.locator("#satImage").get_attribute("src")
    assert evidence["full_disk_native_projection"], "Full-disc projection is not geostationary"
    page.locator("#satRegion").select_option("germany")
    evidence["germany_bbox"]="5%2C47%2C16%2C56" in page.locator("#satImage").get_attribute("src")
    assert evidence["germany_bbox"], "Germany selection did not change bounding box"
    for option in PROD:
        page.locator("#satProduct").select_option(option)
        page.wait_for_timeout(250)
        evidence[option+"_url"]="mtg_fd%3Argb_"+option in page.locator("#satImage").get_attribute("src")
        assert evidence[option+"_url"], "Wrong WMS layer for "+option
    # Source switch cannot falsely identify commissioning images as a stream.
    page.locator("#satSource").select_option("mtgi2")
    evidence["mtgi2_no_live"]="Kein Livestream" in page.locator("#satValid").inner_text()
    evidence["mtgi2_product_disabled"]=not page.locator("#satProduct").is_enabled()
    assert evidence["mtgi2_no_live"] and evidence["mtgi2_product_disabled"]
    page.locator("#satSource").select_option("mtgi1")
    evidence["mtgi1_product_enabled"]=page.locator("#satProduct").is_enabled()
    assert evidence["mtgi1_product_enabled"]
    evidence["theme_toggle_present"]=page.locator("#dashboardThemeToggle").count()==1
    theme_control="#cdMobileSatelliteTheme" if viewport_label=="mobile" else "#dashboardThemeToggle"
    evidence["theme_control_visible"]=page.locator(theme_control).is_visible()
    assert evidence["theme_control_visible"], "The theme control must be visible and reachable"
    page.locator(theme_control).click()
    evidence["dark_theme_on"]=page.evaluate(
        "()=>document.documentElement.dataset.theme === 'dark'")
    assert evidence["dark_theme_on"], "Dark mode did not toggle"
    page.screenshot(path=str(SHOTS/(viewport_label+".png")),full_page=True)
    evidence["screenshot"]=viewport_label+".png"
    return evidence


def main():
    report = {"generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "remote": check_remote(), "capabilities_fixture":None,
              "desktop":{}, "mobile":{}}
    try:
        xml=source_xml()
        report["capabilities_fixture"]="actual EUMETSAT GetCapabilities XML"
    except Exception as e:
        report["capabilities_fixture"]="unavailable: "+str(e)[:240]
        xml=b"""<WMT_MS_Capabilities><Capability><Layer>
        <Layer><Name>mtg_fd:rgb_geocolour</Name><Extent name="time">2026-11-10T11:20:00Z,2026-11-10T11:30:00Z</Extent></Layer>
        <Layer><Name>mtg_fd:rgb_dust</Name><Extent name="time">2026-11-10T11:20:00Z,2026-11-10T11:30:00Z</Extent></Layer>
        <Layer><Name>mtg_fd:rgb_cloudtype</Name><Extent name="time">2026-11-10T11:20:00Z,2026-11-10T11:30:00Z</Extent></Layer>
        </Layer></Capability></WMT_MS_Capabilities>"""
    server=http.server.ThreadingHTTPServer(("127.0.0.1",18873),Server)
    task=threading.Thread(target=server.serve_forever,daemon=True)
    task.start()
    try:
        with sync_playwright() as api:
            browser=api.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for name,viewport in [
                    ("desktop",{"width":1440,"height":900}),
                    ("mobile",{"width":390,"height":844})]:
                    context=browser.new_context(viewport=viewport,
                        is_mobile=(name=="mobile"),has_touch=(name=="mobile"))
                    page=context.new_page()
                    try:
                        report[name]=exercise(page,name,xml)
                    except Exception as error:
                        report[name]={"error":str(error)[:450]}
                    finally:
                        context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        OUT.parent.mkdir(parents=True,exist_ok=True)
        OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(report,ensure_ascii=False,indent=2))
    # Independent checks may be unavailable, but deterministic interactions
    # must remain intact when the browser was able to reach the page.
    failures=[key for key in ("desktop","mobile") if "error" in report.get(key,{})]
    return 1 if failures else 0


if __name__=="__main__":
    raise SystemExit(main())
