#!/usr/bin/env python3
"""Record the exact bytes served by CDN URLs currently referenced by index.html.

Audit only: downloads to GitHub Actions artifacts, never edits the live dashboard.
"""
from __future__ import annotations
import base64
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ASSETS = [
    ("chart-js", "4.4.1", "js", "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js", "vendor/chart.js/4.4.1/dist/chart.umd.min.js", None),
    ("chartjs-plugin-zoom", "2.0.1", "js", "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js", "vendor/chartjs-plugin-zoom/2.0.1/dist/chartjs-plugin-zoom.min.js", None),
    ("chartjs-chart-matrix", "1.3.0", "js", "https://cdn.jsdelivr.net/npm/chartjs-chart-matrix@1.3.0/dist/chartjs-chart-matrix.min.js", "vendor/chartjs-chart-matrix/1.3.0/dist/chartjs-chart-matrix.min.js", None),
    ("chartjs-plugin-datalabels", "2.2.0", "js", "https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0", "vendor/chartjs-plugin-datalabels/2.2.0/dist/chartjs-plugin-datalabels.min.js", None),
    ("jspdf", "4.2.1", "js", "https://cdn.jsdelivr.net/npm/jspdf@4.2.1/dist/jspdf.umd.min.js", "vendor/jspdf/4.2.1/dist/jspdf.umd.min.js", None),
    ("html2canvas", "1.4.1", "js", "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js", "vendor/html2canvas/1.4.1/dist/html2canvas.min.js", None),
    ("leaflet", "1.9.4", "css", "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", "vendor/leaflet/1.9.4/dist/leaflet.css", "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="),
    ("leaflet", "1.9.4", "js", "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", "vendor/leaflet/1.9.4/dist/leaflet.js", "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="),
    ("leaflet", "1.9.4", "image", "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png", "vendor/leaflet/1.9.4/dist/images/marker-icon.png", None),
    ("leaflet", "1.9.4", "image", "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png", "vendor/leaflet/1.9.4/dist/images/marker-icon-2x.png", None),
    ("leaflet", "1.9.4", "image", "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png", "vendor/leaflet/1.9.4/dist/images/marker-shadow.png", None),
    ("leaflet", "1.9.4", "image", "https://unpkg.com/leaflet@1.9.4/dist/images/layers.png", "vendor/leaflet/1.9.4/dist/images/layers.png", None),
    ("leaflet", "1.9.4", "image", "https://unpkg.com/leaflet@1.9.4/dist/images/layers-2x.png", "vendor/leaflet/1.9.4/dist/images/layers-2x.png", None),
]

def download(url: str):
    last_error = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "ClimateDashboard-vendor-audit/1.0",
                "Accept-Encoding": "identity",
                "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=40) as response:
                return response.read(), response.geturl(), response.headers.get("Content-Type", "")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            last_error = error
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"Could not download {url}: {last_error}")

def main():
    output = Path("reports/vendor-cdn-inventory")
    output.mkdir(parents=True, exist_ok=True)
    record = []
    failures = []
    for package, version, kind, url, path, expected_sri in ASSETS:
        try:
            payload, resolved, content_type = download(url)
            if not payload or payload.startswith((b"<html", b"<!doctype html")):
                raise ValueError("empty payload or unexpected HTML")
            sha = hashlib.sha256(payload).hexdigest()
            sri = "sha256-" + base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
            if expected_sri and expected_sri != sri:
                raise ValueError(f"SRI mismatch: expected {expected_sri}; got {sri}")
            local = output / path
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(payload)
            row = {
                "package": package, "version": version, "kind": kind,
                "source_url": url, "resolved_url": resolved, "relative_path": path,
                "content_type": content_type, "bytes": len(payload),
                "sha256": sha, "sri": sri
            }
            record.append(row)
            print("ASSET " + json.dumps(row, ensure_ascii=False), flush=True)
        except Exception as error:
            failures.append(f"{path}: {error}")
            print("ERROR " + failures[-1], file=sys.stderr, flush=True)
    (output/"cdn-inventory.json").write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if failures:
        (output/"failures.txt").write_text("\n".join(failures)+"\n", encoding="utf-8")
        return 1
    print(f"VERIFIED {len(record)} CDN assets (8 HTML entries + 5 Leaflet images)", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
