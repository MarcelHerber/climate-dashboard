#!/usr/bin/env python3
"""GFS 0.25° North Atlantic sea-level lows and Hart (2003) CPS.

Unlike ECMWF's TC-specific BUFR, this detects gridpoint SLP minima, associates
them across forecasts and computes motion-relative B, lower and upper thermal
wind from 900/850/700/600/500/400/300 hPa geopotential heights.

GFS/NOMADS archive is a live upstream dependency; never fabricate observations.
This is a research algorithm, NOT an operational cyclone tracking product.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import logging
import math
from pathlib import Path
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from scipy.ndimage import minimum_filter
from eccodes import codes_grib_new_from_file, codes_get, codes_get_array, codes_release

UTC=dt.timezone.utc
LEVELS=[900,850,700,600,500,400,300]
HOURS=list(range(0,121,6))
LEVEL_KEYS={"gh":LEVELS,"msl":[],"land":[],"sp":[],"u10":[],"v10":[]}
BASE="https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
MPS_KMH=3.6

def fetch(run,lead,target):
    params={"file":f"gfs.t{run:%H}z.pgrb2.0p25.f{lead:03d}",
        "subregion":"","leftlon":"220","rightlon":"359.75",
        "toplat":"80","bottomlat":"10",
        "dir":f"/gfs.{run:%Y%m%d}/{run:%H}/atmos",
        "var_PRMSL":"on","var_HGT":"on","var_LAND":"on",
        "var_PRES":"on","var_UGRD":"on","var_VGRD":"on",
        "lev_mean_sea_level":"on","lev_surface":"on",
        "lev_10_m_above_ground":"on",
        **{f"lev_{p}_mb":"on" for p in LEVELS}}
    request=Request(BASE+"?"+urlencode(params),headers={"User-Agent":"ClimateDashboardResearch/1.0; GFS CPS study"})
    with urlopen(request,timeout=90) as r:
        buf=r.read(25_000_000)
    if len(buf)<2000 or not buf.startswith(b"GRIB"):raise ValueError("NOMADS returned empty/non-GRIB data")
    target.write_bytes(buf)

def get_cube(filename):
    values={}
    lat=None;lon=None;shape=None
    with filename.open("rb") as handle:
        while (msg:=codes_grib_new_from_file(handle)) is not None:
            try:
                short=str(codes_get(msg,"shortName"))
                leveltype=str(codes_get(msg,"typeOfLevel"))
                p=int(codes_get(msg,"level"))
                label=None
                if leveltype=="isobaricInhPa" and p in LEVELS and short in ("gh","z"):
                    label=f"z{p}"
                elif short in ("prmsl","msl") and leveltype in ("meanSea","meanSeaLevel"):
                    label="msl"
                elif short in ("lsm","land") and leveltype=="surface":label="land"
                elif short in ("sp","pres") and leveltype=="surface":label="sp"
                elif short in ("10u","u10") and leveltype=="heightAboveGround" and p==10:label="u10"
                elif short in ("10v","v10") and leveltype=="heightAboveGround" and p==10:label="v10"
                # On GRIB2 GFS variables may map shortName 10u/10v differently;
                # fall back to paramId/shortName diagnostic in reported error.
                if label is None:continue
                nj=int(codes_get(msg,"Nj"));ni=int(codes_get(msg,"Ni"))
                arr=np.asarray(codes_get_array(msg,"values"),dtype=np.float32)
                if arr.size!=ni*nj:raise ValueError(f"incorrect grid size for {label}")
                values[label]=arr.reshape((nj,ni))
                if lat is None:
                    lat=np.asarray(codes_get_array(msg,"latitudes"),dtype=np.float32).reshape((nj,ni))
                    lon=np.asarray(codes_get_array(msg,"longitudes"),dtype=np.float32).reshape((nj,ni))
                    shape=(nj,ni)
            finally:
                codes_release(msg)
    required=["msl"]+[f"z{p}" for p in LEVELS]
    missing=[k for k in required if k not in values]
    if missing:raise ValueError(f"Missing GRIB fields: {missing}; found {list(values)}")
    if values["msl"].mean()>1500:values["msl"]/=100
    if "sp" in values and values["sp"].mean()>1500:values["sp"]/=100
    for p in LEVELS:
        z=values[f"z{p}"]
        # GFS HGT in meters; if it comes as geopotential m²/s², convert it.
        if p==300 and np.nanmedian(z)>12000:values[f"z{p}"]/=9.80665
    return values,lat,((lon+180)%360)-180

def haversine(la,lo,lb,lblo):
    r=math.pi/180
    a=math.sin((lb-la)*r/2)**2+math.cos(la*r)*math.cos(lb*r)*math.sin((lblo-lo)*r/2)**2
    return 12742*math.asin(min(1,math.sqrt(max(0,a))))

def region(lat,lon,la,lo,radius_km=500):
    dy=(lat-la)*111.195
    dx=(lon-lo)*111.195*np.cos(np.radians((lat+la)/2))
    dist=np.hypot(dx,dy)
    return dist<=radius_km,dx,dy,dist

def centers(fields,lat,lon):
    p=fields["msl"]
    local=minimum_filter(p,size=13,mode="nearest")
    candidate=np.where((p<=1012)&(p<=local+.03)&(lat>=27)&(lat<=75)&(lon>=-105)&(lon<=-8))
    ordered=sorted(zip(*candidate),key=lambda ij:float(p[ij]))
    accepted=[]
    for i,j in ordered:
        la,lo=float(lat[i,j]),float(lon[i,j])
        if "land" in fields and fields["land"][i,j]>.7:continue
        if any(haversine(la,lo,x["lat"],x["lon"])<280 for x in accepted):continue
        # Validate pressure minimum against the 180–380 km surrounding annulus.
        # Also require sufficient coverage so edges aren't treated as real lows.
        mask,_,_,distance=region(lat,lon,la,lo,390)
        annulus=mask&(distance>=180)
        if annulus.sum()<70:continue
        rim=float(np.nanmean(p[annulus]))
        if not np.isfinite(rim) or rim-float(p[i,j])<3:continue
        accepted.append({"lat":round(la,2),"lon":round(lo,2),"mslp_hpa":round(float(p[i,j]),1),
                         "i":int(i),"j":int(j),"contrast_hpa":round(rim-float(p[i,j]),1)})
        if len(accepted)>=34:break
    return accepted

def tracks_from_centers(centers_by_hour,run):
    tracks=[];counter=0
    previous={}
    for hour in HOURS:
        centers=centers_by_hour.get(hour,[])
        proposals=[]
        for tid,track in previous.items():
            last=track["points"][-1]
            for j,c in enumerate(centers):
                km=haversine(last["lat"],last["lon"],c["lat"],c["lon"])
                dt_hours=hour-last["h"]
                if dt_hours<=0 or km>min(1250,dt_hours*115):continue
                pdiff=abs(last["mslp_hpa"]-c["mslp_hpa"])
                if pdiff>25:continue
                proposals.append((km+pdiff*11,tid,j))
        proposals.sort()
        assigned_tracks=set();assigned_centers=set();now={}
        for _,tid,j in proposals:
            if tid in assigned_tracks or j in assigned_centers:continue
            c=centers[j]
            tracks[tid]["points"].append(make_point(c,hour,run))
            now[tid]=tracks[tid];assigned_tracks.add(tid);assigned_centers.add(j)
        for j,c in enumerate(centers):
            if j in assigned_centers:continue
            name=f"Nordatlantik-Tief {counter+1:02d}"
            track={"id":f"gfs-atl-{run:%Y%m%d%H}-{counter+1:02d}",
                   "storm_id":f"ATL-{run:%m%d%H}-{counter+1:02d}",
                   "name":name,"model":"gfs","member":0,"is_ensemble":False,
                   "source":"GFS 0.25° MSLP and HGT (NOMADS)",
                   "run":run.strftime("%Y-%m-%dT%H:%M:%SZ"),"points":[make_point(c,hour,run)]}
            tracks.append(track);now[counter]=track;counter+=1
        previous=now
    # Require repeat detection and at least 12h longevity. This is not proof of
    # a closed low, but removes many single-step numerical minima.
    return [t for t in tracks if len(t["points"])>=3
            and t["points"][-1]["h"]-t["points"][0]["h"]>=12]

def make_point(c,lead,run):
    return {"h":lead,"time":(run+dt.timedelta(hours=lead)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lat":c["lat"],"lon":c["lon"],"mslp_hpa":c["mslp_hpa"],
            "vmax_ms":None,"cps":None,"phase":None,"contrast_hpa":c["contrast_hpa"]}

def thermal_wind(levels,amplitudes):
    xs=np.log(np.asarray(levels,dtype=float))
    ys=np.asarray(amplitudes,dtype=float)
    if not np.all(np.isfinite(ys)):return None
    return float(np.polyfit(xs,ys,1)[0])

def calculate_cps(field,lat,lon,point,motion):
    la,lo=point["lat"],point["lon"]
    mask,dx,dy,distance=region(lat,lon,la,lo)
    if mask.sum()<180 or "sp" in field and np.count_nonzero(mask&(field["sp"]>=900))<180:
        return None
    if "sp" in field:mask &= field["sp"]>=900
    valid=mask.copy()
    for lev in LEVELS:valid &= np.isfinite(field[f"z{lev}"])
    if np.count_nonzero(valid)<180:return None
    # Hart ΔZ = max(Z)-min(Z), over identical 500-km disks for each level.
    amps={lev:float(np.nanmax(field[f"z{lev}"][valid])
                    -np.nanmin(field[f"z{lev}"][valid])) for lev in LEVELS}
    low=thermal_wind([900,850,700,600],[amps[x] for x in (900,850,700,600)])
    upper=thermal_wind([600,500,400,300],[amps[x] for x in (600,500,400,300)])
    if low is None or upper is None:return None
    vx,vy=motion
    if math.hypot(vx,vy)<15:return None
    cross=vx*dy-vy*dx
    right=valid&(cross<0)
    left=valid&(cross>0)
    if np.count_nonzero(left)<65 or np.count_nonzero(right)<65:return None
    thickness=field["z600"]-field["z900"]
    weight=np.cos(np.radians(lat))
    means=[]
    for select in (right,left):
        w=weight[select].astype(float)
        means.append(float(np.average(thickness[select],weights=w)))
    b=means[0]-means[1] # NH: right-minus-left relative to motion
    if not np.isfinite(b):return None
    return {"b":round(b,2),"vt_lower":round(low,2),"vt_upper":round(upper,2),
            "radius_km":500,"levels_hpa":[900,850,700,600,500,400,300],
            "method":"Hart (2003), thickness right-left and ln(p) regression",
            "valid_gridpoints":int(np.count_nonzero(valid))}

def phase(cps):
    if cps is None:return None
    b,lower,upper=cps["b"],cps["vt_lower"],cps["vt_upper"]
    if b>=10 and lower<=0:return "Asymmetrischer Kaltkern (außertropischer Charakter)"
    if lower>0 and upper>0:return "Tiefreichender Warm Core"
    if lower>0 and upper<=0:return "Flacher Warm Core / Hybrid"
    if lower<=0 and upper<=0:return "Kaltkern"
    return "Asymmetrisch / Übergangsstruktur" if b>=10 else "Thermisch gemischter Kern"

def bergeron_24h(current, previous):
    """Latitude-adjusted 24-hour Bergeron scale, defined for 25–75N."""
    if previous is None or current is None:
        return None
    lat=float(current["lat"])
    if not 25<=lat<=75:
        return None
    fall=float(previous["mslp_hpa"])-float(current["mslp_hpa"])
    reference=24*math.sin(math.radians(lat))/math.sin(math.radians(60))
    if reference<=0:
        return None
    return {"pressure_drop_hpa_24h":round(fall,1),
            "bergeron":round(fall/reference,2),
            "explosive":bool(fall>=reference),
            "reference_hpa_24h":round(reference,1)}


def wind_radii_10m(fields, lat, lon, point, search_km=600):
    """Directional 10-m wind threshold radii from actual GFS gridpoints.

    These are radial-reach estimates, NOT operational 925-hPa gale radii,
    closed isotach contours, or wind-swath probabilities.
    """
    if "u10" not in fields or "v10" not in fields:
        return None
    inside,dx,dy,distance=region(lat,lon,point["lat"],point["lon"],search_km)
    speed=np.hypot(fields["u10"],fields["v10"])
    finite_mask=inside&np.isfinite(speed)&(distance>=10)
    if np.count_nonzero(finite_mask)<100:
        return None
    sectors={
        "NE":(dx>=0)&(dy>=0),"SE":(dx>=0)&(dy<0),
        "SW":(dx<0)&(dy<0),"NW":(dx<0)&(dy>=0),
    }
    out={}
    for key,threshold in (("gale34",17.5),("storm48",24.7),("hurricane64",32.9)):
        quartiles={}
        for quadrant,sector in sectors.items():
            distances=distance[finite_mask&sector&(speed>=threshold)]
            # A few isolated gridpoints are not enough to describe a storm radius.
            quartiles[quadrant]=round(float(np.percentile(distances,90))) if distances.size>=3 else 0
        out[key]=quartiles
    return {"unit":"km","height":"10 m","method":"90th percentile radial reach of threshold-exceeding GFS gridpoints per geographic quadrant",
            "search_radius_km":search_km,"thresholds_ms":{"gale34":17.5,"storm48":24.7,"hurricane64":32.9},
            "quadrants":out}


def sampled_wind_cells(fields, lat, lon, point):
    """Direct sampled GFS 10-m wind speeds (~1° spacing within 550 km).

    Native GFS is 0.25°, but only every fourth gridpoint is sent to the
    browser to keep the JSON small. NOT gridded interpolation/isotachs.
    """
    if "u10" not in fields or "v10" not in fields:
        return None
    _,_,_,r=region(lat,lon,point["lat"],point["lon"],550)
    speed=np.hypot(fields["u10"],fields["v10"])
    select=(r[::4,::4]<=550)&np.isfinite(speed[::4,::4])&(speed[::4,::4]>=10)
    rows,cols=np.where(select)
    if rows.size==0:
        return []
    lats=lat[::4,::4];lons=lon[::4,::4];winds=speed[::4,::4]
    result=[]
    for i,j in zip(rows[:220],cols[:220]):
        result.append([round(float(lats[i,j]),2),round(float(lons[i,j]),2),
                       round(float(winds[i,j]),1)])
    return result


def enrich(tracks,grids):
    by_hour={}
    for t in tracks:
        for idx,p in enumerate(t["points"]):
            prior=t["points"][max(0,idx-1)]
            following=t["points"][min(len(t["points"])-1,idx+1)]
            dx=(following["lon"]-prior["lon"])*111.195*math.cos(math.radians(p["lat"]))
            dy=(following["lat"]-prior["lat"])*111.195
            by_hour.setdefault(p["h"],[]).append((p,(dx,dy)))
    for hour,points in by_hour.items():
        if hour not in grids:continue
        fields,lat,lon=grids[hour]
        for p,motion in points:
            c=calculate_cps(fields,lat,lon,p,motion)
            if c is not None:
                p["cps"]=c;p["phase"]=phase(c)
            if "u10" in fields and "v10" in fields:
                disk,_,_,dist=region(lat,lon,p["lat"],p["lon"],400)
                if disk.any():
                    speed=np.hypot(fields["u10"][disk],fields["v10"][disk])
                    good=speed[np.isfinite(speed)]
                    if good.size:p["vmax_ms"]=round(float(good.max()),2)
                p["wind_radii"]=wind_radii_10m(fields,lat,lon,p)
                p["wind_cells_10m"]=sampled_wind_cells(fields,lat,lon,p)
    # Exact +24h track-matched central-pressure differences only.
    # Never infer intensification from the current pressure alone.
    for t in tracks:
        by_h={p["h"]:p for p in t["points"]}
        for p in t["points"]:
            if p["h"]-24 not in by_h:
                p["cyclogenesis_24h"]=None
            else:
                p["cyclogenesis_24h"]=bergeron_24h(p,by_h[p["h"]-24])
    return tracks

def run_candidates(now):
    out=[]
    for d in range(0,2):
        date=now.date()-dt.timedelta(days=d)
        for hh in [18,12,6,0]:
            run=dt.datetime.combine(date,dt.time(hour=hh),tzinfo=UTC)
            if run<=now-dt.timedelta(hours=4):out.append(run)
    return out

def process(out,run):
    grids={};detected={}
    with tempfile.TemporaryDirectory(prefix="gfs-cps-") as tmp:
        for h in HOURS:
            source=Path(tmp)/f"gfs_{h:03d}.grb2"
            for attempt in range(3):
                try:
                    fetch(run,h,source)
                    fields,lat,lon=get_cube(source)
                    grids[h]=(fields,lat,lon)
                    detected[h]=centers(fields,lat,lon)
                    print(f"step +{h:03d} h: {len(detected[h])} lows; "
                          f"fields {list(fields)}",flush=True)
                    break
                except Exception as exc:
                    if attempt==2:raise RuntimeError(f"GFS {run:%Y%m%d%H} +{h}: {exc}") from exc
                    time.sleep(3*(attempt+1))
                finally:
                    source.unlink(missing_ok=True)
    tracks=enrich(tracks_from_centers(detected,run),grids)
    for t in tracks:
        t["points"]= [p for p in t["points"] if p["h"] in grids]
        t["points"].sort(key=lambda p:p["h"])
    count=sum(p["cps"] is not None for t in tracks for p in t["points"])
    if not tracks or count<2:
        raise RuntimeError(f"Insufficient real GFS storm/CPS diagnostics: tracks={len(tracks)}, valid CPS={count}")
    payload={
        "schema":1,"updated_utc":dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":"NOAA/NCEP GFS 0.25° via NOMADS GRIB filter",
        "scope":"North Atlantic 27–75N, 105W–8W",
        "method":"MSLP local minima + pressure contrast + nearest-center 6h tracking; Hart (2003) 500-km 900–600/600–300 hPa",
        "limitations":"Research tracker. MSLP minimum may not be a complete closed low; track linking and CPS are diagnostic estimates, not operational classifications. Land pressure levels below ground masked when surface pressure available.",
        "models":[{"model":"gfs","run":run.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "status":"ok","error":None}],
        "tracks":tracks,"cps_available":True,
        "cps_points":count,
        "steps":HOURS
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"run":payload["models"][0]["run"],"tracks":len(tracks),"cps_points":count},ensure_ascii=False),flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=Path("data/cyclone-tracker/atlantic.json"))
    parser.add_argument("--run",help="UTC run YYYYMMDDHH (optional)")
    args=parser.parse_args()
    now=dt.datetime.now(UTC)
    candidates=([dt.datetime.strptime(args.run,"%Y%m%d%H").replace(tzinfo=UTC)]
                if args.run else run_candidates(now))
    err=[]
    main_run = None
    for run in candidates[:4]:
        try:
            process(args.out,run)
            main_run = run
            break
        except Exception as exc:
            logging.warning("Run %s not usable: %s",run,exc)
            err.append(str(exc))
    if main_run is None:
        # Preserve last known good output, if any, and return failure to GitHub CI.
        raise SystemExit("No complete GFS North Atlantic CPS run: "+"; ".join(err[:4]))

    # Keep recent independent GFS initialization cycles to show a true
    # lagged-run CPS spaghetti diagram, clearly NOT a GEFS perturbation ensemble.
    history_dir=args.out.parent/"atlantic_history"
    history_dir.mkdir(parents=True,exist_ok=True)
    for previous_run in candidates:
        if previous_run>=main_run:
            continue
        file=history_dir/f"gfs_{previous_run:%Y%m%d%H}.json"
        if file.exists() and file.stat().st_size>500:
            continue
        try:
            process(file,previous_run)
        except Exception as exc:
            logging.warning("Historical run %s missing; no fabricated values: %s",
                            previous_run,exc)
        # At most two additional GFS runs per refresh to cap download costs.
        if len([p for p in history_dir.glob("gfs_*.json") if p.stat().st_size>500])>=5:
            break

    keep=sorted(history_dir.glob("gfs_*.json"),reverse=True)[:5]
    for file in history_dir.glob("gfs_*.json"):
        if file not in keep:
            file.unlink()
    index={"schema":1,
           "description":"GFS multi-run lagged analyses, not GEFS members",
           "latest_run_utc":main_run.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "runs":["atlantic.json"]+
                [f"atlantic_history/{p.name}" for p in keep]}
    (args.out.parent/"atlantic_history_index.json").write_text(
        json.dumps(index,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Historical GFS runs:",index["runs"],flush=True)

if __name__=="__main__":
    main()
