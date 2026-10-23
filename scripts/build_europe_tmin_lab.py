#!/usr/bin/env python3
"""PRIVATE Wolkenlabor: five real Europe Tmin maps from DWD MOSMIX-L TN and ICON-EU.

Both layers refer to the SAME overnight 18-06 UTC period:
 MOS: native 12-hour TN at 06 UTC (the following morning).
 ICON: minimum of genuine consecutive six-hour TMIN_2M fields ending
       at 00 and 06 UTC. GRIB temporal metadata are checked.
 No made-up cities, fabricated weather, or extrapolated temperature fields.
 The 0.125-degree map is only an OUTPUT raster, not the native ICON-EU mesh.
"""
from __future__ import annotations
import argparse
import bz2
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.client import RemoteDisconnected, IncompleteRead, HTTPException
import json
import logging
from pathlib import Path
import socket
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET
import zipfile

import eccodes
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

LOG=logging.getLogger("europe-tmax-lab")
MOS_URL="https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/all_stations/kml/MOSMIX_L_LATEST.kmz"
ICON_ROOT="https://opendata.dwd.de/weather/nwp/icon-eu/grib"
ICON_PREFIX="icon-eu_europe_regular-lat-lon_single-level"
LON_MIN,LON_MAX,LAT_MIN,LAT_MAX=-29.0,62.0,27.0,73.0
STEP=.125
WIDTH=round((LON_MAX-LON_MIN)/STEP)+1
HEIGHT=round((LAT_MAX-LAT_MIN)/STEP)+1
MAX_DISTANCE_KM=100
# Editorially MATCH the supplied monochrome Europe-temperature reference.
# "Azoren"/"Kanaren" are island labels for real MOSMIX stations near the
# sampled island location; never modelled group averages.
CITIES=(
 ("Reykjavík",-21.94,64.14),("Rovaniemi",25.73,66.50),
 ("Syktywkar",50.82,61.67),("Helsinki",24.94,60.17),
 ("Oslo",10.75,59.91),("Stockholm",18.06,59.33),
 ("Moskau",37.62,55.75),("Minsk",27.57,53.90),
 ("Wolgograd",44.51,48.71),("Dublin",-6.26,53.35),
 ("London",-.13,51.51),("Warschau",21.01,52.23),
 ("Kiew",30.52,50.45),("Frankfurt",8.68,50.11),
 ("Wien",16.37,48.21),("Paris",2.35,48.86),
 ("Bordeaux",-.58,44.84),("Nizza",7.26,43.70),
 ("Belgrad",20.46,44.82),("Varna",27.91,43.21),
 ("Ankara",32.86,39.93),("Lissabon",-9.14,38.72),
 ("Madrid",-3.70,40.42),("Sevilla",-5.99,37.39),
 ("Rom",12.50,41.90),("Palermo",13.36,38.12),
 ("Athen",23.73,37.98),("Antalya",30.71,36.89),
 ("Algier",3.06,36.75),
 ("Azoren",-25.67,37.74),("Kanaren",-16.57,28.29),
)

# Temperature palette -35..45 C; these are DISPLAY colours only.
STOPS=(
 (-35,(27,37,114)),(-20,(35,82,173)),(-10,(49,154,210)),
 (0,(110,202,210)),(7,(83,169,118)),(13,(167,197,103)),
 (18,(246,215,98)),(23,(249,152,78)),(28,(235,95,75)),
 (34,(206,62,95)),(45,(119,43,94))
)
REQ_HEADERS={"User-Agent":"ClimateDashboard-Private-Europe-Tmax/1.0","Connection":"close"}


