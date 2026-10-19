#!/usr/bin/env python3
"""IMO Atlantic ECMWF pressure/isobar chart adapter.

Only publish a forecast if ALL independent evidence agrees:
  1. Original image URL contains YYMMDD_HHMM + lead hour.
  2. Provider webpage supplied that exact URL.
  3. The original PNG contains a printed Gildistími valid time, read by OCR.
  4. That printed time equals run + lead in UTC.
Images contain model-based isobars, NOT drawn analysed fronts.
"""
from __future__ import annotations
import io
import re
import unicodedata
from datetime import datetime,timedelta,timezone
from urllib.parse import urlparse

PAGE="https://en.vedur.is/weather/shipping/atlantic/"
TERMS="https://en.vedur.is/about-imo/the-web/conditions/"
PATH_RE=re.compile(r"^/photos/sjo_atlant_spa/([0-9]{6})_([0-9]{4})_([0-9]{1,3})\.png$",re.I)
VALIDITY_LABEL=re.compile(r"\bGILDISTIMI\b",re.I)
DATE_EU=re.compile(r"(?<!\d)([0-3]?\d)\s*[.\/-]\s*([01]?\d)\s*[.\/-]\s*(20\d\d)\s*(?:KL\.?\s*)?([01]?\d|2[0-3])\s*[:.]\s*([0-5]\d)",re.I)
DATE_ISO=re.compile(r"(?<!\d)(20\d\d)\s*[.\/-]\s*([01]?\d)\s*[.\/-]\s*([0-3]?\d)\s*(?:KL\.?\s*)?([01]?\d|2[0-3])\s*[:.]\s*([0-5]\d)",re.I)

def normalize_caption(caption:str)->str:
    return "".join(c for c in unicodedata.normalize("NFKD",caption or "") if not unicodedata.combining(c)).upper()

def parse_printed_validity(caption:str)->datetime:
    normalized=normalize_caption(caption)
    label=VALIDITY_LABEL.search(normalized)
    if not label:
        raise ValueError("IMO caption lacks the printed 'Gildistími' validity label")
    # Prevent accidentally parsing nearby 'Reiknitími' (initialization time).
    portion=normalized[label.end():label.end()+105]
    m=DATE_EU.search(portion)
    if m:
        day,month,year,hour,minute=map(int,m.groups())
        return datetime(year,month,day,hour,minute,tzinfo=timezone.utc)
    m=DATE_ISO.search(portion)
    if m:
        year,month,day,hour,minute=map(int,m.groups())
        return datetime(year,month,day,hour,minute,tzinfo=timezone.utc)
    raise ValueError("IMO valid date/hours are not legible after printed Gildistími")

def read_printed_banner(raw:bytes)->str:
    from PIL import Image,ImageOps,ImageEnhance
    import pytesseract
    with Image.open(io.BytesIO(raw)) as img:
        img.load()
        if not 600<=img.width<=6000 or not 300<=img.height<=6000:
            raise ValueError("Implausible IMO chart dimensions")
        parts=[]
        for bounds in ((0,0,img.width,int(img.height*.22)),
                       (0,int(img.height*.77),img.width,img.height)):
            strip=ImageOps.autocontrast(img.crop(bounds).convert("L"))
            strip=ImageEnhance.Contrast(strip).enhance(2.0)
            strip=strip.resize((strip.width*2,strip.height*2))
            parts.append(pytesseract.image_to_string(strip,lang="eng",config="--psm 6"))
        return "\n".join(parts)

def parse_filename(url:str)->tuple[datetime,int]:
    parsed=urlparse(url)
    if parsed.scheme!="https" or parsed.hostname not in ("en.vedur.is","www.vedur.is","vedur.is"):
        raise ValueError("IMO map is not from official HTTPS host")
    match=PATH_RE.fullmatch(parsed.path)
    if not match or parsed.username or parsed.password or parsed.query:
        raise ValueError("Not an official dated IMO Atlantic chart URL")
    run_date,run_clock,lead_raw=match.groups()
    run=datetime.strptime(run_date+run_clock,"%y%m%d%H%M").replace(tzinfo=timezone.utc)
    lead=int(lead_raw)
    if run.minute!=0 or run.hour not in (0,12) or not 3<=lead<=144 or lead%3:
        raise ValueError("Unacceptable IMO run time or lead hour")
    return run,lead

def verified_chart(image:bytes,candidate:dict,now:datetime,caption_reader=read_printed_banner)->dict:
    if not image.startswith(b"\x89PNG\r\n\x1a\n") or not 20_000<=len(image)<=9_000_000:
        raise ValueError("Invalid or missing original IMO chart PNG")
    url=candidate.get("url") or ""
    run,lead=parse_filename(url)
    calculated=run+timedelta(hours=lead)
    if calculated.isoformat(timespec="minutes")!=candidate.get("calculated_valid_utc"):
        raise ValueError("IMO provider URL and probe metadata disagree on validity")
    if candidate.get("forecast_hours")!=lead or candidate.get("run_utc")!=run.isoformat(timespec="minutes"):
        raise ValueError("IMO provider URL and probe metadata disagree on model run")
    if not now-timedelta(hours=30)<=calculated<=now+timedelta(hours=120):
        raise ValueError("IMO forecast is stale or too far into future")
    from PIL import Image
    with Image.open(io.BytesIO(image)) as img:
        img.verify()
    printed=parse_printed_validity(caption_reader(image))
    if printed!=calculated:
        raise ValueError(f"IMO printed map validity {printed.isoformat()} differs from filename {calculated.isoformat()}")
    return {
        "source_id":"imo","publisher_id":"imo","kind":"Prognose",
        "forecast_hours":lead,"run_utc":run.isoformat(timespec="minutes"),
        "issued_utc":None,"valid_utc":calculated.isoformat(timespec="minutes"),
        "source_url":url,"source_page":PAGE,
        "credit":"Quelle: Veðurstofa Íslands / Icelandic Meteorological Office · ECMWF-basierte Atlantik-Isobarenprognose ohne Fronten · Abruf "+now.strftime("%Y-%m-%d")+" UTC",
        "terms_url":TERMS,
        "validity_method":"Printed IMO Gildistími matched model run YYMMDD_HHMM + forecast lead; OCR verified",
        "map_type":"isobars_model_forecast_no_fronts",
    }
