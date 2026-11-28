#!/usr/bin/env python3
"""Read-only annual-record audit; output flags + optional DWD raw neighbourhood evidence."""
import argparse
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from statistics import median

import update_station_records as dwd
import build_annual_extremes_extra as extra
from annual_quality_rules import RULES, RULES_VERSION, matching_rule, quality_level

FILES=["dwd_annual_extremes.json","dwd_annual_extra_kl.json","dwd_annual_extra_rr.json","dwd_annual_extra_tu.json"]
DATA=Path("data")
OUTPUT=DATA/"dwd_annual_quality.json"

def identity(metric,entry,metrics):
    count=metrics[metric].get("kind","extreme")!="extreme"
    key=entry[1 if count else 2]
    sid=key.split(":")[-2] if key.count(":")>=2 else key.split(":")[0]
    day=entry[3] if metrics[metric].get("kind")=="station_year_series" else None if count else entry[1]
    return sid,day,key

def metric_field(k):
    if k.startswith(("snow","snox")):return "SHK"
    if k.startswith(("rr","rain","wet_","dry_")):return "RS"
    if k in ("tgn","tgx"):return "TMK"
    if k in ("tnn","tnx") or "frost" in k:return "TNK"
    if k in ("txx","txn") or any(w in k for w in ("ice","summer","hot","desert","heat")):return "TXK"
    if k.startswith(("wind","fgx")):return "FX"
    if k=="dtrx":return "DTR"
    return "night"

def audit(docs):
    metrics={};stations={};rows=defaultdict(lambda:defaultdict(dict))
    for doc in docs:
        metrics.update(doc["metrics"]);stations.update(doc["stations"])
        for a,ys in doc["records"].items():
            for y,row in ys.items():rows[a][y].update(row)
    flags={};checked=0
    def mark(a,y,k,e,status,reason):
        key="|".join((a,y,k));old=flags.get(key)
        if old:
            if reason not in old["reasons"]:old["reasons"].append(reason)
            if status=="excluded":old["status"]=status
        else:flags[key]={"status":status,"reasons":[reason],"entry":e}
    for a,ys in rows.items():
        for y,row in ys.items():
            for k,e in row.items():
                if e is None:continue
                checked+=1
                sid,day,key=identity(k,e,metrics);st=stations.get(key,{})
                h=st.get("height");v=e[0];field=metric_field(k)
                if not st:mark(a,y,k,e,"suspect","Stationsmetadaten fehlen")
                # Match exact day/series range, not a station's unrelated annual metrics.
                if day:
                    rule=matching_rule(sid,field,date.fromisoformat(day),v)
                    if rule:mark(a,y,k,e,rule["status"],rule["reason"])
                if k=="dry_spell" and v>=90:
                    mark(a,y,k,e,"excluded" if sid=="02552" and 1903<=int(y)<=1915 else "suspect","Außergewöhnlich lange Trockenperiode; Nullwert-/Lückenprüfung")
                if k.startswith("snow_gain") and v>=(40 if k.endswith("lt_400") else 100):
                    mark(a,y,k,e,"suspect","Ungewöhnlicher Schneehöhenzuwachs; Nachbartage, Niederschlag und Nachbarstationen prüfen")
                if k.startswith("snox") and ((h is not None and h<100 and v>=50) or (k.endswith("lt_400") and v>=80)):
                    mark(a,y,k,e,"suspect","Ungewöhnliche Schneehöhe für Höhenlage")
                if k.startswith("snox") and day and h is not None and h<1000 and day[5:7] in ("06","07","08") and v>=10:
                    mark(a,y,k,e,"suspect","Schnee im Sommer in geringer Höhenlage")
                if k=="tgn" and day and day[5:7] in ("06","07","08") and h is not None and h<1000 and v< -5:
                    mark(a,y,k,e,"suspect","Ungewöhnlich kaltes Sommertagesmittel")
                if k=="dtrx" and v>=30:mark(a,y,k,e,"suspect","Tagesspanne ≥30 K")
                if k=="wet_spell" and v>=33:mark(a,y,k,e,"suspect","Lange Niederschlagsserie")
                if k.startswith("fgx") and v>=250:mark(a,y,k,e,"suspect","Böe ≥250 km/h; amtliche Bestätigung prüfen")
                # Explicit user estimates retain provenance, not official correction.
                if k.startswith("snox") and sid=="01975" and day in ("2026-01-10","2026-01-11","2026-01-12") and v==25:
                    mark(a,y,k,e,"corrected","Manueller Ersatzwert 25 cm; 10.01. DWD-Aussage, Folgetage Nutzervorgabe")
            for hi,lo in [("txx","tgx"),("txx","tnx"),("tgn","tnn"),("rr720x","rr168x"),("rr168x","rr72x")]:
                if row.get(hi) and row.get(lo) and row[hi][0]<row[lo][0]:
                    for k in (hi,lo):mark(a,y,k,row[k],"suspect","Inkonsistenz "+hi+" / "+lo+"; auch unterschiedliche Datenverfügbarkeit möglich")
    for a,ys in rows.items():
        for y,row in ys.items():
            for k,e in row.items():
                if not e or metrics[k].get("kind","extreme")!="extreme":continue
                sid,day,_=identity(k,e,metrics)
                if k=="rr24x" and sid=="05779" and day=="2002-08-12" and e[0]==312:
                    flags["|".join((a,y,k))]=dict(status="confirmed",entry=e,reasons=["DWD Klimastatusbericht 2002: 312 mm"],source="https://www.dwd.de/DE/leistungen/klimastatusbericht/publikationen/ksb2002_pdf/15_2002.pdf?__blob=publicationFile&v=1")
                if k=="fgx_ge_400" and sid=="05792" and day=="1985-06-12" and abs(e[0]-335)<.5:
                    flags["|".join((a,y,k))]=dict(status="confirmed",entry=e,reasons=["Dokumentierter Windrekord 335 km/h (gerundet), 12.06.1985"],source="https://www.wettergefahren-fruehwarnung.de/Produkte/Sicher/extrem.html")
    return dict(version=1,rules_version=RULES_VERSION,checked=checked,flags=flags,rules=RULES,
                generated_at=datetime.now(timezone.utc).isoformat())

