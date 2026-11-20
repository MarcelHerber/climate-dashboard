"""Prepare the frozen baseline HTML and generated comparison assets."""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from optimize_dashboard_loading import EXTERNAL

SITE = "https://marcelherber.github.io/climate-dashboard/"
EXPECTED = "484d7d63f09a869be21f65d4ab55ec8858d13de773ae18708cd6434fe8340fcc"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    original = args.html.read_bytes()
    if hashlib.sha256(original).hexdigest() != EXPECTED:
        raise SystemExit("Archived baseline HTML hash mismatch")
    baseline = args.root / "baseline"
    baseline.mkdir(parents=True, exist_ok=True)
    (baseline / "index.html").write_bytes(original)
    for tag in EXTERNAL.finditer(original):
        src = re.search(rb'src="([^"]+)"', tag[0])[1].decode()
        if "://" in src:
            continue
        filename = src.split("?")[0]
        if not re.fullmatch(r"[\w.-]+\.js", filename):
            raise ValueError(src)
        with urlopen(Request(SITE + src, headers={"User-Agent": "CI performance comparison"}), timeout=90) as response:
            (baseline / filename).write_bytes(response.read())
    for stage in ("extract", "defer", "lazy"):
        dest = args.root / stage
        shutil.copytree(baseline, dest)
        subprocess.run([sys.executable, str(Path(__file__).with_name("optimize_dashboard_loading.py")), str(dest), "--stage", stage], check=True)
        for js in dest.glob("*.js"):
            subprocess.run(["node", "--check", str(js)], check=True)
    (args.root / "stage.txt").write_text("baseline")
    (args.root / "baseline-asset-sha256.txt").write_text("\n".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in sorted(baseline.iterdir())
    ) + "\n")


if __name__ == "__main__":
    main()
