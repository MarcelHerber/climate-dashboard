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
# Regular, native-2-degree sampling to keep the published image honest about resolution.
LONS = np.arange(-26.0, 46.0001, 2.0)
LATS = np.arange(34.0, 76.0001, 2.0)
EXTENT = (-25.0, 45.0, 34.0, 76.0)
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
    coords=[(float(lat),float(lon)) for lat in LATS for lon in LONS]
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


def draw_geography(ax, geopoly):
    # Polygon fill gives reliable Natural Earth land/ocean distinction.
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch
    for country in geopoly["countries"]:
        for polygon in country["p"]:
            vertices=[]
            codes=[]
            for ring in polygon:
                if len(ring)<4:continue
                vertices.extend([tuple(point) for point in ring])
                codes.extend([MPath.MOVETO]+[MPath.LINETO]*(len(ring)-2)+[MPath.CLOSEPOLY])
            if vertices:
                path=MPath(vertices,codes)
                ax.add_patch(PathPatch(path,facecolor="#ecefed",edgecolor="#48566a",
                                       linewidth=.45,alpha=1,zorder=5,fill=False))


def render_map(outpath,when,kind,grid,geo,source_month,retrieved_utc):
    variant=VARIANTS[kind]
    fig=plt.figure(figsize=(14,9),dpi=145,facecolor="#f7fafc")
    ax=fig.add_axes([.045,.145,.91,.715])
    ax.set_xlim(EXTENT[:2])
    ax.set_ylim(EXTENT[2:])
    ax.set_aspect("auto")
    ax.set_facecolor("#e4f0f5")
    longitude,latitude=np.meshgrid(LONS,LATS)
    levels=variant["levels"]
    cmap=plt.get_cmap(variant["palette"],len(levels)-1)
    norm=mcolors.BoundaryNorm(levels,cmap.N)
    # Never turn absent model data into a forecast.
    masked=np.ma.masked_invalid(grid)
    if masked.count()<int(grid.size*.9):
        raise RuntimeError("%s %s: weniger als 90%% Datenabdeckung" % (kind,when))
    raster=ax.contourf(longitude,latitude,masked,levels=levels,norm=norm,
                       cmap=cmap,extend="both",antialiased=True,zorder=2)
    draw_geography(ax,geo)
    ax.set_xticks(np.arange(-20,46,10));ax.set_yticks(np.arange(35,77,5))
    ax.tick_params(axis="both",labelsize=9,length=0,pad=5,colors="#52647a")
    ax.set_xticklabels([f"{abs(int(x))}°{'W' if x<0 else 'E'}" for x in ax.get_xticks()])
    ax.set_yticklabels([f"{int(x)}°N" for x in ax.get_yticks()])
    ax.grid(color="#536579",alpha=.20,lw=.65,zorder=4)
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
    cax=fig.add_axes([.10,.08,.8,.028])
    ticks=[levels[i] for i in range(0,len(levels),2)]
    cb=fig.colorbar(raster,cax=cax,orientation="horizontal",ticks=ticks,extend="both")
    cb.ax.tick_params(labelsize=10,length=2)
    cb.outline.set_edgecolor("#8392a1")
    cb.set_label(f"Abweichung ({variant['unit']})   |   Blau: {'kälter' if kind=='temperature' else 'mehr'}  ·  Rot: {'wärmer' if kind=='temperature' else 'weniger'}",
                 fontsize=10,labelpad=8,color="#344e65")
    fig.text(.045,.040,
             f"Quelle: ECMWF SEAS5 Ensemble-Mittel über Open-Meteo  |  Modell-Ausgabe: {source_month}"
             "  |  nicht amtliche Warnung",
             fontsize=9,color="#53687a")
    fig.text(.955,.040,f"Abgerufen: {retrieved_utc[:16].replace('T',' ')} UTC",
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
            if nfinite<int(arr.size*.9):
                LOG.warning("Überspringe %s/%s (nur %d/%d Punkte)",date,key,nfinite,arr.size)
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
        "fixed_extent":list(EXTENT),"sample_resolution_deg":2.0,
        "params":{k:{"title":v["title"],"unit":v["unit"]} for k,v in VARIANTS.items()},
        "periods":report
    }
    target=args.out/"index.json"
    target.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    LOG.info("Echte SEAS5-Indexdaten: %s, %d Monate, %d Karten",
             source_month,len(report),sum(len(row["fields"])for row in report))


if __name__=="__main__":
    main()
