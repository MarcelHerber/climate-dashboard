"""Runner-only HTTPS capture/replay for paired Lighthouse audits.

One proxy process, browser URL and resource snapshot serve all variants.
No deployed content is changed. Run with mitmdump on the CI runner.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mitmproxy import http

ROOT = Path(os.environ["PERF_SNAPSHOT_ROOT"])
SITE = "marcelherber.github.io"
PREFIX = "/climate-dashboard/"
cache = {}
manifest = {}


def key(url):
    parts = urlsplit(url)
    # Ignore time-generated cache busters only on mutable data responses.
    if not parts.path.endswith((".js", ".css", ".html")):
        query = [(k, v) for k, v in parse_qsl(parts.query) if not (k in ("t", "v") and v.isdigit())]
        return urlunsplit(parts._replace(query=urlencode(query)))
    return url


def data_request(url):
    parts = urlsplit(url)
    return parts.hostname in (SITE, "raw.githubusercontent.com") and parts.path.endswith(
        (".json", ".csv", ".gz", ".png", ".geojson", ".jpg", ".webp", ".svg"))


def local_file(flow):
    if flow.request.pretty_host != SITE:
        return None
    path = urlsplit(flow.request.path).path
    if not path.startswith(PREFIX):
        return None
    name = path[len(PREFIX):]
    # Only serve checked-in dashboard module assets from the nested folder;
    # never allow traversal or arbitrary paths.
    if not name or ("/" in name and name not in {
        "js/core.js", "js/uebersicht.js", "js/gebietsmittel.js", "js/gebietsmittel.optimized.js",
        "js/extreme.js", "js/stationen-kenntage.js", "js/stationen-auswertungen.js", "js/schnee.js",
        "js/stationen-kenntage.optimized.js", "js/stationen-auswertungen.optimized.js",
    }):
        return None
    stage = (ROOT / "stage.txt").read_text().strip()
    chosen = ROOT / stage / name
    if chosen.is_file():
        return chosen
    original = ROOT / "baseline" / name
    return original if original.is_file() else None


def request(flow: http.HTTPFlow):
    if flow.request.method != "GET":
        return
    path = local_file(flow)
    if path:
        content = path.read_bytes()
        kind = "text/html; charset=utf-8" if path.suffix == ".html" else "application/javascript; charset=utf-8"
        flow.response = http.Response.make(200, content, {
            "Content-Type": kind, "Content-Encoding": "gzip", "Cache-Control": "no-store",
        })
        # Response.make sets content, so encode explicitly using raw_content.
        flow.response.raw_content = gzip.compress(content, mtime=0)
        flow.response.headers["Content-Length"] = str(len(flow.response.raw_content))
        return
    normalized = key(flow.request.pretty_url)
    if normalized in cache:
        flow.response = http.Response.from_state(cache[normalized])
    elif (ROOT / "sealed.txt").exists() and data_request(normalized):
        with (ROOT / "late-data-requests.txt").open("a") as log:
            log.write(normalized + "\n")


def response(flow: http.HTTPFlow):
    if flow.request.method != "GET" or local_file(flow) is not None:
        return
    normalized = key(flow.request.pretty_url)
    if normalized not in cache:
        cache[normalized] = flow.response.get_state()
        payload = flow.response.raw_content or b""
        sha = hashlib.sha256(payload).hexdigest()
        manifest[normalized] = {
            "status": flow.response.status_code,
            "sha256": sha,
            "bytes": len(payload),
        }
        # Store the exact transferred response bodies for the comparison's
        # reproducibility, including mutable external data.
        payload_dir = ROOT / "payloads"
        payload_dir.mkdir(exist_ok=True)
        (payload_dir / sha).write_bytes(payload)
        manifest[normalized]["headers"] = dict(flow.response.headers)
        (ROOT / "snapshot-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        flow.response = http.Response.from_state(cache[normalized])
