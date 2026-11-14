#!/usr/bin/env python3
"""Phase 2 final acceptance: real ECMWF EPS, GEFS, DWD annual + snow charts.
No mocked model responses, intercepted DWD measurements or fabricated datasets.
Check original Vektor-PDF paths/alpha, editable SVG filled bands and 390/1200px.
"""
from __future__ import annotations
from pathlib import Path
from xml.etree import ElementTree as ET
import json, time, urllib.request
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

BASE="https://marcelherber.github.io/climate-dashboard/"
OUT=Path("phase2_completion_live")
OUT.mkdir(exist_ok=True)
RESULTS=[]

def published():
    until=time.monotonic()+550
    while time.monotonic()<until:
        try:
            with urllib.request.urlopen(BASE+"t850_vector_export.js?probe="+str(time.time()),timeout=22) as r:
                source=r.read().decode("utf-8")
            if not all(s in source for s in ("fillAreas(", "fill-opacity", "setGState")):
                time.sleep(12);continue
            pages=("stratosphaere.html","station_jahresanalyse.html","index.html")
            contents=[]
            for name in pages:
                with urllib.request.urlopen(BASE+name+"?phase2="+str(time.time()),timeout=25) as r:
                    contents.append(r.read().decode("utf-8"))
            if all("t850_vector_export.js?v=20261114-vector-areas-v1" in s for s in contents):
                return
        except Exception as e:
            print("Deploy probe:",str(e)[:160],flush=True)
        time.sleep(12)
    raise AssertionError("Filled scientific vector exporter not yet live on all 3 pages")

def inspect(path,kind,needs_fill=False,needs_sides=False):
    buf=path.read_bytes()
    assert len(buf)>1700,f"Empty {kind} export"
    if kind=="svg":
        root=ET.fromstring(buf)
        n="{http://www.w3.org/2000/svg}"
        ink="{http://www.inkscape.org/namespaces/inkscape}"
        assert not list(root.iter(n+"image")),"Raster image embedded in SVG"
        layers=[node.attrib.get(ink+"label","") for node in root.iter(n+"g")
                if node.attrib.get(ink+"groupmode")=="layer"]
        assert len(layers)>=3,"Missing editable named layers"
        fill_paths=[p for p in root.iter(n+"path") if p.attrib.get("fill-opacity")]
        sides={p.attrib.get("data-side") for p in fill_paths}
        alpha=sorted(set(round(float(p.attrib["fill-opacity"]),3) for p in fill_paths))
        if needs_fill:assert fill_paths and any("Fläche:" in l for l in layers),"No editable SVG fill layers"
        if needs_sides:assert {"above","below"}<=sides,f"No red/blue anomalies: {sides}"
        return {"bytes":len(buf),"layers":len(layers),"filled_polygons":len(fill_paths),
                "fill_opacity":alpha,"sides":sorted(s for s in sides if s)}
    assert buf.startswith(b"%PDF"),"No PDF signature"
    pdf=PdfReader(path)
    assert len(pdf.pages)==1,"Expected single diagram PDF"
    page=pdf.pages[0]
    resources=page.get("/Resources")
    resources=resources.get_object() if resources else {}
    xobjects=resources.get("/XObject")
    if xobjects:
        assert not any(o.get_object().get("/Subtype")=="/Image"
                for o in xobjects.get_object().values()),"Raster image embedded in vector PDF"
    stream=page.get_contents().get_data()
    assert b" m" in stream and b" l" in stream,"No independent vector strokes"
    gs=resources.get("/ExtGState")
    alpha=[]
    if gs:
        alpha=[round(float(x.get_object().get("/ca",1)),3) for x in gs.get_object().values()]
    if needs_fill:
        assert b"f" in stream or b"f*" in stream,"No polygon filling operation"
        assert any(0<a<1 for a in alpha),f"Original PDF alpha not retained: {alpha}"
    return {"bytes":len(buf),"pages":1,"raster_images":False,"pdf_alpha":sorted(set(alpha))}

def chartstate(page,canvas):
    return page.evaluate("""id=>{
      const c=document.getElementById(id),ch=window.Chart?.getChart?.(c);
      if(!ch)return null;
      const visible=ch.data.datasets.filter((ds,i)=>ch.isDatasetVisible(i));
      return {
        type:ch.config?.type, axis:ch.scales?.y?.options?.title?.text||"",
        datasets:visible.length,
        member_count:visible.filter(ds=>/^_EPS p\d\d$/.test(ds.label)).length,
        fill_count:visible.filter(ds=>ds.fill&&typeof ds.fill==="object").length,
        samples:visible.reduce((n,ds)=>n+(ds.data||[]).filter(Number.isFinite).length,0),
        labels:ch.data.labels.length,
        signature:JSON.stringify(ch.data.datasets.map(ds=>ds.data))
      };
    }""",canvas)

