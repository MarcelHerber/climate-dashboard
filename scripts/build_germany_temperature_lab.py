#!/usr/bin/env python3
"""Protected Germany temperature maps: exact MOSMIX TX/TN windows, ICON-D2 GRIB."""
import argparse,bz2,json,logging,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import eccodes
from PIL import Image
from scipy.spatial import cKDTree
import build_europe_tmax_lab as tx
import build_europe_tmin_lab as tn

WEST,EAST,SOUTH,NORTH,STEP=5.0,16.5,47.0,56.0,.025
WIDTH,HEIGHT=461,361
CITIES=(("Flensburg",9.43,54.79),("Kiel",10.14,54.32),("Hamburg",10,53.55),
("Rostock",12.13,54.09),("Schwerin",11.41,53.63),("Bremen",8.80,53.08),
("Oldenburg",8.21,53.14),("Hannover",9.74,52.37),("Osnabrück",8.05,52.28),
("Berlin",13.41,52.52),("Potsdam",13.06,52.40),("Magdeburg",11.63,52.13),
("Münster",7.63,51.96),("Dortmund",7.46,51.51),("Düsseldorf",6.78,51.23),
("Köln",6.96,50.94),("Aachen",6.08,50.78),("Kassel",9.50,51.31),
("Erfurt",11.03,50.98),("Leipzig",12.37,51.34),("Dresden",13.74,51.05),
("Chemnitz",12.92,50.83),("Frankfurt",8.68,50.11),("Mainz",8.27,50.00),
("Koblenz",7.59,50.36),("Trier",6.64,49.75),("Saarbrücken",7.00,49.24),
("Kaiserslautern",7.77,49.44),("Mannheim",8.47,49.49),("Karlsruhe",8.40,49.01),
("Stuttgart",9.18,48.78),("Freiburg",7.85,47.99),("Ulm",9.99,48.40),
("Würzburg",9.94,49.79),("Nürnberg",11.08,49.45),("Regensburg",12.10,49.02),
("München",11.58,48.14),("Augsburg",10.90,48.37),("Passau",13.43,48.57),
("Kempten",10.31,47.73),("Garmisch-Partenkirchen",11.10,47.49))
LOG=logging.getLogger("germany-d2")
def windows(cycle,now,kind):
    """Only entire 12-h periods within forecast range; date = end date."""
    result=[]
    for offset in range(4):
        end=(now.replace(hour=18 if kind=="tmax" else 6,minute=0,second=0,microsecond=0)
             +timedelta(days=offset))
        start=end-timedelta(hours=12)
        a=int((start-cycle).total_seconds()/3600); b=a+12
        if start>=cycle and start>=now and b<=48:
            result.append((end.date().isoformat(),a,b))
    return result

def url(cycle,h,kind):
    var=kind+"_2m"
    return f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{cycle.hour:02d}/{var}/icon-d2_germany_regular-lat-lon_single-level_{cycle:%Y%m%d%H}_{h:03d}_2d_{var}.grib2.bz2"

def read_field(cycle,h,kind):
    with tempfile.TemporaryFile() as f:
        f.write(bz2.decompress(tx.request_bytes(url(cycle,h,kind),retries=2)));f.seek(0)
        g=eccodes.codes_grib_new_from_file(f)
        if g is None:raise RuntimeError("GRIB fehlt")
        try:
            start=int(eccodes.codes_get(g,"startStep"));end=int(eccodes.codes_get(g,"endStep"))
            stat=str(eccodes.codes_get(g,"stepType"))
            if end!=h or start>=end or stat!=("max" if kind=="tmax" else "min") or eccodes.codes_get(g,"units")!="K":
                raise RuntimeError(f"Ungültiges GRIB-Intervall {start}-{end} {stat}")
            if int(eccodes.codes_get(g,"dataDate"))!=int(cycle.strftime("%Y%m%d")) or int(eccodes.codes_get(g,"dataTime"))!=cycle.hour*100:
                raise RuntimeError("Falscher Modelllauf")
            lat=np.asarray(eccodes.codes_get_array(g,"latitudes"));lon=np.asarray(eccodes.codes_get_array(g,"longitudes"))
            v=np.asarray(eccodes.codes_get_values(g),dtype=np.float32)-273.15
            v[(v<-80)|(v>65)]=np.nan
            return start,lat,lon,v
        finally:eccodes.codes_release(g)

