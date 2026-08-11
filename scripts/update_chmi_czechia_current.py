#!/usr/bin/env python3

from __future__ import annotations
import csv, gzip, io, json, math, os, pickle, re, time, urllib.error, urllib.parse, urllib.request
from array import array
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

SOURCE = "CHMI Open Data"
HIST_TEMP_INDEX = "https://opendata.chmi.cz/meteorology/climate/historical_csv/data/daily/temperature/"
META1_URL = "https://opendata.chmi.cz/meteorology/climate/historical/metadata/meta1.json"
RECENT_DAILY_INDEX = "https://opendata.chmi.cz/meteorology/climate/recent/data/daily/"
RECENT_META_INDEX = "https://opendata.chmi.cz/meteorology/climate/recent/metadata/"
UA = "climate-dashboard-chmi-czechia/1.0"
TIMEOUT = 120
TRIES = 5
CZ_BBOX = (12.0, 48.4, 19.0, 51.2)
MISSING_I16 = -32768

def log(msg=""):
    print(msg, flush=True)

def http_bytes(url):
    last = None
    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
                if not raw:
                    raise RuntimeError("Leere HTTP-Antwort")
                return raw
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            last = exc
            retryable = not isinstance(exc, urllib.error.HTTPError) or exc.code in {408,429,500,502,503,504}
            if attempt >= TRIES or not retryable:
                raise
            time.sleep(min(30, attempt * 3))
    raise RuntimeError(str(last))

def decode(raw):
    for enc in ("utf-8-sig","utf-8","cp1250","latin-1"):
        try: return raw.decode(enc)
        except UnicodeDecodeError: pass
    return raw.decode("utf-8", errors="replace")

def hrefs(text):
    return re.findall(r'href=["\']([^"\']+)["\']', text, flags=re.I)

def parse_dc(obj):
    node = obj.get("data", {})
    if isinstance(node, dict):
        node = node.get("data", node)
    header = node.get("header")
    values = node.get("values")
    cols = [x.strip() for x in header.split(",")] if isinstance(header, str) else [str(x).strip() for x in header]
    return cols, values

def in_cz(lon, lat):
    return CZ_BBOX[0] <= lon <= CZ_BBOX[2] and CZ_BBOX[1] <= lat <= CZ_BBOX[3]

def load_historical_metadata():
    obj = json.loads(decode(http_bytes(META1_URL)))
    cols, rows = parse_dc(obj)
    idx = {c:i for i,c in enumerate(cols)}
    by = defaultdict(list)
    for row in rows:
        try:
            wsi = str(row[idx["WSI"]]); lon=float(row[idx["GEOGR1"]]); lat=float(row[idx["GEOGR2"]])
        except Exception:
            continue
        if not in_cz(lon,lat): continue
        by[wsi].append({
            "station_id":wsi, "name":str(row[idx["FULL_NAME"]]), "lon":lon, "lat":lat,
            "elevation":row[idx["ELEVATION"]], "begin":str(row[idx["BEGIN_DATE"]])[:10],
            "end":str(row[idx["END_DATE"]])[:10],
        })
    latest = {wsi:max(v, key=lambda x:x["begin"]) for wsi,v in by.items()}
    return by, latest

def historical_inventory():
    text = decode(http_bytes(HIST_TEMP_INDEX))
    tma, tmi = {}, {}
    for href in hrefs(text):
        name = urllib.parse.unquote(href).rsplit("/",1)[-1]
        m = re.fullmatch(r"dly-(.+)-(TMA|TMI)\.csv", name, flags=re.I)
        if not m: continue
        wsi, el = m.groups()
        url = urllib.parse.urljoin(HIST_TEMP_INDEX, href)
        (tma if el.upper()=="TMA" else tmi)[wsi] = url
    return tma, tmi

def quality_ok(v):
    try: return float(v) == 0.0
    except Exception: return False

def tenths(v):
    return int(round(float(v)*10.0))

def untenths(v):
    return None if v == MISSING_I16 else v/10.0

def load_csv_element(url, element, cutoff_year=2025):
    raw = decode(http_bytes(url))
    rdr = csv.reader(io.StringIO(raw), delimiter=",")
    rows = iter(rdr)
    header = next(rows, [])
    idx = {str(c).strip():i for i,c in enumerate(header)}
    needed = ["ELEMENT","DT","VAL","QUALITY"]
    if any(x not in idx for x in needed):
        raise RuntimeError(f"{url}: Header unvollständig: {header}")
    vals = {}
    qrej = Counter()
    invalid = 0
    for row in rows:
        try:
            if str(row[idx["ELEMENT"]]).strip() != element: continue
            ds = str(row[idx["DT"]])[:10]
            d = date.fromisoformat(ds)
            if d.year > cutoff_year: continue
            q = str(row[idx["QUALITY"]]).strip()
            if not quality_ok(q):
                qrej[q or "(leer)"] += 1
                continue
            x = float(row[idx["VAL"]])
            if not math.isfinite(x): continue
            # Official national bounds through 2025.
            if element == "TMA" and not (-50.0 <= x <= 40.4):
                invalid += 1; continue
            if element == "TMI" and not (-42.2 <= x <= 45.0):
                invalid += 1; continue
            if ds in vals:
                vals[ds] = max(vals[ds], x) if element=="TMA" else min(vals[ds], x)
            else:
                vals[ds] = x
        except Exception:
            continue
    return vals, qrej, invalid

