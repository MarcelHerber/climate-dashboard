#!/usr/bin/env python3
"""Daily ECMWF IFS ENS 50-member EOF NAO and AO *independent* experimental indices.

ECMWF Open Data stream=enfo/type=pf, parameter gh, 500/1000 hPa, day 0-15.
NCEP monthly EOF climatology is independently trained and out-of-sample
validated against observed NOAA/CPC indices. NAO is a single-domain EOF
approximation, not the CPC seasonal multi-pattern REOF index.

All values are computed from actual model members. No synthetic gap filling,
no re-labelling of ECMWF weather-regime probabilities as CPC indices.
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import eccodes
import numpy as np
from ecmwf.opendata import Client

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=ROOT/"data/nao_ao_forecast/eof_reference.json"
OUTPUT=ROOT/"data/nao_ao_forecast/ecmwf_indices.json"
MEMBERS=tuple(range(1,51))
LEADS=tuple(range(0,361,24))
LEVELS={"nao":500,"ao":1000}


def percentile(values:list[float],q:float)->float:
    series=sorted(values)
    index=q*(len(series)-1)
    lo=int(math.floor(index));hi=int(math.ceil(index))
    return series[lo]+(series[hi]-series[lo])*(index-lo)


def baseline_for_date(climatology:np.ndarray,day:date)->np.ndarray:
    # Smooth climatological monthly means around the fifteenth of each month.
    mid=day.replace(day=15)
    if day>=mid:
        next_mid=(mid+timedelta(days=20)).replace(day=15)
        left,right=mid,next_mid
    else:
        prev_mid=(mid-timedelta(days=20)).replace(day=15)
        left,right=prev_mid,mid
    ratio=(day-left).days/(right-left).days
    return (1-ratio)*climatology[left.month-1]+ratio*climatology[right.month-1]


def precompute(reference:dict)->dict:
    out={}
    for idx,level in LEVELS.items():
        section=reference["indices"][idx]
        assert int(section["pressure_hpa"])==level
        quality=section["quality"]
        if quality["holdout_correlation"]<.55 or quality["holdout_rmse"]>1.3:
            raise RuntimeError(f"{idx} EOF not validated")
        lats=np.asarray(section["latitude_deg_n"],dtype=np.float64)
        lons=np.asarray(section["longitude_deg_e"],dtype=np.float64)
        eof=np.asarray(section["weighted_eof"],dtype=np.float64)
        area=np.asarray(section["area_weight"],dtype=np.float64)
        climate=np.asarray(section["climatology_gpm"],dtype=np.float64)
        assert eof.shape==area.shape==(len(lats),len(lons))
        assert climate.shape==(12,len(lats),len(lons))
        assert np.all(np.isfinite(eof)) and np.all(np.isfinite(climate))
        assert len(lats)==29 and np.all(np.diff(lats)<0)
        out[level]={
            "name":idx,"lats":lats,"lons":lons,
            "climate":climate,"basis":(eof*area).ravel(),
            "slope":float(section["cpc_fit_slope"]),
            "intercept":float(section["cpc_fit_intercept"]),
        }
    return out


def grid_sample(values:np.ndarray,grib,ref)->np.ndarray:
    ni=int(eccodes.codes_get(grib,"Ni"));nj=int(eccodes.codes_get(grib,"Nj"))
    if ni!=1440 or nj!=721 or len(values)!=ni*nj:
        raise RuntimeError(f"Unexpected ECMWF source grid {ni}x{nj}, values {len(values)}")
    north=float(eccodes.codes_get(grib,"latitudeOfFirstGridPointInDegrees"))
    west=float(eccodes.codes_get(grib,"longitudeOfFirstGridPointInDegrees"))
    lat_step=float(eccodes.codes_get(grib,"jDirectionIncrementInDegrees"))
    lon_step=float(eccodes.codes_get(grib,"iDirectionIncrementInDegrees"))
    if not (abs(north-90)<.01 and abs(lat_step-.25)<.001 and abs(lon_step-.25)<.001):
        raise RuntimeError(f"Unexpected IFS latitude/longitude geometry: {north},{west},{lat_step},{lon_step}")
    rows=np.rint((north-ref["lats"])/lat_step).astype(int)
    cols=np.rint(((ref["lons"]-west)%360)/lon_step).astype(int)%ni
    if np.any(rows<0) or np.any(rows>=nj) or np.any(cols<0) or np.any(cols>=ni):
        raise RuntimeError("Reference extends outside IFS spatial grid")
    z=values.reshape(nj,ni)[np.ix_(rows,cols)]
    if z.shape!=(len(rows),len(cols)) or not np.all(np.isfinite(z)):
        raise RuntimeError("ECMWF member contains invalid height values")
    return z


def project(z:np.ndarray,ref,day:date)->float:
    clim=baseline_for_date(ref["climate"],day)
    raw=float(np.dot((z-clim).ravel(),ref["basis"]))
    value=raw*ref["slope"]+ref["intercept"]
    if not math.isfinite(value) or abs(value)>15:
        raise RuntimeError(f"Implausible normalized {ref['name']} index: {value}")
    return round(value,3)


def parse_step(path:Path,reference:dict,expected_run:date,lead:int):
    output={"nao":{},"ao":{}}
    expected_date=int(expected_run.strftime("%Y%m%d"))
    when=expected_run+timedelta(days=lead//24)
    count=0
    with path.open("rb") as stream:
        while True:
            grib=eccodes.codes_grib_new_from_file(stream)
            if grib is None:break
            try:
                level=int(eccodes.codes_get(grib,"level"))
                member=int(eccodes.codes_get(grib,"number"))
                date_value=int(eccodes.codes_get(grib,"dataDate"))
                utc_hour=int(eccodes.codes_get(grib,"dataTime"))
                actual_step=int(eccodes.codes_get(grib,"step"))
                par=str(eccodes.codes_get(grib,"shortName"))
                if (level not in reference or member not in MEMBERS or
                        par!="gh" or date_value!=expected_date or utc_hour!=0 or
                        actual_step!=lead or
                        str(eccodes.codes_get(grib,"typeOfLevel"))!="isobaricInhPa"):
                    raise RuntimeError(f"Unrecognized ECMWF field {par}, {member=}, {level=}, {date_value=}, {actual_step=}")
                dest=output[reference[level]["name"]]
                if member in dest:raise RuntimeError(f"Duplicate EPS member {member} at level {level}")
                values=np.asarray(eccodes.codes_get_values(grib),dtype=np.float64)
                z=grid_sample(values,grib,reference[level])
                dest[member]=project(z,reference[level],when)
                count+=1
            finally:
                eccodes.codes_release(grib)
    if count!=100 or any(set(output[idx])!=set(MEMBERS) for idx in output):
        raise RuntimeError(f"EPS step +{lead}h is incomplete: {count} gribs, "+
                           str({idx:len(vals) for idx,vals in output.items()}))
    return output


def summarize(per_lead:list[dict[int,float]],run:date)->dict:
    if len(per_lead)!=16 or any(set(r)!=set(MEMBERS) for r in per_lead):
        raise RuntimeError("Missing day(s) or ensemble member(s) in forecast")
    values_per_member={str(m):[r[m] for r in per_lead] for m in MEMBERS}
    stats={"mean":[],"p10":[],"p90":[],"member_count":[],
           "probability":{"positive":[],"negative":[],"strong_positive":[],"strong_negative":[]}}
    for daily in per_lead:
        vals=list(daily.values());n=len(vals)
        stats["mean"].append(round(float(np.mean(vals)),3))
        stats["p10"].append(round(percentile(vals,.10),3))
        stats["p90"].append(round(percentile(vals,.90),3))
        stats["member_count"].append(n)
        stats["probability"]["positive"].append(round(100*sum(v>=0 for v in vals)/n,1))
        stats["probability"]["negative"].append(round(100*sum(v<0 for v in vals)/n,1))
        stats["probability"]["strong_positive"].append(round(100*sum(v>=1 for v in vals)/n,1))
        stats["probability"]["strong_negative"].append(round(100*sum(v<=-1 for v in vals)/n,1))
    return {
        "init_date":run.isoformat(),
        "valid_dates":[(run+timedelta(days=k)).isoformat() for k in range(16)],
        "members":values_per_member,**stats
    }


def build(output:Path=OUTPUT, reference_file:Path=REFERENCE, run:date|None=None):
    doc=json.loads(reference_file.read_text(encoding="utf-8"))
    if doc.get("schema")!=1 or doc.get("ready") is not True:
        raise RuntimeError("No verified EOF reference basis")
    ref=precompute(doc)
    client=Client(source="ecmwf",model="ifs",resol="0p25",maximum_retries=2,retry_after=4)
    when=run or datetime.now(timezone.utc).date()
    if when<datetime.now(timezone.utc).date()-timedelta(days=3):
        raise RuntimeError("ECMWF run is out of the published rolling archive")
    forecasts={"nao":[],"ao":[]}
    with tempfile.TemporaryDirectory() as tmp:
        for lead in LEADS:
            target=Path(tmp)/f"ens_gh_f{lead:03d}.grib2"
            client.retrieve(date=when.strftime("%Y%m%d"),time=0,stream="enfo",type="pf",
                            step=lead,param="gh",levelist=[500,1000],
                            number=list(MEMBERS),target=str(target))
            if target.stat().st_size<20000000:
                raise RuntimeError(f"EPS +{lead}h too small: {target.stat().st_size}")
            projected=parse_step(target,ref,when,lead)
            target.unlink()
            for idx in forecasts:forecasts[idx].append(projected[idx])
            print("IFS EPS",when.isoformat(),"+",lead,"h 50/50 members at 500/1000 hPa",flush=True)
    out={
        "schema":1,"ready":True,
        "generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source":"ECMWF Open Data / IFS ENS 50 perturbed forecasts (enfo:pf/gh)",
        "source_url":"https://www.ecmwf.int/en/forecasts/datasets/open-data",
        "licence":"CC BY 4.0",
        "run_utc":when.isoformat()+"T00:00:00Z",
        "expected_members":50,"lead_days":list(range(16)),
        "unit":"CPC-calibrated standardized EOF index (approximation)",
        "method":"NCEP R1 monthly EOF pattern projected from IFS ENS 00UTC absolute geopotential height with monthly-mean reference interpolation; regression calibrated to CPC 1950/1979-2000 monthly indices.",
        "is_official_cpc":False,
        "nao_is_cpc_exact_method":False,
        "nao_caveat":"Single Atlantic EOF, not CPC's month-dependent rotated EOF / multipattern regression.",
        "ao_caveat":"Annual hemispheric AO EOF resembles CPC's AO mode but differs in daily NCEP climatology and IFS model bias.",
        "reference_generated_at":doc["created_at"],
        "reference_source_url":doc["source_url"],
        "indices":{
            idx:{
                "pressure_hpa":LEVELS[idx],
                "quality":doc["indices"][idx]["quality"],
                **summarize(forecasts[idx],when),
            } for idx in forecasts
        },
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    tmpfile=output.with_suffix(".json.tmp")
    tmpfile.write_text(json.dumps(out,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    tmpfile.replace(output)
    print("EPS indices verified and saved",output,output.stat().st_size,flush=True)
    return out


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--run-date",type=date.fromisoformat)
    parser.add_argument("--output",type=Path,default=OUTPUT)
    args=parser.parse_args()
    build(output=args.output,run=args.run_date)
