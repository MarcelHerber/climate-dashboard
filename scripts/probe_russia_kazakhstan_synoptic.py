#!/usr/bin/env python3
"""Read-only original source audit of Russia and Kazakhstan synoptic maps.

Russia: check four specific official chart PNG files; OCR the explicitly
printed DD.MM.YYYY HH UTC date in the map footer and reject stale dates.
Kazakhstan: inspect the official dynamic viewer HTML for source file links,
script/endpoint hints and explicitly bound full validity times. A JavaScript
date picker or naked image URL is NOT an independently verified chart date.

Never store, embed or republish third-party images. Metadata only.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import re
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlparse
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"data"/"synoptic_charts"/"russia_kazakhstan_probe.json"
RUSSIAN_PAGE="https://meteoinfo.ru/mapsynop"
RUSSIAN_ORIGINALS={
  "00":"https://meteoinfo.ru/hmc-input/mapsynop/Analiz00h.png",
  "06":"https://meteoinfo.ru/hmc-input/mapsynop/Analiz06h.png",
  "12":"https://meteoinfo.ru/hmc-input/mapsynop/Analiz12h.png",
  "18":"https://meteoinfo.ru/hmc-input/mapsynop/Analiz18h.png",
}
KAZ_PAGE="https://www.kazhydromet.kz/en/weather/sinopticheskie-karty-pogody"
KAZ_HOST="www.kazhydromet.kz"
PRINTED_DATE_RE=re.compile(
  r"(?<!\d)([0-3]?\d)[.\-/]([01]?\d)[.\-/](20\d{2})"
  r"\s*(?:г\.?\s*)?([01]?\d|2[0-3])\s*(?:ч\.?|:([0-5]\d))\s*(?:ВСВ|B\s*C\s*B|UTC|GMT)\b",
  re.I,
)
# Digits + Russian month/footer are necessary to attribute dates to the
# original map label, not observation figures elsewhere on the map.
FOOTER_LABEL=re.compile(r"АНАЛИЗ|ПРИЗЕМН|Гидрометцентр|Hydromet",re.I)
MAX_PNG=8_000_000
MAX_HTML=900_000
MAX_SCRIPT=350_000
MAX_KAZ_SCRIPTS=3
KAZ_UTC=re.compile(r"20\d{2}-[01]\d-[0-3]\d[T ][012]\d:[0-5]\d(?::[0-5]\d)?(?:Z|\+00:00)\b")

def checked_url(url:str,expected_host:str)->bool:
    p=urlparse(url)
    return p.scheme=="https" and p.hostname==expected_host and not p.username and not p.password

def printed_russia_time(text:str,run:str,now:datetime)->datetime:
    if run not in RUSSIAN_ORIGINALS:raise ValueError("Unknown Russian map")
    if not FOOTER_LABEL.search(text):
        raise ValueError("Russian synoptic chart footer not recognized")
    hit=PRINTED_DATE_RE.search(text)
    if not hit:raise ValueError("Complete printed DD.MM.YYYY HH UTC not found in chart footer")
    day,month,year,hour,minutes=hit.groups()
    dt=datetime(int(year),int(month),int(day),int(hour),int(minutes or 0),tzinfo=timezone.utc)
    if dt.hour!=int(run) or dt.minute!=0:raise ValueError("Printed UTC hour differs from image product")
    # Record old dates without claiming they are current; deliberately return
    # stale as an ordinary classification rather than ingesting the image.
    if dt>now+timedelta(hours=2):raise ValueError("Printed chart is future-dated")
    return dt

def russian_freshness(dt:datetime,now:datetime)->str:
    if dt>now+timedelta(hours=2):return "future_dated"
    if dt<now-timedelta(hours=40):return "stale"
    return "current_within_40h"

def read_binary(url:str,expected_host:str,limit:int)->bytes:
    if not checked_url(url,expected_host):raise ValueError("Unrecognized source host")
    request=Request(url,headers={"User-Agent":"ClimateDashboardDeutschland/1.0 (source-date-verification)",
                                 "Accept":"image/png,image/*,text/html"})
    with urlopen(request,timeout=18) as response:
        if not checked_url(response.url,expected_host):
            raise ValueError("Redirect to unapproved host")
        if response.url!=url:raise ValueError("Unexpected redirected chart address")
        raw=response.read(limit+1)
        if len(raw)>limit:raise ValueError("Source response exceeds byte limit")
        return raw

def read_russian_original(url:str)->bytes:
    if url not in RUSSIAN_ORIGINALS.values():raise ValueError("Image URL not in official allowlist")
    data=read_binary(url,"meteoinfo.ru",MAX_PNG)
    if not 18000<=len(data)<=MAX_PNG or data[:8]!=b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not an official PNG image")
    return data

def russian_ocr(data:bytes)->tuple[str,list[int]]:
    from PIL import Image,ImageOps,ImageEnhance
    import pytesseract
    with Image.open(io.BytesIO(data)) as im:
        im.seek(0);im.load()
        if not 700<=im.width<=4000 or not 450<=im.height<=2700:
            raise ValueError("Unexpected Russian analysis chart dimensions")
        # See original: white DD.MM.YYYY footer in lower-left corner.
        crop=im.crop((0,max(0,int(im.height*.82)),int(im.width*.40),im.height))
        crop=ImageEnhance.Contrast(ImageOps.autocontrast(crop.convert("L"))).enhance(1.8)
        crop=crop.resize((crop.width*3,crop.height*3))
        value=pytesseract.image_to_string(crop,lang="rus+eng",config="--psm 6")
        return value[:550],[im.width,im.height]

class ViewerHTML(HTMLParser):
    def __init__(self,url:str):
        super().__init__();self.url=url;self.script_urls=[];self.image_urls=[];self.inline=[]
        self._inside_script=False
    def handle_starttag(self,tag,attrs):
        attributes=dict(attrs)
        if tag=="script":
            uri=attributes.get("src")
            if uri:
                address=urljoin(self.url,uri)
                if checked_url(address,KAZ_HOST) and address not in self.script_urls:
                    self.script_urls.append(address)
            else:self._inside_script=True
        if tag in ("img","a","source"):
            for key in ("src","data-src","href"):
                v=attributes.get(key)
                if not v:continue
                address=urljoin(self.url,v)
                if checked_url(address,KAZ_HOST) and re.search(r"\.(?:png|jpg|jpeg|gif|webp)(?:$|[?])",address,re.I):
                    if address not in self.image_urls:self.image_urls.append(address)
    def handle_endtag(self,tag):
        if tag=="script":self._inside_script=False
    def handle_data(self,data):
        if self._inside_script and len(self.inline)<12:self.inline.append(data[:45000])

KAZ_HINTS=re.compile(r"(?:synoptic|sinoptich|map[_/\-]?(?:file|date|time|source)|source[_\-]?file|\\.pdf|\\.(?:png|jpg|gif))",re.I)
URL_HINTS=re.compile(r"""(?:(?:https?://[^"'\s<>]+)|(?:/(?:api|storage|uploads|files|weather)/[^"'\s<>]{4,180}))""",re.I)

def inspect_kaz_html(html:str,page:str=KAZ_PAGE)->dict:
    if page!=KAZ_PAGE:raise ValueError("Wrong Kazhydromet viewer")
    parser=ViewerHTML(page);parser.feed(html)
    snippets=[]
    for raw in parser.inline:
        for m in KAZ_HINTS.finditer(raw):
            snippet=raw[max(0,m.start()-65):m.end()+145]
            cleaned=re.sub(r"\s+"," ",snippet)[:215]
            if cleaned not in snippets:snippets.append(cleaned)
            if len(snippets)>=10:break
    return {"same_host_image_reference_count":len(parser.image_urls),
      "same_host_script_reference_count":len(parser.script_urls),
      "script_urls":parser.script_urls[:20],
      "javascript_clues":snippets[:10],
      "embedded_full_utc_candidates":list(dict.fromkeys(KAZ_UTC.findall(html)))[:8],
      "chart_image_utc_verified":False,
      "image_reuse_permitted":False}

def scan_kaz_scripts(report:dict,fetch=read_binary)->dict:
    hints=[]
    for url in report["script_urls"][:MAX_KAZ_SCRIPTS]:
        try:
            raw=fetch(url,KAZ_HOST,MAX_SCRIPT)
            decoded=raw.decode("utf-8","replace")
            for m in KAZ_HINTS.finditer(decoded):
                hint=re.sub(r"\s+"," ",decoded[max(0,m.start()-50):m.end()+90])[:145]
                if hint not in hints:hints.append(hint)
                if len(hints)>=12:break
        except Exception:pass
    # URLs and scripts are diagnostic leads, never proof of a chart/file timestamp.
    report["script_inspection_hints"]=hints[:12]
    return report

def inspect(now:datetime|None=None,russian_fetch=read_russian_original,
            russian_image_reader=russian_ocr,kaz_fetch=None,fetch_kaz_scripts=False)->dict:
    now=now or datetime.now(timezone.utc)
    russian=[]
    for run,url in RUSSIAN_ORIGINALS.items():
        item={"slot_utc":run,"url":url,"state":"unverified",
              "image_reuse_permitted":False}
        try:
            raw=russian_fetch(url)
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as png:png.verify()
            txt,dims=russian_image_reader(raw)
            item["dimensions"]=dims
            item["footer_excerpt"]=re.sub(r"\s+"," ",txt).strip()[:260]
            dt=printed_russia_time(txt,run,now)
            item["printed_valid_utc"]=dt.isoformat(timespec="minutes")
            item["state"]=russian_freshness(dt,now)
        except Exception as e:
            item["reason"]=(type(e).__name__+": "+str(e))[:180]
        russian.append(item)
    kaz={"state":"unverified","page":KAZ_PAGE,"chart_image_utc_verified":False,
         "image_reuse_permitted":False}
    try:
        if kaz_fetch is None:
            raw=read_binary(KAZ_PAGE,KAZ_HOST,MAX_HTML)
            html=raw.decode("utf-8","replace")
        else:html=kaz_fetch(KAZ_PAGE)
        kaz.update(inspect_kaz_html(html))
        kaz["state"]="viewer_html_inspected"
        if fetch_kaz_scripts:scan_kaz_scripts(kaz)
    except Exception as e:kaz["reason"]=(type(e).__name__+": "+str(e))[:180]
    return {"schema_version":1,"generated_utc":now.isoformat(timespec="seconds"),
       "russia":{"source_page":RUSSIAN_PAGE,"copyright":"© Hydrometcenter Russia; reuse not verified",
                 "image_reuse_permitted":False,"records":russian},
       "kazakhstan":kaz,
       "no_images_persisted":True,
       "ready_for_automatic_image_reuse":False,
       "method":"Russian chart footer OCR + Kazhydromet dynamic viewer source diagnostics; not an image reuse license"}

def main(output:Path=OUTPUT):
    data=inspect(fetch_kaz_scripts=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Russia chart dates:",[(x["slot_utc"],x["state"],x.get("printed_valid_utc")) for x in data["russia"]["records"]],flush=True)
    print("Kazakhstan viewer:",data["kazakhstan"]["state"],"scripts",data["kazakhstan"].get("same_host_script_reference_count",0),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,default=OUTPUT)
    main(p.parse_args().output)
