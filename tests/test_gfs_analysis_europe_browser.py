"""Desktop/mobile smoke test using actual NOAA GFS f000 and CPC country grid."""
from __future__ import annotations
import contextlib
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"gfs_analysis_europe_qa"

def main():
    assert (ROOT/"gfs_analysis_europe/index.json").exists(), "Real GFS data required"
    assert (ROOT/"cpc_europe/index.json").exists(), "Real country grid required"
    OUT.mkdir(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        port=sock.getsockname()[1]
    server=subprocess.Popen(["python","-m","http.server",str(port),"--bind","127.0.0.1"],
                            cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        url=f"http://127.0.0.1:{port}/gfs_analysis_europe.html"
        for _ in range(40):
            try:
                with urlopen(url,timeout=3) as r:
                    assert r.status==200
                break
            except Exception:
                time.sleep(.25)
        else:
            raise RuntimeError("Local test server not available")
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for mobile in (False,True):
                    ctx=browser.new_context(viewport={"width":390 if mobile else 1440,
                                                      "height":844 if mobile else 900},
                                            is_mobile=mobile,has_touch=mobile,
                                            accept_downloads=True)
                    page=ctx.new_page()
                    errors=[]
                    page.on("pageerror",lambda e:errors.append(str(e)))
                    page.goto(url,wait_until="domcontentloaded")
                    page.wait_for_function("() => document.getElementById('gfsDatasetDate').textContent.includes('GFS-Analyse bis')",
                                           timeout=30000)
                    page.wait_for_function("() => document.querySelectorAll('#gfsCountries tr[data-country]').length>=15",
                                           timeout=30000)
                    assert "Keine" not in page.locator("#gfsStatus").inner_text()
                    assert page.locator("#gfsMap").evaluate("e=>e.width")==1400
                    assert page.locator("#gfsBorders").evaluate("e=>e.complete&&e.naturalWidth>1000")
                    assert page.locator("#gfsMetric").input_value()=="absolute"
                    assert page.locator('#gfsMetric option[value="anomaly"]').is_disabled()
                    assert "CFSR/CFSv2-Referenz 1991–2020 noch nicht" in page.locator("#gfsReferenceStatus").inner_text()
                    page.locator("#gfsCountries tr[data-country]").first.click()
                    assert "°C" in page.locator("#gfsSelected").inner_text()
                    if mobile:
                        measure=page.evaluate("({w:document.documentElement.scrollWidth,v:innerWidth})")
                        assert measure["w"]<=measure["v"]+3,measure
                    else:
                        with page.expect_download(timeout=20000) as waiter:
                            page.locator("#gfsPng").click()
                        waiter.value.save_as(str(OUT/"gfs_map.png"))
                        assert (OUT/"gfs_map.png").stat().st_size>10000
                        with page.expect_download(timeout=20000) as waiter:
                            page.locator("#gfsCsv").click()
                        assert waiter.value.suggested_filename.endswith(".csv")
                        page.pdf(path=str(OUT/"gfs_map.pdf"),print_background=True,landscape=True)
                        assert (OUT/"gfs_map.pdf").stat().st_size>10000
                    page.screenshot(path=str(OUT/("mobile.png" if mobile else "desktop.png")),full_page=True)
                    assert not errors,errors
                    ctx.close()
            finally:
                browser.close()
    finally:
        server.terminate()
        with contextlib.suppress(Exception):server.wait(timeout=5)
    print("GFS real-data browser QA passed: desktop, touch/mobile, PNG, CSV and PDF")

if __name__=="__main__":
    main()
