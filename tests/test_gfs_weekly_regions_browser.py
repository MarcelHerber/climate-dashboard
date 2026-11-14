"""Real-data desktop/mobile browser checks for selectable GFS weekly map areas."""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"gfs_regions_browser_qa"
REGIONS=("europe","west","central","germany","nordics",
         "east","med","iberia","alps","atlantic")

def main():
    archive=json.loads((ROOT/"gfs_analysis_europe/weekly_f003.json").read_text())
    assert len(archive["sources"])==28 and archive["reference_metadata"]["source_months"]==360
    OUT.mkdir(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        port=sock.getsockname()[1]
    server=subprocess.Popen(["python","-m","http.server",str(port),"--bind","127.0.0.1"],
                            cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        url=f"http://127.0.0.1:{port}/gfs_weekly_europe.html"
        for _ in range(50):
            try:
                with urlopen(url,timeout=3) as page:
                    assert page.status==200
                break
            except Exception:
                time.sleep(.25)
        else: raise RuntimeError("Local GFS region browser web server failed")
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for mobile in (False,True):
                    ctx=browser.new_context(
                        viewport={"width":390 if mobile else 1440,
                                  "height":844 if mobile else 960},
                        is_mobile=mobile,has_touch=mobile,accept_downloads=True)
                    page=ctx.new_page()
                    errs=[]
                    page.on("pageerror",lambda exc:errs.append(str(exc)))
                    page.goto(url,wait_until="domcontentloaded")
                    page.wait_for_function("() => document.getElementById('weekStatus').textContent.includes('28 Originalfelder')",timeout=45000)
                    assert page.locator("#weekWarning").is_hidden(),page.locator("#weekWarning").inner_text()
                    assert page.locator("#weekRegion").input_value()=="europe"
                    choices=page.locator("#weekRegion option").evaluate_all("opts=>opts.map(o=>o.value)")
                    assert choices==list(REGIONS),choices
                    country=page.locator("#weekCountries tr[data-country]").first.inner_text()
                    baseline=page.locator("#weekMap").evaluate("e=>e.toDataURL('image/png').length")
                    assert baseline>30000
                    for region in ("germany","nordics","med","atlantic","europe"):
                        page.locator("#weekRegion").select_option(region)
                        assert page.locator("#weekWarning").is_hidden()
                        assert page.locator("#weekMap").evaluate("e=>e.width===1400&&e.height===760")
                        assert page.locator("#weekCountries tr[data-country]").first.inner_text()==country
                    page.locator("#weekRegion").select_option("germany")
                    img=page.locator("#weekMap").evaluate("e=>e.toDataURL('image/png').length")
                    assert abs(img-baseline)>1000,"Germany crop indistinguishable from whole Europe"
                    assert "Deutschland" in page.locator("#weekMapLabel").inner_text()
                    if mobile:
                        full=page.evaluate("({a:document.documentElement.scrollWidth,b:innerWidth})")
                        assert full["a"]<=full["b"]+3,full
                        page.screenshot(path=str(OUT/"germany_mobile.png"),full_page=True)
                    else:
                        page.screenshot(path=str(OUT/"germany_desktop.png"),full_page=True)
                        for projection in ("latlon","stereo"):
                            page.locator("#weekProjection").select_option(projection)
                            assert page.locator("#weekWarning").is_hidden()
                        with page.expect_download(timeout=20000) as d:
                            page.locator("#weekPng").click()
                        d.value.save_as(str(OUT/"germany_crop.png"))
                        assert (OUT/"germany_crop.png").stat().st_size>12000
                        with page.expect_download(timeout=20000) as d:
                            page.locator("#weekCsv").click()
                        assert d.value.suggested_filename.endswith(".csv")
                        page.pdf(path=str(OUT/"region.pdf"),landscape=True,print_background=True)
                        assert (OUT/"region.pdf").stat().st_size>12000
                    assert not errs,errs
                    ctx.close()
            finally:browser.close()
    finally:
        server.terminate()
        with contextlib.suppress(Exception):server.wait(timeout=5)
    print("PASS: 10 genuine-GFS region options; polar and geographic crops; "
          "desktop and mobile; unchanged original country values; PNG/PDF/CSV",flush=True)

if __name__=="__main__":
    main()
