#!/usr/bin/env python3
"""Publish real, timestamped synoptic front charts from permitted public sources.

DWD: official Open Data surface analysis PNGs.
AEMET: front maps with attribution.
NOAA OPC: dated East Atlantic surface analyses, NWS public-domain charts.
Do NOT scrape Met Office: their website explicitly forbids automated scraping
and direct embedding of image files. Other services are links until verified.
"""
from __future__ import annotations
import argparse
import io
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"synoptic_charts"
DWD_INDEX="https://opendata.dwd.de/weather/charts/analysis/"
AEMET_PAGE="https://www.aemet.es/es/eltiempo/prediccion/mapa_frentes"
KNMI_PAGE="https://www.knmi.nl/nederland-nu/weer/waarschuwingen-en-verwachtingen/weerkaarten/"
OPC_ARCHIVE="https://ftp.opc.ncep.noaa.gov/ncdc/"
OPC_RE=re.compile(r"^atle_sfcanal_(00|06|12|18)\.([0-9]{8})([0-9]{2})\.gif$",re.I)
OPC_FULL_RE=re.compile(r"^atl00_sfcfcst_(00|06|12|18)\.([0-9]{8})([0-9]{2})\.gif$",re.I)
OPC_WEST_RE=re.compile(r"^atlw_sfcanal_(00|06|12|18)\.([0-9]{8})([0-9]{2})\.gif$",re.I)
OPC_24_RE=re.compile(r"^watl24_sfcfcst_(00|12)\.([0-9]{8})([0-9]{2})\.gif$",re.I)
OPC_48_RE=re.compile(r"^atl48_sfcfcst_(00|12)\.([0-9]{8})([0-9]{2})\.gif$",re.I)
OPC_96_RE=re.compile(r"^atl96_sfcfcst_(12)\.([0-9]{8})([0-9]{2})\.gif$",re.I)
DWD_RE=re.compile(r"_([0-9]{12})_WV12\.png$",re.I)
AEMET_RE=re.compile(r"([0-9]{10})\+([0-9]{3})_ww_[a-z0-9]+\.gif$",re.I)
SOURCES=[
 {"id":"dwd","name":"DWD","country":"Deutschland","url":DWD_INDEX,
  "type":"auto","license":"DWD Open Data · Quelle: Deutscher Wetterdienst"},
 {"id":"aemet","name":"AEMET","country":"Spanien","url":AEMET_PAGE,
  "type":"auto","license":"© AEMET · Verwendung unter Quellenangabe erlaubt"},
 {"id":"noaa_opc","name":"NOAA OPC · Ostatlantik","country":"USA",
  "url":"https://ocean.weather.gov/Atl_tab.php","type":"auto",
  "license":"NOAA/NWS public domain · © keine Schutzrechtsbehauptung, NOAA-Quellenangabe"},
 {"id":"noaa_full","name":"NOAA OPC · Gesamtatlantik (gleicher Dienst)","country":"USA",
  "url":"https://ocean.weather.gov/Atl_tab.php","type":"auto",
  "license":"NOAA/NWS Public Domain; zweiter Kartenausschnitt desselben Wetterdienstes"},
 {"id":"noaa_west","name":"NOAA OPC · Westatlantik","country":"USA",
  "url":"https://ocean.weather.gov/Loops/NCDC_names.php","type":"auto",
  "license":"NOAA/NWS Public Domain · weitere Region desselben Wetterdienstes"},
 {"id":"noaa_24","name":"NOAA OPC · Westatlantik +24 h","country":"USA",
  "url":"https://ocean.weather.gov/Loops/NCDC_names.php","type":"auto",
  "license":"NOAA/NWS Public Domain · 24-h-Prognose"},
 {"id":"noaa_48","name":"NOAA OPC · Nordatlantik +48 h","country":"USA",
  "url":"https://ocean.weather.gov/Loops/NCDC_names.php","type":"auto",
  "license":"NOAA/NWS Public Domain · 48-h-Prognose"},
 {"id":"noaa_96","name":"NOAA OPC · Nordatlantik +96 h","country":"USA",
  "url":"https://ocean.weather.gov/Loops/NCDC_names.php","type":"auto",
  "license":"NOAA/NWS Public Domain · 96-h-Prognose"},
 {"id":"chmi","name":"ČHMÚ · Atlantik/Europa","country":"Tschechien",
  "url":"https://www.chmi.cz/predpoved-pocasi/synopticka-situace",
  "type":"auto","license":"© ČHMÚ · CC BY 4.0 · Bild aus Original-API, ins WebP-Format konvertiert"},
 {"id":"eccc","name":"ECCC · Nordhemisphäre","country":"Kanada",
  "url":"https://weather.gc.ca/analysis/index_e.html","type":"external",
  "license":"Offizielle Nordhemisphären-Bodenanalyse; derzeit kein verlässlich datierter Bildlink"},
 {"id":"metoffice","name":"Met Office","country":"Großbritannien",
  "url":"https://weather.metoffice.gov.uk/maps-and-charts/surface-pressure",
  "type":"external","license":"Nur Quellenseite verlinkt; Bilder nicht eingebettet"},
 {"id":"dmi","name":"DMI · Frontkort","country":"Dänemark",
  "url":"https://www.dmi.dk/vejret/frontkort","type":"external",
  "license":"Originale Analyse und Prognose direkt bei DMI; Bildnutzungsrechte für fertige Frontkort noch nicht eindeutig"},
 {"id":"dhmz","name":"DHMZ · Europa","country":"Kroatien",
  "url":"https://meteo.hr/prognoze_e.php?param=web_fronte_sutra12&section=prognoze_model",
  "type":"auto","license":"Izvor: DHMZ · Wiederverwendung mit Quellenangabe; eingebunden nur bei überprüftem gültigen Druckdatum"},
 {"id":"fmi","name":"FMI · Europa-Wetterlagenanalyse","country":"Finnland",
  "url":"https://en.ilmatieteenlaitos.fi/weather-in-europe","type":"external",
  "license":"Amtliche meteorologisch interpretierte Europakarte; Kartenbild und UTC-Zeit nicht automatisch validiert"},
 {"id":"meteoam","name":"Meteo AM · Suolo","country":"Italien",
  "url":"https://www.meteoam.it/it/suolo","type":"external",
  "license":"Offizielle Suolo-Kartenseite; JavaScript-Karte und Aktualität noch nicht automatisch validiert"},
 {"id":"mgm","name":"MGM · Sinoptik Haritalar","country":"Türkei",
  "url":"https://hezarfen.mgm.gov.tr/HzUsr/SinHarita/Default.aspx","type":"external",
  "license":"Amtlicher Synoptikkarten-Bereich; aktuelles Kartenbild bei Prüfung nicht nachgewiesen"},
 {"id":"meteociel","name":"Météociel · Fronten und Analyse","country":"Frankreich",
  "url":"https://www.meteociel.fr/fronts/index.php",
  "type":"external","license":"Direkte Kartenansicht mit Frontenanalyse und Prognose; Drittanbieter, keine Bildübernahme ohne Rechteprüfung"},
 {"id":"hungaromet","name":"HungaroMet · Fronten (Direktbild nicht bestätigt)","country":"Ungarn",
  "url":"https://kriter.met.hu/idojaras/aktualis_idojaras/napijelentes/main.php?ful=front",
  "type":"external","license":"Angebot einer Europa-Frontenkarte dokumentiert; aktueller Viewer beim Abruf nicht bestätigt"},
 {"id":"metie","name":"Met Éireann","country":"Irland",
  "url":"https://www.met.ie/latest-reports/surface-analysis",
  "type":"external","license":"Met Éireann untersagt automatisiertes Kopieren der Website; Originalanalyse nur als Link"},
 {"id":"metno","name":"MET Norway · kein verifizierter Direktlink","country":"Norwegen",
  "url":"https://www.met.no/en/weather-and-climate",
  "type":"external","license":"Synoptische Analysen in offiziellen Berichten; kein verifizierter automatischer Live-Bildfeed"},
 {"id":"imgw","name":"IMGW · kein verifizierter Direktlink","country":"Polen",
  "url":"https://meteo.imgw.pl/",
  "type":"external","license":"Amtliche synoptische Europakarten; kein freigegebener automatischer Live-Bildabruf"},
 {"id":"knmi","name":"KNMI · Niederlande","country":"Niederlande",
  "url":KNMI_PAGE,"type":"auto","license":"KNMI CC0 sofern kein bildbezogener Rechtevorbehalt; Quelle: KNMI"},
 {"id":"knmi_archiv","name":"KNMI · Wetterkartenarchiv seit 2003","country":"Niederlande",
  "url":"https://www.knmi.nl/nederland-nu/klimatologie/daggegevens/weerkaarten",
  "type":"external","license":"Historisches Archiv amtlicher Karten; nur externe Verlinkung"},
 {"id":"kmi","name":"KMI · Belgien","country":"Belgien",
  "url":"https://www.meteo.be/de/wetter/vorhersage/frontenkarten",
  "type":"external","license":"Amtliche europäische Frontenprognosen; zurzeit nur externe Verlinkung"},
 {"id":"smhi","name":"SMHI · tägliche Wetteranalysen","country":"Schweden",
  "url":"https://www.smhi.se/blogg/blogg/2026-09-02-arkiv-med-dagliga-vaderkartor",
  "type":"external","license":"Offizielles Tageskartenarchiv in den SMHI-Monatsrückblicken; nur externe Verlinkung"},
 {"id":"noaa_wpc","name":"NOAA WPC · Nordamerika Analyse/Prognosen","country":"USA",
  "url":"https://www.weather.gov/forecastmaps",
  "type":"external","license":"Amtliche Bodenanalysen sowie 12-, 24-, 36- und 48-h-Prognosen; externer Link"},
 {"id":"noaa_pacific","name":"NOAA OPC · Pazifik","country":"USA",
  "url":"https://ocean.weather.gov/Pac_tab.php",
  "type":"external","license":"Amtliche Pazifik-Bodenanalysen und Prognosen; externer Link"},
 {"id":"imo","name":"IMO","country":"Island",
  "url":"https://en.vedur.is/weather/shipping/atlantic/",
  "type":"external","license":"Quellenseite verlinkt, Bildrechte nicht pauschal geklärt"}
]

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs=[]
    def handle_starttag(self,tag,attrs):
        props=dict(attrs)
        if tag in ("a","img","source"):
            for key in ("href","src","data-src","data-original"):
                val=props.get(key)
                if val:self.refs.append(val)


