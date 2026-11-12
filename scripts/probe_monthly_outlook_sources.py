#!/usr/bin/env python3
"""Limited live smoke test: actual DWD DUETT 1-km SDU and ensemble API data.

Only fetches ONE DUETT daylight NetCDF hour and a single location with two
forecast days per ensemble. Does not publish/change any dashboard data.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

import numpy as np
import requests

from build_monthly_outlook_duett import BASE, get, load_sdu, source_index
from build_state_monthly_ensemble_outlook import MODEL_CONFIG, hourly_sunshine_to_daily, member_keys

API="https://ensemble-api.open-meteo.com/v1/ensemble"


def smoke_duett():
    now=datetime.now(timezone.utc)
    month=now.strftime("%Y%m")
    index=source_index(get(BASE,timeout=120).decode("utf-8",errors="replace"),month)
    choices=sorted((k for k in index if 8<=int(k[8:10])<=15))
    if not choices:
        raise RuntimeError("No daylight-hour DUETT SDU 1-km NetCDF in current month")
    stamp=choices[-1]
    x,y,grid=load_sdu(get(BASE+index[stamp]))
    coverage=float(np.isfinite(grid).mean())
    valid=grid[np.isfinite(grid)]
    if len(x)<100 or len(y)<100 or coverage<0.2 or not len(valid):
        raise RuntimeError("Invalid DUETT 1-km raster extent or coverage")
    if (abs(float(np.median(np.diff(x)))-1000)>1 or
        abs(float(np.median(np.diff(y)))-1000)>1):
        raise RuntimeError("DWD DUETT coordinate spacing is not 1 km")
    print("LIVE DUETT",index[stamp],"grid",grid.shape,
          "finite coverage",round(coverage,3),
          "SDU min range",round(float(valid.min()),2),round(float(valid.max()),2),
          flush=True)


def smoke_model(key):
    model=MODEL_CONFIG[key]["api_model"]
    location={"latitude":50.1,"longitude":8.7,"models":model,
              "forecast_days":2,"past_days":0,"timezone":"GMT",
              "cell_selection":"land"}
    result={}
    for field,variable in [("hourly","sunshine_duration"),("daily","precipitation_sum")]:
        params={**location,field:variable}
        r=requests.get(API,params=params,timeout=75,
                       headers={"User-Agent":"climate-dashboard-source-smoke/1.0"})
        r.raise_for_status()
        payload=r.json()
        if isinstance(payload,list):
            payload=payload[0]
        if field=="hourly":
            day=hourly_sunshine_to_daily(payload).get("daily",{})
            keys=member_keys(day,"sunshine_duration")
            if not keys or not day.get("time") or not any(v is not None for v in day[keys[0]]):
                raise RuntimeError(f"{key} returned no complete sunshine member days")
        else:
            daily=payload.get("daily") or {}
            keys=member_keys(daily,"precipitation_sum")
            if not keys or not daily.get("time"):
                raise RuntimeError(f"{key} returned no precipitation ensemble days")
        result[field]={"members":len(keys),"days":len((day if field=="hourly" else daily)["time"])}
    print("LIVE ENSEMBLE",key,json.dumps(result),flush=True)


def main():
    smoke_duett()
    errors={}
    success=0
    for key in MODEL_CONFIG:
        try:
            smoke_model(key)
            success+=1
        except Exception as exc:
            errors[key]=str(exc)
            print("LIVE ENSEMBLE ERROR",key,str(exc),flush=True)
    if errors:
        raise RuntimeError(f"Ensemble variable checks failed for: {errors}")
    print("LIVE source smoke OK:",success,"/ 4 models",flush=True)


if __name__=="__main__":
    main()
