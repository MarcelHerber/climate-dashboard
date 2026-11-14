#!/usr/bin/env python3
"""DWD CDC KL daily corrected precipitation and sunshine for the Phase 3 calendar.

Archive contains *original measured daily values* (not synthetic climatologies),
packed as verified little-endian 16-bit tenths of the original published unit.
The daily index preserves February 29 in leap years; other years leave slot 366
unused. Missing values remain -32768, and station/metric coverage is explicit.
"""
from __future__ import annotations
from collections import defaultdict
import argparse,base64,csv,datetime as dt,io,json,re,struct,time,zlib
from pathlib import Path
from urllib.request import Request,urlopen
from zipfile import ZipFile

BASE="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/historical/"
IDS=("01420","00164","00198","00102","05792","03668","04336","01048","00403","01198")
METRICS={"rain":{"column":"RSK","unit":"mm","label":"Tagesniederschlag (korrigiert)"},
         "sun":{"column":"SDK","unit":"h","label":"Sonnenscheindauer"}}
MISSING=-32768

def download(url):
    last=None
    for i in range(3):
        try:
            with urlopen(Request(url,headers={"User-Agent":"ClimateDashboard-Phase3-DWD/1.0"}),timeout=70) as response:
                return response.read(15_000_000)
        except Exception as error:
            last=error;time.sleep(i+1)
    raise RuntimeError(str(last))

def entries(raw,sid):
    rx=re.compile(r"tageswerte_KL_"+sid+r"_(\d{8})_(\d{8})_hist\.zip")
    vals=[(m.group(2),m.group(0)) for m in rx.finditer(raw)]
    return BASE+max(vals)[1] if vals else None

def parse(blob):
    data=defaultdict(lambda:{"rain":[MISSING]*366,"sun":[MISSING]*366})
    with ZipFile(io.BytesIO(blob)) as zipf:
        names=[n for n in zipf.namelist() if n.lower().endswith(".txt") and "produkt" in n.lower()]
        if not names:raise ValueError("Missing product text from DWD KL archive")
        for name in names:
            with zipf.open(name) as dataf,io.TextIOWrapper(dataf,encoding="latin1") as text:
                reader=csv.DictReader(text,delimiter=";")
                header={k.strip():k for k in reader.fieldnames or []}
                if "MESS_DATUM" not in header:raise ValueError("Original KL date field absent")
                for row in reader:
                    day=(row.get(header["MESS_DATUM"]) or "").strip()
                    if not re.fullmatch(r"\d{8}",day):continue
                    try:date=dt.date(int(day[:4]),int(day[4:6]),int(day[6:8]))
                    except ValueError:continue
                    ix=date.timetuple().tm_yday-1
                    for metric,info in METRICS.items():
                        key=header.get(info["column"])
                        if not key:continue
                        try:value=float((row.get(key) or "").strip().replace(",","."))
                        except (TypeError,ValueError):continue
                        if metric=="rain" and not 0<=value<=500:continue
                        if metric=="sun" and not 0<=value<=24:continue
                        data[date.year][metric][ix]=round(value*10)
    return data

def build(root):
    root.mkdir(parents=True,exist_ok=True)
    index=download(BASE).decode("utf8","replace")
    published=[]
    for sid in IDS:
        url=entries(index,sid)
        if not url:print("DWD KL NOT AVAILABLE",sid,flush=True);continue
        try:
            data=parse(download(url))
            years=sorted(data)
            metric_out={}
            for metric,info in METRICS.items():
                values=[x for y in years for x in data[y][metric]]
                valid=sum(x!=MISSING for x in values)
                if valid<200:continue
                payload=struct.pack("<"+"h"*len(values),*values)
                metric_out[metric]={"label":info["label"],"unit":info["unit"],
                                   "measured_days":valid,
                                   "encoded":"dwd-kl-daily-zlib16-v1",
                                   "data":base64.b64encode(zlib.compress(payload,9)).decode("ascii")}
            if not metric_out:
                print("DWD KL MISSING rain/sun",sid,flush=True);continue
            doc={"schema":1,"station_id":sid,"source":"DWD CDC climate/daily/kl/historical (QC complete)",
                 "source_url":url,"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),
                 "years":years,"columns":METRICS,"metrics":metric_out}
            (root/(sid+".json")).write_text(json.dumps(doc,ensure_ascii=False,separators=(",",":")),encoding="utf8")
            published.append({"id":sid,"years":[years[0],years[-1]],
                "metrics":{k:{"days":v["measured_days"]} for k,v in metric_out.items()}})
            print("DWD KL DAILY",sid,years[0],years[-1],{k:v["measured_days"] for k,v in metric_out.items()},flush=True)
        except Exception as error:
            print("DWD KL FAILURE",sid,str(error)[:250],flush=True)
    if not any(x["id"]=="01420" for x in published):
        raise SystemExit("No verified Frankfurt DWD KL original rain/sun daily archive; refuse publishing")
    metadata={"schema":1,"ready":True,"stations":published,
              "dataset":"DWD CDC daily KL historical RSK (corrected rain) and SDK (sunshine)",
              "generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),
              "note":"DWD historical archive, original observations; not all stations measure sunshine."}
    (root/"index.json").write_text(json.dumps(metadata,ensure_ascii=False,separators=(",",":")),encoding="utf8")
    print("DWD KL HISTORICAL DAILY",len(published),"stations",flush=True)

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--out",type=Path,default=Path("data/rekordlabor/calendar"))
    build(ap.parse_args().out)
