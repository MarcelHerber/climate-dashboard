#!/usr/bin/env python3
"""Diagnose the dynamically rendered ČHMÚ synoptic page, without copying maps.

Runs in GitHub Actions Chromium. Captures ONLY origin/path and public DOM labels.
Never reproduces ČHMÚ imagery or invents its forecast valid timestamp.
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin,urlparse

PAGE="https://www.chmi.cz/predpoved-pocasi/synopticka-situace"
OUTPUT=Path(__file__).resolve().parents[1]/"data/synoptic_charts/chmi_browser_probe.json"


def safe_url(url):
    try:
        parsed=urlparse(urljoin(PAGE,url))
        if parsed.scheme!="https" or not (parsed.hostname or "").endswith("chmi.cz"):
            return None
        # NEVER capture signed query params, fragments or credentials.
        return f"https://{parsed.hostname}{parsed.path}"[:280]
    except Exception:
        return None

def safe_shape(value,depth=0):
    """Only public API metadata structure, not raw signed URLs or credentials."""
    if depth>=7:return "<nested>"
    if isinstance(value,dict):
        return {str(k)[:70]:safe_shape(v,depth+1) for k,v in list(value.items())[:55]
                if not any(x in str(k).lower() for x in
                           ("password","token","jwt","secret","authorization","credential","session","cookie"))}
    if isinstance(value,list):
        return {"length":len(value),"sample":[safe_shape(v,depth+1) for v in value[:5]]}
    if isinstance(value,str):
        if value.startswith(("http://","https://")):
            return safe_url(value) or "<external resource>"
        return value[:200]
    if isinstance(value,(int,float,bool)) or value is None:return value
    return str(type(value).__name__)


async def inspect():
    from playwright.async_api import async_playwright
    records=[]
    errors=[]
    api_shapes=[]
    tasks=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,
              args=["--no-sandbox","--disable-dev-shm-usage"])
        page=await browser.new_page(locale="cs-CZ",viewport={"width":1440,"height":1050})
        async def on_response(response):
            uri=safe_url(response.url)
            if uri:
                records.append({"path":uri,"status":response.status,
                                "kind":response.request.resource_type})
            if uri and "/api/playableImages/" in uri:
                entry={"path":uri,"status":response.status}
                try:
                    payload=await response.json()
                    entry["shape"]=safe_shape(payload)
                    if "/init/synopticka-mapa" in uri:
                        import base64,io
                        from PIL import Image
                        frames=payload.get("data",[]) if isinstance(payload,dict) else []
                        thumbs=[]
                        for frame in frames[:3]:
                            val=frame.get("image","")
                            if not isinstance(val,str) or not val.startswith("image/png;base64,"):
                                continue
                            raw=base64.b64decode(val.split(",",1)[1],validate=True)
                            with Image.open(io.BytesIO(raw)) as im:
                                im.thumbnail((840,620))
                                buf=io.BytesIO()
                                im.convert("RGB").save(buf,format="JPEG",quality=77,optimize=True)
                                thumbs.append({"time":frame.get("dateTime"),"width":im.width,"height":im.height,
                                    "jpeg_base64":base64.b64encode(buf.getvalue()).decode("ascii")})
                        entry["verified_image_previews"]=thumbs
                except Exception as exc:
                    entry["reason"]=(type(exc).__name__+": "+str(exc))[:130]
                api_shapes.append(entry)
        page.on("response",lambda r:tasks.append(asyncio.create_task(on_response(r))))
        page.on("pageerror",lambda error:errors.append(str(error)[:180]))
        try:
            await page.goto(PAGE,wait_until="domcontentloaded",timeout=55000)
            await page.wait_for_timeout(12000)
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
            # Some chart variants only load after the normal app is settled.
            images=await page.locator("img").evaluate_all("""nodes =>
              nodes.map(n => ({
                src:n.currentSrc||n.src||'',
                alt:(n.alt||'').slice(0,95),
                width:n.naturalWidth,height:n.naturalHeight
              }))""")
            links=await page.locator("a").evaluate_all("""nodes =>
              nodes.map(n => ({href:n.href||'',text:(n.textContent||'').trim().slice(0,90)}))""")
            selects=await page.locator("select").count()
            title=await page.title()
            data={
                "state":"browser_inspected",
                "title":title[:120],
                "select_count":selects,
                "playable_images_api":api_shapes[:8],
                "images":[{**im,"src":safe_url(im["src"])}
                          for im in images if safe_url(im["src"])][:80],
                "synoptic_links":[{"path":safe_url(li["href"]),"label":li["text"]}
                        for li in links
                        if ("synop" in li["href"].lower() or "synop" in li["text"].lower())
                            and safe_url(li["href"])][:25],
                "resources":[]
            }
            seen=set()
            for item in records:
                uri=item["path"]
                if not uri or uri in seen:continue
                seen.add(uri)
                data["resources"].append(item)
            data["resources"]=data["resources"][-160:]
        except Exception as e:
            data={"state":"browser_error","error":(type(e).__name__+": "+str(e))[:240]}
        finally:
            await browser.close()
    return {
        "schema_version":1,
        "generated_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider":"ČHMÚ","source_page":PAGE,
        "verified_validity_charts":0,
        "note":"Discovery only. No image published until public original time and license are independently verified.",
        "page_errors":errors[:12],
        **data
    }


def main():
    result=asyncio.run(inspect())
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ČHMÚ browser inspection:",result["state"],"images:",len(result.get("images",[])))


if __name__=="__main__":
    main()
