#!/usr/bin/env python3
"""Download one-time pinned frontend dependencies; verify against uploaded inventory hashes."""
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib
import sys

ASSETS = [
    ("vendor/chart.js/4.4.1/dist/chart.umd.min.js", "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js", "d2af8974e95271638772e9e9524db5b9a6f58d6ec2d5d781400447b4a31c681e"),
    ("vendor/chartjs-plugin-zoom/2.0.1/dist/chartjs-plugin-zoom.min.js", "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js", "503c709802be285c676afe0369bf5f72066d0b0c23929188c3158f35c0327a9c"),
    ("vendor/chartjs-chart-matrix/1.3.0/dist/chartjs-chart-matrix.min.js", "https://cdn.jsdelivr.net/npm/chartjs-chart-matrix@1.3.0/dist/chartjs-chart-matrix.min.js", "e0cdbbdfda297be40d5dcea024f6f7e533336984b008287233209ee802b1efa2"),
    ("vendor/chartjs-plugin-datalabels/2.2.0/dist/chartjs-plugin-datalabels.min.js", "https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0", "20c08f3d9c6d2ef76df6d6a6f1127c0013339fe32add24222276c398c6308c38"),
    ("vendor/jspdf/4.2.1/dist/jspdf.umd.min.js", "https://cdn.jsdelivr.net/npm/jspdf@4.2.1/dist/jspdf.umd.min.js", "e6551fcdc32f09d6853b2c5126d18d01d9447e0da618a41a11ebeee0f6c20d54"),
    ("vendor/html2canvas/1.4.1/dist/html2canvas.min.js", "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js", "e87e550794322e574a1fda0c1549a3c70dae5a93d9113417a429016838eab8cb"),
    ("vendor/leaflet/1.9.4/dist/leaflet.css", "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", "a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6"),
    ("vendor/leaflet/1.9.4/dist/leaflet.js", "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", "db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a"),
    ("vendor/leaflet/1.9.4/dist/images/marker-icon.png", "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png", "574c3a5cca85f4114085b6841596d62f00d7c892c7b03f28cbfa301deb1dc437"),
    ("vendor/leaflet/1.9.4/dist/images/marker-icon-2x.png", "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png", "00179c4c1ee830d3a108412ae0d294f55776cfeb085c60129a39aa6fc4ae2528"),
    ("vendor/leaflet/1.9.4/dist/images/marker-shadow.png", "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png", "264f5c640339f042dd729062cfc04c17f8ea0f29882b538e3848ed8f10edb4da"),
    ("vendor/leaflet/1.9.4/dist/images/layers.png", "https://unpkg.com/leaflet@1.9.4/dist/images/layers.png", "1dbbe9d028e292f36fcba8f8b3a28d5e8932754fc2215b9ac69e4cdecf5107c6"),
    ("vendor/leaflet/1.9.4/dist/images/layers-2x.png", "https://unpkg.com/leaflet@1.9.4/dist/images/layers-2x.png", "066daca850d8ffbef007af00b06eac0015728dee279c51f3cb6c716df7c42edf"),
]

def main():
    for rel, url, expected in ASSETS:
        target = Path(rel)
        if target.exists():
            data = target.read_bytes()
        else:
            with urlopen(Request(url, headers={"User-Agent": "climate-dashboard-bootstrap/1.0"}), timeout=45) as r:
                data = r.read()
        found = hashlib.sha256(data).hexdigest()
        if found != expected:
            print(f"SHA-256 mismatch: {rel}: {found}", file=sys.stderr)
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"OK {rel} ({len(data)} bytes)")
    print(f"Verified {len(ASSETS)} files")
    return 0

if __name__ == "__main__":
    sys.exit(main())
