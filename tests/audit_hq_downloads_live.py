#!/usr/bin/env python3
"""Real download smoke test. Uses published DWD/ICON data, no request mocks."""
from pathlib import Path
import json
import struct
import sys
from playwright.sync_api import sync_playwright

ROOT=Path("hq_export_live_audit")
ROOT.mkdir(exist_ok=True)
BASE="https://marcelherber.github.io/climate-dashboard/"
REPORT=[]

def inspect(download,stem,format):
    output=ROOT/(stem+"."+format)
    download.save_as(str(output))
    data=output.read_bytes()
    if format=="png":
        assert data[:8]==b"\x89PNG\r\n\x1a\n","Not a PNG"
        width,height=struct.unpack(">II",data[16:24])
        assert (width,height)==(2200,1470),f"Unexpected export resolution {width}x{height}"
        return {"bytes":len(data),"width":width,"height":height}
    assert data[:4]==b"%PDF","Not a PDF"
    assert len(data)>10000,"PDF has no substantial content"
    return {"bytes":len(data),"pdf_signature":True}

def run(browser,width):
    ctx=browser.new_context(viewport={"width":width,"height":840},
                            is_mobile=width<600,has_touch=width<600,
                            device_scale_factor=1,accept_downloads=True)
    page=ctx.new_page()
    errors=[]
    page.on("pageerror",lambda err:errors.append(str(err)[:500]))
    page.on("dialog",lambda dialog:(errors.append("Dialog: "+dialog.message),dialog.dismiss()))
    entry={"width":width,"from":"live GitHub Pages","checks":[]}
    try:
        page.goto(BASE+"index.html?tab=stationSnow",wait_until="domcontentloaded",timeout=75000)
        page.wait_for_function("""() => {
            const c=document.getElementById("stationSnowChart");
            return !!window.DashboardExportHQ && c && !!window.Chart?.getChart?.(c) &&
              !document.getElementById("stationSnowContent")?.hidden;
        }""",timeout=120000)
        # The newly published shared export system must be used rather than
        # a browser-cached pre-Phase-2 script.
        exporter=page.locator('script[src*="dashboard_export_hq.js?v=20261112-phase2-print-v1"]')
        assert exporter.count()==1,"Updated HQ exporter is not deployed"
        if width<600:
            page.wait_for_function("""() => {
              const canvas=document.getElementById("stationSnowChart");
              return !!canvas && canvas.tabIndex===0 &&
                (canvas.getAttribute("aria-describedby")||"").includes("cdm-chart-tip-") &&
                !!document.getElementById("cdm-chart-tip-"+canvas.id);
            }""",timeout=16000)
            page.locator("#stationSnowChart").focus()
            page.keyboard.press("ArrowRight")
            page.wait_for_function("""() => {
              const chart=Chart.getChart(document.getElementById("stationSnowChart"));
              return chart?.getActiveElements?.()?.length>0;
            }""",timeout=12000)
            entry["checks"].append({"mobile_year_navigation":True,
              "touch_hint":True})
            page.keyboard.press("Escape")
            assert page.evaluate("""() => Chart.getChart(
                document.getElementById("stationSnowChart")).getActiveElements().length""")==0
        panel=page.locator('.chart-export-tools[data-canvas-id="stationSnowChart"]')
        panel.wait_for(state="visible",timeout=30000)
        for kind in ("png","pdf"):
            button=panel.locator("button",has_text=kind.upper()).first
            with page.expect_download(timeout=60000) as event:
                button.click(timeout=30000)
            info=inspect(event.value,"station_snow_"+str(width),kind)
            entry["checks"].append({"chart":kind,**info})
        # The forecast hazard map retains its own calibrated legend and colors.
        # Check its new PDF on a separate real-model page.
        page.goto(BASE+"wettergefahren.html",wait_until="domcontentloaded",timeout=75000)
        page.wait_for_function("""() => {
          const s=window.iconEuHazardExportState?.();
          return !!s?.data && !!s?.decoded && !!window.jspdf?.jsPDF;
        }""",timeout=110000)
        with page.expect_download(timeout=75000) as event:
            page.locator("#exportPdf").click(timeout=30000)
        info=inspect(event.value,"icon_hazards_"+str(width),"pdf")
        entry["checks"].append({"map":"pdf",**info})
        assert not errors,"JavaScript errors or alerts: "+str(errors[-5:])
        entry["passed"]=True
    except Exception as err:
        entry["passed"]=False
        entry["error"]=str(err)[:900]
        try:page.screenshot(path=str(ROOT/("FAIL_"+str(width)+".png")),timeout=15000)
        except Exception:pass
    entry["page_errors"]=errors[-7:]
    REPORT.append(entry)
    ctx.close()

with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
    try:
        for width in (390,1200):run(browser,width)
    finally:browser.close()
(ROOT/"report.json").write_text(json.dumps(REPORT,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(REPORT,ensure_ascii=False,indent=2),flush=True)
sys.exit(0 if all(row["passed"] for row in REPORT) else 1)
