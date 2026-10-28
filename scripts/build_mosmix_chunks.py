#!/usr/bin/env python3
"""Publish MOSMIX map slices from the verified Germany-only source archive.

The browser reads only one mode/day chunk at a time. Missing original DWD
values remain null; values are never substituted or reconstructed.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BERLIN=ZoneInfo("Europe/Berlin")
MODES={
    "rain1":("RR1c","Regen 1 h","mm"),
    "rain3":("RR3c","Regen 3 h","mm"),
    "rain6":("RR6c","Regen 6 h","mm"),
    "rain12":("RRhc","Regen 12 h","mm"),
    "rain24":("RRdc","Regen 24 h","mm"),
    "gust1":("FX1","Böe 1 h","km/h"),
    "gust3":("FX3","Böe 3 h","km/h"),
    "gust12":("FXh","Böe 12 h","km/h"),
    "cloudN":("N","Gesamtbewölkung","%"),
    "cloudNeff":("Neff","Effektive Bewölkung","%"),
    "cloudNl":("Nl","Tiefe Wolken","%"),
    "cloudNm":("Nm","Mittelhohe Wolken","%"),
    "cloudNh":("Nh","Hohe Wolken","%"),
    "visibility":("VV","Sichtweite","km"),
    "lowVis":("VV10","Wahrsch. Sicht unter 1 km","%"),
    "fog1":("wwM","Nebelwahrscheinlichkeit 1 h","%"),
    "fog6":("wwM6","Nebelwahrscheinlichkeit 6 h","%"),
    "snow1":("RRS1c","Schneeniederschlag (Wasseräquivalent) 1 h","mm"),
    "snow3":("RRS3c","Schneeniederschlag (Wasseräquivalent) 3 h","mm"),
    "snowProb":("wwS","Wahrsch. fester Niederschlag 1 h","%"),
    "thunder1":("wwT","Gewitterwahrscheinlichkeit 1 h","%"),
    "thunder6":("wwT6","Gewitterwahrscheinlichkeit 6 h","%"),
    "conv1":("wwC","Wahrsch. konvektiver Niederschlag 1 h","%"),
    "weatherCode":("ww","Signifikantes Wetter (Code)","Code"),
}


def finite(value):
    return value if isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value) else None


def hour_value(station,mode,index):
    if mode=="hourly":
        a=station.get("values",[])
        return finite(a[index]) if index<len(a) else None
    if mode in ("tmax","tmin"):
        return finite(station.get("tx12" if mode=="tmax" else "tn12",{}).get(str(index)))
    key=MODES[mode][0]
    a=station.get("map_extra",{}).get(key,[])
    value=finite(a[index]) if index<len(a) else None
    if value is None:
        return None
    if mode.startswith("rain") or mode.startswith("gust"):
        return value if value>=0 else None
    if mode.startswith("cloud") or mode in ("lowVis","fog1","fog6","snowProb","thunder1","thunder6","conv1"):
        return value if 0<=value<=100 else None
    if mode=="visibility":
        return value if 0<=value<=100 else None
    if mode=="weatherCode":
        return value if 0<=value<=99 and value==int(value) else None
    if mode.startswith("snow"):
        return value if value>=0 else None
    return value


def local_sun_days(steps):
    grouped=defaultdict(list)
    for index,time in enumerate(steps):
        end=datetime.fromisoformat(time.replace("Z","+00:00"))
        calendar=(end-timedelta(microseconds=1)).astimezone(BERLIN).date()
        grouped[calendar].append((index,end))
    for day,rows in sorted(grouped.items()):
        first=rows[0][1]-timedelta(hours=1)
        last=rows[-1][1]
        if first.astimezone(BERLIN).hour!=0 or first.astimezone(BERLIN).date()!=day:
            continue
        if last.astimezone(BERLIN).hour!=0 or last.astimezone(BERLIN).date()!=day+timedelta(days=1):
            continue
        if any(b[1]-a[1]!=timedelta(hours=1) for a,b in zip(rows,rows[1:])):
            continue
        yield str(day),[index for index,_ in rows]


def calendar_day_stat(station,indices,source,method):
    """Derived calendar aggregate using complete, genuine hourly DWD values."""
    series=station.get("map_extra",{}).get(source,[])
    vals=[]
    for i in indices:
        value=finite(series[i]) if i<len(series) else None
        if value is None or value<0:
            return None
        vals.append(value)
    if not vals:return None
    return round(sum(vals),1) if method=="sum" else round(max(vals),1)


def sun_day_value(station,indices):
    series=station.get("sun1",[])
    minutes=0
    for i in indices:
        value=finite(series[i]) if i<len(series) else None
        if value is None or not 0<=value<=60:
            return None
        minutes+=value
    return round(minutes/60,1)


def save_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf-8")


def build(source,out):
    source=Path(source)
    out=Path(out)
    data=json.loads(source.read_text(encoding="utf-8"))
    if data.get("product")!="DWD MOSMIX-L" or len(data.get("stations",[]))<100:
        raise ValueError("Kein gültiges MOSMIX-L-Deutschlandarchiv")
    steps=data["timesteps"]
    stations=data["stations"]
    metadata={key:entry for key,entry in data.items()
              if key in ("product","issue_time","generated_at","timesteps","station_count","bounds","source_url")}
    metadata["schema"]=2
    metadata["stations"]=[{key:row.get(key) for key in ("id","name","lat","lon","elev_m","key")}
                           for row in stations]
    metadata["modes"]={}
    metadata["units"]={"hourly":"°C","tmax":"°C","tmin":"°C","sun":"h","rainDay":"mm","gustDay":"km/h"}
    metadata["units"].update({mode:spec[2] for mode,spec in MODES.items()})
    timestamps=[datetime.fromisoformat(x.replace("Z","+00:00")) for x in steps]

    def write_mode(mode,entries):
        by_day=defaultdict(list)
        for key,valid,label,values in entries:
            valid_count=sum(v is not None for v in values)
            if valid_count<100:
                continue
            date=key[:10]
            by_day[date].append((key,valid,label,values))
        frames=[]
        for day,rows in sorted(by_day.items()):
            relative=f"maps/{mode}/{day}.json"
            save_json(out/relative,{"issue_time":data["issue_time"],"mode":mode,
                                    "values":[r[3] for r in rows]})
            for pos,row in enumerate(rows):
                key,valid,label,_=row
                frames.append({"key":key,"valid":valid,"label":label,"path":relative,"slot":pos})
        if frames:
            metadata["modes"][mode]=frames
        return len(frames)

    for mode in ["hourly","tmax","tmin",*MODES]:
        entries=[]
        for i,iso in enumerate(steps):
            stamp=timestamps[i]
            if mode=="tmax" and stamp.hour!=18:continue
            if mode=="tmin" and stamp.hour!=6:continue
            label=stamp.strftime("%d.%m.%Y %H UTC")
            values=[hour_value(station,mode,i) for station in stations]
            entries.append((iso,iso,label,values))
        write_mode(mode,entries)

    sun_entries=[]
    rain_day_entries=[]
    gust_day_entries=[]
    for day,indices in local_sun_days(steps):
        sun_entries.append((day,day,day,[sun_day_value(st,indices) for st in stations]))
        rain_day_entries.append((day,day,day,[calendar_day_stat(st,indices,"RR1c","sum") for st in stations]))
        gust_day_entries.append((day,day,day,[calendar_day_stat(st,indices,"FX1","max") for st in stations]))
    write_mode("sun",sun_entries)
    write_mode("rainDay",rain_day_entries)
    write_mode("gustDay",gust_day_entries)
    metadata["availability"]={mode:len(frames) for mode,frames in metadata["modes"].items()}
    # Publishing the manifest last acts as the release-commit indicator;
    # clients never see half-written manifests on a local Pages build.
    save_json(out/"manifest.json",metadata)
    print("MOSMIX-Kacheln:",len(metadata["stations"]),"Stationen",
          len(metadata["modes"]),"Kartenarten",
          sum(len(v) for v in metadata["modes"].values()),"Zeitscheiben")
    return metadata


def main():
    p=argparse.ArgumentParser()
    p.add_argument("input",help="DWD-MOSMIX-Deutschlandquelle (mosmix_ttt.json)")
    p.add_argument("output",help="Ausgabeordner mit manifest.json und maps/")
    args=p.parse_args()
    build(args.input,args.output)


if __name__=="__main__":
    main()
