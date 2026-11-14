#!/usr/bin/env python3
"""Discover additional MTG layers from the live official EUMETView WMS.

Never publish a UI choice based solely on a guessed layer name. A layer is
considered validated only after the real GetCapabilities and GetMap checks.
The separate JSON report is observational and does not mutate the UI.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET

import check_satellite_wms as wms

OUT=Path("data/satellite_layer_discovery_latest.json")
PATTERNS={
    "airmass": re.compile(r"air[ _-]?mass|airmasses",re.I),
    "night_microphysics": re.compile(r"night.*micro|micro.*night|24.?h.*micro",re.I),
    "infrared_105": re.compile(r"ir[_ -]?10[._-]?5|10[.,]5.?m|infrared.?10",re.I),
    "convection": re.compile(r"convect|severe.?storm",re.I),
    "fire_temperature": re.compile(r"fire.?temp",re.I),
    "lightning": re.compile(r"li_afa|accumulated.?flash.?area",re.I),
    "ash": re.compile(r"rgb_ash|ash.?rgb",re.I),
    "cloud_phase": re.compile(r"rgb_cloudphase|cloud.?phase",re.I),
    "water_vapour": re.compile(r"water.?vapou?r|(^|[^a-z])wv[_ ]?[67]",re.I),
    "true_colour": re.compile(r"rgb_truecolou?r|true.?colou?r",re.I),
    "visible_06": re.compile(r"vis.?0[._]?6|vis06|visible.?0[.,]6",re.I),
}
MAX_PROBES=12

def direct(node,name):
    for child in node:
        if wms.localname(child.tag)==name:
            return (child.text or "").strip()
    return ""

def get_png(layer,time):
    params={
        "service":"WMS","version":"1.1.1","request":"GetMap",
        "layers":layer,"styles":"","format":"image/png",
        "srs":"EPSG:4326","bbox":"-27,24,49,73",
        "width":"480","height":"309",
    }
    if time:params["time"]=time
    payload,code,mime,cors=wms.fetch(wms.url(params),8*1024*1024)
    if not payload.startswith(b"\x89PNG\r\n\x1a\n") or len(payload)<512:
        raise ValueError(f"Keine PNG-Bilddatei (HTTP {code}, Typ {mime})")
    return {"map_ok":True,"bytes":len(payload),
            "http_status":code,"cors_allow_origin":cors}

def main():
    report={
        "checked_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider":"EUMETSAT EUMETView","wms":wms.SERVICE,
        "capabilities_ok":False,"mtg_layer_count":0,
        "categories":{},"errors":[],
        "caution":"Nur amtlich gelistete Layer mit gültigem PNG und passendem UTC-Zeitpunkt in die UI übernehmen.",
    }
    try:
        xml,code,mime,cors=wms.fetch(wms.url({
            "service":"WMS","version":"1.1.1","request":"GetCapabilities",
        }),wms.MAX_XML)
        root=ET.fromstring(xml)
        if wms.localname(root.tag) not in ("WMT_MS_Capabilities","WMS_Capabilities"):
            raise ValueError("Unerwartetes WMS XML")
        report["capabilities_ok"]=True
        report["cors_allow_origin"]=cors
        layers=[]
        for node in root.iter():
            if wms.localname(node.tag)!="Layer":continue
            name=direct(node,"Name")
            if not name.startswith("mtg_fd:"):continue
            title=direct(node,"Title")
            times=wms.dimensions_for_layer(root,name)
            layers.append({"name":name,"title":title,
                           "available_times":len(times),
                           "latest_time":times[-1] if times else None})
        report["mtg_layer_count"]=len(layers)
        # Auditable catalogue of MTG names only; never treat MSG RGBs as FCI.
        report["available_mtg_layers"]=[{"name":item["name"],"title":item["title"]} for item in layers]
        remaining=MAX_PROBES
        for kind,pattern in PATTERNS.items():
            found=[l for l in layers if pattern.search(l["name"]+" "+l["title"])]
            found.sort(key=lambda x:(bool(x["latest_time"]),x["latest_time"] or ""),reverse=True)
            entries=[]
            for item in found[:3]:
                name=item["name"]
                record={"layer":name,"title":item["title"],
                        "latest_advertised_time":item["latest_time"],
                        "map_ok":False,"tested":False,
                        "product_page":"https://view.eumetsat.int/productviewer/productDetails/"+name.replace(":","%3A")}
                if remaining and item["latest_time"]:
                    remaining-=1
                    record["tested"]=True
                    try:
                        record.update(get_png(name,item["latest_time"]))
                        record["latest_verified_time"]=item["latest_time"]
                        delta=datetime.now(timezone.utc)-wms.parse_date(item["latest_time"])
                        record["age_minutes"]=round(delta.total_seconds()/60,1)
                        record["recent"]=0<=record["age_minutes"]<=90
                    except (HTTPError,URLError,ValueError,TimeoutError) as error:
                        record["error"]=str(error)[:250]
                elif not item["latest_time"]:
                    record["error"]="Keine bestätigte Zeitdimension"
                else:
                    record["error"]="Anfragenlimit: noch nicht bildgeprüft"
                entries.append(record)
            report["categories"][kind]=entries
    except Exception as error:
        report["errors"].append(type(error).__name__+": "+str(error)[:350])
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "checked_at":report["checked_at"],"capabilities_ok":report["capabilities_ok"],
        "mtg_layer_count":report["mtg_layer_count"],
        "products":{name:[{"layer":x["layer"],"map_ok":x["map_ok"],"recent":x.get("recent")}
                           for x in rec] for name,rec in report["categories"].items()},
        "errors":report["errors"],
    },indent=2,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
