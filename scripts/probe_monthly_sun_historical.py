#!/usr/bin/env python3
"""Small real DWD KL historical SDK smoke test, without 30-year area build."""
from __future__ import annotations
from build_monthly_outlook_daily_sun_reference import (
    HIST, available_station_zips, get, parse_sdk_zip, stations_metadata
)


def main():
    listing=get(HIST,timeout=110).decode("latin-1")
    positions=stations_metadata(get(HIST+"KL_Tageswerte_Beschreibung_Stationen.txt").decode("latin-1"))
    files=available_station_zips(listing,positions)
    print("LIVE eligible historical DWD KL files:",len(files),flush=True)
    ids=sorted(files)
    chosen=[ids[min(len(ids)-1,int(i*(len(ids)-1)/9))] for i in range(10)]
    parsed=[]
    for station in chosen:
        try:
            norm=parse_sdk_zip(get(HIST+files[station],timeout=110))
            valid=sum(v is not None for v in norm["daily_h"])
            print(station,valid,"valid historical SDK calendar-day means",flush=True)
            if valid>=330:parsed.append(station)
        except Exception as exc:
            print(station,"could not parse SDK:",exc,flush=True)
    if len(parsed)<2:
        raise RuntimeError("Historical DWD KL station sunshine coverage not confirmed: "+str(parsed))
    print("LIVE DWD KL sunshine source OK:",len(parsed),"of",len(chosen),"sample stations")


if __name__=="__main__":
    main()
