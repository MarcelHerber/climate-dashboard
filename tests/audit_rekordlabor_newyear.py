"""Browser checks on the original, complete DWD archive before publication."""
import csv
import functools
import http.server
import json
from pathlib import Path
import threading
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'newyear_qa';OUT.mkdir(exist_ok=True)
data=json.loads((ROOT/'data/rekordlabor/newyear/index.json').read_text(encoding='utf8'))
assert data['complete'] and len(data['stations'])>=100

def probe(page,width):
    page.goto(f'http://127.0.0.1:{server.server_port}/stations_rekordlabor.html',wait_until='domcontentloaded',timeout=90000)
    page.locator('#rlTabNewYear').click()
    page.wait_for_function("()=>document.querySelectorAll('#rlNYStation option').length>100",timeout=45000)
    for direction in ('warm','cold'):
        page.locator('#rlNYDirection').select_option(direction)
        expected=(max if direction=='warm' else min)(r[1] for st in data['stations'] for r in st['records'])
        assert str(expected).replace('.',',').rstrip('0').rstrip(',') in page.locator('#rlNYTable tr').first.inner_text()
    page.locator('#rlNYState').select_option('Hessen')
    hessen={st['id'] for st in data['stations'] if st['state']=='Hessen'}
    assert set(page.locator('#rlNYStation option').evaluate_all('(opts)=>opts.map(o=>o.value)'))==hessen|{'all'}
    for direction in ('warm','cold'):
        page.locator('#rlNYDirection').select_option(direction)
        expected=(max if direction=='warm' else min)(r[1] for st in data['stations'] if st['id'] in hessen for r in st['records'])
        assert str(expected).replace('.',',').rstrip('0').rstrip(',') in page.locator('#rlNYTable tr').first.inner_text()
    with page.expect_download(timeout=30000) as download:page.locator('#rlNewYear [data-rl-export="csv"]').click()
    regional=OUT/f'{width}-hessen.csv';download.value.save_as(str(regional))
    with regional.open(encoding='utf-8-sig',newline='') as handle:
        rows=list(csv.DictReader(handle,delimiter=';'))
    assert rows and all(r['Bundesland']=='Hessen' and r['Stations-ID'] in hessen for r in rows)
    page.locator('#rlNYStation').select_option(next(iter(hessen)))
    page.locator('#rlNYState').select_option('Bayern')
    assert page.locator('#rlNYStation').input_value()=='all'
    page.locator('#rlNYState').select_option('')
    assert page.locator('#rlNYStation option').count()==len(data['stations'])+1
    eligible=[st for st in data['stations'] if sum(1991<=r[0]<=2020 for r in st['records'])>=2]
    assert eligible,'No station has two measurements from 1991–2020'
    chosen=next((st for st in eligible if st['id']=='01420'),eligible[0])
    page.locator('#rlNYStation').select_option(chosen['id'])
    page.locator('#rlNYPeriod').select_option('1991-2020')
    if page.locator('#rlNYTrend').is_enabled():page.locator('#rlNYTrend').check()
    for kind in ('csv','png','pdf','svg'):
        btn=page.locator(f'#rlNewYear [data-rl-export="{kind}"]')
        assert btn.is_enabled(),kind
        with page.expect_download(timeout=30000) as download:btn.click()
        path=OUT/f'{width}.{kind}';download.value.save_as(str(path))
        content=path.read_bytes()
        if kind=='csv':
            with path.open(encoding='utf-8-sig',newline='') as handle:
                rows=list(csv.DictReader(handle,delimiter=';'))
            assert len(rows)==sum(1991<=r[0]<=2020 for r in chosen['records'])
            assert all(1991<=int(r['Jahr'])<=2020 and r['Stations-ID']==chosen['id'] for r in rows)
            assert all(r['Bezugszeit'] in ('UTC','MEZ (MD)') for r in rows)
        if kind=='png':assert content.startswith(b'\x89PNG')
        if kind=='pdf':assert content.startswith(b'%PDF')
        if kind=='svg':assert b'<svg' in content and b'<image' not in content
    assert page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+3')
    page.screenshot(path=str(OUT/f'{width}-screenshot.png'),full_page=True)

server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(http.server.SimpleHTTPRequestHandler,directory=ROOT))
threading.Thread(target=server.serve_forever,daemon=True).start()
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
    for width in (390,1200):
        ctx=browser.new_context(viewport={'width':width,'height':850},accept_downloads=True,has_touch=width<600,is_mobile=width<600)
        probe(ctx.new_page(),width);ctx.close()
    browser.close()
server.shutdown()
print('DWD NEW YEAR DESKTOP AND MOBILE OK')
