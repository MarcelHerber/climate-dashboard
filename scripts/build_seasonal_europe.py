#!/usr/bin/env python3
"""Real ECMWF SEAS5 monthly anomaly charts, fixed European projection.

Open-Meteo seasonal API serves ECMWF SEAS5 ensemble means + monthly anomalies.
Do NOT substitute ERA5 observational anomalies or label the reference as 1991–2020.
No synthetic data, no smoothing beyond standard contour interpolation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import time
import urllib.error
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
from pyproj import Transformer
from matplotlib.collections import LineCollection

LOG = logging.getLogger("seasonal-europe")
API = "https://seasonal-api.open-meteo.com/v1/seasonal"
MODEL = "ecmwf_seas5_ensemble_mean"
VARIANTS = {
    "temperature": {
        "api": "temperature_2m_anomaly", "unit": "K",
        "title": "2-m-TEMPERATUR", "levels": [-7,-5,-4,-3,-2,-1,-.5,0,.5,1,2,3,4,5,7],
        "palette": "RdBu_r", "description": "Temperaturabweichung", "digits": 1
    },
    "precipitation": {
        "api": "precipitation_anomaly", "unit": "mm",
        "title": "NIEDERSCHLAG", "levels": [-130,-100,-75,-50,-30,-15,-5,0,5,15,30,50,75,100,130],
        "palette": "RdBu", "description": "Niederschlagsabweichung", "digits": 0
    },
    "snowfall": {
        "api": "snowfall_anomaly", "unit": "cm",
        "title": "SCHNEEFALL", "levels": [-100,-75,-50,-30,-15,-7,-2,0,2,7,15,30,50,75,100],
        "palette": "RdBu", "description": "Schneefallabweichung", "digits": 0
    },
}
# The requested map is a fixed Lambert projection. Its top corners are much
# farther west/east than the corner longitudes of EXTENT. Sample at 1-degree
# intervals, but request only those points needed for the VISIBLE projected
# rectangle plus a safe margin. No synthetic forecasts or extrapolation.
LONS = np.arange(-80.0, 100.0001, 1.0)
LATS = np.arange(22.0, 85.0001, 1.0)
EXTENT = (-25.0, 45.0, 34.0, 76.0)
COVERAGE_PAD_M = 175000
MONTHS_DE = ["Januar","Februar","März","April","Mai","Juni","Juli","August",
             "September","Oktober","November","Dezember"]
FIELDS = [p["api"] for p in VARIANTS.values()]
USER_AGENT = "ClimateDashboardDeutschland/1.0 - monthly ECMWF SEAS5 maps"


def fetch_batch(batch, attempts=5):
    params = {
        "latitude": ",".join(str(lat) for lat, lon in batch),
        "longitude": ",".join(str(lon) for lat, lon in batch),
        "monthly": ",".join(FIELDS),
        "models": MODEL,
        "forecast_days": 217,
        "timezone": "GMT",
        "cell_selection": "nearest",
    }
    request = Request(API + "?" + urlencode(params),
                      headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=80) as response:
                parsed = json.load(response)
            if isinstance(parsed, dict) and parsed.get("error"):
                raise ValueError(str(parsed.get("reason", "API error")))
            rows = parsed if isinstance(parsed, list) else [parsed]
            if len(rows) != len(batch):
                raise RuntimeError("API lieferte %d statt %d Positionen" % (len(rows),len(batch)))
            return rows
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            if attempt + 1 == attempts:
                raise RuntimeError("Saisonale API nach Wiederholungen nicht erreichbar") from exc
            wait = min(45, 3 * 2 ** attempt)
            LOG.warning("API-Versuch %d/%d fehlgeschlagen (%s); warte %ds", attempt+1, attempts,exc,wait)
            time.sleep(wait)
    raise AssertionError("unreachable")


def download():
    region = sampling_mask()
    coords=[(float(lat),float(lon))
            for row,lat in enumerate(LATS)
            for col,lon in enumerate(LONS) if region[row,col]]
    LOG.info("Sichtbarer Kartenausschnitt mit 1°-Raster: %d statt %d Punkten",
             len(coords), len(LATS)*len(LONS))
    data={field: {} for field in FIELDS}
    units=None
    valid_months=None
    batch_size=35
    for offset in range(0,len(coords),batch_size):
        batch=coords[offset:offset+batch_size]
        rows=fetch_batch(batch)
        for (lat,lon),item in zip(batch,rows):
            monthly=item.get("monthly") or {}
            times=[str(t)[:7] for t in monthly.get("time",[])]
            if valid_months is None:
                valid_months=times
                units=item.get("monthly_units") or {}
                if len(valid_months)<4 or len(set(valid_months))!=len(valid_months):
                    raise RuntimeError("Monatszeiten fehlen oder sind nicht eindeutig")
            elif times!=valid_months:
                raise RuntimeError("Unterschiedliche Monatsachsen in saisonaler API")
            for field in FIELDS:
                vals=monthly.get(field)
                if not isinstance(vals,list) or len(vals)!=len(times):
                    raise RuntimeError("Keine vollständigen Monatsdaten für "+field)
                for when,value in zip(times,vals):
                    if value is None:continue
                    number=float(value)
                    if not math.isfinite(number) or abs(number)>100000:continue
                    data[field][(when,lat,lon)]=number
        LOG.info("Echte SEAS5-Monatswerte: %d von %d Rasterpunkten", min(offset+len(batch),len(coords)),len(coords))
        time.sleep(.20)
    if valid_months is None:
        raise RuntimeError("Keine echten saisonalen Felder verfügbar")
    for key,variant in VARIANTS.items():
        unit=units.get(variant["api"])
        if unit!=variant["unit"]:
            raise RuntimeError("%s: unbekannte Einheit %s statt %s" % (key,unit,variant["unit"]))
    return data,valid_months,units


# Lambert conformal conic: meteorologically familiar European regional projection.
# Unlike the old longitude/latitude image, this preserves geographic scale
# much better, especially around Iceland and northern Scandinavia.
PROJECT = Transformer.from_crs(
    "EPSG:4326",
    "+proj=lcc +lat_1=40 +lat_2=70 +lat_0=54 +lon_0=10 +datum=WGS84 +units=m +no_defs",
    always_xy=True,
)


def projected_extent(extent):
    west,east,south,north=extent
    edge=np.linspace(0,1,250)
    lon=np.concatenate([west+(east-west)*edge,west+(east-west)*edge,
                        np.full(250,west),np.full(250,east)])
    lat=np.concatenate([np.full(250,south),np.full(250,north),
                        south+(north-south)*edge,south+(north-south)*edge])
    x,y=PROJECT.transform(lon,lat)
    return (float(x.min()),float(x.max()),float(y.min()),float(y.max()))


def sampling_mask():
    """Grid points covering the full projected viewport including buffer.

    This is the crucial difference from a simple [-40,65] longitude clip:
    upper projected corners extend near 70W/90E. Use only real retrieved
    values and guarantee bilinear-neighbour coverage to the visible frame.
    """
    longitude,latitude=np.meshgrid(LONS,LATS)
    xx,yy=PROJECT.transform(longitude,latitude)
    xmin,xmax,ymin,ymax=projected_extent(EXTENT)
    mx=(xmax-xmin)*.012
    my=(ymax-ymin)*.012
    mask=((xx>=xmin-mx-COVERAGE_PAD_M)&(xx<=xmax+mx+COVERAGE_PAD_M)&
          (yy>=ymin-my-COVERAGE_PAD_M)&(yy<=ymax+my+COVERAGE_PAD_M))
    back=Transformer.from_crs(PROJECT.target_crs,"EPSG:4326",always_xy=True)
    # Check every part of the viewport, not only its four corners.
    for x in np.linspace(xmin-mx,xmax+mx,81):
        for y in np.linspace(ymin-my,ymax+my,71):
            lon,lat=back.transform(x,y)
            c=int(np.floor((lon-LONS[0])/(LONS[1]-LONS[0])))
            r=int(np.floor((lat-LATS[0])/(LATS[1]-LATS[0])))
            if not (0<=r<len(LATS)-1 and 0<=c<len(LONS)-1 and
                    mask[r:r+2,c:c+2].all()):
                raise RuntimeError("Unvollständiger Modell-Datenrand bei %.2f°/%.2f°" % (lon,lat))
    return mask


def draw_graticule(ax):
    for lon in range(-20,46,10):
        latitudes=np.linspace(32,79,180)
        xx,yy=PROJECT.transform(np.full_like(latitudes,lon),latitudes)
        ax.plot(xx,yy,color="#294660",alpha=.23,lw=.7,zorder=4)
    for lat in range(35,81,10):
        longitudes=np.linspace(-35,55,220)
        xx,yy=PROJECT.transform(longitudes,np.full_like(longitudes,lat))
        ax.plot(xx,yy,color="#294660",alpha=.23,lw=.7,zorder=4)


def draw_geography(ax,geopoly):
    # The 50m polygons are clipped in lon/lat before projection. This prevents
    # trans-dateline lines and artificial long borders through the map.
    segments=[]
    for country in geopoly["countries"]:
        for polygon in country["p"]:
            for ring in polygon:
                if len(ring)<2:
                    continue
                longitude=np.fromiter((p[0] for p in ring),dtype=float)
                latitude=np.fromiter((p[1] for p in ring),dtype=float)
                xx,yy=PROJECT.transform(longitude,latitude)
                if np.isfinite(xx).all() and np.isfinite(yy).all():
                    segments.append(np.column_stack([xx,yy]))
    if not segments:
        raise RuntimeError("Europa: Keine Länder- oder Küstenumrisse transformiert")
    ax.add_collection(LineCollection(segments,colors="#233e58",linewidths=.63,
                                     alpha=.93,zorder=6,antialiaseds=True))


def render_map(outpath,when,kind,grid,geo,source_month,retrieved_utc):
    variant=VARIANTS[kind]
    fig=plt.figure(figsize=(14,9),dpi=145,facecolor="#f7fafc")
    # Space for the fixed map, a separate legend caption and two footer lines.
    # The old layout let the legend label and source line overlap.
    ax=fig.add_axes([.045,.235,.91,.625])
    # Fixed Lambert map viewport, identical on every monthly chart.
    xmin,xmax,ymin,ymax=projected_extent(EXTENT)
    margin_x=(xmax-xmin)*.012
    margin_y=(ymax-ymin)*.012
    ax.set_xlim(xmin-margin_x,xmax+margin_x)
    ax.set_ylim(ymin-margin_y,ymax+margin_y)
    ax.set_aspect("equal",adjustable="box")
    ax.set_facecolor("#e4f0f5")
    longitude,latitude=np.meshgrid(LONS,LATS)
    xx,yy=PROJECT.transform(longitude,latitude)
    levels=variant["levels"]
    cmap=plt.get_cmap(variant["palette"],len(levels)-1)
    norm=mcolors.BoundaryNorm(levels,cmap.N)
    # Never turn absent model data into a forecast.
    masked=np.ma.masked_invalid(grid)
    needed=sampling_mask()
    if np.count_nonzero(np.isfinite(grid)&needed)<int(needed.sum()*.99):
        raise RuntimeError("%s %s: notwendiger Kartenbereich nicht vollständig" % (kind,when))
    raster=ax.contourf(xx,yy,masked,levels=levels,norm=norm,
                       cmap=cmap,extend="both",antialiased=True,zorder=2)
    draw_graticule(ax)
    draw_geography(ax,geo)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.tick_params(axis="both",length=0)
    for spine in ax.spines.values():
        spine.set_linewidth(.8);spine.set_color("#8899aa")
    year,month=map(int,when.split("-"))
    period=f"{MONTHS_DE[month-1]} {year}"
    fig.text(.045,.952,"CLIMATE DASHBOARD  /  SAISONPROGNOSEN EUROPA",
             fontsize=11,weight="bold",color="#50677f")
    fig.text(.045,.911,variant["title"]+" · MONATSANOMALIE",fontsize=20,
             weight="bold",color="#122c46")
    fig.text(.955,.91,f"ECMWF SEAS5  |  {period}",fontsize=12,
             ha="right",weight="bold",color="#304d68")
    cax=fig.add_axes([.10,.135,.8,.027])
    ticks=[levels[i] for i in range(0,len(levels),2)]
    cb=fig.colorbar(raster,cax=cax,orientation="horizontal",ticks=ticks,extend="both")
    cb.ax.tick_params(labelsize=10,length=2)
    cb.outline.set_edgecolor("#8392a1")
    fig.text(.50,.180,
             f"Abweichung ({variant['unit']})  ·  Blau: {'kälter' if kind=='temperature' else 'mehr'}"
             f"  ·  Rot: {'wärmer' if kind=='temperature' else 'weniger'}",
             fontsize=10,color="#344e65",ha="center")
    fig.text(.045,.068,
             f"Quelle: ECMWF SEAS5 Ensemble-Mittel über Open-Meteo  |  Modell-Ausgabe: {source_month}",
             fontsize=9,color="#53687a")
    fig.text(.045,.038,"Monatsabweichungen zur SEAS5-Modellklimatologie · keine amtliche Wetterwarnung",
             fontsize=9,color="#53687a")
    fig.text(.955,.038,f"Abgerufen: {retrieved_utc[:16].replace('T',' ')} UTC",
             fontsize=9,ha="right",color="#53687a")
    outpath.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(outpath,dpi=145,facecolor=fig.get_facecolor(),metadata={"Software":"Climate Dashboard Deutschland",
                "Description":"ECMWF SEAS5 ensemble monthly model anomaly via Open-Meteo"})
    plt.close(fig)
    LOG.info("Karte %s (%0.1f KiB)",outpath,outpath.stat().st_size/1024)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default="seasonal-europe-public",type=Path)
    parser.add_argument("--geo",default="wettergefahren_basemap.json",type=Path)
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    geometry=json.loads(args.geo.read_text(encoding="utf-8"))
    if not geometry.get("countries"):raise RuntimeError("Kartengeometrie fehlt")
    coverage=sampling_mask()
    fields,dates,units=download()
    source_month=dates[0]
    # SEAS5 is issued once per month. Do not imply exact 00 UTC init time.
    retrieved=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
    report=[]
    for date in dates:
        bykind={}
        for key,config in VARIANTS.items():
            arr=np.full((len(LATS),len(LONS)),np.nan,dtype=float)
            lookup=fields[config["api"]]
            for y,lat in enumerate(LATS):
                for x,lon in enumerate(LONS):
                    val=lookup.get((date,float(lat),float(lon)))
                    if val is not None:arr[y,x]=val
            nfinite=int(np.isfinite(arr).sum())
            nrequired=int(coverage.sum())
            if np.count_nonzero(np.isfinite(arr)&coverage)<int(nrequired*.99):
                LOG.warning("Überspringe %s/%s (nur %d/%d notwendige Punkte)",
                            date,key,int(np.count_nonzero(np.isfinite(arr)&coverage)),nrequired)
                continue
            relative=Path("maps")/source_month/date/(key+".png")
            render_map(args.out/relative,date,key,arr,geometry,source_month,retrieved)
            bykind[key]={"image":str(relative),"unit":config["unit"],
                         "min":round(float(np.nanmin(arr)),2),
                         "max":round(float(np.nanmax(arr)),2),
                         "coverage":round(nfinite/arr.size,3)}
        if bykind:report.append({"month":date,"fields":bykind})
    if len(report)<4 or sum("temperature" in p["fields"] and "precipitation" in p["fields"] for p in report)<4:
        raise RuntimeError("Zu wenige echte Monatskarten veröffentlicht; behalte vorigen Datenbestand")
    manifest={
        "schema":1,"product":"Saisonal Europa · ECMWF SEAS5",
        "provider":"ECMWF SEAS5 via Open-Meteo",
        "base_model_month":source_month,"retrieved_utc":retrieved,
        "model":"ecmwf_seas5_ensemble_mean","source":API,
        "reference_note":"SEAS5 monthly model-climate anomalies supplied by Open-Meteo; NOT ERA5 1991–2020 anomalies.",
        "fixed_extent":list(EXTENT),"sample_resolution_deg":1.0,
        "sampled_locations":int(coverage.sum()),
        "sample_domain":[float(LONS.min()),float(LONS.max()),float(LATS.min()),float(LATS.max())],
        "complete_projected_viewport":True,
        "projection":"Lambert Conformal Conic (40N/70N, centre 10E/54N)",
        "coastlines":"Natural Earth 1:50m, clipped for Europe",
        "params":{k:{"title":v["title"],"unit":v["unit"]} for k,v in VARIANTS.items()},
        "periods":report
    }
    target=args.out/"index.json"
    target.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    LOG.info("Echte SEAS5-Indexdaten: %s, %d Monate, %d Karten",
             source_month,len(report),sum(len(row["fields"])for row in report))


if __name__=="__main__":
    main()