def request_bytes(url,retries=5):
    for attempt in range(retries):
        try:
            with urlopen(Request(url,headers=REQ_HEADERS),timeout=125) as response:
                payload=response.read()
            if len(payload)<150:raise ValueError(f"Antwort zu klein ({len(payload)} Bytes)")
            return payload
        except HTTPError as exc:
            if exc.code in (400,403,404):
                raise RuntimeError(f"Quelldatei fehlt (HTTP {exc.code}): {url}") from exc
            err=exc
        except (URLError,RemoteDisconnected,IncompleteRead,HTTPException,OSError,socket.timeout,
                TimeoutError,ValueError) as exc:err=exc
        if attempt==retries-1:raise RuntimeError(f"DWD nach {retries} Versuchen nicht erreichbar: {url}: {err}") from err
        time.sleep(min(4*2**attempt,45))
    raise AssertionError("unreachable")


def icon_url(cycle,hour):
    basename=f"{ICON_PREFIX}_{cycle:%Y%m%d%H}_{hour:03d}_TMIN_2M.grib2.bz2"
    return f"{ICON_ROOT}/{cycle.hour:02d}/tmin_2m/{basename}"


def choose_cycle(now):
    # 12 UTC runs have five complete 18-06 UTC nights through +114h.
    midnight=now.replace(hour=0,minute=0,second=0,microsecond=0)
    for lag in range(3):
        candidate=midnight+timedelta(hours=12)-timedelta(days=lag)
        first_morning=(candidate+timedelta(days=1)).date()
        # A valid TN forecast for an already elapsed 06 UTC morning is not
        # available in the latest MOSMIX-L update. Never splice old ICON
        # nights with fresh MOS forecasts or publish incomplete five-night data.
        if first_morning<now.date() or (
            first_morning==now.date() and now.hour>=6
        ):
            LOG.info("Skipping stale ICON 12 UTC cycle %s; first night already elapsed",candidate)
            continue
        try:
            raw=request_bytes(icon_url(candidate,114),retries=1)
            if not raw.startswith(b"BZh"):continue
            LOG.info("ICON-EU run candidate: %s",candidate)
            return candidate
        except RuntimeError as ex:
            LOG.info("ICON-EU run not yet ready (%s): %s",candidate,ex)
    raise RuntimeError("Kein geeigneter ICON-EU-Hauptlauf mit Nachttemperaturminimum bis +114 h")


def parse_icon(payload,expected_end):
    with tempfile.TemporaryFile() as handle:
        handle.write(bz2.decompress(payload))
        handle.seek(0)
        grib=eccodes.codes_grib_new_from_file(handle)
        if grib is None:raise RuntimeError("ICON-EU GRIB2 fehlt")
        try:
            # These fields represent preceding six-hour MINIMA, not instant T2m.
            start=int(eccodes.codes_get(grib,"startStep"))
            end=int(eccodes.codes_get(grib,"endStep"))
            stat=str(eccodes.codes_get(grib,"stepType"))
            units=str(eccodes.codes_get(grib,"units"))
            if (start,end,stat)!=(expected_end-6,expected_end,"min"):
                raise RuntimeError(f"ICON-EU +{expected_end}: unerwartetes Intervall {start}-{end}, {stat}")
            if units!="K":raise RuntimeError(f"ICON-EU TMIN nicht in Kelvin: {units}")
            lat=np.asarray(eccodes.codes_get_array(grib,"latitudes"),dtype=np.float32)
            lon=np.asarray(eccodes.codes_get_array(grib,"longitudes"),dtype=np.float32)
            temp=np.asarray(eccodes.codes_get_values(grib),dtype=np.float32)
            if len(temp)<100000 or not(len(lat)==len(lon)==len(temp)):
                raise RuntimeError("ICON-EU-Gitter unvollständig")
            if not np.any((temp>220)&(temp<335)):
                raise RuntimeError("ICON-EU TMIN enthält keine plausiblen Werte")
            return lat,lon,temp-273.15
        finally:eccodes.codes_release(grib)


def image_mapping(lat,lon):
    target_lat,target_lon=np.meshgrid(np.linspace(LAT_MAX,LAT_MIN,HEIGHT),
                                      np.linspace(LON_MIN,LON_MAX,WIDTH),indexing="ij")
    lon=np.where(lon>180,lon-360,lon)
    tree=cKDTree(np.column_stack((lat,lon)))
    distance,index=tree.query(np.column_stack((target_lat.ravel(),target_lon.ravel())),workers=2)
    # Mapping 0.125° output to native resolution, never claiming finer model resolution.
    return index, distance<.20


