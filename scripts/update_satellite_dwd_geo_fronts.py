#!/usr/bin/env python3
"""Discover official DWD front WFS layers, ingest *only* verified NinJo GML.

No public DWD GML URL has yet been demonstrated. Probe official anonymous WFS
GetCapabilities every run. A genuine official GML XML feed can be configured
through the GitHub Actions variable DWD_NINJO_GML_URL after provider approval.
Never reverse-engineer an original PNG into fabricated geographic positions.
"""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"data/synoptic_charts/dwd_fronts_geo.json"
AUDIT=ROOT/"data/synoptic_charts/dwd_fronts_discovery.json"
WFS="https://maps.dwd.de/geoserver/ows?service=WFS&request=GetCapabilities&version=2.0.0"
SOURCE_BASE=("https://opendata.dwd.de/","https://maps.dwd.de/")
FRONT_NAMES={"cold":("cold","kaltfront","coldfront"),
             "warm":("warm","warmfront"),
             "occluded":("occlusion","occluded","ocfnt","okklusion"),
             "stationary":("stationary","stationaer","stationär","stnry")}
GML_NS="http://www.opengis.net/gml"
MAX_FILE=5_000_000
MAX_FEATURES=700

def local(tag):
    return tag.split("}",1)[-1].lower()

def iso(dt):
    return dt.isoformat(timespec="minutes").replace("+00:00","Z")

