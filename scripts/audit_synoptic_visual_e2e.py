#!/usr/bin/env python3
"""One-off browser audit of every URL referenced by the two synoptic catalogs.

Creates browser screenshots and candidate chart-image screenshots as evidence.
Machine classifications are strictly about access/rendering, NOT definitive
meteorological content or the licensing status of a chart.
"""
import asyncio
import collections
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image, ImageDraw, ImageFont, ImageStat
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp" / "synoptic_visual_audit"
SHOTS = OUT / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)
START_UTC = dt.datetime.now(dt.timezone.utc)
RUN_ID = os.environ.get("GITHUB_RUN_ID", "")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

def read_array(path, prefix, suffix):
    s = (ROOT / path).read_text("utf-8")
    start = s.index(prefix) + len(prefix)
    end = s.index(suffix, start)
    return json.loads(s[start:end] + ("]" if suffix == "];" else ""))

def all_sources():
    world = read_array("weltweite_isobaren.html", "const DATA=", ";const REGIONS=")
    original = read_array("isobaren_original.js", "const CURATED_SOURCES=", "];")
    merged = {}
    for source, group in [(x, "weltweit") for x in world] + [(x, "europa") for x in original]:
        url = source["url"].strip()
        if not url.startswith(("https://","http://")):
            continue
        item = merged.setdefault(url, {"url":url, "names":[], "catalogs":[], "categories":[]})
        item["names"].append(source.get("name",""))
        item["catalogs"].append(group)
        item["categories"].append(source.get("status", source.get("category","unspecified")))
    return list(merged.values()), len(world), len(original)

def ocr_image(file_path):
    if not shutil.which("tesseract") or not file_path.exists():
        return ""
    try:
        p = subprocess.run(["tesseract",str(file_path),"stdout","-l","eng",
                            "--psm","11"],capture_output=True,text=True,timeout=7)
        return (p.stdout or "")[:1800]
    except Exception:
        return ""

def extract_times(text):
    stamps = re.findall(r"\b(?:0[0369]|1[258]|21)\s*(?:UTC|Z)\b|\b\d{1,2}:\d{2}\s*(?:UTC|Z)\b",
                        text, re.I)
    dates = re.findall(r"\b(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]20\d{2})\b", text)
    return {"utc_marks": list(dict.fromkeys(stamps))[:18], "date_marks":list(dict.fromkeys(dates))[:20]}

