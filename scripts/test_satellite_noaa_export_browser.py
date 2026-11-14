#!/usr/bin/env python3
"""Desktop/mobile Chromium verification using *real archived NOAA WPC coordinates*.

The WPC geometry, type and valid UTC come unchanged from a verified official
analysis fixture. Only EUMETSAT image pixels and ECMWF isobar fields are mocked
to make the browser/export test deterministic and avoid an upstream outage.
Browser clock is frozen close to the actual 2026-11-14 analysis; this is not
a claim that the historical bulletin is current today.
"""
from __future__ import annotations

import http.server
import json
import tempfile
import threading
import traceback
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

from playwright.sync_api import sync_playwright
import test_satellite_atlantic_export_browser as base

ROOT=Path(__file__).resolve().parents[1]
GEO=json.loads((ROOT/"tests/fixtures/noaa_wpc_verified_20261114.json").read_text(encoding="utf-8"))
VALID=datetime.fromisoformat(GEO["valid_utc"].replace("Z","+00:00"))
# The actual WPC geometry and analysis time remain unchanged.
base.RUN=VALID-timedelta(hours=1)
base.RUN_STR=base.iso(base.RUN)
base.RUN_PATH="r"+base.RUN.strftime("%Y%m%d%H")
base.TIMES=[base.iso(base.RUN+timedelta(hours=3,minutes=i*10)) for i in range(8)]
FROZEN=base.iso(VALID+timedelta(hours=5))
OUT=ROOT/"data/satellite_noaa_export_browser_latest.json"
SHOTS=ROOT/"_satellite_test_screenshots"
SHOTS.mkdir(exist_ok=True)

