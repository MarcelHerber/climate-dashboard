"""Live QA of real DWD Gebietsmittel on desktop and mobile.
No data is mocked; validates the deployed published GitHub Pages chart."""
from __future__ import annotations
import json
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE="https://marcelherber.github.io/climate-dashboard/"
MARKER="monthly_climate_bars.js?v=20261111-climatebars1"
REPORT=Path("climate_bars_audit")
REPORT.mkdir(exist_ok=True)

def deployed() -> None:
    deadline=time.monotonic()+650
    while time.monotonic()<deadline:
        try:
            with urllib.request.urlopen(BASE+"index.html?check="+str(time.time()),timeout=25) as response:
                html=response.read().decode("utf-8")
                if MARKER in html:
                    print("Published Climate Bars asset tag confirmed.",flush=True)
                    return
        except Exception as error:
            print("Deployment not yet ready:",str(error)[:160],flush=True)
        time.sleep(12)
    raise AssertionError("GitHub Pages did not serve the Climate Bars version in time")

def chart_state(page):
    return page.evaluate("""() => {
      const a=Chart.getChart(document.getElementById("monthlyChart"));
      const b=Chart.getChart(document.getElementById("monthlyDeviationChart"));
      const primary=a?.data?.datasets?.[0];
      return {
        primaryExists:!!a&&!!primary, deviationExists:!!b,
        styled:!!a?.$climateBarsStyled&&!!b?.$climateBarsStyled,
        vertical:(a?.options?.indexAxis||"x")==="x"&&(b?.options?.indexAxis||"x")==="x",
        bars:primary?.data?.length||0, deviationBars:b?.data?.datasets?.[0]?.data?.length||0,
        reference:a?.data?.datasets?.find(d=>d.type==="line"&&/^Mittel\\s/.test(d.label||""))?.data?.[0],
        rounding:primary?.borderRadius,
        colors:primary?.backgroundColor,
        baselineOpts:b?.options?.plugins?.datalabels?.display?true:false,
        png:a?.toBase64Image?.().startsWith("data:image/png")||false,
        canvasWidth:document.getElementById("monthlyChart").getBoundingClientRect().width,
        containerWidth:document.querySelector("#monthlyTimeSeries > .chart-container")?.getBoundingClientRect().width,
        viewport:innerWidth
      };
    }""")

def verify_parameter(page,parameter):
    page.evaluate("""(parameter) => {
       const field=document.getElementById("paramSelect");
       field.value=parameter;
       field.dispatchEvent(new Event("change",{bubbles:true}));
       if(typeof updateMonthly==="function")updateMonthly();
    }""",parameter)
    page.wait_for_function("""() => {
       const a=Chart.getChart(document.getElementById("monthlyChart"));
       const b=Chart.getChart(document.getElementById("monthlyDeviationChart"));
       return a?.$climateBarsStyled && b?.$climateBarsStyled && a?.data?.datasets?.[0]?.data?.length>20;
    }""",timeout=90000)
    state=chart_state(page)
    assert state["primaryExists"] and state["deviationExists"],state
    assert state["styled"] and state["vertical"],state
    assert state["rounding"]==6,state
    assert state["bars"]>=40 and state["deviationBars"]>=40,state
    assert state["png"] and state["baselineOpts"],state
    assert state["canvasWidth"]>50 and state["canvasWidth"]<=state["containerWidth"]+3,state
    expected={"temp":("199,62,69","39,103,190"),
              "rain":("39,111,184","180,113,57"),
              "sun":("221,159,46","86,120,167")}[parameter]
    assert any(any(rgb in color for rgb in expected) for color in state["colors"]),state
    print(parameter,"valid",state["bars"],"bars, width",state["canvasWidth"],flush=True)
    return state

def audit_view(browser,label,width,height):
    context=browser.new_context(viewport={"width":width,"height":height},device_scale_factor=1.5,ignore_https_errors=True)
    page=context.new_page()
    errs=[]
    page.on("pageerror",lambda error:errs.append(str(error)))
    page.goto(BASE+"?tab=monthly",wait_until="domcontentloaded",timeout=120000)
    page.wait_for_function("() => typeof Chart !== 'undefined' && typeof switchTab === 'function'",timeout=90000)
    page.evaluate("switchTab('monthly')")
    page.wait_for_function("""() => {
      const c=document.getElementById("monthlyChart");
      const v=document.getElementById("monthlyDeviationChart");
      return c&&v&&Chart.getChart(c)?.data?.datasets?.[0]?.data?.length>40 &&
             Chart.getChart(v)?.$climateBarsStyled;
    }""",timeout=180000)
    values={}
    for parameter in ("temp","rain","sun"):
        values[parameter]=verify_parameter(page,parameter)
    verify_parameter(page,"temp")
    original=page.evaluate("""() => [...Chart.getChart(document.getElementById("monthlyChart")).data.datasets[0].data]""")
    page.evaluate("""() => document.getElementById("dashboardThemeToggle").click()""")
    page.wait_for_function("""() => document.documentElement.dataset.theme==="dark" """,timeout=30000)
    dark=chart_state(page)
    assert dark["styled"] and dark["vertical"] and dark["png"],dark
    assert original==page.evaluate("""() => [...Chart.getChart(document.getElementById("monthlyChart")).data.datasets[0].data]""")
    # Light download remains a chart canvas rather than page background.
    page.locator("#monthlyTimeSeries > .chart-container").first.screenshot(path=str(REPORT/("climate_bars_"+label+"_dark.png")))
    page.evaluate("""() => document.getElementById("dashboardThemeToggle").click()""")
    page.wait_for_function("""() => document.documentElement.dataset.theme==="light" """,timeout=30000)
    page.locator("#monthlyTimeSeries > .chart-container").first.screenshot(path=str(REPORT/("climate_bars_"+label+"_light.png")))
    errors=[e for e in errs if "monthly_climate_bars" in e or "monthlyClimateBars" in e]
    assert not errors,errors
    print(label,"dark mode, light mode, canvas export and all 3 parameters passed",flush=True)
    (REPORT/("state_"+label+".json")).write_text(json.dumps(
        {"parameters":values,"dark":dark,"errors":errs[-8:]},indent=2,ensure_ascii=False),
        encoding="utf-8")
    context.close()

def main():
    deployed()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        try:
            audit_view(browser,"desktop",1440,900)
            audit_view(browser,"mobile",390,844)
        finally:browser.close()

if __name__=="__main__":
    main()