def timestamp(value,fmt):
    return datetime.strptime(value,fmt).replace(tzinfo=timezone.utc)


def extract_dwd(html, now):
    parser=Links();parser.feed(html)
    records={}
    for href in parser.refs:
        url=urljoin(DWD_INDEX,href)
        parsed=urlparse(url)
        name=unquote(parsed.path.rsplit("/",1)[-1])
        if parsed.hostname not in ("opendata.dwd.de","opendatat.dwd.de"):
            continue
        if "ana_bwkman_dwdna_" not in name:
            continue
        match=DWD_RE.search(name)
        if not match:continue
        valid=timestamp(match.group(1),"%Y%m%d%H%M")
        if not (now-timedelta(hours=72)<=valid<=now+timedelta(hours=2)):
            continue
        key=valid.isoformat(timespec="minutes")
        # Pick standard colour product only; ignore variants/duplicate URLs.
        records.setdefault(key,{"source_id":"dwd","kind":"Analyse",
            "valid_utc":key,"issued_utc":None,"source_url":url,
            "source_page":DWD_INDEX,"credit":"© Deutscher Wetterdienst (DWD)"})
    return sorted(records.values(),key=lambda x:x["valid_utc"],reverse=True)[:12]


def extract_aemet(html,now):
    parser=Links();parser.feed(html)
    records={}
    for href in parser.refs:
        url=urljoin(AEMET_PAGE,href)
        parsed=urlparse(url)
        name=unquote(parsed.path.rsplit("/",1)[-1])
        if parsed.hostname not in ("www.aemet.es","aemet.es"):
            continue
        if "/mapa_frentes/" not in parsed.path:
            continue
        match=AEMET_RE.search(name)
        if not match:continue
        run=timestamp(match.group(1),"%Y%m%d%H")
        lead=int(match.group(2))
        valid=run+timedelta(hours=lead)
        if not (now-timedelta(hours=48)<=valid<=now+timedelta(hours=96)) or lead>96:
            continue
        key=valid.isoformat(timespec="minutes")
        record={"source_id":"aemet","kind":"Analyse" if lead==0 else "Prognose",
            "valid_utc":key,"issued_utc":run.isoformat(timespec="minutes"),
            "forecast_hours":lead,"source_url":url,"source_page":AEMET_PAGE,
            "credit":"© AEMET · Agencia Estatal de Meteorología"}
        # Duplicate valid hour: prefer more recently issued charts from the source.
        if key not in records or record["issued_utc"]>records[key]["issued_utc"]:
            records[key]=record
    return sorted(records.values(),key=lambda x:x["valid_utc"])[:8]


