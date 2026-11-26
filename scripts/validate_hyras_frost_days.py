#!/usr/bin/env python3
"""Pilot: annual and monthly HYRAS frost-day counts vs official annual DWD."""
import argparse, csv, io, json
from pathlib import Path
import numpy as np
import xarray as xr
from build_hyras_tmin_regions import DAILY_BASE, daily_listing, latest_daily_files, download, prepare_da, get
from build_hyras_tmean_regions import build_masks, load_states
from build_regional_annual_climate_days import BASE, SOURCES, parse

def frost_fraction(block, mask):
    a=block[:,mask]
    valid=np.isfinite(a)
    n=valid.sum(axis=1)
    return np.divide(((a<0)&valid).sum(axis=1),n,out=np.full(len(a),np.nan),where=n>0),n

def selftest():
    b=np.array([[[-1.,0.],[2.,-3.]],[[1.,-2.],[np.nan,3.]]])
    f,n=frost_fraction(b,np.ones((2,2),bool))
    assert np.allclose(f,[.5,1/3]) and list(n)==[4,3]
    assert np.isnan(frost_fraction(b,np.zeros((2,2),bool))[0]).all()
    print("Threshold and missing-value test OK")

def main(years,work,out):
    work.mkdir(parents=True,exist_ok=True)
    names,official,_=parse(get(BASE+SOURCES["frost"][2]).content)
    files=latest_daily_files(daily_listing())
    features=load_states(work); results=[]
    for year in years:
        name=files[year]
        if "v6-1" not in name: raise RuntimeError(f"Unexpected version {name}")
        path=work/name;download(f"{DAILY_BASE}/{name}",path)
        with xr.open_dataset(path) as ds:
            da,td,x,y=prepare_da(ds)
            dates=da[td].values.astype("datetime64[D]")
            expected=np.arange(np.datetime64(f"{year}-01-01"),np.datetime64(f"{year+1}-01-01"),dtype="datetime64[D]")
            if not np.array_equal(dates,expected): raise RuntimeError(f"Incomplete calendar {year}")
            masks=build_masks(features,x,y)
            masks.update({"Brandenburg/Berlin":masks["Brandenburg"]|masks["Berlin"],"Niedersachsen/Hamburg/Bremen":masks["Niedersachsen"]|masks["Hamburg"]|masks["Bremen"],"Thüringen/Sachsen-Anhalt":masks["Thüringen"]|masks["Sachsen-Anhalt"]})
            months=np.array([int(str(d)[5:7]) for d in dates])
            month_values={a:np.zeros(12) for a in masks}
            coverage={a:[] for a in masks}
            for start in range(0,len(dates),16):
                end=min(start+16,len(dates))
                block=np.asarray(da.isel({td:slice(start,end)}).values,dtype=np.float32)
                for area,mask in masks.items():
                    frac,n=frost_fraction(block,mask)
                    if not np.all(np.isfinite(frac)): raise RuntimeError(f"Missing day {area} {year}")
                    coverage[area].extend(n.tolist())
                    np.add.at(month_values[area],months[start:end]-1,frac)
            for area,monthly in month_values.items():
                ref=official[year][names.index(area)] if area in names else None
                v=float(monthly.sum()); n=coverage[area]
                result={"year":year,"area":area,"hyras_days":round(v,4),"dwd_days":ref,"difference_days":round(v-ref,4) if ref is not None else None,"monthly_days":[round(float(i),4) for i in monthly],"mask_cells":int(masks[area].sum()),"min_valid_cells":min(n),"max_valid_cells":max(n),"minimum_coverage":round(min(n)/int(masks[area].sum()),5)}
                results.append(result)
                print(json.dumps(result,ensure_ascii=False),flush=True)
        path.unlink()
    comparable=[r for r in results if r["difference_days"] is not None]
    summary={}
    for area in names:
        diffs=[r["difference_days"] for r in comparable if r["area"]==area]
        if diffs: summary[area]={"n":len(diffs),"bias":round(float(np.mean(diffs)),4),"mae":round(float(np.mean(np.abs(diffs))),4),"max_abs":round(float(np.max(np.abs(diffs))),4)}
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({"method":"HYRAS v6-1 daily Tmin < 0 C, daily valid-cell fraction summed; EPSG:3035 cell centre masks; official DWD annual frost-day product uses different interpolation","years":years,"summary":summary,"rows":results},ensure_ascii=False,indent=2)+"\n")
    print("SUMMARY:",json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--years",nargs="+",type=int,default=[1951,2010,2024,2025]);p.add_argument("--work",type=Path,default=Path("/tmp/hyras-frost-pilot"));p.add_argument("--output",type=Path,default=Path("data/validation/hyras_frost_days_pilot.json"));p.add_argument("--selftest",action="store_true");a=p.parse_args()
    if a.selftest:selftest()
    else:main(a.years,a.work,a.output)
