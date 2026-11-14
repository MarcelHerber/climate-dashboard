"""Genuine 28-field NOAA GFS 7-day browser QA: stereo/rectangular, touch, exports."""
from __future__ import annotations
import contextlib
import json
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"gfs_weekly_europe_qa"

def main():
    source=ROOT/"gfs_analysis_europe/weekly_f003.json"
    assert source.is_file(),"Must use real GFS 7-day index, never mocked data"
    content=json.loads(source.read_text(encoding="utf-8"))
    assert content["sample_count"]==28 and content["lead_hours"]==list(range(3,166,6))
    assert content["reference_metadata"]["source_months"]==360
    assert (ROOT/"cpc_europe/index.json").is_file()
    assert (ROOT/"cpc_europe/boundaries.png").is_file()
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
                with urlopen(url,timeout=3) as res:
                    assert res.status==200
                break
            except Exception:
                time.sleep(.2)
        else:
            raise RuntimeError("No local real-data website")
        with sync_playwright() as play:
            browser=play.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for mobile in (False,True):
                    context=browser.new_context(viewport={"width":390 if mobile else 1440,
                                                          "height":844 if mobile else 940},
                                                is_mobile=mobile,has_touch=mobile,
                                                accept_downloads=True)
                    page=context.new_page()
                    errors=[]
                    page.on("pageerror",lambda err:errors.append(str(err)))
                    page.goto(url,wait_until="domcontentloaded")
                    page.wait_for_function("() => document.getElementById('weekStatus').textContent.includes('Vorhersage')",
                                           timeout=45000)
                    page.wait_for_function("() => document.querySelectorAll('#weekCountries tr[data-country]').length >= 15",
                                           timeout=45000)
                    assert page.locator("#weekWarning").is_hidden(),page.locator("#weekWarning").inner_text()
                    assert "28 Originalfelder" in page.locator("#weekStatus").inner_text()
                    assert "14.11.2026" in page.locator("#weekRun").inner_text()
                    assert page.locator("#weekMetric").input_value()=="anomaly"
                    assert page.locator("#weekProjection").input_value()=="stereo"
                    assert page.locator("#weekMap").evaluate("e=>e.width")==1400
                    assert page.locator("#weekMap").evaluate("e=>e.height")==760
                    snapStereo=page.locator("#weekMap").evaluate("e=>e.toDataURL('image/png').length")
                    assert snapStereo>30000
                    page.locator("#weekCountries tr[data-country]").first.click()
                    assert " K" in page.locator("#weekSelected").inner_text()
                    page.locator("#weekProjection").select_option("latlon")
                    assert "Breiten-Längen-Ansicht" in page.locator("#weekMapLabel").inner_text()
                    page.locator("#weekProjection").select_option("stereo")
                    assert "Stereografische Europaansicht" in page.locator("#weekMapLabel").inner_text()
                    page.locator("#weekMetric").select_option("absolute")
                    assert "°C" in page.locator("#weekSelected").inner_text()
                    page.locator("#weekMetric").select_option("anomaly")
                    if mobile:
                        dims=page.evaluate("({viewport:innerWidth,full:document.documentElement.scrollWidth})")
                        assert dims["full"]<=dims["viewport"]+3,dims
                        page.screenshot(path=str(OUT/"mobile.png"),full_page=True)
                    else:
                        with page.expect_download(timeout=30000) as dl:
                            page.locator("#weekPng").click()
                        dl.value.save_as(str(OUT/"week_map.png"))
                        assert (OUT/"week_map.png").stat().st_size>12000
                        with page.expect_download(timeout=30000) as dl:
                            page.locator("#weekCsv").click()
                        dl.value.save_as(str(OUT/"countries.csv"))
                        rows=(OUT/"countries.csv").read_text(encoding="utf-8-sig")
                        assert "CFSR/CFSv2 1991-2020 f003" in rows
                        assert rows.count("\n")>=15
                        page.pdf(path=str(OUT/"week_map.pdf"),print_background=True,landscape=True)
                        assert (OUT/"week_map.pdf").stat().st_size>12000
                        page.screenshot(path=str(OUT/"desktop.png"),full_page=True)
                    assert not errors,errors
                    context.close()
            finally:
                browser.close()
    finally:
        server.terminate()
        with contextlib.suppress(Exception):server.wait(timeout=5)
    print("SUCCESS: real GFS 28-field weekly anomaly, polar projection, rectangular projection, "
          "mobile touch, country means, PNG, PDF, CSV",flush=True)

if __name__=="__main__":
    main()