def _extract_opc_type(html, now, regex, source_id, credit, label):
    """NOAA NCDC filename: prefix HH=valid hour, suffix date and issue hour."""
    parser=Links();parser.feed(html)
    records={}
    for href in parser.refs:
        url=urljoin(OPC_ARCHIVE,href)
        parsed=urlparse(url)
        name=unquote(parsed.path.rsplit("/",1)[-1])
        if parsed.hostname not in ("ftp.opc.ncep.noaa.gov","ftp.ocean.weather.gov"):
            continue
        match=regex.fullmatch(name)
        if not match:continue
        valid=timestamp(match.group(2)+match.group(1),"%Y%m%d%H")
        issue=timestamp(match.group(2)+match.group(3),"%Y%m%d%H")
        if not (now-timedelta(hours=60)<=valid<=now+timedelta(hours=1)):
            continue
        if issue<valid or issue>valid+timedelta(hours=9):
            continue
        key=valid.isoformat(timespec="minutes")
        record={"source_id":source_id,"kind":label,"valid_utc":key,
            "issued_utc":issue.isoformat(timespec="minutes"),
            "source_url":url,"source_page":"https://ocean.weather.gov/Atl_tab.php",
            "credit":credit,"publisher_id":"noaa"}
        if key not in records or record["issued_utc"]>records[key]["issued_utc"]:
            records[key]=record
    return sorted(records.values(),key=lambda x:x["valid_utc"],reverse=True)[:8]


