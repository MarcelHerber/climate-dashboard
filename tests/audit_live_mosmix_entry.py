#!/usr/bin/env python3
"""Public-page navigation test; no switchTab calls or mocked responses."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE="https://marcelherber.github.io/climate-dashboard/"
OUT=Path("reports/live-mosmix")
OUT.mkdir(parents=True,exist_ok=True)
results=[]
def ready(page,standalone=False):
    page.wait_for_function("""standalone => {
      const root=document.getElementById('mosmix');
      return !!root && root.classList.contains('active') &&
        !!root.querySelector('#mosmixMap.leaflet-container') &&
        !root.hasAttribute('data-mosmix-lazy-shell') &&
        !!root.querySelector('#mosmixStationSearch');
    }""",arg=standalone,timeout=90000)
    return page.locator("#mosmixRunInfo").inner_text()
with sync_playwright() as p:
    browser=p.chromium.launch(channel="chrome",headless=True)
    for width in (1440,390):
        for route in ("menu","direct"):
            ctx=browser.new_context(viewport={"width":width,"height":844},
                is_mobile=width<600,has_touch=width<600,service_workers="block")
            page=ctx.new_page()
            urls=[];errors=[];http=[]
            page.on("request",lambda req:urls.append(req.url))
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.on("response",lambda r:http.append([r.status,r.url]) if r.status>=400 else None)
            row={"width":width,"route":route}
            try:
                page.goto(BASE+"index.html?tab="+("overview" if route=="menu" else "mosmix"),
                    wait_until="domcontentloaded",timeout=90000)
                if route=="menu":
                    page.wait_for_function("() => document.getElementById('overview')?.classList.contains('active') && !!window.DashboardOptionalModules",timeout=30000)
                    assert not any("/mosmix.js" in u for u in urls), "MOSMIX already loaded before first navigation"
                    if width>800:
                        page.locator('.nav-dropdown[data-nav-group="germany"] .nav-dropdown-toggle').click()
                        button=page.locator('button[data-mosmix-nav="1"]')
                    else:
                        page.locator("#cdMobileMenuButton").click()
                        button=page.locator("#cdMobileMenu .cdm-item").get_by_text("MOSMIX",exact=True)
                        button.locator("xpath=ancestor::details/summary").click()
                    button.wait_for(state="visible",timeout=10000)
                    row["menu_visible_before_first_switch"]=True
                    page.screenshot(path=str(OUT/f"{width}-menu.png"))
                    button.click()
                row["run_info"]=ready(page)
                row["final_url"]=page.url
                row["mosmix_script_requests"]=sum("/mosmix.js" in u for u in urls)
                assert row["mosmix_script_requests"]==1,row
                assert not errors,errors
                row["ok"]=True
                page.screenshot(path=str(OUT/f"{width}-{route}-map.png"))
            except Exception as e:
                row["ok"]=False;row["error"]=str(e)
            finally:
                row["page_errors"]=errors;row["http_errors"]=http
                results.append(row);ctx.close()
    browser.close()
(OUT/"result.json").write_text(json.dumps(results,indent=2,ensure_ascii=False))
print(json.dumps(results,indent=2,ensure_ascii=False))
assert all(r["ok"] for r in results)
