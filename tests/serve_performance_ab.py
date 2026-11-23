#!/usr/bin/env python3
"""Serve two comparable dashboard variants from one production build.

Only eight CDN-vs-vendor URLs differ; all other JS/CSS/data are identical.
Locally served text uses gzip, as on a production static web host.
"""
import argparse
import functools
import gzip
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPLACEMENTS = [
 ("vendor/chart.js/4.4.1/dist/chart.umd.min.js",
  "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"),
 ("vendor/chartjs-plugin-zoom/2.0.1/dist/chartjs-plugin-zoom.min.js",
  "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"),
 ("vendor/chartjs-chart-matrix/1.3.0/dist/chartjs-chart-matrix.min.js",
  "https://cdn.jsdelivr.net/npm/chartjs-chart-matrix@1.3.0/dist/chartjs-chart-matrix.min.js"),
 ("vendor/chartjs-plugin-datalabels/2.2.0/dist/chartjs-plugin-datalabels.min.js",
  "https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0"),
 ("vendor/jspdf/4.2.1/dist/jspdf.umd.min.js",
  "https://cdn.jsdelivr.net/npm/jspdf@4.2.1/dist/jspdf.umd.min.js"),
 ("vendor/html2canvas/1.4.1/dist/html2canvas.min.js",
  "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"),
 ("vendor/leaflet/1.9.4/dist/leaflet.css",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"),
 ("vendor/leaflet/1.9.4/dist/leaflet.js",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"),
]


def make_cdn_html(local_html: bytes) -> bytes:
    text = local_html.decode("utf-8")
    for local, cdn in REPLACEMENTS:
        pattern = r'(?P<prefix>\\b(?:src|href)=")' + re.escape(local) + r'\\?v=[0-9a-f]{10}(?P<suffix>")'
        # Construct pattern without double escaping for raw regular expressions.
        pattern = r'(?P<prefix>\b(?:src|href)=")' + re.escape(local) + r'\?v=[0-9a-f]{10}(?P<suffix>")'
        text, number = re.subn(pattern, lambda m: m.group("prefix") + cdn + m.group("suffix"), text)
        if number != 1:
            raise ValueError(f"Expected one versioned reference to {local}; found {number}")
    return text.encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        self.site_dir = Path(directory).resolve()
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, *_args):
        return

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path not in ("/", "/index.html"):
            candidate = Path(self.translate_path(self.path))
            if candidate.is_file() and candidate.suffix.lower() in (".js", ".css", ".html"):
                return self._send(candidate.read_bytes(), self.guess_type(str(candidate)))
        if parsed.path == "/index.html" and parse_qs(parsed.query).get("variant") == ["cdn"]:
            raw = (self.site_dir / "index.html").read_bytes()
            return self._send(make_cdn_html(raw), "text/html; charset=utf-8", no_cache=True)
        if parsed.path == "/index.html" and parse_qs(parsed.query).get("variant") == ["local"]:
            raw = (self.site_dir / "index.html").read_bytes()
            return self._send(raw, "text/html; charset=utf-8", no_cache=True)
        return super().do_GET()

    def _send(self, data: bytes, content_type: str, no_cache=False):
        supports_gzip = "gzip" in self.headers.get("Accept-Encoding", "").lower()
        body = gzip.compress(data, compresslevel=6) if supports_gzip else data
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if supports_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", "no-store" if no_cache else "public, max-age=3600")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, default=Path("_site"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    site = args.site.resolve()
    assert (site / "index.html").is_file()
    baseline = make_cdn_html((site / "index.html").read_bytes())
    assert baseline.count(b"https://cdn.jsdelivr.net/npm/") == 6
    assert baseline.count(b"https://unpkg.com/leaflet") == 2
    print(f"Comparable A/B variants verified: {len(REPLACEMENTS)} changed URL references", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 functools.partial(Handler, directory=str(site)))
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
