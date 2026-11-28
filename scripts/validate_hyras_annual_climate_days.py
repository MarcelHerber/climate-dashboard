#!/usr/bin/env python3
"""Independent annual HYRAS/DWD regional climate-day validation; no site changes."""
import argparse, csv, json, math, operator
from pathlib import Path
import numpy as np
import xarray as xr
from build_hyras_tmin_regions import download
from build_hyras_tmean_regions import build_masks, load_states

BASE="https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de"
YEARS=[1951,1961,1970,1981,1991,2001,2010,2018,2019,2020,2021,2022,2023,2024,2025]
GROUPS={
 "tasmin":("air_temperature_min",{"frost":(operator.lt,0),"tropical":(operator.ge,20)}),
 "tasmax":("air_temperature_max",{"ice":(operator.lt,0),"summer":(operator.ge,25),"hot":(operator.ge,30)}),
 "pr":("precipitation",{"rr10":(operator.ge,10),"rr20":(operator.ge,20)}),
}
REF=Path("data/dwd_regional_annual_climate_days.json")
REPORT=Path("data/validation/hyras_annual_climate_days_comparison.json")

def counts(block,idx,thresholds):
    a=block.reshape(len(block),-1)[:,idx]
    valid=np.isfinite(a)
    n=valid.sum(axis=1)
    if np.any(n==0): raise ValueError("No valid cells")
    return {k:np.sum(op(a,threshold)&valid,axis=1)/n for k,(op,threshold) in thresholds.items()},n

def prepare(ds,var):
    a=ds[var]
    if set(a.dims)!={"time","x","y"}: raise ValueError(f"Unexpected dimensions {a.dims}")
    units=str(a.attrs.get("units","")).lower().strip()
    if var=="pr":
        if units not in {"mm","mm/d","mm/day","mm d-1","mm day-1","kg m-2","kg m**-2","kg/m2","kg m^-2","kg m-2 day-1","kg m-2 d-1"}: raise ValueError(f"Unexpected precipitation units {units}")
    elif units in {"k","kelvin"}:
        a=a-273.15
    elif units not in {"c","°c","degc","degree_celsius","degrees_celsius","degree_c","degrees_c","celsius","degree celsius","degrees celsius"}:
        raise ValueError(f"Unexpected temperature units {units}")
    a=a.transpose("time","y","x")
    x=np.asarray(a.x.values,dtype=float);y=np.asarray(a.y.values,dtype=float)
    if not (x.ndim==y.ndim==1 and np.allclose(np.abs(np.diff(x)),1000) and np.allclose(np.abs(np.diff(y)),1000) and 2e6<x.min()<5.5e6 and 1e6<y.min()<4.5e6): raise ValueError("Expected 1km LAEA coordinates")
    return a,x,y,units

def calculate(group,years,work,output):
    ref=json.loads(REF.read_text()); areas=ref["areas"]
    folder,thresholds=GROUPS[group]
    work.mkdir(parents=True,exist_ok=True)
    features=load_states(work); rows=[]; previous=None
    for year in years:
        name=f"{group}_hyras_1_{year}_v6-1_de.nc"; url=f"{BASE}/{folder}/{name}"
        path=work/name; download(url,path)
        with xr.open_dataset(path) as ds:
            da,x,y,units=prepare(ds,group)
            dates=da.time.values.astype("datetime64[D]")
            expected=np.arange(np.datetime64(f"{year}-01-01"),np.datetime64(f"{year+1}-01-01"),dtype="datetime64[D]")
            if not np.array_equal(dates,expected): raise ValueError(f"Incomplete calendar {year}")
            if previous is None or not np.array_equal(previous[0],x) or not np.array_equal(previous[1],y):
                masks=build_masks(features,x,y); previous=(x,y)
                for area in areas:
                    if area not in masks:
                        states=area.split("/")
                        masks[area]=np.logical_or.reduce([masks[s] for s in states])
                idx={area:np.flatnonzero(masks[area].ravel()) for area in areas}
            totals={area:{k:0. for k in thresholds} for area in areas}
            coverage={area:1. for area in areas}; maxcoverage={area:0. for area in areas}
            for start in range(0,len(dates),16):
                block=np.asarray(da.isel(time=slice(start,start+16)).values,dtype=np.float32)
                if group=="pr": block[block<0]=np.nan
                else: block[(block< -60)|(block>60)]=np.nan
                for area in areas:
                    f,n=counts(block,idx[area],thresholds)
                    coverage[area]=min(coverage[area],float(n.min()/len(idx[area])))
                    maxcoverage[area]=max(maxcoverage[area],float(n.max()/len(idx[area])))
                    for k,v in f.items(): totals[area][k]+=float(v.sum())
            for i,area in enumerate(areas):
                if coverage[area]<.98: raise ValueError(f"Coverage below 98%: {year} {group} {area} {coverage[area]}")
                for k,v in totals[area].items():
                    official=ref["metrics"][k]["years"][str(year)][i]
                    if official is None: raise ValueError(f"Missing DWD reference {year} {area} {k}")
                    rows.append({"year":year,"metric":k,"area":area,"hyras_days":round(v,5),"dwd_days":official,"difference_days":round(v-official,5),"minimum_coverage":round(coverage[area],6),"maximum_coverage":round(maxcoverage[area],6),"mask_cells":len(idx[area]),"file":name,"units":units})
            print(year,group,"Deutschland",totals["Deutschland"],flush=True)
        path.unlink()
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps({"group":group,"years":years,"rows":rows},ensure_ascii=False,allow_nan=False))

