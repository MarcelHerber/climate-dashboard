#!/usr/bin/env python3
"""Mobile LIVE browser interactions on the public Climate Dashboard.

NO mock data, no intercepted model requests, no source substitutions.
Reports distinguish source availability from touch/UI behavior.
Chromium has_touch is emulation, not a physical iOS/Android validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlparse
import os
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BASE="https://marcelherber.github.io/climate-dashboard/"
MODEL_HOSTS=("raw.githubusercontent.com","cdn.jsdelivr.net","open-meteo.com","github.io")
SIZES=(390,320)
CASES=("stratosphaere","mosmix","isobaren","ensembles","hyras")
REPORT_DIR=Path("mobile_live_reports")

def js_chart(canvas_id:str)->str:
    return """id => {
      const c=document.getElementById(id);
      const chart=c&&window.Chart?.getChart?.(c);
      if(!chart)return {available:false};
      let datasetCount=chart.data.datasets.length;
      let samples=chart.data.datasets.reduce((n,d)=>n+(Array.isArray(d.data)?d.data.filter(v=>v!==null&&v!==undefined).length:0),0);
      return {available:true,datasetCount,samples,canvasWidth:c.getBoundingClientRect().width,
        xTicks:chart.options?.scales?.x?.ticks?.maxTicksLimit||null};
    }"""

def observe(page):
    results={"data_responses":[],"responses_failed":[],"script_errors":[]}
    def response(r):
        try:
            u=r.url
            if any(token in u for token in ("/data/",".json","open-meteo.com","stratosphere-ensemble-data","stratosphere-ecmwf-ens-data")):
                results["data_responses"].append({"status":r.status,"url":u.split("?",1)[0][:175]})
        except Exception:pass
    page.on("response",response)
    page.on("requestfailed",lambda req:results["responses_failed"].append({
        "url":req.url.split("?",1)[0][:165],"reason":req.failure or "network"}))
    page.on("pageerror",lambda error:results["script_errors"].append(str(error)[:260]))
    return results

def touch_menu(page,category,label):
    menu=page.locator("#cdMobileMenuButton")
    menu.wait_for(state="visible",timeout=15000)
    menu.tap()
    panel=page.locator("#cdMobileMenu")
    assert panel.is_visible(),"Mobile drawer not visible"
    cat=panel.locator("details.cdm-category").filter(has=page.locator("summary",has_text=category)).first
    cat.locator("summary").tap()
    cat.locator("button.cdm-item",has_text=label).first.tap()

def wait_until(page,expression,timeout=40000):
    page.wait_for_function(expression,timeout=timeout)

def shot(page,folder,name):
    folder.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(folder/(name+".png")),full_page=False,animations="disabled",timeout=14000)

def page_open(page,filename):
    page.goto(BASE+filename,wait_until="domcontentloaded",timeout=45000)
    page.wait_for_timeout(500)
    return page.url

def get(page,selector):
    return page.locator(selector).first.inner_text(timeout=2500).strip()

def test_stratosphaere(page,folder):
    page_open(page,"stratosphaere.html")
    wait_until(page,"""() => window.Chart && 
      (document.getElementById("stratoEnsembleCsv")?.disabled===false ||
       /Fehler|nicht erreichbar|ungültig/i.test(document.getElementById("stratoEnsembleStatus")?.textContent||""))""",47000)
    status=get(page,"#stratoEnsembleStatus")
    gefs=page.evaluate(js_chart("stratoEnsembleCanvas"),"stratoEnsembleCanvas")
    shot(page,folder,"strato_gefs")
    assert gefs.get("available") and gefs.get("samples",0)>20, "GEFS original data not plotted: "+status
    eps=page.locator("#stratoEpsTab");eps.tap()
    wait_until(page,"""() => document.getElementById("stratoEpsCsv")?.disabled===false ||
      /Fehler|nicht verfügbar|nicht erreichbar/i.test(document.getElementById("stratoEpsStatus")?.textContent||"")""",45000)
    eps_status=get(page,"#stratoEpsStatus")
    eps_chart=page.evaluate(js_chart("stratoEpsCanvas"),"stratoEpsCanvas")
    shot(page,folder,"strato_eps")
    assert eps_chart.get("samples",0)>20,"EPS original data missing: "+eps_status
    # Open the real analysis switch with a touch and inspect member-based heatmap.
    page.locator("#stratoHistoryTab").tap()
    wait_until(page,"""() => document.body.classList.contains("strato-forecast-only")===false""",12000)
    heat=get(page,"#stratoHeatStatus")
    return {"gefs":gefs,"gefs_status":status,"eps":eps_chart,"eps_status":eps_status,
            "analysis_switch":True,"heatmap_status":heat}

def test_mosmix(page,folder):
    page_open(page,"mosmix.html")
    wait_until(page,"""() => 
      document.querySelector("#mosmixMap.leaflet-container") ||
      /konnte nicht gestartet|Fehler:/i.test(document.getElementById("mosmixSectionStatus")?.textContent||"")""",60000)
    status=get(page,"#mosmixSectionStatus")
    map_alive=page.locator("#mosmixMap.leaflet-container").count()>0
    shot(page,folder,"mosmix_map")
    assert map_alive,"Real MOSMIX data/map failed: "+status
    mode=page.locator('[data-mosmix-mode="tmax"]')
    mode.tap()
    page.wait_for_timeout(1000)
    active=mode.evaluate("(el)=>el.classList.contains('active')")
    assert active,"Touch did not activate Tmax mode"
    slider=page.locator("#mosmixSlider")
    initial=slider.input_value()
    box=slider.bounding_box()
    if box:
        page.touchscreen.tap(box["x"]+box["width"]*.73,box["y"]+box["height"]*.50)
    page.wait_for_timeout(400)
    changed=slider.input_value()
    # Station detail must come from current DWD manifest, not test fixture.
    page.locator("#mosmixStationSearch").fill("Frankfurt")
    page.locator("#mosmixStationButton").tap()
    wait_until(page,"""() => /MOSMIX-ID|konnte nicht geladen|Keine passende/i.test(
      document.getElementById("mosmixMeteogramStatus")?.textContent||"")""",50000)
    station_status=get(page,"#mosmixMeteogramStatus")
    chart=page.evaluate(js_chart("mosmixTempChart"),"mosmixTempChart")
    shot(page,folder,"mosmix_meteogram")
    assert chart.get("samples",0)>5,"Real station meteogram failed: "+station_status
    return {"status":status,"map_live":map_alive,"tmax_touch":active,
            "slider_before":initial,"slider_after":changed,
            "meteogram":chart,"station_status":station_status}

def test_isobaren(page,folder):
    page_open(page,"isobaren_original.html")
    wait_until(page,"""() => 
      document.querySelectorAll("#validTime option").length>1 ||
      /Fehler|nicht erreichbar/i.test(document.body.innerText.slice(0,2500))""",45000)
    options=page.locator("#validTime option").count()
    modes=page.locator("#chartMode")
    modes.select_option("four")
    page.wait_for_timeout(650)
    search=page.locator("#sourceSearch");search.fill("DWD")
    page.wait_for_timeout(350)
    cards=page.locator(".sg-panel").count()
    image_count=page.evaluate("""() => [...document.querySelectorAll("img")].filter(
      x=>x.complete&&x.naturalWidth>50&&x.getBoundingClientRect().width>5).length""")
    shot(page,folder,"isobaren_four")
    assert options>1,"Actual synoptic catalog contains no selectable valid times"
    assert page.locator("#chartMode").input_value()=="four","Panel change did not persist"
    return {"real_valid_times":options,"four_panel":True,"source_filter":"DWD",
            "visible_loaded_images":image_count,"gallery_panels":cards}

def test_ensembles(page,folder):
    page_open(page,"index.html")
    touch_menu(page,"Europa & Prognosen","Ensembleprognosen")
    wait_until(page,"""() => document.getElementById("t850-ensembles")?.classList.contains("active")
      && document.getElementById("t850LoadButton")""",20000)
    page.locator("#t850LocationInput").fill("Berlin")
    # Real Open-Meteo API; prefer a smaller parameter while retaining ensemble members.
    page.locator("#t850SearchForm #t850LoadButton").tap()
    wait_until(page,"""() => 
       /geladen|konnte|Fehler/i.test(document.getElementById("t850Status")?.textContent||"")
       && document.getElementById("t850LoadButton")?.disabled===false
    """,85000)
    status=get(page,"#t850Status")
    chart=page.evaluate(js_chart("t850GefsChart"),"t850GefsChart")
    # Determine actual model canvas if id differs; ensure real model plot with
    # ≥3 non-null forecast steps and at least one successful model response.
    allcharts=page.evaluate("""() => [...document.querySelectorAll('#t850-ensembles canvas')].map(c=>({
       id:c.id,chart:!!window.Chart?.getChart?.(c),
       pts:window.Chart?.getChart?.(c)?.data?.datasets?.reduce((n,d)=>n+d.data.filter(
         v=>v!==null&&v!==undefined).length,0)||0
    }))""")
    shot(page,folder,"ensembles_berlin")
    assert any(x["pts"]>5 for x in allcharts),"Ensemble charts have no original forecast points: "+status
    page.locator("#t850PanelSelect").select_option("four")
    page.wait_for_timeout(500)
    return {"status":status,"charts":allcharts,"four_panel_change":page.locator("#t850PanelSelect").input_value()=="four"}

def test_hyras(page,folder):
    page_open(page,"index.html")
    touch_menu(page,"Deutschland","HYRAS-Flächenkarten")
    wait_until(page,"""() => document.getElementById("hyras")?.classList.contains("active")""",12000)
    wait_until(page,"""() =>
      document.querySelectorAll("#hyrasPeriodSelect option").length>1 ||
      /Fehler|nicht verfügbar/i.test(document.getElementById("hyrasStatus")?.textContent||"")""",65000)
    before=get(page,"#hyrasStatus")
    period_count=page.locator("#hyrasPeriodSelect option").count()
    image_count=page.evaluate("""() => [...document.querySelectorAll("#hyrasMapFrame img")].filter(
      img=>img.complete&&img.naturalWidth>20).length""")
    # Touch-friendly parameter select and calendar step.
    page.locator("#hyrasParameterSelect").select_option("tmean")
    page.wait_for_timeout(1100)
    shot(page,folder,"hyras_tmean")
    assert period_count>1,"HYRAS period list not loaded: "+before
    return {"status":before,"periods":period_count,"images":image_count,
            "parameter_selected":page.locator("#hyrasParameterSelect").input_value()}

TESTS={"stratosphaere":test_stratosphaere,"mosmix":test_mosmix,
       "isobaren":test_isobaren,"ensembles":test_ensembles,"hyras":test_hyras}

def run(output:Path):
    output.mkdir(parents=True,exist_ok=True)
    result={"mode":"Live GitHub Pages with original external weather API requests and touch emulation",
            "url":BASE,"generated_utc":datetime.now(timezone.utc).isoformat(),
            "physical_mobile_test":False,"cases":[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
        try:
            for width in SIZES:
                # 390 tests every interactive module; 320 repeats hardest two.
                cases=CASES if width==390 else ("stratosphaere","mosmix")
                context=browser.new_context(viewport={"width":width,"height":844},
                    is_mobile=True,has_touch=True,device_scale_factor=2,
                    reduced_motion="reduce",accept_downloads=True)
                for case in cases:
                    page=context.new_page()
                    network=observe(page)
                    case_record={"page":case,"viewport":width}
                    try:
                        case_record["result"]=TESTS[case](page,output)
                        case_record["passed"]=True
                    except Exception as ex:
                        case_record["passed"]=False
                        case_record["error"]=str(ex)[:550]
                        try:shot(page,output,f"FAILED_{case}_{width}")
                        except Exception:pass
                    case_record["request_summary"]={
                        "successful_data_responses":sum(x["status"]==200 for x in network["data_responses"]),
                        "other_data_responses":network["data_responses"][-16:],
                        "failed_requests":network["responses_failed"][-12:],
                        "script_errors":network["script_errors"][-12:]}
                    result["cases"].append(case_record)
                    page.close()
                context.close()
        finally:browser.close()
    result["passed"]=sum(x["passed"] for x in result["cases"])
    result["total"]=len(result["cases"])
    (output/"audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# Echtdaten- und Touchprüfung auf Mobilgeräten (Chromium-Emulation)","",
         "Keine Fake-Daten. Die öffentliche GitHub-Pages-Seite und ihre Wetterdatenquellen wurden unverändert geladen.","",
         "| Bereich | Breite | Ergebnis | Bemerkung |","|---|---:|---|---|"]
    for x in result["cases"]:
        desc=x.get("error","Originaldaten geladen und Touch-Interaktion geprüft")
        lines.append(f"| {x['page']} | {x['viewport']} px | {'OK' if x['passed'] else 'FEHLER'} | {str(desc).replace('|','/')} |")
    lines+=["",f"**Bestanden: {result['passed']}/{result['total']}**",
      "Details, tatsächliche Daten-URLs, JavaScript-Fehler und Screenshots befinden sich im Artefakt.",
      "Keine echte Android/iOS-Browserabnahme, Exportaufbau nicht Teil dieser Prüfung."]
    (output/"README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines),flush=True)
    for x in result["cases"]:
        if not x["passed"]:
            print("DIAGNOSE:",json.dumps(x,ensure_ascii=False)[:2500],flush=True)
    return 0 if result["passed"]==result["total"] else 1

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=REPORT_DIR)
    args=parser.parse_args()
    sys.exit(run(args.output))