def km(a,b):
    if any(v is None for v in (a.latitude,a.longitude,b.latitude,b.longitude)):return math.inf
    x,y,z,w=map(math.radians,(a.latitude,a.longitude,b.latitude,b.longitude))
    return 6371*2*math.asin(min(1,math.sqrt(math.sin((x-z)/2)**2+math.cos(x)*math.cos(z)*math.sin((y-w)/2)**2)))

def raw_neighbours(report,docs,limit):
    """Compare a bounded priority sample; download original files, not secondary websites.
    QN is preserved, missing stays missing. No automatic exclusion by neighbour alone."""
    metrics={k:v for d in docs for k,v in d["metrics"].items()}
    targets={}
    for key,flag in report["flags"].items():
        a,y,k=key.split("|");e=flag["entry"];sid,day,_=identity(k,e,metrics)
        field=metric_field(k)
        if field not in ("SHK","TMK","RS","DTR","FX") or not day:continue
        targets[(sid,day,field)]=(key,flag)
    priority=lambda item:(0 if item[1][1]["status"]=="excluded" else 1,0 if item[0][2]=="SHK" else 1)
    targets=sorted(targets.items(),key=priority)[:limit]
    configs={}
    for family in ("KL","RR"):
        prefix="" if family=="KL" else "RR_"
        get=lambda n:getattr(dwd,prefix+n)
        meta=dwd.parse_metadata(dwd.download(get("METADATA_URL"),timeout=90))
        files=extra.family_files(get("HISTORICAL_URL"),get("HISTORICAL_PATTERN"),get("RECENT_URL"),get("RECENT_PATTERN"),get("STATION_ID_PATTERN"),300)
        configs[family]=(meta,files)
    @lru_cache(maxsize=24)
    def window(family,sid,day):
        meta,files=configs[family];out={}
        for base,name,pre in files.get(sid,[]):
            matches=re.search(r"_(\d{8})_(\d{8})_hist\.zip$",name,re.I)
            if matches and not matches[1][:4]<=str(day.year)<=matches[2][:4]:continue
            if pre and day.year<date.today().year-2:continue
            blob=dwd.download_station_zip(base,name)
            for row in extra.product_rows(blob,("MESS_DATUM",)):
                stamp=row["MESS_DATUM"].strip()
                if not (day-timedelta(days=2)).strftime("%Y%m%d")<=stamp<=(day+timedelta(days=2)).strftime("%Y%m%d"):continue
                fields={}
                for k,raw,low,high in [("SHK",row.get("SHK_TAG",row.get("SHK")),0,2000),("TMK",row.get("TMK"),-60,60),("TNK",row.get("TNK"),-60,60),("TXK",row.get("TXK"),-60,60),("RS",row.get("RS",row.get("RSK")),0,1000),("FX",row.get("FX",row.get("FXK")),0,120)]:
                    value=extra.number(raw,low,high)
                    if value is not None:fields[k]={"value":value*3.6 if k=="FX" else value,"qn":quality_level(row,k),"recent":pre}
                if "TNK" in fields and "TXK" in fields:fields["DTR"]={"value":round(fields["TXK"]["value"]-fields["TNK"]["value"],1),"qn":quality_level(row,"TNK"),"recent":pre}
                target=out.setdefault(stamp,{})
                for k,v in fields.items():target.setdefault(k,v)
        return out
    evidence={}
    for (sid,stamp,field),(key,flag) in targets:
        try:
            day=date.fromisoformat(stamp);family="RR" if field=="RS" else "KL";meta,files=configs[family]
            seg=meta.segment_for(sid,day)
            nearby=[]
            for other in files:
                if other==sid:continue
                o=meta.segment_for(other,day)
                if not o.start<=day<=o.end:continue
                if seg.height is None or o.height is None or abs(seg.height-o.height)>200:continue
                dist=km(seg,o)
                if dist<=100:nearby.append((dist,other,o))
            actual=window(family,sid,day);neighbours=[]
            for dist,other,o in sorted(nearby,key=lambda x:x[0])[:12]:
                v=window(family,other,day).get(day.strftime("%Y%m%d"),{}).get(field)
                if v:neighbours.append(dict(station_id=other,name=o.name,distance_km=round(dist,1),height=o.height,**v))
                if len(neighbours)>=5:break
            evidence["|".join((sid,stamp,field))]=dict(station_id=sid,date=stamp,field=field,raw_window=actual,neighbours=neighbours,
                  neighbour_median=median([n["value"] for n in neighbours]) if neighbours else None)
        except Exception as exc:evidence["|".join((sid,stamp,field))]={"error":str(exc)}
    report["raw_evidence"]=evidence


