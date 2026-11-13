#!/usr/bin/env python3
"""Phase 2 live test: public DWD charts, real PNG/PDF downloads and mobile widths.

This test never mocks scientific requests or changes original chart datasets.
The GitHub Pages version check prevents a green result on stale frontend code.
"""
from __future__ import annotations
import json
from pathlib import Path
import struct
import time
import urllib.request
from playwright.sync_api import sync_playwright

BASE="https://marcelherber.github.io/climate-dashboard/"
EXPECTED="monthly_frequency.js?v=20261113-phase2-exports-v1"
REPORT=Path("phase2_export_live")
REPORT.mkdir(exist_ok=True)

def check_deployment():
    end=time.monotonic()+600
    while time.monotonic()<end:
        try:
            with urllib.request.urlopen(BASE+"index.html?phase2="+str(time.time()),timeout=25) as handle:
                html=handle.read().decode("utf-8")
                if EXPECTED in html:
                    print("Phase 2 deployed:",EXPECTED,flush=True)
                    return
        except Exception as exc:
            print("Pages probe:",str(exc)[:100],flush=True)
        time.sleep(12)
    raise AssertionError("Phase 2 Pages deployment was not detected within audit window")

def downloaded(info,ext,width):
    path=REPORT/f"climate_frequency_{width}.{ext}"
    info.save_as(str(path))
    raw=path.read_bytes()
    assert len(raw)>12000,(path,len(raw))
    if ext=="png":
        assert raw[:8]==b"\x89PNG\r\n\x1a\n"
        w,h=struct.unpack(">II",raw[16:24])
        assert (w,h)==(2200,1470),(w,h)
        return {"format":"png","width":w,"height":h,"bytes":len(raw)}
    assert raw[:4]==b"%PDF"
    return {"format":"pdf","bytes":len(raw)}

def verify(browser,width):
    context=browser.new_context(
        viewport={"width":width,"height":844 if width<600 else 900},
        device_scale_factor=1,
        is_mobile=width<600,
        has_touch=width<600,
        accept_downloads=True,
        ignore_https_errors=True)
    page=context.new_page()
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)[:250]))
    page.on("dialog",lambda dialog:(errors.append("dialog: "+dialog.message),dialog.dismiss()))
    result={"viewport":width,"passed":False,"downloads":[]}
    try:
        page.goto(BASE+"index.html?tab=monthly",wait_until="domcontentloaded",timeout=90000)
        page.wait_for_function("""() => typeof window.Chart==='function'
            && typeof window.switchTab==='function'
            && !!window.DashboardExportHQ
            && !!document.getElementById('monthlyFrequencyButton')""",timeout=100000)
        page.evaluate("switchTab('monthly')")
        page.locator("#monthlyFrequencyButton").click(timeout=30000)
        page.wait_for_function("""() => {
          const node=document.getElementById('monthlyFrequencyView');
          const chart=window.Chart?.getChart?.('monthlyFrequencyChart');
          return node && !node.hidden && chart?.data?.datasets?.some(
             ds=>ds.data?.some(value=>
               (typeof value==='number'&&Number.isFinite(value))||
               (value && typeof value==='object' &&
                 Number.isFinite(value.x) && Number.isFinite(value.y))
             )
          );
        }""",timeout=70000)
        initial=page.evaluate("""() => {
          const chart=Chart.getChart('monthlyFrequencyChart');
          const area=document.querySelector('.monthly-frequency-export-bar').getBoundingClientRect();
          return {
            count:chart.data.datasets.length,
            nonNull:chart.data.datasets.flatMap(d=>d.data||[]).filter(v=>
              (typeof v==='number'&&Number.isFinite(v)) ||
              (v && typeof v==='object' && Number.isFinite(v.x) && Number.isFinite(v.y))
            ).length,
            viewport:innerWidth,docWidth:document.documentElement.scrollWidth,
            exportLeft:area.left,exportRight:area.right,
            display:getComputedStyle(document.querySelector('.monthly-frequency-export-bar')).display,
            sourceModule:[...document.scripts].some(s=>s.src.includes('monthly_frequency.js?v=20261113-phase2-exports-v1'))
          };
        }""")
        assert initial["nonNull"]>=10,initial
        assert initial["sourceModule"],initial
        assert initial["exportLeft"]>=-3 and initial["exportRight"]<=width+5,initial
        if width<600:
            assert initial["display"] in ("grid","flex"),initial
        result["data"]=initial
        page.locator("#monthlyFrequencyParam").select_option("rain")
        page.wait_for_function("""() => document.getElementById('monthlyFrequencySummary')
          ?.textContent?.includes('Niederschlag')""",timeout=30000)
        result["rain_checked"]=True
        page.locator("#monthlyFrequencyParam").select_option("sun")
        page.wait_for_function("""() => document.getElementById('monthlyFrequencySummary')
          ?.textContent?.includes('Sonnenschein')""",timeout=30000)
        result["sun_checked"]=True
        page.locator("#monthlyFrequencyParam").select_option("temp")
        page.wait_for_function("""() => document.getElementById('monthlyFrequencySummary')
          ?.textContent?.includes('Temperatur')""",timeout=30000)
        if width in (390,1200):
            before=page.evaluate("""() => JSON.stringify(
                Chart.getChart('monthlyFrequencyChart').data.datasets.map(d=>d.data))""")
            for ext in ("png","pdf"):
                button=page.locator("#monthlyFrequencyPngButton" if ext=="png" else "#monthlyFrequencyPdfButton")
                with page.expect_download(timeout=75000) as event:
                    button.click(timeout=40000)
                result["downloads"].append(downloaded(event.value,ext,width))
            after=page.evaluate("""() => JSON.stringify(
                Chart.getChart('monthlyFrequencyChart').data.datasets.map(d=>d.data))""")
            assert before==after,"Source DWD values changed by export"
        page.screenshot(path=str(REPORT/f"screen_climate_frequency_{width}.png"),full_page=False,timeout=30000)
        problem=[x for x in errors if "monthlyFrequency" in x or "Häufigkeitsverteilung" in x or "dialog:" in x]
        assert not problem,problem
        result["passed"]=True
    except Exception as exc:
        result["error"]=str(exc)[:800]
        try:page.screenshot(path=str(REPORT/f"FAILED_{width}.png"),full_page=False,timeout=15000)
        except Exception:pass
    result["page_errors"]=errors[-5:]
    print("PHASE2",json.dumps(result,ensure_ascii=False),flush=True)
    context.close()
    return result

def main():
    check_deployment()
    results=[]
    with sync_playwright() as engine:
        browser=engine.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        try:
            for width in (320,390,430,1200):
                results.append(verify(browser,width))
        finally:
            browser.close()
    (REPORT/"report.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    if not all(item["passed"] for item in results):
        raise SystemExit(1)

if __name__=="__main__":
    main()
