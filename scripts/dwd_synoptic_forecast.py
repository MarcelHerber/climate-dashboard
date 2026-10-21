#!/usr/bin/env python3
"""DWD ICON Nordatlantik: separate ORIGINAL multi-time forecast sheets (0–168 h).

A sheet can cover a LEAD-TIME RANGE, not one valid_utc. Never feed these
records to the UTC-synchronised four-panel surface-analysis index.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

INDEX = "https://opendata.dwd.de/weather/charts/forecasts/icon/global/na/"
PATTERN = re.compile(
    r"^Z__C_EDZW_([0-9]{14})_nwv[0-9]{2},ico_hptfg_na_N_([0-9]{3})([0-9]{3})_[a-zA-Z0-9]+_([0-9]{12})_WV[0-9]+\.png$",
    re.I,
)

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs=[]
    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href=dict(attrs).get("href")
        if href:
            self.hrefs.append(href)

def extract(html: str, now: datetime):
    parser=Links()
    parser.feed(html)
    runs={}
    for href in parser.hrefs:
        url=urljoin(INDEX,href)
        parsed=urlparse(url)
        if parsed.scheme!="https" or parsed.hostname!="opendata.dwd.de":
            continue
        if parsed.path.rsplit("/",1)[0]+"/" != urlparse(INDEX).path:
            continue
        if parsed.query or parsed.fragment:
            continue
        filename=unquote(parsed.path.rsplit("/",1)[-1])
        match=PATTERN.fullmatch(filename)
        if not match:
            continue
        issue=datetime.strptime(match.group(1),"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        start,end=int(match.group(2)),int(match.group(3))
        model_run=datetime.strptime(match.group(4),"%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        if not (0<=start<end<=168) or end-start>96:
            continue
        # Issue timestamp is the file creation time, NOT its UTC forecast validity.
        if not now-timedelta(hours=72)<=issue<=now+timedelta(minutes=25):
            continue
        if not now-timedelta(hours=48)<=model_run<=now or not timedelta(0)<=issue-model_run<=timedelta(hours=18):
            continue
        if model_run.minute!=0 or model_run.hour not in (0,6,12,18):
            continue
        key=(start,end)
        rec={
            "source_id":"dwd_icon_hptfg_na",
            "publisher_id":"dwd",
            "kind":"Prognoseblatt",
            "forecast_from_hours":start,
            "forecast_to_hours":end,
            "generated_utc":issue.isoformat(timespec="seconds"),
            "run_utc":model_run.isoformat(timespec="seconds"),
            "source_url":url,
            "source_page":INDEX,
            "credit":"Quelle: Deutscher Wetterdienst (DWD) · ICON-Nordatlantik",
            "multiple_valid_times":True,
            "has_single_valid_utc":False,
            "description":"Bodendruck, Wetter und Fronten: Original-Kartenblatt für mehrere Vorhersagezeiten",
        }
        latest=runs.setdefault(rec["run_utc"],{})
        if key not in latest or rec["generated_utc"]>latest[key]["generated_utc"]:
            latest[key]=rec
    if not runs:
        return []
    # Use a single coherent ICON model cycle, preferring the newest
    # available cycle with the complete seven-day range. Never mix 00/06Z.
    usable=[(run,list(items.values())) for run,items in runs.items()]
    full=[p for p in usable if max(s["forecast_to_hours"] for s in p[1])==168]
    pool=full if full else usable
    chosen=max(pool,key=lambda x:(x[0],max(s["forecast_to_hours"] for s in x[1])))
    return sorted(chosen[1],key=lambda x:(x["forecast_from_hours"],x["forecast_to_hours"]))

def publish(output:Path, now:datetime, fetch, image_webp):
    output=Path(output)
    html=fetch(INDEX,timeout=35,limit=2_000_000).decode("utf-8","replace")
    candidates=extract(html,now)
    if not candidates:
        raise ValueError("Keine datierten aktuellen DWD-ICON-Originalblätter im Verzeichnis")
    images=output/"images"
    images.mkdir(parents=True,exist_ok=True)
    records=[]
    for rec in candidates:
        # Optional missing sheets do not cause fabricated leads or broken images.
        start,end=rec["forecast_from_hours"],rec["forecast_to_hours"]
        issue=datetime.fromisoformat(rec["generated_utc"])
        basename=f"dwd_icon_na_{start:03d}_{end:03d}_{issue.strftime('%Y%m%d_%H%M%S')}.webp"
        path=images/basename
        try:
            content=fetch(rec["source_url"],timeout=45,limit=9_000_000)
            image_webp(content,path)
        except Exception as exc:
            path.unlink(missing_ok=True)
            print(f"DWD-Prognoseblatt +{start}–{end} h nicht verfügbar: {exc}",flush=True)
            continue
        rec["image"]="images/"+basename
        rec["size_bytes"]=path.stat().st_size
        records.append(rec)
    if not records:
        raise ValueError("Kein DWD-ICON-Prognoseblatt wurde als Originalbild validiert")
    manifest={
        "schema_version":1,
        "generated_utc":now.isoformat(timespec="seconds"),
        "source_id":"dwd_icon_hptfg_na",
        "source_page":INDEX,
        "run_utc":records[0]["run_utc"],
        "license":"DWD Open Data, Quelle: Deutscher Wetterdienst",
        "product":"ICON Nordatlantik · Bodendruck, Wetter und Fronten",
        "time_semantics":"Every image contains multiple lead times; the run_utc is read from the DWD filename. The forecast_from_hours/forecast_to_hours bounds DO NOT prove each 6-hour subslot is a separate chart. Display the whole original sheet.",
        "sheets":records,
        "sheet_count":len(records),
        "max_forecast_hours":max(x["forecast_to_hours"] for x in records),
    }
    tmp=output/"dwd_forecasts.json.tmp"
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(output/"dwd_forecasts.json")
    keep={Path(x["image"]).name for x in records}
    for old in images.glob("dwd_icon_na_*.webp"):
        if old.name not in keep:
            old.unlink()
    return manifest
