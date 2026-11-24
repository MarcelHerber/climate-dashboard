#!/usr/bin/env python3
"""Fast temperature comparison from existing DWD daily station archives.
Fixed station panel per region and parameter, no mixing with HYRAS and no
spatial interpolation. A day is missing if any panel member is missing.
"""
import argparse, base64, calendar, json, zlib
from datetime import date, timedelta
from pathlib import Path
import numpy as np

REGIONS=["Deutschland","Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen"]
FIELDS={"tmax":0,"tmin":1,"tmean":2}
FIRST=date(1981,1,1)
MISSING=-32768

def write(path,doc):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(doc,ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf-8")

def decode(doc, end):
    if doc.get("format")!="dwd-tx-tn-tm-zlib16-v1": raise ValueError("Unknown archive")
    a=np.frombuffer(zlib.decompress(base64.b64decode(doc["data"])),dtype="<i2").reshape(len(doc["years"]),366,3)
    out=np.full(((end-FIRST).days+1,3),MISSING,dtype=np.int16)
    for i,y in enumerate(doc["years"]):
        if y<FIRST.year or y>=end.year: continue
        offset=(date(y,1,1)-FIRST).days
        n=365+calendar.isleap(y)
        out[offset:offset+n]=a[i,:n]
    return out

def panel_series(candidates, historical_days, field):
    # Prefer continuous historical records, then current availability.
    # All selected station IDs are fixed for the complete evaluation interval.
    scored=[]
    for sid,a in candidates:
        valid=(a[:,field]>=-600)&(a[:,field]<=600)
        hist=float(valid[:historical_days].mean())
        recent=float(valid[historical_days:].mean()) if len(valid)>historical_days else 0
        if hist>=.98 and recent>=.9: scored.append((hist,recent,sid,a))
    scored.sort(key=lambda x:(-x[0],-x[1],x[2]))
    complete=[s for s in scored if s[0]==1 and s[1]==1]
    selected=(complete if complete else scored)[:12]
    return [(s[2],s[3]) for s in selected]

def average(panel,field,n):
    if not panel: return [None]*n
    a=np.stack([x[1][:,field] for x in panel])
    valid=((a>=-600)&(a<=600)).all(axis=0)
    v=a.mean(axis=0)/10
    return [round(float(x),3) if ok else None for x,ok in zip(v,valid)]

def extremes(candidates,field,n,direction):
    """Independent daily station extremes, with deterministic ties and sample count."""
    if not candidates: return [None]*n,[None]*n,[0]*n
    candidates=sorted(candidates,key=lambda x:x[0])
    a=np.stack([x[1][:,field] for x in candidates])
    valid=(a>=-600)&(a<=600)
    count=valid.sum(axis=0)
    work=np.where(valid,a,32767 if direction=="low" else -32768)
    ix=work.argmin(axis=0) if direction=="low" else work.argmax(axis=0)
    v=work[ix,np.arange(n)]
    return ([float(x)/10 if c else None for x,c in zip(v,count)],
            [candidates[i][0] if c else None for i,c in zip(ix,count)],
            [int(c) for c in count])

def write_extremes(output,metadata,data,parameter,field,cutoff,n):
    candidates={r:[(sid,v) for sid,v in data.items() if metadata[sid]["state"]==r] for r in REGIONS[1:]}
    candidates["Deutschland"]=list(data.items())
    years=list(range(FIRST.year,cutoff.year+1))
    for direction in ("low","high"):
        series={r:extremes(candidates[r],field,n,direction) for r in REGIONS}
        dest=output/"extremes"/parameter/direction
        for y in years:
            lo=(date(y,1,1)-FIRST).days
            hi=(min(date(y,12,31),cutoff)-FIRST).days+1
            dates=[(FIRST+timedelta(days=i)).isoformat() for i in range(lo,hi)]
            write(dest/f"{y}.json",{"parameter":parameter,"year":y,"unit":"°C","source":"DWD CDC KL Stationsmessungen","dates":dates,"regions":{r:series[r][0][lo:hi] for r in REGIONS},"station_ids":{r:series[r][1][lo:hi] for r in REGIONS},"counts":{r:series[r][2][lo:hi] for r in REGIONS}})
        write(dest/"index.json",{"parameter":parameter,"years":years,"regions":REGIONS,"data_through":cutoff.isoformat(),"direction":direction,"station_names":{sid:s.get("name",sid) for sid,s in metadata.items()},"method":"Tagesextrem aller verfügbaren DWD-KL-Stationen im vorhandenen Dashboard-Archiv. Wechselndes Messnetz, keine Flächenmittel. Laufendes Jahr vorläufig."})
        print("station extremes",parameter,direction,flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,default=Path("."))
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    idx=json.loads((a.root/"station_climate_days_index.json").read_text())
    cutoff=min(date.fromisoformat(idx["data_through"]),date.today()-timedelta(days=1))
    if cutoff.year<=FIRST.year: raise ValueError("Invalid cutoff")
    n=(cutoff-FIRST).days+1
    hist_days=(date(cutoff.year,1,1)-FIRST).days
    metadata={str(s["id"]).zfill(5):s for s in idx["stations"] if s.get("state") in REGIONS[1:]}
    data={}
    for sid,meta in metadata.items():
        path=a.root/"station_threshold_daily"/(sid+".json")
        if not path.exists(): continue
        doc=json.loads(path.read_text())
        data[sid]=decode(doc,cutoff)
    for rel in idx.get("current_files",[]):
        doc=json.loads((a.root/rel).read_text())
        y,m=doc["year"],doc["month"]
        if y!=cutoff.year: continue
        for sid,rows in doc["stations"].items():
            if sid not in metadata: continue
            if sid not in data: data[sid]=np.full((n,3),MISSING,dtype=np.int16)
            for d,row in enumerate(rows,1):
                day=date(y,m,d)
                if day>cutoff: break
                if row and len(row)>=5:
                    data[sid][(day-FIRST).days]=[v if v is not None and -600<=v<=600 else MISSING for v in row[2:5]]
    for parameter,field in FIELDS.items():
        write_extremes(a.output,metadata,data,parameter,field,cutoff,n)
        panels={r:panel_series([(sid,v) for sid,v in data.items() if metadata[sid]["state"]==r],hist_days,field) for r in REGIONS[1:]}
        panels["Deutschland"]=[x for r in REGIONS[1:] for x in panels[r]]
        counts={r:len(v) for r,v in panels.items()}
        if counts["Deutschland"]<10: raise RuntimeError("Insufficient station panel")
        series={r:average(panels[r],field,n) for r in REGIONS}
        years=list(range(FIRST.year,cutoff.year+1))
        for y in years:
            start=date(y,1,1);stop=min(date(y,12,31),cutoff)
            lo=(start-FIRST).days;hi=(stop-FIRST).days+1
            dates=[(FIRST+timedelta(days=i)).isoformat() for i in range(lo,hi)]
            write(a.output/parameter/f"{y}.json",{"parameter":parameter,"year":y,"unit":"°C","source":"DWD CDC KL festes Stationspanel","dates":dates,"regions":{r:series[r][lo:hi] for r in REGIONS}})
        write(a.output/parameter/"index.json",{"parameter":parameter,"years":years,"regions":REGIONS,"data_through":cutoff.isoformat(),"station_counts":counts,"station_ids":{r:[sid for sid,_ in panels[r]] for r in REGIONS},"method":"Ungewichtetes Mittel eines pro Snapshot und Parameter festen Stationspanels; keine Flächenmittel. Fehlende Einzelstation => kein Tageswert. Laufendes Jahr vorläufig. Stationsverlegungen nicht homogenisiert."})
        print(parameter,counts,flush=True)
if __name__=="__main__":main()
