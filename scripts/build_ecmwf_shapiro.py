#!/usr/bin/env python3
"""ECMWF IFS Shapiro-Keyser diagnostics for the password-protected Dynamics Studio.

All map pixels originate from ECMWF 0.25-degree IFS Open Data. Theta-e and
frontogenesis are diagnostics, not forecast-native fields. The candidate
screen is explicitly NOT a Shapiro-Keyser or sting-jet classifier.
Cross section atlas preserves individual 300..925 hPa pressure levels.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import tempfile

import eccodes
from ecmwf.opendata import Client
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, minimum_filter, maximum_filter

from build_ecmwf_dynamics import (
    WEST, EAST, SOUTH, NORTH, STEP, WIDTH, HEIGHT, HOURS,
    cycle_candidates, erte_pv,
)

LOG=logging.getLogger("ifs-shapiro")
LEVELS=(300,400,500,600,700,850,925)
PV_LEVELS=(200,250,300)
SURFACE=("msl","sp")
STANDARD=("u","v","r","w","t")
SCALES={
    "thetae":(260.,370.), "msl":(940.,1050.),
    "fgen":(-32.,32.), "wind850":(0.,85.), "wind700":(0.,95.),
    "rh700":(0.,100.), "rh500":(0.,100.),
    "pv":(-2.,15.), "jet300":(0.,110.), "gh500":(4300.,6100.),
    "omega700":(-3.,3.),"u850":(-85.,85.),"v850":(-85.,85.)
}
ATLAS_SCALES={"wind":(0.,105.),"rh":(0.,100.),"omega":(-5.,5.),"theta":(240.,410.)}
MAP_NAMES=tuple(SCALES)
ATLAS_NAMES=tuple(ATLAS_SCALES)
R_EARTH=6371000.


def read_grib(path:Path, needed:set[str]) -> dict[str,np.ndarray]:
    output={}
    with path.open("rb") as stream:
        while True:
            h=eccodes.codes_grib_new_from_file(stream)
            if h is None:break
            try:
                par=str(eccodes.codes_get(h,"shortName"))
                key=par if par in SURFACE else par+str(int(eccodes.codes_get(h,"level")))
                if key not in needed:continue
                if key in output:raise ValueError("Duplicate field "+key)
                lat=np.asarray(eccodes.codes_get_array(h,"latitudes"),np.float32)
                lon=np.asarray(eccodes.codes_get_array(h,"longitudes"),np.float32)
                v=np.asarray(eccodes.codes_get_values(h),np.float32)
                if len(v)!=len(lat) or len(v)!=len(lon):raise ValueError("GRIB shape mismatch "+key)
                lon=np.where(lon>180,lon-360,lon)
                iy=np.rint((NORTH-lat)/STEP).astype(np.int32)
                ix=np.rint((lon-WEST)/STEP).astype(np.int32)
                mask=(ix>=0)&(ix<WIDTH)&(iy>=0)&(iy<HEIGHT)
                mask &= np.isfinite(v)
                mask &= (np.abs(WEST+ix*STEP-lon)<.02)&(np.abs(NORTH-iy*STEP-lat)<.02)
                raster=np.full((HEIGHT,WIDTH),np.nan,np.float32)
                raster[iy[mask],ix[mask]]=v[mask]
                if np.isfinite(raster).mean()<.99:raise ValueError("Incomplete ECMWF grid "+key)
                output[key]=raster
            finally:
                eccodes.codes_release(h)
    if set(output)!=needed:
        raise ValueError("GRIB missing "+",".join(sorted(needed-set(output))))
    return output


def retrieve(client:Client,run:datetime,hour:int) -> dict[str,np.ndarray]:
    common=dict(date=run.strftime("%Y%m%d"),time=run.hour,
                stream="oper",type="fc",step=hour,resol="0p25")
    with tempfile.TemporaryDirectory() as folder:
        tmp=Path(folder)
        # 7 full atmospheric levels: wind, humidity, omega, potential temperature.
        sets=[
            ("profile", "pl", list(STANDARD), list(LEVELS),
             {p+str(z) for p in STANDARD for z in LEVELS}),
            ("humidity", "pl", ["q"], [850], {"q850"}),
            ("pv", "pl", ["u","v","t","vo"], list(PV_LEVELS),
             {p+str(z) for p in ("u","v","t","vo") for z in PV_LEVELS}),
            ("height", "pl", ["gh"], [500], {"gh500"}),
            ("surface","sfc",["msl","sp"],None,{"msl","sp"}),
        ]
        fields={}
        for name,levtype,params,levels,expected in sets:
            path=tmp/(name+".grib2")
            args={**common,"levtype":levtype,"param":params,"target":str(path)}
            if levels is not None:args["levelist"]=levels
            client.retrieve(**args)
            fields.update(read_grib(path,expected))
    return fields


def theta_e(t:np.ndarray,q:np.ndarray,p_hpa:float=850.) -> np.ndarray:
    """Bolton (1980) approximate equivalent potential temperature, Kelvin."""
    p=p_hpa*100.
    q=np.clip(q.astype(np.float64),1e-8,.05)
    t=np.clip(t.astype(np.float64),180.,340.)
    mix=q/(1-q)
    e=p*mix/(.622+mix) / 100.  # hPa
    ln_e=np.log(np.maximum(e,.01)/6.112)
    td=243.5*ln_e/(17.67-ln_e)+273.15
    tl=1./(1./(td-56.)+np.log(t/td)/800.)+56.
    return (t*(1000./p_hpa)**(.2854*(1-.28*mix))*
            np.exp((3376./tl-2.54)*mix*(1+.81*mix))).astype(np.float32)


def frontogenesis(thetae:np.ndarray,u:np.ndarray,v:np.ndarray) -> np.ndarray:
    """Kinematic horizontal frontogenesis term, K/(100 km * 3 h).

    -g_i (∂u_j/∂x_i) g_j / |g|, based on smoothed 850-hPa theta-e.
    Does not include diabatic effects or the vertical tilting term.
    """
    lat=np.deg2rad(NORTH-np.arange(HEIGHT)*STEP)
    dx=(111195.*STEP*np.maximum(np.cos(lat),.12))[:,None]
    dy=111195.*STEP
    th=gaussian_filter(thetae.astype(np.float64),1.25)
    uu=gaussian_filter(u.astype(np.float64),1.0)
    vv=gaussian_filter(v.astype(np.float64),1.0)
    gx=np.gradient(th,axis=1)/dx
    gy=-np.gradient(th,axis=0)/dy
    ux=np.gradient(uu,axis=1)/dx
    uy=-np.gradient(uu,axis=0)/dy
    vx=np.gradient(vv,axis=1)/dx
    vy=-np.gradient(vv,axis=0)/dy
    grad=np.maximum(np.hypot(gx,gy),1e-12)
    fgen=-(gx*gx*ux+gx*gy*(uy+vx)+gy*gy*vy)/grad
    return (fgen*100000.*10800.).astype(np.float32)


def encode(arr:np.ndarray,limit:tuple[float,float],min_coverage:float=.98) -> Image.Image:
    lo,hi=limit
    a=np.asarray(arr)
    valid=np.isfinite(a)
    if valid.mean()<min_coverage:raise ValueError("Too many missing values in encoded field")
    px=np.full(a.shape,255,np.uint8)
    px[valid]=np.rint(np.clip((a[valid]-lo)/(hi-lo),0,1)*254).astype(np.uint8)
    return Image.fromarray(px)


def detect_lows(msl:np.ndarray,theta:np.ndarray,fgen:np.ndarray,
                wind:np.ndarray,hour:int) -> list[dict]:
    """Transparent pressure-minimum screening, NOT cyclone-type attribution."""
    p=msl.astype(np.float64)
    min_p=minimum_filter(p,size=13,mode="nearest")
    max_p=maximum_filter(p,size=35,mode="nearest")
    # Avoid duplicates from broad flat minima: one point per 1.75-degree neighborhood.
    low_mask=(p<=1005.)&(p<=min_p+.02)&((max_p-p)>=8.)
    low_mask[:20,:]=False;low_mask[-20:,:]=False
    low_mask[:20]=False;low_mask[:,:20]=False;low_mask[:,-20:]=False
    ys,xs=np.where(low_mask)
    sorted_indexes=sorted(zip(ys,xs),key=lambda pair:p[pair])
    accepted=[]
    for y,x in sorted_indexes:
        if any((y-cy)**2+(x-cx)**2<12**2 for cy,cx in accepted):continue
        accepted.append((int(y),int(x)))
        if len(accepted)>=14:break
    out=[]
    for y,x in accepted:
        sl=(slice(max(0,y-12),min(HEIGHT,y+13)),slice(max(0,x-12),min(WIDTH,x+13)))
        yy,xx=np.mgrid[sl]
        dist=(xx-x)**2+(yy-y)**2
        ring=(dist>=5**2)&(dist<=12**2)
        region_th=theta[sl]
        centre=float(np.mean(theta[max(0,y-2):y+3,max(0,x-2):x+3]))
        ring_mean=float(np.nanmean(region_th[ring]))
        warm_anomaly=centre-ring_mean
        frontmax=float(np.nanpercentile(np.maximum(fgen[sl],0),95))
        windmax=float(np.nanmax(wind[sl]))
        depth=float(max_p[y,x]-p[y,x])
        criteria={
          "developed_low":depth>=12,
          "organized_frontogenesis":frontmax>=3,
          "strong_low_level_wind":windmax>=25,
          "warm_core_proxy":warm_anomaly>=2.0,
        }
        score=sum(criteria.values())
        # The warm-core proxy by itself cannot establish a warm seclusion.
        if score<2:continue
        out.append({
          "lon":round(WEST+x*STEP,2),"lat":round(NORTH-y*STEP,2),
          "hour":hour,"msl_hpa":round(float(p[y,x]),1),
          "depth_hpa":round(depth,1),
          "wind850_ms":round(windmax,1),
          "thetae_core_minus_ring_k":round(warm_anomaly,1),
          "fgen_max_k_100km_3h":round(frontmax,1),
          "score":score,"criteria":criteria,
          "classification":"automatic_screening_only",
        })
    return sorted(out,key=lambda c:(-c["score"],c["msl_hpa"]))[:8]


def derive(fields:dict[str,np.ndarray],hour:int) -> tuple[dict,dict,list]:
    te=theta_e(fields["t850"],fields["q850"])
    fgen=frontogenesis(te,fields["u850"],fields["v850"])
    wind850=np.hypot(fields["u850"],fields["v850"])
    wind700=np.hypot(fields["u700"],fields["v700"])
    maps={
      "thetae":te,"msl":fields["msl"]/100.,
      "fgen":fgen,"wind850":wind850,"wind700":wind700,
      "rh700":fields["r700"],"rh500":fields["r500"],
      "pv":erte_pv(fields),"jet300":np.hypot(fields["u300"],fields["v300"]),
      "gh500":fields["gh500"],"omega700":fields["w700"],
      "u850":fields["u850"],"v850":fields["v850"],
    }
    # Mask subterrain levels using ECMWF surface pressure, rather than extrapolating.
    def stack(field):
        return np.vstack([
            np.where(fields["sp"] >= z*100.,field(z),np.nan)
            for z in LEVELS
        ])
    atlases={
      "wind":stack(lambda z:np.hypot(fields["u"+str(z)],fields["v"+str(z)])),
      "rh":stack(lambda z:fields["r"+str(z)]),
      "omega":stack(lambda z:fields["w"+str(z)]),
      "theta":stack(lambda z:fields["t"+str(z)]*(1000./z)**.2854),
    }
    lows=detect_lows(maps["msl"],te,fgen,wind850,hour)
    return maps,atlases,lows


def build(out:Path,hours:tuple[int,...]=HOURS) -> dict:
    out.mkdir(parents=True,exist_ok=True)
    client=Client(source="ecmwf",model="ifs",resol="0p25")
    cycle=None
    for run in cycle_candidates():
        try:
            retrieve(client,run,hours[-1])
            cycle=run
            break
        except Exception as error:
            LOG.warning("IFS cycle %s unavailable: %s",run,error)
    if cycle is None:raise RuntimeError("No verified IFS cycle for Shapiro monitor")
    existing=out/"current.json"
    if existing.is_file():
        try:
            old=json.loads(existing.read_text(encoding="utf-8"))
            if old.get("cycle")==cycle.strftime("%Y%m%d%H") and len(old.get("frames",[]))==len(hours):
                if all((out/f).is_file() for row in old["frames"] for f in tuple(row["maps"].values())+tuple(row["profiles"].values())):
                    return old
        except (ValueError,OSError,KeyError):
            pass
    rows=[]
    folder=out/"frames"/cycle.strftime("%Y%m%d%H")
    folder.mkdir(parents=True,exist_ok=True)
    for hour in hours:
        maps,atlases,lows=derive(retrieve(client,cycle,hour),hour)
        paths={};profiles={}
        for name,grid in maps.items():
            relative=f"frames/{cycle:%Y%m%d%H}/{name}_{hour:03d}.png"
            encode(grid,SCALES[name]).save(out/relative,optimize=True)
            paths[name]=relative
        for name,grid in atlases.items():
            relative=f"frames/{cycle:%Y%m%d%H}/profile_{name}_{hour:03d}.png"
            encode(grid,ATLAS_SCALES[name],min_coverage=.75).save(out/relative,optimize=True)
            profiles[name]=relative
        rows.append({
          "hour":hour,"valid_utc":(cycle+timedelta(hours=hour)).isoformat().replace("+00:00","Z"),
          "maps":paths,"profiles":profiles,"candidates":lows,
        })
        LOG.info("IFS Shapiro +%d: maps, %d profile atlases, %d screened lows",hour,len(profiles),len(lows))
    # Link nearby pressure minima across consecutive three-hour steps.
    next_track=1
    previous=[]
    for row in rows:
        selected=set()
        for c in row["candidates"]:
            possible=[]
            for p in previous:
                if p["track_id"] in selected:continue
                dy=(c["lat"]-p["lat"])*111.2
                dx=(c["lon"]-p["lon"])*111.2*np.cos(np.deg2rad((c["lat"]+p["lat"])/2))
                distance=float(np.hypot(dx,dy))
                if distance<650 and abs(c["msl_hpa"]-p["msl_hpa"])<25:
                    possible.append((distance,p))
            if possible:
                p=min(possible,key=lambda x:x[0])[1]
                c["track_id"]=p["track_id"]
                c["pressure_change_hpa_3h"]=round(c["msl_hpa"]-p["msl_hpa"],1)
            else:
                c["track_id"]=next_track
                c["pressure_change_hpa_3h"]=None
                next_track+=1
            selected.add(c["track_id"])
        previous=row["candidates"]
    manifest={
      "schema":1,"source":"ECMWF IFS Open Data 0.25 degree, CC BY 4.0",
      "cycle":cycle.strftime("%Y%m%d%H"),
      "initialized_utc":cycle.isoformat().replace("+00:00","Z"),
      "built_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,
              "width":WIDTH,"height":HEIGHT,"step":STEP},
      "units":{"thetae":"K","msl":"hPa","fgen":"K/(100km*3h)",
               "wind850":"m/s","wind700":"m/s","rh700":"%",
               "rh500":"%","pv":"PVU","jet300":"m/s",
               "gh500":"gpm","omega700":"Pa/s","u850":"m/s","v850":"m/s"},
      "encoding":{"minmax":SCALES,"profile_minmax":ATLAS_SCALES,
                  "missing":255,"scale_max":254},
      "profile_levels_hpa":LEVELS,
      "profile_atlas_format":"PNG L, vertically stacked pressure levels, 253 pixels per level",
      "diagnostics":{
        "thetae":"Approximate equivalent potential temperature, Bolton 1980, 850 hPa",
        "frontogenesis":"850-hPa kinematic horizontal frontogenesis of smoothed theta-e, no diabatic term",
        "pv":"Layer-mean approximate 200/250/300 hPa Ertel PV, 3 levels",
        "screening":"Objective minima/depth/frontogenesis/wind/theta-e anomaly. NO Shapiro-Keyser or sting-jet verification",
        "cross_section":"925 to 300 hPa native pressure-level forecasts, spatially interpolated along a straight lon-lat segment; subterrain levels masked using surface pressure. Not Lagrangian trajectories"
      },
      "frames":rows,
    }
    tmp=out/"current.json.tmp"
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    tmp.replace(existing)
    return manifest


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--smoke",action="store_true")
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    build(args.out,(0,3) if args.smoke else HOURS)
