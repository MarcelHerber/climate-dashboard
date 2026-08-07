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
from pyproj import CRS, Transformer

DAILY_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/precipitation"
CLIM_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/precipitation"
BOUNDARY_URL = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
USER_AGENT = "climate-dashboard-hyras/15.0.1 (+GitHub Actions; DWD Open Data)"

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
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def _crs_from_attrs(attrs: dict[str, Any]) -> CRS | None:
    if not attrs:
        return None
    for key in ("crs_wkt", "spatial_ref", "esri_pe_string", "proj4", "proj4_params", "crs"):
        value = attrs.get(key)
        if value:
            try:
                return CRS.from_user_input(value)
            except Exception:
                pass
    for key in ("epsg_code", "epsg"):
        value = attrs.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            m = re.search(r"(\d{4,5})", value)
            if m:
                try:
                    return CRS.from_epsg(int(m.group(1)))
                except Exception:
                    pass
        elif isinstance(value, (int, float)):
            try:
                return CRS.from_epsg(int(value))
            except Exception:
                pass
    if "grid_mapping_name" in attrs:
        try:
            return CRS.from_cf(attrs)
        except Exception:
            pass
    return None


def guess_crs_from_xy(x: np.ndarray, y: np.ndarray) -> CRS:
    xmin, xmax = float(np.nanmin(x)), float(np.nanmax(x))
    ymin, ymax = float(np.nanmin(y)), float(np.nanmax(y))
    midx = (xmin + xmax) / 2.0
    # DWD/Copernicus Europe Lambert Azimuthal Equal Area
    if 2_000_000 <= xmin <= 5_500_000 and 1_000_000 <= ymin <= 4_500_000:
        return CRS.from_epsg(3035)
    # DWD LCC Europe / ETRS89-LCC
    if 2_000_000 <= xmin <= 5_500_000 and 4_000_000 <= ymin <= 7_000_000:
        return CRS.from_epsg(3034)
    # UTM32 / ETRS89
    if 150_000 <= xmin <= 1_100_000 and 5_000_000 <= ymin <= 6_500_000:
        return CRS.from_epsg(25832)
    # DHDN / Gauss-Krüger Zonen 3–5
    if 2_500_000 <= xmin <= 6_000_000 and 5_000_000 <= ymin <= 6_500_000:
        zone = int(midx // 1_000_000)
        epsg_by_zone = {3: 31467, 4: 31468, 5: 31469}
        return CRS.from_epsg(epsg_by_zone.get(zone, 31467))
    # Fallback
    return CRS.from_epsg(3034)


def detect_data_crs(ds: xr.Dataset, da: xr.DataArray) -> CRS:
    candidates: list[dict[str, Any]] = [dict(da.attrs), dict(ds.attrs)]
    gm_name = da.attrs.get("grid_mapping")
    if gm_name and gm_name in ds.variables:
        candidates.insert(0, dict(ds[gm_name].attrs))
    for coord_name in da.coords:
        try:
            candidates.append(dict(da.coords[coord_name].attrs))
        except Exception:
            pass
    for attrs in candidates:
        crs = _crs_from_attrs(attrs)
        if crs is not None:
            return crs
    x, y = grid_xy(da)
    return guess_crs_from_xy(x, y)


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
            ax.plot(x, y, color="#3f4850", linewidth=0.42, alpha=0.82, zorder=5)


def draw_boundaries(ax, geojson: dict[str, Any] | None, data_crs: CRS) -> None:
    if not geojson:
        return
    transformer = Transformer.from_crs("EPSG:4326", data_crs, always_xy=True)
    for feature in geojson.get("features", []):
        draw_geometry(ax, feature.get("geometry") or {}, transformer)


def format_de(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def valid_bounds(arr: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float]:
    finite = np.isfinite(arr)
    if not finite.any():
        return float(np.nanmin(x)), float(np.nanmax(x)), float(np.nanmin(y)), float(np.nanmax(y))
    rows = np.where(finite.any(axis=1))[0]
    cols = np.where(finite.any(axis=0))[0]
    y0, y1 = int(rows[0]), int(rows[-1])
    x0, x1 = int(cols[0]), int(cols[-1])
    xmin = float(x[max(x0 - 1, 0)])
    xmax = float(x[min(x1 + 1, len(x) - 1)])
    ymin = float(y[max(y0 - 1, 0)])
    ymax = float(y[min(y1 + 1, len(y) - 1)])
    padx = (xmax - xmin) * 0.03
    pady = (ymax - ymin) * 0.03
    return xmin - padx, xmax + padx, ymin - pady, ymax + pady


def plot_map(da: xr.DataArray, path: Path, title: str, subtitle: str, cmap, norm, label: str, geojson, data_crs: CRS) -> None:
    arr = np.asarray(da.values, dtype=float)
    arr[~np.isfinite(arr)] = np.nan
    x, y = grid_xy(da)
    fig, ax = plt.subplots(figsize=(7.7, 9.2), dpi=200)
    mesh = ax.pcolormesh(x, y, arr, shading="auto", cmap=cmap, norm=norm, rasterized=True)
    draw_boundaries(ax, geojson, data_crs)
    xmin, xmax, ymin, ymax = valid_bounds(arr, x, y)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal")
    ax.set_axis_off()
    fig.suptitle(title, fontsize=20, fontweight="bold", y=0.975)
    ax.set_title(subtitle, fontsize=11, color="#4b5563", pad=9)
    cbar = fig.colorbar(mesh, ax=ax, fraction=0.037, pad=0.02, shrink=0.88)
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
        data_crs = detect_data_crs(ds, da)
        print(f"Verwende HYRAS-Kartenprojektion: {data_crs.to_string()}")
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
    plot_map(current, out/outputs["sum"], f"HYRAS-Niederschlag · {name}", "Niederschlagssumme", sum_cmap, sum_norm, "Niederschlag (l/m²)", geojson, data_crs)
    plot_map(pct, out/outputs["percent"], f"HYRAS-Niederschlag · {name}", "Prozent des Mittels 1991–2020", pct_cmap, pct_norm, "% von 1991–2020", geojson, data_crs)
    plot_map(anom, out/outputs["anomaly"], f"HYRAS-Niederschlag · {name}", "Absolute Abweichung zum Mittel 1991–2020", anom_cmap, anom_norm, "Abweichung (l/m²)", geojson, data_crs)

    stats = finite_stats(current, reference)
    metadata = {
        "schema_version": 2,
        "product": "DWD HYRAS-DE-PR",
        "resolution_km": 1,
        "period_type": "month",
        "year": year,
        "month": month,
        "month_name": MONTH_DE[month],
        "label": name,
        "reference": "1991-2020",
        "data_through": data_through,
        "daily_source_file": daily_name,
        "climatology_source_file": clim_name,
        "data_crs": data_crs.to_string(),
        "outputs": outputs,
        "stats": stats,
        "note": "Aktuellster vollständig in der DWD-HYRAS-Tagesdatei enthaltener Kalendermonat. Rastermittel über Zellen mit gültigem aktuellem und Referenzwert.",
    }
    (out / "hyras_index.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