def export_pair(page,canvas,group,slug,expect_fill=False,sides=False):
    row=page.locator(f'.cd-sciv-actions[aria-label*="{group}"]')
    row.wait_for(state="visible",timeout=25000)
    initial=chartstate(page,canvas)
    assert initial and initial["samples"]>4,f"Missing actual data: {canvas}, {initial}"
    outputs={}
    for kind,label in (("svg","SVG (Ebenen)"),("pdf","PDF (Vektor)")):
        with page.expect_download(timeout=65000) as event:
            row.get_by_role("button",name=label).click(timeout=35000)
        file=OUT/(slug+"."+kind)
        event.value.save_as(file)
        assert event.value.suggested_filename.endswith("."+kind)
        outputs[kind]=inspect(file,kind,expect_fill,sides if kind=="svg" else False)
        assert "Vektorexport erstellt." in row.inner_text(),row.inner_text()
    final=chartstate(page,canvas)
    assert initial["signature"]==final["signature"],f"Export modified original {canvas} values"
    outputs["source"]={k:v for k,v in initial.items() if k!="signature"}
    return outputs

def record(page,case,width,data):
    status={"case":case,"width":width,"ok":True,**data}
    RESULTS.append(status)
    print("PHASE2 COMPLETION",json.dumps(status,ensure_ascii=False),flush=True)
    page.screenshot(path=str(OUT/f"{case}_{width}.png"),timeout=22000)

def stratosphere(browser,width):
    ctx=browser.new_context(viewport={"width":width,"height":850},is_mobile=width<600,
                            has_touch=width<600,accept_downloads=True,ignore_https_errors=True)
    page=ctx.new_page()
    errors=[];page.on("pageerror",lambda e:errors.append(str(e)[:200]))
    try:
        page.goto(BASE+"stratosphaere.html",wait_until="domcontentloaded",timeout=90000)
        page.wait_for_function("""()=>{
          const c=Chart?.getChart?.('stratoEnsembleCanvas');
          return c&&c.data.datasets.some(ds=>ds.fill?.target==="-1")&&
            c.data.datasets.some(ds=>ds.label==="Ensemble-Mittel"&&ds.data.some(Number.isFinite));
        }""",timeout=120000)
        gefs=export_pair(page,"stratoEnsembleCanvas","GEFS",f"gefs_{width}",True)
        assert gefs["svg"]["filled_polygons"]>1
        page.locator("#stratoEpsTab").click()
        page.wait_for_function("""()=>{
          const c=window.Chart?.getChart?.('stratoEpsCanvas');
          return c&&c.data.datasets.filter(ds=>/^_EPS p\d\d$/.test(ds.label)).length===50 &&
            c.data.datasets.filter(ds=>ds.fill&&typeof ds.fill==='object').length>=2;
        }""",timeout=140000)
        eps=export_pair(page,"stratoEpsCanvas","ECMWF IFS ENS",f"eps_{width}",True)
        assert eps["source"]["member_count"]==50 and eps["source"]["fill_count"]>=2
        assert .18 in eps["svg"]["fill_opacity"] and .3 in eps["svg"]["fill_opacity"]
        assert any(abs(a-.18)<.01 for a in eps["pdf"]["pdf_alpha"])
        assert any(abs(a-.3)<.01 for a in eps["pdf"]["pdf_alpha"])
        assert not errors,errors
        record(page,"stratosphere",width,{"gefs":gefs,"ecmwf_eps":eps,"page_errors":errors})
    finally:ctx.close()

def anomaly_has_both(page):
    return page.evaluate("""()=>{
      const c=Chart.getChart('sjaChart');
      const fill=c.data.datasets.find(ds=>ds.fill&&typeof ds.fill==='object');
      const target=c.data.datasets[fill?.fill?.target||0];
      if(!fill||!target)return false;
      const diff=fill.data.map((v,i)=>Number.isFinite(v)&&Number.isFinite(target.data[i])?
        v-target.data[i]:null).filter(Number.isFinite);
      return diff.some(d=>d>0)&&diff.some(d=>d<0);
    }""")

