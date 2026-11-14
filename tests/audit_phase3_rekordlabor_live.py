#!/usr/bin/env python3
"""End-to-end Phase 3 acceptance on the public deployed site with original DWD files.
No route interception, no mocked results, no synthetic station observations.
"""
from __future__ import annotations
import json, time, urllib.request, traceback
from pathlib import Path
from xml.etree import ElementTree as ET
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

BASE="https://marcelherber.github.io/climate-dashboard/"
OUT=Path("rekordlabor_live_reports")
OUT.mkdir(exist_ok=True)
RESULTS=[]

def await_published():
    for _ in range(32):
        try:
            with urllib.request.urlopen(BASE+"stations_rekordlabor.html?qa="+str(time.time()),timeout=16) as response:
                txt=response.read().decode("utf8")
            if ('id="rlChanges"' in txt and 'id="rlMap"' in txt and 'stations_rekordlabor.js?v=20261114-p3' in txt):return
        except Exception as error:
            print("Phase3 release probe:",str(error)[:140],flush=True)
        time.sleep(15)
    raise RuntimeError("GitHub Pages did not publish the Phase 3 records page")

def inspect(download,slug,ext):
    output=OUT/(slug+"."+ext)
    download.save_as(str(output))
    raw=output.read_bytes()
    assert len(raw)>500,"Empty export"
    if ext=="pdf":
        assert raw[:4]==b"%PDF"
        pdf=PdfReader(output)
        assert len(pdf.pages)==1 and b" m" in pdf.pages[0].get_contents().get_data()
        images=(pdf.pages[0].get("/Resources") or {}).get("/XObject")
        if images:
            assert not any(x.get_object().get("/Subtype")=="/Image" for x in images.get_object().values())
    elif ext=="svg":
        root=ET.fromstring(raw);ns="{http://www.w3.org/2000/svg}"
        assert len(list(root.iter(ns+"path")))>2
        assert not list(root.iter(ns+"image"))
    elif ext=="png":
        assert raw[:8]==b"\x89PNG\r\n\x1a\n"
    else: assert b"Datum" in raw or b"Jahr" in raw or b"Zeitpunkt" in raw
    return len(raw)

def downloads(page,panel,slug):
    for ext in ("svg","pdf","csv","png"):
        with page.expect_download(timeout=60000) as event:
            page.locator(f"#{panel} [data-rl-export='{ext}']").click(timeout=20000)
        file=event.value
        assert file.suggested_filename.endswith("."+ext)
        n=inspect(file,slug,ext)
        print("REKORDLABOR REAL EXPORT",slug,ext,n,flush=True)

def validate_layout(page,width):
    geometry=page.evaluate("""()=>({
      width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,
      controls:[...document.querySelectorAll('.rl-tabs button')].filter(n=>{
        const r=n.getBoundingClientRect();return r.right>innerWidth+2||r.left<-2;
      }).length})""")
    assert geometry["scroll"]<=geometry["width"]+3,geometry
    assert geometry["controls"]==0,geometry
    return geometry

