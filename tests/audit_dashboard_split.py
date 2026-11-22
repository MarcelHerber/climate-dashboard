"""Exercise the split dashboard using real data and the archived Pages assets."""
import argparse
import json
import re
import shutil
import time
from pathlib import Path

from audit_europe_hub import prepare as prepare_europe_hub
from test_europe_hub_overview import SOURCE

OLD_MAIN = re.compile(rb'<script>(\s*Chart\.register\(ChartDataLabels\);.*?)</script>', re.S)
SPLIT_MAIN = re.compile(rb'<script src="js/(?:loader|core)\.js[^"\n]*"></script>.*?(?=<script src="monthly_frequency\.js)', re.S)
URL = 'https://marcelherber.github.io/climate-dashboard/index.html'


def prepare(site):
    prepare_europe_hub(site)
    index = site / 'index.html'
    html = index.read_bytes()
    old = list(OLD_MAIN.finditer(html))
    split = list(SPLIT_MAIN.finditer(SOURCE.read_bytes()))
    assert len(old) == len(split) == 1
    html = html[:old[0].start()] + split[0][0] + html[old[0].end():]
    loader=(SOURCE.parent / 'js/loader.js').read_text()
    dynamic=re.findall(r'"([^"]+\.js)"\s*,\s*"[^"]+"\]',loader)
    for filename in dynamic:
        html=re.sub(rb'<script\b[^>]*src="'+re.escape(filename.encode())+rb'(?:\?[^"]*)?"[^>]*>\s*</script>',b'',html)
        if '/' not in filename:
            shutil.copyfile(SOURCE.parent / filename, site / filename)
    html=re.sub(rb'<script src="(https://cdn\.jsdelivr\.net/npm/(?:jspdf|html2canvas)@[^"]+)"',rb'<script defer src="\1"',html)
    index.write_bytes(html)
    shutil.copytree(SOURCE.parent / 'js', site / 'js')
    shutil.copyfile(SOURCE.parent / 'era5_stratosphere.js', site / 'era5_stratosphere.js')
    # The production builder also makes the staged snow archives same-origin.
    path = site / 'js/uebersicht.js'
    source = path.read_text()
    for name in ('station_snow_height_index.json', 'station_snow_height_current_index.json',
                 'station_snow_height_profiles/', 'station_snow_height_years/', 'station_snow_height_current/'):
        anchor = f'  "{name}",\n'
        assert source.count(anchor) == 1
        source = source.replace(anchor, '')
    path.write_text(source)


def chart_data(page, chart):
    return page.evaluate(f"JSON.stringify(Chart.getChart('{chart}')?.data?.datasets?.map(x=>x.data) ?? null)")


def download(page, locator, path, signature):
    with page.expect_download(timeout=90000) as event:
        locator.click()
    event.value.save_as(path)
    assert path.read_bytes().startswith(signature) and path.stat().st_size > 1000, path


def click_lazy_tab(page, tab, width):
    if width < 600:
        name = {'stationSnow': 'Schneehöhe', 'current': 'Aktuelle DWD-Stationen',
                'era5Europe': 'ERA5-Land Europa', 'europeStations': 'Europa-Stationen',
                'hyras':'HYRAS-Flächenkarten','t850-ensembles':'Ensembleprognosen','sst-europe':'Meere / SST',
                'state-monthly-ensemble':'Monatsausblick','gebietsmittelArchive':'Gebietsmittel Archiv','era5Atmosphere':'ERA5 Atmosphäre'}[tab]
        page.locator('#cdMobileMenuButton').click()
        page.locator('.cdm-search').fill(name)
        page.locator('.cdm-results').get_by_role('button', name=re.compile(r'^' + re.escape(name) + r'(?:\s|$)')).click()
    else:
        if tab=='gebietsmittelArchive':
            page.locator('.nav-dropdown[data-nav-group="germany"] .nav-dropdown-toggle').click()
            page.locator('.nav-dropdown[data-nav-group="germany"] .tab-button[onclick="switchTab(\'monthly\')"]').click()
            page.locator('.monthly-section-link[onclick="switchTab(\'gebietsmittelArchive\')"]').click()
            return
        group = 'stations' if tab in ('stationSnow', 'current') else 'germany' if tab=='hyras' else 'europe'
        page.locator(f'.nav-dropdown[data-nav-group="{group}"] .nav-dropdown-toggle').click()
        page.locator(f'.nav-dropdown[data-nav-group="{group}"] .tab-button[onclick="switchTab(\'{tab}\')"]').click()


