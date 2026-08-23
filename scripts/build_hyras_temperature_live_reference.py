#!/usr/bin/env python3
from __future__ import annotations
import argparse, calendar, gzip, json, re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Rectangle
import numpy as np
from PIL import Image
import requests, xarray as xr

REF_START=1991; REF_END=2020; MISSING=-32768; SCALE=100
UA="climate-dashboard-hyras-live-reference/1.0 (+GitHub Actions; DWD Open Data)"
MONTH_ABBR={1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"}
LEVELS=[-6.,-5.,-4.,-3.,-2.,-1.,-.5,0.,.5,1.,2.,3.,4.,5.,6.]
COLORS=["#6B03C6","#5E4FFC","#187DFD","#70B1FB","#C6E4FB","#DDEBF9","#EDF4FA","#FDFCFC","#FDF0BC","#FDE47C","#FDBD3E","#FC691C","#F93A19","#E51B75","#FC579B"]

@dataclass(frozen=True)
class Config:
    key:str; prefix:str; label:str; source_label:str; daily_base:str; clim_base:str; vars:tuple[str,...]

CFG={
    "tmean":Config("tmean","tas","Tmean","HYRAS-DE-TAS",
        "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_mean",
        "https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/air_temperature_mean",
        ("tas","temperature","air_temperature","tmean")),
    "tmax":Config("tmax","tasmax","Tmax","HYRAS-DE-TASMAX",
        "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_max",
        "https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/air_temperature_max",
        ("tasmax","tmax","air_temperature_max","temperature")),
    "tmin":Config("tmin","tasmin","Tmin","HYRAS-DE-TASMIN",
        "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_min",
        "https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/air_temperature_min",
        ("tasmin","tmin","air_temperature_min","temperature")),
}

def get(url,timeout=120):
    r=requests.get(url,timeout=timeout,headers={"User-Agent":UA}); r.raise_for_status(); return r

def listing(url): return get(url+"/",90).text

def download(url,target:Path):
    target.parent.mkdir(parents=True,exist_ok=True); print("Download:",url,flush=True)
    with requests.get(url,stream=True,timeout=480,headers={"User-Agent":UA}) as r:
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk: f.write(chunk)
    print(f"  -> {target.name}: {target.stat().st_size/1024/1024:.1f} MB",flush=True)

def annual_files(c):
    pat=re.compile(rf'href="(?P<f>{c.prefix}_hyras_1_(?P<y>\d{{4}})_v(?P<a>\d+)-(?P<b>\d+)_de\.nc)"'); best={}
    for m in pat.finditer(listing(c.daily_base)):
        y=int(m.group("y")); item=(int(m.group("a")),int(m.group("b")),m.group("f"))
        if y not in best or item[:2]>best[y][:2]: best[y]=item
    return {y:v[2] for y,v in best.items()}

def latest_clim(c,month):
    abbr=MONTH_ABBR[month]; pat=re.compile(rf'href="(?P<f>{c.prefix}_hyras_1_{REF_START}_{REF_END}_v(?P<a>\d+)-(?P<b>\d+)_de_{abbr}\.nc)"')
    items=[(int(m.group("a")),int(m.group("b")),m.group("f")) for m in pat.finditer(listing(c.clim_base))]
    if not items: raise RuntimeError(f"Keine {c.key}-Klimadatei für {abbr}")
    return sorted(items)[-1][2]

def pick(ds,c):
    for n in c.vars:
        if n in ds.data_vars and ds[n].ndim>=2: return ds[n]
    for da in ds.data_vars.values():
        if da.ndim>=2: return da
    raise RuntimeError("Keine Temperaturvariable")

def tdim(da):
    for d in da.dims:
        if d.lower()=="time": return d
    for d in da.dims:
        if d in da.coords and np.issubdtype(da.coords[d].dtype,np.datetime64): return d
    raise RuntimeError("Keine Zeitdimension")

def sdims(da):
    try: t=tdim(da)
    except Exception: t=None
    dims=[d for d in da.dims if d!=t]; y=next((d for d in dims if d.lower() in {"y","lat","latitude","rlat"}),dims[-2]); x=next((d for d in dims if d.lower() in {"x","lon","longitude","rlon"}),dims[-1]); return y,x

def celsius(da):
    u=str(da.attrs.get("units","")).lower(); return da-273.15 if u=="k" or "kelvin" in u else da

def norm(a,x,y):
    a=np.asarray(a,np.float32); x=np.asarray(x,np.float64); y=np.asarray(y,np.float64); a[~np.isfinite(a)]=np.nan
    if len(x)>1 and x[0]>x[-1]: x=x[::-1]; a=a[...,::-1]
    if len(y)>1 and y[0]<y[-1]: y=y[::-1]; a=a[...,::-1,:]
    return a,x,y

def prep(ds,c):
    da=celsius(pick(ds,c)).squeeze(drop=True); t=tdim(da); y,x=sdims(da); da=da.transpose(t,y,x); return da,t,np.asarray(da[x].values,np.float64),np.asarray(da[y].values,np.float64)

def same_grid(x,y,ex,ey): return x.shape==ex.shape and y.shape==ey.shape and np.allclose(x,ex) and np.allclose(y,ey)

def current_mean(path,c,start,end):
    with xr.open_dataset(path,decode_times=True) as ds:
        da,t,x,y=prep(ds,c); sel=da.where((da[t]>=np.datetime64(start))&(da[t]<=np.datetime64(end)),drop=True)
        if sel.sizes.get(t,0)==0: raise RuntimeError(f"Keine {c.key}-Tage {start}–{end}")
        a=np.asarray(sel.mean(t,skipna=True).values,np.float32)
    return norm(a,x,y)

def cache_path(root,c,month): return root/f"{c.key}_month_{month:02d}_1991_2020.npz"

def build_month_cache(c,month,cache_root,work,ex,ey):
    path=cache_path(cache_root,c,month)
    if path.exists():
        with np.load(path,allow_pickle=False) as z:
            x=np.asarray(z["x"]); y=np.asarray(z["y"]); daily=np.asarray(z["daily"],np.float32)
            if int(z["month"])==month and same_grid(x,y,ex,ey): print(f"{c.label}: Monatsreferenz aus Cache",flush=True); return daily
    files=annual_files(c); missing=[y for y in range(REF_START,REF_END+1) if y not in files]
    if missing: raise RuntimeError(f"{c.key}: fehlende Jahre {missing}")
    nd=calendar.monthrange(2000,month)[1]; sums=np.zeros((nd,len(ey),len(ex)),np.float32); counts=np.zeros((nd,len(ey),len(ex)),np.uint8); hwork=work/"reference_years"; hwork.mkdir(parents=True,exist_ok=True)
    print(f"{c.label}: baue Tagesreferenz {MONTH_ABBR[month]} {REF_START}–{REF_END}",flush=True)
    for pos,year in enumerate(range(REF_START,REF_END+1),1):
        fn=files[year]; target=hwork/fn
        if not target.exists(): download(f"{c.daily_base}/{fn}",target)
        with xr.open_dataset(target,decode_times=True) as ds:
            da,t,x,y=prep(ds,c); dates=da[t].values.astype("datetime64[D]")
            for day in range(1,nd+1):
                try: d=np.datetime64(date(year,month,day).isoformat())
                except ValueError: continue
                idx=np.flatnonzero(dates==d)
                if len(idx)!=1: continue
                a,nx,ny=norm(np.asarray(da.isel({t:int(idx[0])}).values,np.float32),x,y)
                if not same_grid(nx,ny,ex,ey): raise RuntimeError(f"{c.key}: Rasterabweichung {fn}")
                ok=np.isfinite(a); sums[day-1][ok]+=a[ok]; counts[day-1][ok]+=1
        target.unlink(missing_ok=True)
        if pos==1 or pos%5==0 or pos==30: print(f"  {pos}/30 Jahre ({year})",flush=True)
    daily=np.full(sums.shape,np.nan,np.float32); ok=counts>0; daily[ok]=sums[ok]/counts[ok].astype(np.float32); cache_root.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(path,month=np.int16(month),daily=daily,x=ex,y=ey,reference_start=np.int16(REF_START),reference_end=np.int16(REF_END)); print(f"{c.label}: Cache {path.stat().st_size/1024/1024:.1f} MB",flush=True); return daily

def static_clim(path,c):
    with xr.open_dataset(path,decode_times=True) as ds:
        da=celsius(pick(ds,c)).squeeze(drop=True)
        while da.ndim>2: da=da.isel({da.dims[0]:0})
        y,x=sdims(da); da=da.transpose(y,x); return norm(np.asarray(da.values,np.float32),da[x].values,da[y].values)

def full_month_ref(c,month,year,work,ex,ey):
    fn=latest_clim(c,month); target=work/"clim"/fn
    if not target.exists(): download(f"{c.clim_base}/{fn}",target)
    a,x,y=static_clim(target,c)
    if not same_grid(x,y,ex,ey): raise RuntimeError(f"{c.key}: Klimaraster passt nicht")
    return a,calendar.monthrange(year,month)[1]

def period_ref(c,start_s,end_s,daily_ref,work,ex,ey):
    s=datetime.strptime(start_s,"%Y-%m-%d").date(); e=datetime.strptime(end_s,"%Y-%m-%d").date()
    if s.year!=e.year: raise RuntimeError("Jahresübergreifend nicht unterstützt")
    total=None; n=0
    for m in range(s.month,e.month+1):
        a=s.day if m==s.month else 1; b=e.day if m==e.month else calendar.monthrange(e.year,m)[1]; full=a==1 and b==calendar.monthrange(e.year,m)[1]
        if full: part,days=full_month_ref(c,m,e.year,work,ex,ey)
        else:
            if m!=e.month: raise RuntimeError("Unerwarteter Teilmonat")
            part=np.nanmean(daily_ref[a-1:b],axis=0).astype(np.float32); days=b-a+1
        total=part*days if total is None else total+part*days; n+=days
    return total/float(n)

def overlay_path(root):
    try:
        rel=json.loads((root/"hyras_index.json").read_text()).get("interactive",{}).get("boundary_overlay_1km"); return root/rel if rel else None
    except Exception: return None

def anomaly_style():
    lev=np.asarray(LEVELS,float); mids=(lev[:-1]+lev[1:])/2; bounds=np.r_[[lev[0]-.5],mids,[lev[-1]+.5]]; cmap=ListedColormap(COLORS,name="hyras_temperature_anomaly_final"); return cmap,BoundaryNorm(bounds,cmap.N,clip=True)

def draw_legend(fig):
    ax=fig.add_axes([.055,.045,.89,.05]); n=len(COLORS); ax.set_xlim(0,n); ax.set_ylim(0,1)
    for i,c in enumerate(COLORS): ax.add_patch(Rectangle((i,.42),1,.52,facecolor=c,edgecolor="white",linewidth=.8))
    zi=LEVELS.index(0.); ax.plot([zi+.5,zi+.5],[.42,.94],color="black",linewidth=.8,zorder=5); labels=["0" if v==0 else (f"{v:+.1f}" if abs(v)==.5 else (f"{v:+.0f}" if v>0 else f"{v:.0f}")) for v in LEVELS]
    for i,l in enumerate(labels): ax.text(i+.5,.12,l,ha="center",va="center",fontsize=7.5)
    ax.text(n+.12,.12,"K",ha="left",va="center",fontsize=8); ax.axis("off")

def render(a,output,c,label,start,end,overlay):
    cmap,normobj=anomaly_style(); fig=plt.figure(figsize=(7.4,9.4),dpi=150); ax=fig.add_axes([.055,.125,.89,.78]); ax.imshow(a,cmap=cmap,norm=normobj,interpolation="nearest"); ax.set_axis_off()
    if overlay and overlay.exists():
        ov=np.asarray(Image.open(overlay).convert("RGBA"));
        if ov.shape[:2]==a.shape: ax.imshow(ov,interpolation="nearest")
    fig.suptitle(f"HYRAS {c.label} · {label}",fontsize=15,fontweight="bold",y=.965); fig.text(.5,.925,f"Abweichung zum Mittel 1991–2020 · {start} bis {end}",ha="center",fontsize=9); draw_legend(fig); fig.text(.055,.012,f"Quelle: Deutscher Wetterdienst · {c.source_label} · Referenz 1991–2020",fontsize=7,color="#555555"); output.parent.mkdir(parents=True,exist_ok=True); fig.savefig(output,facecolor="white",bbox_inches="tight",pad_inches=.12); plt.close(fig)

def qwrite(path,a):
    q=np.full(a.shape,MISSING,dtype="<i2"); ok=np.isfinite(a); q[ok]=np.clip(np.rint(a[ok]*SCALE),-32767,32767).astype(np.int16); path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,"wb",compresslevel=6) as f: f.write(q.tobytes(order="C"))