def encode_temperature_rgba(values):
    """16-bit unsigned fixed-point °C in R/G (0.1 °C); alpha marks valid cells.

    Decode as ((R*256+G)/10 - 100). No interpolation or reforecasting.
    """
    valid=np.isfinite(values)
    result=np.zeros((len(values),4),dtype=np.uint8)
    encoded=np.zeros(len(values),dtype=np.uint16)
    encoded[valid]=np.rint((values[valid]+100.0)*10.0).clip(0,65535).astype(np.uint16)
    result[valid,0]=(encoded[valid]>>8).astype(np.uint8)
    result[valid,1]=(encoded[valid]&255).astype(np.uint8)
    result[valid,3]=255
    return result


def icon_day(cycle,day,out):
    # For 12Z: night 1 uses +12/+18 (18-06 UTC), night 5 +108/+114.
    hours=[day*24+12,day*24+18]
    mapping=None
    minimum=None
    for hour in hours:
        lat,lon,values=parse_icon(request_bytes(icon_url(cycle,hour)),hour)
        if mapping is None:
            mapping=image_mapping(lat,lon)
        index,valid=mapping
        sampled=values[index].copy()
        sampled[~valid]=np.nan
        sampled[(sampled < -80)|(sampled > 65)]=np.nan
        minimum=sampled if minimum is None else np.fmin(minimum,sampled)
        LOG.info("ICON-EU +%03d: %d von %d Kartenzellen",hour,np.isfinite(sampled).sum(),len(sampled))
    if np.mean(np.isfinite(minimum))<.80:
        raise RuntimeError("Zu viele fehlende ICON-EU-Kartenzellen")
    colour=np.zeros((len(minimum),4),dtype=np.uint8)
    valid=np.isfinite(minimum)
    for ch in range(3):
        colour[valid,ch]=np.interp(minimum[valid],
                 [v[0] for v in STOPS],[v[1][ch] for v in STOPS]).astype(np.uint8)
    colour[valid,3]=242
    filename=f"icon_tmin_{(cycle+timedelta(days=day+1)).date().isoformat()}.png"
    Image.fromarray(colour.reshape(HEIGHT,WIDTH,4),"RGBA").save(out/filename,optimize=True)
    rawfilename=f"icon_tmin_raw_{(cycle+timedelta(days=day+1)).date().isoformat()}.png"
    raw=encode_temperature_rgba(minimum)
    Image.fromarray(raw.reshape(HEIGHT,WIDTH,4),"RGBA").save(out/rawfilename,optimize=True)
    return filename,rawfilename,round(float(valid.mean()),4),hours


def local_name(name):return name.rsplit("}",1)[-1]


def nested_text(node,key):
    for item in node.iter():
        if local_name(item.tag)==key:
            value=(item.text or "").strip()
            if value:return value
    return ""


