#!/usr/bin/env python3
"""Phase 2 science SVG/PDF live acceptance: true published GEFS and DWD station data."""
from __future__ import annotations
from pathlib import Path
from xml.etree import ElementTree as ET
import json
import time
import urllib.request

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

BASE="https://marcelherber.github.io/climate-dashboard/"
OUT=Path("phase2_science_vectors_live")
OUT.mkdir(exist_ok=True)

def await_publish():
    deadline=time.monotonic()+540
    while time.monotonic()<deadline:
        try:
            with urllib.request.urlopen(BASE+"index.html?qa="+str(time.time()),timeout=25) as response:
                index=response.read().decode("utf-8")
            with urllib.request.urlopen(BASE+"stratosphaere.html?qa="+str(time.time()),timeout=25) as response:
                strato=response.read().decode("utf-8")
            if all("scientific_vector_actions.js?v=20261113-science-vector-v1" in text for text in [index,strato]):
                return
        except Exception as error:
            print("Pages deployment probe:",str(error)[:160],flush=True)
        time.sleep(14)
    raise AssertionError("GitHub Pages has not published the scientific vector controls.")

def inspect_svg(path):
    ns="{http://www.w3.org/2000/svg}"
    ink="{http://www.inkscape.org/namespaces/inkscape}"
    root=ET.parse(path).getroot()
    layers=[
        g.attrib.get(ink+"label","")
        for g in root.iter(ns+"g") if g.attrib.get(ink+"groupmode")=="layer"
    ]
    assert any(" – " in label for label in layers),layers
    assert sum(" – " in label for label in layers)>=3,layers
    assert not list(root.iter(ns+"image")),"Raster image used in SVG"
    paths=list(root.iter(ns+"path"))
    assert len(paths)>1,"No editable series paths"
    return {"bytes":path.stat().st_size,"layers":len(layers),"paths":len(paths)}

def inspect_pdf(path):
    pdf=PdfReader(path)
    assert len(pdf.pages)==1,"One selected scientific diagram expected"
    page=pdf.pages[0]
    resource=page.get("/Resources")
    if resource:
        xobjects=resource.get_object().get("/XObject")
        if xobjects:
            assert not any(
                item.get_object().get("/Subtype")=="/Image"
                for item in xobjects.get_object().values()
            ),"Embedded raster image found in PDF"
    content=page.get_contents().get_data()
    assert b" m" in content and b" l" in content,"No editable vector lines in PDF"
    return {"bytes":path.stat().st_size,"pages":len(pdf.pages),"vector_paths":True}

def audit(browser,kind,width):
    mobile=width<600
    context=browser.new_context(viewport={"width":width,"height":850},
        is_mobile=mobile,has_touch=mobile,device_scale_factor=1,
        ignore_https_errors=True,accept_downloads=True)
    page=context.new_page()
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)[:250]))
    page.on("dialog",lambda dialog:(errors.append("dialog: "+dialog.message),dialog.dismiss()))
    result={"kind":kind,"width":width,"passed":False}
    try:
        if kind=="gefs":
            page.goto(BASE+"stratosphaere.html",wait_until="domcontentloaded",timeout=90000)
            target="stratoEnsembleCanvas"
        else:
            page.goto(BASE+"index.html?tab=stationSnow",wait_until="domcontentloaded",timeout=90000)
            target="stationSnowChart"
        page.wait_for_function("""id=>{
            const canvas=document.getElementById(id);
            const chart=window.Chart?.getChart?.(canvas);
            return !!chart && !!document.querySelector('script[src*="scientific_vector_actions.js"]') &&
              chart.data.datasets.some((dataset,i)=>chart.isDatasetVisible(i) &&
                dataset.data?.some(v=>typeof v==='number'&&Number.isFinite(v)));
        }""",target,timeout=160000)
        controls=page.locator("#"+target).locator("xpath=..").locator("xpath=following-sibling::div[contains(@class,'cd-sciv-actions')][1]")
        controls.wait_for(state="visible",timeout=30000)
        before=page.evaluate("""id=>JSON.stringify(Chart.getChart(document.getElementById(id)).data.datasets.map(ds=>ds.data))""",target)
        for ext,label in [("svg","SVG (Ebenen)"),("pdf","PDF (Vektor)")]:
            with page.expect_download(timeout=80000) as job:
                controls.get_by_role("button",name=label).click(timeout=25000)
            file=OUT/f"{kind}_{width}.{ext}"
            job.value.save_as(str(file))
            result[ext]=inspect_svg(file) if ext=="svg" else inspect_pdf(file)
        after=page.evaluate("""id=>JSON.stringify(Chart.getChart(document.getElementById(id)).data.datasets.map(ds=>ds.data))""",target)
        assert before==after,"Scientific source values were modified by export"
        assert not [e for e in errors if e.startswith("dialog:")],errors
        page.screenshot(path=str(OUT/f"{kind}_{width}.png"),timeout=30000)
        result["passed"]=True
    except Exception as error:
        result["error"]=str(error)[:900]
        try:page.screenshot(path=str(OUT/f"FAIL_{kind}_{width}.png"),timeout=15000)
        except Exception:pass
    result["errors"]=errors[-6:]
    print("PHASE2 SCIENCE VECTORS",json.dumps(result,ensure_ascii=False),flush=True)
    context.close()
    return result

def main():
    await_publish()
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        try:
            results=[audit(browser,kind,width) for kind in ("gefs","station") for width in (390,1200)]
        finally:
            browser.close()
    (OUT/"report.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    if not all(item["passed"] for item in results):
        raise SystemExit(1)

if __name__=="__main__":
    main()
