"""Verify fully rendered SST, not just a selected tab or loading placeholder."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def audit(browser, width, output):
    context = browser.new_context(viewport={"width": width, "height": 900},
        is_mobile=width < 600, has_touch=width < 600, device_scale_factor=1,
        accept_downloads=True, ignore_https_errors=True)
    page = context.new_page()
    errors = []
    bad_requests = []
    downloads = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("response", lambda response: bad_requests.append((response.status, response.url)) if response.status >= 400 else None)
    page.on("dialog", lambda dialog: (errors.append("dialog: " + dialog.message), dialog.dismiss()))
    try:
        page.goto("https://marcelherber.github.io/climate-dashboard/index.html?tab=sst-europe",
                  wait_until="domcontentloaded", timeout=90000)
        page.wait_for_function("""() => document.querySelector('#sst-europe.active') &&
           document.querySelector('#sstMapImage')?.naturalWidth > 0 &&
           !document.querySelector('#sstPdfDownload').disabled""", timeout=120000)
        assert page.evaluate("!window.jspdf && !window.html2canvas"), "Unexpected eager export libraries"
        for theme in ("light", "dark"):
            if theme == "dark":
                page.locator("#dashboardThemeToggle").click()
                page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
            page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
            page.screenshot(path=str(output / f"{width}-sst-{theme}.png"), full_page=True)
        assert page.evaluate("""() => {
            const main=document.querySelector('main.dashboard-main'), footer=main.querySelector('footer.dashboard-footer');
            return main.contains(document.querySelector('#sst-europe')) &&
              [...main.querySelectorAll('.tab-content')].every(tab=>tab.compareDocumentPosition(footer)&Node.DOCUMENT_POSITION_FOLLOWING);
        }""")
        if width in (390, 1440):
            for ext, selector, magic in (("png", "#sstPngDownload", b"\x89PNG\r\n\x1a\n"),
                                          ("pdf", "#sstPdfDownload", b"%PDF")):
                with page.expect_download(timeout=90000) as event:
                    page.locator(selector).click()
                file = output / f"{width}-sst.{ext}"
                event.value.save_as(file)
                assert file.read_bytes().startswith(magic) and file.stat().st_size > 10000
                downloads.append({"name": file.name, "bytes": file.stat().st_size})
                if ext == "png":
                    assert not page.evaluate("!!window.jspdf")
            assert page.evaluate("!!window.jspdf?.jsPDF")
        assert not errors, errors
        return {"width": width, "passed": True, "downloads": downloads, "network_errors": bad_requests}
    except Exception as exc:
        try:
            page.screenshot(path=str(output / f"{width}-failed.png"), full_page=True, timeout=10000)
        except Exception:
            pass
        return {"width": width, "passed": False, "error": str(exc), "page_errors": errors, "network_errors": bad_requests}
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
            proxy={"server": "http://127.0.0.1:8089"}, args=["--ignore-certificate-errors", "--no-sandbox"])
        rows = [audit(browser, width, args.output) for width in (320, 360, 390, 1440)]
        browser.close()
    (args.output / "results.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))
    return 0 if all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