def pack_station(wsi, meta, tmax, tmin, qrej_tma, qrej_tmi, invalid_tma, invalid_tmi):
    dates = sorted(set(tmax) | set(tmin))
    ords = array("i"); tx = array("h"); tn = array("h")
    bad_order = 0
    for ds in dates:
        a=tmax.get(ds); b=tmin.get(ds)
        if a is not None and b is not None and b > a:
            bad_order += 1
            continue
        ords.append(date.fromisoformat(ds).toordinal())
        tx.append(tenths(a) if a is not None else MISSING_I16)
        tn.append(tenths(b) if b is not None else MISSING_I16)
    return {
        "station_id":wsi, "meta":meta, "ordinals":ords, "tmax_tenths":tx, "tmin_tenths":tn,
        "start_date":date.fromordinal(ords[0]).isoformat() if ords else None,
        "end_date":date.fromordinal(ords[-1]).isoformat() if ords else None,
        "station_days":len(ords),
        "quality_rejected":{"TMA":dict(qrej_tma),"TMI":dict(qrej_tmi)},
        "invalid_rejected":{"TMA":invalid_tma,"TMI":invalid_tmi,"TMIN_GT_TMAX":bad_order},
    }

def save_gz_pickle(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=5) as f: pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)

def load_gz_pickle(path):
    with gzip.open(path, "rb") as f: return pickle.load(f)

def latest_recent_meta():
    text = decode(http_bytes(RECENT_META_INDEX))
    names = []
    for h in hrefs(text):
        n = urllib.parse.unquote(h).rsplit("/",1)[-1]
        if re.fullmatch(r"meta1-\d{8}\.json", n): names.append(n)
    if not names: return {}
    name=max(names)
    obj=json.loads(decode(http_bytes(urllib.parse.urljoin(RECENT_META_INDEX,name))))
    cols,rows=parse_dc(obj); idx={c:i for i,c in enumerate(cols)}
    out={}
    for row in rows:
        try:
            wsi=str(row[idx["WSI"]]); lon=float(row[idx["GEOGR1"]]); lat=float(row[idx["GEOGR2"]])
        except Exception: continue
        if not in_cz(lon,lat): continue
        out[wsi]={"station_id":wsi,"name":str(row[idx["FULL_NAME"]]),"lon":lon,"lat":lat,"elevation":row[idx["ELEVATION"]]}
    return out

def index_month_urls(year, month):
    base = RECENT_DAILY_INDEX if month == datetime.now(timezone.utc).month else urllib.parse.urljoin(RECENT_DAILY_INDEX, f"{month:02d}/")
    text = decode(http_bytes(base))
    pat = re.compile(rf"dly-(.+)-{year}{month:02d}\.json$", re.I)
    out={}
    for h in hrefs(text):
        name=urllib.parse.unquote(h).rsplit("/",1)[-1]
        m=pat.fullmatch(name)
        if m: out[m.group(1)] = urllib.parse.urljoin(base,h)
    # Current month might already only exist at root; closed month directories are authoritative.
    return out

def parse_current_file(url, year):
    obj=json.loads(decode(http_bytes(url))); cols,rows=parse_dc(obj); idx={c:i for i,c in enumerate(cols)}
    out=defaultdict(dict); qrej=Counter(); invalid=Counter()
    for row in rows:
        try:
            el=str(row[idx["ELEMENT"]])
            if el not in {"TMA","TMI"}: continue
            ds=str(row[idx["DT"]])[:10]
            if date.fromisoformat(ds).year != year: continue
            q=str(row[idx["QUALITY"]]).strip()
            if not quality_ok(q):
                qrej[(el,q or "(leer)")]+=1; continue
            x=float(row[idx["VAL"]])
            if not math.isfinite(x): continue
            # Loose emergency QC for current data so a real new national record is not hard-blocked.
            if not (-50.0 <= x <= 45.0):
                invalid[el]+=1; continue
            old=out[ds].get(el)
            if old is None: out[ds][el]=x
            elif el=="TMA": out[ds][el]=max(old,x)
            else: out[ds][el]=min(old,x)
        except Exception:
            continue
    return out,qrej,invalid

import argparse

CACHE_DIR=Path(".cache/europe-stations")
BASELINE=CACHE_DIR/"chmi_czechia_daily_baseline_through_2025_v1.pkl.gz"
OUTPUT=CACHE_DIR/"chmi_czechia_current_2026_v1.pkl.gz"