def exercise(browser,device,url,tmp):
    context=browser.new_context(
        viewport={"width":1440,"height":900} if device=="desktop" else {"width":390,"height":844},
        is_mobile=device=="mobile",has_touch=device=="mobile",accept_downloads=True)
    page=context.new_page()
    page.add_init_script("Date.now = () => Date.parse("+json.dumps(FROZEN)+");")
    details={"device":device,"source":"verified NOAA WPC 2026-11-14 00 UTC coordinates",
             "real_noaa_lines":len(GEO["features"]),
             "satellite_pixels":"simulated WMS fixture","ecmwf_isobars":"deterministic fixture",
             "frozen_browser_time":FROZEN}
    seen=[]
    def handler(route):
        request=route.request.url
        path=urlsplit(request).path
        if path.endswith("/data/synoptic_charts/noaa_wpc_fronts_geo.json"):
            route.fulfill(status=200,body=json.dumps(GEO),content_type="application/json")
        elif path.endswith("/data/satellite_wms_times.json"):
            route.fulfill(status=200,body=json.dumps(base.manifest()),content_type="application/json")
        elif path.endswith("/data/satellite_mslp/preview.json") or path.endswith("/data/satellite_mslp/latest.json"):
            route.fulfill(status=200,body=json.dumps(base.full_model()),content_type="application/json")
        elif path.endswith("/data/satellite_mslp/ten_minute/index.json"):
            route.fulfill(status=200,body=json.dumps(base.model_index()),content_type="application/json")
        elif "/data/satellite_mslp/ten_minute/" in path and path.endswith(".json"):
            stem=Path(path).stem
            hour=int(stem[1:3])
            route.fulfill(status=200,body=json.dumps(base.hour_chunk(hour,stem.endswith("_2hpa"))),
                          content_type="application/json")
        elif "geoserver/wms" in request:
            q=parse_qs(urlsplit(request).query)
            w=int(q.get("width",["400"])[0]);h=int(q.get("height",["200"])[0])
            seen.append({"width":w,"bbox":q.get("bbox",[""])[0],"time":q.get("time",[""])[0]})
            if w>720:
                route.fulfill(status=504,body="Simulated upstream large-map timeout")
            else:
                route.fulfill(status=200,body=base.png(w,h,len(seen)),
                    content_type="image/png",headers={"Access-Control-Allow-Origin":"*"})
        else:
            route.continue_()
    page.route("**/*",handler)
    page.goto(url+"/satelliten.html",wait_until="domcontentloaded",timeout=20000)
    page.wait_for_function("()=>document.querySelector('#satTime')?.options.length>=8",timeout=16000)
    page.locator("#satRegion").select_option("atlantic")
    page.wait_for_function("()=>!document.querySelector('#satWpcFrontSvg').hasAttribute('hidden') && document.querySelectorAll('#satWpcFrontSvg path').length>0",
                           timeout=18000)
    actual=page.locator("#satWpcFrontSvg path").count()
    assert actual>=2 and actual%2==0,("NOAA over image",actual)
    details["noaa_satellite_svg_paths"]=actual
    details["noaa_atlantic_lines"]=actual//2
    details["noaa_status"]=page.locator("#satWpcFrontStatus").inner_text()
    details["date_label"]=page.locator("#satWpcFrontUTC").inner_text()
    assert "NOAA WPC" in details["date_label"],details
    assert page.locator("#satShowWpcFronts").is_checked()
    assert not page.evaluate("()=>document.documentElement.scrollWidth>innerWidth+3"),"Mobile viewport overflows"
    page.screenshot(path=str(SHOTS/(device+"-noaa-real-lines-synthetic-satellite.png")))
    page.wait_for_function("()=>!document.querySelector('#satPngIsobars').disabled && !document.querySelector('#satPdfIsobars').disabled",
                           timeout=17000)
    for ident,ext in [("satPngIsobars","png"),("satPdfIsobars","pdf")]:
        with page.expect_download(timeout=35000) as download:
            page.locator("#"+ident).click()
        item=download.value
        assert "_noaa_fronten."+ext in item.suggested_filename,item.suggested_filename
        target=Path(tmp)/(device+"_"+ident+"."+ext)
        item.save_as(target)
        raw=target.read_bytes()
        if ext=="png":
            assert raw.startswith(bytes([137,80,78,71,13,10,26,10])),"Wrong PNG header"
        else:
            assert raw.startswith(b"%PDF-1.4")
            assert b"NOAA WPC analyzed frontal vectors" in raw
            assert b"/Subtype /Image" in raw
            assert raw.count(bytes([10])+b"S"+bytes([10])+b"Q")>=actual//2,"Front vector strokes are missing"
        details[ident]={"filename":item.suggested_filename,"bytes":len(raw)}
    page.locator("#satFilmLength").select_option("6")
    page.locator("#satFilmQuality").select_option("320")
    page.locator("#satPlay").click()
    page.wait_for_function("()=>!document.querySelector('#satGifIsobars').disabled",timeout=30000)
    with page.expect_download(timeout=30000) as download:
        page.locator("#satGifIsobars").click()
    item=download.value
    target=Path(tmp)/(device+"_noaa.gif")
    item.save_as(target)
    raw=target.read_bytes()
    assert raw.startswith(b"GIF89a") and len(raw)>1500
    assert "_noaa_fronten.gif" in item.suggested_filename,item.suggested_filename
    details["gif"]={"filename":item.suggested_filename,"bytes":len(raw)}
    # The switch is shared: screen and exports must both suppress NOAA lines.
    page.locator("#satShowWpcFronts").uncheck()
    assert page.locator("#satWpcFrontSvg").is_hidden()
    details["toggle_hides_noaa"]=True
    with page.expect_download(timeout=30000) as download:
        page.locator("#satPngIsobars").click()
    assert "_noaa_fronten" not in download.value.suggested_filename
    page.locator("#satRegion").select_option("germany")
    page.wait_for_function("()=>document.querySelector('#satWpcFrontSvg').hasAttribute('hidden')",timeout=12000)
    details["germany_no_fake_noaa_fronts"]=True
    details["wms_requests"]=len(seen)
    context.close()
    return details

def main():
    results={"geometry_source_url":GEO.get("source_url"),"valid_utc":GEO["valid_utc"],
             "tested_at":base.iso(datetime.now(timezone.utc)),
             "mode":"real NOAA WPC geographic polylines; deterministic satellite pixels and ECMWF contours"}
    assert GEO["status"]=="verified" and len(GEO["features"])==46
    server=http.server.ThreadingHTTPServer(("127.0.0.1",0),base.Server)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="noaa-front-export-") as tmp:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
                try:
                    addr="http://127.0.0.1:"+str(server.server_port)
                    for device in ("desktop","mobile"):
                        try:results[device]=exercise(browser,device,addr,tmp)
                        except Exception as exc:
                            results[device]={"error":repr(exc),
                              "traceback":traceback.format_exc(limit=8)[-2700:]}
                finally:browser.close()
    finally:server.shutdown()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(results,ensure_ascii=False,indent=2)+chr(10),encoding="utf-8")
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return int(any("error" in results.get(device,{}) for device in ("desktop","mobile"))

if __name__=="__main__":
    raise SystemExit(main())