def annual(browser,width):
    ctx=browser.new_context(viewport={"width":width,"height":850},is_mobile=width<600,
                            has_touch=width<600,accept_downloads=True,ignore_https_errors=True)
    page=ctx.new_page();errors=[];page.on("pageerror",lambda e:errors.append(str(e)[:220]))
    try:
        page.goto(BASE+"station_jahresanalyse.html?station=01420",
                  wait_until="domcontentloaded",timeout=90000)
        page.wait_for_function("""()=>{
          const c=window.Chart?.getChart?.('sjaChart');
          return c?.data?.labels?.length===365 &&
            c.data.datasets.some(ds=>ds.fill&&typeof ds.fill==='object');
        }""",timeout=140000)
        selected=page.locator("#sjaSelected").inner_text()
        assert "Station" in selected,selected
        if not anomaly_has_both(page):
            for value in page.locator("#sjaFillYear option").evaluate_all("(items)=>items.map(o=>o.value)"):
                page.locator("#sjaFillYear").select_option(value)
                if anomaly_has_both(page):break
        assert anomaly_has_both(page),"No mixed positive/negative authentic station temperature anomalies"
        temp=export_pair(page,"sjaChart","DWD Stations-Jahresanalyse",
                         f"annual_temp_{width}",True,True)
        assert .58 in temp["svg"]["fill_opacity"]
        assert any(abs(a-.58)<.01 for a in temp["pdf"]["pdf_alpha"])
        page.locator("#sjaPrecip").click()
        page.wait_for_function("""()=>window.Chart?.getChart?.('sjaChart')?.data?.labels?.length===12""",
                               timeout=100000)
        precip=export_pair(page,"sjaChart","DWD Stations-Jahresanalyse",
                           f"annual_precip_{width}")
        assert precip["source"]["type"]=="line"
        page.locator("#sjaSnow").click()
        page.wait_for_function("""()=>window.Chart?.getChart?.('sjaChart')?.data?.labels?.length===366""",
                               timeout=100000)
        snow=export_pair(page,"sjaChart","DWD Stations-Jahresanalyse",
                         f"annual_snow_{width}")
        assert snow["source"]["type"]=="line"
        assert not errors,errors
        record(page,"annual",width,{"station":selected,"temp":temp,"precip":precip,
                                     "snow":snow,"page_errors":errors})
    finally:ctx.close()

def snow_accumulation(browser,width):
    ctx=browser.new_context(viewport={"width":width,"height":850},is_mobile=width<600,
                            has_touch=width<600,accept_downloads=True,ignore_https_errors=True)
    page=ctx.new_page();errors=[];page.on("pageerror",lambda e:errors.append(str(e)[:220]))
    try:
        page.goto(BASE+"index.html?tab=stationSnow",wait_until="domcontentloaded",timeout=90000)
        page.wait_for_function("""()=>document.querySelector('#stationSnowStationSelect option') &&
          !document.querySelector('#stationSnowContent').hidden""",timeout=110000)
        page.locator("#stationSnowSearch").fill("Zugspitze")
        page.locator('#stationSnowSuggestions button[data-station-id="05792"]').click(timeout=25000)
        page.wait_for_function("""()=>document.querySelector('#stationSnowSummary')?.textContent.includes('Zugspitze') &&
          !!document.querySelector('#stationSnowYearsList input[data-snow-year="2025"]')""",
          timeout=100000)
        page.locator('#stationSnowYearsList input[data-snow-year="2025"]').check(force=True)
        page.wait_for_function("""()=>{
          const d=window.Chart?.getChart?.('stationSnowCumChart')?.data?.datasets;
          return d?.some(ds=>ds.label.includes('2025')&&ds.data.some(v=>Number.isFinite(v)&&v>0))
        }""",timeout=70000)
        cum=export_pair(page,"stationSnowCumChart","akkumulierte Schneehöhe",
                         f"snow_cumulative_{width}")
        assert "cm·Tage" in cum["source"]["axis"]
        daily=export_pair(page,"stationSnowChart","tägliche Schneehöhe",
                           f"snow_daily_{width}")
        assert not errors,errors
        record(page,"snowstation",width,{"cum":cum,"daily":daily,
                   "station":"Zugspitze 05792","page_errors":errors})
    finally:ctx.close()

def main():
    published()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        try:
            for width in (390,1200):
                for name,fn in (("stratosphere",stratosphere),
                                ("annual",annual),("snowstation",snow_accumulation)):
                    try:fn(browser,width)
                    except Exception as e:
                        failure={"case":name,"width":width,"ok":False,"error":str(e)[:1600]}
                        RESULTS.append(failure)
                        print("PHASE2 COMPLETION FAIL",json.dumps(failure,ensure_ascii=False),flush=True)
        finally:browser.close()
    (OUT/"report.json").write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding="utf-8")
    assert len(RESULTS)==6,"Missing acceptance cases"
    assert all(r["ok"] for r in RESULTS),"ECMWF EPS / annual DWD / snow accumulation live vectors failed"

if __name__=="__main__":main()