def extract_opc(html, now):
    """Northeast Atlantic chart: actual validity from suffix date + prefix HH."""
    return _extract_opc_type(html,now,OPC_RE,"noaa_opc",
        "NOAA/NWS · Ocean Prediction Center (Ostatlantik)","Analyse")


def extract_opc_full(html, now):
    """Full Atlantic 0-hour surface product, SAME NWS office as East Atlantic."""
    return _extract_opc_type(html,now,OPC_FULL_RE,"noaa_full",
        "NOAA/NWS · Ocean Prediction Center (Gesamtatlantik)","0-h-Bodenkarte")


def extract_opc_west(html,now):
    """Northwest Atlantic original surface analysis, same NOAA/NWS publisher."""
    return _extract_opc_type(html,now,OPC_WEST_RE,"noaa_west",
        "NOAA/NWS · Ocean Prediction Center (Westatlantik)","Analyse")


def _extract_opc_forecast(html,now,pattern,source_id,lead,region):
    """Provider's filename prefix gives run UTC hour, suffix date gives
    INITIALIZATION DATE + issued hour. A 48-hour chart valid time is
    run calendar date/hour +48h; never use the suffix date as valid day.
    """
    parser=Links();parser.feed(html)
    data={}
    for href in parser.refs:
        url=urljoin(OPC_ARCHIVE,href)
        parsed=urlparse(url)
        if parsed.hostname not in ("ftp.opc.ncep.noaa.gov","ftp.ocean.weather.gov"):
            continue
        name=unquote(parsed.path.rsplit("/",1)[-1])
        match=pattern.fullmatch(name)
        if not match:continue
        run=timestamp(match.group(2)+match.group(1),"%Y%m%d%H")
        issued=timestamp(match.group(2)+match.group(3),"%Y%m%d%H")
        if not (run<=issued<=run+timedelta(hours=10)):
            continue
        valid=run+timedelta(hours=lead)
        if not (now-timedelta(hours=24)<=valid<=now+timedelta(hours=125)):
            continue
        key=valid.isoformat(timespec="minutes")
        entry={"source_id":source_id,"publisher_id":"noaa",
            "kind":"Prognose","forecast_hours":lead,
            "valid_utc":key,"issued_utc":issued.isoformat(timespec="minutes"),
            "run_utc":run.isoformat(timespec="minutes"),
            "source_url":url,
            "source_page":"https://ocean.weather.gov/Loops/NCDC_names.php",
            "credit":"NOAA/NWS · Ocean Prediction Center ("+region+")"}
        if key not in data or entry["issued_utc"]>data[key]["issued_utc"]:
            data[key]=entry
    return sorted(data.values(),key=lambda x:x["valid_utc"])[:6]


