"""Real-data desktop/mobile browser QA of the standalone CPC Europe page."""
from __future__ import annotations
import contextlib
import json
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "cpc_europe_browser_qa"

def main():
    if not (ROOT/"cpc_europe/index.json").exists():
        raise RuntimeError("Browser test requires actual NOAA CPC data to be generated first")
    OUT.mkdir(exist_ok=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        port=s.getsockname()[1]
    server=subprocess.Popen(["python","-m","http.server",str(port),"--bind","127.0.0.1"],
                            cwd=ROOT, stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        url=f"http://127.0.0.1:{port}/temperatur_anomalie_europa.html"
        for _ in range(30):
            try:
                with urlopen(url,timeout=2) as res:
                    assert res.status==200
                break
            except Exception:
                time.sleep(0.3)
        else:
            raise RuntimeError("Local Pages test server did not start")
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for mobile in (False,True):
                    w,h=(390,844) if mobile else (1440,900)
                    context=browser.new_context(viewport={"width":w,"height":h},
                                                device_scale_factor=1,
                                                accept_downloads=True,is_mobile=mobile,
                                                has_touch=mobile)
                    page=context.new_page()
                    errors=[]
                    page.on("pageerror",lambda e: errors.append(str(e)))
                    page.goto(url,wait_until="domcontentloaded")
                    page.wait_for_function(
                        "() => document.getElementById('cpcDataStatus').textContent.includes('Messdaten bis')",
                        timeout=60000
                    )
                    assert page.locator("#cpcCountryRows tr[data-country]").count()>=20
                    assert page.locator("#cpcMap").evaluate("e=>e.width")>=1000
                    assert page.locator("#cpcBoundaries").evaluate("e=>e.complete && e.naturalWidth>1000")
                    # Visual-only smoothing must yield many interpolated colors,
                    # while the source country means and latest observation date stay unchanged.
                    original_row=page.locator("#cpcCountryRows tr[data-country]").first.inner_text()
                    original_date=page.locator("#cpcDataStatus").inner_text()
                    assert page.locator("#cpcSmooth").is_checked()
                    count_colors="""() => {
                      const c=document.getElementById("cpcMap");
                      const d=c.getContext("2d").getImageData(0,0,c.width,c.height).data;
                      const colors=new Set();
                      for(let y=12;y<c.height-12;y+=7)for(let x=12;x<c.width-12;x+=7){
                        const p=(y*c.width+x)*4;
                        colors.add(d[p]+","+d[p+1]+","+d[p+2]);
                      }
                      return colors.size;
                    }"""
                    soft_colors=page.evaluate(count_colors)
                    page.locator("#cpcSmooth").uncheck()
                    raster_colors=page.evaluate(count_colors)
                    assert soft_colors>raster_colors+30,(soft_colors,raster_colors)
                    assert raster_colors<=25,raster_colors
                    assert page.locator("#cpcCountryRows tr[data-country]").first.inner_text()==original_row
                    assert page.locator("#cpcDataStatus").inner_text()==original_date
                    page.locator("#cpcSmooth").check()
                    assert page.evaluate(count_colors)==soft_colors
                    page.select_option("#cpcPreset","7")
                    assert "7 beobachtete Tage" in page.locator("#cpcPeriodLabel").inner_text()
                    page.select_option("#cpcPreset","30")
                    assert "30 beobachtete Tage" in page.locator("#cpcPeriodLabel").inner_text()
                    page.locator("#cpcCountryRows tr[data-country]").first.click()
                    assert " K" in page.locator("#cpcSelected").inner_text()
                    if not mobile:
                        with page.expect_download(timeout=15000) as handle:
                            page.locator("#cpcPng").click()
                        download=handle.value
                        assert download.suggested_filename.endswith(".png")
                        download.save_as(str(OUT/"cpc_export_desktop.png"))
                        assert (OUT/"cpc_export_desktop.png").stat().st_size>20000
                        page.pdf(path=str(OUT/"cpc_export_desktop.pdf"),
                                 print_background=True,landscape=True)
                        assert (OUT/"cpc_export_desktop.pdf").stat().st_size>15000
                    else:
                        scroll=page.evaluate("({width:document.documentElement.scrollWidth,viewport:innerWidth})")
                        assert scroll["width"] <= scroll["viewport"] + 3, scroll
                    page.screenshot(path=str(OUT/("mobile.png" if mobile else "desktop.png")),
                                    full_page=True)
                    assert not errors,errors
                    context.close()
            finally:
                browser.close()
    finally:
        server.terminate()
        with contextlib.suppress(Exception):
            server.wait(timeout=5)
    print("CPC desktop and mobile browser QA passed; PNG and PDF exports verified")

if __name__=="__main__":
    main()
