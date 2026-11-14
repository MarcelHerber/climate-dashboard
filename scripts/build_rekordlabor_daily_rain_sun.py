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
# Retain established, verified pilot stations, even if a snow series is absent.
PILOT_IDS=("01420","00164","00198","00102","05792","03668","04336","01048","00403","01198")
PER_STATE=6

def select_stations(index_path:Path, per_state:int=PER_STATE)->tuple[list[str],dict[str,int]]:
    """Choose a geographically distributed and traceable set of genuine DWD stations.
    Geographic distribution follows the existing official DWD snow-station index.
    Only well documented stations with recent observations and >=30 QC years enter
    the automatically discovered extension. Previously tested IDs are retained.
    """
    stations=json.loads(index_path.read_text(encoding="utf8")).get("stations",[])
    grouped:dict[str,list[dict]]={}
    for row in stations:
        sid=str(row.get("id","")).zfill(5)
        state=str(row.get("state") or "")
        if not sid.isdigit() or len(sid)!=5 or not state:continue
        if int(row.get("history_end_year") or 0)<2020:continue
        if int(row.get("accepted_history_years") or 0)<30:continue
        grouped.setdefault(state,[]).append({**row,"id":sid})
    selection=set(PILOT_IDS)
    state_counts={}
    for state in sorted(grouped):
        # Older, still-observing archives get priority; ties use DWD station ID.
        entries=sorted(grouped[state],key=lambda v:(
          -int(v.get("accepted_history_years") or 0),
          -int(v.get("reference_years_available") or 0),v["id"]))
        chosen=entries[:per_state]
        selection.update(row["id"] for row in chosen)
        state_counts[state]=len(chosen)
    return sorted(selection),state_counts
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

def build(root, station_index:Path, per_state:int=PER_STATE):
    root.mkdir(parents=True,exist_ok=True)
    index=download(BASE).decode("utf8","replace")
    selected,states=select_stations(station_index,per_state)
    print("DWD KL COVERAGE CANDIDATES",len(selected),"STATES",json.dumps(states,ensure_ascii=False),flush=True)
    published=[]
    for sid in selected:
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
    if len(published)<30:
        raise SystemExit(f"Only {len(published)} verified DWD KL stations. Refusing incomplete coverage regression.")
    # Rebuild indices from this run only: stale JSON not in the new archive must
    # not masquerade as a current station.
    active={row["id"] for row in published}
    for previous in root.glob("[0-9][0-9][0-9][0-9][0-9].json"):
        if previous.stem not in active:previous.unlink()
    metadata={"schema":1,"ready":True,"stations":published,
              "selection":{"method":"DWD official station histories >=30 QC years and observations since 2020",
                           "per_state_target":per_state,"states":states,
                           "candidates":len(selected),"published":len(published)},
              "dataset":"DWD CDC daily KL historical RSK (corrected rain) and SDK (sunshine)",
              "generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),
              "note":"DWD historical archive, original observations; not all stations measure sunshine."}
    (root/"index.json").write_text(json.dumps(metadata,ensure_ascii=False,separators=(",",":")),encoding="utf8")
    print("DWD KL HISTORICAL DAILY",len(published),"stations",flush=True)

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,default=Path("data/rekordlabor/calendar"))
    ap.add_argument("--station-index",type=Path,default=Path("station_snow_height_index.json"))
    ap.add_argument("--per-state",type=int,default=PER_STATE)
    args=ap.parse_args()
    if not 1<=args.per_state<=20:ap.error("--per-state must be 1..20")
    build(args.out,args.station_index,args.per_state)
