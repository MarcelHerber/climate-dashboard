"""Chromium smoke test with both validated original catalogues, no weather fixtures."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
server=ThreadingHTTPServer(("127.0.0.1",0),partial(SimpleHTTPRequestHandler,directory=str(ROOT)))
Thread(target=server.serve_forever,daemon=True).start()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel="chrome",headless=True)
        for width,height in [(1440,900),(390,844)]:
            page=browser.new_page(viewport={"width":width,"height":height},accept_downloads=True)
            errors=[]
            page.on("pageerror",lambda error:errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/grosswetterlagen.html")
            expect(page.locator("#results")).to_be_visible(timeout=30000)
            expect(page.locator("#from")).to_have_value("1940-01-01")
            expect(page.locator("#to")).to_have_value("2026-06-30" if not (ROOT/"data/grosswetterlagen/rea.csv").exists() else (ROOT/"data/grosswetterlagen/rea.csv").read_text().splitlines()[-1].split(";")[0])
            assert page.locator("#freq tbody tr").count()==30
            page.locator("#type").select_option("Alle")
            page.locator("#year").select_option("2000")
            assert page.locator("#calendar .day").count()==366
            page.locator("#source").select_option("hb")
            expect(page.locator("#from")).to_have_value("1881-01-01",timeout=30000)
            expect(page.locator("#to")).to_have_value("2009-12-31")
            assert page.locator("#freq tbody tr").count()==30
            page.locator("#type").select_option("Alle")
            page.locator("#year").select_option("1881")
            assert page.locator("#calendar .day").count()==365
            expect(page.locator("#calendar .day").first).to_have_text("HM")
            page.locator("#season").select_option("1")
            assert page.locator("#calendar .day").count()==31
            with page.expect_download() as event:
                page.locator("#csv").click()
            assert event.value.suggested_filename.endswith(".csv")
            with page.expect_download() as event:
                page.locator("#png").click()
            assert event.value.suggested_filename.endswith(".png")
            page.locator("#theme").click()
            assert page.locator("html").get_attribute("data-theme") in ("dark","light")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"),f"Page overflows viewport {width}"
            assert not errors,errors
            if width==1440:
                page.locator("#season").select_option("all")
                page.locator("#from").fill("2009-01-01")
                page.locator("#from").dispatch_event("change")
                page.locator("#climate").click()
                expect(page.locator("#climtable tbody tr").first).to_be_visible(timeout=60000)
                assert page.locator("#climtable tbody tr").count()==30
                count=sum(int(s.replace(".","")) for s in page.locator("#climtable tbody tr td:nth-child(2)").all_text_contents())
                assert count==365, f"Real 2009 HYRAS regional join: {count} days"
            page.close()
            print(f"Verified original catalogues, charts, filters and downloads in {width}px Chromium")
        browser.close()
finally:
    server.shutdown()