def daily_mos_values(kmz,dates,include_catalog=False):
    """Parse original DWD TN valid at 06 UTC, nearest actual station by city."""
    from io import BytesIO
    expected=set(dates)
    dates_at_index={}
    stations=[]
    issue_time=""
    with zipfile.ZipFile(BytesIO(kmz)) as zipped:
        kml=next((name for name in zipped.namelist() if name.lower().endswith(".kml")),None)
        if not kml:raise RuntimeError("MOSMIX KMZ hat keine KML")
        with zipped.open(kml) as stream:
            steps=[]
            for _,node in ET.iterparse(stream,events=("end",)):
                name=local_name(node.tag)
                if name=="IssueTime" and not issue_time:
                    issue_time=(node.text or "").strip()
                    node.clear()
                elif name=="TimeStep":
                    stamp=(node.text or "").strip()
                    if stamp:
                        date=datetime.fromisoformat(stamp.replace("Z","+00:00"))
                        if date.hour==6 and date.date().isoformat() in expected:
                            dates_at_index[len(steps)]=date.date().isoformat()
                        steps.append(stamp)
                    node.clear()
                elif name=="Placemark":
                    coord=nested_text(node,"coordinates").split()
                    if not coord:
                        node.clear()
                        continue
                    try:
                        lon,lat=map(float,coord[0].split(",")[:2])
                    except (ValueError,IndexError):
                        node.clear()
                        continue
                    if not(LON_MIN<=lon<=LON_MAX and LAT_MIN<=lat<=LAT_MAX):
                        node.clear()
                        continue
                    forecasts={}
                    for f in node.iter():
                        if local_name(f.tag)!="Forecast":continue
                        key=next((v for k,v in f.attrib.items() if local_name(k)=="elementName"),"")
                        if key=="TN":
                            vals=" ".join(part.strip() for part in f.itertext() if part and part.strip()).split()
                            for index,date in dates_at_index.items():
                                if index>=len(vals) or vals[index] in ("-","--"):continue
                                try:
                                    c=float(vals[index])-273.15
                                    if -55<c<55:forecasts[date]=round(c,1)
                                except ValueError:continue
                    if forecasts:
                        stations.append({"id":nested_text(node,"name"),
                                         "name":nested_text(node,"description"),
                                         "lon":lon,"lat":lat,"tn":forecasts})
                    node.clear()
    if len(stations)<100:raise RuntimeError("Zu wenige MOSMIX-Europastationen mit echten TN-Feldern")
    selected=[]
    used=set()
    for city,lon,lat in CITIES:
        options=[]
        for station in stations:
            if station["id"] in used:continue
            # Haversine: only label a city when a genuine MOS forecast is nearby.
            delta_lat=np.deg2rad(station["lat"]-lat)
            delta_lon=np.deg2rad(station["lon"]-lon)
            hav=np.sin(delta_lat/2)**2+np.cos(np.deg2rad(lat))*np.cos(np.deg2rad(station["lat"]))*np.sin(delta_lon/2)**2
            dist=12742*np.arcsin(min(1,np.sqrt(hav)))
            if dist<=MAX_DISTANCE_KM:
                options.append((dist,-len(station["tn"]),station))
        if not options:
            # Keep the reference city's location in the graphic, but NEVER
            # fabricate a MOS temperature when no suitable station exists.
            selected.append({"city":city,"lon":lon,"lat":lat,
                             "station_id":None,"station_name":None,
                             "station_lon":None,"station_lat":None,
                             "distance_km":None,"tn":{},"missing":True})
            LOG.warning("MOSMIX-TN not available near reference city: %s",city)
            continue
        options.sort(key=lambda item:(item[0],item[1]))
        station=options[0][2]
        used.add(station["id"])
        selected.append({"city":city,"lon":lon,"lat":lat,
                         "station_id":station["id"],"station_name":station["name"],
                         "station_lon":station["lon"],"station_lat":station["lat"],
                         "distance_km":round(options[0][0],1),"tn":station["tn"]})
    if len(selected)<18:raise RuntimeError(f"Nur {len(selected)} echte Stadtreferenzen gefunden")
    if not issue_time:raise RuntimeError("DWD MOSMIX IssueTime fehlt")
    LOG.info("MOSMIX %s: %d Stationen gelesen, %d Städte zugeordnet",
             issue_time,len(stations),len(selected))
    return (issue_time,selected,stations) if include_catalog else (issue_time,selected)


