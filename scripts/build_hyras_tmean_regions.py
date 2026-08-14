#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.path import Path as MplPath
import numpy as np
from PIL import Image
from pyproj import CRS, Transformer
import requests
import xarray as xr

DAILY_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_mean"
STATES_URL = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
USER_AGENT = "climate-dashboard-hyras-tmean-regions/1.0 (+GitHub Actions; DWD Open Data)"
REFERENCE_START = 1991
REFERENCE_END = 2020
METHOD_VERSION = 1
MISSING_I16 = -32768
SCALE = 100
EXPECTED_STATES = [
    "Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen",
    "Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz",
    "Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen"
]
MONTH_DE = {
    1:"Januar",2:"Februar",3:"März",4:"April",5:"Mai",6:"Juni",
    7:"Juli",8:"August",9:"September",10:"Oktober",11:"November",12:"Dezember"
}

def get(url: str, timeout: int = 120) -> requests.Response:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r

def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Download: {url}", flush=True)
    with requests.get(url, stream=True, timeout=360, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    print(f"  -> {target.name}: {target.stat().st_size / 1024 / 1024:.1f} MB", flush=True)

def daily_listing() -> str:
    return get(DAILY_BASE + "/", 90).text

def latest_daily_files(text: str) -> dict[int, str]:
    pat = re.compile(r'href="(?P<filename>tas_hyras_1_(?P<year>\d{4})_v(?P<major>\d+)-(?P<minor>\d+)_de\.nc)"')
    best: dict[int, tuple[int, int, str]] = {}
    for m in pat.finditer(text):
        year = int(m.group("year"))
        item = (int(m.group("major")), int(m.group("minor")), m.group("filename"))
        if year not in best or item[:2] > best[year][:2]:
            best[year] = item
    return {year: item[2] for year, item in best.items()}

def pick_var(ds: xr.Dataset) -> xr.DataArray:
    for name in ("tas", "temperature", "air_temperature", "tmean"):
        if name in ds.data_vars and ds[name].ndim >= 2:
            return ds[name]
    for da in ds.data_vars.values():
        if da.ndim >= 2:
            return da
    raise RuntimeError(f"Keine Temperaturvariable gefunden: {list(ds.data_vars)}")

def time_dim(da: xr.DataArray) -> str:
    for d in da.dims:
        if d.lower() == "time":
            return d
    for d in da.dims:
        c = da.coords.get(d)
        if c is not None and np.issubdtype(c.dtype, np.datetime64):
            return d
    raise RuntimeError("Keine Zeitdimension gefunden.")

def spatial_dims(da: xr.DataArray) -> tuple[str, str]:
    td = time_dim(da)
    dims = [d for d in da.dims if d != td]
    if len(dims) != 2:
        raise RuntimeError(f"Unerwartete HYRAS-Dimensionen: {da.dims}")
    y = next((d for d in dims if d.lower() in {"y","lat","latitude","rlat"}), dims[0])
    x = next((d for d in dims if d.lower() in {"x","lon","longitude","rlon"}), dims[1])
    if x == y:
        raise RuntimeError(f"Raumdimensionen konnten nicht bestimmt werden: {da.dims}")
    return y, x

def to_celsius(da: xr.DataArray) -> xr.DataArray:
    units = str(da.attrs.get("units", "")).lower().strip()
    if units == "k" or "kelvin" in units:
        return da - 273.15
    return da

def prepare_da(ds: xr.Dataset) -> tuple[xr.DataArray, str, str, str, np.ndarray, np.ndarray]:
    da = to_celsius(pick_var(ds)).squeeze(drop=True)
    td = time_dim(da)
    ydim, xdim = spatial_dims(da)
    da = da.transpose(td, ydim, xdim)
    x = np.asarray(da[xdim].values, dtype=np.float64)
    y = np.asarray(da[ydim].values, dtype=np.float64)
    if x.ndim != 1 or y.ndim != 1:
        raise RuntimeError("HYRAS x/y-Koordinaten sind nicht eindimensional.")
    return da, td, ydim, xdim, x, y

def grid_signature(x: np.ndarray, y: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(np.asarray(x, dtype="<f8").tobytes())
    h.update(np.asarray(y, dtype="<f8").tobytes())
    return h.hexdigest()[:20]

def load_states(work: Path) -> dict[str, Any]:
    target = work / "bundeslaender.geojson"
    if not target.exists():
        target.write_bytes(get(STATES_URL, 90).content)
    data = json.loads(target.read_text(encoding="utf-8"))
    features = {}
    for feature in data.get("features", []):
        name = str(feature.get("properties", {}).get("name", "")).strip()
        if name:
            features[name] = feature
    missing = [name for name in EXPECTED_STATES if name not in features]
    if missing:
        raise RuntimeError("Bundesländer fehlen im GeoJSON: " + ", ".join(missing))
    return features

def polygon_mask_on_grid(polygon: list, x: np.ndarray, y: np.ndarray, transformer: Transformer) -> np.ndarray:
    result = np.zeros((len(y), len(x)), dtype=bool)
    if not polygon:
        return result
    rings_xy: list[np.ndarray] = []
    for ring in polygon:
        if len(ring) < 3:
            continue
        lon = np.asarray([p[0] for p in ring], dtype=float)
        lat = np.asarray([p[1] for p in ring], dtype=float)
        px, py = transformer.transform(lon, lat)
        rings_xy.append(np.column_stack([px, py]))
    if not rings_xy:
        return result
    outer = rings_xy[0]
    xmin, xmax = float(np.nanmin(outer[:,0])), float(np.nanmax(outer[:,0]))
    ymin, ymax = float(np.nanmin(outer[:,1])), float(np.nanmax(outer[:,1]))
    xi = np.where((x >= xmin) & (x <= xmax))[0]
    yi = np.where((y >= ymin) & (y <= ymax))[0]
    if not len(xi) or not len(yi):
        return result
    xx, yy = np.meshgrid(x[xi], y[yi])
    points = np.column_stack([xx.ravel(), yy.ravel()])
    inside = MplPath(outer).contains_points(points, radius=0.01).reshape(len(yi), len(xi))
    for hole in rings_xy[1:]:
        inside &= ~MplPath(hole).contains_points(points, radius=0.01).reshape(len(yi), len(xi))
    result[np.ix_(yi, xi)] |= inside
    return result

def geometry_mask(geometry: dict[str, Any], x: np.ndarray, y: np.ndarray, transformer: Transformer) -> np.ndarray:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    out = np.zeros((len(y), len(x)), dtype=bool)
    if gtype == "Polygon":
        out |= polygon_mask_on_grid(coords, x, y, transformer)
    elif gtype == "MultiPolygon":
        for polygon in coords:
            out |= polygon_mask_on_grid(polygon, x, y, transformer)
    else:
        raise RuntimeError(f"Nicht unterstützte Geometrie: {gtype}")
    return out

def build_masks(features: dict[str, Any], x: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray]:
    transformer = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(3035), always_xy=True)
    state_masks: dict[str, np.ndarray] = {}
    germany = np.zeros((len(y), len(x)), dtype=bool)
    for name in EXPECTED_STATES:
        mask = geometry_mask(features[name]["geometry"], x, y, transformer)
        count = int(mask.sum())
        if count < 5:
            raise RuntimeError(f"Zu wenige HYRAS-Zellen für {name}: {count}")
        state_masks[name] = mask
        germany |= mask
        print(f"Maske {name}: {count:,} Zellen", flush=True)
    print(f"Maske Deutschland: {int(germany.sum()):,} Zellen", flush=True)
    return {"Deutschland": germany, **state_masks}

def extract_region_daily(ds: xr.Dataset, masks: dict[str, np.ndarray], expected_x=None, expected_y=None, chunk_days: int = 16):
    da, td, _, _, x, y = prepare_da(ds)
    if expected_x is not None and (x.shape != expected_x.shape or not np.allclose(x, expected_x)):
        raise RuntimeError("Historisches HYRAS-x-Gitter weicht vom aktuellen Gitter ab.")
    if expected_y is not None and (y.shape != expected_y.shape or not np.allclose(y, expected_y)):
        raise RuntimeError("Historisches HYRAS-y-Gitter weicht vom aktuellen Gitter ab.")
    dates = [str(v) for v in da[td].values.astype("datetime64[D]")]
    out = {name: [None] * len(dates) for name in masks}
    mask_indices = {name: np.flatnonzero(mask.ravel()) for name, mask in masks.items()}
    for start in range(0, len(dates), chunk_days):
        end = min(len(dates), start + chunk_days)
        block = np.asarray(da.isel({td: slice(start, end)}).values, dtype=np.float32)
        flat = block.reshape(block.shape[0], -1)
        for name, idx in mask_indices.items():
            vals = flat[:, idx]
            with np.errstate(invalid="ignore"):
                means = np.nanmean(vals, axis=1)
            for j, value in enumerate(means):
                out[name][start + j] = round(float(value), 3) if np.isfinite(value) else None
    return dates, out, x, y

def current_payload(current_nc: Path, masks: dict[str, np.ndarray]):
    with xr.open_dataset(current_nc, decode_times=True) as ds:
        dates, values, x, y = extract_region_daily(ds, masks)
    return {
        "schema_version": 1, "method_version": METHOD_VERSION, "parameter": "tmean", "unit": "°C",
        "year": int(dates[-1][:4]) if dates else None, "first_date": dates[0] if dates else None,
        "data_through": dates[-1] if dates else None, "dates": dates, "regions": values,
    }, x, y

def build_climate(files: dict[int, str], work: Path, masks: dict[str, np.ndarray], x: np.ndarray, y: np.ndarray):
    sums = {name: {} for name in masks}
    counts = {name: {} for name in masks}
    climate_work = work / "regional_climate_years"
    climate_work.mkdir(parents=True, exist_ok=True)
    for year in range(REFERENCE_START, REFERENCE_END + 1):
        filename = files.get(year)
        if not filename:
            raise RuntimeError(f"Kein HYRAS-Tmean-Tagesfile für {year} gefunden.")
        target = climate_work / filename
        if not target.exists():
            download(f"{DAILY_BASE}/{filename}", target)
        print(f"Regionale Klimakurve {year}: {filename}", flush=True)
        with xr.open_dataset(target, decode_times=True) as ds:
            dates, vals, _, _ = extract_region_daily(ds, masks, x, y)
        for name in masks:
            for date, value in zip(dates, vals[name]):
                if value is None:
                    continue
                mmdd = date[5:10]
                sums[name][mmdd] = sums[name].get(mmdd, 0.0) + float(value)
                counts[name][mmdd] = counts[name].get(mmdd, 0) + 1
        target.unlink(missing_ok=True)
    climate_regions, sample_counts = {}, {}
    for name in masks:
        climate_regions[name], sample_counts[name] = {}, {}
        for mmdd in sorted(sums[name]):
            n = counts[name].get(mmdd, 0)
            if n:
                climate_regions[name][mmdd] = round(sums[name][mmdd] / n, 3)
                sample_counts[name][mmdd] = n
    return {
        "schema_version": 1, "method_version": METHOD_VERSION, "parameter": "tmean", "unit": "°C",
        "reference": f"{REFERENCE_START}-{REFERENCE_END}", "grid_signature": grid_signature(x, y),
        "regions": climate_regions, "sample_counts": sample_counts,
        "note": "Tägliche HYRAS-Tmean-Gebietsmittel: zuerst räumliches Gebietsmittel je Tag und Jahr, danach Kalendertagsmittel 1991–2020.",
    }

def climate_reusable(path: Path, x: np.ndarray, y: np.ndarray) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (
            data.get("schema_version") == 1 and data.get("method_version") == METHOD_VERSION
            and data.get("reference") == f"{REFERENCE_START}-{REFERENCE_END}"
            and data.get("grid_signature") == grid_signature(x, y)
            and all(name in data.get("regions", {}) for name in ["Deutschland", *EXPECTED_STATES])
        )
    except Exception:
        return False

def date_periods(year: int, data_through: str):
    end = datetime.strptime(data_through, "%Y-%m-%d").date()
    periods = [{
        "key": "year_current", "label": f"Jahr aktuell {year}",
        "start_date": f"{year}-01-01", "end_date": data_through, "map_key": f"{year}_ytd_live",
    }]
    for sid, label, sm, sd, em, ed in [
        ("spring", "Frühling", 3, 1, 5, 31),
        ("summer", "Sommer", 6, 1, 8, 31),
        ("autumn", "Herbst", 9, 1, 11, 30),
    ]:
        start = datetime(year, sm, sd).date()
        finish = datetime(year, em, ed).date()
        if end >= start:
            clipped = min(end, finish)
            live = clipped < finish
            periods.append({
                "key": sid, "label": f"{label}{' aktuell' if live else ''} {year}",
                "start_date": start.isoformat(), "end_date": clipped.isoformat(),
                "map_key": f"{year}_{sid}_live" if live else f"{year}_{sid}",
            })
    for month in range(1, end.month + 1):
        last = calendar.monthrange(year, month)[1]
        month_end = datetime(year, month, last).date()
        clipped = min(end, month_end)
        live = clipped < month_end
        periods.append({
            "key": f"month_{month:02d}", "label": f"{MONTH_DE[month]}{' aktuell' if live else ''} {year}",
            "start_date": f"{year}-{month:02d}-01", "end_date": clipped.isoformat(),
            "map_key": f"{year}_{month:02d}_live" if live else f"{year}_{month:02d}",
        })
    return periods

def load_i16(path: Path, width: int, height: int) -> np.ndarray:
    with gzip.open(path, "rb") as f:
        raw = f.read()
    arr = np.frombuffer(raw, dtype="<i2")
    if arr.size != width * height:
        raise RuntimeError(f"Rastergröße passt nicht: {path} ({arr.size} statt {width*height})")
    arr = arr.reshape(height, width).astype(np.float32)
    arr[arr == MISSING_I16] = np.nan
    arr /= SCALE
    return arr

def get_colormap(mode: str):
    if mode == "anomaly":
        colors = ["#313695","#4575b4","#74add1","#abd9e9","#f7f7f7","#fdae61","#f46d43","#d73027","#a50026"]
        return LinearSegmentedColormap.from_list("hyras_tmean_anomaly", colors), -6.0, 6.0, "K"
    colors = ["#313695","#4575b4","#74add1","#abd9e9","#e0f3f8","#ffffbf","#fee090","#fdae61","#f46d43","#d73027","#a50026"]
    return LinearSegmentedColormap.from_list("hyras_tmean_absolute", colors), -15.0, 35.0, "°C"

def render_map(arr, boundary_path, output, title, subtitle, mode):
    cmap, vmin, vmax, unit = get_colormap(mode)
    fig = plt.figure(figsize=(7.4, 9.4), dpi=150)
    ax = fig.add_axes([0.055, 0.105, 0.89, 0.80])
    im = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_axis_off()
    if boundary_path and boundary_path.exists():
        overlay = np.asarray(Image.open(boundary_path).convert("RGBA"))
        if overlay.shape[:2] == arr.shape:
            ax.imshow(overlay, interpolation="nearest")
    fig.suptitle(title, fontsize=15, fontweight="bold", y=0.965)
    fig.text(0.5, 0.925, subtitle, ha="center", va="center", fontsize=9)
    cax = fig.add_axes([0.14, 0.055, 0.72, 0.025])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal")
    cb.set_label(unit, fontsize=9)
    cb.ax.tick_params(labelsize=8)
    fig.text(0.055, 0.018, "Quelle: Deutscher Wetterdienst · HYRAS-DE-TAS · Referenz 1991–2020", fontsize=7, color="#555555")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, facecolor="white", bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)

