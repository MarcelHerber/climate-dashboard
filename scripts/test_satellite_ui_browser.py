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
PROD = ("geocolour", "dust", "cloudtype", "ir105", "firetemperature")
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
                    "southwest_published":b'value="southwest"' in head,
                    "buffered_film_published":b'id="satFilmLength"' in head,
                    "long_film_published":b'<option value="36">' in head and b'<option value="48">' in head,
                    "overlay_published":b'id="satBordersSvg"' in head and b'satellite_overlay.js' in head,
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
    # Azores, Madeira and Canary Islands in one Southwest-Europe satellite frame.
    page.locator("#satRegion").select_option("southwest")
    evidence["southwest_bbox"]="-37%2C24%2C19%2C53" in (page.locator("#satImage").get_attribute("src") or "")
    assert evidence["southwest_bbox"], "Southwest-Europe extent is not applied"
    # A WMS outage must be reported as a data failure, not suppress all
    # independent tests of SVG borders, city labels, dark mode and controls.
    try:
        page.wait_for_function(
            "() => { const img=document.getElementById('satImage'); "
            "const fail=document.getElementById('satStatus').dataset.kind==='error'; "
            "return fail || (img.src.includes('-37%2C24%2C19%2C53') "
            "&& img.complete && img.naturalWidth>0); }",
            timeout=55000
        )
    except Exception as error:
        evidence["southwest_load_timeout"]=str(error)[:200]
    evidence["southwest_real_image_loaded"]=page.locator("#satImage").evaluate(
        "(img)=>img.complete && img.naturalWidth>0 && img.src.includes('-37%2C24%2C19%2C53')"
    )
    if not evidence["southwest_real_image_loaded"]:
        evidence["southwest_diagnostics"] = {
            "status": page.locator("#satStatus").inner_text(),
            "image": page.locator("#satImage").evaluate(
                "(img)=>({src:img.src,complete:img.complete,width:img.naturalWidth,height:img.naturalHeight})")
        }
        page.screenshot(path=str(SHOTS/(viewport_label+"-southwest-error.png")),full_page=True)
    page.wait_for_function(
        "() => document.querySelector('#satBordersSvg path')?.getAttribute('d')?.length>1000 "
        "&& document.querySelector('#satCitiesLayer')?.textContent.includes('Ponta Delgada')",
        timeout=12000
    )
    evidence["southwest_real_borders"]=True
    evidence["southwest_city_label"]=page.locator("#satCitiesLayer").inner_text()
    page.locator("#satShowBorders").uncheck()
    evidence["border_toggle_off"]=page.locator("#satBordersSvg").is_hidden()
    assert evidence["border_toggle_off"]
    page.locator("#satShowBorders").check()
    assert page.locator("#satBordersSvg").is_visible()
    page.locator("#satShowCities").uncheck()
    assert page.locator("#satCitiesLayer").is_hidden()
    page.locator("#satShowCities").check()
    page.screenshot(path=str(SHOTS/(viewport_label+"-southwest.png")),full_page=True)
    # Real EUMETSAT GeoColour request for the new North Atlantic coverage.
    page.locator("#satRegion").select_option("atlantic")
    evidence["atlantic_bbox"]="-70%2C15%2C35%2C75" in (page.locator("#satImage").get_attribute("src") or "")
    assert evidence["atlantic_bbox"], "North Atlantic extent is not applied"
    try:
        page.wait_for_function(
            "() => { const img=document.getElementById('satImage'); "
            "const fail=document.getElementById('satStatus').dataset.kind==='error'; "
            "return fail || (img.src.includes('-70%2C15%2C35%2C75') "
            "&& img.complete && img.naturalWidth>0); }",
            timeout=55000
        )
    except Exception as error:
        evidence["atlantic_load_timeout"]=str(error)[:200]
    evidence["atlantic_real_image_loaded"]=page.locator("#satImage").evaluate(
        "(img)=>img.complete && img.naturalWidth>0 && img.src.includes('-70%2C15%2C35%2C75')"
    )
    if not evidence["atlantic_real_image_loaded"]:
        evidence["atlantic_wms_warning"]=page.locator("#satStatus").inner_text()
    # Select the native geostationary projection for full disk.
    page.locator("#satRegion").select_option("disk")
    page.wait_for_timeout(350)
    evidence["full_disk_native_projection"]="AUTO%3A97004" in page.locator("#satImage").get_attribute("src")
    assert evidence["full_disk_native_projection"], "Full-disc projection is not geostationary"
    evidence["disk_overlays_disabled"]=(
        page.locator("#satBordersSvg").is_hidden()
        and page.locator("#satShowBorders").is_disabled()
        and page.locator("#satCitiesLayer").is_hidden()
    )
    assert evidence["disk_overlays_disabled"], "Geographic borders wrongly placed on full disk"
    page.locator("#satRegion").select_option("germany")
    evidence["germany_bbox"]="5%2C47%2C16%2C56" in page.locator("#satImage").get_attribute("src")
    assert evidence["germany_bbox"], "Germany selection did not change bounding box"
    for option in PROD:
        page.locator("#satProduct").select_option(option)
        page.wait_for_timeout(250)
        expected=("mtg_fd%3Air105_hrfi" if option=="ir105" else "mtg_fd%3Argb_"+option)
        evidence[option+"_url"]=expected in page.locator("#satImage").get_attribute("src")
        assert evidence[option+"_url"], "Wrong WMS layer for "+option
    # Source switch cannot falsely identify commissioning images as a stream.
    page.locator("#satSource").select_option("mtgi2")
    evidence["mtgi2_no_live"]="Kein Livestream" in page.locator("#satValid").inner_text()
    evidence["mtgi2_product_disabled"]=not page.locator("#satProduct").is_enabled()
    assert evidence["mtgi2_no_live"] and evidence["mtgi2_product_disabled"]
    page.locator("#satSource").select_option("mtgi1")
    evidence["mtgi1_product_enabled"]=page.locator("#satProduct").is_enabled()
    assert evidence["mtgi1_product_enabled"]
    # Extended film options: 36/48 are available on mobile and desktop.
    page.locator("#satFilmLength").select_option("36")
    evidence["long_film_36"]=page.locator("#satFilmLength").input_value()=="36"
    evidence["automatic_320px"]=page.locator("#satFilmQuality").input_value()=="320"
    assert evidence["long_film_36"] and evidence["automatic_320px"]
    page.locator("#satFilmLength").select_option("48")
    evidence["long_film_48"]=page.locator("#satFilmLength").input_value()=="48"
    assert evidence["long_film_48"]
    page.locator("#satFilmLength").select_option("8")
    evidence["theme_toggle_present"]=page.locator("#dashboardThemeToggle").count()==1
    theme_control="#cdMobileSatelliteTheme" if viewport_label=="mobile" else "#dashboardThemeToggle"
    evidence["theme_control_visible"]=page.locator(theme_control).is_visible()
    assert evidence["theme_control_visible"], "The theme control must be visible and reachable"
    page.locator(theme_control).click()
    evidence["dark_theme_on"]=page.evaluate(
        "()=>document.documentElement.dataset.theme === 'dark'")
    assert evidence["dark_theme_on"], "Dark mode did not toggle"
    # Assess codec availability rather than promising MP4 support everywhere.
    evidence["film_export_capabilities"]=page.evaluate("""() => ({
      canvasCapture: typeof HTMLCanvasElement.prototype.captureStream==='function',
      mediaRecorder: typeof MediaRecorder==='function',
      mp4H264: typeof MediaRecorder==='function' && MediaRecorder.isTypeSupported('video/mp4;codecs=avc1.42E01E'),
      mp4Generic: typeof MediaRecorder==='function' && MediaRecorder.isTypeSupported('video/mp4'),
      webmVp9: typeof MediaRecorder==='function' && MediaRecorder.isTypeSupported('video/webm;codecs=vp9'),
      webCodecs: typeof VideoEncoder==='function',
      createImageBitmap: typeof createImageBitmap==='function'
    })""")
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
