#!/usr/bin/env python3
"""IMO Atlantic ECMWF pressure/isobar chart adapter.

Only publish a forecast if ALL independent evidence agrees:
  1. Original image URL contains YYMMDD_HHMM + lead hour.
  2. Provider webpage supplied that exact URL.
  3. The original PNG contains printed validity and UTC run/lead, read by OCR.
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

ICELANDIC_MONTHS={
    "JAN":1,"FEB":2,"MAR":3,"APR":4,"MAI":5,"JUN":6,
    "JUL":7,"AGU":8,"SEP":9,"OKT":10,"NOV":11,"DES":12
}
SHORT_VALID_RE=re.compile(
    r"(?<!\d)([0-3]?\d)\s*\.\s*(JAN|FEB|MAR|APR|MAI|JUN|JUL|AGU|SEP|OKT|NOV|DES)"
    r"\s*\.?\s*(?:KL\.?\s*)?([012]?\d)\s*[:.]\s*([0-5]\d)",re.I
)
LEAD_RE=re.compile(r"\bUTC\s*\(\s*\+\s*(\d{1,3})\s*\)",re.I)

def parse_printed_forecast_validity(caption:str,expected_run:datetime,expected_lead:int)->datetime:
    """Compare two independent on-map clocks with provider filename.

    IMO prints (a) a short Icelandic valid-day caption e.g. '19. okt. kl.
    12:00', and (b) model initialization with year, UTC and (+12 h). The
    valid-day caption has no year, so derive it only from the PRINTED model
    initialization + PRINTED lead, not the wall clock or fetched filename.
    """
    normalized=normalize_caption(caption)
    if VALIDITY_LABEL.search(normalized):
        return parse_printed_validity(caption)
    run_match=None
    for m in DATE_EU.finditer(normalized):
        near=normalized[m.end():m.end()+38]
        lead_label=LEAD_RE.search(near)
        if lead_label:
            run_match=(m,lead_label)
            break
    if not run_match:
        raise ValueError("IMO lacks a legible printed UTC model run and (+lead) footer")
    m,lead_label=run_match
    d,mo,y,hr,minute=map(int,m.groups())
    printed_run=datetime(y,mo,d,hr,minute,tzinfo=timezone.utc)
    printed_lead=int(lead_label.group(1))
    if printed_run!=expected_run or printed_lead!=expected_lead:
        raise ValueError("IMO image's printed UTC model run/lead disagrees with its filename")
    printed_valid=printed_run+timedelta(hours=printed_lead)
    top=SHORT_VALID_RE.search(normalized)
    if not top:
        raise ValueError("IMO image lacks printed Icelandic valid day, month and hour")
    day,month_name,hour,mins=top.groups()
    expected_tuple=(printed_valid.day,printed_valid.month,printed_valid.hour,printed_valid.minute)
    found=(int(day),ICELANDIC_MONTHS[month_name.upper()],int(hour),int(mins))
    if found!=expected_tuple:
        raise ValueError("IMO short map validity caption disagrees with model run+lead")
    return printed_valid

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
    printed=parse_printed_forecast_validity(caption_reader(image),run,lead)
    if printed!=calculated:
        raise ValueError(f"IMO printed map validity {printed.isoformat()} differs from filename {calculated.isoformat()}")
    return {
        "source_id":"imo","publisher_id":"imo","kind":"Prognose",
        "forecast_hours":lead,"run_utc":run.isoformat(timespec="minutes"),
        "issued_utc":None,"valid_utc":calculated.isoformat(timespec="minutes"),
        "source_url":url,"source_page":PAGE,
        "credit":"Quelle: Veðurstofa Íslands / Icelandic Meteorological Office · ECMWF-basierte Atlantik-Isobarenprognose ohne Fronten · Abruf "+now.strftime("%Y-%m-%d")+" UTC",
        "terms_url":TERMS,
        "validity_method":"Printed IMO valid-day caption AND printed UTC model initialization + lead matched image filename; OCR verified",
        "map_type":"isobars_model_forecast_no_fronts",
    }
