#!/usr/bin/env python3
"""Compact observed daily regional archive. No model data or gap filling."""
import argparse, calendar, importlib, json, re, subprocess
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import xarray as xr
from build_hyras_tmean_regions import build_masks, load_states, EXPECTED_STATES
from build_hyras_temperature_rank_shard import _unpack_prepared
import update_hyras_maps as rain
from build_monthly_outlook_precip_series import daily_area_mean

REGIONS = ["Deutschland", *EXPECTED_STATES]
PARAMS = {"tmin":"build_hyras_tmin_regions","tmax":"build_hyras_tmax_regions","tmean":"build_hyras_tmean_regions"}

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf-8")
    temp.replace(path)

def extract(parameter, path, work, year):
    with xr.open_dataset(path,decode_times=True) as ds:
        if parameter=="precipitation":
            da=rain.pick_precip_var(ds)
            td=rain.time_dim(da)
            yd,xd=rain.spatial_dim_names(da)
            da=da.transpose(td,yd,xd)
            x,y=rain.grid_xy(da)
        else:
            module=importlib.import_module(PARAMS[parameter])
            da,td,yd,xd,x,y=_unpack_prepared(module,ds)
            da=da.transpose(td,yd,xd)
        masks=build_masks(load_states(work),x,y)
        dates=[str(d) for d in da[td].values.astype("datetime64[D]")]
        if dates!=sorted(set(dates)) or any(not d.startswith(str(year)+"-") for d in dates):
            raise ValueError("Invalid annual source dates")
        values={r:[] for r in REGIONS}
        cutoff=(date.today()-timedelta(days=1)).isoformat()
        kept=[]
        for i,d in enumerate(dates):
            if d>cutoff: continue
            field=np.asarray(da.isel({td:i}).values,dtype=np.float32)
            kept.append(d)
            for r in REGIONS:
                if parameter=="precipitation":
                    v,_=daily_area_mean(field,masks[r])
                else:
                    a=field[masks[r]]
                    valid=np.isfinite(a)&(a>=-80)&(a<=65)
                    v=round(float(a[valid].mean(dtype=np.float64)),3) if valid.mean()>=.9 else None
                values[r].append(v)
        return {"parameter":parameter,"year":year,"dates":kept,"regions":values,"source":"DWD HYRAS-DE 1 km","unit":"mm" if parameter=="precipitation" else "°C"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--parameter",choices=[*PARAMS,"precipitation"],required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--work",type=Path,required=True)
    p.add_argument("--batch",type=int,default=12)
    p.add_argument("--checkpoint-branch", help="Publish each completed year to this data branch")
    a=p.parse_args()
    a.work.mkdir(parents=True,exist_ok=True)
    if a.parameter=="precipitation":
        module=rain
        html=rain.directory_text(rain.DAILY_BASE+"/")
        files={}
        for y in range(1951,date.today().year+1):
            try: files.update(rain.daily_file_map(html,range(y,y+1)))
            except RuntimeError: pass
    else:
        module=importlib.import_module(PARAMS[a.parameter])
        files=module.latest_daily_files(module.daily_listing())
    files={y:f for y,f in files.items() if 1951<=y<=date.today().year}
    if not files: raise RuntimeError("No annual files found")
    newest=max(files)
    def complete(y):
        path=a.output/f"{y}.json"
        if not path.exists(): return False
        try:
            old=json.loads(path.read_text())
            return len(old['dates'])==365+calendar.isleap(y) and old['dates'][0]==f'{y}-01-01' and old['dates'][-1]==f'{y}-12-31' and old.get('source_file')==files[y]
        except (ValueError,KeyError,IndexError): return False
    missing=[y for y in sorted(files,reverse=True) if y!=newest and not complete(y)]
    def checkpoint():
        years=sorted(int(p.stem) for p in a.output.glob("[0-9][0-9][0-9][0-9].json"))
        write(a.output/"index.json",{"parameter":a.parameter,"years":years,"source_years":sorted(files),"regions":REGIONS,"data_through":json.loads((a.output/f"{newest}.json").read_text())["dates"][-1],"minimum_target_year":1981,"missing_target_years":[y for y in range(1981,newest+1) if y not in years]})
        if a.checkpoint_branch:
            def git(*args,check=True):
                return subprocess.run(["git","-C",str(a.output),*args],check=check)
            git("add","--","*.json")
            if git("diff","--cached","--quiet",check=False).returncode==1:
                git("commit","-m","Update regional daily archive")
                git("push","origin","HEAD:refs/heads/"+a.checkpoint_branch)
    for year in [newest,*missing[:max(0,a.batch)]]:
        filename=files[year]
        target=a.work/filename
        module.download(module.DAILY_BASE+"/"+filename,target)
        try:
            data=extract(a.parameter,target,a.work,year)
            if not data["dates"]: raise ValueError("Empty year")
            if year<newest and len(data["dates"])!=365+calendar.isleap(year):
                raise ValueError(f"Incomplete historical year {year}")
            data["source_file"]=filename
            write(a.output/f"{year}.json",data)
        finally: target.unlink(missing_ok=True)
        checkpoint()


if __name__=="__main__": main()
