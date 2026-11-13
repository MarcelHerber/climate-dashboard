#!/usr/bin/env python3
"""Publish verified metadata for the latest *original DWD surface front analyses*.

The source is the official DWD Open Data analysis directory, not the
forecast 'ico_tkboden' images. Original DWD PNGs are linked unchanged;
only the tiny JSON index is committed (no growing image archive).
Actual validity is parsed from the original filename, never guessed from
download/publication time.
"""
from __future__ import annotations

import json
import re
import struct
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
INDEX="https://opendata.dwd.de/weather/charts/analysis/"
OUTPUT=ROOT/"data/synoptic_charts/dwd_fronts_satellite.json"
REGIONS={
    "atlantic":{"title":"Nordatlantik und Europa","source_code":"dwdna"},
    "central":{"title":"Mitteleuropa","source_code":"dwdc"},
}
# Official manual surface analysis, reduced-size *original PNG* (WV12SW),
# not ICO/ICON forecast charts, not a reprojected image.
FILE_RE=re.compile(
    r"^Z__C_EDZW_(\d{14})_tka01,ana_bwkman_(dwdna|dwdc)_O_000000_000000_(\d{12})_WV12SW\.png$",
    re.IGNORECASE)
PNG=b"\x89PNG\r\n\x1a\n"
MAX_BYTES=7_000_000
FRESH_HOURS=18
MAX_AGE_HOURS=42


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs=[]
    def handle_starttag(self, tag, attrs):
        if tag=="a":
            href=dict(attrs).get("href")
            if href:self.hrefs.append(href)


def moment(value,fmt):
    return datetime.strptime(value,fmt).replace(tzinfo=timezone.utc)


def iso(value):
    return value.isoformat(timespec="minutes").replace("+00:00","Z")


def candidate_maps(html,now):
    parser=Links()
    parser.feed(html)
    found={region:{} for region in REGIONS}
    for href in parser.hrefs:
        url=urljoin(INDEX,href)
        parsed=urlsplit(url)
        if parsed.scheme!="https" or parsed.hostname!="opendata.dwd.de" or parsed.query or parsed.fragment:
            continue
        if not parsed.path.startswith("/weather/charts/analysis/"):
            continue
        filename=unquote(parsed.path.rsplit("/",1)[-1])
        match=FILE_RE.fullmatch(filename)
        if not match:continue
        published=moment(match[1],"%Y%m%d%H%M%S")
        valid=moment(match[3],"%Y%m%d%H%M")
        # Analysis, not a forecast! DWD manually publishes after valid UTC.
        if not (valid<=published<=now+timedelta(minutes=15)):
            continue
        if published-valid>timedelta(hours=10):
            continue
        if not now-timedelta(hours=MAX_AGE_HOURS)<=valid<=now:
            continue
        region="atlantic" if match[2].lower()=="dwdna" else "central"
        key=iso(valid)
        obj={
            "region":region,
            "kind":"analysis",
            "valid_utc":key,
            "published_utc":iso(published),
            "source_url":url,
            "source_page":INDEX,
            "source":"Deutscher Wetterdienst (DWD)",
            "credit":"© Deutscher Wetterdienst (DWD)",
            "original":True
        }
        # If an analysis has been corrected at the same validity, use
        # the latest published revision only.
        prev=found[region].get(key)
        if not prev or prev["published_utc"]<obj["published_utc"]:
            found[region][key]=obj
    return {region:sorted(entries.values(),key=lambda x:(x["valid_utc"],x["published_utc"]),reverse=True)
            for region,entries in found.items()}


def url_bytes(url,limit=MAX_BYTES,timeout=18):
    if not url.startswith(INDEX):
        raise ValueError("Only official DWD analysis URLs are permitted")
    request=Request(url,headers={"User-Agent":"ClimateDashboard-DWD-FrontAnalysis/1.0"})
    with urlopen(request,timeout=timeout) as response:
        if response.status!=200:
            raise ValueError("HTTP "+str(response.status))
        body=response.read(limit+1)
    if len(body)>limit:
        raise ValueError("Image exceeds download limit")
    return body


