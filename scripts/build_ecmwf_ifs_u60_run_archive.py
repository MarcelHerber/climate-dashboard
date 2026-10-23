#!/usr/bin/env python3
"""ECMWF IFS 10 hPa 60N zonal U-wind: authentic run-by-run archive.

Only use released ECMWF open data (CC BY 4.0). No synthetic forecasts,
no interpolation of missing steps, no replacement with GEFS data.
At 0.25 degrees 60N contains exactly 1440 distinct longitudes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import tempfile

import numpy as np

LOG=logging.getLogger("ecmwf-ifs-u60")
LEVEL_HPA=10
LATITUDE=60.0
LONGITUDES=1440
STEPS=list(range(0,361,12))
MAX_RUNS=61
MAX_AGE_DAYS=32

def mean_u60(latitude,longitude,wind):
    """Arithmetically average *u*, not wind speed, around the full 60N circle."""
    latitude=np.asarray(latitude,dtype=np.float64)
    longitude=np.asarray(longitude,dtype=np.float64)
    wind=np.asarray(wind,dtype=np.float64)
    if latitude.shape!=longitude.shape or wind.shape!=latitude.shape:
        raise ValueError("ECMWF latitude/longitude/velocity shapes differ")
    validrow=np.isclose(latitude,LATITUDE,atol=.002)
    lons=np.mod(longitude[validrow],360.0)
    values=wind[validrow]
    if len(lons)!=LONGITUDES or len(np.unique(np.rint(lons*4).astype(int)))!=LONGITUDES:
        raise ValueError(f"ECMWF 60N full longitude circle unavailable: {len(lons)}/{LONGITUDES}")
    if not np.isfinite(values).all() or np.any((values<=-160)|(values>=170)):
        raise ValueError("ECMWF 10 hPa U wind includes missing/out-of-range grid points")
    return round(float(np.mean(values,dtype=np.float64)),3)

def extract_run(path,cycle):
    """Read GRIB2 messages, independently check cycle, pressure and all 31 leads."""
    import eccodes
    row_indices=None
    keys=None
    result={}
    with path.open("rb") as src:
        while True:
            h=eccodes.codes_grib_new_from_file(src)
            if h is None:break
            try:
                field=str(eccodes.codes_get(h,"shortName")).lower()
                level=int(eccodes.codes_get(h,"level"))
                kind=str(eccodes.codes_get(h,"typeOfLevel"))
                date=int(eccodes.codes_get(h,"dataDate"))
                time=int(eccodes.codes_get(h,"dataTime"))
                step=int(eccodes.codes_get(h,"endStep"))
                if field!="u" or level!=LEVEL_HPA or kind!="isobaricInhPa":
                    raise ValueError(f"Unexpected ECMWF GRIB field {field}/{kind}/{level}")
                if date!=int(cycle.strftime("%Y%m%d")) or time!=cycle.hour*100:
                    raise ValueError("ECMWF field belongs to a different model cycle")
                if step not in STEPS or step in result:
                    raise ValueError(f"Unexpected/duplicate ECMWF forecast hour {step}")
                values=np.asarray(eccodes.codes_get_values(h),dtype=np.float64)
                if row_indices is None:
                    latitude=np.asarray(eccodes.codes_get_array(h,"latitudes"),dtype=np.float64)
                    longitude=np.asarray(eccodes.codes_get_array(h,"longitudes"),dtype=np.float64)
                    # Confirm the 60N ring and retain its original ordering for
                    # the later messages of the same regular lat-lon field.
                    row_indices=np.flatnonzero(np.isclose(latitude,LATITUDE,atol=.002))
                    longitude_ring=np.mod(longitude[row_indices],360.0)
                    if len(row_indices)!=LONGITUDES or len(np.unique(np.rint(longitude_ring*4).astype(int)))!=LONGITUDES:
                        raise ValueError("Incomplete 60N zonal ring")
                    keys=(len(values),str(eccodes.codes_get(h,"gridType")))
                if len(values)!=keys[0] or str(eccodes.codes_get(h,"gridType"))!=keys[1]:
                    raise ValueError("Inconsistent forecast GRIB grid")
                wind=values[row_indices]
                if not np.isfinite(wind).all() or np.any((wind<=-160)|(wind>=170)):
                    raise ValueError(f"Bad/missing ECMWF wind at +{step} h")
                result[step]=round(float(np.mean(wind,dtype=np.float64)),3)
            finally:
                eccodes.codes_release(h)
    if sorted(result)!=STEPS:
        raise ValueError(f"Incomplete forecast: got {len(result)}/{len(STEPS)} steps")
    return [result[step] for step in STEPS]

def validate_run(item):
    try:
        cycle=datetime.fromisoformat(item["cycle_utc"].replace("Z","+00:00"))
        if cycle.tzinfo is None or cycle.hour not in (0,12) or cycle.minute!=0: return False
        if cycle.hour!=0 and cycle.hour!=12:return False
        return (item.get("steps_hours")==STEPS and
                len(item.get("values",[]))==len(STEPS) and
                all(isinstance(x,(float,int)) and np.isfinite(x) and -160<x<170
                    for x in item["values"]))
    except (KeyError,TypeError,ValueError):return False

def cycle_candidates(now):
    current=now.replace(minute=0,second=0,microsecond=0)
    start=current.replace(hour=12 if current.hour>=12 else 0)
    return [start-timedelta(hours=12*i) for i in range(8)]

def build(dest,max_new=1,source="ecmwf",now=None):
    from ecmwf.opendata import Client
    now=now or datetime.now(timezone.utc)
    dest.parent.mkdir(parents=True,exist_ok=True)
    previous={}
    if dest.exists():
        try:previous=json.loads(dest.read_text(encoding="utf-8"))
        except (OSError,ValueError):pass
    retained=[item for item in previous.get("runs",[]) if validate_run(item) and
        timedelta(0)<=now-datetime.fromisoformat(item["cycle_utc"].replace("Z","+00:00"))<timedelta(days=MAX_AGE_DAYS)]
    by_cycle={r["cycle_utc"]:r for r in retained}
    client=Client(source=source,model="ifs",resol="0p25")
    added=0
    # ECMWF keeps only approx. 12 recent operational runs. Archive every
    # successful cycle for the next 30 days as it arrives.
    for cycle in cycle_candidates(now):
        if added>=max_new:break
        if now-cycle<timedelta(hours=8):continue
        key=cycle.strftime("%Y-%m-%dT%H:00:00Z")
        if key in by_cycle:continue
        try:
            with tempfile.TemporaryDirectory() as tempdir:
                target=Path(tempdir)/"ecmwf-u10.grib2"
                client.retrieve(date=cycle.strftime("%Y%m%d"),time=cycle.hour,
                    stream="oper",type="fc",levtype="pl",param="u",levelist=10,
                    step=STEPS,target=str(target))
                if target.stat().st_size<30000:
                    raise ValueError("GRIB returned too few bytes for a real cycle")
                series=extract_run(target,cycle)
            by_cycle[key]={"cycle_utc":key,"steps_hours":STEPS,"values":series}
            added+=1
            LOG.info("Verified full ECMWF %s 10hPa U forecast: %s lead steps",key,len(series))
        except Exception as exc:
            LOG.warning("ECMWF cycle %s not available/complete: %s",key,exc)
    if not by_cycle:
        raise RuntimeError("No verified complete ECMWF IFS U60 run; refusing to publish")
    runs=sorted(by_cycle.values(),key=lambda r:r["cycle_utc"],reverse=True)[:MAX_RUNS]
    latest=runs[0]
    result={
        "schema_version":1,"provider":"ECMWF IFS","stream":"oper",
        "resolution_degrees":0.25,"parameter":"u",
        "level_hpa":LEVEL_HPA,"latitude_deg":LATITUDE,"units":"m/s",
        "statistic":"zonal mean of 1440 valid U component values at exactly 60°N",
        "license":"CC BY 4.0","source_url":"https://www.ecmwf.int/en/forecasts/datasets/open-data",
        "forecast_step_hours":STEPS,"horizon_hours":360,
        "latest_cycle_utc":latest["cycle_utc"],"generated_utc":now.isoformat(),
        "runs":runs,"run_count":len(runs)
    }
    dest.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    LOG.info("Stored %s ECMWF runs (%s new), latest %s",len(runs),added,latest["cycle_utc"])
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path("data/stratosphere/ecmwf/ifs_runs.json"))
    parser.add_argument("--max-new",type=int,default=1)
    parser.add_argument("--source",default="ecmwf")
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    build(args.output,max_new=args.max_new,source=args.source)

if __name__=="__main__":main()
