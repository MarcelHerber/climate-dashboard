#!/usr/bin/env python3
"""Geographic surface fronts from official NOAA WPC HIGH-RES CODED ANALYSIS.

Source: https://tgftp.nws.noaa.gov/data/raw/as/asus02.kwbc.cod.sus.txt
ASUS02 (not ASUS01) carries exact analyzed polylines at 0.1-degree
precision (see WPC high resolution coded bulletin documentation).
NOAA's domain is principally North America and the western North Atlantic:
it does NOT supply a verified manual DWD front analysis for Europe.
Do not infer fronts or graphical locations from DWD PNG images.
"""
from __future__ import annotations
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/synoptic_charts/noaa_wpc_fronts_geo.json"
SOURCE="https://tgftp.nws.noaa.gov/data/raw/as/asus02.kwbc.cod.sus.txt"
DOC="https://www.wpc.ncep.noaa.gov/html/read_coded_bull_hr.shtml"
FRONT={"COLD":"cold","WARM":"warm","OCFNT":"occluded","STNRY":"stationary"}
TYPES=tuple(FRONT)
NOW=lambda:datetime.now(timezone.utc)
MAX_AGE_HOURS=14
MAX_BYTES=300_000
COORD=re.compile(r"^\d{7}$")
WMO=re.compile(r"^ASUS02\s+KWBC\s+(\d{6})\b",re.MULTILINE)
VALID=re.compile(r"\bVALID\s+(\d{2})(\d{2})(\d{2})Z\b")
KEYS=set(FRONT)|{"HIGHS","LOWS","TROF","TROUGH","DRY","SQUALL","$$"}

def iso(dt):
    return dt.isoformat(timespec="minutes").replace("+00:00","Z")

def closest_valid(mm,dd,hh,now):
    values=[]
    for year in (now.year-1,now.year,now.year+1):
        try: values.append(datetime(year,int(mm),int(dd),int(hh),tzinfo=timezone.utc))
        except ValueError: continue
    return min(values,key=lambda t:abs((now-t).total_seconds())) if values else None

def decode(token):
    """ASUS02 coordinate AAATTTT = N lat tenths / W lon tenths."""
    if not COORD.fullmatch(token):return None
    lat=int(token[:3])/10
    west=int(token[3:])/10
    if lat>90 or west>180:return None
    return [-west,lat]

def parse(text,now):
    # Match official high-resolution header; never misread degree-only ASUS01
    # as 0.1-degree data.
    if not WMO.search(text) or "CODSUS" not in text or "CODED SURFACE FRONTAL POSITIONS" not in text:
        raise ValueError("No official WPC high-resolution ASUS02 / CODSUS header")
    match=VALID.search(text)
    if not match:raise ValueError("Valid WPC surface analysis UTC missing")
    valid=closest_valid(*match.groups(),now)
    if not valid:raise ValueError("Invalid WPC UTC")
    diff=(now-valid).total_seconds()/3600
    if diff < -0.5 or diff>MAX_AGE_HOURS:
        raise ValueError(f"WPC analysis is not current: {diff:.1f}h")
    fields=[]
    active=None
    for line in text.splitlines():
        stripped=line.strip()
        if not stripped or stripped.startswith("$$"):continue
        parts=stripped.split()
        if not parts:continue
        code=parts[0].upper()
        if code in KEYS:
            active=code if code in FRONT else None
            if active: fields.append((active,[]))
            parts=parts[1:]
        if active and fields:
            for token in parts:
                if token.upper() in ("WK","MDT","STG"):continue
                if COORD.fullmatch(token):fields[-1][1].append(token)
                elif token not in ("",):active=None
    features=[]
    for code,tokens in fields:
        points=[decode(t) for t in tokens]
        points=[p for p in points if p is not None]
        if len(points)<2:continue
        # Dateline/wrap and impossible trajectory jumps must never become
        # lines crossing Europe by accident.
        segments=[[points[0]]]
        for p in points[1:]:
            previous=segments[-1][-1]
            if abs(p[0]-previous[0])>35 or abs(p[1]-previous[1])>25:
                segments.append([p])
            elif p!=previous:
                segments[-1].append(p)
        for segment in segments:
            if len(segment)>=2 and len(features)<600:
                features.append({
                    "type":"Feature","geometry":{"type":"LineString","coordinates":segment},
                    "properties":{"front_type":FRONT[code],"symbol_orientation_verified":False,
                                  "origin":"WPC high-resolution coded surface analysis"}
                })
    if not features:
        raise ValueError("No decoded analyzed frontal polylines")
    return {
        "schema_version":1,"status":"verified",
        "provider":"NOAA WPC","kind":"analysis",
        "coordinate_reference_system":"EPSG:4326",
        "georeferencing_verified":True,
        "front_source_format":"CODSUS-HIRES",
        "valid_utc":iso(valid),"checked_at":iso(now),
        "source_url":SOURCE,"documentation_url":DOC,
        "analysis_domain":"North America and western North Atlantic; not the DWD manual Europe analysis",
        "geographic_precision_degrees":0.1,
        "features":features
    }

def unavailable(now,reason):
    return {"schema_version":1,"status":"unavailable","provider":"NOAA WPC",
            "kind":"analysis","coordinate_reference_system":"EPSG:4326",
            "georeferencing_verified":False,"front_source_format":"CODSUS-HIRES",
            "valid_utc":None,"checked_at":iso(now),"source_url":SOURCE,
            "features":[],"error":str(reason)[:300]}

def retrieve():
    req=urllib.request.Request(SOURCE,headers={"User-Agent":"ClimateDashboard-NOAA-WPC-Fronts/1.0",
                                              "Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=22) as response:
        if response.status!=200:raise ValueError("WPC status "+str(response.status))
        data=response.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:raise ValueError("Oversized NOAA coded surface bulletin")
    return data.decode("ascii","replace")

def main():
    now=NOW()
    try:
        outcome=parse(retrieve(),now)
        print("Decoded",len(outcome["features"]),"NOAA WPC fronts for",outcome["valid_utc"])
    except Exception as err:
        # Never republish an older frame as "latest" after an upstream outage.
        outcome=unavailable(now,err)
        print("NOAA front analysis unavailable:",err)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(outcome,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return 0

if __name__=="__main__":
    sys.exit(main())