def load_i16(path,width,height):
    with gzip.open(path,"rb") as f: raw=f.read()
    a=np.frombuffer(raw,dtype="<i2")
    if a.size!=width*height: raise RuntimeError(f"Rastergröße passt nicht: {path} ({a.size} statt {width*height})")
    a=a.reshape(height,width).astype(np.float32); a[a==MISSING]=np.nan; a/=SCALE; return a

def rerender_all_tmean(root):
    troot=root/"tmean"; ip=troot/"index.json"; mp=troot/"regions"/"map_downloads.json"
    if not ip.exists() or not mp.exists(): return
    idx=json.loads(ip.read_text(encoding="utf-8")); maps=json.loads(mp.read_text(encoding="utf-8")); w=int(idx["grid_1km"]["width"]); h=int(idx["grid_1km"]["height"]); ov=overlay_path(root); count=0
    for p in idx.get("periods",[]):
        rel=p.get("anomaly")
        if not rel: continue
        src=troot/str(rel)
        if not src.exists(): continue
        key=str(p["key"]); target=f"download_maps/{key}_anomaly.png"; render(load_i16(src,w,h),troot/target,CFG["tmean"],str(p.get("label",key)),str(p.get("start_date","")),str(p.get("end_date","")),ov); mi=maps.setdefault("periods",{}).setdefault(key,{"label":p.get("label",key)}); mi["anomaly"]=target
        if p.get("reference_exact") is not None: mi["reference_exact"]=bool(p.get("reference_exact"))
        if p.get("reference_note"): mi["reference_note"]=p.get("reference_note")
        count+=1
    maps["data_through"]=idx.get("data_through"); mp.write_text(json.dumps(maps,ensure_ascii=False,indent=2),encoding="utf-8"); print(f"Tmean: {count} Abweichungskarten mit finaler Skala neu gerendert.",flush=True)