def extract_opc_24(html,now):
    return _extract_opc_forecast(html,now,OPC_24_RE,"noaa_24",24,"Westatlantik +24 h")


def extract_opc_48(html,now):
    return _extract_opc_forecast(html,now,OPC_48_RE,"noaa_48",48,"Nordatlantik +48 h")


def extract_opc_96(html,now):
    return _extract_opc_forecast(html,now,OPC_96_RE,"noaa_96",96,"Nordatlantik +96 h")



class KNMILinks(HTMLParser):
    """Read validity only from the provider's explicitly dated anchor label."""
    def __init__(self):
        super().__init__()
        self.href=None
        self.parts=[]
        self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a":
            self.href=dict(attrs).get("href")
            self.parts=[]
    def handle_data(self,data):
        if self.href is not None:
            self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=="a" and self.href is not None:
            self.links.append((self.href," ".join(self.parts).strip()))
            self.href=None
            self.parts=[]

def extract_knmi(html,now):
    p=KNMILinks()
    p.feed(html)
    records={}
    for href,label in p.links:
        match=re.search(r"(Analyse|Prognose\s+voor)\s+.*?([0-9]{2})-([0-9]{2})-([0-9]{4})\s+([0-9]{2})\s*UTC",label,re.I)
        if not match:continue
        url=urljoin(KNMI_PAGE,href)
        parsed=urlparse(url)
        if parsed.hostname!="cdn.knmi.nl" or not re.fullmatch(
            r"/knmi/map/page/weer/waarschuwingen_verwachtingen/weerkaarten/[AP]L[0-9]{4}_large\.gif",
            parsed.path,re.I):continue
        valid=timestamp("".join((match.group(4),match.group(3),match.group(2),match.group(5))),"%Y%m%d%H")
        if not(now-timedelta(hours=72)<=valid<=now+timedelta(hours=96)):continue
        kind="Analyse" if match.group(1).lower()=="analyse" else "Prognose"
        filename=parsed.path.rsplit("/",1)[-1]
        if (filename.startswith("AL"))!=(kind=="Analyse"):continue
        if filename[2:6]!=valid.strftime("%d%H"):continue
        key=valid.isoformat(timespec="minutes")
        records[key]={"source_id":"knmi","publisher_id":"knmi","kind":kind,
                      "valid_utc":key,"issued_utc":None,"source_url":url,
                      "source_page":KNMI_PAGE,"credit":"Quelle: KNMI · CC0, soweit keine Ausnahme"}
    return sorted(records.values(),key=lambda x:x["valid_utc"])[:8]

