"""Test the edited hub on the frozen performance-preview data and assets."""
import argparse
import json
from pathlib import Path

from test_europe_hub_overview import SOURCE, START, END, TARGETS, GRID_RULE


def prepare(snapshot):
    path = snapshot / 'index.html'
    frozen = path.read_text(encoding='utf-8')
    edited = SOURCE.read_text(encoding='utf-8')
    hub = edited.split(START, 1)[1].split(END, 1)[0]
    before, tail = frozen.split(START, 1)
    _, after = tail.split(END, 1)
    anchor = '.europe-hub-note{font-size:12px;color:#6b7787;line-height:1.55}'
    assert before.count(anchor) == 1 and GRID_RULE in edited
    before = before.replace(anchor, anchor + '\n' + GRID_RULE)
    path.write_text(before + START + hub + END + after, encoding='utf-8')


def audit(browser, width, output):
    context = browser.new_context(viewport={'width': width, 'height': 900},
        is_mobile=width < 600, has_touch=width < 600, device_scale_factor=1,
        ignore_https_errors=True)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto('https://marcelherber.github.io/climate-dashboard/index.html?tab=europeHub',
                  wait_until='domcontentloaded', timeout=90000)
        page.wait_for_function("document.querySelector('#europeHub.active') && typeof window.switchTab === 'function'")
        cards = page.locator('#europeHub .europe-hub-card')
        assert cards.count() == 3
        for theme in ('light', 'dark'):
            if theme == 'dark':
                page.locator('#dashboardThemeToggle').click()
                page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
            page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
            page.screenshot(path=str(output / f'{width}-europe-{theme}.png'), full_page=True)
            layout = page.evaluate('''() => {
                const hub = document.querySelector('#europeHub');
                const grid = hub.querySelector('.europe-hub-grid');
                const cards = [...grid.querySelectorAll('.europe-hub-card')];
                const bounds = grid.getBoundingClientRect();
                return {width: bounds.width, third: cards[2].getBoundingClientRect().width,
                    overflow: [...hub.querySelectorAll('.europe-hub-card,.europe-hub-statcard,.europe-hub-hero,.europe-hub-statrow,.europe-hub-actions')].filter(e => e.scrollWidth > e.clientWidth+2 || e.getBoundingClientRect().right > innerWidth+2).map(e => e.className),
                    gridColumns: getComputedStyle(grid).gridTemplateColumns};
            }''')
            assert not layout['overflow'], (width, theme, layout)
            assert abs(layout['third'] - layout['width']) < 2, layout
        if width in (390, 1440):
            for target in TARGETS:
                page.locator(f'#europeHub button[onclick="switchTab(\'{target}\')"]').click()
                page.locator(f'#{target}.active').wait_for(state='visible')
                page.evaluate("switchTab('europeHub')")
                page.locator('#europeHub.active').wait_for(state='visible')
        assert not errors, errors
        return {'width': width, 'passed': True, 'page_errors': errors}
    except Exception as exc:
        page.screenshot(path=str(output / f'{width}-failed.png'), full_page=True, timeout=10000)
        return {'width': width, 'passed': False, 'error': str(exc), 'page_errors': errors}
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare)
        return 0
    from playwright.sync_api import sync_playwright
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True,
            proxy={'server': 'http://127.0.0.1:8089'}, args=['--ignore-certificate-errors', '--no-sandbox'])
        rows = [audit(browser, width, args.output) for width in (320, 360, 390, 1440)]
        browser.close()
    (args.output / 'results.json').write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))
    return 0 if all(row['passed'] for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
