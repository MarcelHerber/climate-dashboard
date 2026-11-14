#!/usr/bin/env python3
"""Merge verified DWD hourly weather-turn shards into the Pages archive.

Publication is atomic at the index level: index.json is replaced only after
all worker manifests and every published station document were validated.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
from pathlib import Path
import shutil
from collections import Counter

METRICS={"temperature","pressure","wind_direction"}
HOURS={"1","3","6","12","24"}

def read_json(path:Path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)

def validate_station(doc,station_id):
    if doc.get("schema")!=1 or doc.get("station_id")!=station_id or not doc.get("metrics"):
        raise ValueError(f"Invalid DWD hourly station {station_id}")
    if not (doc.get("name") and doc.get("state")):
        raise ValueError(f"Missing station metadata: {station_id}")
    for metric,entry in doc["metrics"].items():
        if metric not in METRICS:raise ValueError(f"Unknown DWD metric: {metric}")
        if metric=="pressure" and (entry.get("source_column")!="P" or
            entry.get("pressure_reference")!="sea_level" or
            not entry.get("source","").endswith(" · P")):
            raise ValueError(f"Legacy station-altitude P0 pressure rejected: {station_id}")
        if not entry.get("source_url","").startswith("https://opendata.dwd.de/"):
            raise ValueError(f"Non-DWD archive: {station_id}/{metric}")
        period=entry.get("period") or {}
        if not period.get("start") or period["start"]>period.get("end",""):
            raise ValueError(f"Missing DWD period: {station_id}/{metric}")
        if not entry.get("windows"):
            raise ValueError(f"No actual hourly pairs: {station_id}/{metric}")
        for width,group in entry["windows"].items():
            if width not in HOURS or group.get("coverage",{}).get("pairs",0)<1:
                raise ValueError(f"Unsupported or empty hourly window {station_id}/{metric}/{width}")
            for side in ("up","down"):
                for event in group.get(side,[]):
                    if not event.get("start","")<event.get("end","") or not event.get("trace"):
                        raise ValueError(f"Invalid hourly weather change: {station_id}/{metric}/{width}")
    return {"id":station_id,"name":doc["name"],"state":doc["state"],
        "lat":doc["lat"],"lon":doc["lon"],
        "metrics":list(doc["metrics"]),
        "periods":{k:v["period"] for k,v in doc["metrics"].items()}}

def merge(parts:Path,archive:Path,expected_shards:int):
    folders=sorted(p for p in parts.iterdir() if p.is_dir() and (p/"_manifest.json").is_file())
    if len(folders)!=expected_shards:
        raise ValueError(f"Expected {expected_shards} DWD hourly shards, found {len(folders)}")
    seen_shards=set();candidate_hash=None;candidate_count=None
    selected=[];accepted=[];excluded={}
    for folder in folders:
        manifest=read_json(folder/"_manifest.json")
        shard=int(manifest["shard_index"])
        if not (0<=shard<expected_shards) or shard in seen_shards or manifest["shard_count"]!=expected_shards:
            raise ValueError("DWD hourly shards missing or duplicated")
        seen_shards.add(shard)
        fingerprint=manifest["candidate_hash"]
        if candidate_hash is not None and candidate_hash!=fingerprint:
            raise ValueError("Official DWD station inventory changed during shard collection")
        candidate_hash=fingerprint
        total=manifest["candidate_count"]
        if candidate_count is not None and total!=candidate_count:
            raise ValueError("DWD shard candidate counts differ")
        candidate_count=total
        ids=manifest["attempted"]
        if any(sid in selected for sid in ids):
            raise ValueError("A DWD station appears in multiple shards")
        selected.extend(ids)
        valid=manifest["accepted"]
        failures=manifest["excluded"]
        if set(valid)&set(failures) or set(valid)|set(failures)!=set(ids):
            raise ValueError(f"Incomplete DWD hourly shard {shard}")
        for sid in valid:
            path=folder/(sid+".json")
            if not path.is_file() or path.stat().st_size<500:
                raise ValueError(f"Missing verified DWD hour record: {sid}")
            validate_station(read_json(path),sid)
            accepted.append((sid,path))
        excluded.update(failures)
    if len(selected)!=candidate_count or len(seen_shards)!=expected_shards:
        raise ValueError(f"Unprocessed DWD stations: {len(selected)} of {candidate_count}")

    archive.mkdir(parents=True,exist_ok=True)
    previous=archive/"index.json"
    old=read_json(previous) if previous.is_file() else {"stations":[]}
    records={row["id"]:row for row in old.get("stations",[])}
    for sid,path in accepted:
        # Revalidate before replacing the existing file.
        doc=read_json(path)
        entry=validate_station(doc,sid)
        shutil.copyfile(path,archive/(sid+".json"))
        records[sid]=entry
    # Previously published P0 station-height ranks are scientifically
    # incompatible with sea-level P. Keep already validated other metrics,
    # but never carry legacy P0 pressure forward when a new build fails.
    accepted_ids={sid for sid,_ in accepted}
    for sid in set(row["id"] for row in old.get("stations",[])):
        path=archive/(sid+".json")
        if not path.is_file():
            raise ValueError(f"Previously verified DWD station vanished: {sid}")
        if sid in accepted_ids:continue
        doc=read_json(path)
        pressure=doc.get("metrics",{}).get("pressure")
        if pressure and (pressure.get("source_column")!="P" or
                         pressure.get("pressure_reference")!="sea_level"):
            doc["metrics"].pop("pressure")
            doc.setdefault("unavailable_sources",{})["pressure"]=(
                "Legacy DWD P0 is station-level pressure; MSL P not verified")
            path.write_text(json.dumps(doc,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
            if doc["metrics"]:
                records[sid]=validate_station(doc,sid)
            else:
                records.pop(sid,None)
                print("DWD LEGACY PRESSURE-ONLY STATION QUARANTINED",sid,flush=True)
    sorted_records=sorted(records.values(),key=lambda x:(x["state"],x["name"],x["id"]))
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    result={"schema":1,"ready":True,"publisher":"Deutscher Wetterdienst (DWD) CDC",
        "method":"Exact original hourly time pairs; no interpolation, gap-safe, station-specific",
        "generated_at":now,"stations":sorted_records,
        "note":"All DWD hourly stations with at least one validated metric and available hour pairs. Historical coverage differs by station; not a Germany-wide record ranking."}
    coverage={"schema":1,"generated_at":now,"source":"DWD CDC historical hourly directory listings",
        "candidate_count":candidate_count,"validated_in_run":len(accepted),
        "published_count":len(sorted_records),"preserved_from_previous":len(records)-len(accepted),
        "excluded_count":len(excluded),"excluded":excluded,
        "metrics":dict(Counter(m for row in sorted_records for m in row["metrics"]))}
    (archive/"coverage.json").write_text(json.dumps(coverage,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    temporary=archive/"index.json.next"
    temporary.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    temporary.replace(archive/"index.json")
    print("DWD ALL ELIGIBLE HOURLY ARCHIVES",json.dumps({
        "candidates":candidate_count,"validated":len(accepted),
        "published":len(sorted_records),"excluded":len(excluded),
        "metrics":coverage["metrics"]},ensure_ascii=False),flush=True)
    return result,coverage

if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("--parts",type=Path,required=True)
    cli.add_argument("--archive",type=Path,default=Path("data/rekordlabor/weather_turns"))
    cli.add_argument("--expected-shards",type=int,default=8)
    args=cli.parse_args()
    merge(args.parts,args.archive,args.expected_shards)
