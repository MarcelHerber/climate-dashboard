#!/usr/bin/env python3
"""Independently probe genuine ECMWF IFS open 2m-temperature forecasts.

Only verifies freely reusable ECMWF IFS 0.25-degree GRIB2, its exact forecast
steps, valid UTC times, geographic grid and provenance. Does NOT invent any
1991–2020 ERA5 normal, or publish an unsupported IFS anomaly.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np

VALID_STEPS=(3,24,168)
GRIB_GRID=(1440,721)


def check_message(gid, ec, requested_step: int) -> dict:
    def val(name):
        return ec.codes_get(gid,name)
    if (int(val("edition"))!=2 or str(val("typeOfLevel"))!="heightAboveGround"
        or int(val("level"))!=2 or int(val("discipline"))!=0
        or int(val("parameterCategory"))!=0
        or int(val("parameterNumber"))!=0):
        raise ValueError("ECMWF GRIB is not an authentic 2m temperature field")
    if int(val("forecastTime"))!=requested_step or str(val("stepRange")) not in (
        str(requested_step),f"{requested_step}-{requested_step}"):
        raise ValueError("ECMWF forecast step is not the requested instantaneous field")
    if (int(val("Ni")),int(val("Nj")))!=GRIB_GRID:
        raise ValueError("ECMWF open 0.25 degree GRIB does not have the expected global grid")
    if abs(float(val("latitudeOfFirstGridPointInDegrees"))-90)>0.01:
        raise ValueError("ECMWF latitude origin differs from 90 deg N")
    date=int(val("dataDate"))
    time=int(val("dataTime"))
    valid_date=int(val("validityDate"))
    valid_time=int(val("validityTime"))
    run=datetime.strptime(f"{date:08d}{time:04d}","%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    valid=run+timedelta(hours=requested_step)
    if valid_date!=int(valid.strftime("%Y%m%d")) or valid_time!=int(valid.strftime("%H%M")):
        raise ValueError("ECMWF valid time and analysis time disagree with forecast lead")
    vals=np.asarray(ec.codes_get_values(gid),dtype=np.float32).reshape(GRIB_GRID[1],GRIB_GRID[0])
    if not np.isfinite(vals).all() or not np.all((vals>170)&(vals<340)):
        raise ValueError("Invalid ECMWF global 2m temperatures")
    return {
        "run_utc":run.isoformat().replace("+00:00","Z"),
        "valid_utc":valid.isoformat().replace("+00:00","Z"),
        "step_hours":requested_step,
        "min_k":round(float(vals.min()),2),
        "max_k":round(float(vals.max()),2),
        "mean_europe_c":round(float(vals[80:240,1360:1440].mean()-273.15),2),
        "ni":GRIB_GRID[0],"nj":GRIB_GRID[1]
    }


def probe(target: Path, source: str = "ecmwf") -> dict:
    import eccodes as ec
    from ecmwf.opendata import Client

    client=Client(source=source,model="ifs",resol="0p25")
    # Select latest completed 00Z ECMWF IFS deterministic forecast.
    # A request for step 168 ensures that the full 7-day horizon is available.
    target.parent.mkdir(parents=True,exist_ok=True)
    info={}
    with tempfile.TemporaryDirectory() as tmp:
        grib=Path(tmp)/"ifs_2t_samples.grib2"
        retrieval=client.retrieve(time=0,stream="oper",type="fc",
                                  step=list(VALID_STEPS),param="2t",
                                  target=str(grib))
        if not grib.is_file() or grib.stat().st_size<50_000:
            raise RuntimeError("ECMWF returned no authentic 0.25 degree 2t GRIB2")
        raw=grib.read_bytes()
        info["sha256"]=hashlib.sha256(raw).hexdigest()
        info["bytes"]=len(raw)
        fields=[]
        with grib.open("rb") as f:
            while (gid:=ec.codes_grib_new_from_file(f)) is not None:
                try:
                    lead=int(ec.codes_get(gid,"forecastTime"))
                    if lead not in VALID_STEPS:
                        raise ValueError(f"Unexpected ECMWF forecast step: {lead}")
                    if any(row["step_hours"]==lead for row in fields):
                        raise ValueError("Duplicate ECMWF step")
                    fields.append(check_message(gid,ec,lead))
                finally:
                    ec.codes_release(gid)
        if len(fields)!=len(VALID_STEPS) or sorted(x["step_hours"] for x in fields)!=list(VALID_STEPS):
            raise RuntimeError("ECMWF IFS has not supplied all 3 requested 2t forecast steps")
        if len({x["run_utc"] for x in fields})!=1:
            raise ValueError("Cannot mix different ECMWF IFS model initializations")
        info.update({
            "source":"ECMWF IFS open data 0.25 degree, CC BY 4.0",
            "model":"ifs","stream":"oper","type":"fc","param":"2t",
            "resolution_degrees":0.25,"grid":GRIB_GRID,
            "provenance_verified":True,
            "anomaly_ready":False,
            "reason":"ERA5 / ECMWF model-consistent 1991-2020 reference not prepared",
            "runs":fields
        })
    target.write_text(json.dumps(info,indent=2),encoding="utf-8")
    print(json.dumps(info,indent=2),flush=True)
    return info


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=Path("gfs_analysis_europe/ecmwf_ifs_open_2t_pilot.json"))
    parser.add_argument("--source",choices=["ecmwf","aws","google","azure"],default="ecmwf")
    args=parser.parse_args()
    probe(args.out,args.source)
