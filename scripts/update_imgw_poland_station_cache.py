#!/usr/bin/env python3
"""Build a resumable IMGW-PIB Poland daily temperature cache.

Official source: IMGW-PIB public measurement/observation archive,
``dane_meteorologiczne/dobowe/klimat``.  The k_d_t CSV inside every ZIP
contains daily temperature fields.  Historical layout:

* 1951-2000: annual ZIPs inside five-year directories
* 2001+: monthly ZIPs inside year directories

Every successfully parsed ZIP is persisted as a small shard.  A failed first
pass therefore never destroys previous progress.  The final baseline covers
all available TMAX/TMIN observations through ``current_year - 1``.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import math
import pickle
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import update_europe_station_records as core

BASE = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_meteorologiczne"
DAILY = f"{BASE}/dobowe/klimat"
STATION_CATALOG_URL = f"{BASE}/wykaz_stacji.csv"
HEADER_NAME = "k_d_t_nagłówek.csv"
HEADER_URL = DAILY + "/" + urllib.parse.quote(HEADER_NAME)
PUBLIC_URL = "https://danepubliczne.imgw.pl/"
SOURCE = "IMGW-PIB"
BASELINE_FORMAT_VERSION = 1
RESOURCE_FORMAT_VERSION = 1
START_YEAR = 1951


def log(msg: str) -> None:
    print(msg, flush=True)


def read_bytes(url: str, attempts: int = 4, timeout: int = 120) -> bytes:
    last = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "climate-dashboard-poland/1.0 (+GitHub Actions)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last = exc
            if attempt >= attempts:
                break
            wait = min(3 * attempt, 12)
            time.sleep(wait)
    raise RuntimeError(f"IMGW Download fehlgeschlagen: {url}: {last}")


def decode_polish(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1250", "iso-8859-2", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1250", errors="replace")


def norm(text: object) -> str:
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:5])
    counts = {d: sample.count(d) for d in (";", ",", "\t")}
    return max(counts, key=counts.get)


def parse_float(value: object) -> Optional[float]:
    s = str(value or "").strip().replace(" ", "")
    if not s:
        return None
    # decimal comma when value itself is not CSV-separated anymore
    s = s.replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def parse_coord(value: object, is_lat: bool) -> Optional[float]:
    x = parse_float(value)
    limit = 90 if is_lat else 180
    if x is not None and abs(x) <= limit:
        return x
    s = str(value or "").strip().replace(",", ".")
    nums = [float(v) for v in re.findall(r"[-+]?\d+(?:\.\d+)?", s)]
    if not nums:
        return None
    sign = -1 if any(c in s.upper() for c in ("S", "W")) or s.lstrip().startswith("-") else 1
    deg = abs(nums[0]); minute = nums[1] if len(nums) > 1 else 0; sec = nums[2] if len(nums) > 2 else 0
    val = sign * (deg + minute / 60 + sec / 3600)
    return val if abs(val) <= limit else None


def first_index(headers: List[str], predicates: Iterable) -> Optional[int]:
    nh = [norm(h) for h in headers]
    for pred in predicates:
        for i, h in enumerate(nh):
            if pred(h):
                return i
    return None


def load_temperature_schema() -> dict:
    text = decode_polish(read_bytes(HEADER_URL))
    delim = detect_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        raise RuntimeError("IMGW k_d_t Headerdatei ist leer.")
    headers = [x.strip() for x in rows[0] if str(x).strip()]
    if len(headers) < 7:
        # Some IMGW header files are one-column lists. Accept that form too.
        headers = [r[0].strip() for r in rows if r and r[0].strip()]
    n = [norm(x) for x in headers]
    def ix(words):
        for i, h in enumerate(n):
            if all(w in h for w in words):
                return i
        return None
    schema = {
        "headers": headers,
        "station": ix(["kod", "stacji"]),
        "name": ix(["nazwa", "stacji"]),
        "year": ix(["rok"]),
        "month": ix(["miesiac"]),
        "day": ix(["dzien"]),
        "tmax": next((i for i,h in enumerate(n) if "temperatur" in h and ("maks" in h or "tmax" in h) and "status" not in h), None),
        "tmin": next((i for i,h in enumerate(n) if "temperatur" in h and ("min" in h or "tmin" in h) and "status" not in h), None),
    }
    # Official k_d_t layout starts with station/name/year/month/day. Keep this
    # positional fallback only for those identifiers; temperature fields must
    # be discovered semantically to avoid silently swapping variables.
    for key, fallback in (("station",0),("name",1),("year",2),("month",3),("day",4)):
        if schema[key] is None and len(headers) > fallback:
            schema[key] = fallback
    if schema["tmax"] is None or schema["tmin"] is None:
        raise RuntimeError(f"IMGW k_d_t Header ohne erkennbare Tmax/Tmin-Spalten: {headers}")
    return schema


def parse_station_catalog() -> Dict[str, core.StationMeta]:
    text = decode_polish(read_bytes(STATION_CATALOG_URL))
    delim = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if not rows:
        raise RuntimeError("IMGW Stationsverzeichnis ist leer.")
    headers = [x.strip() for x in rows[0]]
    nh = [norm(x) for x in headers]

    def find_any(groups: List[Tuple[str, ...]]) -> Optional[int]:
        for group in groups:
            for i,h in enumerate(nh):
                if all(word in h for word in group):
                    return i
        return None

    i_code = find_any([("kod","stacji"), ("kod",), ("id",)])
    i_name = find_any([("nazwa","stacji"), ("nazwa",), ("station","name")])
    i_lat = find_any([("szerokosc",), ("latitude",), ("lat",)])
    i_lon = find_any([("dlugosc",), ("longitude",), ("lon",)])
    i_elev = find_any([("wysokosc",), ("elevation",), ("altitude",)])

    if i_code is None or i_name is None or i_lat is None or i_lon is None:
        raise RuntimeError(f"IMGW wykaz_stacji.csv ohne erkennbare Code/Name/Koordinaten-Spalten: {headers}")

    out: Dict[str, core.StationMeta] = {}
    for row in rows[1:]:
        if max(i_code, i_name, i_lat, i_lon) >= len(row):
            continue
        raw = row[i_code].strip().replace(".0", "")
        if not raw:
            continue
        lat = parse_coord(row[i_lat], True); lon = parse_coord(row[i_lon], False)
        if lat is None or lon is None or not (48.5 <= lat <= 55.5 and 13.5 <= lon <= 24.5):
            continue
        elev = parse_float(row[i_elev]) if i_elev is not None and i_elev < len(row) else None
        name = row[i_name].strip() or raw
        sid = f"IMGW:{raw}"
        out[sid] = core.StationMeta(
            sid, lat, lon, None if elev is None or elev < -100 else round(elev,1),
            name, "PL", "Polen", SOURCE,
            "IMGW-PIB tägliche Klimadaten k_d_t: veröffentlichte Tmax/Tmin-Werte; nichtnumerische/fehlende Werte werden verworfen.",
        )
    if not out:
        raise RuntimeError("Keine polnischen IMGW-Stationen mit Koordinaten aus wykaz_stacji.csv gelesen.")
    return out


def resource_urls(cutoff_year: int) -> List[dict]:
    out = []
    for y in range(START_YEAR, cutoff_year + 1):
        if y <= 2000:
            a = START_YEAR + ((y - START_YEAR)//5)*5; b = a + 4
            url = f"{DAILY}/{a}_{b}/{y}_k.zip"
            out.append({"year": y, "month": None, "url": url, "key": f"{y}"})
        else:
            for m in range(1,13):
                url = f"{DAILY}/{y}/{y}_{m:02d}_k.zip"
                out.append({"year": y, "month": m, "url": url, "key": f"{y}_{m:02d}"})
    return out


def current_resource_urls(year: int) -> List[dict]:
    index_url = f"{DAILY}/{year}/"
    html = decode_polish(read_bytes(index_url, attempts=3, timeout=90))
    months = sorted({int(x) for x in re.findall(rf"{year}_(\d{{2}})_k\.zip", html) if 1 <= int(x) <= 12})
    return [{"year":year,"month":m,"url":f"{DAILY}/{year}/{year}_{m:02d}_k.zip","key":f"{year}_{m:02d}"} for m in months]


def partial_state() -> dict:
    return core.mf_empty_partial_state()


def temp_tenths(value: object) -> Optional[int]:
    x = parse_float(value)
    if x is None or x < -70 or x > 60:
        return None
    return int(round(x * 10))


def parse_zip(data: bytes, schema: dict, *, cutoff_year: Optional[int] = None, exact_year: Optional[int] = None):
    partial: Dict[str,dict] = {}; current: Dict[str,dict] = {}; names: Dict[str,str] = {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise RuntimeError("ungültiges ZIP") from exc
    members = [n for n in zf.namelist() if Path(n).name.lower().startswith("k_d_t_") and n.lower().endswith(".csv")]
    if not members:
        raise RuntimeError(f"IMGW ZIP enthält keine k_d_t CSV: {zf.namelist()[:20]}")
    idxs = [schema[k] for k in ("station","name","year","month","day","tmax","tmin")]
    maxidx = max(i for i in idxs if i is not None)
    for member in members:
        text = decode_polish(zf.read(member)); delim = detect_delimiter(text)
        for row in csv.reader(io.StringIO(text), delimiter=delim):
            if len(row) <= maxidx:
                continue
            raw = row[schema["station"]].strip().replace(".0", "")
            if not raw:
                continue
            try:
                y=int(float(row[schema["year"]])); m=int(float(row[schema["month"]])); d=int(float(row[schema["day"]]))
                date=dt.date(y,m,d)
            except (ValueError,TypeError):
                continue
            if cutoff_year is not None and y > cutoff_year: continue
            if exact_year is not None and y != exact_year: continue
            sid=f"IMGW:{raw}"; names[sid]=row[schema["name"]].strip() if schema["name"] is not None else raw
            date_int=int(date.strftime("%Y%m%d")); mmdd=date.strftime("%m-%d")
            for field, element in (("tmax","TMAX"),("tmin","TMIN")):
                value=temp_tenths(row[schema[field]])
                if value is None: continue
                if exact_year is not None:
                    c=current.setdefault(sid,{"TMAX":{},"TMIN":{}})
                    old=c[element].get(mmdd)
                    if old is None or core.better(element,value,old[0]): c[element][mmdd]=(value,date_int)
                else:
                    s=partial.setdefault(sid,partial_state()); b=s[element]
                    b["abs"]=core.update_record(b.get("abs"),value,date_int,element)
                    b["cal"][mmdd]=core.update_record(b["cal"].get(mmdd),value,date_int,element)
                    b["start"]=date_int if b["start"] is None else min(b["start"],date_int)
                    b["end"]=date_int if b["end"] is None else max(b["end"],date_int)
                    b["year_set"].add(y)
    return partial,current,names


def resource_dir(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"imgw_poland_resources_through_{cutoff_year}_v{RESOURCE_FORMAT_VERSION}"


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"imgw_poland_daily_baseline_through_{cutoff_year}_v{BASELINE_FORMAT_VERSION}.pkl.gz"


def shard_path(cache_dir: Path, cutoff_year: int, key: str) -> Path:
    return resource_dir(cache_dir, cutoff_year) / f"{key}.pkl.gz"


def save_shard(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    with gzip.open(tmp,"wb",compresslevel=5) as h: pickle.dump(payload,h,pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def load_shard(path: Path, cutoff_year: int) -> Optional[dict]:
    if not path.exists() or path.stat().st_size == 0: return None
    try:
        with gzip.open(path,"rb") as h: p=pickle.load(h)
        if p.get("format_version") != RESOURCE_FORMAT_VERSION or p.get("cutoff_year") != cutoff_year: return None
        return p
    except Exception:
        return None


def merge_partial(target: dict, src: dict) -> None:
    core.merge_mf_partial(target, src)


def process_resource(res: dict, schema: dict, cache_dir: Path, cutoff_year: int, force: bool=False):
    path=shard_path(cache_dir,cutoff_year,res["key"])
    if not force:
        cached=load_shard(path,cutoff_year)
        if cached is not None: return cached,"cache",None
    try:
        data=read_bytes(res["url"],attempts=3,timeout=120)
        partial,_current,names=parse_zip(data,schema,cutoff_year=cutoff_year)
        payload={"format_version":RESOURCE_FORMAT_VERSION,"cutoff_year":cutoff_year,"key":res["key"],"url":res["url"],"partial":partial,"names":names}
        save_shard(path,payload)
        return payload,"download",None
    except Exception as exc:
        return None,"error",str(exc)


def build_baseline(current_year: int, cache_dir: Path, workers: int=8, force: bool=False) -> dict:
    cutoff=current_year-1; cache_dir.mkdir(parents=True,exist_ok=True)
    schema=load_temperature_schema(); stations_catalog=parse_station_catalog(); resources=resource_urls(cutoff)
    log(f"IMGW-PIB Stationsverzeichnis: {len(stations_catalog):,} Stationen mit Koordinaten.")
    log(f"Historischer Plan {START_YEAR}-{cutoff}: {len(resources):,} ZIP-Ressourcen; {workers} parallele Downloads; jede erfolgreiche ZIP wird einzeln gecacht.")
    partial={}; names={}; failures=[]; counts={"cache":0,"download":0,"error":0}; done=0
    with ThreadPoolExecutor(max_workers=max(1,workers)) as ex:
        futs={ex.submit(process_resource,r,schema,cache_dir,cutoff,force):r for r in resources}
        for fut in as_completed(futs):
            r=futs[fut]; payload,mode,error=fut.result(); done+=1; counts[mode]+=1
            if payload:
                merge_partial(partial,payload.get("partial",{})); names.update(payload.get("names",{}))
            else:
                failures.append({"key":r["key"],"url":r["url"],"error":error}); log(f"FEHLER IMGW {r['key']}: {error}")
            if done==1 or done%25==0 or done==len(resources):
                log(f"  IMGW historical: {done}/{len(resources)} ZIPs | Cache {counts['cache']} | neu {counts['download']} | fehlerhaft {counts['error']} | {len(partial):,} Stationscodes …")
    states_all=core.finalize_mf_states(partial)
    states={sid:st for sid,st in states_all.items() if sid in stations_catalog and (st["TMAX"]["abs"] is not None or st["TMIN"]["abs"] is not None)}
    stations={sid:stations_catalog[sid] for sid in states}
    unmatched=len(states_all)-len(states)
    complete=not failures
    status={"source":SOURCE,"cutoff_year":cutoff,"resource_count":len(resources),"available":len(resources)-len(failures),"missing":len(failures),"complete":complete,"station_count":len(states),"unmatched_station_codes":unmatched,"failures":failures}
    (cache_dir/f"imgw_poland_status_through_{cutoff}.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
    if complete:
        payload={"format_version":BASELINE_FORMAT_VERSION,"cutoff_year":cutoff,"states":states,"stations":stations,"resource_count":len(resources),"source":SOURCE}
        path=baseline_path(cache_dir,cutoff)
        with gzip.open(path,"wb",compresslevel=5) as h: pickle.dump(payload,h,pickle.HIGHEST_PROTOCOL)
        log(f"IMGW POLAND OK: {len(states):,} Stationsreihen mit TMAX/TMIN bis {cutoff} | {len(resources)} historische ZIP-Ressourcen.")
        return payload
    log(f"IMGW POLAND noch unvollständig: {len(failures)} von {len(resources)} ZIPs fehlen. Erfolgreiche Einzelcaches bleiben erhalten.")
    return {"format_version":BASELINE_FORMAT_VERSION,"cutoff_year":cutoff,"states":states,"stations":stations,"resource_count":len(resources),"complete":False}


def load_baseline(cache_dir: Path, cutoff_year: int) -> dict:
    path=baseline_path(cache_dir,cutoff_year)
    if not path.exists(): raise RuntimeError(f"IMGW-Polen-Cache fehlt: {path}")
    with gzip.open(path,"rb") as h: p=pickle.load(h)
    if p.get("format_version") != BASELINE_FORMAT_VERSION or p.get("cutoff_year") != cutoff_year or not p.get("states"):
        raise RuntimeError("IMGW-Polen-Cache ungültig oder leer.")
    return p


def parse_current_year(year: int, stations: Dict[str,core.StationMeta], workers: int=6):
    schema=load_temperature_schema(); resources=current_resource_urls(year)
    if not resources: raise RuntimeError(f"IMGW hat für {year} noch keine täglichen Klimadateien veröffentlicht.")
    out={}; failures=[]
    def one(r):
        data=read_bytes(r["url"],attempts=3,timeout=120); _p,c,_n=parse_zip(data,schema,exact_year=year); return c
    with ThreadPoolExecutor(max_workers=max(1,workers)) as ex:
        futs={ex.submit(one,r):r for r in resources}
        for fut in as_completed(futs):
            r=futs[fut]
            try:
                c=fut.result()
                for sid,state in c.items():
                    if sid not in stations: continue
                    dst=out.setdefault(sid,{"TMAX":{},"TMIN":{}})
                    for e in ("TMAX","TMIN"): dst[e].update(state.get(e,{}))
            except Exception as exc: failures.append((r["key"],str(exc)))
    if failures: log(f"WARNUNG IMGW current {year}: {len(failures)} Monatsdateien fehlgeschlagen: {failures[:5]}")
    latest=max(r["month"] for r in resources)
    log(f"IMGW {year}: {len(out):,} Stationen mit laufenden TMAX/TMIN-Daten aus {len(resources)} veröffentlichten Monats-ZIPs (bis Monat {latest:02d}).")
    return out, latest


def self_test() -> None:
    headers=["Kod stacji","Nazwa stacji","Rok","Miesiąc","Dzień","Temperatura maksymalna [°C]","Status pomiaru TMAX","Temperatura minimalna [°C]","Status pomiaru TMIN"]
    schema={"headers":headers,"station":0,"name":1,"year":2,"month":3,"day":4,"tmax":5,"tmin":7}
    csv_text='123456789,"TEST",2025,7,1,35.2,,18.1,\n123456789,"TEST",2025,7,2,36.4,,17.5,\n'
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z: z.writestr("k_d_t_2025.csv",csv_text.encode("cp1250"))
    p,c,n=parse_zip(buf.getvalue(),schema,cutoff_year=2025)
    sid="IMGW:123456789"
    assert p[sid]["TMAX"]["abs"][0]==364 and p[sid]["TMIN"]["abs"][0]==175
    assert n[sid]=="TEST" and not c
    urls=resource_urls(2001)
    assert urls[0]["url"].endswith("1951_1955/1951_k.zip") and urls[-1]["url"].endswith("2001/2001_12_k.zip")
    print("IMGW Poland self-test OK")


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--year",type=int,default=dt.datetime.now(dt.timezone.utc).year); ap.add_argument("--cache-dir",default=".cache/europe-stations"); ap.add_argument("--workers",type=int,default=8); ap.add_argument("--force",action="store_true"); ap.add_argument("--self-test",action="store_true"); args=ap.parse_args()
    if args.self_test: self_test(); return 0
    log("=== IMGW POLAND ONLY BASELINE ===")
    log("Quelle: IMGW-PIB tägliche Klimadaten; nur Polen, keine anderen Länder werden bearbeitet.")
    build_baseline(args.year,Path(args.cache_dir),workers=args.workers,force=args.force)
    return 0

if __name__=="__main__": raise SystemExit(main())