def build(out,workers):
    out.mkdir(parents=True,exist_ok=True)
    now=datetime.now(timezone.utc)
    cycle=choose_cycle(now)
    dates=[(cycle+timedelta(days=i+1)).date().isoformat() for i in range(5)]
    mos_payload=request_bytes(MOS_URL)
    if not mos_payload.startswith(b"PK"):raise RuntimeError("MOSMIX KMZ ist kein ZIP")
    issue,stations,catalog=daily_mos_values(mos_payload,dates,include_catalog=True)
    mos_age=now-datetime.fromisoformat(issue.replace("Z","+00:00"))
    if not timedelta(0)<=mos_age<=timedelta(hours=30):
        raise RuntimeError(f"MOSMIX-L-Ausgabe veraltet: {issue}")
    # Compact, real MOSMIX-TN catalogue for private editing/search.
    # The user interface may place a label at any coordinate, but only these
    # actual DWD station forecasts are eligible as temperature sources.
    catalog_data={
        "schema":1,"issue_time":issue,"days":dates,
        "stations":[{"id":x["id"],"name":x["name"],
                     "lon":round(x["lon"],5),"lat":round(x["lat"],5),
                     "tn":[x["tn"].get(day) for day in dates]}
                    for x in sorted(catalog,key=lambda q:(q["name"],q["id"]))
                    if x["id"] and x["name"]]
    }
    if len(catalog_data["stations"])<1000:
        raise RuntimeError("MOSMIX-Stationskatalog unvollständig")
    (out/"stations_catalog.json").write_text(
        json.dumps(catalog_data,ensure_ascii=False,separators=(",",":")),
        encoding="utf-8"
    )
    daydata={}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs={pool.submit(icon_day,cycle,i,out):i for i in range(5)}
        for future in as_completed(jobs):
            i=jobs[future]
            daydata[i]=future.result()
    days=[]
    for i,date in enumerate(dates):
        image,rawimage,coverage,hours=daydata[i]
        points=[]
        for s in stations:
            # Reference cities without native MOSMIX TX are kept with null.
            points.append({k:s[k] for k in ("city","lon","lat","station_id","station_name",
                                           "station_lon","station_lat","distance_km")}|{"tmin_c":s["tn"].get(date)})
        if sum(point["tmin_c"] is not None for point in points)<15:
            raise RuntimeError(f"Nur {len(points)} aktuelle MOSMIX-TN-Städte für {date}")
        days.append({"date":date,"icon_png":image,
                     "icon_raw_png":rawimage,"icon_hours":hours,
                     "coverage":coverage,"stations":points})
    manifest={
        "schema":2,"product":"Europa Tmin · MOSMIX-L + ICON-EU",
        "icon_cycle":cycle.strftime("%Y%m%d%H"),"mos_issue_utc":issue,
        "built_utc":now.isoformat().replace("+00:00","Z"),
        "timezone":"UTC","daily_window":"18:00-06:00 UTC",
        "forecast_kind":"tmin",
        "night_date_basis":"date is following 06 UTC morning",
        "stations_catalog":"stations_catalog.json",
        "stations_catalog_count":len(catalog_data["stations"]),
        "mos_parameter":"TN 12-hour minimum valid at 06 UTC",
        "icon_parameter":"TMIN_2M six-hour minima, combined 18-06 UTC",
        "units":"degrees C",
        "grid":{"west":LON_MIN,"east":LON_MAX,"south":LAT_MIN,"north":LAT_MAX,
                "width":WIDTH,"height":HEIGHT,"step":STEP},
        "raster_note":"0.125 degree display grid only; no assertion of native ICON-EU resolution.",
        "raw_raster_encoding":"R*256+G = round((Tmin_C+100)*10); A=255 valid, A=0 missing",
        "sources":{"mos":"DWD Open Data MOSMIX-L all_stations KMZ",
                   "icon":"DWD Open Data ICON-EU Europe regular-lat-lon GRIB2"},
        "days":days
    }
    # Publish manifest last, after all images are valid on disk.
    for day in days:
        for key in ("icon_png","icon_raw_png"):
            fp=out/day[key]
            with Image.open(fp) as img:
                img.verify()
    tmp=out/"current.json.tmp"
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    tmp.replace(out/"current.json")
    LOG.info("Alle fünf echten ICON+MOS-Nachtminima verifiziert: %s",dates)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--max-workers",type=int,default=2)
    a=p.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    build(a.out,max(1,min(a.max_workers,3)))


if __name__=="__main__":
    main()
