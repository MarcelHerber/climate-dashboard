#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import gzip
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap
from matplotlib.patches import Rectangle
import numpy as np
from PIL import Image
import requests
import xarray as xr

REF_START=1991
REF_END=2020
UA="climate-dashboard-hyras-live-reference/1.0 (+GitHub Actions; DWD Open Data)"
MONTH_ABBR={1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"}
MISSING=-32768
SCALE=100

# Final abgestimmte Tmean-Abweichungsskala.
# Die Farben -6 ... +6 stammen aus der bestätigten Referenzskala;
# bei -0.5 und +0.5 kommen zusätzliche sehr helle Zwischenklassen hinzu.
TMEAN_ANOMALY_LEVELS=[-6.0,-5.0,-4.0,-3.0,-2.0,-1.0,-0.5,0.0,0.5,1.0,2.0,3.0,4.0,5.0,6.0]
TMEAN_ANOMALY_COLORS=[
    "#6B03C6",  # -6 violett
    "#5E4FFC",  # -5 violett-blau
    "#187DFD",  # -4 kräftiges Blau
    "#70B1FB",  # -3 helleres Blau
    "#C6E4FB",  # -2 blassblau
    "#DDEBF9",  # -1 sehr hellblau
    "#EDF4FA",  # -0.5 zusätzliches leichtes Blau
    "#FDFCFC",  #  0 nahezu weiß
    "#FDF0BC",  # +0.5 zusätzliches leichtes Gelb
    "#FDE47C",  # +1 gelb
    "#FDBD3E",  # +2 goldgelb
    "#FC691C",  # +3 orange
    "#F93A19",  # +4 rot-orange
    "#E51B75",  # +5 dunkles Magenta
    "#FC579B",  # +6 helleres Pink
]

@dataclass(frozen=True)
class Config:
    key:str
    prefix:str
    label:str
    source_label:str
    daily_base:str
    clim_base:str
    vars:tuple[str,...]

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
    target.parent.mkdir(parents=True,exist_ok=True)
    print("Download:",url,flush=True)
    with requests.get(url,stream=True,timeout=480,headers={"User-Agent":UA}) as r:
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk: f.write(chunk)
    print(f"  -> {target.name}: {target.stat().st_size/1024/1024:.1f} MB",flush=True)

def annual_files(c:Config):
    pat=re.compile(rf'href="(?P<f>{c.prefix}_hyras_1_(?P<y>\d{{4}})_v(?P<a>\d+)-(?P<b>\d+)_de\.nc)"')
    best={}
    for m in pat.finditer(listing(c.daily_base)):
        y=int(m.group("y")); item=(int(m.group("a")),int(m.group("b")),m.group("f"))
        if y not in best or item[:2]>best[y][:2]: best[y]=item
    return {y:v[2] for y,v in best.items()}

def latest_clim(c:Config,month:int):
    abbr=MONTH_ABBR[month]
    pat=re.compile(rf'href="(?P<f>{c.prefix}_hyras_1_{REF_START}_{REF_END}_v(?P<a>\d+)-(?P<b>\d+)_de_{abbr}\.nc)"')
    items=[(int(m.group("a")),int(m.group("b")),m.group("f")) for m in pat.finditer(listing(c.clim_base))]
    if not items: raise RuntimeError(f"Keine {c.key}-Klimadatei für {abbr}")
    return sorted(items)[-1][2]

def pick(ds,c):
    for n in c.vars:
        if n in ds.data_vars and ds[n].ndim>=2: return ds[n]
    for da in ds.data_vars.values():
        if da.ndim>=2:return da
    raise RuntimeError("Keine Temperaturvariable")

def tdim(da):
    for d in da.dims:
        if d.lower()=="time": return d
    for d in da.dims:
        if d in da.coords and np.issubdtype(da.coords[d].dtype,np.datetime64): return d
    raise RuntimeError("Keine Zeitdimension")

def sdims(da):
    try:t=tdim(da)
    except Exception:t=None
    dims=[d for d in da.dims if d!=t]
    y=next((d for d in dims if d.lower() in {"y","lat","latitude","rlat"}),dims[-2])
    x=next((d for d in dims if d.lower() in {"x","lon","longitude","rlon"}),dims[-1])
    return y,x

def celsius(da):
    u=str(da.attrs.get("units","")).lower()
    return da-273.15 if u=="k" or "kelvin" in u else da

def norm(arr,x,y):
    arr=np.asarray(arr,dtype=np.float32); x=np.asarray(x,dtype=np.float64); y=np.asarray(y,dtype=np.float64)
    arr[~np.isfinite(arr)]=np.nan
    if len(x)>1 and x[0]>x[-1]: x=x[::-1]; arr=arr[...,::-1]
    if len(y)>1 and y[0]<y[-1]: y=y[::-1]; arr=arr[...,::-1,:]
    return arr,x,y

def prep(ds,c):
    da=celsius(pick(ds,c)).squeeze(drop=True); t=tdim(da); y,x=sdims(da); da=da.transpose(t,y,x)
    return da,t,np.asarray(da[x].values,dtype=np.float64),np.asarray(da[y].values,dtype=np.float64)

def same_grid(x,y,ex,ey): return x.shape==ex.shape and y.shape==ey.shape and np.allclose(x,ex) and np.allclose(y,ey)

def current_mean(path,c,start,end):
    with xr.open_dataset(path,decode_times=True) as ds:
        da,t,x,y=prep(ds,c)
        sel=da.where((da[t]>=np.datetime64(start))&(da[t]<=np.datetime64(end)),drop=True)
        if sel.sizes.get(t,0)==0: raise RuntimeError(f"Keine {c.key}-Tage {start}–{end}")
        arr=np.asarray(sel.mean(t,skipna=True).values,dtype=np.float32)
    return norm(arr,x,y)

def cache_path(root:Path,c:Config,month:int): return root/f"{c.key}_month_{month:02d}_1991_2020.npz"

def build_month_cache(c:Config,month:int,cache_root:Path,work:Path,ex,ey):
    path=cache_path(cache_root,c,month)
    if path.exists():
        with np.load(path,allow_pickle=False) as z:
            x=np.asarray(z["x"]); y=np.asarray(z["y"]); daily=np.asarray(z["daily"],dtype=np.float32)
            if int(z["month"])==month and same_grid(x,y,ex,ey):
                print(f"{c.label}: Monatsreferenz aus Cache",flush=True); return daily
    files=annual_files(c)
    missing=[y for y in range(REF_START,REF_END+1) if y not in files]
    if missing: raise RuntimeError(f"{c.key}: fehlende Jahre {missing}")
    nd=calendar.monthrange(2000,month)[1]
    sums=np.zeros((nd,len(ey),len(ex)),dtype=np.float32); counts=np.zeros((nd,len(ey),len(ex)),dtype=np.uint8)
    hwork=work/"reference_years"; hwork.mkdir(parents=True,exist_ok=True)
    print(f"{c.label}: baue Tagesreferenz {MONTH_ABBR[month]} {REF_START}–{REF_END}",flush=True)
    for pos,year in enumerate(range(REF_START,REF_END+1),1):
        fn=files[year]; target=hwork/fn
        if not target.exists(): download(f"{c.daily_base}/{fn}",target)
        with xr.open_dataset(target,decode_times=True) as ds:
            da,t,x,y=prep(ds,c); dates=da[t].values.astype("datetime64[D]")
            for day in range(1,nd+1):
                try:d=np.datetime64(date(year,month,day).isoformat())
                except ValueError:continue
                idx=np.flatnonzero(dates==d)
                if len(idx)!=1:continue
                arr,nx,ny=norm(np.asarray(da.isel({t:int(idx[0])}).values,dtype=np.float32),x,y)
                if not same_grid(nx,ny,ex,ey): raise RuntimeError(f"{c.key}: Rasterabweichung {fn}")
                ok=np.isfinite(arr); sums[day-1][ok]+=arr[ok]; counts[day-1][ok]+=1
        target.unlink(missing_ok=True)
        if pos==1 or pos%5==0 or pos==30: print(f"  {pos}/30 Jahre ({year})",flush=True)
    daily=np.full(sums.shape,np.nan,dtype=np.float32); ok=counts>0; daily[ok]=sums[ok]/counts[ok].astype(np.float32)
    cache_root.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(path,month=np.int16(month),daily=daily,x=ex,y=ey,reference_start=np.int16(REF_START),reference_end=np.int16(REF_END))
    print(f"{c.label}: Cache {path.stat().st_size/1024/1024:.1f} MB",flush=True)
    return daily

def static_clim(path,c):
    with xr.open_dataset(path,decode_times=True) as ds:
        da=celsius(pick(ds,c)).squeeze(drop=True)
        while da.ndim>2: da=da.isel({da.dims[0]:0})
        y,x=sdims(da); da=da.transpose(y,x)
        return norm(np.asarray(da.values,dtype=np.float32),da[x].values,da[y].values)

def full_month_ref(c,month,year,work,ex,ey):
    fn=latest_clim(c,month); target=work/"clim"/fn
    if not target.exists(): download(f"{c.clim_base}/{fn}",target)
    arr,x,y=static_clim(target,c)
    if not same_grid(x,y,ex,ey): raise RuntimeError(f"{c.key}: Klimaraster passt nicht")
    return arr,calendar.monthrange(year,month)[1]

def period_ref(c,start_s,end_s,daily_ref,work,ex,ey):
    start=datetime.strptime(start_s,"%Y-%m-%d").date(); end=datetime.strptime(end_s,"%Y-%m-%d").date()
    if start.year!=end.year: raise RuntimeError("Jahresübergreifend nicht unterstützt")
    total=None; n=0
    for m in range(start.month,end.month+1):
        a=start.day if m==start.month else 1; b=end.day if m==end.month else calendar.monthrange(end.year,m)[1]
        full=a==1 and b==calendar.monthrange(end.year,m)[1]
        if full: part,days=full_month_ref(c,m,end.year,work,ex,ey)
        else:
            if m!=end.month: raise RuntimeError("Unerwarteter Teilmonat")
            part=np.nanmean(daily_ref[a-1:b],axis=0).astype(np.float32); days=b-a+1
        total=part*days if total is None else total+part*days; n+=days
    return total/float(n)

def overlay_path(data_root):
    try:
        p=json.loads((data_root/"hyras_index.json").read_text()); rel=p.get("interactive",{}).get("boundary_overlay_1km")
        return data_root/rel if rel else None
    except Exception:return None

def tmean_anomaly_style():
    levels=np.asarray(TMEAN_ANOMALY_LEVELS,dtype=float)
    mids=(levels[:-1]+levels[1:])/2.0
    bounds=np.concatenate(([levels[0]-0.5],mids,[levels[-1]+0.5]))
    cmap=ListedColormap(TMEAN_ANOMALY_COLORS,name="hyras_tmean_anomaly_final")
    return cmap,BoundaryNorm(bounds,cmap.N,clip=True),bounds

def draw_tmean_anomaly_legend(fig):
    ax=fig.add_axes([.055,.045,.89,.050])
    n=len(TMEAN_ANOMALY_COLORS)
    ax.set_xlim(0,n); ax.set_ylim(0,1)
    for i,color in enumerate(TMEAN_ANOMALY_COLORS):
        ax.add_patch(Rectangle((i,0.42),1,0.52,facecolor=color,edgecolor="white",linewidth=.8))
    zero_index=TMEAN_ANOMALY_LEVELS.index(0.0)
    ax.plot([zero_index+.5,zero_index+.5],[.42,.94],color="black",linewidth=.8,zorder=5)
    labels=[]
    for value in TMEAN_ANOMALY_LEVELS:
        if value==0:
            labels.append("0")
        elif abs(value)==0.5:
            labels.append(f"{value:+.1f}")
        else:
            labels.append(f"{value:+.0f}" if value>0 else f"{value:.0f}")
    for i,label in enumerate(labels):
        ax.text(i+.5,.12,label,ha="center",va="center",fontsize=7.5)
    ax.text(n+.12,.12,"K",ha="left",va="center",fontsize=8)
    ax.axis("off")

def render(arr,output,c,label,start,end,overlay):
    tmean_discrete=c.key=="tmean"
    if tmean_discrete:
        cmap,map_norm,_=tmean_anomaly_style()
    else:
        cmap=LinearSegmentedColormap.from_list("anom",["#313695","#4575b4","#74add1","#abd9e9","#f7f7f7","#fdae61","#f46d43","#d73027","#a50026"])
        map_norm=None
    fig=plt.figure(figsize=(7.4,9.4),dpi=150)
    ax=fig.add_axes([.055,.125,.89,.78] if tmean_discrete else [.055,.105,.89,.80])
    if tmean_discrete:
        im=ax.imshow(arr,cmap=cmap,norm=map_norm,interpolation="nearest")
    else:
        im=ax.imshow(arr,cmap=cmap,vmin=-6,vmax=6,interpolation="nearest")
    ax.set_axis_off()
    if overlay and overlay.exists():
        ov=np.asarray(Image.open(overlay).convert("RGBA"));
        if ov.shape[:2]==arr.shape: ax.imshow(ov,interpolation="nearest")
    fig.suptitle(f"HYRAS {c.label} · {label}",fontsize=15,fontweight="bold",y=.965)
    fig.text(.5,.925,f"Abweichung zum Mittel 1991–2020 · {start} bis {end}",ha="center",fontsize=9)
    if tmean_discrete:
        draw_tmean_anomaly_legend(fig)
    else:
        cb=fig.colorbar(im,cax=fig.add_axes([.14,.055,.72,.025]),orientation="horizontal"); cb.set_label("K",fontsize=9)
    fig.text(.055,.012,f"Quelle: Deutscher Wetterdienst · {c.source_label} · Referenz 1991–2020",fontsize=7,color="#555555")
    output.parent.mkdir(parents=True,exist_ok=True); fig.savefig(output,facecolor="white",bbox_inches="tight",pad_inches=.12); plt.close(fig)

def qwrite(path,arr):
    q=np.full(arr.shape,MISSING,dtype="<i2"); ok=np.isfinite(arr); q[ok]=np.clip(np.rint(arr[ok]*SCALE),-32767,32767).astype(np.int16)
    path.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(path,"wb",compresslevel=6) as f:f.write(q.tobytes(order="C"))

def load_i16(path:Path,width:int,height:int):
    with gzip.open(path,"rb") as f:
        raw=f.read()
    arr=np.frombuffer(raw,dtype="<i2")
    if arr.size!=width*height:
        raise RuntimeError(f"Rastergröße passt nicht: {path} ({arr.size} statt {width*height})")
    arr=arr.reshape(height,width).astype(np.float32)
    arr[arr==MISSING]=np.nan
    arr/=SCALE
    return arr

def rerender_all_tmean_anomaly_maps(data_root:Path):
    troot=data_root/"tmean"
    idx_path=troot/"index.json"
    maps_path=troot/"regions/map_downloads.json"
    if not idx_path.exists() or not maps_path.exists():
        return
    idx=json.loads(idx_path.read_text(encoding="utf-8"))
    maps=json.loads(maps_path.read_text(encoding="utf-8"))
    width=int(idx["grid_1km"]["width"]); height=int(idx["grid_1km"]["height"])
    ov=overlay_path(data_root)
    count=0
    for p in idx.get("periods",[]):
        anomaly_rel=p.get("anomaly")
        if not anomaly_rel:
            continue
        source=troot/str(anomaly_rel)
        if not source.exists():
            continue
        key=str(p["key"])
        target_rel=f"download_maps/{key}_anomaly.png"
        arr=load_i16(source,width,height)
        render(arr,troot/target_rel,CFG["tmean"],str(p.get("label",key)),str(p.get("start_date","")),str(p.get("end_date","")),ov)
        mi=maps.setdefault("periods",{}).setdefault(key,{"label":p.get("label",key)})
        mi["anomaly"]=target_rel
        if p.get("reference_exact") is not None:
            mi["reference_exact"]=bool(p.get("reference_exact"))
        if p.get("reference_note"):
            mi["reference_note"]=p.get("reference_note")
        count+=1
    maps["data_through"]=idx.get("data_through")
    maps_path.write_text(json.dumps(maps,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Tmean: {count} Abweichungskarten mit finaler Skala neu gerendert.",flush=True)

def parameter_state(data_root,c):
    if c.key=="tmean":
        idx_path=data_root/"tmean/index.json"; maps_path=data_root/"tmean/regions/map_downloads.json"; idx=json.loads(idx_path.read_text()); maps=json.loads(maps_path.read_text()); year=int(idx["year"]); through=str(idx["data_through"]); current_name=str(idx["current_source_file"])
    else:
        idx_path=data_root/c.key/"regions/index.json"; maps_path=data_root/c.key/"regions/map_downloads.json"; idx=json.loads(idx_path.read_text()); maps=json.loads(maps_path.read_text()); year=int(idx["year"]); through=str(idx["data_through"]); current_name=annual_files(c)[year]
    return idx_path,maps_path,idx,maps,year,through,current_name

def process(data_root,cache_root,work,c,reference_only=False,month_override=None):
    idx_path,maps_path,idx,maps,year,through,current_name=parameter_state(data_root,c)
    month=month_override or int(through[5:7]); current=work/current_name
    if not current.exists(): download(f"{c.daily_base}/{current_name}",current)
    probe_date=f"{year}-{month:02d}-01"; _,ex,ey=current_mean(current,c,probe_date,probe_date)
    daily_ref=build_month_cache(c,month,cache_root,work,ex,ey)
    if reference_only:return
    ov=overlay_path(data_root)
    periods=idx.get("periods",[])
    for p in periods:
        key=str(p["key"]); end=str(p.get("end_date",""))
        if end!=through:continue
        if c.key=="tmean" and not bool(p.get("live")):continue
        mi=maps.setdefault("periods",{}).setdefault(key,{"label":p.get("label",key)})
        if c.key!="tmean" and mi.get("anomaly"):continue
        start=str(p["start_date"]); cur,x,y=current_mean(current,c,start,end)
        if not same_grid(x,y,ex,ey):raise RuntimeError(f"{c.key}: aktuelles Raster passt nicht")
        ref=period_ref(c,start,end,daily_ref,work,ex,ey); anom=cur-ref
        rel=f"download_maps/{key}_anomaly.png"; render(anom,data_root/c.key/rel,c,str(p.get("label",key)),start,end,ov)
        mi["anomaly"]=rel; mi["reference_exact"]=True; mi["reference_note"]="Tagesgenauer Vergleich mit demselben Kalenderabschnitt des HYRAS-Mittels 1991–2020."
        if c.key=="tmean":
            arel=f"current/{key}_anomaly.i16.gz"; qwrite(data_root/"tmean"/arel,anom); p["anomaly"]=arel; p["reference_exact"]=True; p["reference_note"]=mi["reference_note"]
            p.setdefault("stats",{})["reference_mean_c"]=round(float(np.nanmean(ref)),2); p["stats"]["anomaly_mean_k"]=round(float(np.nanmean(anom)),2)
        print(f"{c.label}: Live-Anomalie {key}",flush=True)
    idx_path.write_text(json.dumps(idx,ensure_ascii=False,indent=2)); maps_path.write_text(json.dumps(maps,ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data-root",default="/tmp/hyras-data"); ap.add_argument("--reference-cache",default="/tmp/hyras-temperature-reference-cache"); ap.add_argument("--parameter",choices=("all","tmean","tmax","tmin"),default="all"); ap.add_argument("--build-reference-only",action="store_true"); ap.add_argument("--month",type=int); args=ap.parse_args()
    data_root=Path(args.data_root); cache_root=Path(args.reference_cache); params=("tmean","tmax","tmin") if args.parameter=="all" else (args.parameter,)
    for key in params: process(data_root,cache_root,Path(f"/tmp/hyras-{key}-live-ref"),CFG[key],args.build_reference_only,args.month)
    if not args.build_reference_only:
        if "tmean" in params:
            rerender_all_tmean_anomaly_maps(data_root)
        meta={"schema_version":1,"reference":"1991-2020","method":"Tagesgenaue Rasterreferenz für laufende Teilzeiträume; kompakte Monatscaches liegen im GitHub-Actions-Cache.","parameters":params}
        (data_root/"_temperature_reference.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())