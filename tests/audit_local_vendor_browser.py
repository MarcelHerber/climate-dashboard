#!/usr/bin/env python3
"""Step 5 browser smoke: real vendored JS/CSS/PNG from the Pages output."""
import functools
import hashlib
import importlib.util
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def run(root, output):
    spec=importlib.util.spec_from_file_location("vendor_import",ROOT/"tools/import_vendor_assets.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output.mkdir(parents=True,exist_ok=True)
    assert (root/"asset-manifest.json").is_file()
    asset_manifest=json.loads((root/"asset-manifest.json").read_text())
    static=module.EXPECTED
    assert len(static)==13
    for path,expected in static.items():
        content=(root/path).read_bytes()
        assert hashlib.sha256(content).hexdigest()==expected,(path,expected)
        content_hash=hashlib.sha256(content.replace(b"\r\n",b"\n")).hexdigest()[:10]
        assert asset_manifest["assets"][path]["hash"]==content_hash,(path,content_hash)

    server=ThreadingHTTPServer(("127.0.0.1",0),functools.partial(QuietHandler,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f"http://127.0.0.1:{server.server_port}"
    host=f"127.0.0.1:{server.server_port}"
    results=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                for width,direct in [(1440,"overview"),(390,"hyras"),(390,"europeStations"),(1440,"sst-europe")]:
                    context=browser.new_context(viewport={"width":width,"height":860},
                        is_mobile=width<600,has_touch=width<600,accept_downloads=True,
                        ignore_https_errors=True)
                    page=context.new_page()
                    failures=[]
                    external_cdn=[]
                    js_errors=[]
                    local_vendor_urls=set()
                    page.on("pageerror",lambda e: js_errors.append(str(e)))
                    def on_request(request):
                        url=request.url
                        if "cdn.jsdelivr.net/npm/" in url or "unpkg.com/leaflet@" in url:
                            external_cdn.append(url)
                        if "/vendor/" in url and urlsplit(url).netloc==host:
                            local_vendor_urls.add(url)
                    def on_response(response):
                        parsed=urlsplit(response.url)
                        if parsed.netloc==host and response.status>=400:
                            failures.append((response.status,response.url))
                    page.on("request",on_request)
                    page.on("response",on_response)
                    try:
                        page.goto(f"{base}/index.html?tab={direct}",wait_until="domcontentloaded",timeout=60000)
                        page.wait_for_function("""() => !!window.Chart &&
                          !!window.L && !!window.jspdf?.jsPDF && !!window.html2canvas &&
                          !!window.DashboardModules""",timeout=45000)
                        state=page.evaluate("""() => ({
                          chart: Chart.version, leaflet:L.version,
                          datalabels:!!Chart.registry.plugins.get('datalabels'),
                          zoom:!!Chart.registry.plugins.get('zoom'),
                          matrix:!!Chart.registry.controllers.get('matrix'),
                          pdf:!!window.jspdf?.jsPDF, canvas:typeof html2canvas==='function'
                        })""")
                        assert state["chart"]=="4.4.1",state
                        assert state["leaflet"]=="1.9.4",state
                        assert all(state[k] for k in ("datalabels","zoom","matrix","pdf","canvas")),state

                        # Fetch the exact hashed URLs from a real browser.
                        if width==1440 and direct=="overview":
                            for path,expected in static.items():
                                version=asset_manifest["assets"][path]["hash"]
                                fetched=page.evaluate("""async info=>{
                                  const r=await fetch('./'+info.path+'?v='+info.hash,{cache:'no-store'});
                                  const bytes=new Uint8Array(await r.arrayBuffer());
                                  return {status:r.status, bytes:Array.from(bytes)};
                                }""",{"path":path,"hash":version})
                                assert fetched["status"]==200,path
                                assert hashlib.sha256(bytes(fetched["bytes"])).hexdigest()==expected,path

                            page.evaluate("""() => {
                              const el=document.createElement('div');
                              el.id='vendorLeafletTestMap';el.style.cssText='width:420px;height:260px';
                              document.body.appendChild(el);
                              const map=L.map(el).setView([50.11,8.67],7);
                              const marker=L.marker([50.11,8.67]).addTo(map);
                              L.control.layers({'Station':L.layerGroup([marker])}).addTo(map);
                              window.__vendorLeafletMap=map;
                            }""")
                            page.wait_for_function("""() => {
                              const map=document.querySelector('#vendorLeafletTestMap');
                              return !!map?.querySelector('.leaflet-marker-icon') &&
                                !!map?.querySelector('.leaflet-control-layers-toggle');
                            }""",timeout=15000)
                            page.wait_for_timeout(1200)
                            png=page.evaluate("""() => {
                              const canvas=document.createElement('canvas');
                              canvas.width=520;canvas.height=260;
                              document.body.appendChild(canvas);
                              const chart=new Chart(canvas,{type:'bar',
                                data:{labels:['A','B'],datasets:[{label:'Test',data:[2,5]}]},
                                options:{animation:false,plugins:{
                                  datalabels:{display:true},
                                  zoom:{zoom:{wheel:{enabled:false},mode:'x'}}
                                }}});
                              const png=chart.toBase64Image();
                              chart.destroy();
                              return png;
                            }""")
                            assert png.startswith("data:image/png;base64,"),png[:100]
                            pdf=page.evaluate("""() => {
                              const doc=new window.jspdf.jsPDF();
                              doc.text('Vendored PDF smoke',10,10);
                              const output=doc.output('arraybuffer');
                              return Array.from(new Uint8Array(output).slice(0,5));
                            }""")
                            assert bytes(pdf)==b"%PDF-",pdf
                            png2=page.evaluate("""async () => {
                              const d=document.createElement('div');
                              d.textContent='Vendor html2canvas smoke';
                              d.style.cssText='width:120px;height:45px;background:#fff';
                              document.body.appendChild(d);
                              const c=await window.html2canvas(d,{logging:false});
                              return c.toDataURL('image/png');
                            }""")
                            assert png2.startswith("data:image/png;base64,")

                        # Direct links to lazy modules must still resolve.
                        if direct!="overview":
                            page.wait_for_function("""id => {
                              return !!document.getElementById(id) &&
                                !!window.DashboardModules &&
                                window.DashboardModules.tabReady(id);
                            }""",arg=direct,timeout=60000)
                        for tab in (["current","era5Europe"] if width==1440 else ["hyras","stationSnow"]):
                            page.evaluate("tab => switchTab(tab)",tab)
                            page.wait_for_function("tab => DashboardModules.tabReady(tab)",arg=tab,timeout=60000)

                        page.wait_for_timeout(500)
                        assert not failures,failures
                        assert not external_cdn,external_cdn
                        assert not [e for e in js_errors if re.search(
                            r"Chart is not defined|L is not defined|Leaflet is not|ChartDataLabels is not|jspdf is not|html2canvas is not",e,re.I)],js_errors
                        page.screenshot(path=str(output/f"vendor-{width}-{direct}.png"))
                        results.append({"width":width,"direct":direct,"libraries":state,
                            "vendor_requests":len(local_vendor_urls),
                            "http_errors":failures,"npm_cdns":external_cdn,
                            "js_library_errors":[]})
                        print(f"OK {width} {direct}: libraries/hashed URLs/lazy tabs",flush=True)
                    finally:
                        context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
        (output/"vendor-browser-report.json").write_text(json.dumps(
            {"vendor_files":len(static),"runs":results},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"vendor_files":len(static),"runs":results},ensure_ascii=False,indent=2))


if __name__=="__main__":
    run(ROOT/"_site",ROOT/"reports/vendor-browser")
