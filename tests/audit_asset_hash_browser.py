#!/usr/bin/env python3
"""Chromium smoke audit for content-hashed Pages assets on the built _site."""
import argparse
import functools
import hashlib
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright


class QuietFiles(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def hash_bytes(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()[:10]


def record_error(errors, error):
    errors.append(str(error))


def new_page(browser, width, host):
    ctx = browser.new_context(
        viewport={"width": width, "height": 900},
        is_mobile=width < 600, has_touch=width < 600, accept_downloads=True,
        ignore_https_errors=True,
    )
    page = ctx.new_page()
    errors, local_failures, local_script_urls = [], [], []
    page.on("pageerror", lambda err: record_error(errors, err))

    def on_response(rsp):
        if urlsplit(rsp.url).netloc == host and rsp.status >= 400:
            local_failures.append([rsp.status, rsp.url])
    page.on("response", on_response)

    def on_request(req):
        parsed = urlsplit(req.url)
        if parsed.netloc == host and parsed.path.endswith(".js"):
            local_script_urls.append(req.url)
    page.on("request", on_request)
    return ctx, page, errors, local_failures, local_script_urls


def wait_for_tab(page, tab):
    page.wait_for_function(
        """tab => {
          const node=document.getElementById(tab);
          return !!node && node.classList.contains('active')
            && !!window.DashboardModules
            && window.DashboardModules.tabReady(tab);
        }""",
        arg=tab, timeout=60000,
    )
    # Let the module callback and late-DOMContentLoaded handlers settle.
    page.wait_for_timeout(700)
    notice = page.locator(f'#{tab} > .module-load-notice[role="alert"]')
    assert notice.count() == 0, (tab, notice.all_text_contents())


def check_browser_files(page, manifest):
    entries = list(manifest["assets"].items())
    wrong = []
    for i in range(0, len(entries), 12):
        batch = [{"path": name, "hash": info["hash"]} for name, info in entries[i:i+12]]
        results = page.evaluate(
            """async batch => await Promise.all(batch.map(async ({path, hash}) => {
              const url = './' + path + '?v=' + hash;
              try {
                const response = await fetch(url, {cache:'no-store'});
                if (!response.ok) return {path, problem:'HTTP '+response.status};
                let bytes = new Uint8Array(await response.arrayBuffer());
                let normalized = new Uint8Array(bytes.length);
                let j = 0;
                for (let n=0; n<bytes.length; n++) {
                  if (bytes[n]===13 && n+1<bytes.length && bytes[n+1]===10) continue;
                  normalized[j++]=bytes[n];
                }
                const digest = await crypto.subtle.digest('SHA-256', normalized.subarray(0,j));
                const found=Array.from(new Uint8Array(digest))
                  .map(n=>n.toString(16).padStart(2,'0')).join('').slice(0,10);
                return found===hash?{path,ok:true}:{path,problem:'Hash '+found+' instead of '+hash};
              } catch (e) {
                return {path,problem:String(e)};
              }
            }))""", batch)
        wrong.extend(item for item in results if not item.get("ok"))
    assert not wrong, f"Browser asset fetch/hash errors: {wrong[:15]}"
    return len(entries)


def validate_loader_versions(page, manifest):
    modules = ["aktuell", "era5-land", "europa-stationen", "schnee",
        "hyras_temperature_interactive", "hyras", "hyras-tmin",
        "hyras_historical_temperature_1km", "t850_ensembles", "sst_europe",
        "state_monthly_ensemble", "gebietsmittel_archiv", "era5_europe",
        "station_snow_years", "station_snow_accumulation",
        "station_snow_explorer", "europe_station_basemap"]
    problems = []
    for name in modules:
        url = page.evaluate("name=>DashboardModules.moduleUrl(name)", name)
        uri = urlsplit(url)
        path = uri.path.removeprefix("./")
        actual = parse_qs(uri.query).get("v", [None])[0]
        expected = manifest["assets"].get(path, {}).get("hash")
        if not expected or actual != expected:
            problems.append([name, path, actual, expected])
    assert not problems, f"Lazy module table hash mismatch: {problems}"
    return len(modules)


def check_html_file_versions(site, manifest):
    # Every static script/css link in each staged page must carry its final hash.
    ref = re.compile(r'<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*"([^"]+)"', re.I)
    missing=[]
    number=0
    for html in manifest["html"]:
        text = (site / html).read_text(encoding="utf-8")
        for url in ref.findall(text):
            uri=urlsplit(url)
            if uri.scheme or uri.netloc or uri.path.startswith("/") or not uri.path.lower().endswith((".js",".css")):
                continue
            path = uri.path.removeprefix("./")
            expected=manifest["assets"].get(path,{}).get("hash")
            got=parse_qs(uri.query).get("v",[None])[0]
            if not expected or got != expected:
                missing.append([html,path,got,expected])
            number+=1
    assert not missing, f"HTML references without matching hash: {missing[:15]}"
    return number


def audit(site, output):
    output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((site/"asset-manifest.json").read_text(encoding="utf-8"))
    assert manifest["assets"] and "index.html" in manifest["html"]
    for p,info in manifest["assets"].items():
        assert (site/p).is_file() and hash_bytes((site/p).read_bytes())==info["hash"],p
    html_count=check_html_file_versions(site,manifest)

    server = ThreadingHTTPServer(("127.0.0.1", 0),
        functools.partial(QuietFiles, directory=str(site)))
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    base=f"http://127.0.0.1:{server.server_port}"
    host=f"127.0.0.1:{server.server_port}"
    report={"manifest_assets":len(manifest["assets"]), "html_pages":len(manifest["html"]),
            "html_refs":html_count,"cases":[]}
    try:
        with sync_playwright() as play:
            browser=play.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                # Test hashes in an actual browser, not only on the filesystem.
                ctx,page,errors,failed,requests=new_page(browser,1440,host)
                page.goto(base+"/index.html?tab=overview",wait_until="domcontentloaded",timeout=90000)
                page.wait_for_function("() => !!window.DashboardModules",timeout=30000)
                report["verified_browser_assets"]=check_browser_files(page,manifest)
                report["verified_lazy_modules"]=validate_loader_versions(page,manifest)
                # Static shell must execute; pure fetch verification is not enough.
                assert page.evaluate("() => typeof window.switchTab==='function' || typeof switchTab==='function'")
                assert not failed,failed
                assert not errors,errors
                ctx.close()

                cases = [
                    (1440,"overview",["current","era5Europe","sst-europe",
                           "hyras","state-monthly-ensemble","t850-ensembles"]),
                    (1440,"era5Atmosphere",["gebietsmittelArchive"]),
                    (390,"europeStations",["stationSnow","hyras"]),
                    (390,"hyras",["current"]),
                ]
                for width,direct,clicks in cases:
                    ctx,page,errors,failed,requests=new_page(browser,width,host)
                    name=f"{width}-{direct}"
                    try:
                        page.goto(base+"/index.html?tab="+direct,
                            wait_until="domcontentloaded",timeout=90000)
                        wait_for_tab(page,direct)
                        for tab in clicks:
                            page.evaluate("tab=>switchTab(tab)",tab)
                            wait_for_tab(page,tab)
                        # Check *executed* hashed scripts, not just fetch results.
                        js_loaded=sorted(set(urlsplit(u).path.lstrip("/") for u in requests))
                        for path in js_loaded:
                            if path in manifest["assets"]:
                                urls=[u for u in requests if urlsplit(u).path.lstrip("/")==path]
                                expected=manifest["assets"][path]["hash"]
                                assert all(parse_qs(urlsplit(u).query).get("v",[None])[0]==expected
                                    for u in urls), f"Script fetched with stale version: {path}"
                        page.screenshot(path=str(output/f"{name}.png"),full_page=False)
                        assert not failed,f"{name}: local HTTP errors {failed}"
                        assert not errors,f"{name}: JS runtime errors {errors}"
                        report["cases"].append({"viewport":width,"direct":direct,
                            "switched":clicks,"local_js_requested":len(js_loaded),
                            "page_errors":errors,"local_http_failures":failed})
                    finally:
                        ctx.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        worker.join(timeout=10)
        server.server_close()
        (output/"asset-hash-browser-report.json").write_text(
            json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--site",type=Path,default=Path("_site"))
    parser.add_argument("--output",type=Path,default=Path("asset-hash-browser-report"))
    args=parser.parse_args()
    audit(args.site.resolve(),args.output.resolve())
