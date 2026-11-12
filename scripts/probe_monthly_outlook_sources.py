#!/usr/bin/env python3
"""Limited live smoke test: actual DWD DUETT 1-km SDU and ensemble API data.

Only fetches ONE DUETT daylight NetCDF hour and a single location with two
forecast days per ensemble. Does not publish/change any dashboard data.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

from build_monthly_outlook_duett import BASE, get, load_sdu, source_index, area_hourly_minutes
from build_state_monthly_ensemble_outlook import MODEL_CONFIG, hourly_sunshine_to_daily, hourly_precipitation_to_hyras_day, member_keys
from build_hyras_tmean_regions import build_masks, load_states

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
    if (abs(abs(float(np.median(np.diff(x))))-1000)>1 or
        abs(abs(float(np.median(np.diff(y))))-1000)>1):
        raise RuntimeError("DWD DUETT coordinate spacing is not 1 km")
    print("LIVE DUETT",index[stamp],"grid",grid.shape,
          "finite coverage",round(coverage,3),
          "SDU min range",round(float(valid.min()),2),round(float(valid.max()),2),
          flush=True)

    # Validate one entire real DWD synoptic day against all 17 geographic
    # masks. This is a small smoke check; the full monthly job uses the
    # same routine with the cached data branch.
    earliest=(now-timedelta(days=1)).strftime("%Y%m%d")
    dates=sorted({stamp[:8] for stamp in index if stamp[:8]<=earliest})
    full_days=[day for day in dates if all(day+f"{hour:02d}50" in index for hour in range(24))]
    if not full_days:
        raise RuntimeError("No 24-hour-complete DUETT day for full-day smoke")
    last_day=full_days[-1]
    masks=build_masks(load_states(Path("/tmp/monthly-outlook-duett-smoke")),x,y)
    running={key:0.0 for key in masks}
    for hour in range(24):
        timestamp=last_day+f"{hour:02d}50"
        xx,yy,field=load_sdu(get(BASE+index[timestamp]))
        if not np.array_equal(xx,x) or not np.array_equal(yy,y):
            raise RuntimeError("DUETT spatial grid changed within the day")
        means=area_hourly_minutes(field,masks)
        for region,value in means.items():
            running[region]+=value/60
    if len(running)!=17 or any(not 0<=v<=24 for v in running.values()):
        raise RuntimeError("Invalid DUETT full-day sunshine region summary")
    print("LIVE DUETT DAY",last_day,"24 complete synoptic hours",
          "Germany",round(running["Deutschland"],2),"h",
          "regions",len(running),flush=True)


def smoke_model(key):
    model=MODEL_CONFIG[key]["api_model"]
    location={"latitude":50.1,"longitude":8.7,"models":model,
              "forecast_days":2,"past_days":0,"timezone":"GMT",
              "cell_selection":"land"}
    result={}
    for variable in ("sunshine_duration", "precipitation"):
        params={**location,"hourly":variable}
        r=requests.get(API,params=params,timeout=75,
                       headers={"User-Agent":"climate-dashboard-source-smoke/1.0"})
        r.raise_for_status()
        payload=r.json()
        if isinstance(payload,list):
            payload=payload[0]
        if variable=="sunshine_duration":
            day=hourly_sunshine_to_daily(payload).get("daily",{})
        else:
            day=hourly_precipitation_to_hyras_day(payload).get("daily",{})
        keys=member_keys(day,variable)
        if not keys or not day.get("time") or not any(v is not None for v in day[keys[0]]):
            raise RuntimeError(f"{key} returned no complete {variable} member days")
        result[variable]={"members":len(keys),"days":len(day["time"])}
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
