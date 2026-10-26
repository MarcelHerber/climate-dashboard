#!/usr/bin/env python3
"""Read-only checks for *official* European synoptic chart viewers.

No forecast image is copied, no run time is guessed, and no chart is admitted
to the synchronized panel. Individual provider adapters require explicit rights
and an independently verified original-image UTC date.
"""
from __future__ import annotations
import argparse, json, re
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlparse
from urllib.request import Request,urlopen

BASE=Path(__file__).resolve().parents[1]
OUTPUT=BASE/"data"/"synoptic_charts"/"europe_viewer_probe.json"
VIEWERS={
 "hnms":("Griechenland","https://emy.gr/en/marine","emy.gr"),
 "imgw_synoptic_forecast":("Polen","https://meteo.imgw.pl/cmm/?page_id=19032","meteo.imgw.pl"),
 "meteofrance":("Frankreich","https://meteofrance.com/isofronts","meteofrance.com"),
 "meteoswiss":("Schweiz","https://www.meteoschweiz.admin.ch/service-und-publikationen/applikationen/allgemeine-lage.html","www.meteoschweiz.admin.ch"),
 "smhi":("Schweden","https://www.smhi.se/klimat/klimatet-da-och-nu/manadens-vader-och-vatten-i-sverige","www.smhi.se"),
 "rhmz":("Serbien","https://hidmet.gov.rs/eng/osmotreni/analiza.php","hidmet.gov.rs"),
 "italiameteo_isobars":("Italien","https://meteohub.agenziaitaliameteo.it/app/maps/meteotiles","meteohub.agenziaitaliameteo.it"),
 "cyprus_dom_wrf":("Zypern","https://www.dom.org.cy/WRF4/00Z/01/SLP_W10m_T2m/index.html","www.dom.org.cy"),
 "meteoam":("Italien","https://www.meteoam.it/it/meteo-citta/front","www.meteoam.it"),
 "russia_hmc_analysis":("Russland","https://meteoinfo.ru/mapsynop","meteoinfo.ru"),
 "kazakhstan_synoptic":("Kasachstan","https://www.kazhydromet.kz/en/weather/sinopticheskie-karty-pogody","www.kazhydromet.kz"),
 "bosnia_fhmz_gfs":("Bosnien und Herzegowina","https://www.fhmzbih.gov.ba/latinica/METEO/GFSprognoza.php","www.fhmzbih.gov.ba"),
 "luxembourg_meteolux":("Luxemburg","https://www.meteolux.lu/fr/produits-et-services/produits-aeronautiques/cartes-du-temps-significatif/","www.meteolux.lu"),
 "jma_asas":("Japan","https://www.jma.go.jp/bosai/weather_map/","www.jma.go.jp"),
 "kma_analysis":("Südkorea","https://www.kma.go.kr/neng/image/chart/analysis-chart.do","www.kma.go.kr"),
 "cma_nmc":("China","https://www.nmc.cn/publish/observations/asia/dm/weatherchart-h000/basic.html","www.nmc.cn"),
 "bom_current":("Australien","https://www.bom.gov.au/australia/charts/","www.bom.gov.au"),
 "metservice_surface":("Neuseeland","https://www.metservice.com/maps-radar/surface-pressure/southwest-pacific","www.metservice.com"),
 "brazil_navy":("Brasilien","https://www.marinha.mil.br/chm/dados-do-smm-cartas-sinoticas/cartas-sinoticas","www.marinha.mil.br")
}
IMAGES=re.compile(r"\.(?:png|jpe?g|gif|webp)(?:$|[?#])",re.I)
DATE_VALID=re.compile(r"^20\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:Z|\+00:00)$")
MAX_RESPONSE=700_000

def known_image(value,base,hostname):
    if not value or not isinstance(value,str):return None
    url=urljoin(base,value)
    p=urlparse(url)
    if p.scheme!="https" or p.username or p.password or p.hostname!=hostname:return None
    return url if IMAGES.search(p.path) else None

class ChartMarkup(HTMLParser):
    def __init__(self,base,hostname):
        super().__init__();self.base=base;self.host=hostname
        self.images=[];self.utc_hints=[];self.text=[]
    def handle_starttag(self,tag,attributes):
        d=dict(attributes)
        if tag in ("img","a","source"):
            for key in ("src","data-src","data-original","href"):
                url=known_image(d.get(key),self.base,self.host)
                if url and url not in self.images:self.images.append(url)
        for key in ("data-valid-utc","data-valid-time","data-validity"):
            raw=d.get(key,"")
            if DATE_VALID.fullmatch(raw) and raw not in self.utc_hints:self.utc_hints.append(raw)
    def handle_data(self,text):
        if text and len(self.text)<500:self.text.append(text)

def parse_viewer(html,url,host):
    parser=ChartMarkup(url,host);parser.feed(html)
    # These are possibilities, NOT verified date/time pairs for specific maps.
    return {"same_host_image_candidates":parser.images[:12],
            "explicit_utc_attributes":parser.utc_hints[:12],
            "mentions_isobars":bool(re.search(r"isobars?|isofront|fronten|fronter|pressure|pression|frontes|synoptyczn|bodenanalyse|luftdruck|frontal", " ".join(parser.text),re.I)),
            "ready_for_image_reuse":False}

def read_provider(url,host,limit=MAX_RESPONSE):
    req=Request(url,headers={"User-Agent":"ClimateDashboardDeutschland/1.0 (official-synoptic-viewer-check)","Accept":"text/html"})
    with urlopen(req,timeout=14) as response:
        if urlparse(response.url).hostname!=host:raise ValueError("Unexpected redirect to another domain")
        raw=response.read(limit+1)
        if len(raw)>limit:raise ValueError("Source exceeds bounded viewer audit")
        return raw.decode("utf-8","replace")

def collect(fetch=read_provider,now=None):
    now=now or datetime.now(timezone.utc)
    out=[]
    for id,(country,url,host) in VIEWERS.items():
        item={"id":id,"country":country,"url":url,"state":"not_reachable",
              "checked_utc":now.isoformat(timespec="seconds"),
              "ready_for_automatic_charts":False}
        if id == "metservice_surface":
            # The provider prohibits automated website monitoring/scraping.
            # Retain this external link but do not contact its website.
            item.update({"state":"excluded_provider_terms",
                         "reason":"MetService NZ website terms restrict automated monitoring; external link only"})
            out.append(item)
            continue
        try:
            html=fetch(url,host)
            item.update(parse_viewer(html,url,host))
            item["state"]="html_inspected"
        except Exception as exc:
            item["error"]=(type(exc).__name__+": "+str(exc))[:150]
        out.append(item)
    return {"schema_version":1,"generated_utc":now.isoformat(timespec="seconds"),
            "method":"official_HTML_viewer_diagnostics_not_original_chart_timestamp_verification",
            "no_auto_ingestion":True,"sources":out}

def main(output=OUTPUT):
    result=collect()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("European chart-viewer diagnostics:",[(s["id"],s["state"]) for s in result["sources"]],flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=OUTPUT)
    main(parser.parse_args().output)