def download(url,timeout=30,limit=9_000_000):
    request=Request(url,headers={
        "User-Agent":"ClimateDashboardDeutschland/1.0 (synoptic-source-monitor)",
        "Accept":"image/avif,image/webp,image/png,image/gif,image/*;q=0.8,text/html;q=0.7,*/*;q=0.5",
        "Accept-Language":"de-DE,de;q=0.9,en;q=0.7",
    })
    with urlopen(request,timeout=timeout) as r:
        payload=r.read(limit+1)
        if len(payload)>limit:raise ValueError("Source content exceeds maximum size")
        return payload


def image_webp(content,path):
    from PIL import Image,UnidentifiedImageError
    with Image.open(io.BytesIO(content)) as img:
        if img.format not in ("GIF","PNG","JPEG","WEBP"):
            raise ValueError(f"Unexpected chart image format: {img.format}")
        if img.width<500 or img.height<300:
            raise ValueError("Image too small to be a synoptic chart")
        if img.width>6000 or img.height>6000:
            raise ValueError("Image unreasonably large")
        rgb=img.convert("RGB")
        path.parent.mkdir(parents=True,exist_ok=True)
        rgb.save(path,format="WEBP",quality=88,method=5)
    if not path.exists() or path.stat().st_size<18000:
        raise ValueError("WebP image validation failed")


