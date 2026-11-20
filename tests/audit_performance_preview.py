"""Real Chrome checks against the isolated snapshot proxy (no publication)."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://marcelherber.github.io/climate-dashboard/index.html?tab=overview"


def verify(browser, width, output, exports):
    context = browser.new_context(
        viewport={"width": width, "height": 844 if width < 600 else 900},
        device_scale_factor=1, is_mobile=width < 600, has_touch=width < 600,
        accept_downloads=True, ignore_https_errors=True, color_scheme="light",
    )
    page = context.new_page()
    errors, warnings, requests, downloads = [], [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda msg: warnings.append(msg.text) if msg.type == "error" else None)
    page.on("dialog", lambda dialog: (errors.append("dialog: " + dialog.message), dialog.dismiss()))
    page.on("request", lambda request: requests.append(request.url))
    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_function("""() => window.Chart && window.L && window.DashboardExportHQ
            && document.querySelector('#overview.active') && document.querySelector('#overviewMap svg path')""", timeout=90000)
        assert not page.evaluate("!!window.jspdf || !!window.html2canvas"), "Export libraries loaded before export"
        assert not any("npm/jspdf@" in url or "npm/html2canvas@" in url for url in requests)
        assert page.locator(".overview-quicklink-grid .overview-quicklink").count() == 6
        detail = page.locator(".overview-more-links")
        assert not detail.evaluate("(node) => node.open")
        page.screenshot(path=str(output / f"{width}-light-closed.png"), full_page=True)
        detail.locator("summary").click()
        assert detail.evaluate("(node) => node.open")
        assert detail.locator(".overview-quicklink:visible").count() == 4
        page.screenshot(path=str(output / f"{width}-light-open.png"), full_page=True)
        detail.locator("summary").click()
        assert not detail.evaluate("(node) => node.open")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
        colors = page.evaluate("""() => [
          overviewMapScale([-2,0,2], 'temp'),
          regionalMapScale([-2,0,2], 'temp', 'anomaly'),
          regionalMapDifferenceScale([-2,0,2], 'temp')
        ].map(s => [-2,0,2].map(s.color))""")
        assert colors == [["#2b5c9a", "#f5f5f3", "#b9212f"],
                          ["#313695", "#f7f7f7", "#a50026"],
                          ["#313695", "#f7f7f7", "#a50026"]], colors
        page.locator("#dashboardThemeToggle").click()
        page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
        page.screenshot(path=str(output / f"{width}-dark.png"), full_page=True)
        page.evaluate("switchTab('sst-europe')")
        page.wait_for_function("document.querySelector('#sst-europe.active')", timeout=30000)
        assert page.evaluate("""() => {
          const main=document.querySelector('main.dashboard-main'), footer=main.querySelector('footer.dashboard-footer');
          return main.contains(document.querySelector('#sst-europe')) &&
            [...main.querySelectorAll('.tab-content')].every(tab=>tab.compareDocumentPosition(footer)&Node.DOCUMENT_POSITION_FOLLOWING);
        }""")
        page.screenshot(path=str(output / f"{width}-sst.png"), full_page=True)
        if exports:
            page.evaluate("switchTab('monthly')")
            page.locator("#monthlyFrequencyButton").click(timeout=30000)
            page.wait_for_function("""() => Chart.getChart('monthlyFrequencyChart')?.data?.datasets?.some(
                ds=>ds.data?.some(v=>Number.isFinite(v) || Number.isFinite(v?.y)))""", timeout=90000)
            before = page.evaluate("JSON.stringify(Chart.getChart('monthlyFrequencyChart').data.datasets.map(d=>d.data))")
            for ext, selector, magic in (
                ("png", "#monthlyFrequencyPngButton", b"\x89PNG\r\n\x1a\n"),
                ("pdf", "#monthlyFrequencyPdfButton", b"%PDF"),
            ):
                with page.expect_download(timeout=90000) as event:
                    page.locator(selector).click(timeout=30000)
                file = output / f"{width}-monthly-frequency.{ext}"
                event.value.save_as(str(file))
                assert file.read_bytes().startswith(magic) and file.stat().st_size > 10000
                downloads.append({"file": file.name, "bytes": file.stat().st_size})
                if ext == "png":
                    assert page.evaluate("!!window.html2canvas && !window.jspdf")
            assert page.evaluate("JSON.stringify(Chart.getChart('monthlyFrequencyChart').data.datasets.map(d=>d.data))") == before
            assert page.evaluate("!!window.jspdf?.jsPDF")
        assert not errors, errors
        return {"width": width, "passed": True, "colors": colors, "downloads": downloads, "console_errors": warnings}
    except Exception as exc:
        try:
            page.screenshot(path=str(output / f"{width}-FAILED.png"), full_page=True, timeout=10000)
        except Exception:
            pass
        return {"width": width, "passed": False, "error": str(exc), "page_errors": errors, "console_errors": warnings}
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("mobile", "desktop"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True,
            proxy={"server": "http://127.0.0.1:8089"}, args=["--ignore-certificate-errors", "--no-sandbox"])
        widths = (320, 360, 390) if args.device == "mobile" else (1440,)
        rows = [verify(browser, width, args.output, width == widths[-1]) for width in widths]
        browser.close()
    (args.output / "browser-results.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))
    return 0 if all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
