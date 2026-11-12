#!/usr/bin/env python3
"""Real cold browser load-time audit for Phase 1, with no mocked data.

Measure HTTPS Pages as actually published, on a narrow touch viewport and
a desktop viewport. Report network and upstream failures independently from
frontend chart readiness; never confuse transfer savings with measured speed.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from playwright.sync_api import sync_playwright

BASE="https://marcelherber.github.io/climate-dashboard/"
OUTPUT=Path("phase1_live_perf")
OUTPUT.mkdir(parents=True,exist_ok=True)
CASES=(
    ("stationSnow","index.html?tab=stationSnow"),
    ("stationPrecip","index.html?tab=stationPrecip"),
    ("satellite","satelliten.html"),
)

def audit(browser,viewport,module,url):
    mobile=viewport==390
    context=browser.new_context(
        viewport={"width":viewport,"height":840},has_touch=mobile,
        is_mobile=mobile,device_scale_factor=1,service_workers="block")
    page=context.new_page()
    row={"viewport_px":viewport,"mobile":mobile,"module":module,
         "url":BASE+url,"cold_context":True}
    errors=[];failed=[];http=[]
    page.on("pageerror",lambda error:errors.append(str(error)[:220]))
    page.on("requestfailed",lambda request:failed.append(
        {"url":request.url[:220],"failure":request.failure}))
    page.on("response",lambda response:http.append(
        {"status":response.status,"url":response.url[:220]})
        if response.status>=400 else None)
    start=perf_counter()
    try:
        response=page.goto(BASE+url,wait_until="domcontentloaded",timeout=70000)
        row["html_status"]=response.status if response else None
        row["domcontentloaded_ms"]=round((perf_counter()-start)*1000)
        if module=="satellite":
            try:
                page.wait_for_function("""() => {
                  const options=document.getElementById("satTime")?.options?.length||0;
                  const kind=document.getElementById("satStatus")?.dataset?.kind;
                  return options>1||kind==="error";
                }""",timeout=25000)
                row["metadata_ready_ms"]=round((perf_counter()-start)*1000)
            except Exception as error:
                row["metadata_error"]=str(error)[:230]
            # A WMS error is a resolved *request*, not a successful picture.
            # Require actual decoded pixels in the visible still image. The
            # original audit accidentally marked status='error' as success.
            try:
                page.wait_for_function("""() => {
                  const img=document.getElementById("satImage");
                  return !!img && !img.hidden && img.complete && img.naturalWidth>0;
                }""",timeout=35000)
                row["satellite_image_ready_ms"]=round((perf_counter()-start)*1000)
            except Exception as error:
                row["satellite_error"]=str(error)[:230]
            row["satellite_status"]=page.locator("#satStatus").inner_text()[:240]
            row["image_width"]=page.locator("#satImage").evaluate("(el)=>el.naturalWidth")
            row["image_src"]=page.locator("#satImage").get_attribute("src")
            row["observation_label"]=page.locator("#satValid").inner_text()[:160]
            row["archived_fallback"]=("Archivaufnahme:" in row["observation_label"]
                                       and row["image_width"]>0)
            row["live_image"]=("Beobachtung:" in row["observation_label"]
                                and row["image_width"]>0)
            row["script_url"]=page.locator('script[src*="satelliten.js"]').get_attribute("src")
            row["deployed_fastcache_script"]=bool(row["script_url"]
                and "fastcache-v1" in row["script_url"])
            if row["image_width"]==0:
                page.screenshot(path=str(OUTPUT/f"satellite_failed_{viewport}.png"),
                    full_page=True)
        else:
            try:
                page.wait_for_function("""tab => {
                    const canvas=document.getElementById(tab+"Chart");
                    return !!canvas && !!window.Chart?.getChart?.(canvas);
                }""",arg=module,timeout=110000)
                row["chart_ready_ms"]=round((perf_counter()-start)*1000)
            except Exception as error:
                row["chart_error"]=str(error)[:300]
            row["chart_present"]=page.evaluate("""tab => {
                const canvas=document.getElementById(tab+"Chart");
                return !!canvas && !!window.Chart?.getChart?.(canvas);
            }""",module)
        page.wait_for_timeout(350)
        row["viewport_overflow"]=page.evaluate(
            "()=>document.documentElement.scrollWidth>window.innerWidth+3")
        row["resources"]=page.evaluate("""() => performance.getEntriesByType("resource")
            .filter(x=>/\.json(?:\?|$)|\.js(?:\?|$)/.test(x.name))
            .sort((a,b)=>b.duration-a.duration).slice(0,12)
            .map(x=>({name:x.name.split("?")[0].split("/").pop(),
                duration_ms:Math.round(x.duration),
                transfer_bytes:x.transferSize||null,
                decoded_bytes:x.decodedBodySize||null}))""")
        row["ok"]=row.get("html_status")==200 and (
            (row.get("image_width",0)>0 and row.get("deployed_fastcache_script",False))
            if module=="satellite" else row.get("chart_present",False))
    except Exception as error:
        row["ok"]=False;row["error"]=str(error)[:350]
    finally:
        row["page_errors"]=errors[:8]
        row["request_failures"]=failed[:12]
        row["http_errors"]=http[:12]
        context.close()
    return row

def main():
    result={"generated_utc":datetime.now(timezone.utc).isoformat(),
        "source":"Real published GitHub Pages; no mocks; cold Chromium contexts",
        "results":[]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
        try:
            for viewport in (390,1200):
                for module,url in CASES:
                    row=audit(browser,viewport,module,url)
                    result["results"].append(row)
                    print(json.dumps({k:row.get(k) for k in
                        ("module","viewport_px","html_status","domcontentloaded_ms",
                         "chart_ready_ms","metadata_ready_ms","satellite_image_ready_ms",
                         "image_width","archived_fallback","deployed_fastcache_script",
                         "ok","satellite_error","chart_error","error")},ensure_ascii=False),flush=True)
        finally:
            browser.close()
    dest=OUTPUT/"report.json"
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Complete report:",dest)
    failures=[r for r in result["results"] if not r.get("ok")]
    if failures:
        raise SystemExit("Real data or chart not available in "
                         +", ".join(f"{r['module']} ({r['viewport_px']} px)" for r in failures))

if __name__=="__main__":
    main()
