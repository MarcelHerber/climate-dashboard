"""Browser QA against complete real NOAA GFS/CFSR 121x361 widened weekly anomaly.

Requires original verified 30-year reference and published NOAA f003..f165
field JSON plus Natural Earth 50m geography. No substitute/mocks.
"""
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
DATA=ROOT/"gfs_analysis_europe/weekly_f003_extended.json"
GEO=ROOT/"gfs_analysis_europe/extended_geography.json"
OUT=ROOT/"gfs_weekly_extended_browser_qa"

REGIONS=("europe","west","central","germany","nordics",
         "east","med","iberia","alps","atlantic","greenland","iceland","eurasia")


def main():
    payload=json.loads(DATA.read_text(encoding="utf-8"))
    geography=json.loads(GEO.read_text(encoding="utf-8"))
    assert payload["sample_count"]==28 and payload["lead_hours"]==list(range(3,166,6))
    assert payload["reference_version"]=="cfsr-cfsv2-t2m-f003-extended-v1"
    assert payload["reference_metadata"]["source_months"]==360
    assert (payload["width"],payload["height"])==(361,121)
    assert (geography["width"],geography["height"])==(361,121)
    assert len(geography["countries"])>60 and len(geography["rings"])>100
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
                with urlopen(url,timeout=3) as response:assert response.status==200
                break
            except Exception:time.sleep(.2)
        else:raise RuntimeError("Cannot serve original 7-day wide GFS data")
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for mobile in (False,True):
                    ctx=browser.new_context(
                        viewport={"width":390 if mobile else 1440,
                                  "height":844 if mobile else 950},
                        is_mobile=mobile,has_touch=mobile,accept_downloads=True)
                    page=ctx.new_page()
                    errors=[]
                    page.on("pageerror",lambda ex:errors.append(str(ex)))
                    page.goto(url,wait_until="domcontentloaded")
                    page.wait_for_function(
                        "() => document.getElementById('weekReference').textContent.includes('erweitertes Originalraster')",
                        timeout=60000)
                    page.wait_for_function(
                        "() => document.querySelectorAll('#weekCountries tr[data-country]').length>=30",
                        timeout=60000)
                    assert page.locator("#weekWarning").is_hidden(),page.locator("#weekWarning").inner_text()
                    assert "28 Originalfelder" in page.locator("#weekStatus").inner_text()
                    choices=page.locator("#weekRegion option").evaluate_all("xs=>xs.map(x=>x.value)")
                    assert choices==list(REGIONS),choices
                    assert "80°W–100°O" in page.locator("#weekReference").inner_text()
                    default=page.locator("#weekMap").evaluate("e=>e.toDataURL('image/png').length")
                    assert default>30000
                    countries=page.locator("#weekCountries tr[data-country]").count()
                    assert countries>=30
                    for key in ("atlantic","greenland","iceland","eurasia","europe",
                                "germany","nordics","east"):
                        page.locator("#weekRegion").select_option(key)
                        assert page.locator("#weekWarning").is_hidden()
                        assert page.locator("#weekMap").evaluate("e=>e.width==1400&&e.height==760")
                    page.locator("#weekRegion").select_option("greenland")
                    assert "Grönland" in page.locator("#weekMapLabel").inner_text()
                    wideLen=page.locator("#weekMap").evaluate("e=>e.toDataURL('image/png').length")
                    assert abs(wideLen-default)>1000
                    page.locator("#weekProjection").select_option("latlon")
                    assert "Breiten-Längen-Ansicht" in page.locator("#weekMapLabel").inner_text()
                    page.locator("#weekProjection").select_option("stereo")
                    assert "Stereografische Europaansicht" in page.locator("#weekMapLabel").inner_text()
                    page.locator("#weekMetric").select_option("absolute")
                    assert "°C" in page.locator("#weekCountryHeader").inner_text()
                    page.locator("#weekMetric").select_option("anomaly")
                    assert "K" in page.locator("#weekCountryHeader").inner_text()
                    if mobile:
                        dims=page.evaluate("({width:innerWidth,scroll:document.documentElement.scrollWidth})")
                        assert dims["scroll"]<=dims["width"]+3,dims
                        page.screenshot(path=str(OUT/"greenland_mobile.png"),full_page=True)
                    else:
                        page.screenshot(path=str(OUT/"greenland_desktop.png"),full_page=True)
                        with page.expect_download(timeout=30000) as d:
                            page.locator("#weekPng").click()
                        d.value.save_as(str(OUT/"greenland.png"))
                        assert (OUT/"greenland.png").stat().st_size>16000
                        with page.expect_download(timeout=30000) as d:
                            page.locator("#weekCsv").click()
                        d.value.save_as(str(OUT/"all_countries.csv"))
                        assert (OUT/"all_countries.csv").read_text(encoding="utf-8-sig").count("\n")>=30
                        page.pdf(path=str(OUT/"greenland.pdf"),print_background=True,landscape=True)
                        assert (OUT/"greenland.pdf").stat().st_size>12000
                    assert not errors,errors
                    ctx.close()
            finally:browser.close()
    finally:
        server.terminate()
        with contextlib.suppress(Exception):server.wait(timeout=5)
    print("PASS: real NOAA GFS f003..165 expanded 121x361 seven-day map, "
          "13 regions, original Natural Earth 50m outlines, mobile, polar/latlon, PNG/PDF/CSV",flush=True)


if __name__=="__main__":
    main()
