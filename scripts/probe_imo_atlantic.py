#!/usr/bin/env python3
"""Discover IMO North Atlantic chart image and exact UTC metadata, fail closed.

The website publishes ECMWF pressure/isobar forecasts with validity written on
the map. Neither the slider position nor the web page retrieval date may be
treated as the chart's valid_utc. This probe fetches NO images, and never
publishes an IMO chart. It reports actual HTML/script assets for inspection.
"""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"synoptic_charts"/"imo_probe.json"
PAGES=(
 "https://en.vedur.is/weather/shipping/atlantic/",
 "https://www.vedur.is/vedur/sjovedur/atlantshafskort/",
)
TERMS="https://en.vedur.is/about-imo/the-web/conditions/"
IMG_EXT=re.compile(r"\.(?:png|jpe?g|gif|webp)(?:$|[?#])",re.I)
JS_EXT=re.compile(r"\.js(?:$|[?#])",re.I)
DATE_ISO=re.compile(r"(?<![0-9])((?:20[0-9]{2})[-]?[01][0-9][-]?[0-3][0-9])[_T -]?([012][0-9])(?::?([0-5][0-9]))?(?![0-9A-Za-z])")
VALIDITY_KEYS=("data-valid-utc","data-validity","data-valid-time","data-gildistimi","valid_utc")
ATTR_IMAGE_KEYS=("src","data-src","data-image","data-url","data-original","data-img","href")
ALLOWED_HOSTS={"en.vedur.is","www.vedur.is","vedur.is","brunnur.vedur.is"}
MAX_HTML_BYTES=650_000
MAX_JS_FILES=5
MAX_JS_BYTES=250_000

def allowed_url(raw:str,base:str)->str|None:
    if not isinstance(raw,str) or not raw.strip():return None
    url=urljoin(base,raw.strip())
    parsed=urlparse(url)
    if parsed.scheme!="https" or parsed.hostname not in ALLOWED_HOSTS:return None
    if parsed.username or parsed.password:return None
    return url

def exact_utc(text:str)->str|None:
    """Parse *only* complete year-month-day-hour UTC timestamps, never a lead."""
    if not isinstance(text,str):return None
    for hit in DATE_ISO.finditer(text):
        raw=hit.group(1).replace("-","")
        try:
            dt=datetime.strptime(raw+hit.group(2)+(hit.group(3) or "00"),"%Y%m%d%H%M")
            return dt.replace(tzinfo=timezone.utc).isoformat(timespec="minutes")
        except ValueError:
            pass
    return None

class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images=[]
        self.scripts=[]
        self.validated=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        validity=next((d.get(k) for k in VALIDITY_KEYS if d.get(k)),None)
        for key in ATTR_IMAGE_KEYS:
            value=d.get(key)
            if not value:continue
            if IMG_EXT.search(urlparse(value).path):
                self.images.append({"url":value,"valid_hint":validity or "",
                                    "alt":str(d.get("alt") or "")[:160]})
        if tag=="script" and d.get("src"):
            self.scripts.append(d["src"])

def document_assets(html:str,base:str)->dict:
    p=AssetParser();p.feed(html)
    seen=set();images=[]
    for item in p.images:
        url=allowed_url(item["url"],base)
        if not url or url in seen:continue
        seen.add(url)
        valid=exact_utc(item["valid_hint"])
        filename=exact_utc(unquote(urlparse(url).path))
        # Both independent provider-side metadata and the URL must agree.
        same=bool(valid and filename and valid==filename)
        images.append({"url":url,"valid_hint_utc":valid,
                       "filename_utc":filename,"strong_timestamp_match":same,
                       "alt":item["alt"]})
    scripts=[];seen=set()
    for value in p.scripts:
        url=allowed_url(value,base)
        if not url or not JS_EXT.search(urlparse(url).path) or url in seen:continue
        seen.add(url);scripts.append(url)
    return {"images":images[:35],"scripts":scripts[:30]}

def download_text(url:str,limit:int=MAX_HTML_BYTES)->str:
    req=Request(url,headers={"User-Agent":"ClimateDashboardDeutschland/1.0 (IMO-source-verification)",
                              "Accept":"text/html,application/javascript,text/javascript;q=0.8"})
    with urlopen(req,timeout=18) as resp:
        body=resp.read(limit+1)
        if len(body)>limit:raise ValueError("Page exceeds bounded source probe")
        return body.decode("utf-8","replace")

def inspect_script(text:str)->list[str]:
    """Only report possible provider image/template clues; never fetch images."""
    patterns=(r"""["']([^"'<>\s]{5,180}\.(?:png|gif|jpe?g|webp)(?:\?[^"'<>\s]*)?)["']""",
              r"""["']([^"'<>\s]{5,180}(?:spakort|atlantshaf|forecast|atlantic)[^"'<>\s]{0,90})["']""")
    hits=[]
    for pat in patterns:
        hits.extend(re.findall(pat,text,re.I))
    return list(dict.fromkeys(hits))[:12]

def probe(now:datetime|None=None,fetch=download_text)->dict:
    now=now or datetime.now(timezone.utc)
    reports=[];candidates=[];checked=set()
    for page in PAGES:
        report={"page":page,"state":"unreachable","image_count":0,"script_count":0}
        try:
            html=fetch(page)
            assets=document_assets(html,page)
            report.update({"state":"inspected","image_count":len(assets["images"]),
                           "script_count":len(assets["scripts"]),
                           "inline_image_or_endpoint_hints":inspect_script(html)})
            for img in assets["images"]:
                candidates.append({"source_page":page,**img})
            # Avoid unbounded crawling; only same-origin JavaScript. This is
            # diagnostics, NOT evidence of an image's timestamp.
            for url in assets["scripts"]:
                if len(checked)>=MAX_JS_FILES:break
                if url in checked:continue
                checked.add(url)
                try:
                    code=fetch(url)
                    report.setdefault("script_hints",[]).append({
                        "url":url,"image_or_endpoint_strings":inspect_script(code)})
                except Exception as ex:
                    report.setdefault("script_errors",[]).append({
                        "url":url,"error":(type(ex).__name__+": "+str(ex))[:160]})
        except Exception as ex:
            report["error"]=(type(ex).__name__+": "+str(ex))[:190]
        reports.append(report)
    matches=[x for x in candidates if x["strong_timestamp_match"]]
    # HTML evidence alone is a candidate for manual source validation, not yet
    # a confirmed original graphic: no images have been downloaded or checked.
    return {"schema_version":1,"checked_utc":now.isoformat(timespec="seconds"),
            "publisher":"Icelandic Meteorological Office (IMO)",
            "provider_terms":TERMS,
            "product":"ECMWF-based North Atlantic pressure/isobar forecast, no analysed fronts",
            "pages":reports,"image_candidates":candidates[:35],
            "matching_metadata_candidates":len(matches),
            "ready_for_automated_chart_ingestion":False,
            "state":"requires_image_and_utc_verification" if any(p["state"]=="inspected" for p in reports) else "source_unreachable",
            "reason":"Actual map image and its printed Gildistími/UTC time must be independently verified. Never use crawl time or slider position."}

def main(output:Path=OUT)->dict:
    result=probe()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("IMO Atlantic probe:",result["state"],
          "assets:",len(result["image_candidates"]),
          "matching metadata:",result["matching_metadata_candidates"],flush=True)
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,default=OUT)
    args=p.parse_args()
    main(args.output)
