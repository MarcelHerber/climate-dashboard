"""Exercise real renderer markup and native-cell interaction at both viewport sizes."""
import base64
import gzip
import json
import os
import struct
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HTML = '\n'.join((ROOT / name).read_text() for name in ('index.html', 'js/hyras.js', 'js/hyras-tmin.js'))
JS = (ROOT / 'hyras_temperature_interactive.js').read_text()


def renderer(parameter):
    cap = parameter[0].upper() + parameter[1:]
    start = HTML.index(f'function hyras{cap}RenderCurveChart(')
    end = HTML.index('\n  frame.querySelectorAll', start)
    return HTML[start:end] + '\n}'


def run():
    with sync_playwright() as p:
        args = {'headless': True, 'args': ['--no-sandbox']}
        if os.environ.get('CHROMIUM_PATH'):
            args['executable_path'] = os.environ['CHROMIUM_PATH']
        browser = p.chromium.launch(**args)
        for width, height, mobile in [(1280, 900, False), (390, 844, True)]:
            page = browser.new_page(viewport={'width': width, 'height': height}, has_touch=mobile)
            page.route('https://example.test/**', lambda route: route.fulfill(status=200, content_type='application/octet-stream', headers={'Access-Control-Allow-Origin':'*'}, body=gzip.compress(struct.pack('<4h',125,-250,-32768,0))))
            page.set_content('<div id="hyrasMapFrame"></div>')
            page.add_script_tag(content=JS)
            page.add_script_tag(content='''
                const HYRAS_DATA_BASE='https://example.test',hyrasIndex={};
                let ref='1991-2020'; function hyrasReferencePeriod(){return ref;}
                function hyrasReferenceDisplay(){return ref;}
                function hyrasDate(d){return d;}
                function hyrasDailyAnomalyPanelHtml(){return '<div class="daily-animation"></div>';}
                function hyrasTemperaturePreviewHref(url){return url;}
                const entry={anomaly:'modern.png',anomaly_by_reference:{'1961-1990':'old.png'},raster_grid:{width:2,height:2},raster_by_reference:{'1991-2020':'modern.gz','1961-1990':'old.gz'},raster_dates_by_reference:{'1991-2020':['2026-11-01','2026-11-14'],'1961-1990':['2026-11-01','2026-11-14']}};
                const maps={periods:{month_11:entry,'2026_11_live':entry}};
                const hyrasTmeanMapDownloads=maps,hyrasTmaxMapDownloads=maps,hyrasTminMapDownloads=maps;
                const hyrasTmeanRegionsIndex={data_through:'2026-11-14'},hyrasTmaxRegionsIndex=hyrasTmeanRegionsIndex,hyrasTminRegionsIndex=hyrasTmeanRegionsIndex;
                let hyrasTmeanRegionChart=null,hyrasTmaxRegionChart=null,hyrasTminRegionChart=null;
                function hyrasTmeanDownloadHref(p){return 'https://example.test/'+p;}
                const hyrasTmaxMapHref=hyrasTmeanDownloadHref,hyrasTminMapHref=hyrasTmeanDownloadHref;
                const period={key:'month_11',map_key:'2026_11_live',label:'November aktuell',start_date:'2026-11-01',end_date:'2026-11-14'};
            ''' + '\n'.join(renderer(v) for v in ('tmean','tmax','tmin')))
            for parameter in ('tmean','tmax','tmin'):
                cap = parameter[0].upper() + parameter[1:]
                for ref in ('1991-2020','1961-1990'):
                    page.evaluate(f"ref={json.dumps(ref)}; hyras{cap}RenderCurveChart('Deutschland',period,[])")
                    assert page.locator('.hyras-tmean-region-panel > :first-child').get_attribute('class') == 'hyras-tmean-anomaly-preview'
                    assert page.locator('.daily-animation').count() == 1
                    assert page.locator(f'#hyras{cap}RegionCanvas').count() == 1
                    assert page.locator('.hyras-tmean-anomaly-preview img').get_attribute('src').endswith('old.png' if ref=='1961-1990' else 'modern.png')
                    native = page.locator('.hyras-temperature-native-canvas')
                    native.wait_for()
                    native.evaluate("el=>{el.style.width='200px';el.style.height='200px';}")
                    box = native.bounding_box()
                    if mobile:
                        page.touchscreen.tap(box['x']+25,box['y']+25)
                    else:
                        page.mouse.move(box['x']+25,box['y']+25)
                    assert '+1,25 K' in page.locator('.hyras-temperature-raster-value').inner_text()
            page.close()
        browser.close()


if __name__ == '__main__':
    run()
    print('HYRAS temperature renderer and desktop/mobile interaction: OK')
