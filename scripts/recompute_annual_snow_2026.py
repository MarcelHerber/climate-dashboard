#!/usr/bin/env python3
"""Recompute affected 2026 annual snow records only, using DWD originals + local correction."""
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import update_station_records as dwd
import build_annual_extremes_extra as extra
from annual_snow_corrections import CORRECTION, DAYS, STATION, corrected_snow

YEAR=2026
AREAS=("Deutschland","Hamburg")
LEGACY=("snox_lt_400",)
EXTRA=("snow50_days_lt_400","snow_gain_lt_400")
PATHS=[Path("data/dwd_annual_extremes.json"),Path("data/dwd_annual_extremes_stage1.json"),Path("data/dwd_annual_extra_kl.json")]

def pick(bucket, key, entry, kind):
    old=bucket.get(key)
    if old is None or entry[0]>old[0] or (entry[0]==old[0] and tuple(entry[1:3] if kind=="extreme" else entry[1:2])<tuple(old[1:3] if kind=="extreme" else old[1:2])):
        bucket[key]=entry

def main():
    docs={p:json.loads(p.read_text(encoding="utf-8")) for p in PATHS if p.is_file()}
    assert PATHS[0] in docs and PATHS[1] in docs
    cutoffs={p:date.fromisoformat(d["data_through"][:10]) for p,d in docs.items()}
    end=max(cutoffs.values())
    assert end.year==YEAR and end>=max(DAYS)
    metadata=dwd.parse_metadata(dwd.download(dwd.METADATA_URL,timeout=90))
    meta=metadata.public_dict()
    files=extra.family_files(dwd.HISTORICAL_URL,dwd.HISTORICAL_PATTERN,dwd.RECENT_URL,dwd.RECENT_PATTERN,dwd.STATION_ID_PATTERN,300)
    # Historical ZIPs ending before 2026 cannot affect the target year.
    files={sid:[item for item in entries if item[2] or (re.search(r"_(\d{8})_hist\.zip$",item[1],re.I) and re.search(r"_(\d{8})_hist\.zip$",item[1],re.I).group(1)>="20260101")] for sid,entries in files.items()}
    pairs=[(sid,entries) for sid,entries in sorted(files.items()) if entries]
    assert len(pairs)>=300 and STATION in dict(pairs)
    best={p:{a:{} for a in AREAS} for p in docs}
    verified_days=set();station_days=0
    def read(pair):
        sid,entries=pair
        data=extra.read_station(entries,sid,"KL",end)
        snow={day:{"SHK":row["SHK"]} for day,row in data.items() if day.year==YEAR and "SHK" in row}
        return sid,snow
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i in range(0,len(pairs),16):
            for sid,snow in pool.map(read,pairs[i:i+16]):
                station_days+=len(snow)
                if sid==STATION:
                    for day in DAYS:
                        assert snow[day]["SHK"][0]==25, (day,snow.get(day))
                        verified_days.add(day)
                for p,cut in cutoffs.items():
                    subset={day:row for day,row in snow.items() if day<=cut}
                    if p==PATHS[2]:
                        for area,year,key,entry in extra.station_records(subset,sid,"KL",metadata,cut):
                            if area in AREAS and key in EXTRA:
                                pick(best[p][area],key,entry,extra.METRICS[key]["kind"])
                    else:
                        for day,row in subset.items():
                            seg=metadata.segment_for(sid,day)
                            if seg.height is None or seg.height>=400:continue
                            value,pre=row["SHK"]
                            for area in ["Deutschland"]+(["Hamburg"] if seg.state=="Hamburg" else []):
                                pick(best[p][area],"snox_lt_400",[round(value,1),day.isoformat(),seg.key,int(pre or day.year==YEAR)],"extreme")
            if i%80==0:print(f"{i}/{len(pairs)} Stationen",flush=True)
    assert verified_days==set(DAYS) and station_days>30000
    for p,d in docs.items():
        keys=EXTRA if p==PATHS[2] else LEGACY
        for area in AREAS:
            row=d["records"][area][str(YEAR)]
            for k in keys:
                if k not in d["metrics"]:continue
                old=row.get(k);new=best[p][area].get(k)
                # Refuse to erase an existing record if the replacement network is incomplete.
                if old is not None and new is None:raise RuntimeError(f"Missing replacement {p} {area} {k}")
                if new is not None:
                    kind=d["metrics"][k].get("kind","extreme")
                    st=new[2] if kind=="extreme" else new[1]
                    raw=st.removeprefix("KL:") if p==PATHS[2] else st
                    if raw in meta:d["stations"][st]=meta[raw]
                row[k]=new
                print(p,area,k,old,"=>",new,flush=True)
        d["snow_corrections"]=[CORRECTION]
    # Only write after all source downloads and validations succeed.
    for p,d in docs.items():
        p.write_text(json.dumps(d,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
