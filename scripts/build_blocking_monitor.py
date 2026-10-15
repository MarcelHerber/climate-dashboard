#!/usr/bin/env python3
"""ERA5 500-hPa Atlantic-European blocking diagnostic and static map.

Tibaldi/Molteni-type one-dimensional gradient reversal:
 GHGS = (Z500(phi0)-Z500(phiS))/(phi0-phiS) > 0 gpm/degree;
 GHGN = (Z500(phiN)-Z500(phi0))/(phiN-phi0) < -10 gpm/degree;
 phi0=60+delta, phiS=40+delta, phiN=80+delta,
 delta in {-5,0,+5} degrees. Spatial sectors >= 10 degrees.
 Persistent event: same longitudes satisfy the condition on five
 consecutive analysed days (never infer missing history).
This is a *diagnostic*, not an operational warning or prediction.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "blocking"
DATASET = "derived-era5-pressure-levels-daily-statistics"
DOI = "10.24381/cds.50314f4c"
GRAVITY = 9.80665
OFFSETS = (-5, 0, 5)
PERSIST_DAYS = 5
MIN_WIDTH = 10
MAP_WEST, MAP_EAST = -90, 65


def request(days):
    """UTC daily mean on a fixed 1-degree Europe/Atlantic lat-lon grid."""
    if not days or any(d.year != days[0].year or d.month != days[0].month for d in days):
        raise ValueError("One CDS request must be within one calendar month")
    return {
        "product_type": "reanalysis", "variable": ["geopotential"],
        "pressure_level": ["500"], "year": str(days[0].year),
        "month": [f"{days[0].month:02d}"],
        "day": [f"{d.day:02d}" for d in days],
        "daily_statistic": "daily_mean", "time_zone": "utc+00:00",
        "frequency": "6_hourly", "area": [85, MAP_WEST, 25, MAP_EAST],
        "grid": "1/1",
    }


def parse_grids(ds, expected):
    """Reject truncated, misdated, non-finite, or physically implausible ERA5."""
    import update_era5_stratosphere as era
    data = era.select_array(ds, "z", 500)
    tim = next((v for v in ("valid_time", "time", "date") if v in data.dims), None)
    lat = next((v for v in ("latitude", "lat") if v in data.dims), None)
    lon = next((v for v in ("longitude", "lon") if v in data.dims), None)
    if not all((tim,lat,lon)):
        raise ValueError(f"Unexpected ERA5 Z500 coordinates: {data.dims}")
    dates = [str(np.datetime64(t,"D")) for t in data[tim].values]
    if dates != [d.isoformat() for d in expected]:
        raise ValueError(f"ERA5 returned unexpected days {dates}")
    lats = np.asarray(data[lat].values,dtype=float)
    lons = np.asarray(data[lon].values,dtype=float)
    if len(lats) < 60 or lats.min() > 25.1 or lats.max() < 84.9:
        raise ValueError("ERA5 latitude range incomplete")
    if len(lons) < 150 or lons.min() > MAP_WEST+.1 or lons.max() < MAP_EAST-.1:
        raise ValueError("ERA5 longitude range incomplete")
    grid = np.asarray(data.transpose(tim,lat,lon).values,dtype=float) / GRAVITY
    if not np.isfinite(grid).all() or grid.min() < 4300 or grid.max() > 6500:
        raise ValueError("ERA5 geopotential not valid Z500 (gpm)")
    return lats,lons,grid


def blocking_mask(lats,lons,z500):
    """Return per-longitude instantaneous reversal mask (1-D, not a 2-D block area)."""
    lats = np.asarray(lats,dtype=float)
    lons = np.asarray(lons,dtype=float)
    height = np.asarray(z500,dtype=float)
    if height.shape != (len(lats),len(lons)) or not np.isfinite(height).all():
        raise ValueError("Invalid height array")
    if any(np.min(np.abs(lats-(phi+o))) > .1 for o in OFFSETS for phi in (40,60,80)):
        raise ValueError("Missing TM reference latitudes")
    found = np.zeros(len(lons),dtype=bool)
    for offset in OFFSETS:
        south=height[np.argmin(abs(lats-(40+offset)))]
        central=height[np.argmin(abs(lats-(60+offset)))]
        north=height[np.argmin(abs(lats-(80+offset)))]
        ghgs=(central-south)/20
        ghgn=(north-central)/20
        found |= (ghgs>0) & (ghgn < -10)
    return found


def regions(lons,mask,minimum_degrees=MIN_WIDTH):
    """Contiguous longitude intervals with conservative finite-grid width."""
    lons=np.asarray(lons)
    found=np.asarray(mask,dtype=bool)
    if len(lons) != len(found) or (len(lons)>1 and np.any(np.diff(lons)<=0)):
        raise ValueError("Longitude mask not sorted")
    groups=[];start=None
    for i in range(len(lons)+1):
        inside=i<len(lons) and bool(found[i])
        if inside and start is None: start=i
        if not inside and start is not None:
            end=i-1
            if end>start:
                cell=float(np.median(np.diff(lons)))
                width=float(lons[end]-lons[start]+cell)
                if width>=minimum_degrees:
                    groups.append({"west":float(lons[start]),"east":float(lons[end]),"width_degrees":round(width,1)})
            start=None
    return groups


def diagnostics(lats,lons,fields,dates):
    if len(fields)!=len(dates) or len(fields)==0:
        raise ValueError("Missing analysis days")
    masks=[blocking_mask(lats,lons,field) for field in fields]
    today=masks[-1]
    instant=regions(lons,today)
    persistent=[]
    if len(dates)>=PERSIST_DAYS and all((dates[i+1]-dates[i]).days==1 for i in range(len(dates)-1)):
        streak=np.logical_and.reduce(masks[-PERSIST_DAYS:])
        persistent=regions(lons,streak)
    return {"instantaneous":instant,"persistent":persistent,
            "history_complete":len(dates)>=PERSIST_DAYS and all((dates[i+1]-dates[i]).days==1 for i in range(len(dates)-1)),
            "daily": [{"date":day.isoformat(),
                       "longitude_count":int(mask.sum())} for day,mask in zip(dates,masks)]}


def render_map(lats,lons,z500,day,blocking,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import cartopy.crs as ccrs

    fig=plt.figure(figsize=(11.6,7.5),dpi=140,facecolor="white")
    ax=fig.add_axes([.08,.18,.84,.66],projection=ccrs.PlateCarree())
    ax.set_extent([MAP_WEST,MAP_EAST,28,83],crs=ccrs.PlateCarree())
    levels=np.arange(4800,6251,40)
    cs=ax.contourf(lons,lats,z500,levels=levels,cmap="Spectral_r",extend="both",
                   transform=ccrs.PlateCarree())
    lines=ax.contour(lons,lats,z500,levels=np.arange(4800,6251,80),
                     colors="#1f2937",linewidths=.64,alpha=.74,
                     transform=ccrs.PlateCarree())
    ax.clabel(lines,inline=True,fontsize=7,fmt="%d")
    # Operational signal is a LONGITUDE sector, not an arbitrary local high.
    # Highlight across the same latitude analysis band in every sector.
    for area in blocking["instantaneous"]:
        ax.fill([area["west"],area["east"],area["east"],area["west"]],
                [45,45,75,75],transform=ccrs.PlateCarree(),
                color="#fde68a",alpha=.35,zorder=4)
    for area in blocking["persistent"]:
        ax.fill([area["west"],area["east"],area["east"],area["west"]],
                [45,45,75,75],transform=ccrs.PlateCarree(),
                color="#f97316",alpha=.30,zorder=5)
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            artist=ax.coastlines(resolution="110m",color="#334155",linewidth=.75)
            fig.canvas.draw()
    except Exception as e:
        try: artist.remove()
        except Exception: pass
        print("Natural Earth coastlines unavailable:",str(e),flush=True)
    gl=ax.gridlines(draw_labels={"bottom":"x","left":"y"},linewidth=.55,
                    color="#64748b",alpha=.45,linestyle="--")
    gl.top_labels=False;gl.right_labels=False
    gl.xlocator=mticker.FixedLocator(np.arange(-90,91,30))
    gl.ylocator=mticker.FixedLocator(np.arange(30,91,15))
    gl.xlabel_style={"size":9};gl.ylabel_style={"size":9}
    fig.text(.08,.95,"BLOCKING · NORDATLANTIK / EUROPA",color="#1d4f7d",
             weight="bold",fontsize=12)
    fig.text(.08,.898,"500-hPa-Geopotenzialhöhe",color="#172b43",
             weight="bold",fontsize=24)
    fig.text(.08,.86,f"ERA5-Tagesmittel · {day:%d.%m.%Y} · 00–24 UTC",
             color="#53687d",fontsize=11)
    cb=fig.colorbar(cs,ax=ax,orientation="horizontal",pad=.085,
                    fraction=.075,shrink=.9,aspect=38)
    cb.set_label("Geopotenzialhöhe (gpm)",fontsize=10)
    fig.text(.08,.045,"Gelb: momentane Gradienten-Umkehr (TM) · Orange: auch an fünf aufeinanderfolgenden Tagen",
             color="#485c71",fontsize=9)
    fig.text(.08,.023,"Copernicus C3S / ECMWF · ERA5 · DOI: "+DOI+" · Reanalyse, keine Vorhersage",
             color="#485c71",fontsize=9)
    output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(output,dpi=140,facecolor="white")
    plt.close(fig)


def build(output=DEST, today=None,client=None):
    import update_era5_stratosphere as era
    today=today or datetime.now(timezone.utc).date()
    output=Path(output)
    prior={}
    metadata=output/"current.json"
    png=output/"blocking_z500_current.png"
    if metadata.is_file() and png.is_file():
        try:
            prior=json.loads(metadata.read_text(encoding="utf-8"))
            if date.fromisoformat(prior["analysis_date"]) >= today-timedelta(days=8):
                print("Blocking ERA5 archive current:",prior["analysis_date"])
                return prior
        except (ValueError,KeyError):
            prior={}
    if client is None:
        import cdsapi
        client=cdsapi.Client()
    # Try latest reliable ERA5 days, fall back to older verified dates.
    errors=[]
    for ago in (8,9,10):
        target=today-timedelta(days=ago)
        dates=[target-timedelta(days=i) for i in range(4,-1,-1)]
        fields={}
        try:
            # CDS API daily-statistics request is scoped to one month; split if needed.
            groups={}
            for d in dates:groups.setdefault((d.year,d.month),[]).append(d)
            for group in groups.values():
                with tempfile.TemporaryDirectory(prefix="blocking-era5-") as temp:
                    raw=Path(temp)/"daily.zip"
                    client.retrieve(DATASET,request(group),str(raw))
                    ds=era.open_cds_file(raw)
                    lats,lons,grid=parse_grids(ds,group)
                    for day,value in zip(group,grid):
                        fields[day]=value
            if set(fields)!=set(dates):
                raise ValueError("Missing some daily grids")
            arr=np.stack([fields[d] for d in dates])
            diag=diagnostics(lats,lons,arr,dates)
            with tempfile.TemporaryDirectory(prefix="blocking-render-") as temp:
                tmp=Path(temp)/"map.png"
                render_map(lats,lons,arr[-1],target,diag,tmp)
                if not tmp.exists() or tmp.stat().st_size<25000 or tmp.read_bytes()[:8]!=bytes.fromhex("89504e470d0a1a0a"):
                    raise ValueError("PNG validation failed")
                payload={
                    "schema_version":1,"ready":True,"forecast":False,
                    "analysis_date":target.isoformat(),"generated_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "dates_used":[d.isoformat() for d in dates],"pressure_hpa":500,
                    "parameter":"geopotential_height","unit":"gpm","source":"Copernicus C3S/ECMWF ERA5",
                    "doi":DOI,"image":"blocking_z500_current.png",
                    "daily_statistic":"daily_mean","frequency":"6_hourly","resolution_degrees":1,
                    "region":"Nordatlantik und Europa, 90°W–65°E",
                    "blocking_method":"Tibaldi-Molteni-type 1D 500-hPa gradients, phi=60N plus offsets -5/0/+5; GHGS>0, GHGN<-10 gpm/degree; >=10 degrees width; persistent >=5 consecutive days",
                    "instantaneous_sectors":diag["instantaneous"],
                    "persistent_sectors":diag["persistent"],
                    "history_complete":diag["history_complete"],"days_analysed":len(dates),
                    "min_gpm":round(float(arr[-1].min()),1),"max_gpm":round(float(arr[-1].max()),1),
                    "note":"Diagnostic sectors in longitude only; not a 2D blocking footprint. No positive signal does not exclude all types of blocking."
                }
                output.mkdir(parents=True,exist_ok=True)
                os.replace(tmp,png)
                temp_json=metadata.with_suffix(".tmp")
                temp_json.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                os.replace(temp_json,metadata)
                print(f"ERA5 Blocking published {target}: {len(diag['instantaneous'])} instantaneous and {len(diag['persistent'])} persistent sectors")
                return payload
        except Exception as e:
            print(f"Blocking ERA5 {target} failed: {e}",flush=True)
            errors.append(str(e))
    if prior and png.is_file():
        print("Preserving previously verified map; new ERA5 retrieval failed")
        return prior
    raise RuntimeError("No verified ERA5 500hPa map yet: "+"; ".join(errors[-2:]))


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,default=DEST)
    opts=p.parse_args()
    build(opts.output)


if __name__=="__main__":
    main()