def thumbnail(src, label, width=340, height=240):
    frame=Image.new("RGB",(width,height),"white")
    try:
        with Image.open(src) as im:
            im.convert("RGB").thumbnail((width-12,height-44))
            sample=im.convert("RGB")
            frame.paste(sample,((width-sample.width)//2,35+(height-40-sample.height)//2))
    except Exception:
        pass
    d=ImageDraw.Draw(frame)
    d.rectangle((0,0,width,31),fill="#e6eaf0")
    d.text((7,7),label[:47],fill="#172638")
    return frame

async def one(browser, sem, domain_sems, i, source):
    url=source["url"]
    name=source["names"][0]
    hostname=urlsplit(url).netloc
    domain_sems.setdefault(hostname, asyncio.Semaphore(2))
    entry=dict(source, ordinal=i+1, checked_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
               http_status=None, final_url="", content_type="", title="", page_text="", 
               page_utc_marks=[], page_date_marks=[], image_utc_marks=[], image_date_marks=[],
               images=[], best_image_url="", largest_img_dimensions=None,
               screenshot=f"screenshots/{i+1:03d}_page.jpg",
               chart_screenshot="", stage="not_started", error="", likely_challenge=False)
    async with sem, domain_sems[hostname]:
        context=None
        try:
            context=await browser.new_context(user_agent=UA, viewport={"width":1366,"height":880},
                                               ignore_https_errors=True, locale="en-US",
                                               device_scale_factor=1, service_workers="block")
            page=await context.new_page()
            try:
                response=await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except PlaywrightTimeout as exc:
                entry["error"]="navigation_timeout"
                response=None
            except Exception as exc:
                entry["error"]=str(exc)[:300]
                response=None
            if response:
                entry["http_status"]=response.status
                entry["content_type"]=(response.headers.get("content-type","") or "")[:100]
            entry["final_url"]=page.url
            try:
                await page.wait_for_timeout(800)
                await page.screenshot(path=str(OUT/entry["screenshot"]), type="jpeg", quality=62,
                                      timeout=7000, animations="disabled")
            except Exception as exc:
                entry["error"] += "; screenshot "+str(exc)[:120]
            try:
                entry["title"]=(await page.title())[:240]
                info=await page.evaluate("""() => {
                  const txt=(document.body?.innerText||'').slice(0,9000);
                  const photos=[...document.querySelectorAll('img')].map((e,i)=>{
                    const b=e.getBoundingClientRect();
                    return {index:i, src:e.currentSrc||e.src||'',alt:e.alt||'',
                      w:e.naturalWidth||0,h:e.naturalHeight||0,
                      screen_w:Math.round(b.width),screen_h:Math.round(b.height)};});
                  return {text:txt, images:photos, canvases:document.querySelectorAll('canvas').length,
                    svg:document.querySelectorAll('svg').length,
                    iframes:[...document.querySelectorAll('iframe')].map(x=>x.src).slice(0,10),
                    pdf_links:[...document.querySelectorAll('a[href]')].map(a=>a.href).filter(x=>/\.pdf([?#]|$)/i.test(x)).slice(0,8)};
                }""")
                entry["page_text"]=info["text"][:1200]
                entry["images"]=sorted(info["images"],key=lambda x:(x["w"]*x["h"]),reverse=True)[:8]
                entry["iframes"]=info["iframes"]
                entry["canvases"]=info["canvases"]
                entry["svg_elements"]=info["svg"]
                entry["pdf_links"]=info["pdf_links"]
                entry["page_utc_marks"]=extract_times(info["text"])["utc_marks"]
                entry["page_date_marks"]=extract_times(info["text"])["date_marks"]
                entry["likely_challenge"]=bool(re.search(r"captcha|access denied|are you human|cloudflare|forbidden|robot verification|just a moment",info["text"][:1700],re.I))
                candidates=[x for x in info["images"] if x["w"]>=380 and x["h"]>=240]
                if candidates:
                    best=candidates[0]
                    entry["best_image_url"]=best["src"][:900]
                    entry["largest_img_dimensions"]=[best["w"],best["h"]]
                    cpath=f"screenshots/{i+1:03d}_map.png"
                    try:
                        locator=page.locator("img").nth(best["index"])
                        await locator.scroll_into_view_if_needed(timeout=4500)
                        await locator.screenshot(path=str(OUT/cpath),timeout=6000,animations="disabled")
                        entry["chart_screenshot"]=cpath
                        ocr=await asyncio.to_thread(ocr_image,OUT/cpath)
                        entry["image_utc_marks"]=extract_times(ocr)["utc_marks"]
                        entry["image_date_marks"]=extract_times(ocr)["date_marks"]
                        entry["image_ocr_excerpt"]=ocr[:500]
                    except Exception as exc:
                        entry["error"]+="; img "+str(exc)[:100]
                elif info["canvases"]:
                    try:
                        cpath=f"screenshots/{i+1:03d}_canvas.png"
                        await page.locator("canvas").first.screenshot(path=str(OUT/cpath),timeout=5000)
                        entry["chart_screenshot"]=cpath
                        ocr=await asyncio.to_thread(ocr_image,OUT/cpath)
                        entry["image_utc_marks"]=extract_times(ocr)["utc_marks"]
                        entry["image_date_marks"]=extract_times(ocr)["date_marks"]
                        entry["image_ocr_excerpt"]=ocr[:500]
                    except Exception as exc:
                        entry["error"]+="; canvas "+str(exc)[:100]
            except Exception as exc:
                entry["error"]+="; DOM "+str(exc)[:190]
            status=entry["http_status"]
            typ=entry["content_type"].lower()
            if status==404 or status==410:
                entry["stage"]="http_missing"
            elif status==403 or status==429 or entry["likely_challenge"]:
                entry["stage"]="access_blocked_or_challenge"
            elif status is not None and status>=500:
                entry["stage"]="server_error"
            elif status is None:
                entry["stage"]="unresolved_navigation"
            elif "image/" in typ:
                entry["stage"]="image_rendered_needs_visual_validation"
            elif "pdf" in typ:
                entry["stage"]="pdf_endpoint_needs_page_validation"
            elif "json" in typ:
                entry["stage"]="api_response_needs_layer_validation"
            elif entry["chart_screenshot"]:
                entry["stage"]="page_with_large_visual_needs_map_validation"
            elif entry.get("canvases",0) or entry.get("iframes"):
                entry["stage"]="dynamic_page_needs_map_validation"
            elif status>=200 and status<400:
                entry["stage"]="page_without_large_map_evidence"
            else:
                entry["stage"]="unclassified"
        except Exception as exc:
            entry["stage"]="browser_error"
            entry["error"] += "; outer "+str(exc)[:260]
        finally:
            if context:
                try: await context.close()
                except Exception: pass
        print(f"AUDIT [{i+1:03d}/{len(SOURCES)}] {entry['stage']:44} HTTP={entry['http_status']} {hostname} {name[:31]}",flush=True)
        return entry

def build_report(results, original_count, world_count):
    counts=dict(collections.Counter(z["stage"] for z in results))
    report={"schema_version":2, "created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
      "test_started_utc":START_UTC.isoformat(),
      "github_actions_run_url":f"https://github.com/MarcelHerber/climate-dashboard/actions/runs/{RUN_ID}" if RUN_ID else "",
      "sources_original":original_count,"sources_world":world_count,"unique_urls":len(results),
      "note":"Alle URL-Ziele wurden mit einem echten Headless-Chromium-Browser geöffnet, DOM-/Bildinformationen und Screenshots gespeichert. Automatische Erreichbarkeitsprüfung ist KEIN menschliches visuelles Urteil über meteorologischen Inhalt, Rechte oder UTC-Aktualität. Zeitstempel aus OCR sind Indizien, keine verifizierten Analysegültigkeiten. Fehler/403 können Bot-Abwehr bedeuten.",
      "stages":counts,
      "results":results}
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    # Lightweight summary copied into public repo; screenshots remain an artifact for rights reasons.
    public={"schema_version":2,"created_utc":report["created_utc"],"test_started_utc":report["test_started_utc"],
      "github_actions_run_url":report["github_actions_run_url"],"unique_urls":len(results),
      "sources_world":world_count,"sources_original":original_count,"stages":counts,
      "note":report["note"],"results":[{k:v for k,v in x.items() if k not in 
           ("page_text","image_ocr_excerpt","images","iframes","pdf_links","screenshot","chart_screenshot")}
         for x in results]}
    dest=ROOT/"data/synoptic_charts/isobaren_e2e_latest.json"
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(public,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    html_rows=[]
    sheets=[]
    for k in range(0,len(results),20):
        canvas=Image.new("RGB",(340*4,240*5),"#ffffff")
        for j,entry in enumerate(results[k:k+20]):
            img=OUT/(entry["chart_screenshot"] or entry["screenshot"])
            thumb=thumbnail(img,f"{entry['ordinal']:03d} {entry['names'][0][:32]}")
            canvas.paste(thumb,((j%4)*340,(j//4)*240))
        dest_sheet=OUT/f"contact_sheet_{k//20+1:02d}.jpg"
        canvas.save(dest_sheet,quality=80)
        sheets.append(dest_sheet.name)
    for entry in results:
        fn=entry["chart_screenshot"] or entry["screenshot"]
        thumb=html.escape(fn)
        url=html.escape(entry["url"],quote=True)
        name=html.escape(entry["names"][0])
        stage=html.escape(entry["stage"])
        when=html.escape(",".join(entry["image_utc_marks"] or entry["page_utc_marks"]) or "nicht lesbar")
        dates=html.escape(",".join(entry["image_date_marks"] or entry["page_date_marks"]) or "nicht lesbar")
        html_rows.append(f'<article><a href="{url}" target="_blank" rel="noopener"><b>{entry["ordinal"]:03d}. {name}</b></a>'
           f'<p><small>{stage}, HTTP {entry["http_status"]} · UTC: {when} · Datum: {dates}</small></p>'
           f'<a href="{html.escape(entry["screenshot"])}"><img loading="lazy" src="{thumb}"></a>'
           f'<p><small>{url}</small></p></article>')
    markup='''<!DOCTYPE html><html lang="de"><meta charset="utf-8"><title>Synoptik Linkaudit</title>
<style>body{font:14px system-ui;background:#f2f5f8;color:#192b3b;margin:28px}
h1{font-size:28px}p{max-width:1000px}article{background:white;padding:12px;border-radius:8px;min-width:0;overflow-wrap:anywhere}
article img{max-width:100%;height:190px;object-fit:contain}article p{margin:8px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:15px}
a{color:#175f86}</style><h1>Synoptik: Browser- und Karten-Sichtprüfung</h1>''' 
    markup+='<p>Automatische Browser-Screenshots von 120 individuellen URLs. Die Bildinhalte sind erst nach manueller Betrachtung meteorologisch und zeitlich bestätigt. Gesperrte Zugriffe gelten nicht automatisch als defekte Quellen.</p>'
    markup+='<p><a href="report.json">Maschinenlesbarer Prüfbericht</a> | '
    markup+=' | '.join(f'<a href="{html.escape(sheet)}">Kontaktbogen {i+1}</a>' for i,sheet in enumerate(sheets))+"</p>"
    markup+='<main class="grid">'+"\n".join(html_rows)+"</main></html>"
    (OUT/"index.html").write_text(markup,encoding="utf-8")
    print("AUDIT_COMPLETE "+json.dumps({"unique_urls":len(results),"stages":counts,"artifact_index":"tmp/synoptic_visual_audit/index.html","public_json":"data/synoptic_charts/isobaren_e2e_latest.json"},ensure_ascii=False),flush=True)

async def main():
    global SOURCES
    SOURCES,world_count,original_count=all_sources()
    print(f"AUDIT_INIT {len(SOURCES)} distinct URLs / {world_count} global entries / {original_count} original entries",flush=True)
    sem=asyncio.Semaphore(6)
    domain_sems={}
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
        tasks=[one(browser,sem,domain_sems,i,s) for i,s in enumerate(SOURCES)]
        results=await asyncio.gather(*tasks)
        await browser.close()
    build_report(results,original_count,world_count)

if __name__=="__main__":
    asyncio.run(main())
