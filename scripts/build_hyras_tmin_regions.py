#!/usr/bin/env python3
from __future__ import annotations

import calendar
import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import requests
import xarray as xr

USER_AGENT = "climate-dashboard-hyras-tmin/1.0"
DAILY_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_min"

REGION_NAMES = [
    "Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg",
    "Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen",
    "Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt",
    "Schleswig-Holstein","Thüringen","Deutschland",
]

MASK_CANDIDATES = [
    ("hyras_region_masks_v1.npz", "hyras_region_masks_v1.json"),
    ("region_masks_v1.npz", "region_masks_v1.json"),
    ("tmean/regions/region_masks_v1.npz", "tmean/regions/region_masks_v1.json"),
    ("tmax/regions/region_masks_v1.npz", "tmax/regions/region_masks_v1.json"),
]

def get(url: str, timeout: int = 120) -> requests.Response:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response

def listing(url: str) -> str:
    return get(url + "/").text

def download(url: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target
    with requests.get(url, stream=True, timeout=180, headers={"User-Agent": USER_AGENT}) as response:
        response.raise_for_status()
        with target.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return target

def latest_daily_files(html: str) -> dict[int, str]:
    pattern = re.compile(r'href="(?P<filename>tasmin_hyras_1_(?P<year>\d{4})_v\d+-\d+_de\.nc)"')
    result = {}
    for m in pattern.finditer(html):
        result[int(m.group("year"))] = m.group("filename")
    return result

def pick_var(ds: xr.Dataset) -> xr.DataArray:
    for candidate in ("tasmin", "tas", "air_temperature_min", "temperature"):
        if candidate in ds.data_vars:
            return ds[candidate]
    if len(ds.data_vars) != 1:
        raise RuntimeError(f"Kein eindeutiges Tmin-Datenfeld gefunden: {list(ds.data_vars)}")
    return next(iter(ds.data_vars.values()))

def to_celsius(da: xr.DataArray) -> xr.DataArray:
    units = str(da.attrs.get("units", "")).lower()
    if units == "k" or "kelvin" in units:
        return da - 273.15
    return da

def prepare_da(ds: xr.Dataset):
    da = to_celsius(pick_var(ds))
    td = next((d for d in da.dims if "time" in d.lower()), da.dims[0])
    ydim = next((d for d in da.dims if d.lower() in {"y","lat","latitude","rlat"}), None)
    xdim = next((d for d in da.dims if d.lower() in {"x","lon","longitude","rlon"}), None)
    if ydim is None or xdim is None:
        tail = [d for d in da.dims if d != td]
        if len(tail) != 2:
            raise RuntimeError(f"Unerwartete Dimensionsfolge: {da.dims}")
        ydim, xdim = tail
    da = da.transpose(td, ydim, xdim)
    x = np.asarray(da[xdim].values)
    y = np.asarray(da[ydim].values)
    return da, td, x, y

def discover_masks(data_root: Path):
    for npz_name, json_name in MASK_CANDIDATES:
        npz_path = data_root / npz_name
        json_path = data_root / json_name
        if npz_path.exists() and json_path.exists():
            return npz_path, json_path
    raise RuntimeError(
        "Keine vorbereiteten HYRAS-Regionsmasken gefunden. "
        "Bitte zuerst die bestehende Tmean/Tmax-Basis laufen lassen, damit der Maskencache vorhanden ist."
    )

def load_masks(data_root: Path, shape):
    npz_path, _ = discover_masks(data_root)
    npz = np.load(npz_path)
    masks = {}
    for name in REGION_NAMES:
        key = name.replace("ü","ue").replace("ä","ae").replace("ö","oe").replace("ß","ss")
        key = key.replace("-","_").replace(" ","_")
        if key not in npz:
            raise RuntimeError(f"Maskencache enthält Region nicht: {name}")
        arr = np.asarray(npz[key]).astype(bool)
        if arr.shape != shape:
            raise RuntimeError(f"Maskenform passt nicht für {name}: {arr.shape} vs {shape}")
        masks[name] = arr
    return masks

def daily_region_means(arr3d, masks):
    values = {name: [] for name in masks}
    for i in range(arr3d.shape[0]):
        plane = arr3d[i]
        for name, mask in masks.items():
            data = plane[mask]
            good = data[np.isfinite(data)]
            values[name].append(None if good.size == 0 else float(good.mean()))
    return values

def mmdd_index(times):
    out = []
    for value in times:
        d = np.datetime_as_string(value, unit="D")
        out.append(d[5:10])
    return out

def build_daily_climate(files, work: Path, masks, force: bool):
    cache_path = work / "tmin_daily_climate_1991_2020.json"
    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    sums = {name: {} for name in REGION_NAMES}
    counts = {name: {} for name in REGION_NAMES}
    for year in range(1991, 2021):
        fname = files.get(year)
        if not fname:
            continue
        path = download(f"{DAILY_BASE}/{fname}", work / "daily" / fname)
        with xr.open_dataset(path, decode_times=True) as ds:
            da, td, _, _ = prepare_da(ds)
            arr = np.asarray(da.values, dtype=np.float32)
            means = daily_region_means(arr, masks)
            keys = mmdd_index(np.asarray(da[td].values))
        for region in REGION_NAMES:
            for key, value in zip(keys, means[region]):
                if key == "02-29" or value is None:
                    continue
                sums[region][key] = sums[region].get(key, 0.0) + float(value)
                counts[region][key] = counts[region].get(key, 0) + 1
        print(f"Regionale Tmin-Klimakurve {year}: {fname}", flush=True)
    climate = {
        region: {
            key: round(sums[region][key] / counts[region][key], 3)
            for key in sorted(sums[region]) if counts[region].get(key, 0) > 0
        }
        for region in REGION_NAMES
    }
    payload = {"regions": climate}
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload

def build_daily_records(files, work: Path, masks, force: bool, last_year: int):
    cache_path = work / "tmin_daily_records_1951_2025.json"
    if cache_path.exists() and not force:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if int(payload.get("last_year", 0)) == last_year:
            return payload
    out = {name: {} for name in REGION_NAMES}
    for year in range(1951, last_year + 1):
        fname = files.get(year)
        if not fname:
            continue
        path = download(f"{DAILY_BASE}/{fname}", work / "daily" / fname)
        with xr.open_dataset(path, decode_times=True) as ds:
            da, td, _, _ = prepare_da(ds)
            arr = np.asarray(da.values, dtype=np.float32)
            means = daily_region_means(arr, masks)
            keys = mmdd_index(np.asarray(da[td].values))
        for region in REGION_NAMES:
            for key, value in zip(keys, means[region]):
                if key == "02-29" or value is None:
                    continue
                item = out[region].setdefault(key, {"max": None, "min": None, "max_years": [], "min_years": []})
                v = float(value)
                if item["max"] is None or v > item["max"]:
                    item["max"] = round(v, 3)
                    item["max_years"] = [year]
                elif abs(v - item["max"]) < 1e-9:
                    item["max_years"].append(year)
                if item["min"] is None or v < item["min"]:
                    item["min"] = round(v, 3)
                    item["min_years"] = [year]
                elif abs(v - item["min"]) < 1e-9:
                    item["min_years"].append(year)
        print(f"Regionale Tmin-Rekorde {year}: {fname}", flush=True)
    payload = {"first_year": 1951, "last_year": last_year, "regions": out}
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload

def build_periods(dates: list[str]):
    last = date.fromisoformat(dates[-1])
    periods = []
    full_last_month = last.month - 1
    full_last_year = last.year
    if full_last_month == 0:
        full_last_month = 12
        full_last_year -= 1
    periods.append({"key": "year", "label": f"Jahr {last.year}", "start_date": f"{last.year}-01-01", "end_date": last.isoformat()})
    for month in range(1, full_last_month + 1):
        end_day = calendar.monthrange(full_last_year, month)[1]
        periods.append({
            "key": f"month_{month:02d}",
            "label": calendar.month_name[month],
            "start_date": f"{full_last_year}-{month:02d}-01",
            "end_date": f"{full_last_year}-{month:02d}-{end_day:02d}",
        })
    periods.append({
        "key": f"month_{last.month:02d}_running",
        "label": f"{calendar.month_name[last.month]} aktuell",
        "start_date": f"{last.year}-{last.month:02d}-01",
        "end_date": last.isoformat(),
    })
    if last.month >= 3:
        periods.append({"key": "spring", "label": "Frühling", "start_date": f"{last.year}-03-01", "end_date": min(last, date(last.year, 5, 31)).isoformat()})
    if last.month >= 6:
        periods.append({"key": "summer", "label": "Sommer", "start_date": f"{last.year}-06-01", "end_date": min(last, date(last.year, 8, 31)).isoformat()})
    if last.month >= 9:
        periods.append({"key": "autumn", "label": "Herbst", "start_date": f"{last.year}-09-01", "end_date": min(last, date(last.year, 11, 30)).isoformat()})
    return periods

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="/tmp/hyras-data")
    parser.add_argument("--work", default="/tmp/hyras-tmin-work")
    parser.add_argument("--force-history-summary", action="store_true")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    out_root = data_root / "tmin" / "regions"
    out_root.mkdir(parents=True, exist_ok=True)

    html = listing(DAILY_BASE)
    files = latest_daily_files(html)
    current_year = max(files)
    current_name = files[current_year]
    current_path = download(f"{DAILY_BASE}/{current_name}", work / "daily" / current_name)

    with xr.open_dataset(current_path, decode_times=True) as ds:
        da, td, x, y = prepare_da(ds)
        arr = np.asarray(da.values, dtype=np.float32)
        dates = [np.datetime_as_string(v, unit="D") for v in np.asarray(da[td].values)]

    masks = load_masks(data_root, (len(y), len(x)))
    current_regions = daily_region_means(arr, masks)
    climate = build_daily_climate(files, work, masks, args.force_history_summary)
    records = build_daily_records(files, work, masks, args.force_history_summary, current_year - 1)

    current_file = f"current_{current_year}.json"
    (out_root / current_file).write_text(json.dumps({"parameter": "tmin", "year": current_year, "dates": dates, "regions": current_regions}, ensure_ascii=False), encoding="utf-8")
    climate_file = "climate_1991_2020.json"
    (out_root / climate_file).write_text(json.dumps({"parameter": "tmin", "reference": "1991-2020", "regions": climate["regions"]}, ensure_ascii=False), encoding="utf-8")
    records_file = "daily_records.json"
    (out_root / records_file).write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    index = {
        "schema_version": 1,
        "parameter": "tmin",
        "year": current_year,
        "data_through": dates[-1],
        "regions": REGION_NAMES,
        "current_file": current_file,
        "climate_file": climate_file,
        "records_file": records_file,
        "records_first_year": 1951,
        "records_last_year": current_year - 1,
        "method_note": "HYRAS Tmin Gebietsmittel. Tagesklimakurve 1991–2020 und Tagesrekorde 1951–Vorjahr.",
        "periods": build_periods(dates),
    }
    (out_root / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Regionale Tmin-Kurven fertig.", flush=True)
    print("Datenstand:", dates[-1], flush=True)
    print("Gebiete:", len(REGION_NAMES), flush=True)
    print("Perioden:", len(index["periods"]), flush=True)

if __name__ == "__main__":
    main()
