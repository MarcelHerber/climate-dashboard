#!/usr/bin/env python3
"""DHMZ (Croatian Weather Service) front chart time verification.

The publicly published static chart may be STALE, even if the DHMZ web page
describes it as 'tomorrow 12 UTC'. Do not derive validity from current date,
HTTP modification date or URLs. The exact valid date is PRINTED on the image
in Croatian, e.g. 'ČET, 15. LIS 2026. 12:00'. Read only its date strip.
If unavailable/unreadable/too old, publish no DHMZ chart.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta, timezone

PAGE = "https://meteo.hr/prognoze_e.php?param=web_fronte_sutra12&section=prognoze_model"
IMAGE_URL = "https://prognoza.hr/web_fronte_sutra12.jpg"
TERMS_URL = "https://meteo.hr/o_nama.php?param=uvjeti&section=naslovnica"
CRO_MONTHS = {
    "SIJ": 1, "VEL": 2, "OZU": 3, "TRA": 4, "SVI": 5, "LIP": 6,
    "SRP": 7, "KOL": 8, "RUJ": 9, "LIS": 10, "STU": 11, "PRO": 12,
}
DATE_RE = re.compile(
    r"(?<!\d)([0-3]?\d)\s*[.\-,]?\s*"
    r"(SIJ|VEL|OZU|TRA|SVI|LIP|SRP|KOL|RUJ|LIS|STU|PRO)"
    r"\s*[.\-,]?\s*(20\d{2})\s*[.\-,]?\s*"
    r"(\d{1,2})\s*[:.]\s*(\d\d)",re.I,
)


def parse_valid_utc(caption):
    """Parse only a printed Croatian month abbreviation, never 'tomorrow'."""
    normalized=(caption or "").upper().replace("Ž","Z").replace("Č","C")
    match=DATE_RE.search(normalized)
    if not match:
        raise ValueError("DHMZ map lacks an unambiguous Croatian printed UTC date")
    d,month,y,hr,minute=match.groups()
    dt=datetime(int(y),CRO_MONTHS[month],int(d),int(hr),int(minute),tzinfo=timezone.utc)
    if dt.hour!=12 or dt.minute!=0:
        raise ValueError("DHMZ published image is not the verified 12 UTC map")
    return dt


def read_caption(image_bytes):
    """Last resort: restricted OCR of small bottom-left printed date banner."""
    from PIL import Image,ImageOps,ImageEnhance
    import pytesseract
    with Image.open(io.BytesIO(image_bytes)) as image:
        image.load()
        if image.width<600 or image.height<500 or image.width>4000 or image.height>4000:
            raise ValueError("DHMZ image dimensions implausible")
        # The provider places the validity stamp near the lower left.
        box=(0,int(image.height*0.89),min(image.width,1300),image.height)
        caption=ImageOps.autocontrast(image.crop(box).convert("L"))
        caption=ImageEnhance.Contrast(caption).enhance(2.3)
        caption=caption.resize((caption.width*2,caption.height*3))
        return pytesseract.image_to_string(caption,lang="eng",config="--psm 6")


def verified_chart(image_bytes, now, caption_reader=read_caption):
    from PIL import Image
    if not image_bytes.startswith((b"\xff\xd8\xff",b"\x89PNG\r\n\x1a\n")):
        raise ValueError("Not a JPEG/PNG DHMZ map")
    with Image.open(io.BytesIO(image_bytes)) as image:
        image.verify()
    valid=parse_valid_utc(caption_reader(image_bytes))
    # Strict: never publish yesterday's old PNG as tomorrow's forecast.
    if not now-timedelta(hours=8) <= valid <= now+timedelta(hours=42):
        raise ValueError(f"DHMZ picture is outdated or implausible: printed {valid.isoformat()}")
    return {
        "source_id":"dhmz","publisher_id":"dhmz","kind":"Prognose",
        "valid_utc":valid.isoformat(timespec="minutes"),"issued_utc":None,
        "source_url":IMAGE_URL,"source_page":PAGE,
        "credit":"Izvor: DHMZ · Kroatischer Wetterdienst · Original-Frontenprognose, für WebP konvertiert",
        "terms_url":TERMS_URL,
        "validity_method":"Printed Croatian date/time on original DHMZ map; OCR of caption only",
    }
