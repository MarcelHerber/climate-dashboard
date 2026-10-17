#!/usr/bin/env python3
"""Safe metadata-only probe of official ČHMÚ synoptic charts.

The 2026 website renders its imagery dynamically. This probe NEVER fabricates
a UTC validity timestamp, never downloads/ republishes unverified pictures,
and never copies query tokens/HTML. It records which static links the page
advertises so an independent map adapter can be built from actual evidence.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

PAGE="https://www.chmi.cz/predpoved-pocasi/synopticka-situace"
OUTPUT=Path(__file__).resolve().parents[1]/"data/synoptic_charts/chmi_probe.json"
TRUSTED={"www.chmi.cz","chmi.cz","opendata.chmi.cz","data.chmi.cz"}
ASSET_EXT=re.compile(r"\.(?:png|gif|jpe?g|webp|svg)$",re.I)
DATE_RE=re.compile(r"(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)[T_\-]?([012]\d)(?!\d)")
SYN_RE=re.compile(r"synop|front|tlak|pressure|map[ay]",re.I)


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag not in ("a","img","source","script","link","iframe","picture"):
            return
        raw=attrs.get("src") or attrs.get("href") or attrs.get("data-src") or attrs.get("data-original")
        if raw:self.refs.append({"tag":tag,"value":raw})


def probe(now=None,fetch=None):
    now=now or datetime.now(timezone.utc)
    result={"schema_version":1,"generated_utc":now.isoformat(timespec="seconds"),
            "provider":"ČHMÚ","source_page":PAGE,"state":"unavailable",
            "verified_utc_charts":0,
            "note":"Only original charts with independently published UTC validity can be included."}
    try:
        if fetch is None:
            req=Request(PAGE,headers={"User-Agent":"ClimateDashboard/1.0 (public ČHMÚ chart metadata check)",
                                      "Accept":"text/html"})
            with urlopen(req,timeout=28) as conn:
                raw=conn.read(4_000_001)
                if len(raw)>4_000_000:raise ValueError("page too large")
                html=raw.decode("utf-8","replace")
        else:html=fetch()
        parser=Resources()
        parser.feed(html)
        refs=[]
        for item in parser.refs:
            try:
                uri=urlparse(urljoin(PAGE,item["value"]))
                if uri.hostname not in TRUSTED:continue
                # Remove query/fragment unconditionally: they can include session identifiers.
                ref=uri.scheme+"://"+uri.netloc+uri.path
                refs.append({"tag":item["tag"],"path":ref[:300],
                             "image":bool(ASSET_EXT.search(uri.path)),
                             "synoptic":bool(SYN_RE.search(uri.path)),
                             "dated":bool(DATE_RE.search(uri.path))})
            except ValueError:continue
        result.update({
            "state":"static_metadata_only",
            "html_bytes":len(html.encode("utf-8")),
            "links_seen":len(parser.refs),
            "trusted_links":len(refs),
            "dated_synoptic_images":sum(x["image"] and x["synoptic"] and x["dated"] for x in refs),
            "synoptic_image_links":list(dict.fromkeys(x["path"] for x in refs
                                                    if x["image"] and x["synoptic"]))[:15],
            "dated_image_paths":list(dict.fromkeys(x["path"] for x in refs
                                                if x["image"] and x["dated"]))[:10],
            "js_resources":list(dict.fromkeys(x["path"] for x in refs
                                            if x["tag"]=="script"))[:15],
            "synoptic_page_links":list(dict.fromkeys(x["path"] for x in refs
                                                    if x["tag"]=="a" and x["synoptic"]))[:12],
        })
        if not result["dated_synoptic_images"]:
            result["note"]="No independently dated synoptic image found in static HTML. Dynamic provider API not yet identified; link to original page only."
        else:
            result["note"]="Dated candidate paths found, but time semantics and product licensing require independent verification before publication."
    except Exception as exc:
        result.update(state="fetch_error",reason=(type(exc).__name__+": "+str(exc))[:220])
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,default=OUTPUT)
    args=ap.parse_args()
    result=probe()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ČHMÚ official chart probe:",result["state"],
          "dated synoptic image candidates:",result.get("dated_synoptic_images",0),flush=True)


if __name__=="__main__":
    main()