def baseline_calendar_extremes(baseline):
    out={}
    for sid,st in baseline["stations"].items():
        mx={}; mn={}
        for ordv,tx,tn in zip(st["ordinals"],st["tmax_tenths"],st["tmin_tenths"]):
            d=date.fromordinal(ordv); key=f"{d.month:02d}-{d.day:02d}"
            if tx != MISSING_I16:
                x=tx/10.0
                if key not in mx or x>mx[key]: mx[key]=x
            if tn != MISSING_I16:
                x=tn/10.0
                if key not in mn or x<mn[key]: mn[key]=x
        out[sid]={"tmax":mx,"tmin":mn}
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--year",type=int,default=datetime.now(timezone.utc).year); ap.add_argument("--workers",type=int,default=12)
    args=ap.parse_args(); year=args.year
    if not BASELINE.exists():
        raise RuntimeError(f"Baseline fehlt: {BASELINE}")
    baseline=load_gz_pickle(BASELINE)
    if not baseline.get("complete"): raise RuntimeError("Baseline ist nicht vollständig.")
    hist_ids=set(baseline["stations"])
    current_meta=latest_recent_meta()
    merged_meta={sid:st["meta"] for sid,st in baseline["stations"].items()}
    merged_meta.update(current_meta)
    months=range(1,datetime.now(timezone.utc).month+1) if year==datetime.now(timezone.utc).year else range(1,13)
    jobs=[]
    for month in months:
        urls=index_month_urls(year,month)
        for sid,url in urls.items():
            if sid in merged_meta: jobs.append((month,sid,url))
        log(f"CHMI {year}-{month:02d}: {len(urls)} Dateien im Index")
    station_rows=defaultdict(dict); qrej=Counter(); invalid=Counter(); errors=[]
    workers=max(1,min(args.workers,20))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs={pool.submit(parse_current_file,url,year):(month,sid) for month,sid,url in jobs}
        done=0
        for fut in as_completed(futs):
            month,sid=futs[fut]; done+=1
            try:
                rows,qr,iv=fut.result()
                for ds,vals in rows.items(): station_rows[sid][ds]=vals
                qrej.update(qr); invalid.update(iv)
            except Exception as exc: errors.append((sid,month,str(exc)))
            if done%100==0 or done==len(futs):
                log(f"Current: {done}/{len(futs)} Dateien | Fehler {len(errors)}")
    cal=baseline_calendar_extremes(baseline)
    stations={}; total_days=0; first=None; last=None; record_events=0
    for sid,rows in station_rows.items():
        both_dates=sorted(ds for ds,v in rows.items() if "TMA" in v or "TMI" in v)
        if not both_dates: continue
        ords=array("i"); tx=array("h"); tn=array("h")
        for ds in both_dates:
            v=rows[ds]; a=v.get("TMA"); b=v.get("TMI")
            if a is not None and b is not None and b>a:
                invalid["TMIN_GT_TMAX"]+=1; continue
            d=date.fromisoformat(ds); ords.append(d.toordinal())
            tx.append(tenths(a) if a is not None else MISSING_I16); tn.append(tenths(b) if b is not None else MISSING_I16)
            key=f"{d.month:02d}-{d.day:02d}"
            old=cal.get(sid,{})
            if a is not None and key in old.get("tmax",{}) and a>old["tmax"][key]: record_events+=1
            if b is not None and key in old.get("tmin",{}) and b<old["tmin"][key]: record_events+=1
        if not ords: continue
        st={
            "station_id":sid,"meta":merged_meta.get(sid,{}),"ordinals":ords,"tmax_tenths":tx,"tmin_tenths":tn,
            "start_date":date.fromordinal(ords[0]).isoformat(),"end_date":date.fromordinal(ords[-1]).isoformat(),
            "station_days":len(ords),"has_historical_baseline":sid in hist_ids,
        }
        stations[sid]=st; total_days+=len(ords)
        if first is None or st["start_date"]<first: first=st["start_date"]
        if last is None or st["end_date"]>last: last=st["end_date"]
    out={
        "source":SOURCE,"format_version":1,"year":year,"complete":True,
        "station_count":len(stations),"station_days":total_days,"start_date":first,"end_date":last,
        "stations":stations,"new_historical_daily_record_events":record_events,
        "quality_policy":"Only QUALITY=0 (Good) is accepted; 1/2/3/4/5 are excluded.",
        "quality_rejected":dict(qrej),"invalid_rejected":dict(invalid),"errors":errors,
    }
    save_gz_pickle(OUTPUT,out)
    log("=== CHMI CZECHIA CURRENT SUMMARY ===")
    log(f"Stationsreihen mit {year}-Daten: {len(stations):,}")
    log(f"Stationstage: {total_days:,}")
    log(f"Datenzeitraum: {first} bis {last}")
    log(f"Neue historische Tagesrekord-Ereignisse: {record_events:,}")
    log(f"QUALITY verworfen: {dict(qrej)}")
    log(f"QC verworfen: {dict(invalid)}")
    log(f"Download-/Parse-Fehler: {len(errors)}")
    log(f"Output: {OUTPUT}")
    log("CHMI Czechia current OK.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
