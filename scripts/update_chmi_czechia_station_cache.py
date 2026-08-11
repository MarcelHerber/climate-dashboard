#!/usr/bin/env python3

from __future__ import annotations
import csv, gzip, io, json, math, os, pickle, re, time, urllib.error, urllib.parse, urllib.request
from array import array
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

SOURCE = "CHMI Open Data"
PUBLIC_URL = "https://opendata.chmi.cz/meteorology/climate/"
COUNTRY = "Tschechien"
COUNTRY_CODE = "CZ"
FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
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


def historical_limits(cutoff_year):
    # Verified Czech national bounds are used through 2025.  For later
    # historical cutoffs, keep a loose emergency envelope so a genuine
    # future national record is not discarded by an obsolete record limit.
    if int(cutoff_year) <= 2025:
        return 40.4, -42.2
    return 45.0, -50.0

def baseline_path(cache_dir, cutoff_year):
    return Path(cache_dir) / f"chmi_czechia_daily_baseline_through_{int(cutoff_year)}_v{FORMAT_VERSION}.pkl.gz"

def parts_dir(cache_dir, cutoff_year):
    return Path(cache_dir) / f"chmi_czechia_station_parts_v{FORMAT_VERSION}_{int(cutoff_year)}"

def load_csv_element(url, element, cutoff_year=2025):
    raw = decode(http_bytes(url))
    rdr = csv.reader(io.StringIO(raw), delimiter=",")
    rows = iter(rdr)
    header = next(rows, [])
    idx = {str(c).strip():i for i,c in enumerate(header)}

    # CHMI uses slightly different field names in its products:
    # historical CSV: TIMEFUNC + VALUE
    # recent JSON:    VTYPE    + VAL
    # This historical loader therefore accepts both VALUE and VAL.
    value_col = "VALUE" if "VALUE" in idx else ("VAL" if "VAL" in idx else None)

    needed = ["ELEMENT", "DT", "QUALITY"]
    if any(x not in idx for x in needed) or value_col is None:
        raise RuntimeError(
            f"{url}: Header unvollständig/unerwartet: {header} "
            f"(erwartet ELEMENT, DT, QUALITY und VALUE oder VAL)"
        )

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
            x = float(row[idx[value_col]])
            if not math.isfinite(x): continue
            max_limit, min_limit = historical_limits(cutoff_year)
            if element == "TMA" and not (-50.0 <= x <= max_limit):
                invalid += 1; continue
            if element == "TMI" and not (min_limit <= x <= 45.0):
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
import shutil

def build_station(wsi, meta, tma_url, tmi_url, cutoff_year):
    tx,qx,ix = load_csv_element(tma_url,"TMA",cutoff_year)
    tn,qn,inn = load_csv_element(tmi_url,"TMI",cutoff_year)
    return pack_station(wsi,meta,tx,tn,qx,qn,ix,inn)

def valid_baseline(path, cutoff_year):
    path = Path(path)
    if not path.exists():
        return False
    try:
        obj = load_gz_pickle(path)
    except Exception:
        return False
    return (
        isinstance(obj, dict)
        and obj.get("complete") is True
        and int(obj.get("cutoff_year", -1)) == int(cutoff_year)
        and int(obj.get("station_count", 0)) > 0
    )

def load_baseline(cache_dir, cutoff_year):
    path = baseline_path(cache_dir, cutoff_year)
    if not valid_baseline(path, cutoff_year):
        raise RuntimeError(f"CHMI Czechia Baseline fehlt/unvollständig: {path}")
    return load_gz_pickle(path)

