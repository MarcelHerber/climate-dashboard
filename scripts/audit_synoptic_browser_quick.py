#!/usr/bin/env python3
"""Bounded Chromium screenshot probe for every unique catalog URL."""
import asyncio,datetime as dt,json,re,os,html,shutil
from pathlib import Path
from urllib.parse import urlsplit
from collections import Counter
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"tmp/synoptic_browser_quick"
SHOTS=OUT/"screens"
SHOTS.mkdir(parents=True,exist_ok=True)
def grab(path,needle,ending):
    text=(ROOT/path).read_text("utf-8")
    p=text.index(needle)+len(needle); q=text.index(ending,p)
    return json.loads(text[p:q]+("]" if ending=="];" else ""))
world=grab("weltweite_isobaren.html","const DATA=",";const REGIONS=")
eu=grab("isobaren_original.js","const CURATED_SOURCES=","];")
rows={}
for origin,sources in [("weltweite",world),("europa",eu)]:
    for item in sources:
        u=item.get("url","")
        if u.startswith(("http://","https://")):
            r=rows.setdefault(u,{"url":u,"name":item.get("name",""),"listed_in":[]})
            r["listed_in"].append(origin)
items=list(rows.values())
sem=asyncio.Semaphore(9)
domain_sems={}
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

async def inspect(browser,i,info):
    r={**info,"ordinal":i+1,"http":None,"final_url":"","title":"","content_type":"","page_screenshot":"",
       "largest_image_screenshot":"","visible_imgs":[],"canvas_count":0,"iframes":[],
       "date_or_utc_mentions":[],"stage":"unexamined","error":""}
    context=None
    try:
        context=await browser.new_context(user_agent=UA,viewport={"width":1280,"height":860},
             ignore_https_errors=True,device_scale_factor=1,service_workers="block")
        page=await context.new_page()
        resp=None
        try:resp=await page.goto(info["url"],wait_until="domcontentloaded",timeout=11000)
        except Exception as err:r["error"]+="nav "+str(err)[:130]
        if resp:
            r["http"]=resp.status
            r["content_type"]=(resp.headers.get("content-type") or "")[:100]
        r["final_url"]=page.url
        await page.wait_for_timeout(320)
        try:
            sp=SHOTS/f"page_{i+1:03d}.jpg"
            await page.screenshot(path=str(sp),type="jpeg",quality=65,timeout=3700,animations="disabled")
            r["page_screenshot"]="screens/"+sp.name
        except Exception as err:r["error"]+=" screen "+str(err)[:100]
        try:
            data=await asyncio.wait_for(page.evaluate("""() => ({
              title:document.title||'', text:(document.body?.innerText||'').slice(0,5500),
              imgs:[...document.querySelectorAll('img')].map((x,i)=>({
                index:i,src:x.currentSrc||x.src||'',alt:x.alt||'',
                w:x.naturalWidth||0,h:x.naturalHeight||0
              })).sort((a,b)=>b.w*b.h-a.w*a.h).slice(0,10),
              frames:[...document.querySelectorAll('iframe')].map(x=>x.src).slice(0,6),
              canvas:document.querySelectorAll('canvas').length
            })"""),timeout=3.5)
            r["title"]=data["title"][:170]
            r["visible_imgs"]=data["imgs"]
            r["canvas_count"]=data["canvas"]
            r["iframes"]=data["frames"]
            text=data["text"]
            r["date_or_utc_mentions"]=list(dict.fromkeys(re.findall(r"\b(?:\d{1,2}[:.]\d{2}\s*(?:UTC|Z)|(?:0[0369]|1[258]|21)\s*UTC|20\d{2}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]20\d{2})\b",text,re.I)))[:15]
            best=next((x for x in data["imgs"] if x["w"]>=400 and x["h"]>=250),None)
            if best:
                try:
                    p=SHOTS/f"map_{i+1:03d}.png"
                    await page.locator("img").nth(best["index"]).screenshot(path=str(p),timeout=3800,animations="disabled")
                    r["largest_image_screenshot"]="screens/"+p.name
                except Exception as err:r["error"]+=" map "+str(err)[:100]
        except Exception as err:r["error"]+=" DOM "+str(err)[:150]
        if r["http"] in [403,429]:r["stage"]="blocked_access_not_dead"
        elif r["http"] in [404,410]:r["stage"]="http_missing"
        elif r["http"] and r["http"]>=500:r["stage"]="server_error"
        elif r["http"] is None:r["stage"]="navigation_error_or_timeout"
        elif "image/" in r["content_type"] or "octet-stream" in r["content_type"]:
            r["stage"]="image_endpoint_browser_reached"
        elif r["largest_image_screenshot"]:r["stage"]="browser_map_candidate_image_captured"
        elif r["canvas_count"] or r["iframes"]:r["stage"]="dynamic_viewer_captured_unverified"
        elif r["page_screenshot"]:r["stage"]="html_screenshot_no_large_map"
        else:r["stage"]="no_visual_evidence"
    except asyncio.CancelledError:
        r["stage"]="overall_timeout";r["error"]+=" 26sec outer limit"
    except Exception as err:
        r["stage"]="browser_error";r["error"]+=str(err)[:180]
    finally:
        if context:
            try:await asyncio.wait_for(context.close(),timeout=3)
            except Exception:pass
    print(f"VISUAL {i+1:03d}/{len(items)} {r['stage']} HTTP {r['http']} {urlsplit(info['url']).netloc}",flush=True)
    return r