def summarize(rows):
    a=np.array([r["difference_days"] for r in rows]);ref=np.array([r["dwd_days"] for r in rows]); h=np.array([r["hyras_days"] for r in rows])
    j=int(np.argmax(np.abs(a)))
    result={"n":len(rows),"bias":float(a.mean()),"mae":float(np.abs(a).mean()),"rmse":float(np.sqrt(np.mean(a*a))),"max_abs":float(np.abs(a[j])),"worst_year":rows[j]["year"],"worst_area":rows[j]["area"],"dwd_mean":float(ref.mean()),"mae_pct_of_dwd_mean":float(np.abs(a).mean()/ref.mean()*100) if ref.mean()>0 else None,"correlation":float(np.corrcoef(h,ref)[0,1]) if len(a)>1 and h.std()>0 and ref.std()>0 else None,"minimum_coverage":min(r["minimum_coverage"] for r in rows)}
    return {k:round(v,5) if isinstance(v,float) else v for k,v in result.items()}

def merge(inputs,output):
    ref=json.loads(REF.read_text()); areas=ref["areas"];parts=[json.loads(p.read_text()) for p in inputs]
    rows=[r for p in parts for r in p["rows"]]
    keys={(r["metric"],r["area"],r["year"]) for r in rows}
    expected={(k,a,y) for k in ref["metrics"] for a in areas for y in YEARS}
    if keys!=expected or len(rows)!=len(expected): raise ValueError("Incomplete or duplicated comparisons")
    rows.sort(key=lambda r:(r["metric"],r["area"],r["year"]))
    summary={}
    for k in ref["metrics"]:
        subset=[r for r in rows if r["metric"]==k]
        summary[k]={"label":ref["metrics"][k]["label"],"areas":{a:summarize([r for r in subset if r["area"]==a]) for a in areas}}
    result={"version":1,"years":YEARS,"method":"HYRAS v6-1 daily valid-cell threshold fractions summed annually; 1km LAEA cell centre masks; DWD official regional annual values; independent products, not identical interpolation","summary":summary,"rows":rows}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    with output.with_suffix(".csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter=";");writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:v["areas"]["Deutschland"] for k,v in summary.items()},ensure_ascii=False,indent=2))

def selftest():
    b=np.array([[[-1.,0.],[20.,np.nan]],[[25.,30.],[29.,-2.]]])
    f,n=counts(b,np.arange(4),{"frost":(operator.lt,0),"hot":(operator.ge,30),"tropical":(operator.ge,20)})
    assert np.allclose(f["frost"],[1/3,1/4]) and np.allclose(f["hot"],[0,1/4]) and np.allclose(f["tropical"],[1/3,3/4]) and n.tolist()==[3,4]
    f,n=counts(np.array([[[0.,10.],[20.,19.9]]]),np.arange(4),GROUPS["pr"][1])
    assert f["rr10"][0]==.75 and f["rr20"][0]==.25
    r=summarize([{"difference_days":-2,"dwd_days":10,"hyras_days":8,"year":1951,"area":"Deutschland","minimum_coverage":1},{"difference_days":4,"dwd_days":20,"hyras_days":24,"year":2025,"area":"Deutschland","minimum_coverage":.99}])
    assert r["bias"]==1 and r["mae"]==3 and r["max_abs"]==4 and r["worst_year"]==2025
    print("Synthetic threshold, missing cell and statistics checks OK")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--group",choices=GROUPS);p.add_argument("--years",nargs="+",type=int,default=YEARS);p.add_argument("--work",type=Path,default=Path("/tmp/hyras-annual-validation"));p.add_argument("--output",type=Path,default=REPORT);p.add_argument("--merge",nargs="+",type=Path);p.add_argument("--selftest",action="store_true");a=p.parse_args()
    if a.selftest:selftest()
    elif a.merge:merge(a.merge,a.output)
    elif a.group:calculate(a.group,a.years,a.work,a.output)
    else:p.error("Specify group, merge or selftest")