def main(output=OUT,now=None):
    now=now or datetime.now(timezone.utc)
    output=Path(output)
    charts=[];status={}
    sources=[("dwd",DWD_INDEX,extract_dwd),("aemet",AEMET_PAGE,extract_aemet),
             ("knmi",KNMI_PAGE,extract_knmi),
             ("noaa_opc",OPC_ARCHIVE,extract_opc),
             ("noaa_full",OPC_ARCHIVE,extract_opc_full),
             ("noaa_west",OPC_ARCHIVE,extract_opc_west),
             ("noaa_24",OPC_ARCHIVE,extract_opc_24),
             ("noaa_48",OPC_ARCHIVE,extract_opc_48),
             ("noaa_96",OPC_ARCHIVE,extract_opc_96)]
    with __import__("tempfile").TemporaryDirectory(prefix="synoptic-charts-") as work:
        temp=Path(work)
        html_cache={}
        for key,url,parse in sources:
            try:
                if url not in html_cache:
                    html_cache[url]=download(url).decode("utf-8","replace")
                html=html_cache[url]
                candidate=parse(html,now)
                if not candidate:raise ValueError("No plausible dated chart URL found")
                successes=0
                for record in candidate:
                    safe_date=datetime.fromisoformat(record["valid_utc"]).strftime("%Y%m%d_%H%M")
                    target_name=f"{key}_{safe_date}.webp"
                    try:
                        image_webp(download(record["source_url"]),temp/target_name)
                    except Exception as exc:
                        print(f"Skipping unavailable {key} chart {record['valid_utc']}: {exc}",flush=True)
                        continue
                    record["image"]="images/"+target_name
                    record["size_bytes"]=(temp/target_name).stat().st_size
                    charts.append(record)
                    successes+=1
                if not successes:raise ValueError("No source image passed validation")
                status[key]={"state":"available","charts":successes}
            except Exception as exc:
                status[key]={"state":"unavailable","reason":str(exc)[:180]}
                print(f"Source {key} unavailable: {exc}",flush=True)
        # ČHMÚ's public provider transmits PNGs inside JSON. Its API dateTime
        # is a playback time, NOT map validity. Parse only verified UTC heading.
        try:
            import chmi_synoptic_adapter as chmi
            payload=json.loads(download(chmi.API,timeout=55,limit=35_000_000).decode("utf-8"))
            candidate=chmi.parse_chmi_json(payload,now)
            if not candidate:
                raise ValueError("No ČHMÚ chart header yielded a verifiable UTC validity")
            successes=0
            for record,raw_png in candidate:
                date_str=datetime.fromisoformat(record["valid_utc"]).strftime("%Y%m%d_%H%M")
                name=f"chmi_{date_str}.webp"
                try:
                    image_webp(raw_png,temp/name)
                    record["image"]="images/"+name
                    record["size_bytes"]=(temp/name).stat().st_size
                    charts.append(record)
                    successes+=1
                except Exception as exc:
                    print(f"Skipping ČHMÚ PNG: {exc}",flush=True)
            if not successes:raise ValueError("No verified ČHMÚ map image")
            status["chmi"]={"state":"available","charts":successes}
        except Exception as exc:
            status["chmi"]={"state":"unavailable","reason":(type(exc).__name__+": "+str(exc))[:200]}
            print("ČHMÚ source unavailable:",str(exc)[:200],flush=True)
        # DHMZ official synoptic front map: provider URL can serve OLD images.
        # Never infer tomorrow from today's clock; verify printed Croatian date.
        try:
            import dhmz_synoptic_adapter as dhmz
            raw=download(dhmz.IMAGE_URL,timeout=28)
            record=dhmz.verified_chart(raw,now)
            date_str=datetime.fromisoformat(record["valid_utc"]).strftime("%Y%m%d_%H%M")
            filename=f"dhmz_{date_str}.webp"
            image_webp(raw,temp/filename)
            record["image"]="images/"+filename
            record["size_bytes"]=(temp/filename).stat().st_size
            charts.append(record)
            status["dhmz"]={"state":"available","charts":1,"valid_utc":record["valid_utc"]}
        except Exception as exc:
            status["dhmz"]={"state":"unavailable","reason":(type(exc).__name__+": "+str(exc))[:180]}
            print("DHMZ source unavailable:",str(exc)[:180],flush=True)
        if not charts:
            raise RuntimeError("No authenticated original chart downloaded; do not publish empty/synthetic catalog")
        charts.sort(key=lambda p:(p["valid_utc"],p["source_id"]))
        published={
            "schema_version":1,"generated_utc":now.isoformat(timespec="seconds"),
            "ready":True,"method":"original_weather_service_surface_maps",
            "same_validity_rule":"Exact matching valid_utc; no rounding, no time-shift or fallback",
            "sources":SOURCES,"source_status":status,"charts":charts,
            "time_slots":sorted({x["valid_utc"] for x in charts}),
            "chart_count":len(charts),
            "note":"Original maps with isobars and fronts, not a common model or cartographic projection."
        }
        images=output/"images"
        images.mkdir(parents=True,exist_ok=True)
        expected=set()
        for record in charts:
            name=Path(record["image"]).name
            (images/name).write_bytes((temp/name).read_bytes())
            expected.add(name)
        for stale in images.glob("*.webp"):
            if stale.name not in expected:stale.unlink()
        tmp=output/"index.json.tmp"
        tmp.write_text(json.dumps(published,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        tmp.replace(output/"index.json")
        print("Verified synoptic charts:",len(charts),status,flush=True)
    return published


if __name__=="__main__":
    arg=argparse.ArgumentParser()
    arg.add_argument("--output",type=Path,default=OUT)
    opts=arg.parse_args()
    main(output=opts.output)