async def bounded(browser,i,x):
    host=urlsplit(x["url"]).netloc
    domain_sems.setdefault(host,asyncio.Semaphore(2))
    async with sem,domain_sems[host]:
        try:return await asyncio.wait_for(inspect(browser,i,x),timeout=26)
        except Exception as err:
            return {**x,"ordinal":i+1,"stage":"overall_timeout","http":None,"error":str(err)[:100],"page_screenshot":"","largest_image_screenshot":""}

async def main():
    async with async_playwright() as p:
        binary=shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
        args={"headless":True,"args":["--no-sandbox","--disable-dev-shm-usage"]}
        if binary:args["executable_path"]=binary
        browser=await p.chromium.launch(**args)
        results=await asyncio.gather(*(bounded(browser,i,x) for i,x in enumerate(items)))
        await browser.close()
    counts=dict(Counter(r["stage"] for r in results))
    timestamp=dt.datetime.now(dt.timezone.utc).isoformat()
    audit={"schema_version":1,"checked_utc":timestamp,"world_sources":len(world),
        "europe_sources":len(eu),"unique_urls":len(results),"run_url":f"https://github.com/MarcelHerber/climate-dashboard/actions/runs/{os.getenv('GITHUB_RUN_ID','')}",
        "counts":counts,"caveat":"Screenshots are real Chromium renders, but not independent human map-content validation. Browser limitations and stale dates are tracked separately; 200 does not prove isobars, 403 does not prove dead links. Each link gets a bounded 26-second attempt.", "results":results}
    (OUT/"report.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")
    slim={**audit,"results":[{k:v for k,v in x.items() if k not in ["page_screenshot","largest_image_screenshot","visible_imgs","iframes"]} for x in results]}
    path=ROOT/"data/synoptic_charts/isobaren_browser_quick_latest.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(slim,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    cards=[]
    for x in results:
        u=html.escape(x["url"],quote=True);name=html.escape(x["name"])
        shot=html.escape(x.get("largest_image_screenshot") or x.get("page_screenshot") or "")
        stage=html.escape(x["stage"])
        cards.append(f'<article><b>{x["ordinal"]:03d} {name}</b><p>{stage} | HTTP {x.get("http")}</p><a href="{u}">{u}</a><img loading="lazy" src="{shot}"></article>')
    doc="""<!doctype html><html lang=de><meta charset=utf-8><title>Alle Synoptik-Links: Browser-Screenshots</title>
<style>body{font:14px system-ui;background:#edf1f5;padding:18px;color:#172636}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
article{background:white;padding:11px;border-radius:8px;overflow-wrap:anywhere}
img{display:block;width:100%;height:200px;object-fit:contain}a{color:#185579}</style>
<h1>120 synoptische Linkziele – tatsächlich gerenderte Browseransichten</h1>
<p>Ein Screenshot beweist nur, was ein Browser angezeigt hat, nicht dass es eine aktuelle amtliche Isobarenkarte ist. Siehe auch report.json.</p><main>"""
    (OUT/"index.html").write_text(doc+"\n".join(cards)+"</main></html>",encoding="utf-8")
    print("QUICK_VISUAL_AUDIT_COMPLETE "+json.dumps({"urls":len(results),"counts":counts},ensure_ascii=False),flush=True)
asyncio.run(main())