def test(browser,width):
    ctx=browser.new_context(viewport={"width":width,"height":860},
       accept_downloads=True,has_touch=width<600,is_mobile=width<600,ignore_https_errors=True)
    page=ctx.new_page();errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)[:400]))
    result={"width":width,"ok":False,"cases":[]}
    try:
        page.goto(BASE+"stations_rekordlabor.html?qa="+str(time.time()),
                  wait_until="domcontentloaded",timeout=75000)
        page.wait_for_function("""()=>/historische Jahre/.test(document.getElementById('rlStation')?.textContent||'')""",
                               timeout=100000)
        station=page.locator("#rlStation").inner_text()
        assert "01420" in station,f"Frankfurt initial station missing: {station}"
        page.wait_for_function("""()=>document.getElementById('rlMapStatus')?.textContent.includes('Stationsstandorte')""",timeout=35000)
        assert page.locator("#rlMap.leaflet-container").count()==1,"Original DWD station map absent"
        result["map"]=page.locator("#rlMapStatus").inner_text()
        page.wait_for_function("""()=>document.getElementById("rlCalendarTable")?.querySelectorAll("tr").length>=5""",
                               timeout=45000)
        cover=page.locator("#rlCalendarMeta").inner_text()
        assert "DWD CDC" in cover and "gültige" in cover,cover
        rows=page.locator("#rlCalendarTable tr").count()
        assert rows==10,rows
        first=page.locator("#rlCalendarTable tr").first.inner_text()
        assert "°C" in first
        result["station"]=station;result["calendar_rows"]=rows
        downloads(page,"rlCalendar",f"calendar_{width}")
        result["cases"].append("original_temperature_calendar")
        page.locator("#rlDay").select_option("02-29")
        leap=page.locator("#rlCalendarMeta").inner_text()
        assert "DWD CDC" in leap,leap
        leap_dates=page.locator("#rlCalendarAllYears tr").evaluate_all("(rows)=>rows.map(row=>row.textContent.trim())")
        result["leap_probe"]={"days":leap_dates[:10],"count":len(leap_dates),"meta":leap}
        assert leap_dates and all(".02." in row for row in leap_dates), "February 29 leap-year list incorrect: "+repr(result["leap_probe"])
        result["phase"]="select leap day snow"
        page.locator("#rlCalMetric").select_option("snow")
        page.wait_for_function("""()=>document.getElementById('rlCalendarMeta')?.textContent?.includes('Schneehöhe SHK_TAG')""",
                               timeout=40000)
        result["cases"].append("real_snow_day_calendar_leap")
        result["phase"]="season module"
        page.locator("#rlTabSeasons").click()
        page.wait_for_function("""()=>document.getElementById('rlSeasonMeta')?.textContent?.includes('DWD CDC')""",
                               timeout=30000)
        result["season"]=page.locator("#rlSeasonMeta").inner_text()
        downloads(page,"rlSeasons",f"season_{width}")
        page.locator("#rlSeasonMetric").select_option("hotFirst")
        assert "Frühester heißer Tag" in page.locator("#rlSeasonMeta").inner_text()
        page.locator("#rlSeasonMetric").select_option("snowRun")
        assert "Schneedecke" in page.locator("#rlSeasonMeta").inner_text()
        result["cases"].append("true_qualified_seasonal_records")

        result["phase"]="hourly weather changes"
        page.locator("#rlTabChanges").click()
        page.wait_for_function("""()=>/Archiv|DWD|Stunden/.test(document.getElementById('rlChangeMeta')?.textContent||'')""",
                               timeout=70000)
        page.wait_for_timeout(900)
        change_status=page.locator("#rlChangeMeta").inner_text()
        result["weather_status"]=change_status
        if page.locator("#rlChangeStation option").count()>=1:
            available=page.locator("#rlChangeStation option").count()
            assert available>0
            page.wait_for_function("""()=>document.getElementById('rlChangeTable')?.querySelector('tr[data-rl-event]')""",
                                   timeout=70000)
            weather=page.locator("#rlChangeMeta").inner_text()
            assert "DWD CDC" in weather and "geprüfte Messwertpaare" in weather,weather
            result["weather"]=weather
            downloads(page,"rlChanges",f"weather_{width}")
            page.locator("#rlChangeHours").select_option("6")
            assert page.locator("#rlChangeTable tr[data-rl-event]").count()>0
            page.locator("#rlChangeMetric").select_option("pressure")
            page.locator("#rlChangeHours").select_option("1")
            page.wait_for_function("""()=>document.getElementById('rlChangeMeta')?.textContent.includes('pressure')""",timeout=30000)
            pvalues=page.locator("#rlChangeTable tr[data-rl-event]").all_inner_texts()
            assert pvalues and "hPa" in pvalues[0],"Validated DWD hourly pressure records missing"
            doc=page.evaluate("""async()=>await (await fetch('data/rekordlabor/weather_turns/00164.json',{cache:'no-store'})).json()""")
            assert "930" in doc["metrics"]["pressure"]["quality_notes"],"Unverified historical P0 data present"
            hourly=doc["metrics"]["pressure"]["windows"]["1"]
            assert abs(hourly["up"][0]["delta"])<=8 and abs(hourly["down"][0]["delta"])<=8
            result["pressure_qc"]={"up":hourly["up"][0]["delta"],"down":hourly["down"][0]["delta"]}
            page.locator("#rlChangeMetric").select_option("wind_direction")
            assert page.locator("#rlChangeTable tr[data-rl-event]").count()>0,"DWD wind shifts missing"
            result["cases"].append("real_hourly_dwd_changes_pressure_qc_wind")
        else:
            assert "kein" in change_status.lower() or "noch" in change_status.lower(),change_status
            result["cases"].append("hourly_archive_not_yet_published")

        result["layout"]=validate_layout(page,width)
        assert not errors,f"Browser errors: {errors}"
        result["ok"]=True
        page.screenshot(path=str(OUT/f"rekordlabor_{width}.png"),timeout=22000)
    except Exception as error:
        result["error"]=repr(error)[:1600]
        result["traceback"]=traceback.format_exc()[-1800:]
        try:page.screenshot(path=str(OUT/f"FAILED_rekordlabor_{width}.png"),timeout=15000)
        except Exception:pass
    result["page_errors"]=errors[-5:]
    RESULTS.append(result)
    print("PHASE3 REKORDLABOR LIVE",json.dumps(result,ensure_ascii=False),flush=True)
    ctx.close()

def main():
    await_published()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        try:
            for width in (390,1200):test(browser,width)
        finally:browser.close()
    (OUT/"report.json").write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding="utf8")
    assert all(x["ok"] for x in RESULTS),"Phase3 original-station desktop/mobile test failed"
    print("PHASE3 COMPLETE LIVE QUALITY",RESULTS,flush=True)

if __name__=="__main__":main()
