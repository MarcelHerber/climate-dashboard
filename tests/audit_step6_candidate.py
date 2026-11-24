#!/usr/bin/env python3
"""Playwright regression tests for accumulation, mobile chart labels, map zoom and ERA5 menu.
Serves a REAL production Pages artifact; no substituted meteorological responses.
"""
import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def run(site,output):
    output.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(("127.0.0.1",0),functools.partial(Quiet,directory=str(site)))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f"http://127.0.0.1:{server.server_port}"
    rows=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for width in (320,390,1440):
                    context=browser.new_context(viewport={"width":width,"height":850},
                        is_mobile=width<600,has_touch=width<600,service_workers="block")
                    page=context.new_page()
                    errors=[]
                    local_http=[]
                    page.on("pageerror",lambda e:errors.append(str(e)[:220]))
                    page.on("response",lambda r:local_http.append([r.status,r.url]) if
                        urlsplit(r.url).netloc==urlsplit(base).netloc and r.status>=400 else None)
                    row={"width":width}
                    try:
                        page.goto(base+"/index.html?tab=overview",wait_until="domcontentloaded",timeout=90000)
                        page.wait_for_function("() => typeof window.switchTab==='function' && window.DashboardModules",timeout=35000)
                        page.evaluate("switchTab('accumulation')")
                        page.wait_for_function("""() => window.Chart?.getChart?.('accumulationChart')?.data?.datasets
                          ?.some(d=>(d.data||[]).some(v=>Number.isFinite(v)))""",timeout=50000)
                        row["accumulation_summary"]=page.locator("#accSummary").inner_text()[:180]
                        assert "wird berechnet" not in row["accumulation_summary"],row
                        page.evaluate("switchTab('index')")
                        page.wait_for_function("() => !!Chart.getChart('climateIndexChart')",timeout=35000)
                        labels=page.evaluate("""() => {
                           const c=Chart.getChart('climateIndexChart');
                           const opts=c.options.plugins.datalabels;
                           const data=c.data.datasets[0];
                           return {points:data.data.length,visible:data.data.filter((v,i)=>
                             opts.display({datasetIndex:0,dataIndex:i,dataset:data})).length};
                        }""")
                        assert labels["points"]>=20,labels
                        if width<=600:assert labels["visible"]<=labels["points"]/3,labels
                        else:assert labels["visible"]==labels["points"],labels
                        row["index_labels"]=labels
                        page.screenshot(path=str(output/f"{width}-climate-index.png"),full_page=False)
                        page.evaluate("switchTab('europeStations')")
                        page.wait_for_function("""() => !!document.querySelector('#europeStationMap.leaflet-container')
                          && !!document.querySelector('#europeStationMap .leaflet-control-zoom')""",timeout=60000)
                        rects=page.evaluate("""() => {
                           const rect=x=>{let r=x.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom};};
                           const panel=rect(document.querySelector('#europeStations .europe-station-panel'));
                           const zoom=rect(document.querySelector('#europeStationMap .leaflet-control-zoom'));
                           return {panel,zoom,overlap:!(panel.r<=zoom.l||zoom.r<=panel.l||panel.b<=zoom.t||zoom.b<=panel.t)};
                        }""")
                        if width<=520:
                            assert not rects["overlap"],f"Zoom overlaps mobile panel: {rects}"
                        row["zoom"]=rects
                        page.screenshot(path=str(output/f"{width}-europe-stations.png"),full_page=False)
                        page.wait_for_function("""() => !document.getElementById('era5SynopticNav')?.hidden""",timeout=20000)
                        row["era5_desktop_menu"]=page.locator("#era5SynopticNav").is_visible() if width>800 else not page.locator("#era5SynopticNav").get_attribute("hidden")
                        if width<=600:
                            page.locator("#cdMobileMenuButton").click()
                            page.wait_for_function("""() => [...document.querySelectorAll('#cdMobileMenu .cdm-item')]
                              .some(el=>el.textContent.includes('ERA5 Tageskarten'))""",timeout=5000)
                            row["era5_mobile_menu"]=True
                        row["local_http_errors"]=local_http[:12]
                        row["page_errors"]=errors[:12]
                        assert not local_http,f"Local resource failure: {local_http[:5]}"
                        assert not errors,f"JS exceptions: {errors[:5]}"
                        row["ok"]=True
                    except Exception as e:
                        row["ok"]=False
                        row["error"]=str(e)[:750]
                    finally:
                        rows.append(row)
                        context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
    (output/"candidate-regression.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps(rows,indent=2,ensure_ascii=False))
    assert all(r["ok"] for r in rows),"Browser regression failed"

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--site",type=Path,default=Path("_site"))
    p.add_argument("--output",type=Path,default=Path("reports/step6"))
    args=p.parse_args()
    run(args.site.resolve(),args.output.resolve())
