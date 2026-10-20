#!/usr/bin/env python3
"""Non-redistributing audit of Cyprus Department of Meteorology WRF isobar GIFs.

Run tags (00Z/12Z), filenames (d01-000.gif), image order, and retrieval time
are NOT sufficient to establish a valid_utc. Independently parse a printed
model initiation date + valid date + explicit UTC label before reporting
verified times. Images are read only in memory and never copied or published.
Image reuse is NEVER enabled by this probe.
"""
from __future__ import annotations
import argparse
import io
import json
import re
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlparse
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"data"/"synoptic_charts"/"cyprus_wrf_probe.json"
HOST="www.dom.org.cy"
PAGES={run:f"https://{HOST}/WRF4/{run}Z/01/SLP_W10m_T2m/index.html" for run in ("00","12")}
ABOUT=f"https://{HOST}/about.html"
MAP_RE=re.compile(r"^/WRF4/(00|12)Z/01/SLP_W10m_T2m/SLP_W10m_T2m_d01-(\d{3})\.gif$")
SAMPLE_INDICES=(0,6)
MAX_HTML=500_000
MAX_GIF=8_000_000

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__();self.references=[]
    def handle_starttag(self,tag,attrs):
        if tag not in ("img","a","source"):return
        d=dict(attrs)
        for key in ("src","data-src","href"):
            if d.get(key):self.references.append(d[key])

def frames_from_html(html:str,page:str,run:str)->list[dict]:
    if run not in PAGES or page!=PAGES[run]:raise ValueError("Unknown official model run URL")
    parser=LinkParser();parser.feed(html)
    found={}
    for ref in parser.references:
        u=urljoin(page,ref);parsed=urlparse(u)
        if parsed.scheme!="https" or parsed.hostname!=HOST or parsed.username or parsed.password or parsed.query:
            continue
        match=MAP_RE.fullmatch(parsed.path)
        if match and match.group(1)==run:
            frame=int(match.group(2))
            if frame<121 and frame not in found:
                found[frame]={"frame":frame,"url":u}
    return [found[k] for k in sorted(found)]

# Support clear YYYY-MM-DD HH:MM UTC and DD.MM.YYYY HH:MM UTC image labels.
DATE_RE=re.compile(r"(?<!\d)(20\d{2}[-./][01]?\d[-./][0-3]?\d|[0-3]?\d[-./][01]?\d[-./]20\d{2})"
                   r"[T _]+([01]?\d|2[0-3])[:.]([0-5]\d)(?::[0-5]\d)?\s*(UTC|Z)\b",re.I)
INIT_RE=re.compile(r"\b(?:init(?:ial(?:ization|isation)?)?|model\s*run|start)\b\s*(?:time\s*)?[:=\s]{0,12}",re.I)
VALID_RE=re.compile(r"\b(?:valid(?:ity)?|forecast\s*valid|verification|vt)\b\s*(?:time\s*)?[:=\s]{0,12}",re.I)

def parse_full_utc(fragment:str)->datetime|None:
    m=DATE_RE.search(fragment or "")
    if not m:return None
    raw,hour,minute,_=m.groups()
    raw=raw.replace("/","-").replace(".","-")
    try:
        if raw[:4].isdigit() and raw[:4].startswith("20"):
            year,month,day=map(int,raw.split("-"))
        else:
            day,month,year=map(int,raw.split("-"))
        return datetime(year,month,day,int(hour),int(minute),tzinfo=timezone.utc)
    except ValueError:return None

def parse_printed_times(text:str,run:str,now:datetime)->dict:
    """Only accept image-printed, explicitly labeled INIT and VALID UTC dates."""
    if run not in PAGES:raise ValueError("Unknown WRF run")
    values={}
    for key,pattern in (("run_utc",INIT_RE),("valid_utc",VALID_RE)):
        for hit in pattern.finditer(text):
            dt=parse_full_utc(text[hit.end():hit.end()+90])
            if dt:
                values[key]=dt
                break
    if len(values)!=2:raise ValueError("Missing printed INIT or VALID complete UTC date")
    init,valid=values["run_utc"],values["valid_utc"]
    if init.hour!=int(run) or init.minute!=0:
        raise ValueError("Image-printed initialization does not match official 00/12 model run")
    if not now-timedelta(hours=72)<=init<=now+timedelta(hours=4):
        raise ValueError("Image-printed initialization is stale or unexpectedly future")
    if not init<=valid<=init+timedelta(hours=150):
        raise ValueError("Invalid or unreasonably distant printed WRF validity")
    return {name:dt.isoformat(timespec="minutes") for name,dt in values.items()}

