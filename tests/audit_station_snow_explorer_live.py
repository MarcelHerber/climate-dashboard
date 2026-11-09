#!/usr/bin/env python3
"""Live real-data audit: 5k-station snow search, map, mobile touch, and exports.

Uses the published GitHub Pages site and actual DWD daily data. It never mocks
station JSON or chart datasets, and writes screenshots + a JSON report.
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE="https://marcelherber.github.io/climate-dashboard/index.html?tab=stationSnow"
OUT=Path("snow_explorer_browser_audit")
OUT.mkdir(parents=True,exist_ok=True)
REPORT=[]

def case(browser,width):
    mobile=width<700
    context=browser.new_context(
        viewport={"width":width,"height":850},device_scale_factor=1,
        has_touch=mobile,is_mobile=mobile,accept_downloads=True,
        reduced_motion="reduce",
    )
    page=context.new_page()
    result={"width":width,"mobile":mobile,"ok":False}
    problems=[]
    page.on("pageerror",lambda error:problems.append(str(error)[:180]))
    requests=[]
    page.on("request",lambda req:requests.append(req.url) if
            "station_snow_height_additional_profiles/" in req.url or
            "station_snow_height_profiles/" in req.url else None)
    try:
        page.goto(BASE,wait_until="domcontentloaded",timeout=80000)
        page.wait_for_function("""()=>
          !!document.querySelector('#stationSnowContent') &&
          !document.querySelector('#stationSnowContent').hidden &&
          !!document.querySelector('#stationSnowStationSelect option') &&
          typeof window.StationSnowExplorer?.getState === 'function'
        """,timeout=120000)
        page.wait_for_function("""()=>
          document.querySelector('#stationSnowSummary')?.textContent.includes('Zugspitze') &&
          !!window.stationSnowAccumulationChart
        """,timeout=120000)
        baseline=page.evaluate("""()=>({
          all:stationSnowIndex.stations.length,
          options:document.getElementById('stationSnowStationSelect').options.length,
          long:stationSnowIndex.stations.filter(s=>s.accepted_history_years>=30).length,
          id:document.getElementById('stationSnowStationSelect').value,
          chartDatasets:stationSnowChart?.data?.datasets?.length,
          current:stationSnowCurrentIndex?.stations?.length
        })""")
        result["initial"]=baseline
        assert baseline["all"]>=5000,baseline
        assert baseline["options"]<=47,baseline
        assert baseline["id"]=="05792",baseline
        assert baseline["chartDatasets"]>0,baseline
        count_before=len(requests)
        search=page.locator("#stationSnowSearch")
        search.fill("Nürnberg")
        page.wait_for_timeout(450)
        choices=page.locator("#stationSnowSuggestions button")
        assert choices.count()>0,"No search suggestions for Nürnberg"
        assert choices.count()<=15,choices.count()
        assert page.locator("#stationSnowStationSelect").input_value()=="05792",\
            "Typing changed selected station before explicit selection"
        assert len(requests)==count_before,\
            "Typing requested per-station snow JSON before user selected a station"
        chosen=choices.first
        if mobile:
            chosen.tap(timeout=10000)
        else:
            chosen.click(timeout=10000)
        page.wait_for_function("""()=>
          document.getElementById('stationSnowSummary')?.textContent.includes('Nürnberg')
        """,timeout=60000)
        result["searchSelected"]=page.locator("#stationSnowStationSelect").input_value()
        assert result["searchSelected"]=="03668"
        assert page.evaluate("""()=>stationSnowChart?.data?.datasets?.length>0""")
        assert page.locator("#stationSnowSelectedMeta").inner_text().find("Nürnberg")>=0

        # Search remains independent of the 30-quality-year filter.
        search.fill("")
        page.wait_for_timeout(450)
        page.locator("#stationSnowLongSeriesOnly").check()
        page.wait_for_timeout(250)
        quality=page.evaluate("""()=>({
          matching:filteredStationSnowStations().length,
          valid:filteredStationSnowStations().every(s=>s.accepted_history_years>=30),
          options:document.getElementById('stationSnowStationSelect').options.length
        })""")
        result["qualityFilter"]=quality
        assert quality["valid"] and quality["matching"]>=267 and quality["options"]<=47

        # Check the additional current-data and elevation filter combinatorics.
        page.locator("#stationSnowAvailabilitySelect").select_option("current")
        page.locator("#stationSnowElevationSelect").select_option("500-1000")
        actual=page.evaluate("""()=>({
          matching:filteredStationSnowStations().length,
          valid:filteredStationSnowStations().every(s=>{
            const h=Number(s.height);
            return h>=500&&h<1000&&
              stationSnowCurrentMeta(s.id)?.current_available===true;
          })
        })""")
        result["additionalFilters"]=actual
        assert actual["valid"],actual

        # Restore the broad map view and test the touch-safe accordion.
        page.locator("#stationSnowElevationSelect").select_option("all")
        page.locator("#stationSnowAvailabilitySelect").select_option("all")
        page.locator("#stationSnowLongSeriesOnly").uncheck()
        details=page.locator("#stationSnowMapDetails")
        if not details.evaluate("(el)=>el.open"):
            summary=details.locator("summary")
            if mobile: summary.tap(timeout=15000)
            else: summary.click(timeout=15000)
        page.wait_for_function("""()=>window.StationSnowExplorer?.getState()?.mapReady""",
                               timeout=30000)
        page.wait_for_function("""()=>document.querySelector(
          '#stationSnowMapStatus')?.textContent.includes('Marker/Cluster')""",
                               timeout=20000)
        mapstatus=page.locator("#stationSnowMapStatus").inner_text()
        result["mapStatus"]=mapstatus
        # At low zoom many DWD stations must be clustered.
        cluster=page.locator("#stationSnowMap .station-snow-cluster-icon").first
        assert cluster.count()>0,"Cluster missing for >5000 plotted stations"
        if mobile: cluster.tap(timeout=15000)
        else: cluster.click(timeout=15000)
        result["mapClickOk"]=True
        result["mapReady"]=page.evaluate("""()=>window.StationSnowExplorer.getState().mapReady""")
        assert page.evaluate("""()=>document.querySelector('#stationSnowMap').clientWidth>0""")
        result["mapNoOverflow"]=page.evaluate("""()=>{
          const el=document.querySelector('#stationSnowMap');
          const bounds=el.getBoundingClientRect();
          const parent=el.parentElement.getBoundingClientRect();
          const clipped=getComputedStyle(el).overflowX==='hidden';
          return clipped && bounds.width>0 &&
            bounds.left>=parent.left-3 && bounds.right<=parent.right+3 &&
            document.documentElement.scrollWidth<=window.innerWidth+3
        }""")
        assert result["mapNoOverflow"]

        # Real chart and labeled downloads after selecting via search.
        page.locator("#stationSnowSearch").fill("Zugspitze")
        page.wait_for_timeout(400)
        button=page.locator("#stationSnowSuggestions button").first
        (button.tap if mobile else button.click)(timeout=15000)
        page.wait_for_function("""()=>document.querySelector('#stationSnowSummary')
          ?.textContent.includes('Zugspitze') &&
          !!window.stationSnowAccumulationChart""",timeout=45000)
        page.locator('#stationSnowCumStart').select_option("12-01")
        page.locator('#stationSnowCumEnd').select_option("02-28")
        # CSV guarantees data export independent of raster canvas. PNG/PDF
        # downloads must also be generated from labeled charts.
        for button_id,suffix in [
            ("stationSnowCumCsv",".csv"),
            ("stationSnowCumPng",".png"),
            ("stationSnowCumPdf",".pdf"),
        ]:
            with page.expect_download(timeout=30000) as download_info:
                page.locator("#"+button_id).click(timeout=15000)
            download=download_info.value
            name=download.suggested_filename.lower()
            assert name.endswith(suffix),name
            result[button_id]=name
        page.screenshot(path=str(OUT/f"explorer_{width}.png"),full_page=False)
        result["ok"]=True
    except Exception as exc:
        result["error"]=str(exc)[:800]
        try:page.screenshot(path=str(OUT/f"FAIL_explorer_{width}.png"),full_page=False)
        except Exception:pass
    result["page_errors"]=problems[-8:]
    REPORT.append(result)
    context.close()

with sync_playwright() as playwright:
    browser=playwright.chromium.launch(headless=True,args=["--no-sandbox"])
    try:
        for width in (390,1280):
            case(browser,width)
    finally:browser.close()
(OUT/"report.json").write_text(json.dumps(REPORT,indent=2,ensure_ascii=False))
print(json.dumps(REPORT,indent=2,ensure_ascii=False),flush=True)
sys.exit(0 if all(x["ok"] for x in REPORT) else 1)
