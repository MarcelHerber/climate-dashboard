#!/usr/bin/env python3
"""Archive verified daily DUETT observations from the existing monthly pipeline.
The archive starts at the first available observation snapshot; no historical
coverage is inferred and no station/model values are mixed into DUETT.
"""
import argparse, json, math
from datetime import date
from pathlib import Path
import requests
from build_bundeslaender_daily import REGIONS, write

URL="https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/state-monthly-sun-obs/observed_sun.json"

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    response=requests.get(URL,timeout=90)
    response.raise_for_status()
    doc=response.json()
    if doc.get("product")!="state_monthly_duett_sunshine_observations" or doc.get("forecast") is not False or doc.get("unit")!="h":
        raise ValueError("Invalid DUETT snapshot")
    dates=doc["dates"]
    if not dates or dates!=sorted(set(dates)) or dates[-1]>=date.today().isoformat() or doc["data_through"]!=dates[-1]:
        raise ValueError("Invalid DUETT dates")
    for d in dates: date.fromisoformat(d)
    for region in REGIONS:
        series=doc["regions"][region]["daily"]
        if len(series)!=len(dates) or any(not isinstance(v,(float,int)) or not math.isfinite(v) or not 0<=v<=24 for v in series):
            raise ValueError("Invalid DUETT daily values")
    for year in sorted({int(d[:4]) for d in dates}):
        path=a.output/f"{year}.json"
        existing=json.loads(path.read_text()) if path.exists() else {"dates":[],"regions":{r:[] for r in REGIONS}}
        by_date={d:{r:existing["regions"][r][i] for r in REGIONS} for i,d in enumerate(existing["dates"])}
        for i,d in enumerate(dates):
            if int(d[:4])==year: by_date[d]={r:doc["regions"][r]["daily"][i] for r in REGIONS}
        keys=sorted(by_date)
        write(path,{"parameter":"sunshine","year":year,"source":"DWD DUETT SDU 1 km","unit":"h","dates":keys,"regions":{r:[by_date[d][r] for d in keys] for r in REGIONS}})
    years=sorted(int(f.stem) for f in a.output.glob("[0-9][0-9][0-9][0-9].json"))
    write(a.output/"index.json",{"parameter":"sunshine","years":years,"regions":REGIONS,"data_through":dates[-1]})
if __name__=="__main__":main()
