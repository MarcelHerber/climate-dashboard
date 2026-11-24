#!/usr/bin/env python3
"""Same-build, same-gzip server: eager baseline vs optional on-demand scripts."""
import argparse
import functools
import gzip
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HEAVY=("monthly_frequency.js","mosmix.js","station_thresholds.js")

def make_baseline(site):
    original=(site/"index.html").read_text(encoding="utf-8")
    start=original.index("<!-- DWD daily-map navigation stays eager;")
    end=original.index('<script src="monthly_layout.js',start)
    manifest=json.loads((site/"asset-manifest.json").read_text())
    parts=[]
    for name in HEAVY:
        h=manifest["assets"][name]["hash"]
        parts.append(f'<script src="{name}?v={h}"></script>')
    candidate=original[:start]+"\n".join(parts)+"\n"+original[end:]
    assert all(f'src="{name}?v=' in candidate for name in HEAVY)
    assert "optional_dashboard_modules.js" not in candidate
    return original.encode(),candidate.encode()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,directory=None,variants=None,**kwargs):
        self.variants=variants
        super().__init__(*args,directory=directory,**kwargs)
    def log_message(self,*a):pass
    def do_GET(self):
        parsed=urlsplit(self.path)
        if parsed.path in ("/","/index.html"):
            variant=parse_qs(parsed.query).get("lazy")
            if variant in (["on"],["off"]):
                return self.send_body(self.variants[variant[0]],"text/html; charset=utf-8",no_cache=True)
        if parsed.path.endswith((".html",".js",".css",".json")):
            path=Path(self.translate_path(self.path))
            if path.is_file():return self.send_body(path.read_bytes(),self.guess_type(str(path)))
        return super().do_GET()
    def send_body(self,raw,mime,no_cache=False):
        compressed="gzip" in self.headers.get("Accept-Encoding","")
        data=gzip.compress(raw,compresslevel=6) if compressed else raw
        self.send_response(200)
        self.send_header("Content-Type",mime)
        self.send_header("Cache-Control","no-store" if no_cache else "public, max-age=3600")
        self.send_header("Vary","Accept-Encoding")
        if compressed:self.send_header("Content-Encoding","gzip")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--site",type=Path,default=Path("_site"))
    p.add_argument("--port",type=int,default=8765)
    a=p.parse_args()
    site=a.site.resolve()
    on,off=make_baseline(site)
    print("Same build and origin: only eager vs on-demand scripts differ",flush=True)
    with ThreadingHTTPServer(("127.0.0.1",a.port),functools.partial(
        Handler,directory=str(site),variants={"on":on,"off":off})) as srv:
        srv.serve_forever()

if __name__=="__main__":
    main()
