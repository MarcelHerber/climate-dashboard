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


async def inspect():
    from playwright.async_api import async_playwright
    records=[]
    errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,
              args=["--no-sandbox","--disable-dev-shm-usage"])
        page=await browser.new_page(locale="cs-CZ",viewport={"width":1440,"height":1050})
        page.on("response",lambda r:records.append({
            "path":safe_url(r.url),"status":r.status,
            "kind":r.request.resource_type}) if safe_url(r.url) else None)
        page.on("pageerror",lambda error:errors.append(str(error)[:180]))
        try:
            await page.goto(PAGE,wait_until="domcontentloaded",timeout=55000)
            await page.wait_for_timeout(12000)
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
