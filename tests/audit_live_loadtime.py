#!/usr/bin/env python3
"""Cold-load real GitHub Pages data on mobile and desktop; no mocks or intercepts."""
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from playwright.sync_api import sync_playwright

BASE="https://marcelherber.github.io/climate-dashboard/index.html"
OUTPUT=Path("live_loadtime_audit")
OUTPUT.mkdir(parents=True,exist_ok=True)
cases=[]
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
    try:
        for width in (390,1200):
            for tab in ("stationSnow","stationPrecip"):
                context=browser.new_context(
                    viewport={"width":width,"height":840},
                    is_mobile=width<600,has_touch=width<600,
                    service_workers="block",device_scale_factor=1)
                page=context.new_page()
                failures=[]
                page.on("pageerror",lambda error:failures.append(str(error)[:300]))
                item={"width":width,"tab":tab,"from":"live GitHub Pages",
                      "cold_context":True}
                started=perf_counter()
                try:
                    response=page.goto(BASE+"?tab="+tab,
                                       wait_until="domcontentloaded",timeout=70000)
                    item["html_status"]=response.status if response else None
                    item["html_ready_ms"]=round((perf_counter()-started)*1000)
                    page.wait_for_function("""tab => {
                        const panel=document.getElementById(tab+"Content");
                        const canvas=document.getElementById(tab+"Chart");
                        return panel && !panel.hidden && canvas &&
                          !!window.Chart?.getChart?.(canvas);
                    }""",arg=tab,timeout=120000)
                    item["chart_ready_ms"]=round((perf_counter()-started)*1000)
                    item["station_count"]=page.evaluate("""tab => {
                        const index=tab==="stationSnow"?
                          window.stationSnowIndex:window.stationPrecipIndex;
                        return index?.stations?.length||null;
                    }""",tab)
                    item["resources"]=page.evaluate("""() =>
                        performance.getEntriesByType("resource")
                          .filter(e=>/\.json(?:\?|$)|\.js(?:\?|$)/.test(e.name))
                          .sort((a,b)=>b.duration-a.duration).slice(0,12)
                          .map(e=>({
                             name:e.name.split("?")[0].split("/").pop(),
                             duration_ms:Math.round(e.duration),
                             decoded_bytes:e.decodedBodySize||null,
                             transferred_bytes:e.transferSize||null
                          }))""")
                    item["passed"]=True
                except Exception as error:
                    item["passed"]=False
                    item["error"]=str(error)[:600]
                item["page_errors"]=failures[-5:]
                cases.append(item)
                context.close()
    finally:
        browser.close()
report={"created_utc":datetime.now(timezone.utc).isoformat(),
        "method":"real cold browser data, Playwright Chromium; latency includes network",
        "results":cases}
(OUTPUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),
                                  encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
if not all(c["passed"] for c in cases):
    raise SystemExit(1)