def audit(browser, root, stage, width, output, export=False):
    (root / 'stage.txt').write_text(stage)
    context = browser.new_context(viewport={'width': width, 'height': 900},
        is_mobile=width < 600, has_touch=width < 600, device_scale_factor=1,
        ignore_https_errors=True, color_scheme='light', accept_downloads=True)
    page = context.new_page()
    errors, console_errors, network, loads = [], [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
    page.on('response', lambda rsp: network.append([rsp.status, rsp.url]) if rsp.status >= 400 else None)
    page.on('request', lambda req: loads.append(req.url))
    page.on('dialog', lambda d: (errors.append('dialog: ' + d.message), d.dismiss()))
    key = f'{stage}-{width}'
    try:
        page.goto(URL + '?tab=overview', wait_until='domcontentloaded', timeout=90000)
        if stage != 'control':
            assert page.evaluate("typeof DashboardModules !== 'undefined' && ['current','stationSnow','era5Europe','hyras','sst-europe','t850-ensembles','state-monthly-ensemble','gebietsmittelArchive','era5Atmosphere'].every(tab=>!DashboardModules.tabReady(tab))")
        page.wait_for_function("""() => document.querySelector('#overview.active') &&
            document.querySelector('#overviewMap svg path') && document.querySelector('#overviewDotMonthly.ok') &&
            document.querySelector('#overviewTempAnomaly').textContent.includes('°C') &&
            document.querySelector('#statusBadges .status-badge')""", timeout=90000)
        assert page.evaluate('monthlyData.length > 1000')
        overview = page.evaluate("""() => Object.fromEntries(['overviewCurrentTitle','overviewTempAnomaly',
            'overviewRainPercent','overviewSunPercent','overviewStatusMonthly','dataStatus'].map(id=>[id,document.getElementById(id).textContent]))""")
        page.screenshot(path=str(output / f'{key}-overview.png'), full_page=True)
        page.locator('#overview .overview-quicklink[onclick="switchTab(\'monthly\')"]').click()
        page.wait_for_function("document.querySelector('#monthly.active') && Chart.getChart('monthlyChart')?.data?.datasets?.length", timeout=90000)
        page.locator('#paramSelect').select_option('rain')
        page.locator('#monthSelect').select_option('10')
        page.wait_for_function("Chart.getChart('monthlyChart')?.data?.datasets?.some(d=>d.data?.some(Number.isFinite))")
        before = chart_data(page, 'monthlyChart')
        page.locator('#paramSelect').select_option('temp')
        assert chart_data(page, 'monthlyChart') != before, 'Parameter change did not update chart'
        page.locator('#monthlyMapSection summary').click()
        page.wait_for_function("document.querySelectorAll('#regionalMap svg path').length > 0 && document.querySelectorAll('#regionalMapDiff svg path').length > 0", timeout=90000)
        year_options = page.locator('#regionalMapYearSelect option').evaluate_all('(items)=>items.map(i=>i.value)')
        assert len(year_options) > 10
        page.locator('#regionalMapYearSelect').select_option('2024')
        page.wait_for_function("document.querySelector('#regionalMapTitleA').textContent.includes('2024')")
        page.screenshot(path=str(output / f'{key}-monthly.png'), full_page=True)
        if export:
            if stage == 'lazy':
                assert not page.evaluate('!!window.html2canvas || !!window.jspdf')
            download(page, page.locator('#regionalMapDownloadA'), output / f'{key}-regional-map.png', b'\x89PNG\r\n\x1a\n')
            if stage == 'lazy':
                assert page.evaluate('!!window.html2canvas && !window.jspdf')
            tools = page.locator('.chart-export-tools[data-canvas-id="monthlyChart"]')
            download(page, tools.get_by_role('button', name='PNG', exact=True), output / f'{key}-chart.png', b'\x89PNG\r\n\x1a\n')
            download(page, tools.get_by_role('button', name='PDF', exact=True), output / f'{key}-chart.pdf', b'%PDF-')
        page.evaluate("switchTab('index')")
        page.locator('#index.active').wait_for(state='visible')
        page.wait_for_function("Chart.getChart('climateIndexChart')?.data?.datasets?.length")
        index_before = chart_data(page, 'climateIndexChart')
        target = '02' if page.locator('#indexPeriodSelect').input_value() == '01' else '01'
        page.locator('#indexPeriodSelect').select_option(target)
        page.wait_for_timeout(300)
        index_updates = chart_data(page, 'climateIndexChart') != index_before
        if stage != 'control':
            assert index_updates, 'Climate index period change did not update chart'
        page.screenshot(path=str(output / f'{key}-index.png'), full_page=True)
        stations = {}
        hyras_modes = {}
        for tab, condition in [
            ('daily', "Chart.getChart('dailyChart')?.data?.datasets?.length"),
            ('stationClimateDays', "!document.getElementById('stationClimateDaysContent').hidden && Chart.getChart('stationClimateDaysCumulativeChart')?.data?.datasets?.length"),
            ('stationHeatwaves', "!document.getElementById('stationHeatwavesContent').hidden && Chart.getChart('stationHeatwavesBarChart')?.data?.datasets?.length"),
            ('stationPrecip', "!document.getElementById('stationPrecipContent').hidden && Chart.getChart('stationPrecipChart')?.data?.datasets?.length"),
            ('records', "!document.getElementById('recordContent').hidden && document.querySelector('#stationRecordTable tbody tr') && !document.getElementById('stationStreakContent').hidden && document.querySelector('#stationStreakTable tbody tr')"),
            ('stationSnow', "!document.getElementById('stationSnowContent').hidden && Chart.getChart('stationSnowChart')?.data?.datasets?.length"),
            ('stationProfile', "!document.getElementById('stationProfileContent').hidden && document.querySelector('#stationProfileMap .leaflet-marker-icon') && Chart.getChart('stationProfileTemperatureChart')?.data?.datasets?.length"),
            ('current', "document.querySelector('#currentMap .leaflet-marker-icon') && Chart.getChart('currentConditionsChart')?.data?.datasets?.length"),
            ('hyras', "document.querySelector('#hyrasMapFrame canvas') || (document.querySelector('#hyrasMapFrame img')?.naturalWidth > 0)"),
            ('maps', "document.querySelector('#stationMap .leaflet-marker-icon') && document.querySelector('#mapSummary strong')"),
        ]:
            if stage != 'control' and tab in ('stationSnow', 'current', 'hyras'):
                click_lazy_tab(page, tab, width)
            else:
                page.evaluate('(tab) => switchTab(tab)', tab)
            page.locator(f'#{tab}.active').wait_for(state='visible')
            try:
                page.wait_for_function(condition, timeout=45000)
                stations[tab] = 'rendered'
            except Exception:
                stations[tab] = 'not ready: ' + page.locator(f'#{tab} .record-loading:visible').all_text_contents().__str__()
            page.screenshot(path=str(output / f'{key}-{tab}.png'))
            if tab in ('stationProfile', 'current', 'hyras', 'maps') or (stage != 'control' and tab == 'stationSnow'):
                assert stations[tab] == 'rendered', (tab, stations[tab])
            if tab == 'current' and export:
                download(page, page.locator('#currentMapPngButton'), output / f'{key}-current-map.png', b'\x89PNG\r\n\x1a\n')
                download(page, page.locator('#currentMapPdfButton'), output / f'{key}-current-map.pdf', b'%PDF-')
            if tab == 'hyras' and stage != 'control':
                # Rank slider and step controls are active only once the archive is available.
                page.locator('#hyrasRankSlider').evaluate("el=>el.closest('details')?.setAttribute('open','')")
                page.wait_for_function("Number(document.getElementById('hyrasRankSlider').max)>0", timeout=90000)
                page.locator('#hyrasRankSlider').evaluate("el=>{el.value=el.max;el.dispatchEvent(new Event('input',{bubbles:true}));}")
                value=int(page.locator('#hyrasRankSlider').input_value())
                page.locator('#hyrasRankPrev').click()
                assert int(page.locator('#hyrasRankSlider').input_value())==value-1
                page.locator('#hyrasRankNext').click()
                assert int(page.locator('#hyrasRankSlider').input_value())==value
                for parameter, cap in [('tmean', 'Tmean'), ('tmax', 'Tmax'), ('tmin', 'Tmin')]:
                    page.locator('#hyrasParameterSelect').select_option(parameter)
                    page.wait_for_function(f"Chart.getChart('hyras{cap}RegionCanvas')?.data?.datasets?.length > 0 && !!document.querySelector('a[data-{parameter}-pdf]')", timeout=90000)
                    page.locator(f'#hyras{cap}RegionCanvas').scroll_into_view_if_needed()
                    page.screenshot(path=str(output / f'{key}-hyras-{parameter}.png'))
                    hyras_modes[parameter] = 'rendered'
                    if export:
                        download(page, page.locator(f'a[data-{parameter}-pdf]'), output / f'{key}-hyras-{parameter}.pdf', b'%PDF-')
                page.locator('#hyrasParameterSelect').select_option('precipitation')
                page.wait_for_function("document.querySelector('#hyrasMapFrame canvas') || document.querySelector('#hyrasMapFrame img')?.naturalWidth > 0", timeout=90000)
        if stage != 'control':
            page.wait_for_function("!document.getElementById('era5SynopticNav').hidden", timeout=30000)
            # Execute all new modules with real datasets, both from navigation and direct links.
            for tab, condition in [
                ('sst-europe', "document.getElementById('sstMapImage')?.naturalWidth>0 && !document.getElementById('sstPdfDownload').disabled"),
                ('state-monthly-ensemble', "Chart.getChart('stateMonthlyChart_gefs')?.data.datasets.some(d=>d.data.some(v=>Number.isFinite(v)))"),
                ('gebietsmittelArchive', "document.querySelectorAll('#gaMonths .ga-period').length===12 && document.querySelectorAll('#gaTableBody tr').length>0"),
                ('era5Atmosphere', "document.getElementById('era5AtmosImage')?.naturalWidth>0"),
            ]:
                click_lazy_tab(page,tab,width)
                page.wait_for_function(f"document.getElementById('{tab}').classList.contains('active') && ({condition})", timeout=90000)
                page.screenshot(path=str(output / f'{key}-{tab}-click.png'))
                if export and tab=='sst-europe':
                    download(page,page.locator('#sstPngDownload'),output / f'{key}-sst.png',b'\x89PNG\r\n\x1a\n')
                    download(page,page.locator('#sstPdfDownload'),output / f'{key}-sst.pdf',b'%PDF-')
                if export and tab=='state-monthly-ensemble':
                    download(page,page.locator('#stateMonthlyPng'),output / f'{key}-state.png',b'\x89PNG\r\n\x1a\n')
                    download(page,page.locator('#stateMonthlyPdf'),output / f'{key}-state.pdf',b'%PDF-')
                if export and tab=='gebietsmittelArchive':
                    download(page,page.locator('#gaPng'),output / f'{key}-archive.png',b'\x89PNG\r\n\x1a\n')
                    download(page,page.locator('#gaPdf'),output / f'{key}-archive.pdf',b'%PDF-')
                page.goto(URL + '?tab='+tab,wait_until='domcontentloaded',timeout=90000)
                page.wait_for_function(f"document.getElementById('{tab}').classList.contains('active') && ({condition})",timeout=90000)
                page.screenshot(path=str(output / f'{key}-{tab}-deeplink.png'))
            for direct in (False, True):
                if direct:page.goto(URL+'?tab=t850-ensembles',wait_until='domcontentloaded',timeout=90000)
                else:click_lazy_tab(page,'t850-ensembles',width)
                page.wait_for_function("typeof window.mountT850Ensembles==='function' && !!document.getElementById('t850YAxisMode')",timeout=90000)
                page.locator('#t850LocationInput').fill('Frankfurt am Main')
                page.locator('#t850LoadButton').click()
                page.wait_for_function("Chart.getChart('t850ChartGefs')?.data?.datasets?.length>0 && !document.getElementById('t850PdfDownload').disabled",timeout=120000)
                page.screenshot(path=str(output / f'{key}-t850-{"deeplink" if direct else "click"}.png'))
                if export and not direct:
                    download(page,page.locator('#t850PngDownload'),output / f'{key}-t850.png',b'\x89PNG\r\n\x1a\n')
                    download(page,page.locator('#t850PdfDownload'),output / f'{key}-t850.pdf',b'%PDF-')
            for tab, condition in [
                ('era5Europe', "era5EuropeIndex && document.querySelector('#era5EuropeImageWrap img')?.naturalWidth > 0"),
                ('europeStations', "europeStationLoaded && europeStationMap && europeStationMarkerById.size > 0"),
            ]:
                click_lazy_tab(page, tab, width)
                page.wait_for_function(f"document.querySelector('#{tab}.active') && ({condition})", timeout=90000)
                page.screenshot(path=str(output / f'{key}-{tab}-click.png'))
            page.goto(URL + '?tab=current&s_currentMapMetricSelect=wind', wait_until='domcontentloaded', timeout=90000)
            page.wait_for_function("document.querySelector('#current.active') && document.getElementById('currentMapMetricSelect').value === 'wind' && document.querySelector('#currentMap .leaflet-marker-icon')", timeout=90000)
            page.screenshot(path=str(output / f'{key}-current-deeplink.png'))
            page.goto(URL + '?tab=stationSnow&s_stationSnowStateSelect=Bayern&s_stationSnowStationSelect=05792', wait_until='domcontentloaded', timeout=90000)
            page.wait_for_function("document.querySelector('#stationSnow.active') && !document.getElementById('stationSnowContent').hidden && Chart.getChart('stationSnowChart')?.data?.datasets?.length", timeout=90000)
            assert page.locator('#stationSnowStateSelect').input_value() == 'Bayern'
            assert page.locator('#stationSnowStationSelect').input_value() == '05792'
            page.screenshot(path=str(output / f'{key}-snow-deeplink.png'))
            # Exercise the modules introduced by Schnitt 5 via restored URLs.
            page.goto(URL + '?tab=era5Europe', wait_until='domcontentloaded', timeout=90000)
            page.wait_for_function("document.querySelector('#era5Europe.active') && era5EuropeIndex && document.querySelector('#era5EuropeImageWrap img')?.naturalWidth > 0", timeout=90000)
            page.screenshot(path=str(output / f'{key}-era5-land.png'))
            page.goto(URL + '?tab=europeStations&s_europeStationParameter=tmin', wait_until='domcontentloaded', timeout=90000)
            page.wait_for_function("document.querySelector('#europeStations.active') && europeStationLoaded && europeStationMap && europeStationMarkerById.size > 0", timeout=90000)
            page.screenshot(path=str(output / f'{key}-europe-stations.png'))
            assert page.locator('#europeStationParameter').input_value() == 'tmin'
            page.goto(URL + '?tab=hyras&s_hyrasParameterSelect=tmin', wait_until='domcontentloaded', timeout=90000)
            page.wait_for_function("document.querySelector('#hyras.active') && document.getElementById('hyrasParameterSelect').value === 'tmin' && Chart.getChart('hyrasTminRegionCanvas')?.data?.datasets?.length > 0", timeout=90000)
            page.screenshot(path=str(output / f'{key}-hyras-deeplink.png'))
            page.evaluate("switchTab('era5Atmosphere')")
            page.locator('#era5Stratosphere').wait_for(state='visible', timeout=30000)
            assert not any('era5_stratosphere.js' in url for status, url in network), network
            page.screenshot(path=str(output / f'{key}-stratosphere.png'))
            page.goto(URL + '?tab=index&s_indexPeriodSelect=02&s_indexAreaSelect=Deutschland', wait_until='domcontentloaded', timeout=90000)
            page.wait_for_function("""document.querySelector('#index.active') && document.getElementById('indexPeriodSelect').value === '02' && document.getElementById('indexAreaSelect').value === 'Deutschland' && Chart.getChart('climateIndexChart')?.data?.datasets?.length""", timeout=90000)
            page.screenshot(path=str(output / f'{key}-index-deeplink.png'), full_page=True)
            if stage == 'source' and width == 1440:
                # Simulate a failed module transfer, then use the real retry button.
                page.route('**/js/aktuell.js?*', lambda route: route.abort())
                page.goto(URL + '?tab=current', wait_until='domcontentloaded', timeout=90000)
                retry = page.locator('#current .module-load-notice').get_by_role('button', name='Erneut versuchen')
                retry.wait_for(state='visible', timeout=30000)
                page.unroute('**/js/aktuell.js?*')
                retry.click()
                page.wait_for_function("DashboardModules.tabReady('current') && document.querySelector('#currentMap .leaflet-marker-icon')", timeout=90000)
                # A slow external Tmin file must not race restored tab state.
                def delay_tmin(route):
                    time.sleep(0.8)
                    route.continue_()
                page.route('**/js/hyras-tmin.js?*', delay_tmin)
                page.goto(URL + '?tab=hyras&s_hyrasParameterSelect=tmin', wait_until='domcontentloaded', timeout=90000)
                page.wait_for_function("document.querySelector('#hyras.active') && document.getElementById('hyrasParameterSelect').value === 'tmin' && Chart.getChart('hyrasTminRegionCanvas')?.data?.datasets?.length > 0", timeout=90000)
                page.screenshot(path=str(output / f'{key}-hyras-tmin-deeplink.png'))
                page.unroute('**/js/hyras-tmin.js?*', delay_tmin)
                # Failed middle group dependency must not execute a later override.
                page.route('**/js/hyras-tmin.js?*',lambda route:route.abort())
                page.goto(URL+'?tab=hyras&s_hyrasParameterSelect=tmin',wait_until='domcontentloaded',timeout=90000)
                retry=page.locator('#hyras .module-load-notice').get_by_role('button', name='Erneut versuchen')
                retry.wait_for(state='visible',timeout=30000)
                assert page.evaluate("typeof hyrasRenderBeforeTmin === 'undefined' && !DashboardModules.tabReady('hyras')")
                page.unroute('**/js/hyras-tmin.js?*')
                retry.click()
                page.wait_for_function("DashboardModules.tabReady('hyras') && Chart.getChart('hyrasTminRegionCanvas')?.data.datasets.length>0",timeout=90000)
                # Even a late atmosphere module must be ready before state restoration.
                page.route('**/era5_europe.js?*', delay_tmin)
                page.goto(URL + '?tab=era5Atmosphere', wait_until='domcontentloaded', timeout=90000)
                page.wait_for_function("document.querySelector('#era5Atmosphere.active') && typeof ensureEra5AtmosphereLoaded === 'function'", timeout=90000)
                page.unroute('**/era5_europe.js?*', delay_tmin)
        # Direct link with multiple persisted control values and Unicode region name.
        page.goto(URL + '?tab=monthly&s_monthlyAreaSelect=Deutschland&s_paramSelect=rain&s_monthSelect=10&s_monthlyReferenceSelect=1961-1990&s_regionalMapYearSelect=2025&s_regionalMapYearBSelect=2024', wait_until='domcontentloaded', timeout=90000)
        page.wait_for_function("""() => document.querySelector('#monthly.active') && monthlyData.length > 1000 &&
            ['monthlyAreaSelect','paramSelect','monthSelect','monthlyReferenceSelect','regionalMapYearSelect','regionalMapYearBSelect'].map(id=>document.getElementById(id).value).join('|') === 'Deutschland|rain|10|1961-1990|2025|2024' && Chart.getChart('monthlyChart')?.data?.datasets?.length""", timeout=90000)
        page.screenshot(path=str(output / f'{key}-deeplink.png'), full_page=True)
        if stage != 'control':
            for filename in ('core.js', 'uebersicht.js', 'gebietsmittel', 'extreme.js', 'stationen-kenntage', 'stationen-auswertungen', 'schnee.js', 'export-karten-vergleich', 'stationsprofil', 'aktuell', 'hyras.', 'hyras-tmin.', 'era5-land.', 'europa-stationen.js', 'dashboard-state.js', 'bootstrap.js'):
                assert any('/js/' + filename in url for url in loads), filename
            assert not [url for status, url in network if '/js/' in url], network
        assert not errors, errors
        assert not [e for e in console_errors if re.search(r'ReferenceError|SyntaxError|is not defined', e)], console_errors
        return {'stage': stage, 'width': width, 'passed': True, 'overview': overview,
                'monthly_chart': before, 'index_updates': index_updates, 'stations': stations, 'hyras_modes': hyras_modes, 'console_errors': console_errors,
                'page_errors': errors, 'network_errors': network}
    except Exception as exc:
        try:
            page.screenshot(path=str(output / f'{key}-FAILED.png'), full_page=True, timeout=10000)
        except Exception:
            pass
        return {'stage': stage, 'width': width, 'passed': False, 'error': str(exc),
                'page_errors': errors, 'console_errors': console_errors, 'network_errors': network}
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', type=Path)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare)
        return 0
    from playwright.sync_api import sync_playwright
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, proxy={'server': 'http://127.0.0.1:8089'}, args=['--ignore-certificate-errors', '--no-sandbox'])
        rows = [audit(browser, args.root, stage, width, args.output, export=(stage != 'control' and width == 1440))
                for stage, width in [('control', 1440), ('source', 1440), ('lazy', 1440), ('lazy', 390)]]
        browser.close()
    control = rows[0]
    for result in rows[1:]:
        if result['passed'] and control['passed']:
            for name in ('overview', 'monthly_chart', 'stations'):
                if result[name] != control[name]:
                    result['passed'] = False
                    result['error'] = 'Behavior differs from control: ' + name
    (args.output / 'results.json').write_text(json.dumps(rows, indent=2))
    print(json.dumps([{k: v for k, v in row.items() if k != 'monthly_chart'} for row in rows], indent=2))
    return 0 if all(row['passed'] for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