def validate_png(data):
    if len(data)<90_000 or not data.startswith(PNG):
        raise ValueError("Invalid or suspiciously small original DWD PNG")
    if data[12:16]!=b"IHDR":
        raise ValueError("Missing PNG IHDR")
    width,height=struct.unpack(">II",data[16:24])
    if not (750<=width<=6000 and 480<=height<=4500):
        raise ValueError("Unexpected DWD PNG image dimensions")
    if data[-12:] != b"\x00\x00\x00\x00IEND\xaeB\x60\x82":
        raise ValueError("Incomplete PNG / missing IEND")
    return width,height


def select_verified(candidates,now,fetch=url_bytes,attempts=3):
    maps={}
    diagnostics={}
    for region,items in candidates.items():
        errors=[]
        for item in items[:attempts]:
            try:
                blob=fetch(item["source_url"])
                width,height=validate_png(blob)
            except Exception as exc:
                errors.append(str(exc)[:180])
                continue
            value=dict(item)
            value.update({
                "width":width,"height":height,
                "image_bytes":len(blob),
                "image_verified":True,
                "verified_at":iso(now),
                "age_hours":round((now-moment(item["valid_utc"].replace("Z","+0000"),"%Y-%m-%dT%H:%M%z")).total_seconds()/3600,2)
            })
            value["fresh"]=value["age_hours"]<=FRESH_HOURS
            maps[region]=value
            break
        if region not in maps:
            diagnostics[region]=" | ".join(errors)[:250] if errors else "No current DWD analysis file"
    return maps,diagnostics


def prior_if_recent(report,region,now):
    item=(report.get("maps") or {}).get(region)
    if not isinstance(item,dict) or item.get("kind")!="analysis" or not item.get("image_verified"):
        return None
    try:
        valid=datetime.fromisoformat(item["valid_utc"].replace("Z","+00:00"))
    except (TypeError,ValueError,KeyError):
        return None
    if not timedelta(0)<=now-valid<=timedelta(hours=MAX_AGE_HOURS):
        return None
    if not item.get("source_url","").startswith(INDEX):
        return None
    old=dict(item)
    old["fresh"]=False
    old["age_hours"]=round((now-valid).total_seconds()/3600,2)
    old["previously_verified"]=True
    return old


def build_report(html,now,fetch=url_bytes,previous=None):
    candidates=candidate_maps(html,now)
    maps,issues=select_verified(candidates,now,fetch=fetch)
    for region in REGIONS:
        if region not in maps:
            old=prior_if_recent(previous or {},region,now)
            if old:maps[region]=old
    statuses=[m.get("fresh",False) for m in maps.values()]
    state="healthy" if len(maps)==len(REGIONS) and all(statuses) else ("degraded" if maps else "unavailable")
    return {
        "schema_version":1,
        "generated_at":iso(now),
        "provider":"Deutscher Wetterdienst (DWD)",
        "product":"Handanalysierte Bodendruckkarte mit Fronten und Isobaren",
        "kind":"analysis",
        "source_page":INDEX,
        "image_policy":"Official unmodified PNGs loaded directly from DWD; no republishing or reprojection",
        "status":state,
        "fresh_hours":FRESH_HOURS,
        "maps":maps,
        "errors":issues,
    }


def main():
    now=datetime.now(timezone.utc)
    try:
        previous=json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        previous={}
    try:
        html=url_bytes(INDEX,limit=2_000_000,timeout=18).decode("utf-8","replace")
        result=build_report(html,now,previous=previous)
    except Exception as exc:
        result=build_report("",now,previous=previous)
        result["fetch_error"]=str(exc)[:300]
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for region in REGIONS:
        item=result["maps"].get(region)
        print(region,"verified",item and item.get("valid_utc"),
              "fresh",item and item.get("fresh"),"error",result["errors"].get(region))
    print("DWD Frontanalysekarten:",result["status"],result["generated_at"])
    # A data outage is visible via JSON status. Do not poison main or delete
    # still recent, formerly verified DWD source URLs on a transient 504.
    return 0


if __name__=="__main__":
    sys.exit(main())
