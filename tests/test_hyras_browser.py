"""Browser-level viewport snapshots of the HYRAS dashboard."""
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path("hyras-browser-snapshots")
OUT.mkdir(exist_ok=True)


def check(page, label):
    page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    page.evaluate("""() => {
      if (typeof switchTab !== 'function') throw new Error('Dashboard tabs unavailable');
      switchTab('hyras');
    }""")
    page.locator("#hyras").scroll_into_view_if_needed()
    page.wait_for_timeout(2200)
    page.screenshot(path=str(OUT / f"{label}.png"), full_page=False)
    result = page.evaluate("""() => {
      const section = document.querySelector('#hyras');
      const controls = section?.querySelector('.controls');
      return {
        sectionVisible: !!section && getComputedStyle(section).display !== 'none',
        viewport: document.documentElement.clientWidth,
        sectionWidth: section?.getBoundingClientRect().width || 0,
        controlsWidth: controls?.getBoundingClientRect().width || 0,
        overflowing: !!section && section.scrollWidth > section.clientWidth + 5
      };
    }""")
    print(label, result, flush=True)
    assert result["sectionVisible"], f"{label}: HYRAS tab not visible"
    assert result["sectionWidth"] > 250, f"{label}: HYRAS section width too small"
    assert not result["overflowing"], f"{label}: HYRAS spills horizontally"

    # Also exercise the dynamically mounted daily calendar panel directly.
    page.evaluate("""() => {
      if (!document.getElementById('hyrasDailyAnomalyPanel')) {
        if (typeof hyrasDailyAnomalyPanelHtml !== 'function')
          throw new Error('Daily panel template missing');
        document.querySelector('#hyras').insertAdjacentHTML(
          'beforeend', hyrasDailyAnomalyPanelHtml('tmean')
        );
      }
    }""")
    panel = page.locator("#hyrasDailyAnomalyPanel")
    panel.scroll_into_view_if_needed()
    panel.screenshot(path=str(OUT / f"{label}-daily-panel.png"))
    assert page.locator("#hyrasDailyAnomalyCalendar").count() == 1
    overflow = panel.evaluate("(el) => el.scrollWidth > el.clientWidth + 5")
    assert not overflow, f"{label}: Daily calendar panel spills horizontally"


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for width, height, name in [
                (1440, 900, "desktop-1440"),
                (390, 844, "mobile-390"),
                (360, 780, "mobile-360"),
            ]:
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                try:
                    check(page, name)
                finally:
                    page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
