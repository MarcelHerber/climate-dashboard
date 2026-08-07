#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
import requests
import xarray as xr
from pyproj import CRS, Transformer
from PIL import Image, ImageDraw

DAILY_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/precipitation"
MONTHLY_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/monthly/hyras_de/precipitation"
CLIM_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/precipitation"
BOUNDARY_URL = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
USER_AGENT = "climate-dashboard-hyras/15.3 (+GitHub Actions; DWD Open Data)"

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



def date_sum(da: xr.DataArray, start_date: str, end_date: str) -> xr.DataArray:
    td = time_dim(da)
    start = np.datetime64(start_date)
    end = np.datetime64(end_date)
    sel = da.where((da[td] >= start) & (da[td] <= end), drop=True)
    if sel.sizes.get(td, 0) == 0:
        raise RuntimeError(f"Keine HYRAS-Tage für {start_date} bis {end_date}")
    return squeeze_2d(sel.sum(td, skipna=True, min_count=1))


def month_end(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def period_label_date(start_date: str, end_date: str) -> str:
    s = datetime.strptime(start_date, "%Y-%m-%d")
    e = datetime.strptime(end_date, "%Y-%m-%d")
    if s.year == e.year:
        return f"{s.strftime('%d.%m.')}–{e.strftime('%d.%m.%Y')}"
    return f"{s.strftime('%d.%m.%Y')}–{e.strftime('%d.%m.%Y')}"


def load_month_reference(month: int, work: Path, cache: dict[int, xr.DataArray]) -> tuple[xr.DataArray, str]:
    if month in cache:
        return cache[month], latest_clim_filename(month)
    filename = latest_clim_filename(month)
    target = work / filename
    if not target.exists():
        download(f"{CLIM_BASE}/{filename}", target)
    with xr.open_dataset(target, decode_times=True) as ds:
        da = squeeze_2d(pick_precip_var(ds)).load()
    cache[month] = da
    return da, filename


def reference_for_months(months: list[int], work: Path, cache: dict[int, xr.DataArray]) -> tuple[xr.DataArray, list[str]]:
    refs: list[xr.DataArray] = []
    files: list[str] = []
    for month in months:
        ref, filename = load_month_reference(month, work, cache)
        refs.append(ref)
        files.append(filename)
    base = refs[0].copy(deep=True)
    for ref in refs[1:]:
        base, aligned = xr.align(base, ref, join="exact")
        base = base + aligned
    return squeeze_2d(base), files


def period_output_names(key: str, has_reference: bool) -> dict[str, str]:
    outputs = {"sum": f"hyras_{key}_sum.png"}
    if has_reference:
        outputs["percent"] = f"hyras_{key}_percent_1991_2020.png"
        outputs["anomaly"] = f"hyras_{key}_anomaly_mm_1991_2020.png"
    return outputs


def render_period(
    *, out: Path, current: xr.DataArray, reference: xr.DataArray | None,
    key: str, title_label: str, subtitle_period: str, geojson, data_crs: CRS,
    source_files: list[str], period_type: str, start_date: str, end_date: str,
    reference_note: str | None = None,
) -> dict[str, Any]:
    sum_bounds = [0,10,25,50,75,100,150,200,300,500,750,1000]
    sum_cmap = ListedColormap(["#f7fbff","#deebf7","#c6dbef","#9ecae1","#6baed6","#4292c6","#2171b5","#08519c","#08306b","#041f4a","#02142f"])
    sum_norm = BoundaryNorm(sum_bounds, sum_cmap.N, clip=True)
    pct_bounds = [0,25,50,75,90,110,125,150,200,300]
    pct_cmap = ListedColormap(["#6b3d1f","#9a6334","#c99762","#e4c49f","#f1ede5","#dcebd5","#a8d39b","#68ad6f","#287d46"])
    pct_norm = BoundaryNorm(pct_bounds, pct_cmap.N, clip=True)
    anom_bounds = [-400,-250,-150,-100,-75,-50,-25,-10,10,25,50,75,100,150,250,400]
    anom_cmap = ListedColormap(["#3b1f00","#543005","#8c510a","#bf812d","#d69f4b","#dfc27d","#ead8ad","#f6e8c3","#f5f5f5","#c7eae5","#80cdc1","#35978f","#1b7f75","#01665e","#003c30"])
    anom_norm = BoundaryNorm(anom_bounds, anom_cmap.N, clip=True)

    outputs = period_output_names(key, reference is not None)
    plot_map(current, out / outputs["sum"], f"HYRAS-Niederschlag · {title_label}", f"Niederschlagssumme · {subtitle_period}", sum_cmap, sum_norm, "Niederschlag (l/m²)", geojson, data_crs)

    stats: dict[str, float | None]
    if reference is not None:
        current, reference = xr.align(current, reference, join="exact")
        pct = xr.where(reference > 0.1, current / reference * 100.0, np.nan)
        anom = current - reference
        plot_map(pct, out / outputs["percent"], f"HYRAS-Niederschlag · {title_label}", f"Prozent des Mittels 1991–2020 · {subtitle_period}", pct_cmap, pct_norm, "% von 1991–2020", geojson, data_crs)
        plot_map(anom, out / outputs["anomaly"], f"HYRAS-Niederschlag · {title_label}", f"Absolute Abweichung zu 1991–2020 · {subtitle_period}", anom_cmap, anom_norm, "Abweichung (l/m²)", geojson, data_crs)
        stats = finite_stats(current, reference)
    else:
        arr = np.asarray(current.values, dtype=float)
        finite = np.isfinite(arr)
        cur = float(np.mean(arr[finite])) if finite.any() else None
        stats = {
            "current_mean_mm": round(cur, 1) if cur is not None else None,
            "reference_mean_mm": None,
            "percent_of_reference": None,
            "anomaly_mean_mm": None,
        }

    return {
        "key": key,
        "label": title_label,
        "period_type": period_type,
        "start_date": start_date,
        "end_date": end_date,
        "date_label": subtitle_period,
        "reference": "1991-2020" if reference is not None else None,
        "reference_exact": reference is not None,
        "reference_note": reference_note,
        "outputs": outputs,
        "stats": stats,
        "climatology_source_files": source_files,
    }



def spatial_dim_names(da: xr.DataArray) -> tuple[str, str]:
    x_name = next((d for d in da.dims if d.lower() in {"x", "lon", "longitude", "rlon"}), da.dims[-1])
    y_name = next((d for d in da.dims if d.lower() in {"y", "lat", "latitude", "rlat"}), da.dims[-2])
    return y_name, x_name


def sample_daily_for_web(da: xr.DataArray, factor: int) -> tuple[np.ndarray, list[str], np.ndarray, np.ndarray]:
    """Sample every Nth HYRAS grid cell and orient the result north-up/west-left."""
    td = time_dim(da)
    y_name, x_name = spatial_dim_names(da)
    sampled = da.isel({y_name: slice(None, None, factor), x_name: slice(None, None, factor)}).transpose(td, y_name, x_name)
    values = np.asarray(sampled.values, dtype=np.float32)
    x = np.asarray(sampled[x_name].values, dtype=float)
    y = np.asarray(sampled[y_name].values, dtype=float)
    dates = [str(v)[:10] for v in sampled[td].values.astype("datetime64[D]")]
    values[~np.isfinite(values)] = np.nan
    values[values < 0] = np.nan
    if len(x) > 1 and x[0] > x[-1]:
        x = x[::-1]
        values = values[:, :, ::-1]
    if len(y) > 1 and y[0] < y[-1]:
        y = y[::-1]
        values = values[:, ::-1, :]
    return values, dates, x, y


def reference_day_template() -> list[tuple[int, int]]:
    # Leap-year template so 29 February has a defined daily climatology too.
    d = date(2000, 1, 1)
    end = date(2000, 12, 31)
    out: list[tuple[int, int]] = []
    while d <= end:
        out.append((d.month, d.day))
        d += timedelta(days=1)
    return out


def daily_file_map(listing_text: str, years: range) -> dict[int, str]:
    out: dict[int, tuple[tuple[int, int], str]] = {}
    pattern = re.compile(r'href="(pr_hyras_1_(\d{4})_v(\d+)-(\d+)_de\.nc)"')
    wanted = set(years)
    for filename, year_s, major_s, minor_s in pattern.findall(listing_text):
        year = int(year_s)
        if year not in wanted:
            continue
        version = (int(major_s), int(minor_s))
        if year not in out or version > out[year][0]:
            out[year] = (version, filename)
    missing = [y for y in years if y not in out]
    if missing:
        raise RuntimeError(f"HYRAS-Referenzjahre fehlen im DWD-Verzeichnis: {missing[:8]}")
    return {year: item[1] for year, item in out.items()}


def build_or_load_daily_reference(
    *, cache_dir: Path, work: Path, factor: int, expected_x: np.ndarray,
    expected_y: np.ndarray, data_crs: CRS,
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"hyras_daily_reference_1991_2020_web{factor}_v1.npz"
    if cache_file.exists():
        print(f"Lade tagesgenaue 1991–2020-Referenz aus Cache: {cache_file}")
        with np.load(cache_file, allow_pickle=False) as npz:
            daily_mean = np.asarray(npz["daily_mean"], dtype=np.float32)
            months = np.asarray(npz["months"], dtype=np.int16)
            days = np.asarray(npz["days"], dtype=np.int16)
            x = np.asarray(npz["x"], dtype=float)
            y = np.asarray(npz["y"], dtype=float)
        if daily_mean.shape[1:] != (len(expected_y), len(expected_x)) or not np.allclose(x, expected_x) or not np.allclose(y, expected_y):
            print("Cache-Raster passt nicht zum aktuellen HYRAS-Raster – Referenz wird neu aufgebaut.")
            cache_file.unlink(missing_ok=True)
        else:
            return daily_mean, list(zip(months.tolist(), days.tolist()))

    print("Baue tagesgenaue HYRAS-Referenz 1991–2020 für freie Zeiträume. Das dauert beim ersten Lauf deutlich länger …")
    template = reference_day_template()
    lookup = {md: i for i, md in enumerate(template)}
    ny, nx = len(expected_y), len(expected_x)
    sums = np.zeros((len(template), ny, nx), dtype=np.float64)
    counts = np.zeros((len(template), ny, nx), dtype=np.uint16)
    listing = directory_text(DAILY_BASE + "/")
    file_map = daily_file_map(listing, range(1991, 2021))

    for n, year in enumerate(range(1991, 2021), start=1):
        filename = file_map[year]
        target = work / "reference_years" / filename
        if not target.exists():
            download(f"{DAILY_BASE}/{filename}", target)
        print(f"Referenzjahr {year} ({n}/30) …")
        with xr.open_dataset(target, decode_times=True) as ds:
            source = pick_precip_var(ds)
            vals, dates, x, y = sample_daily_for_web(source, factor)
        if vals.shape[1:] != (ny, nx) or not np.allclose(x, expected_x) or not np.allclose(y, expected_y):
            raise RuntimeError(f"Raster von Referenzjahr {year} passt nicht zum aktuellen HYRAS-Raster")
        for i, iso in enumerate(dates):
            dt = datetime.strptime(iso, "%Y-%m-%d")
            idx = lookup[(dt.month, dt.day)]
            arr = vals[i]
            valid = np.isfinite(arr)
            sums[idx][valid] += arr[valid]
            counts[idx][valid] += 1
        # Die großen Jahresdateien werden nach Verarbeitung entfernt.
        try:
            target.unlink()
        except OSError:
            pass

    with np.errstate(invalid="ignore", divide="ignore"):
        daily_mean = (sums / np.where(counts > 0, counts, np.nan)).astype(np.float32)
    months = np.array([m for m, _ in template], dtype=np.int16)
    days = np.array([d for _, d in template], dtype=np.int16)
    np.savez_compressed(cache_file, daily_mean=daily_mean, months=months, days=days,
                        x=expected_x.astype(np.float64), y=expected_y.astype(np.float64),
                        crs=np.array(data_crs.to_string()))
    print(f"Tagesreferenz gespeichert: {cache_file} ({cache_file.stat().st_size/1024/1024:.1f} MB)")
    return daily_mean, template


def encode_precip_png(values_mm: np.ndarray, target: Path, scale: int = 10) -> None:
    """Encode cumulative precipitation losslessly-ish as RGB integer tenths of mm + alpha mask."""
    valid = np.isfinite(values_mm)
    quant = np.zeros(values_mm.shape, dtype=np.uint32)
    quant[valid] = np.clip(np.rint(values_mm[valid] * scale), 0, 16_777_215).astype(np.uint32)
    rgba = np.zeros((*values_mm.shape, 4), dtype=np.uint8)
    rgba[..., 0] = ((quant >> 16) & 255).astype(np.uint8)
    rgba[..., 1] = ((quant >> 8) & 255).astype(np.uint8)
    rgba[..., 2] = (quant & 255).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(target, optimize=True, compress_level=7)


def build_boundary_overlay(
    *, geojson: dict[str, Any] | None, data_crs: CRS, x: np.ndarray, y: np.ndarray,
    target: Path,
) -> None:
    width, height = len(x), len(y)
    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    if not geojson or width < 2 or height < 2:
        image.save(target)
        return
    draw = ImageDraw.Draw(image)
    transformer = Transformer.from_crs("EPSG:4326", data_crs, always_xy=True)
    xmin, xmax = float(x[0]), float(x[-1])
    ymax, ymin = float(y[0]), float(y[-1])
    dx = xmax - xmin
    dy = ymax - ymin
    def px(xv: float, yv: float) -> tuple[float, float]:
        return ((xv - xmin) / dx * (width - 1), (ymax - yv) / dy * (height - 1))
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry") or {}
        typ = geometry.get("type")
        coords = geometry.get("coordinates") or []
        polygons = coords if typ == "MultiPolygon" else [coords] if typ == "Polygon" else []
        for polygon in polygons:
            for ring in polygon:
                if len(ring) < 2:
                    continue
                lon = [p[0] for p in ring]
                lat = [p[1] for p in ring]
                gx, gy = transformer.transform(lon, lat)
                points = [px(float(a), float(b)) for a, b in zip(gx, gy)]
                draw.line(points, fill=(45, 55, 65, 225), width=1, joint="curve")
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, optimize=True)


def build_web_cumulative_package(
    *, daily: xr.DataArray, year: int, data_through: str, factor: int,
    out: Path, work: Path, cache_dir: Path, geojson: dict[str, Any] | None,
    data_crs: CRS,
) -> dict[str, Any]:
    print(f"Erzeuge Web-Raster für freie Zeiträume (Abtastung {factor} km) …")
    vals, dates, x, y = sample_daily_for_web(daily, factor)
    keep = [i for i, iso in enumerate(dates) if iso <= data_through and iso.startswith(f"{year}-")]
    vals = vals[keep]
    dates = [dates[i] for i in keep]
    if not dates:
        raise RuntimeError("Keine aktuellen HYRAS-Tage für das Web-Raster")
    mask = np.any(np.isfinite(vals), axis=0)
    cumulative = np.cumsum(np.where(np.isfinite(vals), vals, 0.0), axis=0, dtype=np.float32)
    cumulative[:, ~mask] = np.nan

    reference_daily, template = build_or_load_daily_reference(
        cache_dir=cache_dir, work=work, factor=factor, expected_x=x, expected_y=y, data_crs=data_crs,
    )
    ref_lookup = {md: i for i, md in enumerate(template)}
    ref_sequence = []
    for iso in dates:
        dt = datetime.strptime(iso, "%Y-%m-%d")
        ref_sequence.append(reference_daily[ref_lookup[(dt.month, dt.day)]])
    ref_stack = np.stack(ref_sequence, axis=0).astype(np.float32)
    ref_mask = np.any(np.isfinite(ref_stack), axis=0)
    ref_cumulative = np.cumsum(np.where(np.isfinite(ref_stack), ref_stack, 0.0), axis=0, dtype=np.float32)
    ref_cumulative[:, ~ref_mask] = np.nan

    current_files: dict[str, str] = {}
    reference_files: dict[str, str] = {}
    for i, iso in enumerate(dates):
        current_rel = f"web/current/cum_{iso}.png"
        ref_rel = f"web/reference/cum_{iso}.png"
        encode_precip_png(cumulative[i], out / current_rel)
        encode_precip_png(ref_cumulative[i], out / ref_rel)
        current_files[iso] = current_rel
        reference_files[iso] = ref_rel
        if (i + 1) % 50 == 0 or i + 1 == len(dates):
            print(f"  Web-Kumulativraster {i+1}/{len(dates)}")

    boundary_rel = "web/boundaries.png"
    build_boundary_overlay(geojson=geojson, data_crs=data_crs, x=x, y=y, target=out / boundary_rel)
    manifest = {
        "schema_version": 1,
        "year": year,
        "data_through": data_through,
        "native_resolution_km": 1,
        "web_sampling_km": factor,
        "value_scale": 10,
        "width": len(x),
        "height": len(y),
        "data_crs": data_crs.to_string(),
        "first_date": dates[0],
        "last_date": dates[-1],
        "current_files": current_files,
        "reference_files": reference_files,
        "boundary_overlay": boundary_rel,
        "note": "Freie Zeiträume werden tagesgenau gegen die mittlere Tagesniederschlagssumme 1991–2020 verglichen. Für schnelle Browserdarstellung wird jedes fünfte 1-km-HYRAS-Rasterelement verwendet.",
    }
    (out / "hyras_web_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return manifest


def sample_monthly_for_web(da: xr.DataArray, factor: int) -> tuple[np.ndarray, list[str], np.ndarray, np.ndarray]:
    """Sample a monthly HYRAS cube onto the same compact web grid used by free periods."""
    td = time_dim(da)
    y_name, x_name = spatial_dim_names(da)
    sampled = da.isel({y_name: slice(None, None, factor), x_name: slice(None, None, factor)}).transpose(td, y_name, x_name)
    values = np.asarray(sampled.values, dtype=np.float32)
    x = np.asarray(sampled[x_name].values, dtype=float)
    y = np.asarray(sampled[y_name].values, dtype=float)
    dates = [str(v)[:10] for v in sampled[td].values.astype("datetime64[D]")]
    values[~np.isfinite(values)] = np.nan
    values[values < 0] = np.nan
    if len(x) > 1 and x[0] > x[-1]:
        x = x[::-1]
        values = values[:, :, ::-1]
    if len(y) > 1 and y[0] < y[-1]:
        y = y[::-1]
        values = values[:, ::-1, :]
    return values, dates, x, y


def latest_monthly_archive(listing_text: str, max_year: int) -> tuple[str, int] | None:
    """Find newest consolidated monthly HYRAS file starting in 1931."""
    matches = []
    pattern = re.compile(r'href="(pr_hyras_1_1931_(\d{4})_v(\d+)-(\d+)_de_monsum\.nc)"')
    for filename, end_s, major_s, minor_s in pattern.findall(listing_text):
        end_year = int(end_s)
        if end_year <= max_year:
            matches.append((end_year, int(major_s), int(minor_s), filename))
    if not matches:
        return None
    matches.sort()
    end_year, _major, _minor, filename = matches[-1]
    return filename, end_year


def monthly_annual_file_map(listing_text: str, years: range) -> dict[int, str]:
    wanted = set(years)
    found: dict[int, tuple[tuple[int, int], str]] = {}
    pattern = re.compile(r'href="(pr_hyras_1_(\d{4})_v(\d+)-(\d+)_de_monsum\.nc)"')
    for filename, year_s, major_s, minor_s in pattern.findall(listing_text):
        year = int(year_s)
        if year not in wanted:
            continue
        version = (int(major_s), int(minor_s))
        if year not in found or version > found[year][0]:
            found[year] = (version, filename)
    return {year: item[1] for year, item in found.items()}


def historical_month_path(out: Path, year: int, month: int) -> Path:
    return out / "historical" / str(year) / f"month_{month:02d}.png"


def historical_year_complete(out: Path, year: int) -> bool:
    return all(historical_month_path(out, year, m).exists() for m in range(1, 13))


def build_historical_monthly_package(
    *, out: Path, work: Path, factor: int, current_year: int,
    expected_x: np.ndarray, expected_y: np.ndarray, data_crs: CRS,
) -> dict[str, Any]:
    """Build compact monthly HYRAS web rasters for 1931 through the previous year.

    Existing rasters copied from the hyras-data branch are reused. The expensive
    consolidated archive is therefore only needed on the first historical build.
    """
    target_first = 1931
    target_last = current_year - 1
    if target_last < target_first:
        raise RuntimeError("Kein historischer HYRAS-Zeitraum verfügbar")

    hist_root = out / "historical"
    hist_root.mkdir(parents=True, exist_ok=True)
    ref_root = hist_root / "reference"
    ref_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "hyras_historical_manifest.json"

    existing_years = [y for y in range(target_first, target_last + 1) if historical_year_complete(out, y)]
    missing_years = [y for y in range(target_first, target_last + 1) if y not in set(existing_years)]
    ref_complete = all((ref_root / f"month_{m:02d}.png").exists() for m in range(1, 13))
    print(f"Historische Monatsraster: {len(existing_years)} Jahre vorhanden, {len(missing_years)} Jahre fehlen.")

    listing = directory_text(MONTHLY_BASE + "/")
    archive = latest_monthly_archive(listing, target_last)
    reference_sums = [np.zeros((len(expected_y), len(expected_x)), dtype=np.float64) for _ in range(12)]
    reference_counts = [np.zeros((len(expected_y), len(expected_x)), dtype=np.uint16) for _ in range(12)]
    need_reference = not ref_complete

    # On a first build the consolidated 1931-20xx file is far faster than ~100 separate downloads.
    archive_end = 1930
    if archive and (need_reference or any(y <= archive[1] for y in missing_years)):
        archive_name, archive_end = archive
        archive_file = work / "historical" / archive_name
        if not archive_file.exists():
            download(f"{MONTHLY_BASE}/{archive_name}", archive_file)
        print(f"Verarbeite HYRAS-Monatsarchiv {archive_name} …")
        with xr.open_dataset(archive_file, decode_times=True) as ds:
            source = pick_precip_var(ds)
            vals, dates, x, y = sample_monthly_for_web(source, factor)
        if vals.shape[1:] != (len(expected_y), len(expected_x)) or not np.allclose(x, expected_x) or not np.allclose(y, expected_y):
            raise RuntimeError("Historisches HYRAS-Monatsraster passt nicht zum aktuellen Webraster")
        missing_set = set(missing_years)
        for i, iso in enumerate(dates):
            dt = datetime.strptime(iso, "%Y-%m-%d")
            if dt.year < target_first or dt.year > min(target_last, archive_end):
                continue
            if dt.year in missing_set:
                encode_precip_png(vals[i], historical_month_path(out, dt.year, dt.month))
            if need_reference and 1991 <= dt.year <= 2020:
                arr = vals[i]
                valid = np.isfinite(arr)
                reference_sums[dt.month - 1][valid] += arr[valid]
                reference_counts[dt.month - 1][valid] += 1
        try:
            archive_file.unlink()
        except OSError:
            pass

    # Years newer than the consolidated archive are tiny annual monthly files (e.g. 2025).
    remaining = [y for y in missing_years if not historical_year_complete(out, y)]
    annual_map = monthly_annual_file_map(listing, range(target_first, target_last + 1))
    for pos, year in enumerate(remaining, start=1):
        filename = annual_map.get(year)
        if not filename:
            raise RuntimeError(f"Keine HYRAS-Monatsdatei für historisches Jahr {year} gefunden")
        target = work / "historical" / filename
        if not target.exists():
            download(f"{MONTHLY_BASE}/{filename}", target)
        print(f"Historisches Jahr {year} ({pos}/{len(remaining)}) …")
        with xr.open_dataset(target, decode_times=True) as ds:
            vals, dates, x, y = sample_monthly_for_web(pick_precip_var(ds), factor)
        if vals.shape[1:] != (len(expected_y), len(expected_x)) or not np.allclose(x, expected_x) or not np.allclose(y, expected_y):
            raise RuntimeError(f"Historisches HYRAS-Raster {year} passt nicht zum Webraster")
        seen = set()
        for i, iso in enumerate(dates):
            dt = datetime.strptime(iso, "%Y-%m-%d")
            if dt.year != year:
                continue
            encode_precip_png(vals[i], historical_month_path(out, year, dt.month))
            seen.add(dt.month)
            if need_reference and 1991 <= year <= 2020:
                arr = vals[i]
                valid = np.isfinite(arr)
                reference_sums[dt.month - 1][valid] += arr[valid]
                reference_counts[dt.month - 1][valid] += 1
        if len(seen) < 12:
            raise RuntimeError(f"Historisches HYRAS-Jahr {year} enthält nur {len(seen)} Monatswerte")
        try:
            target.unlink()
        except OSError:
            pass

    # If a new installation needs the reference, it was accumulated from 1991-2020 above.
    if need_reference:
        # If 1991-2020 were already present as PNGs but reference files were deleted,
        # rebuild their mean directly from the compact rasters without a new NetCDF download.
        if not all(np.any(c > 0) for c in reference_counts):
            for year in range(1991, 2021):
                for month in range(1, 13):
                    p = historical_month_path(out, year, month)
                    if not p.exists():
                        continue
                    image = np.asarray(Image.open(p).convert("RGBA"), dtype=np.uint8)
                    valid = image[..., 3] > 0
                    q = image[..., 0].astype(np.uint32) * 65536 + image[..., 1].astype(np.uint32) * 256 + image[..., 2].astype(np.uint32)
                    arr = q.astype(np.float32) / 10.0
                    reference_sums[month - 1][valid] += arr[valid]
                    reference_counts[month - 1][valid] += 1
        for month in range(1, 13):
            counts = reference_counts[month - 1]
            with np.errstate(invalid="ignore", divide="ignore"):
                ref = (reference_sums[month - 1] / np.where(counts > 0, counts, np.nan)).astype(np.float32)
            encode_precip_png(ref, ref_root / f"month_{month:02d}.png")

    years = [y for y in range(target_first, target_last + 1) if historical_year_complete(out, y)]
    if not years:
        raise RuntimeError("Keine historischen Monatsraster erfolgreich erzeugt")
    if years[0] != target_first or years[-1] != target_last:
        print(f"Warnung: historische Reihe ist nicht vollständig: {years[0]}–{years[-1]}")

    manifest = {
        "schema_version": 1,
        "product": "DWD HYRAS-DE-PR monthly precipitation",
        "first_year": years[0],
        "last_year": years[-1],
        "years": years,
        "native_resolution_km": 1,
        "web_sampling_km": factor,
        "value_scale": 10,
        "width": len(expected_x),
        "height": len(expected_y),
        "data_crs": data_crs.to_string(),
        "month_file_pattern": "historical/{year}/month_{month}.png",
        "reference_files": {str(m): f"historical/reference/month_{m:02d}.png" for m in range(1, 13)},
        "reference": "1991-2020",
        "boundary_overlay": "web/boundaries.png",
        "seasons": {
            "spring": [3, 4, 5],
            "summer": [6, 7, 8],
            "autumn": [9, 10, 11],
            "winter": [12, 1, 2],
            "year": list(range(1, 13)),
        },
        "note": "Historische Monats-, Jahreszeiten- und Jahreskarten werden im Browser aus monatlichen HYRAS-Summen auf einem kompakten 5-km-Webraster zusammengesetzt. Quelle ist das native 1-km-HYRAS-DE-PR-Monatsprodukt; Referenz ist 1991-2020.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Historisches HYRAS-Webpaket bereit: {years[0]}–{years[-1]} ({len(years)} Jahre).")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="hyras_output")
    parser.add_argument("--work", default="hyras_work")
    parser.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--reference-cache", default="hyras_reference_cache")
    parser.add_argument("--web-factor", type=int, default=5)
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
        latest_year, latest_month, data_through = latest_complete_month(da)
        daily = da.load()

    if latest_year != args.year:
        raise RuntimeError(f"Aktuellster vollständiger Monat liegt nicht in {args.year}: {latest_year}-{latest_month:02d}")

    data_through_dt = datetime.strptime(data_through, "%Y-%m-%d")
    geojson = load_boundaries()
    ref_cache: dict[int, xr.DataArray] = {}
    periods: list[dict[str, Any]] = []

    # Vollständige Monate des aktuellen Jahres.
    complete_months: list[int] = []
    for month in range(1, latest_month + 1):
        try:
            current = month_sum(daily, args.year, month).load()
        except Exception as exc:
            print(f"Monat {month:02d} übersprungen: {exc}")
            continue
        complete_months.append(month)
        reference, ref_files = reference_for_months([month], work, ref_cache)
        key = f"{args.year}_{month:02d}"
        periods.append(render_period(
            out=out, current=current, reference=reference, key=key,
            title_label=f"{MONTH_DE[month]} {args.year}", subtitle_period=f"01.{month:02d}.–{calendar.monthrange(args.year, month)[1]:02d}.{month:02d}.{args.year}",
            geojson=geojson, data_crs=data_crs, source_files=ref_files,
            period_type="month", start_date=f"{args.year}-{month:02d}-01", end_date=month_end(args.year, month),
        ))

    # Abgeschlossene Jahreszeiten, sobald alle Monate vorhanden sind.
    season_defs = [
        ("spring", "Frühling", [3,4,5]),
        ("summer", "Sommer", [6,7,8]),
        ("autumn", "Herbst", [9,10,11]),
    ]
    for key, label, months in season_defs:
        if not all(m in complete_months for m in months):
            continue
        start_date = f"{args.year}-{months[0]:02d}-01"
        end_date = month_end(args.year, months[-1])
        current = date_sum(daily, start_date, end_date).load()
        reference, ref_files = reference_for_months(months, work, ref_cache)
        periods.append(render_period(
            out=out, current=current, reference=reference, key=f"{args.year}_{key}",
            title_label=f"{label} {args.year}", subtitle_period=period_label_date(start_date, end_date),
            geojson=geojson, data_crs=data_crs, source_files=ref_files, period_type="season",
            start_date=start_date, end_date=end_date,
        ))

    # Sommer bis zum Ende des letzten vollständigen Monats – exakter Referenzvergleich.
    summer_complete_months = [m for m in (6,7,8) if m in complete_months]
    if summer_complete_months:
        start_date = f"{args.year}-06-01"
        end_date = month_end(args.year, summer_complete_months[-1])
        current = date_sum(daily, start_date, end_date).load()
        reference, ref_files = reference_for_months(summer_complete_months, work, ref_cache)
        periods.append(render_period(
            out=out, current=current, reference=reference, key=f"{args.year}_summer_so_far_complete",
            title_label=f"Sommer bisher {args.year}", subtitle_period=period_label_date(start_date, end_date),
            geojson=geojson, data_crs=data_crs, source_files=ref_files, period_type="summer_so_far_complete",
            start_date=start_date, end_date=end_date,
            reference_note="Exakter Vergleich 1991–2020 über vollständig abgeschlossene Kalendermonate.",
        ))

    # Jahr bis zum Ende des letzten vollständigen Monats – exakter Referenzvergleich.
    if complete_months:
        start_date = f"{args.year}-01-01"
        end_date = month_end(args.year, complete_months[-1])
        current = date_sum(daily, start_date, end_date).load()
        reference, ref_files = reference_for_months(complete_months, work, ref_cache)
        periods.append(render_period(
            out=out, current=current, reference=reference, key=f"{args.year}_ytd_complete",
            title_label=f"Jahr bisher {args.year}", subtitle_period=period_label_date(start_date, end_date),
            geojson=geojson, data_crs=data_crs, source_files=ref_files, period_type="ytd_complete",
            start_date=start_date, end_date=end_date,
            reference_note="Exakter Vergleich 1991–2020 über vollständig abgeschlossene Kalendermonate.",
        ))

    # Aktueller Zeitraum bis zum letzten HYRAS-Tag. Für Teilmonate zunächst nur Summe.
    if data_through_dt.month >= 6:
        start_date = f"{args.year}-06-01"
        current = date_sum(daily, start_date, data_through).load()
        periods.append(render_period(
            out=out, current=current, reference=None, key=f"{args.year}_summer_live",
            title_label=f"Sommer aktuell {args.year}", subtitle_period=period_label_date(start_date, data_through),
            geojson=geojson, data_crs=data_crs, source_files=[], period_type="summer_live",
            start_date=start_date, end_date=data_through,
            reference_note="Für diese vordefinierte 1-km-Karte wird der laufende Teilmonat nur als Summe gezeigt. Für einen tagesgenauen 1991–2020-Vergleich denselben Zeitraum bitte über „Freier Zeitraum“ im Dashboard wählen.",
        ))
    start_date = f"{args.year}-01-01"
    current = date_sum(daily, start_date, data_through).load()
    periods.append(render_period(
        out=out, current=current, reference=None, key=f"{args.year}_ytd_live",
        title_label=f"Jahr aktuell {args.year}", subtitle_period=period_label_date(start_date, data_through),
        geojson=geojson, data_crs=data_crs, source_files=[], period_type="ytd_live",
        start_date=start_date, end_date=data_through,
        reference_note="Für diese vordefinierte 1-km-Karte wird der laufende Teilmonat nur als Summe gezeigt. Für einen tagesgenauen 1991–2020-Vergleich denselben Zeitraum bitte über „Freier Zeitraum“ im Dashboard wählen.",
    ))

    # Web-Raster für wirklich freie Start-/Enddaten.
    web_manifest = build_web_cumulative_package(
        daily=daily, year=args.year, data_through=data_through, factor=max(2, args.web_factor),
        out=out, work=work, cache_dir=Path(args.reference_cache), geojson=geojson, data_crs=data_crs,
    )

    # Kompakte historische Monatsraster 1931 bis Vorjahr. Bereits vorhandene
    # Raster aus dem hyras-data-Branch werden vom Workflow vorab wiederverwendet.
    _sample_vals, _sample_dates, hist_x, hist_y = sample_daily_for_web(daily, max(2, args.web_factor))
    del _sample_vals, _sample_dates
    historical_manifest = build_historical_monthly_package(
        out=out, work=work, factor=max(2, args.web_factor), current_year=args.year,
        expected_x=hist_x, expected_y=hist_y, data_crs=data_crs,
    )

    # Default: Sommer-bisher mit exaktem Vergleich, sonst letzter vollständiger Monat.
    default_key = f"{args.year}_summer_so_far_complete" if any(p["key"] == f"{args.year}_summer_so_far_complete" for p in periods) else f"{args.year}_{latest_month:02d}"

    metadata = {
        "schema_version": 5,
        "product": "DWD HYRAS-DE-PR",
        "resolution_km": 1,
        "reference": "1991-2020",
        "data_through": data_through,
        "daily_source_file": daily_name,
        "data_crs": data_crs.to_string(),
        "year": args.year,
        "latest_complete_month": latest_month,
        "default_period": default_key,
        "periods": periods,
        "web_manifest": "hyras_web_manifest.json",
        "web_sampling_km": web_manifest["web_sampling_km"],
        "historical_manifest": "hyras_historical_manifest.json",
        "historical_first_year": historical_manifest["first_year"],
        "historical_last_year": historical_manifest["last_year"],
        "note": "Version 15.3: wie 15.2 plus historische Monats-, Jahreszeiten- und Jahresauswahl ab 1931 über ein kompaktes 5-km-Webraster. Die aktuellen Presetkarten bleiben im nativen 1-km-Raster.",
    }
    (out / "hyras_index.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"period_count": len(periods), "default_period": default_key, "data_through": data_through}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
