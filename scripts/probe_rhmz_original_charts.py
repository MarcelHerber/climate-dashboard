#!/usr/bin/env python3
"""Check six RHMZ ORIGINAL Europe/Balkan surface-analysis JPEGs, without publishing images.

The 00/12 UTC in an IMAGE FILENAME identifies a product slot, NOT the day.
A chart is verified only when the image header itself contains a complete
DD-MM-YYYY HH UTC date, the hour matches the slot, and it is recent.
Images are downloaded transiently for metadata verification; no image bytes
are written to the repository or reused on GitHub Pages without permission.
"""
from __future__ import annotations
import argparse
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"data"/"synoptic_charts"/"rhmz_probe.json"
SOURCE_PAGE="https://www.hidmet.gov.rs/eng/osmotreni/analiza.php"
TERMS="https://www.hidmet.gov.rs/eng/osmotreni/analiza.php"
PRODUCTS={
  "europe00":"https://www.hidmet.gov.rs/data/analiza/EVROPA/evropa00_JPG.jpg",
  "europe12":"https://www.hidmet.gov.rs/data/analiza/EVROPA/evropa12_JPG.jpg",
  "balkan06":"https://www.hidmet.gov.rs/data/analiza/BALKAN/balkan06_JPG.jpg",
  "balkan09":"https://www.hidmet.gov.rs/data/analiza/BALKAN/balkan09_JPG.jpg",
  "balkan12":"https://www.hidmet.gov.rs/data/analiza/BALKAN/balkan12_JPG.jpg",
  "balkan15":"https://www.hidmet.gov.rs/data/analiza/BALKAN/balkan15_JPG.jpg",
}
# Printed example: EVROPA / PRIZEMNI PODACI 19-10-2026 12 UTC
COMPLETE_TIME=re.compile(
 r"(?<!\d)([0-3]?\d)\s*[.\-/]\s*([01]?\d)\s*[.\-/]\s*(20\d{2})\s*"
 r"([01]?\d|2[0-3])\s*(?::\s*([0-5]\d))?\s*U\s*T\s*C\b",re.I
)
CONTEXT=re.compile(r"PRIZEMN|PODACI|EVROPA",re.I)
HOST="www.hidmet.gov.rs"

def url_is_expected(product:str,url:str)->bool:
    return product in PRODUCTS and url==PRODUCTS[product] and urlparse(url).hostname==HOST

def printed_utc(caption:str)->datetime:
    normalized=(caption or "").upper().replace("O","O")
    # Reject date text copied from webpage labels or plausible inferred times.
    if not CONTEXT.search(normalized):
        raise ValueError("No Europe/surface-data caption found in image header")
    m=COMPLETE_TIME.search(normalized)
    if not m: raise ValueError("No complete DD-MM-YYYY HH UTC printed in chart")
    day,month,year,hour,minute=m.groups()
    return datetime(int(year),int(month),int(day),int(hour),int(minute or 0),tzinfo=timezone.utc)

def verified_time(product:str,url:str,caption:str,now:datetime)->datetime:
    if not url_is_expected(product,url):raise ValueError("Unknown RHMZ map URL")
    dt=printed_utc(caption)
    slot={"europe00":0,"europe12":12,"balkan06":6,"balkan09":9,"balkan12":12,"balkan15":15}[product]
    if dt.hour!=slot or dt.minute!=0:
        raise ValueError("Printed hour differs from official RHMZ product slot")
    if not(now-timedelta(hours=48)<=dt<=now+timedelta(hours=2)):
        raise ValueError("Chart print is stale or unexpectedly future-dated")
    return dt

def read_jpeg(url:str)->bytes:
    if url not in PRODUCTS.values():raise ValueError("Unknown JPEG address")
    req=Request(url,headers={"User-Agent":"ClimateDashboardDeutschland/1.0 (official-chart-time-audit)",
                             "Accept":"image/jpeg"})
    with urlopen(req,timeout=18) as resp:
        if resp.url!=url:raise ValueError("Unverified redirect during image retrieval")
        data=resp.read(7_000_001)
    if not 20000<=len(data)<=7_000_000 or not data.startswith(b"\xff\xd8\xff"):
        raise ValueError("Invalid RHMZ JPEG")
    return data

def ocr_header(data:bytes)->str:
    from PIL import Image,ImageOps,ImageEnhance
    import pytesseract
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if not (750<=image.width<=4500 and 450<=image.height<=3000):
            raise ValueError("Implausible Europe analysis image dimensions")
        # The printed date appears at the TOP RIGHT. Isolate header rather
        # than running OCR over the map or attempting to read meteorological data.
        right=image.crop((int(image.width*.65),0,image.width,min(image.height//5,105)))
        gray=ImageOps.autocontrast(right.convert("L"))
        gray=ImageEnhance.Contrast(gray).enhance(2)
        enlarged=gray.resize((gray.width*3,gray.height*3))
        return pytesseract.image_to_string(enlarged,lang="eng",config="--psm 6")[:300]

def check(now:datetime|None=None,fetch_image=read_jpeg,header_reader=ocr_header)->dict:
    now=now or datetime.now(timezone.utc)
    records=[]
    for product,url in PRODUCTS.items():
        entry={"product":product,"region":"Balkan" if product.startswith("balkan") else "Europa","image_url":url,"source_page":SOURCE_PAGE,
               "slot_utc":product[-2:]+":00",
               "state":"unverified","image_reuse_permitted":False}
        try:
            image=fetch_image(url)
            from PIL import Image
            with Image.open(io.BytesIO(image)) as pic:pic.verify()
            caption=header_reader(image)
            validity=verified_time(product,url,caption,now)
            entry.update({"state":"printed_utc_verified","valid_utc":validity.isoformat(timespec="minutes"),
                          "verification":"OCR of full date and UTC in image header; slot and recency match"})
        except Exception as e:
            entry["reason"]=(type(e).__name__+": "+str(e))[:180]
        records.append(entry)
    return {
      "schema_version":1,"generated_utc":now.isoformat(timespec="seconds"),
      "provider":"RHMZ / Republic Hydrometeorological Service of Serbia",
      "source_page":SOURCE_PAGE,"copyright":"© RHMZ Serbia; no general reuse license verified",
      "only_external_links":True,
      "records":records,
      "no_images_persisted":True
    }

def main(output:Path=OUTPUT):
    result=check()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("RHMZ chart time check:",[(x["product"],x["state"]) for x in result["records"]],flush=True)
    return result

if __name__=="__main__":
    args=argparse.ArgumentParser()
    args.add_argument("--output",type=Path,default=OUTPUT)
    main(args.parse_args().output)