def make_map(cycle,a,b,kind,date,out):
    h=b; mapping=None; aggregate=None; intervals=[]; reference=None
    reducer=np.maximum if kind=="tmax" else np.minimum
    while h>a:
        start,lat,lon,values=read_field(cycle,h,kind)
        if start<a:raise RuntimeError(f"GRIB überschreitet Zeitfenster {a}-{b}: {start}-{h}")
        if mapping is None:
            yy,xx=np.meshgrid(np.linspace(NORTH,SOUTH,HEIGHT),np.linspace(WEST,EAST,WIDTH),indexing="ij")
            lon=np.where(lon>180,lon-360,lon)
            # Longitude distance corrected near Germany; no extrapolation.
            factor=np.cos(np.deg2rad(51.5))
            tree=cKDTree(np.column_stack((lat,lon*factor)))
            dist,index=tree.query(np.column_stack((yy.ravel(),xx.ravel()*factor)),workers=2)
            mapping=(index,dist<=.045);reference=(lat,lon)
        else:
            lon=np.where(lon>180,lon-360,lon)
            if not np.array_equal(lat,reference[0]) or not np.array_equal(lon,reference[1]):raise RuntimeError("Wechselndes ICON-Gitter")
        index,valid=mapping
        sample=values[index].copy();sample[~valid]=np.nan
        aggregate=sample if aggregate is None else reducer(aggregate,sample)
        intervals.append([start,h]);h=start
    valid=np.isfinite(aggregate);coverage=float(valid.mean())
    if coverage<.95:raise RuntimeError(f"Unvollständige ICON-D2-Fläche: {coverage:.3f}")
    color=np.zeros((len(aggregate),4),dtype=np.uint8)
    for ch in range(3):color[valid,ch]=np.interp(aggregate[valid],[x[0] for x in tx.STOPS],[x[1][ch] for x in tx.STOPS]).astype(np.uint8)
    color[valid,3]=242
    names=[f"icon_{kind}_{date}.png",f"icon_{kind}_raw_{date}.png"]
    for name,data in zip(names,[color,tx.encode_temperature_rgba(aggregate)]):
        Image.fromarray(data.reshape(HEIGHT,WIDTH,4),"RGBA").save(out/name,optimize=True)
        with Image.open(out/name) as img:img.verify()
    return {"date":date,"icon_png":names[0],"icon_raw_png":names[1],"coverage":round(coverage,4),"icon_intervals":sorted(intervals)}

def geography(out):
    base=json.loads(tx.request_bytes("https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/seasonal-europe-data/data/seasonal-europe/geography_50m.json"))
    states=json.loads(tx.request_bytes("https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"))
    base["states"]=[]
    for feature in states["features"]:
        g=feature["geometry"]
        polygons=[g["coordinates"]] if g["type"]=="Polygon" else g["coordinates"] if g["type"]=="MultiPolygon" else []
        base["states"].append({"p":polygons})
    if len(base["states"])!=16 or not base.get("countries"):raise RuntimeError("Kartengrenzen unvollständig")
    (out/"geo.json").write_text(json.dumps(base,ensure_ascii=False,separators=(",",":")),encoding="utf8")

def build(kind,out):
    now=datetime.now(timezone.utc)
    module=tx if kind=="tmax" else tn; key="tx" if kind=="tmax" else "tn"
    module.LON_MIN,module.LON_MAX,module.LAT_MIN,module.LAT_MAX=WEST,EAST,SOUTH,NORTH
    module.CITIES=CITIES;module.MAX_DISTANCE_KM=35
    cycle0=now.replace(hour=now.hour//3*3,minute=0,second=0,microsecond=0)
    out.mkdir(parents=True,exist_ok=True)
    geography(out)
    mos=tx.request_bytes(tx.MOS_URL)
    errors=[]
    for lag in range(9):
        cycle=cycle0-timedelta(hours=3*lag)
        periods=windows(cycle,now,kind)
        if not periods:continue
        dates=[p[0] for p in periods]
        try:
            issue,cities,catalog=module.daily_mos_values(mos,dates,include_catalog=True)
            issue_dt=datetime.fromisoformat(issue.replace("Z","+00:00"))
            if not timedelta(0)<=now-issue_dt<=timedelta(hours=30):raise RuntimeError("MOSMIX veraltet")
            if any(issue_dt>datetime.fromisoformat(date+"T"+("06:00" if kind=="tmax" else "06:00")+"+00:00")-(timedelta(hours=12) if kind=="tmin" else timedelta(0)) for date in dates):raise RuntimeError("MOSMIX nach Fensterbeginn")
            if any(sum(s[key].get(date) is not None for s in cities)<15 for date in dates):raise RuntimeError("Zu wenige MOSMIX-Städte")
            days=[]
            for date,a,b in periods:
                d=make_map(cycle,a,b,kind,date,out)
                d["stations"]=[{k:s[k] for k in ("city","lon","lat","station_id","station_name","station_lon","station_lat","distance_km")}|{kind+"_c":s[key].get(date)} for s in cities]
                days.append(d)
            stations=[{"id":s["id"],"name":s["name"],"lon":s["lon"],"lat":s["lat"],key:[s[key].get(date) for date in dates]} for s in catalog if s["id"] and s["name"]]
            if len(stations)<100:raise RuntimeError("MOSMIX-Katalog unvollständig")
            (out/"stations_catalog.json").write_text(json.dumps({"schema":1,"issue_time":issue,"days":dates,"stations":stations},ensure_ascii=False),encoding="utf8")
            manifest={"schema":2,"product":"Deutschland "+kind+" · MOSMIX-L + ICON-D2","icon_cycle":cycle.strftime("%Y%m%d%H"),"mos_issue_utc":issue,"built_utc":datetime.now(timezone.utc).isoformat(),"daily_window":"06:00-18:00 UTC" if kind=="tmax" else "18:00-06:00 UTC","grid":{"west":WEST,"east":EAST,"south":SOUTH,"north":NORTH,"width":WIDTH,"height":HEIGHT,"step":STEP},"stations_catalog_count":len(stations),"days":days}
            (out/"current.json").write_text(json.dumps(manifest,ensure_ascii=False),encoding="utf8")
            LOG.info("Verified %s %s",kind,dates);return
        except Exception as e:
            LOG.warning("Run %s: %s",cycle,e);errors.append(str(e))
    raise RuntimeError("Kein vollständiger gemeinsamer ICON-D2/MOSMIX-L-Lauf: "+"; ".join(errors))

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--kind",choices=["tmin","tmax"],required=True);p.add_argument("--out",type=Path,required=True)
    args=p.parse_args();logging.basicConfig(level=logging.INFO);build(args.kind,args.out)
