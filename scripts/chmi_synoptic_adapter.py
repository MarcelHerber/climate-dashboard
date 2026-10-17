#!/usr/bin/env python3
"""Original ČHMÚ synoptic chart adapter with verified UTC from chart heading.

Critical: playableImages.data[].dateTime is a PLAYER TIMELINE time, not
necessarily the map validity. In October 2026, e.g. 10Z player -> 00Z analysis
and 10Z player -> 12Z forecast. Never publish dateTime as chart validity.
The only source of the chart's valid hour is its printed 'DD.MM.YYYY HH UTC'
header. Strictly discard images without a legible date and hour.
"""
from __future__ import annotations
import base64
import io
import re
from datetime import datetime,timedelta,timezone

PAGE="https://www.chmi.cz/predpoved-pocasi/synopticka-situace"
API="https://data-provider.chmi.cz/api/playableImages/init/synopticka-mapa"
DATE_RE=re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
HEADER_RE=re.compile(r"(?<!\d)(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(20\d{2})\s+(00|06|12|18)\s*UTC\b",re.I)
PNG_HEADER=bytes.fromhex("89504e470d0a1a0a")


def parse_printed_timestamp(text):
    match=HEADER_RE.search(text or "")
    if not match:
        raise ValueError("No verified UTC validity printed in ČHMÚ map heading")
    day,month,year,hour=map(int,match.groups())
    return datetime(year,month,day,hour,tzinfo=timezone.utc)


def read_map_heading(png_data):
    """Use OCR only for small UTC timestamp heading; never analyse map pixels."""
    import pytesseract
    from PIL import Image,ImageOps,ImageEnhance
    with Image.open(io.BytesIO(png_data)) as image:
        image.load()
        if image.width<700 or image.height<420 or image.width>6000:
            raise ValueError("ČHMÚ synoptic chart resolution implausible")
        # Header is a narrow text strip at the upper edge of the official map.
        h=min(74,max(42,int(image.height*.092)))
        top=image.crop((0,0,image.width,h)).convert("L")
        top=ImageOps.autocontrast(top)
        top=ImageEnhance.Contrast(top).enhance(2.2)
        top=top.resize((top.width*2,top.height*3))
        return pytesseract.image_to_string(top,lang="eng",
                                          config="--psm 6")


def parse_chmi_json(payload,now,heading_reader=read_map_heading):
    if not isinstance(payload,dict) or not isinstance(payload.get("data"),list):
        raise ValueError("ČHMÚ: unexpected playableImages response")
    data=payload["data"]
    if not 1<=len(data)<=25 or payload.get("type") not in (None,"image"):
        raise ValueError("ČHMÚ: wrong image product or frame count")
    forecast_start=next((i for i,item in enumerate(data)
                         if isinstance(item,dict) and item.get("isForecastStart") is True),None)
    records={}
    for idx,item in enumerate(data):
        if not isinstance(item,dict):continue
        api_time=item.get("dateTime")
        val=item.get("image")
        if not isinstance(api_time,str) or not DATE_RE.fullmatch(api_time):
            continue
        if not isinstance(val,str) or not val.startswith("image/png;base64,"):
            continue
        timeline=datetime.strptime(api_time,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if not (now-timedelta(hours=72)<=timeline<=now+timedelta(hours=120)):
            continue
        raw=base64.b64decode(val.partition(",")[2],validate=True)
        if len(raw)<18_000 or len(raw)>12_000_000 or not raw.startswith(PNG_HEADER):
            raise ValueError("ČHMÚ: invalid PNG in provider response")
        try:
            valid=parse_printed_timestamp(heading_reader(raw))
        except (ValueError,RuntimeError) as e:
            print(f"ČHMÚ skipped unverified frame {api_time}: {e}",flush=True)
            continue
        if abs((valid-timeline).total_seconds())>25*3600 or not (
            now-timedelta(hours=72)<=valid<=now+timedelta(hours=120)):
            print(f"ČHMÚ rejected implausible difference between timeline and chart header: {api_time}",flush=True)
            continue
        kind=("Analyse" if idx<forecast_start else "Prognose") if forecast_start is not None else "Originalkarte"
        stamp=valid.isoformat(timespec="minutes")
        records[stamp]=({
            "source_id":"chmi","publisher_id":"chmi","kind":kind,
            "valid_utc":stamp,"issued_utc":None,
            "source_url":API,"source_page":PAGE,
            "credit":"© Český hydrometeorologický ústav (ČHMÚ) · CC BY 4.0 · in WebP konvertiert",
            "license_url":"https://creativecommons.org/licenses/by/4.0/",
            "provider_timeline_utc":timeline.isoformat(timespec="minutes"),
            "validity_method":"Printed DD.MM.YYYY HH UTC map heading, OCR verified; API dateTime is NOT used as valid time",
        },raw)
    return [records[k] for k in sorted(records)]
