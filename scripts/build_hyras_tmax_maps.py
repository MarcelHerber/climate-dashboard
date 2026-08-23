#!/usr/bin/env python3
from __future__ import annotations
import argparse, calendar, json, re
from datetime import datetime
from pathlib import Path
from typing import Any
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap
from matplotlib.patches import Rectangle
import numpy as np
from PIL import Image
import requests, xarray as xr
from build_hyras_tmax_regions import DAILY_BASE, USER_AGENT, download, latest_daily_files, pick_var, prepare_da, to_celsius

CLIM_BASE="https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/air_temperature_max"
REFERENCE_START=1991; REFERENCE_END=2020
MONTH_ABBR={1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"}
LEVELS=[-6.,-5.,-4.,-3.,-2.,-1.,-.5,0.,.5,1.,2.,3.,4.,5.,6.]
COLORS=["#6B03C6","#5E4FFC","#187DFD","#70B1FB","#C6E4FB","#DDEBF9","#EDF4FA","#FDFCFC","#FDF0BC","#FDE47C","#FDBD3E","#FC691C","#F93A19","#E51B75","#FC579B"]

def get(url,timeout=120):
    r=requests.get(url,timeout=timeout,headers={"User-Agent":USER_AGENT}); r.raise_for_status(); return r

def listing(url): return get(url+"/",90).text

def latest_clim_filename(month,text=None):
    text=text if text is not None else listing(CLIM_BASE); abbr=MONTH_ABBR[month]
    pat=re.compile(rf'href="(?P<filename>tasmax_hyras_1_{REFERENCE_START}_{REFERENCE_END}_v(?P<major>\d+)-(?P<minor>\d+)_de_{abbr}\.nc)"')
    m=[(int(x.group("major")),int(x.group("minor")),x.group("filename")) for x in pat.finditer(text)]
    if not m: raise RuntimeError(f"Keine Tmax-Klimadatei für {abbr} gefunden.")
    return sorted(m)[-1][2]

def static_2d(ds):
    da=to_celsius(pick_var(ds)).squeeze(drop=True)
    while da.ndim>2: da=da.isel({da.dims[0]:0})
    if da.ndim!=2: raise RuntimeError(f"Keine statische 2D-Tmax-Klimatologie: {da.dims}")
    dims=list(da.dims); y=next((d for d in dims if d.lower() in {"y","lat","latitude","rlat"}),dims[0]); x=next((d for d in dims if d.lower() in {"x","lon","longitude","rlon"}),dims[1]); da=da.transpose(y,x)
    a=np.asarray(da.values,np.float32); xx=np.asarray(da[x].values,np.float64); yy=np.asarray(da[y].values,np.float64); a[~np.isfinite(a)]=np.nan; return a,xx,yy

def period_current_mean(daily,td,start,end):
    s=daily.where((daily[td]>=np.datetime64(start))&(daily[td]<=np.datetime64(end)),drop=True)
    if s.sizes.get(td,0)==0: raise RuntimeError(f"Keine Tmax-Tage für {start} bis {end}.")
    a=np.asarray(s.mean(td,skipna=True).values,np.float32); a[~np.isfinite(a)]=np.nan; return a

def complete_reference_months(p):
    s=datetime.strptime(p["start_date"],"%Y-%m-%d").date(); e=datetime.strptime(p["end_date"],"%Y-%m-%d").date()
    if p["key"].startswith("month_"):
        if s.day!=1 or s.month!=e.month or s.year!=e.year or e.day!=calendar.monthrange(e.year,e.month)[1]: return None
        return [s.month]
    sm={"spring":[3,4,5],"summer":[6,7,8],"autumn":[9,10,11]}; months=sm.get(p["key"])
    if not months: return None
    es=datetime(s.year,months[0],1).date(); ee=datetime(s.year,months[-1],calendar.monthrange(s.year,months[-1])[1]).date()
    return months if s==es and e==ee else None

def reference_for_months(months,year,work,text,ex,ey):
    weighted=None; total=0
    for m in months:
        fn=latest_clim_filename(m,text); target=work/"climatology"/fn
        if not target.exists(): download(f"{CLIM_BASE}/{fn}",target)
        with xr.open_dataset(target,decode_times=True) as ds: a,x,y=static_2d(ds)
        if x.shape!=ex.shape or y.shape!=ey.shape or not np.allclose(x,ex) or not np.allclose(y,ey): raise RuntimeError(f"Tmax-Klimaraster {fn} passt nicht zum aktuellen Gitter.")
        days=calendar.monthrange(year,m)[1]; weighted=a*days if weighted is None else weighted+a*days; total+=days
    if weighted is None or total<=0: raise RuntimeError("Keine Tmax-Referenzmonate vorhanden.")
    return weighted/float(total)

def anomaly_style():
    lev=np.asarray(LEVELS,float); mids=(lev[:-1]+lev[1:])/2; bounds=np.r_[[lev[0]-.5],mids,[lev[-1]+.5]]; cmap=ListedColormap(COLORS,name="hyras_tmax_anomaly_final"); return cmap,BoundaryNorm(bounds,cmap.N,clip=True)

def draw_legend(fig):
    ax=fig.add_axes([.055,.045,.89,.05]); n=len(COLORS); ax.set_xlim(0,n); ax.set_ylim(0,1)
    for i,c in enumerate(COLORS): ax.add_patch(Rectangle((i,.42),1,.52,facecolor=c,edgecolor="white",linewidth=.8))
    zi=LEVELS.index(0.); ax.plot([zi+.5,zi+.5],[.42,.94],color="black",linewidth=.8,zorder=5)
    labels=["0" if v==0 else (f"{v:+.1f}" if abs(v)==.5 else (f"{v:+.0f}" if v>0 else f"{v:.0f}")) for v in LEVELS]
    for i,l in enumerate(labels): ax.text(i+.5,.12,l,ha="center",va="center",fontsize=7.5)
    ax.text(n+.12,.12,"K",ha="left",va="center",fontsize=8); ax.axis("off")

def render_map(a,boundary,output,title,subtitle,mode):
    anom=mode=="anomaly"; fig=plt.figure(figsize=(7.4,9.4),dpi=150)
    if anom:
        cmap,norm=anomaly_style(); ax=fig.add_axes([.055,.125,.89,.78]); im=ax.imshow(a,cmap=cmap,norm=norm,interpolation="nearest")
    else:
        cmap=LinearSegmentedColormap.from_list("hyras_tmax_absolute",["#313695","#4575b4","#74add1","#abd9e9","#e0f3f8","#ffffbf","#fee090","#fdae61","#f46d43","#d73027","#a50026"]); ax=fig.add_axes([.055,.105,.89,.80]); im=ax.imshow(a,cmap=cmap,vmin=-15.0,vmax=45.0,interpolation="nearest")
    ax.set_axis_off()
    if boundary and boundary.exists():
        ov=np.asarray(Image.open(boundary).convert("RGBA"));
        if ov.shape[:2]==a.shape: ax.imshow(ov,interpolation="nearest")
    fig.suptitle(title,fontsize=15,fontweight="bold",y=.965); fig.text(.5,.925,subtitle,ha="center",va="center",fontsize=9)
    if anom: draw_legend(fig)
    else:
        cb=fig.colorbar(im,cax=fig.add_axes([.14,.055,.72,.025]),orientation="horizontal"); cb.set_label("°C",fontsize=9); cb.ax.tick_params(labelsize=8)
    fig.text(.055,.012 if anom else .018,"Quelle: Deutscher Wetterdienst · HYRAS-DE-TASMAX · Referenz 1991–2020",fontsize=7,color="#555555")
    output.parent.mkdir(parents=True,exist_ok=True); fig.savefig(output,facecolor="white",bbox_inches="tight",pad_inches=.12); plt.close(fig)

def boundary_overlay(root):
    p=root/"hyras_index.json"
    if not p.exists(): return None
    try:
        rel=json.loads(p.read_text(encoding="utf-8")).get("interactive",{}).get("boundary_overlay_1km"); return root/rel if rel else None
    except Exception: return None

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data-root",default="/tmp/hyras-data"); ap.add_argument("--work",default="/tmp/hyras-tmax-work"); args=ap.parse_args()
    root=Path(args.data_root); work=Path(args.work); troot=root/"tmax"; regions=troot/"regions"; ip=regions/"index.json"
    if not ip.exists(): raise RuntimeError("Tmax-Regionsindex fehlt.")
    idx=json.loads(ip.read_text(encoding="utf-8")); year=int(idx["year"]); files=latest_daily_files(listing(DAILY_BASE)); fn=files.get(year)
    if not fn: raise RuntimeError(f"Keine aktuelle Tmax-Datei für {year} gefunden.")
    nc=work/fn
    if not nc.exists(): download(f"{DAILY_BASE}/{fn}",nc)
    with xr.open_dataset(nc,decode_times=True) as ds: daily,td,x,y=prepare_da(ds); daily=daily.load()
    out=troot/"download_maps"; out.mkdir(parents=True,exist_ok=True)
    for old in out.glob("*.png"): old.unlink()
    climtext=listing(CLIM_BASE); overlay=boundary_overlay(root); result={}
    for p in idx.get("periods",[]):
        key=str(p["key"]); label=str(p.get("label",key)); start=str(p["start_date"]); end=str(p["end_date"]); cur=period_current_mean(daily,td,start,end)
        arel=f"download_maps/{key}_absolute.png"; render_map(cur,overlay,troot/arel,f"HYRAS Tmax · {label}",f"2-m-Tagesmaximum · {start} bis {end}","absolute")
        item={"label":label,"absolute":arel,"start_date":start,"end_date":end}; months=complete_reference_months(p)
        if months:
            ref=reference_for_months(months,year,work,climtext,x,y); anomaly=cur-ref; rel=f"download_maps/{key}_anomaly.png"; render_map(anomaly,overlay,troot/rel,f"HYRAS Tmax · {label}",f"Abweichung zum Mittel 1991–2020 · {start} bis {end}","anomaly"); item["anomaly"]=rel; item["reference_exact"]=True
        else:
            item["reference_exact"]=False; item["reference_note"]="Für laufende Teilmonate/-jahreszeiten wird keine Rasteranomalie veröffentlicht; die Gebietskurve nutzt weiterhin die tagesgenaue 1991–2020-Referenz."
        result[key]=item; print(f"Tmax Downloadkarte {key}: absolut"+(" + Anomalie" if "anomaly" in item else ""),flush=True)
    manifest={"schema_version":1,"parameter":"tmax","reference":"1991-2020","data_through":idx.get("data_through"),"periods":result}; mp=regions/"map_downloads.json"; mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8"); idx["map_downloads_file"]=mp.name; ip.write_text(json.dumps(idx,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Tmax-Kartendownloads fertig.",flush=True); print("Perioden:",len(result),flush=True); print("Mit exakter Anomaliekarte:",sum(1 for i in result.values() if i.get("anomaly")),flush=True); return 0

if __name__=="__main__": raise SystemExit(main())
