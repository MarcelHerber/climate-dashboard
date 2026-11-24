#!/usr/bin/env python3
"""Validate optional dashboard modules with real browser and real Pages data."""
import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

HEAVY=("mosmix.js","monthly_frequency.js","station_thresholds.js")

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*a):pass

def audit(site:Path,output:Path):
    output.mkdir(parents=True,exist_ok=True)
    html=(site/"index.html").read_text(encoding="utf-8")
    assert "optional_dashboard_modules.js" in html
    for name in HEAVY:
        assert f'src="{name}?v=' not in html, f"{name} loaded eagerly"
    assert "dwd_station_daily_map.js" in html
    server=ThreadingHTTPServer(("127.0.0.1",0),functools.partial(Quiet,directory=str(site)))
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    base=f"http://127.0.0.1:{server.server_port}"
    reports=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for width in (1440,390):
                    ctx=browser.new_context(viewport={"width":width,"height":860},
                        is_mobile=width<600,has_touch=width<600,accept_downloads=True,
                        ignore_https_errors=True,service_workers="block")
                    page=ctx.new_page()
                    request_urls=[]
                    errors=[]
                    failed=[]
                    def response(resp):
                        if resp.url.split("?")[0].endswith(".js"):request_urls.append(resp.url)
                        if urlsplit(resp.url).netloc==urlsplit(base).netloc and resp.status>=400:
                            failed.append([resp.status,resp.url])
                    page.on("response",response)
                    page.on("pageerror",lambda err:errors.append(str(err)[:300]))
                    row={"width":width}
                    try:
                        page.goto(base+"/index.html?tab=overview",wait_until="domcontentloaded",timeout=90000)
                        page.wait_for_function("() => typeof window.switchTab==='function' && !!window.DashboardOptionalModules",timeout=35000)
                        page.wait_for_timeout(1400)
                        initial=list(request_urls)
                        row["initial_js_requests"]=len(initial)
                        row["initial_script_urls"]=initial
                        for name in HEAVY:
                            assert not any(urlsplit(url).path.endswith("/"+name) for url in initial),(name,initial)
                        assert page.locator("#mosmix[data-mosmix-lazy-shell='1']").count()==1,"Missing MOSMIX shell"
                        assert page.locator("#dwdDailyMap").count()==1,"DWD daily-map navigation disappeared"
                        assert page.locator('[data-mosmix-nav="1"]').count()>=1,"MOSMIX navigation disappeared"
                        page.evaluate("switchTab('monthly')")
                        page.wait_for_function("""() => !!document.getElementById('monthlyFrequencyButton')
                            && window.DashboardOptionalModules?.loaded('frequency')""",timeout=40000)
                        page.locator("#monthlyFrequencyButton").click()
                        page.wait_for_function("""() => !!window.Chart?.getChart?.('monthlyFrequencyChart')?.data?.datasets
                            ?.some(ds=>ds.data?.length>0)""",timeout=50000)
                        row["monthly_frequency"]={"loaded":True,"chart":True}
                        page.evaluate("switchTab('stationClimateDays')")
                        page.wait_for_function("""() => window.DashboardOptionalModules?.loaded('thresholds')
                            && !!document.getElementById('stationThresholdPanel')""",timeout=50000)
                        row["station_thresholds"]={"loaded":True,"panel":True}
                        page.evaluate("switchTab('mosmix')")
                        page.wait_for_function("""() => window.DashboardOptionalModules?.loaded('mosmix')
                            && !document.querySelector('#mosmix[data-mosmix-lazy-shell="1"]')
                            && !!document.getElementById('mosmixMap')""",timeout=50000)
                        page.wait_for_function("""() => !!document.querySelector('#mosmixMap.leaflet-container')
                            || /fehlgeschlagen|nicht erreichbar/i.test(
                              document.getElementById('mosmixSectionStatus')?.textContent||'')""",timeout=70000)
                        assert page.locator("#mosmixMap.leaflet-container").count()==1,(
                            "Real MOSMIX map not initialized",page.locator("#mosmixSectionStatus").inner_text())
                        row["mosmix"]={"loaded":True,"map":True,
                            "station_search":page.locator("#mosmixStationSearch").count()==1}
                        for name in HEAVY:
                            occurrences=[u for u in request_urls if urlsplit(u).path.endswith("/"+name)]
                            assert len(occurrences)==1,f"{name} fetched {len(occurrences)} times"
                        row["total_js_requests_after_three_tabs"]=len(request_urls)
                        row["module_js_requests"]={name:sum(urlsplit(u).path.endswith("/"+name)
                            for u in request_urls) for name in HEAVY}
                        row["page_errors"]=errors[:20]
                        row["local_http_errors"]=failed[:20]
                        # MOSMIX treats quality_status.json as optional evidence:
                        # it legitimately falls back to a second source on 404.
                        # Keep the HTTP event visible, but do not misclassify this
                        # documented missing quality file as a broken JS module.
                        optional=[x for x in failed if x[0]==404 and
                            urlsplit(x[1]).path=="/data/mosmix/quality_status.json"]
                        critical=[x for x in failed if x not in optional]
                        row["optional_quality_source_404"]=optional
                        assert not critical,f"Unexpected local HTTP failures: {critical[:5]}"
                        assert not errors,f"Runtime JS errors: {errors[:5]}"
                        page.screenshot(path=str(output/f"lazy-{width}-mosmix.png"),
                            animations="disabled",full_page=False)
                        row["ok"]=True
                    except Exception as err:
                        row["ok"]=False
                        row["error"]=str(err)[:1000]
                    finally:
                        reports.append(row)
                        ctx.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        worker.join(timeout=10)
        server.server_close()
    (output/"optional-module-browser.json").write_text(
        json.dumps(reports,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(reports,indent=2,ensure_ascii=False),flush=True)
    assert all(r["ok"] for r in reports),"Optional module browser regression"

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--site",type=Path,default=Path("_site"))
    p.add_argument("--output",type=Path,default=Path("reports/optional"))
    a=p.parse_args()
    audit(a.site.resolve(),a.output.resolve())