def compare_decades(report,docs):
    """Same station and same month-third, not an independent measurement.
    An older record can corroborate an extremum but cannot prove it valid."""
    mapping={
        "dwd_decade_records.json":{"tnn":"tnk_low","txx":"txk_high","tnx":"tnk_high","txn":"txk_low"},
        "dwd_decade_snow_records.json":{"snox_ge_400":None,"snox_lt_400":None},
        "dwd_decade_extra_kl.json":{"tgx":"tmk_high","tgn":"tmk_low"},
        "dwd_decade_precip_records.json":{"rr24x":None}
    }
    out={};checked=0;matches=0
    for filename,keys in mapping.items():
        path=DATA/filename
        if not path.exists():continue
        dec=json.loads(path.read_text(encoding="utf-8"))
        for doc in docs:
            for a,ys in doc["records"].items():
                for y,row in ys.items():
                    for k,dk in keys.items():
                        e=row.get(k)
                        if not e:continue
                        sid,day,_=identity(k,e,doc["metrics"])
                        if not day or day>dec["data_through"]:continue
                        period=f"month-{day[5:7]}-d{min(3,(int(day[8:10])-1)//10+1)}"
                        root=dec["station_records"] if dk is None else dec["station_records"].get(dk,{})
                        candidate=root.get(a,{}).get(period,{}).get(sid)
                        if not candidate:continue
                        checked+=1
                        if candidate[1]==day and abs(candidate[0]-e[0])<.11:
                            matches+=1;continue
                        direction=doc["metrics"][k].get("direction","desc")
                        if (direction=="asc" and e[0]<candidate[0]-.11) or (direction!="asc" and e[0]>candidate[0]+.11):
                            key="|".join((a,y,k))
                            out[key]=dict(annual=e,decade=candidate,archive=filename)
                            flag=report["flags"].setdefault(key,dict(status="suspect",entry=e,reasons=[]))
                            flag["reasons"].append("Abweichung zum älteren Dekadenarchiv; Datenrevision/Abdeckung möglich")
        del dec
    report["decade_comparison"]=dict(checked=checked,exact_matches=matches,discrepancies=out)

def main():
    p=argparse.ArgumentParser();p.add_argument("--neighbours",type=int,default=0);args=p.parse_args()
    docs=[json.loads((DATA/f).read_text(encoding="utf-8")) for f in FILES if (DATA/f).exists()]
    assert len(docs)==4,"All four archives required"
    report=audit(docs)
    compare_decades(report,docs)
    if args.neighbours:raw_neighbours(report,docs,args.neighbours)
    elif OUTPUT.exists():
        previous=json.loads(OUTPUT.read_text(encoding="utf-8"))
        report["raw_evidence"]=previous.get("raw_evidence",{})
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    print("checked",report["checked"],"flags",len(report["flags"]),flush=True)

if __name__=="__main__":main()
