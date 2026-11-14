#!/usr/bin/env python3
"""Deterministic real-Chromium Atlantic PNG/PDF/GIF integration check.

Only satellite pixels and IFS pressure *fixtures* are simulated; the actual
published JS/CSS, browser canvas, PDF writer, GIF encoder and download actions
run unmodified. WMS 1400px requests intentionally fail.
"""
from __future__ import annotations

import http.server
import json
import struct
import tempfile
import threading
import traceback
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/satellite_atlantic_export_test_latest.json"
SHOTS = ROOT / "_satellite_test_screenshots"
SHOTS.mkdir(exist_ok=True)
UTC = timezone.utc
RUN = (datetime.now(UTC)-timedelta(hours=6)).replace(minute=0,second=0,microsecond=0)


def iso(moment):
    return moment.isoformat(timespec="seconds").replace("+00:00","Z")


def ring(lon,lat,r,n=64):
    import math
    return [[lon+r*math.cos(2*math.pi*i/n),
             lat+r*.6*math.sin(2*math.pi*i/n)] for i in range(n+1)]


CONTOURS = [
    {"hpa":995,"lines":[ring(-55,55,3)]},
    {"hpa":1000,"lines":[ring(-55,55,6)]},
    {"hpa":1005,"lines":[ring(-55,55,10)]},
    # Broad, shallow high with just one closed 1020-hPa contour
    {"hpa":1020,"lines":[ring(-25,43,10)]},
]
# A separate fine-resolution contour fixture mimicking the real ECMWF
# 2-hPa sidecars. This MUST NOT be interpolated from 5-hPa contour lines.
FINE_CONTOURS = [
    *[{"hpa":994+2*i,"lines":[ring(-55,55,3+i*1.4)]} for i in range(6)],
    *[{"hpa":1028-2*i,"lines":[ring(-25,43,3+i*1.4)]} for i in range(6)],
    # Open, meteorologically plausible gradients also cross Germany and
    # central Europe; they must appear even without a closed H/T ring.
    {"hpa":1006,"lines":[[[-2,48],[5,49],[11,51],[17,52],[25,54]]]},
    {"hpa":1008,"lines":[[[-2,49],[5,50],[11,52],[17,53],[25,55]]]},
    {"hpa":1010,"lines":[[[-2,50],[5,51],[11,53],[17,54],[25,56]]]},
]
FINE_REGIONS = ["europe","southwest","central","germany"]


def png(width,height,number):
    """Tiny valid generated RGB image, not an actual EUMETSAT observation."""
    def section(kind,payload):
        data=kind+payload
        return struct.pack(">I",len(payload))+data+struct.pack(">I",zlib.crc32(data)&0xffffffff)
    pixel=bytes([30+number%120,70+number%95,120+number%105])
    rows=(b"\x00"+pixel*width)*height
    return (b"\x89PNG\r\n\x1a\n"
            +section(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0))
            +section(b"IDAT",zlib.compress(rows,2))
            +section(b"IEND",b""))


TIMES = [iso(RUN+timedelta(hours=3,minutes=i*10)) for i in range(8)]
RUN_STR = iso(RUN)
RUN_PATH = "r"+RUN.strftime("%Y%m%d%H")


def manifest():
    return {"capabilities_ok":True,"generated_at":iso(datetime.now(UTC)),
            "products":{"geocolour":{
                "map_ok":True,"latest_verified_time":TIMES[-1],
                "available_times":TIMES}}}


def model_index():
    return {"schema_version":2,"model":"ECMWF IFS Open Data",
            "run_utc":RUN_STR,"generated_at":iso(datetime.now(UTC)),
            "time_resolution_minutes":10,"source_interval_hours":3,
            "hours":{"h"+f"{h:02d}":RUN_PATH+"/h"+f"{h:02d}"+".json"
                     for h in range(19)},
            "fine_interval_hpa":2,"fine_regions":FINE_REGIONS,
            "fine_hours":{"h"+f"{h:02d}":RUN_PATH+"/h"+f"{h:02d}"+"_2hpa.json"
                          for h in range(19)}}


def full_model():
    return {"schema_version":1,"model":"ECMWF IFS Open Data",
            "run_utc":RUN_STR,"generated_at":iso(datetime.now(UTC)),
            "resolution_degrees":0.25,"interval_hpa":5,"units":"hPa",
            "field":"mean sea-level pressure","bbox":[-75,12,55,80],
            "frames":[{"valid_utc":iso(RUN+timedelta(hours=h)),
                       "forecast_hour":h,"contours":CONTOURS}
                      for h in range(0,19,3)]}


