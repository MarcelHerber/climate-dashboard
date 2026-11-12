#!/usr/bin/env python3
"""Real ECMWF IFS-ENS mean geopotential-height forecasts for NAO/AO map context.

NOT CPC index forecasts or geopotential *anomalies*. These are absolute
500/1000-hPa ensemble mean heights in geopotential metres (gpm), sourced from
ECMWF Open Data (CC BY 4.0) and independently labeled for transparency.
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path as MplPath
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "nao_ao_forecast" / "ecmwf_maps"
HOURS = (72, 144, 240)
LEVELS = (500, 1000)
G0 = 9.80665
BASEMAP = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"


def fetch_maps(when: date, output: Path) -> tuple[date, dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]]]:
    from ecmwf.opendata import Client
    import eccodes
    client = Client(source="ecmwf", model="ifs", resol="0p25", maximum_retries=2, retry_after=4)
    with tempfile.TemporaryDirectory() as tmp:
        grib = Path(tmp) / "ens_gh.grib2"
        client.retrieve(
            date=when.strftime("%Y%m%d"), time=0, stream="enfo",
            type="em", param="gh", levelist=list(LEVELS),
            step=list(HOURS), target=str(grib)
        )
        if not grib.is_file() or grib.stat().st_size < 200000:
            raise RuntimeError("ECMWF GRIB is missing or suspiciously small")
        fields: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        with grib.open("rb") as handle:
            while True:
                gid=eccodes.codes_grib_new_from_file(handle)
                if gid is None:
                    break
                try:
                    level=int(eccodes.codes_get(gid,"level"))
                    hour=int(eccodes.codes_get(gid,"step"))
                    param=str(eccodes.codes_get(gid,"shortName"))
                    grid=str(eccodes.codes_get(gid,"gridType"))
                    data_date=str(eccodes.codes_get(gid,"dataDate"))
                    data_time=int(eccodes.codes_get(gid,"dataTime"))
                    ni=int(eccodes.codes_get(gid,"Ni"))
                    nj=int(eccodes.codes_get(gid,"Nj"))
                    first_lon=float(eccodes.codes_get(gid,"longitudeOfFirstGridPointInDegrees"))
                    first_lat=float(eccodes.codes_get(gid,"latitudeOfFirstGridPointInDegrees"))
                    dlon=float(eccodes.codes_get(gid,"iDirectionIncrementInDegrees"))
                    dlat=float(eccodes.codes_get(gid,"jDirectionIncrementInDegrees"))
                    if (param != "gh" or grid != "regular_ll" or level not in LEVELS
                        or hour not in HOURS or ni < 1200 or nj < 600
                        or int(data_date) != int(when.strftime("%Y%m%d")) or data_time!=0):
                        raise RuntimeError(f"Unexpected ECMWF GRIB field: {param} {grid} {level}hPa +{hour}h {data_date} {data_time}")
                    z=np.asarray(eccodes.codes_get_values(gid), dtype=np.float32).reshape((nj,ni))
                    lons=((first_lon+np.arange(ni)*dlon+180)%360)-180
                    lats=first_lat-np.arange(nj)*dlat
                    idx=np.argsort(lons)
                    # Plot at 0.5 degree (0.25 degree source) for cost efficiency.
                    lons=lons[idx][::2]
                    lats=lats[::2]
                    z=z[::2,idx][:,::2]
                    finite=np.isfinite(z)
                    if np.count_nonzero(finite)<.95*z.size or not -2000<float(z.min())<10000:
                        raise RuntimeError("Bad ECMWF height field")
                    fields[(level,hour)]=(lons,lats,z)
                finally:
                    eccodes.codes_release(gid)
        if set(fields)!={(a,b) for a in LEVELS for b in HOURS}:
            raise RuntimeError(f"ECMWF missing requested combinations: {set(fields)}")
    return when,fields


def fetch_coastlines():
    req=urllib.request.Request(BASEMAP,headers={"User-Agent":"climate-dashboard/NAO-AO/1.0"})
    with urllib.request.urlopen(req,timeout=45) as response:
        obj=json.load(response)
    if obj.get("type")!="FeatureCollection" or len(obj.get("features",[]))<100:
        raise RuntimeError("Natural Earth countries GeoJSON invalid")
    edges=[]
    for feature in obj["features"]:
        geom=feature.get("geometry") or {}
        t=geom.get("type")
        coords=geom.get("coordinates") or []
        if t=="Polygon":
            shapes=[coords]
        elif t=="MultiPolygon":
            shapes=coords
        else:continue
        for poly in shapes:
            for ring in poly[:1]:
                if len(ring)<2:continue
                # Split across antimeridian to avoid a polygon drawing across the map.
                segment=[ring[0]]
                for point in ring[1:]:
                    if abs(point[0]-segment[-1][0])>180:
                        if len(segment)>1:edges.append(segment)
                        segment=[point]
                    else:segment.append(point)
                if len(segment)>1:edges.append(segment)
    if len(edges)<100:raise RuntimeError("No usable coastlines")
    return edges


def draw_map(lons,lats,z,level:int,hour:int,run:date,edges:list,filename:Path):
    import cartopy.crs as ccrs
    region="Atlantik & Europa" if level==500 else "Nordhemisphäre · Arktis"
    fig=plt.figure(figsize=(15,9),dpi=125,facecolor="#f6f8fc")
    if level==500:
        ax=fig.add_axes([.055,.145,.86,.70],projection=ccrs.PlateCarree())
        ax.set_extent([-78,65,28,83],crs=ccrs.PlateCarree())
        levs=np.arange(4800,6001,50)
        step=100
    else:
        ax=fig.add_axes([.12,.14,.75,.72],projection=ccrs.NorthPolarStereo())
        ax.set_extent([-180,180,35,90],crs=ccrs.PlateCarree())
        # Circle framing the polar stereographic viewport.
        phi=np.linspace(0,2*np.pi,180)
        circle=MplPath(np.column_stack([np.sin(phi),np.cos(phi)])*.5+.5)
        ax.set_boundary(circle,transform=ax.transAxes)
        levs=np.arange(-500,501,40)
        step=80
    ax.set_facecolor("#eaf1f7")
    lon,lat=np.meshgrid(lons,lats)
    # Limit domain to the Northern Hemisphere; all values remain measured fields.
    subset=lats>=25
    field=np.ma.masked_invalid(z[subset])
    cs=ax.contourf(lon[subset],lat[subset],field,
        levels=levs,cmap="RdYlBu_r",extend="both",transform=ccrs.PlateCarree())
    ax.contour(lon[subset],lat[subset],field,
        levels=np.arange(levs[0],levs[-1]+1,step),colors="#263b54",
        linewidths=.46,alpha=.6,transform=ccrs.PlateCarree())
    for ring in edges:
        x,y=zip(*ring)
        ax.plot(x,y,transform=ccrs.PlateCarree(),color="#243d54",
            lw=.5,alpha=.78,zorder=5)
    gl=ax.gridlines(draw_labels=False,linewidth=.5,alpha=.4,color="#607187",linestyle=":")
    cb=fig.colorbar(cs,ax=ax,orientation="horizontal",fraction=.045,pad=.045,shrink=.76)
    cb.set_label("Geopotenzialhöhe (gpm) · feste Farbskala je Druckniveau",fontsize=10,color="#344963")
    cb.ax.tick_params(labelsize=9)
    title=f"IFS-ENS · {level} hPa · Ensemble-Mittel"
    fig.text(.06,.965,title,fontweight="bold",fontsize=20,color="#152943")
    fig.text(.06,.925,region+" · Vorhersage +"+str(hour)+" h",fontsize=12,color="#4a637d")
    valid=datetime.combine(run,datetime.min.time(),tzinfo=timezone.utc)+timedelta(hours=hour)
    fig.text(.06,.891,"Modelllauf "+run.strftime("%d.%m.%Y")+" 00 UTC   |   gültig "+valid.strftime("%d.%m.%Y %H UTC"),
        fontsize=10,color="#4a637d")
    fig.text(.06,.037,"ECMWF Open Data · CC BY 4.0 · IFS ENS Mittel (em/gh, 0,25° Ausgangsdaten) · absolute Höhen, KEINE NAO-/AO-Indexprojektion",
        color="#596f85",fontsize=9)
    filename.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(filename,dpi=125,facecolor=fig.get_facecolor(),bbox_inches="tight",pad_inches=.15)
    plt.close(fig)
    if filename.stat().st_size<50000 or filename.read_bytes()[:8]!=bytes.fromhex("89504e470d0a1a0a"):
        raise RuntimeError(f"Map rendering failed: {filename}")


def build(output:Path=OUT,run:date|None=None):
    today=datetime.now(timezone.utc).date()
    # Prefer the previous 00 UTC cycle; its complete archive is available.
    run=run or today-timedelta(days=1)
    if not(today-timedelta(days=3)<=run<=today):
        raise ValueError("Selected ECMWF run is outside the rolling archive")
    observed,fields=fetch_maps(run,output)
    coastlines=fetch_coastlines()
    maps=[]
    for level,hour in sorted(fields):
        filename=f"ifs_ens_gh_{level}hpa_f{hour:03d}.png"
        draw_map(*fields[(level,hour)],level,hour,observed,coastlines,output/filename)
        valid=(datetime.combine(observed,datetime.min.time(),tzinfo=timezone.utc)+timedelta(hours=hour)).isoformat(timespec="minutes")
        maps.append({"level_hpa":level,"step_hours":hour,"valid_time_utc":valid,"file":filename,
           "size_bytes":(output/filename).stat().st_size})
    doc={"schema":1,"ready":True,
         "source":"ECMWF Open Data / IFS ENS ensemble mean (em/gh)",
         "source_url":"https://www.ecmwf.int/en/forecasts/datasets/open-data",
         "geography":"global source; NAO display: -78–65°E 28–83°N; AO display: hemisphere north of 35°N",
         "generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "model_run_utc":observed.isoformat()+"T00:00:00Z",
         "is_index_forecast":False,"is_anomaly":False,
         "parameter":"absolute_geopotential_height",
         "unit":"gpm","native_grid_degrees":0.25,"plot_grid_degrees":0.5,
         "fixed_scales_gpm":{"500":[4800,6000],"1000":[-500,500]},
         "licence":"CC BY 4.0","maps":maps}
    (output/"index.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Verified ECMWF maps:",[(x["level_hpa"],x["step_hours"],x["size_bytes"]) for x in maps])
    return doc


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=OUT)
    args=parser.parse_args()
    build(args.output)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