def read_html(url:str)->str:
    if url not in PAGES.values():raise ValueError("Unrecognized Cyprus viewer URL")
    request=Request(url,headers={"User-Agent":"ClimateDashboardDeutschland/1.0 (Cyprus-isobar-timestamp-check)",
                                 "Accept":"text/html"})
    with urlopen(request,timeout=17) as response:
        if response.url!=url:raise ValueError("Unexpected HTML redirect")
        raw=response.read(MAX_HTML+1)
    if len(raw)>MAX_HTML:raise ValueError("Cyprus viewer HTML exceeds limit")
    return raw.decode("utf-8","replace")

def read_gif(url:str)->bytes:
    parsed=urlparse(url)
    if parsed.scheme!="https" or parsed.hostname!=HOST or not MAP_RE.fullmatch(parsed.path):
        raise ValueError("Unrecognized Cyprus original chart URL")
    req=Request(url,headers={"User-Agent":"ClimateDashboardDeutschland/1.0 (Cyprus-isobar-timestamp-check)",
                             "Accept":"image/gif"})
    with urlopen(req,timeout=20) as response:
        if response.url!=url:raise ValueError("Unexpected original-image redirect")
        raw=response.read(MAX_GIF+1)
    if not (15_000<=len(raw)<=MAX_GIF and raw[:6] in (b"GIF87a",b"GIF89a")):
        raise ValueError("Cyprus original GIF missing, oversized or invalid")
    return raw

def read_image_clock(image:bytes)->tuple[str,list[int]]:
    from PIL import Image,ImageEnhance,ImageOps
    import pytesseract
    with Image.open(io.BytesIO(image)) as im:
        im.seek(0)
        im.load()
        if not(600<=im.width<=6000 and 350<=im.height<=4500):
            raise ValueError("Implausible WRF synoptic GIF dimensions")
        texts=[]
        for y0,y1 in ((0,max(80,int(im.height*.22))),
                      (max(0,int(im.height*.75)),im.height)):
            part=ImageOps.autocontrast(im.crop((0,y0,im.width,y1)).convert("L"))
            part=ImageEnhance.Contrast(part).enhance(1.7)
            part=part.resize((part.width*2,part.height*2))
            texts.append(pytesseract.image_to_string(part,lang="eng",config="--psm 6"))
        return "\n".join(texts)[:1000],[im.width,im.height]

def check(now:datetime|None=None,html_fetch=read_html,image_fetch=read_gif,
          image_reader=read_image_clock)->dict:
    now=now or datetime.now(timezone.utc)
    reports=[]
    for run,page in PAGES.items():
        info={"run_hour_utc":run,"page":page,"state":"unreachable","frame_count":0,
              "sample_maps":[],"ready_for_image_reuse":False}
        try:
            html=html_fetch(page)
            frames=frames_from_html(html,page,run)
            info["frame_count"]=len(frames)
            info["state"]="html_inspected" if frames else "no_verified_gif_links"
            for frame_no in SAMPLE_INDICES:
                sample=next((f for f in frames if f["frame"]==frame_no),None)
                if not sample:continue
                item={"frame":frame_no,"url":sample["url"],"state":"timestamp_unverified"}
                try:
                    raw=image_fetch(sample["url"])
                    from PIL import Image
                    with Image.open(io.BytesIO(raw)) as picture:picture.verify()
                    caption,dimensions=image_reader(raw)
                    item["image_size_px"]=dimensions
                    item["printed_header_excerpt"]=re.sub(r"\s+"," ",caption).strip()[:390]
                    try:
                        item.update(parse_printed_times(caption,run,now))
                        item["state"]="printed_init_and_valid_utc_verified"
                    except ValueError as ex:
                        item["reason"]=str(ex)
                except Exception as ex:
                    item["reason"]=(type(ex).__name__+": "+str(ex))[:150]
                info["sample_maps"].append(item)
        except Exception as ex:
            info["reason"]=(type(ex).__name__+": "+str(ex))[:160]
        reports.append(info)
    return {
       "schema_version":1,
       "generated_utc":now.isoformat(timespec="seconds"),
       "publisher":"Cyprus Department of Meteorology",
       "product":"WRF v4.1.3 8-km Eastern Mediterranean sea-level pressure, 10-m wind, 2-m temperature; no fronts",
       "about":ABOUT,
       "usage":"Raw numerical model guidance, not the official weather forecast. No chart-image republication permission established.",
       "model_run_paths_checked":["00Z","12Z"],
       "reports":reports,
       "no_images_persisted":True,
       "ready_for_automatic_image_reuse":False,
       "reason":"Printed exact WRF initialization and validity UTC plus chart-specific republication rights needed. GIF sequence numbers are not UTC timestamps.",
    }

def main(output:Path=OUTPUT):
    report=check()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Cyprus WRF original GIF audit:",[(x["run_hour_utc"],x["state"],x["frame_count"],
            [s["state"] for s in x["sample_maps"]]) for x in report["reports"]],flush=True)
    return report

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=OUTPUT)
    main(parser.parse_args().output)