def hour_chunk(hour,fine=False):
    length=1 if hour==18 else 6
    return {"schema_version":2,"model":"ECMWF IFS Open Data",
            "run_utc":RUN_STR,"hour":hour,
            **({"interval_hpa":2,"regions":FINE_REGIONS} if fine else {}),
            "frames":[{"valid_utc":iso(RUN+timedelta(hours=hour,minutes=i*10)),
                       "forecast_minute":hour*60+i*10,
                       "interpolated":(hour*6+i)%18!=0,
                       "contours":FINE_CONTOURS if fine else CONTOURS}
                      for i in range(length)]}


class Server(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT),**kwargs)
    def log_message(self,*args):
        pass


def exercise(browser,device,base,tmp):
    context=browser.new_context(
        viewport={"width":1440,"height":900} if device=="desktop"
        else {"width":390,"height":844},
        is_mobile=device=="mobile",has_touch=device=="mobile",
        accept_downloads=True,
    )
    page=context.new_page()
    details={"device":device,"simulated_wms":True}
    requested=[]

    def handler(route):
        url=route.request.url
        path=urlsplit(url).path
        if path.endswith("/data/satellite_wms_times.json"):
            route.fulfill(status=200,body=json.dumps(manifest()),content_type="application/json")
        elif path.endswith("/data/satellite_mslp/preview.json") or path.endswith("/data/satellite_mslp/latest.json"):
            route.fulfill(status=200,body=json.dumps(full_model()),content_type="application/json")
        elif path.endswith("/data/satellite_mslp/ten_minute/index.json"):
            route.fulfill(status=200,body=json.dumps(model_index()),content_type="application/json")
        elif "/data/satellite_mslp/ten_minute/" in path and path.endswith(".json"):
            filename=Path(path).stem
            fine=filename.endswith("_2hpa")
            hour=int(filename[1:3])
            route.fulfill(status=200,body=json.dumps(hour_chunk(hour,fine=fine)),
                          content_type="application/json")
        elif "geoserver/wms" in url:
            q=parse_qs(urlsplit(url).query)
            width=int(q.get("width",["1400"])[0])
            height=int(q.get("height",["850"])[0])
            requested.append({"width":width,"time":q.get("time",[""])[0],
                              "bbox":q.get("bbox",[""])[0]})
            if width>720:
                route.fulfill(status=504,body="Simulated upstream WMS timeout")
            else:
                route.fulfill(status=200,body=png(width,height,len(requested)),
                    content_type="image/png",headers={"Access-Control-Allow-Origin":"*"})
        else:
            route.continue_()

    page.route("**/*",handler)
    page.goto(base+"/satelliten.html",wait_until="domcontentloaded",timeout=20000)
    page.wait_for_function(
        "()=>document.querySelector('#satTime')?.options.length>=8",timeout=15000)
    # Exercise both fine and default modes with real browser rendering.
    assert page.locator("#satIsobarSpacing").input_value()=="5"
    for area in ("europe","southwest","central","germany"):
        page.locator("#satRegion").select_option(area)
        fine_option=page.locator('#satIsobarSpacing option[value="2"]')
        assert fine_option.count()==1 and fine_option.is_enabled()
        assert not fine_option.evaluate("(o) => o.hidden")
        page.locator("#satIsobarSpacing").select_option("2")
        page.wait_for_function(
            "()=>document.querySelector('#satIsobarStatus')?.textContent.includes('2 hPa')"
            "&&document.querySelectorAll('#satIsobarSvg path').length>0",
            timeout=15000)
        widths=page.locator("#satIsobarSvg path[stroke='#c6a2bb']").evaluate_all(
            "(els)=>[...new Set(els.map(p=>Number(p.getAttribute('stroke-width'))))]")
        assert widths==[0.58],(area,widths)
        details["fine_2hpa_"+area]={"positive_lines":len(page.locator(
            "#satIsobarSvg path[stroke='#c6a2bb']").all()),"widths":widths}
        if area=="europe":
            screenshot=SHOTS/(device+"-europe-2hpa-synthetic.png")
            page.screenshot(path=str(screenshot))
            details["europe_2hpa_screenshot"]=screenshot.name
            page.wait_for_function(
                "()=>!document.querySelector('#satPdfIsobars').disabled",
                timeout=15000)
            with page.expect_download(timeout=25000) as info:
                page.locator("#satPdfIsobars").click()
            artifact=info.value
            target=Path(tmp)/(device+"_europe_2hpa.pdf")
            artifact.save_as(target)
            raw=target.read_bytes()
            assert raw.startswith(b"%PDF-1.4")
            assert b"Abstand 2 hPa" in raw
            details["europe_2hpa_pdf"]={"bytes":len(raw),"filename":artifact.suggested_filename}
        page.locator("#satIsobarSpacing").select_option("5")
        assert page.locator("#satIsobarSpacing").input_value()=="5"
    page.locator("#satRegion").select_option("atlantic")
    assert page.locator("#satIsobarSpacing").input_value()=="5"
    assert not page.locator('#satIsobarSpacing option[value="2"]').is_enabled()
    assert page.locator('#satIsobarSpacing option[value="2"]').evaluate("(o)=>o.hidden")
    details["atlantic_fine_disabled"]=True
    page.wait_for_function(
        "()=>document.querySelector('#satImage')?.naturalWidth>0&&"
        "!document.querySelector('#satPngIsobars')?.disabled",timeout=15000)
    page.wait_for_function(
        "()=>document.querySelectorAll('#satIsobarSvg .sat-pressure-center').length>=2",
        timeout=18000)
    letters=page.locator("#satIsobarSvg .sat-pressure-center").all_text_contents()
    assert "T" in letters and "H" in letters,letters
    details["pressure_letters"]=letters
    screenshot=SHOTS/(device+"-atlantic-ht-synthetic.png")
    page.screenshot(path=str(screenshot))
    details["atlantic_ht_screenshot"]=screenshot.name

    # The native 1400px WMS request is deliberately broken. Our fix must use
    # smaller CORS-safe imagery, preserving the original bbox and selected UTC.
    for button,extension in [
        ("#satPng","png"),("#satPngIsobars","png"),("#satPdfIsobars","pdf")
    ]:
        with page.expect_download(timeout=25000) as info:
            page.locator(button).click()
        artifact=info.value
        target=Path(tmp)/(device+"_"+button.lstrip("#")+"."+extension)
        artifact.save_as(target)
        raw=target.read_bytes()
        assert len(raw)>100, (button,len(raw))
        assert "_atlantic_" in artifact.suggested_filename
        if extension=="png":
            assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        else:
            assert raw.startswith(b"%PDF-1.4")
            assert b"/Subtype /Image" in raw
            assert b"(H) Tj ET" in raw and b"(T) Tj ET" in raw
        details[button.lstrip("#")]={"filename":artifact.suggested_filename,
                                     "size":len(raw),"valid":True}

    # Globe view is not an EPSG:4326 pressure overlay; it must never expose 2 hPa.
    page.locator("#satRegion").select_option("disk")
    assert page.locator("#satIsobarSpacing").is_disabled()
    assert page.locator('#satIsobarSpacing option[value="2"]').evaluate("(o)=>o.hidden")
    assert page.locator("#satIsobarSvg").is_hidden()
    page.locator("#satRegion").select_option("atlantic")
    page.locator("#satFilmLength").select_option("6")
    page.locator("#satFilmQuality").select_option("320")
    page.locator("#satPlay").click()
    page.wait_for_function(
        "()=>!document.querySelector('#satGifIsobars').disabled",timeout=25000)
    with page.expect_download(timeout=25000) as gif_info:
        page.locator("#satGifIsobars").click()
    animation=gif_info.value
    target=Path(tmp)/(device+"_atlas_pressure.gif")
    animation.save_as(target)
    gif=target.read_bytes()
    assert gif.startswith(b"GIF89a") and len(gif)>1000
    assert "_isobaren" in animation.suggested_filename
    details["gif"]={"size":len(gif),"filename":animation.suggested_filename}

    atlantic_requests=[x for x in requested if x["bbox"]=="-70,15,35,75"]
    export_wms=[x for x in atlantic_requests if x["width"]==720]
    assert export_wms, "No CORS-safe 720px Atlantic image requested"
    assert all(x["time"] in TIMES for x in requested if x["time"])
    details["export_720px_requests"]=len(export_wms)
    details["all_WMS_requests"]=len(requested)
    context.close()
    return details


def main():
    result={"tested_at":iso(datetime.now(UTC)),
            "mode":"synthetic imagery and model geometry, real browser export code"}
    server=http.server.ThreadingHTTPServer(("127.0.0.1",0),Server)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="atlantic-export-") as tmp:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
                try:
                    url="http://127.0.0.1:"+str(server.server_port)
                    for device in ("desktop","mobile"):
                        try:result[device]=exercise(browser,device,url,tmp)
                        except Exception as error:
                            result[device]={"error":repr(error),
                                            "traceback":traceback.format_exc(limit=8)[-2500:]}
                finally:browser.close()
    finally:server.shutdown()
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if any("error" in result.get(device,{}) for device in ("desktop","mobile")) else 0


if __name__=="__main__":
    raise SystemExit(main())
