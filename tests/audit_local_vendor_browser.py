#!/usr/bin/env python3
"""Full same-origin browser-library audit for the staged Pages artifact."""
import argparse
import functools
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def audit(site: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    required = [
        "vendor/chart.js/4.4.1/dist/chart.umd.min.js",
        "vendor/chartjs-plugin-zoom/2.0.1/dist/chartjs-plugin-zoom.min.js",
        "vendor/chartjs-chart-matrix/1.3.0/dist/chartjs-chart-matrix.min.js",
        "vendor/chartjs-plugin-datalabels/2.2.0/dist/chartjs-plugin-datalabels.min.js",
        "vendor/jspdf/4.2.1/dist/jspdf.umd.min.js",
        "vendor/html2canvas/1.4.1/dist/html2canvas.min.js",
        "vendor/leaflet/1.9.4/dist/leaflet.css",
        "vendor/leaflet/1.9.4/dist/leaflet.js",
    ]
    manifest = json.loads((site / "asset-manifest.json").read_text())
    for asset in required:
        assert (site / asset).is_file(), f"Missing vendor file: {asset}"
        assert asset in manifest["assets"], f"Not in manifest: {asset}"
    files = sorted(x for x in (site / "vendor").rglob("*") if x.is_file())
    assert len(files) == 13, f"Expected 13 vendor files; found {len(files)}"

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(site)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    result = {"asset_count": len(files), "devices": []}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                for width, mobile in [(1440, False), (390, True)]:
                    ctx = browser.new_context(viewport={"width": width, "height": 900},
                        is_mobile=mobile, has_touch=mobile, ignore_https_errors=True)
                    page = ctx.new_page()
                    cdn_npm, vendor_failures, page_errors = [], [], []
                    page.on("request", lambda req: cdn_npm.append(req.url) if
                        ("cdn.jsdelivr.net/npm/" in req.url or "unpkg.com/" in req.url) else None)
                    page.on("response", lambda rsp: vendor_failures.append([rsp.status, rsp.url]) if
                        urlparse(rsp.url).path.startswith("/vendor/") and rsp.status != 200 else None)
                    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                    try:
                        page.goto(base + "/index.html?tab=overview", wait_until="domcontentloaded", timeout=90000)
                        page.wait_for_function("""() => window.Chart && window.L && window.jspdf?.jsPDF && window.html2canvas""",
                                               timeout=30000)
                        library_demo = page.evaluate("""async () => {
                          const registry=Chart.registry;
                          if (!registry.getPlugin('datalabels') || !registry.getPlugin('zoom'))
                            throw Error('Chart.js plugins not registered');
                          if (!registry.getController('matrix')) throw Error('Matrix chart controller missing');
                          const area=document.createElement('div');
                          area.style.cssText='position:fixed;left:0;top:0;width:310px;height:200px;background:white;z-index:99999';
                          document.body.appendChild(area);
                          const map=L.map(area,{zoomControl:false}).setView([50,10],5);
                          const marker=L.marker([50,10]).addTo(map);
                          L.control.layers({}, {Markers:L.layerGroup([L.marker([51,11])])}).addTo(map);
                          const icon=marker._icon?.src || '';
                          const shadow=marker._shadow?.src || '';
                          if (!icon.includes('/vendor/leaflet/') || !shadow.includes('/vendor/leaflet/'))
                            throw Error('Marker URLs are not local: '+icon+' / '+shadow);
                          const cnv=document.createElement('canvas');
                          cnv.width=450;cnv.height=240;document.body.appendChild(cnv);
                          const bar=new Chart(cnv,{type:'bar',data:{labels:['A','B'],datasets:[{data:[4,7]}]},
                            options:{responsive:false,animation:false,plugins:{datalabels:{display:true}}}});
                          if(typeof bar.zoom !== 'function') throw Error('Chart zoom not registered');
                          bar.zoom(1.2);
                          const png=cnv.toDataURL('image/png');
                          if(!png.startsWith('data:image/png;base64,')) throw Error('PNG failed');
                          bar.destroy();
                          const matrix=new Chart(cnv,{type:'matrix',data:{datasets:[{
                            data:[{x:1,y:1,v:3}],backgroundColor:'red',width:18,height:18}]},
                            options:{responsive:false,animation:false,scales:{x:{type:'linear'},y:{type:'linear'}}}});
                          matrix.update();matrix.destroy();
                          const pdf=new jspdf.jsPDF();
                          pdf.text('Local vendor OK',10,15);
                          const raw=new Uint8Array(pdf.output('arraybuffer'));
                          const magic=String.fromCharCode(...raw.slice(0,4));
                          if(magic!=='%PDF') throw Error('PDF failed');
                          const shot=await html2canvas(area,{logging:false});
                          if(!shot.width || !shot.height) throw Error('html2canvas failed');
                          map.remove();cnv.remove();area.remove();
                          return {pdf_bytes:raw.length,png_prefix:png.slice(0,22),map_icon:icon,
                            map_shadow:shadow,html2canvas_width:shot.width};
                        }""")
                        page.wait_for_timeout(600)
                        tabs = page.evaluate("""() => Array.from(document.querySelectorAll('button.tab-button[onclick]'))
                          .map(el=>(el.getAttribute('onclick')||'').match(/switchTab\\('([^']+)'\\)/)?.[1])
                          .filter(Boolean)""")
                        # Audit each main-page tab, not external subpages. Hidden navigation
                        # entries can still be selected programmatically.
                        assert len(tabs) >= 25, f"Too few main-page tabs: {tabs}"
                        switched = []
                        for tab in tabs:
                            page.evaluate("tab => switchTab(tab)", tab)
                            page.wait_for_timeout(180)
                            switched.append(tab)
                        assert not cdn_npm, f"Remote browser library requests: {cdn_npm}"
                        assert not vendor_failures, f"Vendor HTTP errors: {vendor_failures}"
                        # Missing data in a staging snapshot is recorded but does not
                        # mask errors explicitly concerning bundled dependencies.
                        library_errors = [e for e in page_errors if re.search(
                            r"Chart is not defined|L is not defined|jspdf is not defined|html2canvas is not defined|"
                            r"Library.*not loaded|Cannot find module.*vendor", e, re.I)]
                        assert not library_errors, f"Runtime library errors: {library_errors}"
                        result["devices"].append({"width": width, "mobile": mobile,
                            "main_page_tabs": len(switched), "tabs": switched, "libraries": library_demo,
                            "vendor_http_failures": vendor_failures, "remote_npm_requests": cdn_npm,
                            "other_page_errors": page_errors[:15]})
                        page.screenshot(path=str(output / f"desktop-{width}.png"), full_page=False)
                    finally:
                        ctx.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=10)
        (output / "local-vendor-browser.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, default=Path("_site"))
    parser.add_argument("--output", type=Path, default=Path("reports"))
    args = parser.parse_args()
    audit(args.site.resolve(), args.output.resolve())
