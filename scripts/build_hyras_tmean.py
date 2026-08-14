#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import gzip
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests
import xarray as xr

DAILY_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_mean"
MONTHLY_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/monthly/hyras_de/air_temperature_mean"
CLIM_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/air_temperature_mean"
USER_AGENT = "climate-dashboard-hyras-tmean/1.0 (+GitHub Actions; DWD Open Data)"
MONTH_ABBR = {1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"}
MONTH_DE = {1:"Januar",2:"Februar",3:"März",4:"April",5:"Mai",6:"Juni",7:"Juli",8:"August",9:"September",10:"Oktober",11:"November",12:"Dezember"}
MISSING_I16 = -32768
SCALE = 100


def get(url: str, timeout: int = 90) -> requests.Response:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r


def listing(url: str) -> str:
    return get(url + "/", 60).text


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Download: {url}", flush=True)
    with requests.get(url, stream=True, timeout=240, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    print(f"  -> {target.name}: {target.stat().st_size/1024/1024:.1f} MB", flush=True)


def latest_version_file(text: str, pattern: str) -> str:
    matches = []
    for m in re.finditer(pattern, text):
        matches.append((int(m.group("major")), int(m.group("minor")), m.group("filename")))
    if not matches:
        raise RuntimeError(f"Kein passender HYRAS-Dateiname gefunden: {pattern}")
    matches.sort()
    return matches[-1][2]


def latest_daily_filename(year: int) -> str:
    text = listing(DAILY_BASE)
    pat = rf'href="(?P<filename>tas_hyras_1_{year}_v(?P<major>\d+)-(?P<minor>\d+)_de\.nc)"'
    return latest_version_file(text, pat)


def latest_monthly_filename(year: int, text: str | None = None) -> str:
    text = text if text is not None else listing(MONTHLY_BASE)
    pat = rf'href="(?P<filename>tas_hyras_1_{year}_v(?P<major>\d+)-(?P<minor>\d+)_de_monmean\.nc)"'
    return latest_version_file(text, pat)


def latest_clim_filename(month: int) -> str:
    text = listing(CLIM_BASE)
    abbr = MONTH_ABBR[month]
    pat = rf'href="(?P<filename>tas_hyras_1_1991_2020_v(?P<major>\d+)-(?P<minor>\d+)_de_{abbr}\.nc)"'
    return latest_version_file(text, pat)


def pick_var(ds: xr.Dataset) -> xr.DataArray:
    for name in ("tas", "temperature", "air_temperature", "tmean"):
        if name in ds.data_vars and ds[name].ndim >= 2:
            return ds[name]
    for name, da in ds.data_vars.items():
        if da.ndim >= 2:
            print(f"Hinweis: verwende Temperaturvariable {name}", flush=True)
            return da
    raise RuntimeError(f"Keine HYRAS-Temperaturvariable gefunden: {list(ds.data_vars)}")


def time_dim(da: xr.DataArray) -> str:
    for d in da.dims:
        if d.lower() == "time":
            return d
    for d in da.dims:
        c = da.coords.get(d)
        if c is not None and np.issubdtype(c.dtype, np.datetime64):
            return d
    raise RuntimeError("Keine Zeitdimension gefunden")


def spatial_dims(da: xr.DataArray) -> tuple[str, str]:
    td = None
    try:
        td = time_dim(da)
    except Exception:
        pass
    dims = [d for d in da.dims if d != td]
    if len(dims) < 2:
        raise RuntimeError(f"Keine 2D-Raumdimensionen: {da.dims}")
    y = next((d for d in dims if d.lower() in {"y","lat","latitude","rlat"}), dims[-2])
    x = next((d for d in dims if d.lower() in {"x","lon","longitude","rlon"}), dims[-1])
    return y, x


def to_celsius(da: xr.DataArray) -> xr.DataArray:
    units = str(da.attrs.get("units", "")).strip().lower()
    if units in {"k", "kelvin", "degree_kelvin", "degrees_kelvin"} or "kelvin" in units:
        return da - 273.15
    # Defensive fallback for files with incomplete metadata.
    try:
        probe = float(da.isel({d:0 for d in da.dims[:-2]}).mean(skipna=True).values)
        if np.isfinite(probe) and probe > 100:
            return da - 273.15
    except Exception:
        pass
    return da


def squeeze_2d(da: xr.DataArray) -> xr.DataArray:
    da = da.squeeze(drop=True)
    while da.ndim > 2:
        da = da.isel({da.dims[0]: 0})
    if da.ndim != 2:
        raise RuntimeError(f"Kein 2D-Raster: {da.dims} {da.shape}")
    return da


def normalize_array(da: xr.DataArray, factor: int = 1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    da = squeeze_2d(da)
    y_name, x_name = spatial_dims(da)
    sampled = da.isel({y_name: slice(None, None, factor), x_name: slice(None, None, factor)}).transpose(y_name, x_name)
    arr = np.asarray(sampled.values, dtype=np.float32)
    x = np.asarray(sampled[x_name].values, dtype=float)
    y = np.asarray(sampled[y_name].values, dtype=float)
    arr[~np.isfinite(arr)] = np.nan
    if len(x) > 1 and x[0] > x[-1]:
        x = x[::-1]; arr = arr[:, ::-1]
    if len(y) > 1 and y[0] < y[-1]:
        y = y[::-1]; arr = arr[::-1, :]
    return arr, x, y


def quantize(arr: np.ndarray) -> np.ndarray:
    out = np.full(arr.shape, MISSING_I16, dtype="<i2")
    valid = np.isfinite(arr)
    q = np.rint(arr[valid] * SCALE)
    q = np.clip(q, -32767, 32767).astype(np.int16)
    out[valid] = q
    return out


def write_i16_gz(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    q = quantize(arr)
    with gzip.open(path, "wb", compresslevel=6) as f:
        f.write(q.tobytes(order="C"))


def latest_complete_month(da: xr.DataArray) -> tuple[int, int, str]:
    td = time_dim(da)
    dates = da[td].values.astype("datetime64[D]")
    if not len(dates):
        raise RuntimeError("Aktuelle HYRAS-Tmean-Datei ist leer")
    last = str(dates[-1])
    counts: dict[tuple[int,int], set[str]] = {}
    for raw in dates:
        iso = str(raw)
        yy, mm, _ = map(int, iso.split("-"))
        counts.setdefault((yy,mm), set()).add(iso)
    complete = [(yy,mm) for (yy,mm), days in counts.items() if len(days) >= calendar.monthrange(yy,mm)[1]]
    if not complete:
        raise RuntimeError("Kein vollständiger Monat in der aktuellen HYRAS-Tmean-Datei")
    yy, mm = max(complete)
    return yy, mm, last


def mean_range(da: xr.DataArray, start: str, end: str) -> xr.DataArray:
    td = time_dim(da)
    sel = da.where((da[td] >= np.datetime64(start)) & (da[td] <= np.datetime64(end)), drop=True)
    if sel.sizes.get(td, 0) == 0:
        raise RuntimeError(f"Keine Tmean-Tage für {start} bis {end}")
    return squeeze_2d(sel.mean(td, skipna=True))


def month_end(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year,month)[1]:02d}"


def current_season(dt: datetime) -> tuple[str, str, str]:
    if 3 <= dt.month <= 5: return "spring", "Frühling", f"{dt.year}-03-01"
    if 6 <= dt.month <= 8: return "summer", "Sommer", f"{dt.year}-06-01"
    if 9 <= dt.month <= 11: return "autumn", "Herbst", f"{dt.year}-09-01"
    if dt.month == 12: return "winter", "Winter", f"{dt.year}-12-01"
    return "winter", "Winter", f"{dt.year-1}-12-01"


def weighted_reference(months: list[int], work: Path, cache: dict[int, xr.DataArray], weights: list[int] | None = None) -> xr.DataArray:
    refs = []
    ws = weights or [calendar.monthrange(2001, m)[1] for m in months]  # only relative day weights matter here
    for m in months:
        if m not in cache:
            filename = latest_clim_filename(m)
            target = work / "climatology" / filename
            if not target.exists(): download(f"{CLIM_BASE}/{filename}", target)
            with xr.open_dataset(target, decode_times=True) as ds:
                cache[m] = squeeze_2d(to_celsius(pick_var(ds))).load()
        refs.append(cache[m])
    base = refs[0] * float(ws[0])
    total = float(ws[0])
    for ref, w in zip(refs[1:], ws[1:]):
        base, aligned = xr.align(base, ref, join="exact")
        base = base + aligned * float(w)
        total += float(w)
    return squeeze_2d(base / total)


def add_period(periods: list[dict[str,Any]], out_root: Path, *, key: str, label: str, period_type: str,
               start_date: str, end_date: str, current: xr.DataArray, reference: xr.DataArray | None,
               live: bool = False) -> None:
    cur, x, y = normalize_array(current, 1)
    cur_rel = f"current/{key}_absolute.i16.gz"
    write_i16_gz(out_root / cur_rel, cur)
    item: dict[str,Any] = {
        "key": key, "label": label, "period_type": period_type,
        "start_date": start_date, "end_date": end_date, "live": bool(live),
        "absolute": cur_rel, "reference_exact": reference is not None,
        "stats": {"current_mean_c": round(float(np.nanmean(cur)), 2)},
    }
    if reference is not None:
        ref, rx, ry = normalize_array(reference, 1)
        if ref.shape != cur.shape or not np.allclose(rx,x) or not np.allclose(ry,y):
            raise RuntimeError(f"Referenzraster passt nicht zu {key}")
        anom = cur - ref
        anom_rel = f"current/{key}_anomaly.i16.gz"
        write_i16_gz(out_root / anom_rel, anom)
        item["anomaly"] = anom_rel
        item["stats"].update({
            "reference_mean_c": round(float(np.nanmean(ref)), 2),
            "anomaly_mean_k": round(float(np.nanmean(anom)), 2),
        })
    else:
        item["reference_note"] = "Für den laufenden Teilzeitraum wird in Stufe 1 zunächst die absolute HYRAS-Tmean-Karte veröffentlicht; die tagesgenaue 1991–2020-Referenz folgt separat."
    periods.append(item)


def build_current(*, out_root: Path, work: Path, year: int) -> dict[str,Any]:
    filename = latest_daily_filename(year)
    target = work / filename
    if not target.exists(): download(f"{DAILY_BASE}/{filename}", target)
    with xr.open_dataset(target, decode_times=True) as ds:
        source = to_celsius(pick_var(ds))
        latest_year, latest_month, data_through = latest_complete_month(source)
        if latest_year != year:
            raise RuntimeError(f"Letzter vollständiger Tmean-Monat ist {latest_year}-{latest_month:02d}, nicht {year}")
        # Current year only; loaded once because several periods reuse it.
        daily = source.load()

    periods: list[dict[str,Any]] = []
    clim_cache: dict[int,xr.DataArray] = {}
    complete_months = list(range(1, latest_month + 1))

    for m in complete_months:
        start = f"{year}-{m:02d}-01"; end = month_end(year,m)
        cur = mean_range(daily,start,end)
        ref = weighted_reference([m],work,clim_cache,[calendar.monthrange(year,m)[1]])
        add_period(periods,out_root,key=f"{year}_{m:02d}",label=f"{MONTH_DE[m]} {year}",period_type="month",start_date=start,end_date=end,current=cur,reference=ref)

    season_defs = [("spring","Frühling",[3,4,5]),("summer","Sommer",[6,7,8]),("autumn","Herbst",[9,10,11])]
    for sid,label,months in season_defs:
        if all(m in complete_months for m in months):
            start=f"{year}-{months[0]:02d}-01"; end=month_end(year,months[-1])
            cur=mean_range(daily,start,end)
            weights=[calendar.monthrange(year,m)[1] for m in months]
            ref=weighted_reference(months,work,clim_cache,weights)
            add_period(periods,out_root,key=f"{year}_{sid}",label=f"{label} {year}",period_type="season",start_date=start,end_date=end,current=cur,reference=ref)

    # Complete-month YTD comparison.
    if complete_months:
        start=f"{year}-01-01"; end=month_end(year,complete_months[-1])
        cur=mean_range(daily,start,end)
        weights=[calendar.monthrange(year,m)[1] for m in complete_months]
        ref=weighted_reference(complete_months,work,clim_cache,weights)
        add_period(periods,out_root,key=f"{year}_ytd_complete",label=f"Jahr bisher {year} · vollständige Monate",period_type="ytd_complete",start_date=start,end_date=end,current=cur,reference=ref)

    through_dt=datetime.strptime(data_through,"%Y-%m-%d")
    live_month_start=f"{year}-{through_dt.month:02d}-01"
    add_period(periods,out_root,key=f"{year}_{through_dt.month:02d}_live",label=f"{MONTH_DE[through_dt.month]} aktuell {year}",period_type="month_live",start_date=live_month_start,end_date=data_through,current=mean_range(daily,live_month_start,data_through),reference=None,live=True)

    sid,slabel,sstart=current_season(through_dt)
    # In Jan/Feb the previous December is not in the current-year file. The full winter-live
    # map is therefore added in a later stage; do not publish a misleading partial winter.
    if not (through_dt.month in (1,2)):
        add_period(periods,out_root,key=f"{year}_{sid}_live",label=f"{slabel} aktuell {year}",period_type="season_live",start_date=sstart,end_date=data_through,current=mean_range(daily,sstart,data_through),reference=None,live=True)

    ystart=f"{year}-01-01"
    add_period(periods,out_root,key=f"{year}_ytd_live",label=f"Jahr aktuell {year}",period_type="ytd_live",start_date=ystart,end_date=data_through,current=mean_range(daily,ystart,data_through),reference=None,live=True)

    # Grid metadata from first period/current day mean.
    sample, x, y = normalize_array(mean_range(daily,f"{year}-01-01",f"{year}-01-01"),1)
    return {
        "year": year, "data_through": data_through, "latest_complete_month": latest_month,
        "source_file": filename, "width": int(sample.shape[1]), "height": int(sample.shape[0]),
        "periods": periods,
    }


def build_history(*, out_root: Path, work: Path, current_year: int, factor: int, force: bool) -> dict[str,Any]:
    hist_root = out_root / f"history_{factor}km"
    manifest_path = hist_root / "manifest.json"
    target_first, target_last = 1951, current_year - 1
    expected_years = list(range(target_first,target_last+1))
    if not force and manifest_path.exists():
        try:
            existing=json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("years") == expected_years and all((hist_root/f"month_{m:02d}.i16.gz").exists() for m in range(1,13)):
                print(f"Tmean-Historie {target_first}–{target_last} auf {factor}-km-Raster bereits vollständig – Wiederverwendung.",flush=True)
                return existing
        except Exception:
            pass

    print(f"Baue Tmean-Historie {target_first}–{target_last} auf ca. {factor}-km-Analyseraster …",flush=True)
    text=listing(MONTHLY_BASE)
    files={y:latest_monthly_filename(y,text) for y in expected_years}
    planes: dict[int,np.ndarray] = {}
    width=height=None
    x_ref=y_ref=None

    for pos,y in enumerate(expected_years,1):
        filename=files[y]; target=work/"monthly"/filename
        if not target.exists(): download(f"{MONTHLY_BASE}/{filename}",target)
        with xr.open_dataset(target,decode_times=True) as ds:
            da=to_celsius(pick_var(ds)); td=time_dim(da)
            dates=[str(v)[:10] for v in da[td].values.astype("datetime64[D]")]
            by_month={int(iso[5:7]):i for i,iso in enumerate(dates) if int(iso[:4])==y}
            if len(by_month)<12: raise RuntimeError(f"{filename} enthält nur {len(by_month)} Monatswerte")
            for m in range(1,13):
                arr,x,ycoords=normalize_array(da.isel({td:by_month[m]}),factor)
                if width is None:
                    height,width=arr.shape; x_ref=x; y_ref=ycoords
                    planes={mm:np.full((len(expected_years),height,width),MISSING_I16,dtype="<i2") for mm in range(1,13)}
                elif arr.shape!=(height,width) or not np.allclose(x,x_ref) or not np.allclose(ycoords,y_ref):
                    raise RuntimeError(f"Tmean-Rastergeometrie änderte sich in {filename}")
                planes[m][pos-1]=quantize(arr)
        try: target.unlink()
        except OSError: pass
        if pos==1 or pos%5==0 or pos==len(expected_years):
            print(f"Tmean historical: {pos}/{len(expected_years)} Jahre verarbeitet ({y})",flush=True)

    hist_root.mkdir(parents=True,exist_ok=True)
    for m in range(1,13):
        path=hist_root/f"month_{m:02d}.i16.gz"
        with gzip.open(path,"wb",compresslevel=6) as f: f.write(planes[m].tobytes(order="C"))
        print(f"  {path.name}: {path.stat().st_size/1024/1024:.1f} MB",flush=True)

    manifest={
        "schema_version":1,"parameter":"tmean","label":"2-m-Temperaturmittel","unit":"°C",
        "first_year":target_first,"last_year":target_last,"years":expected_years,
        "resolution_km":factor,"width":int(width),"height":int(height),
        "value_scale":SCALE,"missing_value":MISSING_I16,"dtype":"int16","endianness":"little",
        "file_pattern":f"tmean/history_{factor}km/month_{{month:02d}}.i16.gz",
        "aggregation":"Monatsmittel; Jahreszeiten und Jahre werden tagesgewichtet aus Monatsmitteln kombiniert.",
        "reference":"1991-2020",
    }
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Tmean-Historie bereit: {target_first}–{target_last} · {width}×{height} · {factor} km",flush=True)
    return manifest


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-root",default="hyras_output")
    parser.add_argument("--work",default="hyras_tmean_work")
    parser.add_argument("--year",type=int,default=datetime.now(timezone.utc).year)
    parser.add_argument("--history-factor",type=int,default=5)
    parser.add_argument("--force-history",action="store_true")
    args=parser.parse_args()

    data_root=Path(args.data_root); out_root=data_root/"tmean"; work=Path(args.work)
    out_root.mkdir(parents=True,exist_ok=True); work.mkdir(parents=True,exist_ok=True)

    print("=== HYRAS TMEAN · STUFE 1 ===",flush=True)
    print("Aktuelle Tagesmittel + vollständige Monatsabweichungen + historische Monatsbasis",flush=True)
    history=build_history(out_root=out_root,work=work,current_year=args.year,factor=max(2,args.history_factor),force=args.force_history)
    current=build_current(out_root=out_root,work=work,year=args.year)

    index={
        "schema_version":1,"parameter":"tmean","label":"2-m-Temperaturmittel","unit":"°C",
        "reference":"1991-2020","data_through":current["data_through"],"year":args.year,
        "latest_complete_month":current["latest_complete_month"],"grid_1km":{"width":current["width"],"height":current["height"]},
        "current_source_file":current["source_file"],"periods":current["periods"],
        "history_manifest":f"history_{max(2,args.history_factor)}km/manifest.json",
        "history_first_year":history["first_year"],"history_last_year":history["last_year"],
        "history_resolution_km":history["resolution_km"],
        "note":"Stufe 1: Tmean-Datenbasis. Vollständige Monate besitzen exakte HYRAS-1991–2020-Monatsreferenzen; laufende Teilzeiträume werden zunächst absolut veröffentlicht. Frontend-Integration folgt im nächsten Schritt.",
    }
    (out_root/"index.json").write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding="utf-8")
    print("=== SUMMARY ===",flush=True)
    print(f"Tmean Datenstand: {current['data_through']}",flush=True)
    print(f"Letzter vollständiger Monat: {MONTH_DE[current['latest_complete_month']]} {args.year}",flush=True)
    print(f"Historie: {history['first_year']}–{history['last_year']} ({history['resolution_km']} km)",flush=True)
    print(f"Aktuelle Perioden: {len(current['periods'])}",flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