def from_utc(raw):
    if not isinstance(raw,str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?Z",raw):
        return None
    try:return datetime.fromisoformat(raw.replace("Z","+00:00")).astimezone(timezone.utc)
    except ValueError:return None

def official_gml(url):
    parsed=urlsplit(url)
    return (parsed.scheme=="https" and parsed.netloc in ("opendata.dwd.de","maps.dwd.de") and
            parsed.path.lower().endswith((".gml",".xml")) and re.search(r"(?:analysis|analyse|ana_|bwkman)",parsed.path,re.I) is not None and not parsed.query and not parsed.fragment)

def get(url,limit=MAX_FILE):
    req=urllib.request.Request(url,headers={"User-Agent":"ClimateDashboard-OfficialDWDFrontDiscovery/1.0"})
    with urllib.request.urlopen(req,timeout=22) as response:
        if response.status!=200:raise ValueError(f"HTTP {response.status}")
        payload=response.read(limit+1)
    if len(payload)>limit:raise ValueError("Oversized source payload")
    return payload

def discover(xml):
    root=ET.fromstring(xml)
    names=[]
    for feature in root.iter():
        if local(feature.tag)!="featuretype":continue
        name=next(((x.text or "").strip() for x in feature if local(x.tag)=="name"),"")
        title=next(((x.text or "").strip() for x in feature if local(x.tag)=="title"),"")
        if re.search(r"front|frontal|ninjo|bwkman|okklusion",name+" "+title,re.I):
            names.append({"name":name,"title":title})
    return names[:60]

def type_of(raw):
    token=raw.casefold().replace(" ","").replace("_","").replace("-","")
    for kind,aliases in FRONT_NAMES.items():
        if any(alias in token for alias in aliases):return kind
    return None

def extract_features(xml,now,source_url):
    if not official_gml(source_url):raise ValueError("GML must come from a confirmed official DWD origin")
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("External XML entity declarations are not accepted")
    root=ET.fromstring(xml)
    # Reject forecast products that are not manual surface analysis.
    if any(local(n.tag) in ("forecasttime","forecaststep","leadtime","prognosistime")
           for n in root.iter()):
        raise ValueError("NinJo GML contains forecast fields, not manual analysis")
    members=[x for x in root.iter() if local(x.tag) in ("featuremember","member")]
    if not members:raise ValueError("No explicit GML FeatureMembers")
    features=[];valid_times=set();total=0
    for member in members:
        front_type=None;valid=None
        # Require a typed attribute: a free text legend mention is not a front.
        for node in member.iter():
            tag=local(node.tag)
            if tag in ("fronttype","front_type","frontaltype","meteorologicaltype","subtype"):
                front_type=type_of((node.text or "").strip())
            elif tag in ("validtime","valid_time","analysistime","referencetime","validat","timeposition"):
                stamp=from_utc((node.text or "").strip())
                if stamp:valid=stamp
        if not front_type:continue
        if valid is None:raise ValueError("Feature has front geometry but no explicit analysis validity UTC")
        geometries=[el for el in member.iter() if local(el.tag)=="linestring"]
        for line in geometries:
            srs=line.attrib.get("srsName","")
            values=None
            for el in line.iter():
                if local(el.tag)=="poslist":
                    values=(el.text or "").split()
                    srs=el.attrib.get("srsName",srs)
                    break
            if not values or not srs:continue
            srsl=srs.lower()
            if "crs84" in srsl:order="lonlat"
            elif "epsg" in srsl and srsl.rstrip("/").endswith(("4326","::4326")):
                order="latlon" # GML EPSG:4326 is latitude-first
            else:continue
            if len(values)<4 or len(values)%2 or len(values)>6000:continue
            try:numbers=[float(x) for x in values]
            except ValueError:continue
            points=[]
            for i in range(0,len(numbers),2):
                a,b=numbers[i:i+2]
                lon,lat=(a,b) if order=="lonlat" else (b,a)
                if not (-180<=lon<=180 and -90<=lat<=90):
                    points=[];break
                points.append([round(lon,5),round(lat,5)])
            if len(points)<2:continue
            total+=len(points)
            if total>60000:raise ValueError("Too many GML coordinates")
            if valid:valid_times.add(valid)
            features.append({"type":"Feature","geometry":{"type":"LineString","coordinates":points},
                             "properties":{"front_type":front_type,
                                           "origin":"DWD official NinJo GML analysis",
                                           "symbol_orientation_verified":False}})
            if len(features)>MAX_FEATURES:raise ValueError("Too many front features")
    if not features:raise ValueError("No identifiable official NinJo front line geometry")
    if len(valid_times)!=1:raise ValueError("Missing or ambiguous GML analysis UTC")
    valid=valid_times.pop()
    age=(now-valid).total_seconds()/3600
    if age<-.25 or age>30:raise ValueError(f"DWD front analysis is {age:.1f}h old/future")
    return {"schema_version":1,"status":"verified","provider":"DWD","kind":"analysis",
            "coordinate_reference_system":"EPSG:4326","georeferencing_verified":True,
            "front_source_format":"NinJo-GML","source_url":source_url,
            "valid_utc":iso(valid),"checked_at":iso(now),"features":features}

def empty(now,msg):
    return {"schema_version":1,"status":"unavailable","provider":"DWD","kind":"analysis",
        "coordinate_reference_system":"EPSG:4326","georeferencing_verified":False,
        "front_source_format":"NinJo-GML","valid_utc":None,"source_url":None,
        "features":[],"checked_at":iso(now),"reason":str(msg)[:350]}

def main():
    now=datetime.now(timezone.utc)
    audit={"checked_at":iso(now),"wfs":WFS,"public_wfs_front_layers":[],
           "verified_public_ninjo_gml":False}
    try:
        capabilities=get(WFS)
        audit["wfs_capabilities_http_ok"]=True
        audit["public_wfs_front_layers"]=discover(capabilities)
    except Exception as e:
        audit["wfs_capabilities_http_ok"]=False
        audit["wfs_error"]=str(e)[:300]
    configured=os.environ.get("DWD_NINJO_GML_URL","").strip()
    if configured:
        try:
            if not official_gml(configured):raise ValueError("Configured GML URL not an official DWD .gml/.xml download")
            outcome=extract_features(get(configured),now,configured)
            audit["verified_public_ninjo_gml"]=True
            audit["verified_source_url"]=configured
        except Exception as exc:
            outcome=empty(now,"Configured DWD GML unavailable/unverified: "+str(exc))
    else:
        outcome=empty(now,"No confirmed public DWD NinJo-GML front source. "+
          "WFS capabilities are checked independently; any candidate layer requires its own geometry/UTC verification.")
    for name,data in [(OUTPUT,outcome),(AUDIT,audit)]:
        name.parent.mkdir(parents=True,exist_ok=True)
        name.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("DWD direct vector fronts:",outcome["status"],len(outcome["features"]))
    print("Official WFS candidate layers:",audit["public_wfs_front_layers"])
    return 0

if __name__=="__main__":
    sys.exit(main())
