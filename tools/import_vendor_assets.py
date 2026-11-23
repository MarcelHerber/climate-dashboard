#!/usr/bin/env python3
"""Import previously audited CDN binaries from the GitHub Actions artifact.

Refuses an unexpected file, a missing file or a SHA-256 mismatch before writing vendor/.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

EXPECTED = {
    "vendor/chart.js/4.4.1/dist/chart.umd.min.js": "d2af8974e95271638772e9e9524db5b9a6f58d6ec2d5d781400447b4a31c681e",
    "vendor/chartjs-plugin-zoom/2.0.1/dist/chartjs-plugin-zoom.min.js": "503c709802be285c676afe0369bf5f72066d0b0c23929188c3158f35c0327a9c",
    "vendor/chartjs-chart-matrix/1.3.0/dist/chartjs-chart-matrix.min.js": "e0cdbbdfda297be40d5dcea024f6f7e533336984b008287233209ee802b1efa2",
    "vendor/chartjs-plugin-datalabels/2.2.0/dist/chartjs-plugin-datalabels.min.js": "20c08f3d9c6d2ef76df6d6a6f1127c0013339fe32add24222276c398c6308c38",
    "vendor/jspdf/4.2.1/dist/jspdf.umd.min.js": "e6551fcdc32f09d6853b2c5126d18d01d9447e0da618a41a11ebeee0f6c20d54",
    "vendor/html2canvas/1.4.1/dist/html2canvas.min.js": "e87e550794322e574a1fda0c1549a3c70dae5a93d9113417a429016838eab8cb",
    "vendor/leaflet/1.9.4/dist/leaflet.css": "a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6",
    "vendor/leaflet/1.9.4/dist/leaflet.js": "db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a",
    "vendor/leaflet/1.9.4/dist/images/marker-icon.png": "574c3a5cca85f4114085b6841596d62f00d7c892c7b03f28cbfa301deb1dc437",
    "vendor/leaflet/1.9.4/dist/images/marker-icon-2x.png": "00179c4c1ee830d3a108412ae0d294f55776cfeb085c60129a39aa6fc4ae2528",
    "vendor/leaflet/1.9.4/dist/images/marker-shadow.png": "264f5c640339f042dd729062cfc04c17f8ea0f29882b538e3848ed8f10edb4da",
    "vendor/leaflet/1.9.4/dist/images/layers.png": "1dbbe9d028e292f36fcba8f8b3a28d5e8932754fc2215b9ac69e4cdecf5107c6",
    "vendor/leaflet/1.9.4/dist/images/layers-2x.png": "066daca850d8ffbef007af00b06eac0015728dee279c51f3cb6c716df7c42edf",
}


def verify(directory):
    manifest = json.loads((directory / "cdn-inventory.json").read_text(encoding="utf-8"))
    actual = {item["relative_path"]: item["sha256"] for item in manifest}
    if actual != EXPECTED or len(manifest) != len(EXPECTED):
        raise SystemExit("ERROR: The artifact inventory does not match the audited 13-file manifest")
    for path, expected in EXPECTED.items():
        source = directory / path
        if not source.is_file():
            raise SystemExit(f"ERROR: Missing vendor artifact {path}")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != expected:
            raise SystemExit(f"ERROR: SHA-256 mismatch for {path}: {digest} != {expected}")
    print(f"Verified {len(EXPECTED)} audited upstream files; no checksum mismatch.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", default="vendor-artifact")
    parser.add_argument("--destination", default=".")
    args = parser.parse_args()
    artifact = Path(args.artifact_dir)
    verify(artifact)
    for path in EXPECTED:
        output = Path(args.destination) / path
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(artifact / path, output)
    print(f"Imported {len(EXPECTED)} verified assets to {args.destination}/vendor/")