def build_download_maps(data_root: Path, tmean_index: dict[str, Any]):
    troot = data_root / "tmean"
    width, height = int(tmean_index["grid_1km"]["width"]), int(tmean_index["grid_1km"]["height"])
    boundary_path = None
    pidx_path = data_root / "hyras_index.json"
    if pidx_path.exists():
        try:
            pidx = json.loads(pidx_path.read_text(encoding="utf-8"))
            rel = pidx.get("interactive", {}).get("boundary_overlay_1km")
            if rel:
                boundary_path = data_root / rel
        except Exception:
            pass
    out_dir = troot / "download_maps"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for period in tmean_index.get("periods", []):
        key = period["key"]
        item = {"label": period.get("label", key)}
        for mode, field in (("absolute", "absolute"), ("anomaly", "anomaly")):
            rel = period.get(field)
            if not rel:
                continue
            source = troot / rel
            if not source.exists():
                continue
            arr = load_i16(source, width, height)
            target_rel = f"download_maps/{key}_{mode}.png"
            subtitle_kind = "Abweichung zum Mittel 1991–2020" if mode == "anomaly" else "2-m-Temperaturmittel"
            render_map(arr, boundary_path, troot / target_rel, f"HYRAS Tmean · {period.get('label', key)}",
                       f"{subtitle_kind} · {period.get('start_date','')} bis {period.get('end_date','')}", mode)
            item[mode] = target_rel
        if len(item) > 1:
            result[key] = item
    return {"schema_version": 1, "parameter": "tmean", "data_through": tmean_index.get("data_through"), "periods": result}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default="/tmp/hyras-data")
    ap.add_argument("--work", default="/tmp/hyras-tmean-work")
    ap.add_argument("--force-climate", action="store_true")
    args = ap.parse_args()

    data_root, work = Path(args.data_root), Path(args.work)
    troot = data_root / "tmean"
    regions_dir = troot / "regions"
    regions_dir.mkdir(parents=True, exist_ok=True)
    tmean_index = json.loads((troot / "index.json").read_text(encoding="utf-8"))
    year = int(tmean_index["year"])
    source_name = str(tmean_index["current_source_file"])
    current_nc = work / source_name
    if not current_nc.exists():
        download(f"{DAILY_BASE}/{source_name}", current_nc)

    with xr.open_dataset(current_nc, decode_times=True) as ds:
        _, _, _, _, x, y = prepare_da(ds)
    masks = build_masks(load_states(work), x, y)

    current, cx, cy = current_payload(current_nc, masks)
    current_path = regions_dir / f"current_{year}.json"
    current_path.write_text(json.dumps(current, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    climate_path = regions_dir / "climate_1991_2020.json"
    if args.force_climate or not climate_reusable(climate_path, cx, cy):
        print("Baue tägliche regionale HYRAS-Klimakurve 1991–2020 einmalig neu …", flush=True)
        climate = build_climate(latest_daily_files(daily_listing()), work, masks, cx, cy)
        climate_path.write_text(json.dumps(climate, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    else:
        print("Verwende vorhandene tägliche regionale HYRAS-Klimakurve 1991–2020.", flush=True)

    maps = build_download_maps(data_root, tmean_index)
    map_path = regions_dir / "map_downloads.json"
    map_path.write_text(json.dumps(maps, ensure_ascii=False, indent=2), encoding="utf-8")

    region_index = {
        "schema_version": 1, "method_version": METHOD_VERSION, "parameter": "tmean",
        "label": "2-m-Temperaturmittel", "unit": "°C", "reference": "1991-2020",
        "year": year, "data_through": current["data_through"],
        "regions": ["Deutschland", *EXPECTED_STATES],
        "current_file": current_path.name, "climate_file": climate_path.name,
        "map_downloads_file": map_path.name, "periods": date_periods(year, current["data_through"]),
        "method_note": "HYRAS-DE-TAS: tägliches räumliches Mittel aller 1-km-Gitterzellen mit Zellmittelpunkt im jeweiligen Bundesland; Deutschland ist die Vereinigung der 16 Landesmasken. Klimakurve: Mittel der täglichen Gebietsmittel 1991–2020.",
    }
    (regions_dir / "index.json").write_text(json.dumps(region_index, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Regionale Tmean-Kurven fertig.", flush=True)
    print("Datenstand:", current["data_through"], flush=True)
    print("Gebiete:", len(region_index["regions"]), flush=True)
    print("Perioden:", len(region_index["periods"]), flush=True)
    print("Download-Kartenperioden:", len(maps["periods"]), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
