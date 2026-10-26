#!/usr/bin/env python3
"""Continual, conservative global synoptic source discovery.

Checks *official source pages*, not arbitrary web search and not chart images.
Records only potential original pressure-chart references found in their HTML.
New discoveries remain suggestions until independently validated UTC and rights.
Runs on each synoptic workflow schedule; previous GitHub JSON is the baseline.
"""
from __future__ import annotations
import argparse,json,re
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlparse
from urllib.request import urlopen,Request

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"data"/"synoptic_charts"/"worldwide_source_watch.json"
SOURCES={
 "jma":("Japan","https://www.jma.go.jp/bosai/weather_map/","www.jma.go.jp"),
 "kma":("Südkorea","https://www.kma.go.kr/neng/image/chart/analysis-chart.do","www.kma.go.kr"),
 "cma":("China","https://disp.nmc.cn/publish/observations/asia/dm/weatherchart-h000/basic.html","disp.nmc.cn"),
 "bom":("Australien","https://www.bom.gov.au/australia/charts/","www.bom.gov.au"),
 "metservice":("Neuseeland","https://services.metservice.com/maps-radar/maps/southwest-pacific-low-bandwidth","services.metservice.com"),
 "marinha":("Brasilien","https://pam.marinha.mil.br/sig.html","pam.marinha.mil.br"),
 "cptec":("Brasilien","https://www.cptec.inpe.br/cartas-e-boletins","www.cptec.inpe.br"),
 "hko":("Hongkong","https://www.hko.gov.hk/en/wxinfo/currwx/wxcht.htm","www.hko.gov.hk"),
 "imd":("Indien","https://rsmcnewdelhi.imd.gov.in/surface_chart00.php","rsmcnewdelhi.imd.gov.in"),
}
MAX_HTML=550_000
CHART_WORDS=re.compile(r"(?:surface|synoptic|weatherchart|isobar|as[al]s|sfc|pressure|metchart|mslp|frontal|cartas.sinoticas|wxchart|analysis)",re.I)
PIC_EXT=re.compile(r"\.(?:png|gif|webp|jpe?g|pdf)(?:$|\?)",re.I)
NUM_DATE=re.compile(r"(?<!\d)20[2-9]\d(?:[01]\d)(?:[0-3]\d)(?:[012]\d)?(?!\d)")

class Links(HTMLParser):
    def __init__(self,base,host):
        super().__init__();self.base=base;self.host=host;self.chart_links=[]
    def handle_starttag(self,tag,attrs):
        if tag not in ("img","a","source"):return
        vals=dict(attrs)
        for key in ("src","data-src","href"):
            if not vals.get(key):continue
            candidate=urljoin(self.base,vals[key])
            p=urlparse(candidate)
            if p.scheme!="https" or p.hostname!=self.host or p.username or p.password:continue
            if len(candidate)>400:continue
            # Logo/banner/image asset must not create a false discovery.
            if not PIC_EXT.search(p.path) or not CHART_WORDS.search(p.path):continue
            if candidate not in self.chart_links:self.chart_links.append(candidate)

def read_official(page:str,host:str)->str:
    p=urlparse(page)
    if p.scheme!="https" or p.hostname!=host:raise ValueError("Untrusted official provider address")
    req=Request(page,headers={"User-Agent":"ClimateDashboardDeutschland/1.0 (official-global-chart-source-watch)",
                             "Accept":"text/html"})
    with urlopen(req,timeout=15) as r:
        dest=urlparse(r.url)
        if dest.scheme!="https" or dest.hostname!=host:raise ValueError("Unexpected redirected source")
        content=r.read(MAX_HTML+1)
    if len(content)>MAX_HTML:raise ValueError("Source page exceeds read bound")
    return content.decode("utf-8","replace")

def collect(previous=None,fetch=read_official,now=None):
    now=now or datetime.now(timezone.utc)
    previous=previous if isinstance(previous,dict) else {}
    old={x["id"]:x for x in previous.get("sources",[]) if isinstance(x,dict) and isinstance(x.get("id"),str)}
    sources=[]
    for id,(country,url,host) in SOURCES.items():
        entry={"id":id,"country":country,"source_url":url,"status":"unreachable",
               "original_images_republished":False,"sync_ready":False,
               "last_checked_utc":now.isoformat(timespec="seconds"),
               "reference_image_candidates":[],"new_candidate_urls":[]}
        if id == "metservice":
            # MetService website Terms of Use restrict automated scraping/monitoring.
            # Preserve the source entry for external linking; never request its HTML.
            entry.update({"status":"excluded_provider_terms",
                          "reason":"MetService NZ web terms restrict automated monitoring and scraping; external link only"})
            sources.append(entry)
            continue
        try:
            html=fetch(url,host)
            p=Links(url,host);p.feed(html)
            candidates=p.chart_links[:18]
            known=set(old.get(id,{}).get("reference_image_candidates",[]))
            entry.update({"status":"source_html_available",
                          "reference_image_candidates":candidates,
                          "new_candidate_urls":[x for x in candidates if x not in known][:10],
                          "explicit_utc_date_in_html":bool(NUM_DATE.search(html))})
        except Exception as e:
            entry["reason"]=(type(e).__name__+": "+str(e))[:150]
        sources.append(entry)
    return {"schema_version":1,"generated_utc":now.isoformat(timespec="seconds"),
            "source_count":len(sources),"method":"bounded official-page HTML link discovery only",
            "no_image_copied":True,"no_automatic_chart_publication":True,
            "sources":sources}

def main(output=OUTPUT):
    try:prior=json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    except (OSError,ValueError):prior={}
    result=collect(previous=prior)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("World source monitor:",[(x["id"],x["status"],len(x["new_candidate_urls"])) for x in result["sources"]])

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=OUTPUT)
    main(p.parse_args().output)
