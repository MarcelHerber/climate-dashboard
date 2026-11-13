#!/usr/bin/env python3
"""Download REAL GEFS T850 vectors from published Pages in mobile and desktop Chromium."""
from pathlib import Path
import json, time, urllib.request
from xml.etree import ElementTree as ET
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

BASE="https://marcelherber.github.io/climate-dashboard/"
OUT=Path("t850_vector_live")
OUT.mkdir(exist_ok=True)
VERSION="t850_ensembles.js?v=20261113-t850-vectors-v1"

def await_deployment():
    deadline=time.monotonic()+540
    while time.monotonic()<deadline:
        try:
            with urllib.request.urlopen(BASE+"index.html?fresh="+str(time.time()),timeout=20) as res:
                html=res.read().decode("utf8")
            with urllib.request.urlopen(BASE+"t850_vector_export.js?fresh="+str(time.time()),timeout=20) as res:
                js=res.read().decode("utf8")
            if VERSION in html and "T850VectorExport" in js:return
        except Exception as exc:print("Publish probe:",str(exc)[:100],flush=True)
        time.sleep(12)
    raise AssertionError("Current Pages T850 vector exporter was not deployed.")

def inspect_pdf(file):
    reader=PdfReader(file)
    assert len(reader.pages)>=2,"Four-panel PDF should have model and comparison pages"
    for page in reader.pages:
        res=page.get("/Resources")
        if res:
            xobjects=res.get_object().get("/XObject")
            if xobjects:
                assert all(obj.get_object().get("/Subtype")!="/Image"
                    for obj in xobjects.get_object().values()),"Unexpected embedded bitmap"
        commands=page.get_contents().get_data()
        assert b" m" in commands and b" l" in commands,"Missing independent vector paths"
    return {"pages":len(reader.pages),"bytes":file.stat().st_size}

def inspect_svg(file):
    root=ET.parse(file).getroot()
    svg="{http://www.w3.org/2000/svg}"
    ink="{http://www.inkscape.org/namespaces/inkscape}"
    layers=[g.attrib.get(ink+"label","") for g in root.iter(svg+"g")
        if g.attrib.get(ink+"groupmode")=="layer"]
    assert len(layers)>4,layers
    assert any("Member " in label for label in layers),layers
    assert any("Ensemble-Mittel" in label for label in layers),layers
    assert not list(root.iter(svg+"image")),"Raster image embedded"
    return {"layers":len(layers),"bytes":file.stat().st_size}

def run(browser,width):
    mobile=width<600
    ctx=browser.new_context(viewport={"width":width,"height":860},
        is_mobile=mobile,has_touch=mobile,accept_downloads=True,ignore_https_errors=True)
    page=ctx.new_page()
    errors=[]
    page.on("pageerror",lambda err:errors.append(str(err)[:200]))
    page.on("dialog",lambda dialog:(errors.append("dialog: "+dialog.message),dialog.dismiss()))
    status={"width":width,"ok":False}
    try:
        page.goto(BASE+"index.html?test=t850",wait_until="domcontentloaded",timeout=90000)
        page.wait_for_function("()=>typeof window.mountT850Ensembles==='function' && typeof window.switchTab==='function'",timeout=90000)
        page.evaluate("switchTab('t850-ensembles')")
        page.wait_for_function("()=>!!document.getElementById('t850SvgDownload')",timeout=20000)
        page.locator("#t850LocationInput").fill("Frankfurt am Main")
        page.locator("#t850LoadButton").click()
        page.wait_for_function("""()=>{
          const c=window.Chart?.getChart?.('t850ChartGefs');
          return c&&!document.getElementById('t850PdfDownload').disabled &&
            !document.getElementById('t850SvgDownload').disabled &&
            c.data.datasets.some(ds=>ds.data?.some(v=>typeof v==='number'&&Number.isFinite(v)));
        }""",timeout=160000)
        before=page.evaluate("()=>JSON.stringify(Chart.getChart('t850ChartGefs').data.datasets.map(d=>d.data))")
        page.locator("#t850PanelSelect").select_option("four")
        page.wait_for_timeout(300)
        with page.expect_download(timeout=75000) as job:page.locator("#t850PdfDownload").click()
        pdf=OUT/f"t850_{width}.pdf";job.value.save_as(pdf)
        status["pdf"]=inspect_pdf(pdf)
        with page.expect_download(timeout=75000) as job:page.locator("#t850SvgDownload").click()
        svg=OUT/f"t850_{width}.svg";job.value.save_as(svg)
        status["svg"]=inspect_svg(svg)
        after=page.evaluate("()=>JSON.stringify(Chart.getChart('t850ChartGefs').data.datasets.map(d=>d.data))")
        assert before==after,"Vector export mutated real forecast values"
        assert not [e for e in errors if e.startswith("dialog:")],errors
        page.screenshot(path=str(OUT/f"t850_{width}.png"))
        status["ok"]=True
    except Exception as exc:
        status["error"]=str(exc)[:950]
        try:page.screenshot(path=str(OUT/f"FAILED_{width}.png"))
        except Exception:pass
    status["page_errors"]=errors[-8:]
    print("T850 VECTOR LIVE",json.dumps(status,ensure_ascii=False),flush=True)
    ctx.close()
    return status

def main():
    await_deployment()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        try: results=[run(browser,w) for w in (390,1200)]
        finally:browser.close()
    (OUT/"report.json").write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding="utf8")
    if not all(r["ok"] for r in results):raise SystemExit(1)

if __name__=="__main__":main()
