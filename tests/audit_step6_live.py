#!/usr/bin/env python3
"""Strict, real-data Playwright acceptance of deployed Climate Dashboard.
No API response replacement or test fixtures. Records HTTP status,
initial script requests, tab-level lazy JS requests, usable data and exports.
"""
import argparse
import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

BASE="https://marcelherber.github.io/climate-dashboard/"
TABS=["monthly","index","accumulation","hyras","t850-ensembles","sst-europe",
      "stationSnow","era5Europe","era5Atmosphere","europeStations","era5Synoptic"]
def js_evidence(page,tab):
    return page.evaluate("""tab => {
      const root=document.getElementById(tab);
      if(!root)return {error:'missing tab'};
      const charts=[...root.querySelectorAll('canvas')].map(c=>{
        const inst=window.Chart?.getChart?.(c);
        return {id:c.id,visible:c.getBoundingClientRect().width>0,
          points:inst?.data?.datasets?.reduce((n,d)=>n+(d.data||[]).filter(
            x=>x!==null && x!==undefined && (typeof x!=='number'||Number.isFinite(x))).length,0)||0};
      });
      return {charts,images:[...root.querySelectorAll('img')].map(im=>({
          src:im.currentSrc?.slice(0,110),width:im.naturalWidth,visible:!im.hidden,
          complete:im.complete})).slice(0,14),
        status:[...root.querySelectorAll('[id*="Status"],[id*="Loading"]')]
         .map(x=>({id:x.id,text:(x.textContent||'').trim().slice(0,170)})).slice(0,15)};
    }""",tab)

def record_network(page):
    out={"responses":[],"http_errors":[],"requests_failed":[],"page_errors":[],"script_requests":[]}
    def response(resp):
        url=resp.url
        if urlsplit(url).path.lower().endswith((".js",".mjs")):
            out["script_requests"].append({"status":resp.status,"url":url[:210]})
        if resp.status>=400:
            out["http_errors"].append({"status":resp.status,"url":url[:210]})
        if any(t in url for t in ("data.json","hyras","sst","era5","open-meteo","europe_stations","mosmix")):
            if len(out["responses"])<220:
                out["responses"].append({"status":resp.status,"url":url[:160]})
    page.on("response",response)
    page.on("requestfailed",lambda req:out["requests_failed"].append({
        "url":req.url[:210],"reason":str(req.failure)[:160]}))
    page.on("pageerror",lambda err:out["page_errors"].append(str(err)[:320]))
    return out

def screenshot(page,directory,name):
    page.screenshot(path=str(directory/(name+".png")),full_page=False,
                    animations="disabled",timeout=24000)

def export(page,out,selector,ext,prefix):
    target=page.locator(selector)
    target.wait_for(state="visible",timeout=20000)
    with page.expect_download(timeout=50000) as download_info:
        target.click(timeout=30000)
    download=download_info.value
    dest=out/(prefix+"."+ext)
    download.save_as(str(dest))
    data=dest.read_bytes()
    if ext=="png":
        assert data.startswith(b"\x89PNG\r\n\x1a\n"),f"Invalid PNG {selector}"
        w,h=struct.unpack(">II",data[16:24])
        assert w>=300 and h>=150,(w,h)
        return {"format":"png","bytes":len(data),"width":w,"height":h}
    assert data.startswith(b"%PDF"),f"Invalid PDF {selector}"
    assert len(data)>4000,len(data)
    return {"format":"pdf","bytes":len(data)}

def try_case(results,name,fn):
    start=time.monotonic()
    try:
        value=fn()
        results[name]={"ok":True,"elapsed_ms":round((time.monotonic()-start)*1000),
                       "evidence":value}
    except Exception as e:
        results[name]={"ok":False,"elapsed_ms":round((time.monotonic()-start)*1000),
                       "error":str(e)[:700]}

