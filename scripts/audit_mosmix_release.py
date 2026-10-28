#!/usr/bin/env python3
"""Fail closed before publishing DWD MOSMIX-L to mosmix-data/Pages.

Check every advertised map file, run-time identity, physical ranges and a
sample of exact original station forecasts. Optional parameters may be
absent, but an advertised map must never be empty or corrupt.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

CORE_MODES=("hourly","tmax","tmin","sun")
WEATHER_PROB=("fog1","fog6","lowVis","snowProb","thunder1","thunder6","conv1")
CLOUD=("cloudN","cloudNeff","cloudNl","cloudNm","cloudNh")
RAINS=("rain1","rain3","rain6","rain12","rain24","rainDay","snow1","snow3")
GUSTS=("gust1","gust3","gust12","gustDay")
ALL=set(CORE_MODES+WEATHER_PROB+CLOUD+RAINS+GUSTS+("visibility","weatherCode"))
ORIGINAL_SOURCE={"rain1":"RR1c","rain3":"RR3c","rain6":"RR6c",
                 "rain12":"RRhc","rain24":"RRdc",
                 "gust1":"FX1","gust3":"FX3","gust12":"FXh",
                 "cloudN":"N","cloudNeff":"Neff","cloudNl":"Nl",
                 "cloudNm":"Nm","cloudNh":"Nh","visibility":"VV",
                 "lowVis":"VV10","fog1":"wwM","fog6":"wwM6",
                 "snow1":"RRS1c","snow3":"RRS3c","snowProb":"wwS",
                 "thunder1":"wwT","thunder6":"wwT6","conv1":"wwC",
                 "weatherCode":"ww"}

def audit(directory, original):
    root=Path(directory)
    original=json.loads(Path(original).read_text(encoding="utf-8"))
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    assert original["product"]=="DWD MOSMIX-L"
    assert manifest["schema"]==2
    assert manifest["issue_time"]==original["issue_time"]
    n=len(original["stations"])
    assert 100<n==len(manifest["stations"])
    keys=[s["key"] for s in manifest["stations"]]
    assert keys==[s["key"] for s in original["stations"]]
    assert len(set(keys))==n
    assert len(manifest["modes"]["hourly"])>40
    assert len(manifest["modes"]["tmax"])>=2
    assert len(manifest["modes"]["tmin"])>=2
    assert len(manifest["modes"]["sun"])>=2
    counts={}
    for mode,frames in manifest["modes"].items():
        assert mode in ALL,(mode,"unknown mode")
        assert frames
        prev=""
        by_path={}
        for frame in frames:
            key=frame["key"]
            assert key>prev,(mode,"frames not chronological")
            prev=key
            path=Path(frame["path"])
            assert not path.is_absolute() and ".." not in path.parts
            assert path.parts[0]=="maps" and path.parts[1]==mode
            by_path.setdefault(path,[]).append(frame)
        for path,group in by_path.items():
            chunk=json.loads((root/path).read_text(encoding="utf-8"))
            assert chunk["issue_time"]==manifest["issue_time"],(mode,path)
            assert chunk["mode"]==mode
            values=chunk["values"]
            for frame in group:
                arr=values[frame["slot"]]
                assert len(arr)==n,(mode,path,len(arr),n)
                valid=0
                for val in arr:
                    if val is None:continue
                    assert isinstance(val,(float,int)) and not isinstance(val,bool)
                    assert math.isfinite(val),(mode,val)
                    if mode in CLOUD+WEATHER_PROB:
                        assert 0<=val<=100,(mode,val)
                    elif mode=="weatherCode":
                        assert 0<=val<=99 and val==int(val)
                    elif mode=="visibility":
                        assert 0<=val<=100
                    elif mode in RAINS+GUSTS+("sun",):
                        assert val>=0,(mode,val)
                    valid+=1
                assert valid>=100,(mode,path,"too few values",valid)
                if mode in ORIGINAL_SOURCE and mode not in ("rainDay","gustDay"):
                    source_key=ORIGINAL_SOURCE[mode]
                    if source_key:
                        index=original["timesteps"].index(frame["valid"])
                        for i in (0,n//3,2*n//3,n-1):
                            source_values=original["stations"][i].get("map_extra",{}).get(source_key,[])
                            expect=source_values[index] if index<len(source_values) else None
                            actual=arr[i]
                            if isinstance(expect,(int,float)) and math.isfinite(expect):
                                assert actual==expect,(mode,frame["valid"],i,actual,expect)
        counts[mode]=len(frames)
    print("MOSMIX Qualität bestanden:",manifest["issue_time"],
          "| Stationen",n,"| Modi",len(counts),
          "| geprüfte Zeitkarten",sum(counts.values()))
    return counts

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("original")
    args=p.parse_args()
    audit(args.root,args.original)
