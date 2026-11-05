#!/usr/bin/env python3
"""Live real-data Chromium regression for the DWD snow-height station tab.

The complete page and station data come from GitHub Pages. Never mock DWD values.
The year selector must expose real published daily history, not annual summaries.
"""
from pathlib import Path
import json
import sys
from playwright.sync_api import sync_playwright

BASE="https://marcelherber.github.io/climate-dashboard/index.html"
OUT=Path("snow_year_browser_audit")
OUT.mkdir(exist_ok=True)
cases=[]


def document_active_is_snow(page):
    return page.locator(".tab-content.active").first.get_attribute("id")=="stationSnow"

def choose_snow_station(page, name, station_id):
    """Use the bounded searchable dropdown; all ~5,600 stations are indexed."""
    page.locator("#stationSnowSearch").fill(name)
    button=page.locator(f'#stationSnowSuggestions button[data-station-id="{station_id}"]')
    button.wait_for(state="visible",timeout=20000)
    button.click(timeout=20000)
    assert page.locator("#stationSnowStationSelect").input_value()==station_id

def run_case(browser,width):
    mobile=width<600
    context=browser.new_context(
        viewport={"width":width,"height":840},device_scale_factor=1,
        is_mobile=mobile,has_touch=mobile,reduced_motion="reduce")
    page=context.new_page()
    failures=[]
    page.on("pageerror",lambda error:failures.append(str(error)[:200]))
    result={"width":width,"mobile":mobile}
    try:
        page.goto(BASE+"?tab=stationSnow",wait_until="domcontentloaded",timeout=70000)
        page.wait_for_function("""()=>
          document.querySelector('#stationSnowStationSelect option') &&
          !document.querySelector('#stationSnowContent').hidden
        """,timeout=80000)
        choose_snow_station(page,"Nürnberg","03668")
        page.wait_for_function("""()=>
          document.querySelector('.tab-content.active')?.id==='stationSnow' &&
          document.querySelector('#stationSnowSummary')?.textContent.includes('Nürnberg')
        """,timeout=60000)
        page.wait_for_timeout(1600)  # regression: delayed dashboard state restoration
        active=page.locator(".tab-content.active").first.get_attribute("id")
        assert active=="stationSnow",f"Station selection changed to tab {active!r}"
        result["station_selected"]="03668"
        choose_snow_station(page,"Zugspitze","05792")
        page.wait_for_function("""()=>
          document.querySelector('#stationSnowSummary')?.textContent.includes('Zugspitze') &&
          document.querySelector('#stationSnowYearsList input[data-snow-year]')
        """,timeout=60000)
        options=page.locator("#stationSnowYearsList input[data-snow-year]")
        count=options.count()
        result["year_count"]=count
        assert count>=30,f"Historical per-year archive not published (only {count} years)"
        historic=page.locator('#stationSnowYearsList input[data-snow-year="2025"]')
        assert historic.count()==1,"Historical year 2025 not in the checklist"
        historic.check(force=True)
        page.wait_for_function("""()=>
          typeof stationSnowChart!=="undefined" && stationSnowChart?.data?.datasets?.some(
            item=>item.label==='Hydrologisches Jahr 2025' &&
            item.data?.some(value=>value!==null))
        """,timeout=30000)
        # Accumulated snow-height comparison from real SHK_TAG series.
        page.wait_for_function("""() => {
          const d=window.stationSnowAccumulationChart?.data?.datasets;
          return d?.some(item=>item.label?.includes("Hydrologisches Jahr 2025")
            && item.data.some(value=>value!==null && value>0));
        }""",timeout=30000)
        page.locator("#stationSnowCumStart").select_option("12-01")
        page.locator("#stationSnowCumEnd").select_option("02-28")
        page.wait_for_function("""() =>
          document.getElementById("stationSnowCumPreset")?.value==="custom" &&
          window.stationSnowAccumulationChart?.data?.labels?.[0]==="01.12." &&
          window.stationSnowAccumulationChart?.data?.labels?.at(-1)==="28.02."
        """,timeout=30000)
        result["accumulation"]=page.evaluate("""() => ({
          start:document.getElementById("stationSnowCumStart").value,
          end:document.getElementById("stationSnowCumEnd").value,
          summary:document.getElementById("stationSnowCumSummary").textContent,
          series:stationSnowAccumulationChart.data.datasets.map(item=>({
            label:item.label,last:item.data.at(-1)
          }))
        })""")
        assert any("2025" in item["label"] and (item["last"] or 0)>0
                   for item in result["accumulation"]["series"])
        assert document_active_is_snow(page),"Snow accumulation period changed active tab"
        # Switching stations preserves the custom period but loads the other
        # station's authentic daily series and must not navigate to Europa.
        choose_snow_station(page,"Nürnberg","03668")
        page.wait_for_function("""() =>
          document.getElementById("stationSnowSummary")?.textContent.includes("Nürnberg") &&
          window.stationSnowAccumulationChart?.options?.plugins?.title?.text?.includes("Nürnberg")
        """,timeout=45000)
        assert page.locator("#stationSnowCumStart").input_value()=="12-01"
        assert page.locator("#stationSnowCumEnd").input_value()=="02-28"
        assert document_active_is_snow(page),"Station change navigated away from snow accumulation"
        result["range_persisted_after_station_switch"]=True
        result.update(page.evaluate("""() => ({
          activeTab:document.querySelector('.tab-content.active')?.id,
          plottedYears:stationSnowChart.data.datasets.filter(
            d=>d.label?.startsWith('Hydrologisches Jahr ')).map(d=>d.label),
          deviationYears:stationSnowDeviationChart.data.datasets.map(d=>d.label),
          status:document.getElementById('stationSnowYearsStatus')?.textContent
        })"""))
        assert result["activeTab"]=="stationSnow","Historical selection switched tabs"
        assert any("2025" in item for item in result["deviationYears"])
        assert not failures,f"Browser JavaScript errors: {failures[-3:]}"
        page.screenshot(path=str(OUT/f"snow_{width}.png"),full_page=False,timeout=15000)
        result["ok"]=True
    except Exception as error:
        result["ok"]=False
        result["error"]=str(error)[:750]
        try:page.screenshot(path=str(OUT/f"FAIL_snow_{width}.png"),full_page=False,timeout=15000)
        except Exception:pass
    result["page_errors"]=failures[-6:]
    cases.append(result)
    context.close()

with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
    try:
        for width in (390,1200):
            run_case(browser,width)
    finally:
        browser.close()

(OUT/"report.json").write_text(json.dumps(cases,indent=2,ensure_ascii=False))
print(json.dumps(cases,indent=2,ensure_ascii=False),flush=True)
sys.exit(0 if all(item["ok"] for item in cases) else 1)