def device(browser,width,out):
    mobile=width<=600
    ctx=browser.new_context(viewport={"width":width,"height":844},device_scale_factor=1,
         has_touch=mobile,is_mobile=mobile,accept_downloads=True,
         service_workers="block",ignore_https_errors=True)
    page=ctx.new_page()
    net=record_network(page)
    results={}
    try:
        response=page.goto(BASE+"index.html?tab=overview&step6="+str(int(time.time())),
                           wait_until="domcontentloaded",timeout=90000)
        assert response and response.status==200
        page.wait_for_function("() => typeof window.switchTab==='function' && !!window.DashboardModules",timeout=40000)
        page.wait_for_timeout(1500)
        # Before idle prefetch (6 seconds), count actual JS requests.
        initial=[s for s in net["script_requests"]]
        results["initial_script_count"]=len(initial)
        results["initial_script_urls"]=initial
        results["initial_vendor"]=[s for s in initial if "/vendor/" in s["url"]]
        results["initial_third_party_npm"]=[s for s in initial if
            "cdn.jsdelivr.net/npm/" in s["url"] or "unpkg.com/" in s["url"]]
        assert not results["initial_third_party_npm"],results["initial_third_party_npm"]
        for tab in TABS:
            def run_tab():
                before=len(net["script_requests"])
                page.evaluate("tab=>switchTab(tab)",tab)
                page.wait_for_function("""tab => document.getElementById(tab)?.classList.contains('active')""",
                                       arg=tab,timeout=15000)
                if tab in ("hyras","t850-ensembles","sst-europe","stationSnow","era5Europe","europeStations"):
                    page.wait_for_function("""tab => window.DashboardModules?.tabReady(tab)""",arg=tab,timeout=45000)
                if tab=="monthly":
                    page.wait_for_function("() => !!window.Chart?.getChart?.('monthlyChart')",timeout=35000)
                if tab=="index":
                    page.wait_for_function("() => !!window.Chart?.getChart?.('climateIndexChart')",timeout=35000)
                if tab=="accumulation":
                    page.wait_for_function("() => !!window.Chart?.getChart?.('accumulationChart')",timeout=35000)
                if tab=="europeStations":
                    page.wait_for_function("() => !!document.querySelector('#europeStationMap.leaflet-container')",timeout=35000)
                if tab=="sst-europe":
                    page.wait_for_function("""() => document.getElementById('sstMapImage')?.naturalWidth>80 ||
                      /fehler|nicht verfügbar/i.test(document.getElementById('sstStatus')?.textContent||'')""",timeout=35000)
                if tab=="era5Synoptic":
                    page.wait_for_timeout(1300)
                else:
                    page.wait_for_timeout(650)
                ev=js_evidence(page,tab)
                ev["js_requests_during_tab"]=net["script_requests"][before:]
                if tab=="hyras":
                    ev["period_options"]=page.locator("#hyrasPeriodSelect option").count()
                if tab=="europeStations":
                    ev["map_loaded"]=page.locator("#europeStationMap.leaflet-container").count()>0
                    ev["zoom"]=page.locator("#europeStationMap .leaflet-control-zoom").count()
                if tab=="era5Synoptic":
                    ev["desktop_menu_visible"]=page.locator("#era5SynopticNav").is_visible()
                    ev["archive_days"]=page.evaluate("() => window.era5SynopticIndex?.days?.length||0")
                if tab=="accumulation":
                    assert any(c["points"]>=6 for c in ev["charts"]),ev
                if tab=="monthly":
                    assert any(c["points"]>=6 for c in ev["charts"]),ev
                if tab=="sst-europe":
                    assert page.locator("#sstMapImage").evaluate("(im)=>im.naturalWidth")>80,ev
                return ev
            try_case(results,tab,run_tab)
            if mobile and tab in ("index","europeStations"):
                try:screenshot(page,out,f"{width}-{tab}")
                except Exception:pass
        # Real Open-Meteo model request. Do not substitute cached forecasts.
        def ensembles():
            page.evaluate("switchTab('t850-ensembles')")
            page.locator("#t850LocationInput").fill("Berlin")
            page.locator("#t850LoadButton").click()
            page.wait_for_function("""() => {
               let state=document.getElementById('t850Status')?.textContent||'';
               return !document.getElementById('t850LoadButton')?.disabled &&
                  /geladen|Fehler|konnte|nicht erreichbar/i.test(state);
            }""",timeout=85000)
            ev=js_evidence(page,"t850-ensembles")
            ev["status"]=page.locator("#t850Status").inner_text()[:230]
            assert any(c["points"]>5 for c in ev["charts"]),ev
            return ev
        try_case(results,"real_ensembles_Berlin",ensembles)
        # DWD observed monthly charts, PNG/PDF real user download.
        def export_monthly():
            page.evaluate("switchTab('monthly')")
            page.locator("#monthlyFrequencyButton").click(timeout=30000)
            page.wait_for_function("""() => window.Chart?.getChart?.('monthlyFrequencyChart')?.data?.datasets
               ?.some(ds=>ds.data?.some(x=>
                 (typeof x==='number'&&Number.isFinite(x)) ||
                 (x && typeof x==='object' && Number.isFinite(x.x) && Number.isFinite(x.y))
               ))""",timeout=45000)
            chart_counts=page.evaluate("""() => {
               const chart=Chart.getChart('monthlyFrequencyChart');
               return chart.data.datasets.map(ds=>({label:ds.label,
                 finite:ds.data.filter(x=>typeof x==='number'&&Number.isFinite(x) ||
                   x && typeof x==='object' && Number.isFinite(x.x) && Number.isFinite(x.y)).length}));
            }""")
            ev={"source":"real DWD monthly data","dataset_counts":chart_counts,"downloads":[]}
            for ext,selector in [("png","#monthlyFrequencyPngButton"),("pdf","#monthlyFrequencyPdfButton")]:
                ev["downloads"].append(export(page,out,selector,ext,f"{width}-monthly"))
            return ev
        try_case(results,"real_DWD_png_pdf",export_monthly)

        # Standalone MOSMIX must consume real DWD forecast catalog and station detail.
        mos=ctx.new_page()
        mnet=record_network(mos)
        def mosmix():
            response=mos.goto(BASE+"mosmix.html?step6="+str(int(time.time())),
                             wait_until="domcontentloaded",timeout=90000)
            assert response and response.status==200
            mos.wait_for_function("""() => !!document.querySelector('#mosmixMap.leaflet-container') ||
              /Fehler|nicht gestartet/i.test(document.getElementById('mosmixSectionStatus')?.textContent||'')""",timeout=85000)
            assert mos.locator("#mosmixMap.leaflet-container").count()>0,mos.locator("#mosmixSectionStatus").inner_text()
            mos.locator("#mosmixStationSearch").fill("Frankfurt")
            mos.locator("#mosmixStationButton").click()
            mos.wait_for_function("""() => /MOSMIX-ID|konnte nicht geladen|Keine passende/i.test(
             document.getElementById('mosmixMeteogramStatus')?.textContent||'')""",timeout=70000)
            points=mos.evaluate("""() => window.Chart?.getChart?.('mosmixTempChart')
              ?.data?.datasets?.reduce((n,ds)=>n+(ds.data||[]).filter(x=>x!=null).length,0)||0""")
            ev={"map_ready":True,"station_status":mos.locator("#mosmixMeteogramStatus").inner_text()[:220],
                "real_chart_points":points,"downloads":[],"http_errors":mnet["http_errors"][:25]}
            assert points>5,ev
            for ext,selector in [("png","#mosmixDiagramPng"),("pdf","#mosmixDiagramPdf")]:
                ev["downloads"].append(export(mos,out,selector,ext,f"{width}-mosmix"))
            return ev
        try_case(results,"real_MOSMIX_and_png_pdf",mosmix)
        results["mosmix_network"]=mnet
        mos.close()
    finally:
        results["network"]=net
        results["device_width"]=width
        results["checked_at_utc"]=datetime.now(timezone.utc).isoformat()
        ctx.close()
    return results

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,default=Path("reports/live"))
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    rows=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
        try:
            for width in (1440,390):
                report=device(browser,width,a.output)
                rows.append(report)
                path=a.output/f"live-{width}.json"
                path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
                print(json.dumps({"width":width,"initial_scripts":report.get("initial_script_count"),
                  "cases":{k:v.get("ok") for k,v in report.items() if isinstance(v,dict) and "ok" in v}},
                  indent=2),flush=True)
        finally:
            browser.close()
    (a.output/"live-summary.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False))
    failed=[f"{x['device_width']}:{k}: {v.get('error','')[:180]}" for x in rows
            for k,v in x.items() if isinstance(v,dict) and v.get("ok") is False]
    if failed:
        print("FAILED LIVE CASES:",*failed,sep="\n",flush=True)
        raise SystemExit(1)

if __name__=="__main__":
    main()
