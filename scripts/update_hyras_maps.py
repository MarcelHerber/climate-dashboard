#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
import requests
import xarray as xr
from pyproj import Transformer

DAILY_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/precipitation"
CLIM_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/precipitation"
BOUNDARY_URL = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
USER_AGENT = "climate-dashboard-hyras/15.0 (+GitHub Actions; DWD Open Data)"

MONTH_ABBR = {1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"}
MONTH_DE = {1:"Januar",2:"Februar",3:"März",4:"April",5:"Mai",6:"Juni",7:"Juli",8:"August",9:"September",10:"Oktober",11:"November",12:"Dezember"}


def get(url: str, timeout: int = 120) -> requests.Response:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Download: {url}")
    with requests.get(url, stream=True, timeout=180, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    print(f"  -> {target.name}: {target.stat().st_size / 1024 / 1024:.1f} MB")


def directory_text(url: str) -> str:
    return get(url, 60).text


def latest_daily_filename(year: int) -> str:
    text = directory_text(DAILY_BASE + "/")
    matches = re.findall(rf'href="(pr_hyras_1_{year}_v(\d+)-(\d+)_de\.nc)"', text)
    if not matches:
        raise RuntimeError(f"Keine HYRAS-Tagesdatei für {year} gefunden")
    matches.sort(key=lambda m: (int(m[1]), int(m[2])))
    return matches[-1][0]


def latest_clim_filename(month: int) -> str:
    abbr = MONTH_ABBR[month]
    text = directory_text(CLIM_BASE + "/")
    matches = re.findall(rf'href="(pr_hyras_1_1991_2020_v(\d+)-(\d+)_de_{abbr}\.nc)"', text)
    if not matches:
        raise RuntimeError(f"Keine HYRAS-Klimadatei 1991–2020 für {abbr} gefunden")
    matches.sort(key=lambda m: (int(m[1]), int(m[2])))
    return matches[-1][0]


def pick_precip_var(ds: xr.Dataset) -> xr.DataArray:
    for name in ("pr", "precipitation", "rr"):
        if name in ds.data_vars and ds[name].ndim >= 2:
            return ds[name]
    for name, da in ds.data_vars.items():
        if da.ndim >= 2:
            print(f"Hinweis: verwende Datenvariable {name}")
            return da
    raise RuntimeError(f"Keine Rastervariable gefunden: {list(ds.data_vars)}")


def time_dim(da: xr.DataArray) -> str:
    for dim in da.dims:
        if dim.lower() == "time":
            return dim
    for dim in da.dims:
        coord = da.coords.get(dim)
        if coord is not None and np.issubdtype(coord.dtype, np.datetime64):
            return dim
    raise RuntimeError("Keine Zeitdimension gefunden")


def squeeze_2d(da: xr.DataArray) -> xr.DataArray:
    da = da.squeeze(drop=True)
    while da.ndim > 2:
        da = da.isel({da.dims[0]: 0})
    if da.ndim != 2:
        raise RuntimeError(f"Kein 2D-Raster: {da.dims} {da.shape}")
    return da


def latest_complete_month(da: xr.DataArray) -> tuple[int, int, str]:
    td = time_dim(da)
    dates = da[td].values.astype("datetime64[D]")
    if len(dates) == 0:
        raise RuntimeError("HYRAS-Datei enthält keine Tage")
    last_date = str(dates[-1])
    months: dict[tuple[int, int], set[str]] = {}
    for raw in dates:
        d = str(raw)
        y, m, _ = map(int, d.split("-"))
        months.setdefault((y, m), set()).add(d)
    complete = []
    for (y, m), ds in months.items():
        if len(ds) >= calendar.monthrange(y, m)[1]:
            complete.append((y, m))
    if not complete:
        raise RuntimeError("Noch kein vollständiger Monat in der HYRAS-Datei")
    y, m = max(complete)
    return y, m, last_date


def month_sum(da: xr.DataArray, year: int, month: int) -> xr.DataArray:
    td = time_dim(da)
    sel = da.where((da[td].dt.year == year) & (da[td].dt.month == month), drop=True)
    expected = calendar.monthrange(year, month)[1]
    count = sel.sizes.get(td, 0)
    if count < expected:
        raise RuntimeError(f"{MONTH_DE[month]} {year} unvollständig: {count}/{expected} Tage")
    return squeeze_2d(sel.sum(td, skipna=True, min_count=1))


def grid_xy(da: xr.DataArray):
    x_name = next((d for d in da.dims if d.lower() in {"x","lon","longitude","rlon"}), da.dims[-1])
    y_name = next((d for d in da.dims if d.lower() in {"y","lat","latitude","rlat"}), da.dims[-2])
    x = da.coords.get(x_name)
    y = da.coords.get(y_name)
    if x is None or y is None or x.ndim != 1 or y.ndim != 1:
        raise RuntimeError("Keine eindimensionalen HYRAS-x/y-Koordinaten gefunden")
    return np.asarray(x), np.asarray(y)


def load_boundaries() -> dict[str, Any] | None:
    try:
        return get(BOUNDARY_URL, 45).json()
    except Exception as exc:
        print(f"Warnung: Bundeslandgrenzen nicht geladen: {exc}")
        return None


def draw_geometry(ax, geometry: dict[str, Any], transformer: Transformer) -> None:
    typ = geometry.get("type")
    coords = geometry.get("coordinates") or []
    polygons = coords if typ == "MultiPolygon" else [coords] if typ == "Polygon" else []
    for polygon in polygons:
        for ring in polygon:
            if len(ring) < 2:
                continue
            lon = [p[0] for p in ring]
            lat = [p[1] for p in ring]
            x, y = transformer.transform(lon, lat)
            ax.plot(x, y, color="#3f4850", linewidth=0.48, alpha=0.78, zorder=5)


def draw_boundaries(ax, geojson: dict[str, Any] | None) -> None:
    if not geojson:
        return
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3034", always_xy=True)
    for feature in geojson.get("features", []):
        draw_geometry(ax, feature.get("geometry") or {}, transformer)


def format_de(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def plot_map(da: xr.DataArray, path: Path, title: str, subtitle: str, cmap, norm, label: str, geojson) -> None:
    arr = np.asarray(da.values, dtype=float)
    arr[~np.isfinite(arr)] = np.nan
    x, y = grid_xy(da)
    fig, ax = plt.subplots(figsize=(8.8, 10.2), dpi=200)
    mesh = ax.pcolormesh(x, y, arr, shading="auto", cmap=cmap, norm=norm, rasterized=True)
    draw_boundaries(ax, geojson)
    ax.set_aspect("equal")
    ax.set_axis_off()
    fig.suptitle(title, fontsize=20, fontweight="bold", y=0.975)
    ax.set_title(subtitle, fontsize=11, color="#4b5563", pad=9)
    cbar = fig.colorbar(mesh, ax=ax, fraction=0.034, pad=0.018, shrink=0.88)
    cbar.set_label(label, fontsize=10)
    cbar.ax.tick_params(labelsize=9)
    fig.text(0.5, 0.018, "Quelle: Deutscher Wetterdienst · HYRAS-DE-PR · 1-km-Raster", ha="center", fontsize=8.5, color="#5d6670")
    fig.tight_layout(rect=(0.01, 0.035, 0.99, 0.95))
    fig.savefig(path, bbox_inches="tight", facecolor="white", dpi=200)
    plt.close(fig)


def finite_stats(current: xr.DataArray, ref: xr.DataArray) -> dict[str, float | None]:
    a = np.asarray(current.values, dtype=float)
    b = np.asarray(ref.values, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b) & (b > 0.1)
    if not mask.any():
        return {"current_mean_mm":None,"reference_mean_mm":None,"percent_of_reference":None,"anomaly_mean_mm":None}
    cur = float(np.mean(a[mask]))
    refm = float(np.mean(b[mask]))
    return {
        "current_mean_mm": round(cur, 1),
        "reference_mean_mm": round(refm, 1),
        "percent_of_reference": round(cur / refm * 100.0, 1) if refm else None,
        "anomaly_mean_mm": round(cur - refm, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="hyras_output")
    parser.add_argument("--work", default="hyras_work")
    parser.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    args = parser.parse_args()

    out = Path(args.output)
    work = Path(args.work)
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    daily_name = latest_daily_filename(args.year)
    daily_url = f"{DAILY_BASE}/{daily_name}"
    daily_file = work / daily_name
    download(daily_url, daily_file)

    with xr.open_dataset(daily_file, decode_times=True) as ds:
        da = pick_precip_var(ds)
        year, month, data_through = latest_complete_month(da)
        current = month_sum(da, year, month).load()

    clim_name = latest_clim_filename(month)
    clim_url = f"{CLIM_BASE}/{clim_name}"
    clim_file = work / clim_name
    download(clim_url, clim_file)
    with xr.open_dataset(clim_file, decode_times=True) as ds:
        reference = squeeze_2d(pick_precip_var(ds)).load()

    current, reference = xr.align(current, reference, join="exact")
    pct = xr.where(reference > 0.1, current / reference * 100.0, np.nan)
    anom = current - reference
    geojson = load_boundaries()

    sum_bounds = [0,10,25,50,75,100,150,200,300,500]
    sum_cmap = ListedColormap(["#f7fbff","#deebf7","#c6dbef","#9ecae1","#6baed6","#4292c6","#2171b5","#08519c","#08306b"])
    sum_norm = BoundaryNorm(sum_bounds, sum_cmap.N, clip=True)
    pct_bounds = [0,25,50,75,90,110,125,150,200,300]
    pct_cmap = ListedColormap(["#6b3d1f","#9a6334","#c99762","#e4c49f","#f1ede5","#dcebd5","#a8d39b","#68ad6f","#287d46"])
    pct_norm = BoundaryNorm(pct_bounds, pct_cmap.N, clip=True)
    anom_bounds = [-200,-150,-100,-75,-50,-25,-10,10,25,50,75,100,150,200]
    anom_cmap = ListedColormap(["#543005","#8c510a","#bf812d","#dfc27d","#ead8ad","#f6e8c3","#f5f5f5","#c7eae5","#80cdc1","#35978f","#1b7f75","#01665e","#003c30"])
    anom_norm = BoundaryNorm(anom_bounds, anom_cmap.N, clip=True)

    name = f"{MONTH_DE[month]} {year}"
    outputs = {
        "sum":"hyras_latest_sum.png",
        "percent":"hyras_latest_percent_1991_2020.png",
        "anomaly":"hyras_latest_anomaly_mm_1991_2020.png",
    }
    plot_map(current, out/outputs["sum"], f"HYRAS-Niederschlag · {name}", "Niederschlagssumme", sum_cmap, sum_norm, "Niederschlag (l/m²)", geojson)
    plot_map(pct, out/outputs["percent"], f"HYRAS-Niederschlag · {name}", "Prozent des Mittels 1991–2020", pct_cmap, pct_norm, "% von 1991–2020", geojson)
    plot_map(anom, out/outputs["anomaly"], f"HYRAS-Niederschlag · {name}", "Absolute Abweichung zum Mittel 1991–2020", anom_cmap, anom_norm, "Abweichung (l/m²)", geojson)

    stats = finite_stats(current, reference)
    metadata = {
        "schema_version":1,
        "product":"DWD HYRAS-DE-PR",
        "resolution_km":1,
        "period_type":"month",
        "year":year,
        "month":month,
        "month_name":MONTH_DE[month],
        "label":name,
        "reference":"1991-2020",
        "data_through":data_through,
        "daily_source_file":daily_name,
        "climatology_source_file":clim_name,
        "outputs":outputs,
        "stats":stats,
        "note":"Aktuellster vollständig in der DWD-HYRAS-Tagesdatei enthaltener Kalendermonat. Rastermittel über Zellen mit gültigem aktuellem und Referenzwert.",
    }
    (out/"hyras_index.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
