"""Build small calendar-day winner series from the verified regional archive."""
import argparse
import calendar
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

PARTITIONS = ("1750-1900","1901-1920","1921-1940","1941-1960","1961-1980","1981-1990","1991-2000","2001-2010","2011-2020","2021-2026")
DAYS = [(dt.date(2000,1,1)+dt.timedelta(days=i)).strftime("%m-%d") for i in range(366)]

def reduce_day(parts, md, current_year):
    """Return historical and comparison-year winners, with original metadata.

    A value tie uses the same year/station-ID/station-key order as the Top 50.
    Results include nulls instead of inventing measurements.
    """
    manifest = parts[0][0]
    result = {metric:{area:[None,None] for area in manifest["areas"]} for metric in manifest["metrics"]}
    winners = {}
    for m, rows in parts:
        if m["metrics"] != manifest["metrics"] or m["areas"] != manifest["areas"]:
            raise ValueError("Inconsistent archive metadata")
        stations = m["stations"]
        for year, metrics in rows:
            if year > current_year or (md == "02-29" and not calendar.isleap(year)):
                continue
            slot = int(year == current_year)
            for metric, areas in metrics.items():
                sign = 1 if m["metrics"][metric]["direction"] == "asc" else -1
                for area, candidates in areas.items():
                    # The archive contains the top 50 per year and region.
                    # Scan every candidate, so even ties use the exact UI order.
                    key = (metric,area,slot)
                    previous = winners.get(key)
                    for value, station_index, preliminary in candidates:
                        if previous is not None and sign*value > previous[0]:
                            continue
                        station = stations[station_index]
                        candidate = (sign*value,year,station["id"],station["key"])
                        if previous is None or candidate < previous:
                            previous = candidate
                            winners[key] = candidate
                            result[metric][area][slot] = [value,year,station["id"],station["name"],int(bool(preliminary))]
    return result

def load_part(folder, manifest, md):
    info = manifest["files"][md]
    data = (folder/(md+".json.gz")).read_bytes()
    if len(data) != info["bytes"] or hashlib.sha256(data).hexdigest() != info["sha256"]:
        raise ValueError(f"Archive integrity failed: {folder.name}/{md}")
    return manifest,json.loads(gzip.decompress(data))

def build(source, destination):
    folders=[source/p for p in PARTITIONS]
    manifests=[json.loads((f/"manifest.json").read_text()) for f in folders]
    latest=manifests[-1]["last"]
    data_end=max(m["data_end"] for m in manifests if m["data_end"])
    areas=manifests[0]["areas"]
    metrics=manifests[0]["metrics"]
    data={metric:{area:[] for area in areas} for metric in metrics}
    for i,md in enumerate(DAYS):
        rows=reduce_day([load_part(folder,m,md) for folder,m in zip(folders,manifests)],md,latest)
        for metric in metrics:
            for area in areas:
                data[metric][area].append(rows[metric][area])
        if i%30==0: print(f"{i+1}/366 calendar days",flush=True)
    destination.mkdir(parents=True,exist_ok=True)
    for metric in metrics:
        for index,area in enumerate(areas):
            doc={"schema":1,"metric":metric,"area":area,"unit":metrics[metric]["unit"],"label":metrics[metric]["label"],"direction":metrics[metric]["direction"],"start":manifests[0]["first"],"historical_end":latest-1,"current_year":latest,"data_end":data_end,"rows":data[metric][area]}
            (destination/f"{metric}-{index}.json").write_text(json.dumps(doc,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print(f"Wrote {len(metrics)*len(areas)} series, each 366 days, archive through {data_end}")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("source",type=Path)
    parser.add_argument("destination",type=Path)
    args=parser.parse_args()
    build(args.source,args.destination)