def parameter_state(root,c):
    if c.key=="tmean":
        ip=root/"tmean"/"index.json"; mp=root/"tmean"/"regions"/"map_downloads.json"; idx=json.loads(ip.read_text()); maps=json.loads(mp.read_text()); year=int(idx["year"]); through=str(idx["data_through"]); current=str(idx["current_source_file"])
    else:
        ip=root/c.key/"regions"/"index.json"; mp=root/c.key/"regions"/"map_downloads.json"; idx=json.loads(ip.read_text()); maps=json.loads(mp.read_text()); year=int(idx["year"]); through=str(idx["data_through"]); current=annual_files(c)[year]
    return ip,mp,idx,maps,year,through,current

def process(root,cache,work,c,reference_only=False,month_override=None):
    ip,mp,idx,maps,year,through,current_name=parameter_state(root,c); month=month_override or int(through[5:7]); current=work/current_name
    if not current.exists(): download(f"{c.daily_base}/{current_name}",current)
    probe=f"{year}-{month:02d}-01"; _,ex,ey=current_mean(current,c,probe,probe); daily_ref=build_month_cache(c,month,cache,work,ex,ey)
    if reference_only: return
    ov=overlay_path(root)
    for p in idx.get("periods",[]):
        key=str(p["key"]); end=str(p.get("end_date",""))
        if end!=through: continue
        if c.key=="tmean" and not bool(p.get("live")): continue
        mi=maps.setdefault("periods",{}).setdefault(key,{"label":p.get("label",key)})
        if c.key!="tmean" and mi.get("anomaly"): continue
        start=str(p["start_date"]); cur,x,y=current_mean(current,c,start,end)
        if not same_grid(x,y,ex,ey): raise RuntimeError(f"{c.key}: aktuelles Raster passt nicht")
        ref=period_ref(c,start,end,daily_ref,work,ex,ey); anomaly=cur-ref; rel=f"download_maps/{key}_anomaly.png"; render(anomaly,root/c.key/rel,c,str(p.get("label",key)),start,end,ov); mi["anomaly"]=rel; mi["reference_exact"]=True; mi["reference_note"]="Tagesgenauer Vergleich mit demselben Kalenderabschnitt des HYRAS-Mittels 1991–2020."
        if c.key=="tmean":
            arel=f"current/{key}_anomaly.i16.gz"; qwrite(root/"tmean"/arel,anomaly); p["anomaly"]=arel; p["reference_exact"]=True; p["reference_note"]=mi["reference_note"]; p.setdefault("stats",{})["reference_mean_c"]=round(float(np.nanmean(ref)),2); p["stats"]["anomaly_mean_k"]=round(float(np.nanmean(anomaly)),2)
        print(f"{c.label}: Live-Anomalie {key}",flush=True)
    ip.write_text(json.dumps(idx,ensure_ascii=False,indent=2)); mp.write_text(json.dumps(maps,ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data-root",default="/tmp/hyras-data"); ap.add_argument("--reference-cache",default="/tmp/hyras-temperature-reference-cache"); ap.add_argument("--parameter",choices=("all","tmean","tmax","tmin"),default="all"); ap.add_argument("--build-reference-only",action="store_true"); ap.add_argument("--month",type=int); args=ap.parse_args()
    root=Path(args.data_root); cache=Path(args.reference_cache); params=("tmean","tmax","tmin") if args.parameter=="all" else (args.parameter,)
    for key in params: process(root,cache,Path(f"/tmp/hyras-{key}-live-ref"),CFG[key],args.build_reference_only,args.month)
    if not args.build_reference_only:
        if "tmean" in params: rerender_all_tmean(root)
        meta={"schema_version":1,"reference":"1991-2020","method":"Tagesgenaue Rasterreferenz für laufende Teilzeiträume; kompakte Monatscaches liegen im GitHub-Actions-Cache.","parameters":params}; (root/"_temperature_reference.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
