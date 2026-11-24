#!/usr/bin/env python3
"""A/B server for real Pages artifact: same gzip origin; only Prefetch delay differs."""
import argparse
import gzip
import functools
import re
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,directory=None,**kwargs):
        self.site=Path(directory).resolve()
        super().__init__(*args,directory=directory,**kwargs)

    def log_message(self,*args):
        pass

    def do_GET(self):
        u=urlsplit(self.path)
        if u.path in ('/index.html','/') and parse_qs(u.query).get('prefetch') in (['on'],['off']):
            html=(self.site/'index.html').read_text(encoding='utf-8')
            off=parse_qs(u.query).get('prefetch')==['off']
            pattern=r'(?P<begin>src=")js/loader\.js(?P<query>\?v=[0-9a-f]{10})(?P<end>")'
            if off:
                html,n=re.subn(pattern,lambda m:m['begin']+'js/loader.prefetch-off.js'+m['query']+m['end'],html)
            else:
                n=len(re.findall(pattern,html))
            if n!=1:
                self.send_error(500,f'Expected 1 hashed loader reference, got {n}')
                return
            return self._content(html.encode(),'text/html; charset=utf-8',no_cache=True)
        if u.path.endswith(('.html','.js','.css','.json')):
            path=Path(self.translate_path(self.path))
            if path.is_file():
                return self._content(path.read_bytes(),self.guess_type(str(path)))
        return super().do_GET()

    def _content(self,raw,mime,no_cache=False):
        compressed='gzip' in self.headers.get('Accept-Encoding','')
        body=gzip.compress(raw,compresslevel=6) if compressed else raw
        self.send_response(200)
        self.send_header('Content-Type',mime)
        self.send_header('Vary','Accept-Encoding')
        self.send_header('Cache-Control','no-store' if no_cache else 'public, max-age=3600')
        if compressed:self.send_header('Content-Encoding','gzip')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--site',type=Path,default=Path('_site'))
    p.add_argument('--port',type=int,default=8765)
    a=p.parse_args()
    site=a.site.resolve()
    src=site/'js/loader.js'
    before=src.read_text()
    assert before.count('const PREFETCH_DELAY=6000;')==1
    off=before.replace('const PREFETCH_DELAY=6000;','const PREFETCH_DELAY=false;')
    assert off!=before
    (site/'js/loader.prefetch-off.js').write_text(off)
    print('A/B verified: exact same Pages build, only prefetch delay differs',flush=True)
    with ThreadingHTTPServer(('127.0.0.1',a.port),functools.partial(Handler,directory=str(site))) as srv:
        srv.serve_forever()

if __name__=='__main__':
    main()
