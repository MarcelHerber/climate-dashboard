#!/usr/bin/env python3
"""Real dashboard browser QA on an isolated branch; never deploys Pages."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
import threading
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from inject_mobile_navigation import inject

WIDTHS = (1440, 320, 360, 390)
OUT = ROOT / 'overview_visual_reports'
LIVE = 'https://marcelherber.github.io/climate-dashboard/'


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def build_preview_html():
    # The Pages builder injects these assets after copying index.html. Preserve
    # the proposed source HTML and all original scripts, including Chart.js.
    html = inject((ROOT / 'index.html').read_text(encoding='utf-8'))
    html = html.replace('</head>', '<link rel="stylesheet" href="sst_nino_years.css?v=20261118-1">\n'
                        '<script defer src="scientific_vector_actions.js?v=20261113-science-vector-v1"></script>\n</head>', 1)
    return html.replace('</body>', '<script defer src="sst_nino_years.js?v=20261119-1"></script>\n</body>', 1)


def checks(page, width, theme):
    return page.evaluate('''({width,theme}) => {
      const box = s => document.querySelector(s);
      const count = s => getComputedStyle(box(s)).gridTemplateColumns.split(' ').length;
      const root=document.documentElement;
      const footer=box('.dashboard-footer'), main=box('main.dashboard-main');
      const fontSizes = ['.overview-link-copy','.overview-mini-label','.overview-mini-detail',
        '.overview-map-legend','.overview-stat-name','.overview-source-table'].map(s=>[s,getComputedStyle(box(s)).fontSize]);
      return {width,theme,actualTheme:root.dataset.theme,viewport:innerWidth,
        scrollWidth:root.scrollWidth,overflow:Math.max(0,root.scrollWidth-width),
        miniColumns:count('.overview-mini-grid'),bottomColumns:count('.overview-bottom-grid'),
        fontSizes,primaryCount:box('.overview-quicklink-grid').querySelectorAll('button').length,
        moreCount:box('.overview-more-list').querySelectorAll('button').length,
        summaryColor:getComputedStyle(box('.overview-more-links summary')).color,
        cardBackground:getComputedStyle(box('.overview-quicklinks')).backgroundColor,
        footerLast:main.lastElementChild===footer,
        outsideTabs:[...document.querySelectorAll('.tab-content')].filter(el=>!main.contains(el)).map(el=>el.id),
        mapShapes:box('#overviewMap').querySelectorAll('path.leaflet-interactive').length,
        kpi:box('#overviewTempAnomaly').innerText,
        pixelRatio:Chart.defaults.devicePixelRatio};
    }''', {'width': width, 'theme': theme})


def validate(result):
    width = result['width']
    problems = []
    def require(condition, description):
        if not condition:
            problems.append(description)
    require(result['actualTheme'] == result['theme'], 'Theme toggle did not apply')
    require(result['viewport'] == width, 'Wrong browser viewport')
    require(result['overflow'] <= 3, 'Horizontal overflow: '+str(result['overflow'])+' px')
    require(result['miniColumns'] == (3 if width > 800 else 1 if width <= 360 else 2), 'Wrong mini-card grid')
    require(result['bottomColumns'] == (3 if width > 1180 else 2 if width > 800 else 1), 'Wrong bottom grid')
    require(all(x[1] == '12px' for x in result['fontSizes']), 'Overview font-size regression')
    require(result['primaryCount'] == 6 and result['moreCount'] == 4, 'Wrong shortcut counts')
    require(result['footerLast'] and not result['outsideTabs'], 'Main/footers/tabs are out of order')
    require(result['mapShapes'] >= 16 and result['kpi'] != '–', 'Map or real DWD KPI did not render')
    require(result['pixelRatio'] == 1, 'Normal screen rendered at wrong DPR')
    return problems


def audit_map_colors(page):
    # The live map is rendered normally first. Inject controlled inputs only
    # inside this temporary browser, so a genuine exact-zero boundary is tested.
    page.evaluate('''() => {
      const original=overviewMetric;
      overviewMetric=(area,param,date)=>param==='temp' ? ({Bayern:-2,Hessen:0,Sachsen:2}[area] ?? 0) : original(area,param,date);
      overviewMapParam='temp'; renderOverviewMap();
    }''')
    page.wait_for_function('''() => {
      if (!overviewMapLayer) return false;
      const colors={}; overviewMapLayer.eachLayer(l=>colors[l.feature.properties.name]=l.options.fillColor);
      return colors.Bayern === '#2b5c9a' && colors.Sachsen === '#b9212f';
    }''', timeout=15000)
    colors = page.evaluate('''() => {
      const overview={}; overviewMapLayer.eachLayer(l=>{if(['Bayern','Hessen','Sachsen'].includes(l.feature.properties.name)) {
        overview[l.feature.properties.name]={fill:l.options.fillColor,svgFill:l.getElement()?.getAttribute('fill')};
      }});
      return {overview,regional:[-2,0,2].map(regionalMapScale([-2,0,2],'temp','anomaly').color),
        difference:[-2,0,2].map(regionalMapDifferenceScale([-2,0,2],'temp').color)};
    }''')
    page.evaluate("document.getElementById('overviewMapSubtitle').textContent='TESTDATEN: Bayern −2 °C · Hessen 0 °C · Sachsen +2 °C'")
    page.locator('.overview-map-card').screenshot(path=str(OUT/'map_controlled_minus_zero_plus.png'), animations='disabled')
    expected = {'Bayern':'#2b5c9a','Hessen':'#f5f5f3','Sachsen':'#b9212f'}
    for area, color in expected.items():
        assert colors['overview'][area] == {'fill':color,'svgFill':color}, colors
    assert colors['regional'] == colors['difference'] == ['#313695','#f7f7f7','#a50026'], colors
    return colors


def main():
    OUT.mkdir(exist_ok=True)
    html = build_preview_html()
    server = ThreadingHTTPServer(('127.0.0.1',0), partial(QuietHandler,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:'+str(server.server_port)+'/'
    observations, failures, map_colors = [], [], None
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox'],executable_path=shutil.which('google-chrome'))
            for width in WIDTHS:
                context=browser.new_context(viewport={'width':width,'height':900},device_scale_factor=1,
                    is_mobile=width<500,has_touch=width<500,color_scheme='light',reduced_motion='reduce')
                page=context.new_page()
                errors, console, network = [], [], []
                page.on('pageerror',lambda exc: errors.append(str(exc)))
                page.on('console',lambda msg: console.append({'type':msg.type,'message':msg.text,'url':msg.location.get('url','')}) if msg.type in ('error','warning') else None)
                page.on('response',lambda response: network.append({'status':response.status,'url':response.url}) if response.status>=400 else None)
                page.on('requestfailed',lambda req: network.append({'error':req.failure,'url':req.url}))
                def route_local(route):
                    path=urlparse(route.request.url).path.lstrip('/')
                    if path=='index.html':
                        return route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
                    # Some optional data are copied from dataset branches only
                    # during the Pages build. Use real published data if absent
                    # locally; never substitute scripts or weather values.
                    if path.endswith('.json') and not (ROOT/path).is_file():
                        try:
                            resp=route.fetch(url=LIVE+path,timeout=15000)
                            return route.fulfill(response=resp)
                        except Exception:
                            pass
                    route.continue_()
                page.route(base+'**',route_local)
                try:
                    page.goto(base+'index.html?tab=overview',wait_until='domcontentloaded',timeout=90000)
                    page.wait_for_function("typeof Chart!=='undefined' && document.getElementById('overviewTempAnomaly').textContent!=='–'",timeout=30000)
                    try:
                        page.wait_for_function("document.querySelectorAll('#overviewMap path.leaflet-interactive').length>=16",timeout=15000)
                    except Exception:
                        diagnostic=page.evaluate(r'''() => ({leaflet:typeof L,chart:typeof Chart,ready:document.readyState,
                          active:document.querySelector('#overview').classList.contains('active'),
                          monthlyRows:monthlyData.length,latest:overviewLatestGermanyRow()?.date,
                          legend:document.querySelector('#overviewMapLegend').innerText,
                          mapExists:!!overviewMap,layerExists:!!overviewMapLayer,
                          mapTitle:document.querySelector('#overviewMapTitle').textContent,
                          mapText:document.querySelector('#overviewMap').innerText,
                          resources:performance.getEntriesByType('resource').filter(r=>/leaflet|geo\.json/.test(r.name)).map(r=>({name:r.name,status:r.responseStatus,duration:r.duration}))})''')
                        observations.append({'width':width,'initialMapDiagnostic':diagnostic})
                        print(f'{width}: initial map diagnostic {diagnostic}',flush=True)
                        failures.append(f'{width}px: overview map did not render automatically')
                        page.locator('[data-overview-param="temp"]').click()
                        try:
                            page.wait_for_function("document.querySelectorAll('#overviewMap path.leaflet-interactive').length>=16",timeout=15000)
                        except Exception:
                            pass
                        observations.append({'width':width,'mapShapesAfterClick':page.locator('#overviewMap path.leaflet-interactive').count()})
                    for theme in ('light','dark'):
                        if page.locator('html').get_attribute('data-theme') != theme:
                            page.locator('#dashboardThemeToggle').click(timeout=5000)
                        page.evaluate('window.scrollTo(0,0)')
                        result=checks(page,width,theme)
                        result['problems']=validate(result)
                        summary=page.locator('.overview-more-links summary')
                        details=page.locator('.overview-more-links')
                        assert details.get_attribute('open') is None, 'Disclosure starts open'
                        page.screenshot(path=str(OUT/f'overview_{width}_{theme}_closed.png'),full_page=True,animations='disabled')
                        summary.click()
                        assert details.locator('.overview-more-list button').count()==4
                        assert all(x.is_visible() for x in details.locator('.overview-more-list button').all())
                        assert page.locator('.overview-more-list').evaluate("el=>getComputedStyle(el).gridTemplateColumns.split(' ').length")== (1 if width<=520 else 2)
                        result['openOverflow']=page.evaluate('document.documentElement.scrollWidth-innerWidth')
                        if result['openOverflow']>3: result['problems'].append('Disclosure causes horizontal overflow')
                        page.locator('.overview-quicklinks').screenshot(path=str(OUT/f'shortcuts_{width}_{theme}_open.png'),animations='disabled')
                        summary.click()
                        assert not details.locator('.overview-more-list button').first.is_visible()
                        result['disclosure']='opened and closed by click'
                        if result['problems']: failures.append(f'{width} {theme}: {result["problems"]}')
                        observations.append(result)
                    # Exercise the actual tab-switch code and await the real SST archive map.
                    page.evaluate("switchTab('sst-europe')")
                    page.wait_for_function("document.querySelector('#sst-europe').classList.contains('active') && document.querySelector('#sstMapImage').naturalWidth > 0 && document.querySelector('#sstRegion').options.length > 0 && !document.querySelector('#sstPngDownload').disabled", timeout=40000)
                    for theme in ('dark','light'):
                        if page.locator('html').get_attribute('data-theme')!=theme:
                            page.locator('#dashboardThemeToggle').click(timeout=5000)
                        page.evaluate('window.scrollTo(0,0)')
                        sst=page.evaluate('''() => {const main=document.querySelector('main.dashboard-main'), tab=document.querySelector('#sst-europe'), footer=document.querySelector('.dashboard-footer');
                        return {theme:document.documentElement.dataset.theme,footerAfter:main.lastElementChild===footer&&!!(tab.compareDocumentPosition(footer)&Node.DOCUMENT_POSITION_FOLLOWING),contains:main.contains(tab),imgWidth:document.querySelector('#sstMapImage').naturalWidth,region:document.querySelector('#sstRegion').selectedOptions[0]?.textContent,source:document.querySelector('#sstDataThrough').textContent,overflow:document.documentElement.scrollWidth-innerWidth};}''')
                        observations.append({'width':width,'sst':sst})
                        if not (sst['footerAfter'] and sst['contains'] and sst['imgWidth']>0 and sst['overflow']<=3): failures.append(f'SST {width} {theme}: {sst}')
                        page.screenshot(path=str(OUT/f'sst_{width}_{theme}.png'),full_page=True,animations='disabled')
                    if width==1440 and page.evaluate('typeof L!=="undefined"'):
                        page.evaluate("switchTab('overview')")
                        map_colors=audit_map_colors(page)
                except Exception as exc:
                    failures.append(f'{width}px: {exc}')
                    try: page.screenshot(path=str(OUT/f'failure_{width}.png'),full_page=True,animations='disabled')
                    except Exception: pass
                # The explicit runtime errors are decisive. HTTP errors are
                # kept separately (optional data fallback, external failures).
                if errors: failures.append(f'{width}px uncaught JS: {errors}')
                non_network=[m for m in console if m['type']=='error' and not m['message'].startswith('Failed to load resource')]
                if non_network: failures.append(f'{width}px console errors: {non_network}')
                observations.append({'width':width,'pageErrors':errors,'console':console,'network':network})
                context.close()
            browser.close()
    finally:
        server.shutdown()
        report={'source':'isolated branch index.html + real DWD/SST data; Pages mobile assets injected; exact-zero test only uses controlled inputs',
                'observations':observations,'mapColors':map_colors,'failures':failures}
        (OUT/'audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(report,indent=2,ensure_ascii=False),flush=True)
    if failures or map_colors is None:
        raise SystemExit('Browser audit failed; do not publish main.')
    print('PASS: all requested viewports, both themes, disclosure, colors, SST and console.')


if __name__=='__main__':
    main()
