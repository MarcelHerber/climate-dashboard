"""Browser verification using the original-archive pilot produced by Actions."""
import gzip
import json
import shutil
import tempfile
from pathlib import Path
from threading import Thread
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as directory:
    site=Path(directory)
    for name in ('stations_temperaturgegensatz.html','stations_temperaturgegensatz.js','stations_rekordlabor.css','dashboard_theme.css','dashboard_theme.js','t850_vector_export.js'):
        shutil.copy(ROOT/name,site/name)
    data=site/'data/rekordlabor/contrast'; shutil.copytree('/tmp/contrast-pilot',data)
    manifest={}
    for mode in ('hourly','daily'):
        p=json.loads(gzip.decompress((data/mode/'2025/DE.json.gz').read_bytes()))
        assert p['results']['9999-9999-9999'],mode
        manifest[mode]=[dict(year=2025,start=p['start'],end=p['end'],quality_version='contrast-qc-v2')]
        audit=json.loads(gzip.decompress((data/mode/'2025/quality.json.gz').read_bytes()))
        assert audit['version']=='contrast-qc-v2'
    (data/'index.json').write_text(json.dumps(manifest))
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=directory))
    Thread(target=server.serve_forever,daemon=True).start()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(args=['--no-sandbox'])
        for viewport in ({'width':1440,'height':900},{'width':390,'height':844}):
            page=browser.new_page(viewport=viewport,accept_downloads=True)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/stations_temperaturgegensatz.html')
            page.locator('#ranking tr').first.wait_for(timeout=60000)
            assert page.locator('#region option').count()==17
            assert page.locator('#ranking tr').count()<=100
            assert 'Plausibilitätsprüfung: 1/1' in page.locator('#status').inner_text()
            assert page.locator('#qcAudit').is_hidden()
            page.wait_for_function("!document.querySelector('#hourPanel').hidden")
            assert page.locator('#detail').inner_text().endswith('UTC')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            annual_value=page.evaluate("Chart.getChart('annual').data.datasets[0].data[0]")
            auto=page.evaluate("[Chart.getChart('annual').scales.y.min,Chart.getChart('annual').scales.y.max]")
            assert 0<auto[0]<annual_value<auto[1],auto
            page.locator('#axisMode').select_option('zero')
            assert page.evaluate("Chart.getChart('annual').scales.y.min") == 0
            page.locator('#axisMode').select_option('manual')
            manual_max=int(annual_value/5+2)*5
            page.locator('#axisMin').fill('0'); page.locator('#axisMin').press('Tab')
            page.locator('#axisMax').fill(str(manual_max)); page.locator('#axisMax').press('Tab')
            page.locator('#axisStep').fill('5'); page.locator('#axisStep').press('Tab')
            assert page.evaluate("[Chart.getChart('annual').scales.y.min,Chart.getChart('annual').scales.y.max]") == [0,manual_max]
            assert page.evaluate("Chart.getChart('annual').scales.y.ticks.map(t=>t.value)") == list(range(0,manual_max+1,5))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            for kind in ('png','pdf','svg','csv'):
                with page.expect_download(timeout=15000) as d: page.locator(f'[data-fmt={kind}]').click()
                assert d.value.suggested_filename.endswith('.'+kind)
                assert d.value.path().stat().st_size>100
                if kind=='svg':
                    svg=d.value.path().read_text()
                    assert 'DWD CDC' in svg and f'>{manual_max}</text>' in svg and '>5</text>' in svg
            page.locator('#axisMode').select_option('auto')
            assert page.evaluate("[Chart.getChart('annual').scales.y.min,Chart.getChart('annual').scales.y.max]") == auto
            page.locator('#mode').select_option('daily')
            page.wait_for_function("document.querySelector('#method').textContent.includes('TXK') && document.querySelector('#ranking tr')")
            assert page.locator('#hourPanel').is_hidden()
            page.locator('#region').select_option('11')
            page.wait_for_function("!document.querySelector('#status').textContent.startsWith('Lade')")
            assert not errors,errors
            page.close()
        browser.close()
    server.shutdown()
print('Original DWD pilot · desktop/mobile · filters, hourly detail, exports verified')