def build_baseline(cache_dir, cutoff_year, *, force=False, workers=8):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    output = baseline_path(cache_dir, cutoff_year)
    parts = parts_dir(cache_dir, cutoff_year)

    if force:
        output.unlink(missing_ok=True)
        if parts.exists():
            shutil.rmtree(parts)

    if not force and valid_baseline(output, cutoff_year):
        log(f"Verwende vorhandenen CHMI-Czechia-Baselinecache: {output}")
        return output

    parts.mkdir(parents=True, exist_ok=True)
    by_meta, latest = load_historical_metadata()
    tma, tmi = historical_inventory()
    stations = sorted(set(tma) & set(tmi) & set(by_meta))
    if not stations:
        raise RuntimeError("CHMI historische TMA+TMI-Inventarisierung ist leer.")

    log(f"CHMI historische TMA+TMI-Stationen: {len(stations)}")
    existing = {
        p.name[:-7] for p in parts.glob("*.pkl.gz")
    }
    todo = [s for s in stations if s.replace("/", "_") not in existing]
    log(f"Cache-Teile vorhanden: {len(existing)} | neu zu laden: {len(todo)}")

    workers = max(1, min(int(workers), 16))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(build_station, s, latest[s], tma[s], tmi[s], cutoff_year): s
            for s in todo
        }
        done = 0
        for fut in as_completed(futs):
            s = futs[fut]
            part = fut.result()
            safe = s.replace("/", "_")
            save_gz_pickle(parts / f"{safe}.pkl.gz", part)
            done += 1
            if done % 10 == 0 or done == len(todo):
                log(f"CHMI: {len(existing)+done}/{len(stations)} Stationsreihen gecacht")

    data = {}
    qrej = Counter(); invalid = Counter(); total_days = 0; first = None; last = None
    for s in stations:
        p = parts / f"{s.replace('/', '_')}.pkl.gz"
        if not p.exists():
            raise RuntimeError(f"CHMI Stations-Teilcache fehlt: {p}")
        part = load_gz_pickle(p)
        data[s] = part
        total_days += int(part["station_days"])
        if part.get("start_date") and (first is None or part["start_date"] < first): first = part["start_date"]
        if part.get("end_date") and (last is None or part["end_date"] > last): last = part["end_date"]
        for el,d in part.get("quality_rejected",{}).items():
            for k,v in d.items(): qrej[(el,k)] += v
        for k,v in part.get("invalid_rejected",{}).items(): invalid[k] += v

    out = {
        "source": SOURCE, "public_url": PUBLIC_URL, "country": COUNTRY,
        "country_code": COUNTRY_CODE, "format_version": FORMAT_VERSION,
        "cutoff_year": int(cutoff_year), "complete": True,
        "station_count": len(data), "inventory_count": len(stations),
        "station_days": total_days, "start_date": first, "end_date": last,
        "stations": data,
        "quality_policy": "Only QUALITY=0 (Good) is accepted for TMA/TMI.",
        "quality_rejected": dict(qrej), "invalid_rejected": dict(invalid),
    }
    save_gz_pickle(output, out)
    max_limit, min_limit = historical_limits(cutoff_year)
    log("=== CHMI CZECHIA BASELINE SUMMARY ===")
    log(f"Stationsreihen: {len(data):,}")
    log(f"Stationstage: {total_days:,}")
    log(f"Datenzeitraum: {first} bis {last}")
    log(f"QUALITY verworfen: {dict(qrej)}")
    log(f"QC-Grenzen: TMAX <= {max_limit:.1f} C | TMIN >= {min_limit:.1f} C")
    log(f"QC verworfen: {dict(invalid)}")
    log(f"Output: {output}")
    log("CHMI Czechia Baseline OK.")
    return output

def self_test():
    assert historical_limits(2025) == (40.4, -42.2)
    assert historical_limits(2026) == (45.0, -50.0)
    assert quality_ok("0.0") and not quality_ok("3.0")
    assert baseline_path(Path("x"), 2025).name == "chmi_czechia_daily_baseline_through_2025_v1.pkl.gz"
    print("CHMI Czechia historical cache self-test OK")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    ap.add_argument("--cutoff-year", type=int, default=datetime.now(timezone.utc).year - 1)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test(); return 0
    build_baseline(Path(args.cache_dir), args.cutoff_year, force=args.force, workers=args.workers)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
