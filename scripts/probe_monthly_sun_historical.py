#!/usr/bin/env python3
"""Small real DWD KL historical SDK smoke test, without 30-year area build."""
from __future__ import annotations
import io
import zipfile
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
            blob=get(HIST+files[station],timeout=110)
            if station==chosen[0]:
                with zipfile.ZipFile(io.BytesIO(blob)) as z:
                    name=next((n for n in z.namelist() if "produkt_klima_tag" in n.lower() and n.endswith(".txt")),None)
                    print("LIVE DWD FILE",files[station],"name",name,flush=True)
                    if name:
                        rows=z.read(name).decode("latin-1").splitlines()
                        print("LIVE CSV HEADER:",rows[0][:350] if rows else "empty",flush=True)
                        print("LIVE CSV FIRST ROW:",rows[1][:350] if len(rows)>1 else "empty",flush=True)
                        print("LIVE CSV LAST ROW:",rows[-1][:350] if len(rows)>1 else "empty",flush=True)
            norm=parse_sdk_zip(blob)
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
