#!/usr/bin/env python3
from __future__ import annotations

import calendar
import gzip
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
from PIL import Image
import requests
import xarray as xr

REFERENCE_START = 1991
REFERENCE_END = 2020
USER_AGENT = "climate-dashboard-hyras-live-temperature-reference/1.0 (+GitHub Actions; DWD Open Data)"
MONTH_ABBR = {1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC"}
MISSING_I16 = -32768
SCALE = 100


@dataclass(frozen=True)
class ParameterConfig:
    key: str
    prefix: str
    label: str
    source_label: str
    daily_base: str
    clim_base: str
    var_candidates: tuple[str, ...]


CONFIGS = {
    "tmean": ParameterConfig(
        key="tmean",
        prefix="tas",
        label="Tmean",
        source_label="HYRAS-DE-TAS",
        daily_base="https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_mean",
        clim_base="https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/air_temperature_mean",
        var_candidates=("tas","temperature","air_temperature","tmean"),
    ),
    "tmax": ParameterConfig(
        key="tmax",
        prefix="tasmax",
        label="Tmax",
        source_label="HYRAS-DE-TASMAX",
        daily_base="https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_max",
        clim_base="https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/air_temperature_max",
        var_candidates=("tasmax","tmax","air_temperature_max","temperature"),
    ),
    "tmin": ParameterConfig(
        key="tmin",
        prefix="tasmin",
        label="Tmin",
        source_label="HYRAS-DE-TASMIN",
        daily_base="https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_min",
        clim_base="https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/air_temperature_min",
        var_candidates=("tasmin","tmin","air_temperature_min","temperature"),
    ),
}


def get(url: str, timeout: int = 120) -> requests.Response:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response


def listing(url: str) -> str:
    return get(url + "/", 90).text


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Download: {url}", flush=True)
    with requests.get(url, stream=True, timeout=480, headers={"User-Agent": USER_AGENT}) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
    print(f"  -> {target.name}: {target.stat().st_size / 1024 / 1024:.1f} MB", flush=True)


def annual_files(config: ParameterConfig, text: str) -> dict[int, str]:
    pattern = re.compile(
        rf'href="(?P<filename>{config.prefix}_hyras_1_(?P<year>\d{{4}})_'
        rf'v(?P<major>\d+)-(?P<minor>\d+)_de\.nc)"'
    )
    best: dict[int, tuple[int,int,str]] = {}
    for match in pattern.finditer(text):
        year = int(match.group("year"))
        item = (int(match.group("major")), int(match.group("minor")), match.group("filename"))
        if year not in best or item[:2] > best[year][:2]:
            best[year] = item
    return {year:item[2] for year,item in best.items()}


def latest_clim_file(config: ParameterConfig, month: int, text: str) -> str:
    abbr = MONTH_ABBR[month]
    pattern = re.compile(
        rf'href="(?P<filename>{config.prefix}_hyras_1_{REFERENCE_START}_{REFERENCE_END}_'
        rf'v(?P<major>\d+)-(?P<minor>\d+)_de_{abbr}\.nc)"'
    )
    matches: list[tuple[int,int,str]] = []
    for match in pattern.finditer(text):
        matches.append((int(match.group("major")), int(match.group("minor")), match.group("filename")))
    if not matches:
        raise RuntimeError(f"Keine {config.key}-Klimadatei für {abbr} gefunden.")
    matches.sort()
    return matches[-1][2]


def pick_var(ds: xr.Dataset, config: ParameterConfig) -> xr.DataArray:
    for name in config.var_candidates:
        if name in ds.data_vars and ds[name].ndim >= 2:
            return ds[name]
    for _, da in ds.data_vars.items():
        if da.ndim >= 2:
            return da
    raise RuntimeError(f"Keine Temperaturvariable in {list(ds.data_vars)}")


def time_dim(da: xr.DataArray) -> str:
    for dim in da.dims:
        if dim.lower() == "time":
            return dim
    for dim in da.dims:
        coord = da.coords.get(dim)
        if coord is not None and np.issubdtype(coord.dtype, np.datetime64):
            return dim
    raise RuntimeError(f"Keine Zeitdimension: {da.dims}")


def spatial_dims(da: xr.DataArray) -> tuple[str,str]:
    td = None
    try:
        td = time_dim(da)
    except Exception:
        pass
    dims = [dim for dim in da.dims if dim != td]
    if len(dims) < 2:
        raise RuntimeError(f"Keine 2D-Raumdimensionen: {da.dims}")
    ydim = next((d for d in dims if d.lower() in {"y","lat","latitude","rlat"}), dims[-2])
    xdim = next((d for d in dims if d.lower() in {"x","lon","longitude","rlon"}), dims[-1])
    return ydim, xdim


def to_celsius(da: xr.DataArray) -> xr.DataArray:
    units = str(da.attrs.get("units", "")).lower().strip()
    if units == "k" or "kelvin" in units:
        return da - 273.15
    return da


def normalize(arr: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    arr = np.asarray(arr, dtype=np.float32)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    arr[~np.isfinite(arr)] = np.nan
    if len(x) > 1 and x[0] > x[-1]:
        x = x[::-1]
        arr = arr[..., ::-1]
    if len(y) > 1 and y[0] < y[-1]:
        y = y[::-1]
        arr = arr[..., ::-1, :]
    return arr, x, y


def prepare_daily(ds: xr.Dataset, config: ParameterConfig) -> tuple[xr.DataArray,str,np.ndarray,np.ndarray]:
    da = to_celsius(pick_var(ds, config)).squeeze(drop=True)
    td = time_dim(da)
    ydim, xdim = spatial_dims(da)
    da = da.transpose(td, ydim, xdim)
    x = np.asarray(da[xdim].values, dtype=np.float64)
    y = np.asarray(da[ydim].values, dtype=np.float64)
    return da, td, x, y


def static_clim(ds: xr.Dataset, config: ParameterConfig) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    da = to_celsius(pick_var(ds, config)).squeeze(drop=True)
    while da.ndim > 2:
        da = da.isel({da.dims[0]: 0})
    ydim, xdim = spatial_dims(da)
    da = da.transpose(ydim, xdim)
    return normalize(
        np.asarray(da.values, dtype=np.float32),
        np.asarray(da[xdim].values, dtype=np.float64),
        np.asarray(da[ydim].values, dtype=np.float64),
    )


def grid_ok(x: np.ndarray, y: np.ndarray, expected_x: np.ndarray, expected_y: np.ndarray) -> bool:
    return (
        x.shape == expected_x.shape and y.shape == expected_y.shape
        and np.allclose(x, expected_x) and np.allclose(y, expected_y)
    )


def current_mean(
    current_nc: Path,
    config: ParameterConfig,
    start_date: str,
    end_date: str,
) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    with xr.open_dataset(current_nc, decode_times=True) as ds:
        da, td, x, y = prepare_daily(ds, config)
        selected = da.where(
            (da[td] >= np.datetime64(start_date))
            & (da[td] <= np.datetime64(end_date)),
            drop=True,
        )
        if selected.sizes.get(td, 0) == 0:
            raise RuntimeError(f"Keine {config.key}-Tage für {start_date} bis {end_date}.")
        arr = np.asarray(selected.mean(td, skipna=True).values, dtype=np.float32)
    return normalize(arr, x, y)


def month_reference_cache_path(data_root: Path, config: ParameterConfig) -> Path:
    return data_root / "_temperature_reference" / f"{config.key}_current_month_1991_2020.npz"


def load_cached_month_reference(
    path: Path,
    month: int,
    expected_x: np.ndarray,
    expected_y: np.ndarray,
) -> np.ndarray | None:
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            if int(data["schema_version"]) != 1 or int(data["month"]) != month:
                return None
            if int(data["reference_start"]) != REFERENCE_START or int(data["reference_end"]) != REFERENCE_END:
                return None
            x = np.asarray(data["x"], dtype=np.float64)
            y = np.asarray(data["y"], dtype=np.float64)
            if not grid_ok(x, y, expected_x, expected_y):
                return None
            daily = np.asarray(data["daily"], dtype=np.float32)
            if daily.shape[1:] != (len(expected_y), len(expected_x)):
                return None
            return daily
    except Exception:
        return None


def build_month_reference(
    data_root: Path,
    work: Path,
    config: ParameterConfig,
    month: int,
    expected_x: np.ndarray,
    expected_y: np.ndarray,
) -> np.ndarray:
    cache_path = month_reference_cache_path(data_root, config)
    cached = load_cached_month_reference(cache_path, month, expected_x, expected_y)
    if cached is not None:
        print(f"{config.label}: tagesgenaue {MONTH_ABBR[month]}-Referenz 1991–2020 aus Cache.", flush=True)
        return cached

    print(
        f"{config.label}: baue tagesgenaue Referenz für {MONTH_ABBR[month]} "
        f"{REFERENCE_START}–{REFERENCE_END} einmalig …",
        flush=True,
    )
    files = annual_files(config, listing(config.daily_base))
    missing = [year for year in range(REFERENCE_START, REFERENCE_END + 1) if year not in files]
    if missing:
        raise RuntimeError(f"{config.key}: historische Tagesdateien fehlen: {missing}")

    ndays = calendar.monthrange(2000, month)[1]
    sums = np.zeros((ndays, len(expected_y), len(expected_x)), dtype=np.float32)
    counts = np.zeros((ndays, len(expected_y), len(expected_x)), dtype=np.uint8)
    history_work = work / "live_reference_years"
    history_work.mkdir(parents=True, exist_ok=True)

    for pos, year in enumerate(range(REFERENCE_START, REFERENCE_END + 1), 1):
        filename = files[year]
        target = history_work / filename
        if not target.exists():
            download(f"{config.daily_base}/{filename}", target)

        with xr.open_dataset(target, decode_times=True) as ds:
            da, td, x, y = prepare_daily(ds, config)
            dates = da[td].values.astype("datetime64[D]")
            for day in range(1, ndays + 1):
                try:
                    target_date = np.datetime64(date(year, month, day).isoformat())
                except ValueError:
                    continue
                indices = np.flatnonzero(dates == target_date)
                if len(indices) != 1:
                    continue
                arr = np.asarray(da.isel({td:int(indices[0])}).values, dtype=np.float32)
                arr, nx, ny = normalize(arr, x, y)
                if not grid_ok(nx, ny, expected_x, expected_y):
                    raise RuntimeError(f"{config.key}: Rasterabweichung in {filename}")
                valid = np.isfinite(arr)
                sums[day - 1][valid] += arr[valid]
                counts[day - 1][valid] += 1

        target.unlink(missing_ok=True)
        if pos == 1 or pos % 5 == 0 or pos == (REFERENCE_END - REFERENCE_START + 1):
            print(f"  {config.label} Referenz: {pos}/30 Jahre ({year})", flush=True)

    daily = np.full(sums.shape, np.nan, dtype=np.float32)
    valid = counts > 0
    daily[valid] = sums[valid] / counts[valid].astype(np.float32)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        cache_path,
        schema_version=np.int16(1),
        month=np.int16(month),
        reference_start=np.int16(REFERENCE_START),
        reference_end=np.int16(REFERENCE_END),
        daily=daily,
        x=np.asarray(expected_x, dtype=np.float64),
        y=np.asarray(expected_y, dtype=np.float64),
    )
    print(
        f"{config.label}: Referenzcache geschrieben: "
        f"{cache_path.stat().st_size / 1024 / 1024:.1f} MB",
        flush=True,
    )
    return daily


def monthly_reference(
    work: Path,
    config: ParameterConfig,
    months: list[int],
    target_year: int,
    expected_x: np.ndarray,
    expected_y: np.ndarray,
    clim_listing: str,
) -> tuple[np.ndarray,int]:
    weighted: np.ndarray | None = None
    total_days = 0
    clim_work = work / "live_reference_climatology"
    clim_work.mkdir(parents=True, exist_ok=True)

    for month in months:
        filename = latest_clim_file(config, month, clim_listing)
        target = clim_work / filename
        if not target.exists():
            download(f"{config.clim_base}/{filename}", target)
        with xr.open_dataset(target, decode_times=True) as ds:
            arr, x, y = static_clim(ds, config)
        if not grid_ok(x, y, expected_x, expected_y):
            raise RuntimeError(f"{config.key}: Klimaraster {filename} passt nicht.")
        days = calendar.monthrange(target_year, month)[1]
        weighted = arr * float(days) if weighted is None else weighted + arr * float(days)
        total_days += days

    if weighted is None or total_days <= 0:
        raise RuntimeError(f"{config.key}: keine Monatsreferenz.")
    return weighted, total_days


def period_reference(
    data_root: Path,
    work: Path,
    config: ParameterConfig,
    start_date: str,
    end_date: str,
    expected_x: np.ndarray,
    expected_y: np.ndarray,
    month_daily_ref: np.ndarray,
    clim_listing: str,
) -> np.ndarray:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    if start.year != end.year:
        raise RuntimeError(f"{config.key}: jahresübergreifende Live-Referenz noch nicht unterstützt.")

    weighted: np.ndarray | None = None
    total_days = 0
    cursor_month = start.month

    while cursor_month <= end.month:
        month_start_day = start.day if cursor_month == start.month else 1
        month_end_day = end.day if cursor_month == end.month else calendar.monthrange(end.year, cursor_month)[1]
        full_month = (
            month_start_day == 1
            and month_end_day == calendar.monthrange(end.year, cursor_month)[1]
        )

        if full_month:
            part, days = monthly_reference(
                work, config, [cursor_month], end.year,
                expected_x, expected_y, clim_listing,
            )
        else:
            if cursor_month != end.month:
                raise RuntimeError(f"{config.key}: unerwarteter Teilmonat {cursor_month}.")
            part_days = month_daily_ref[month_start_day - 1:month_end_day]
            part = np.nanmean(part_days, axis=0).astype(np.float32)
            days = month_end_day - month_start_day + 1

        weighted = part * float(days) if weighted is None else weighted + part * float(days)
        total_days += days
        cursor_month += 1

    if weighted is None or total_days <= 0:
        raise RuntimeError(f"{config.key}: leere Periodenreferenz {start_date}–{end_date}.")
    return weighted / float(total_days)


def boundary_overlay(data_root: Path) -> Path | None:
    idx = data_root / "hyras_index.json"
    if not idx.exists():
        return None
    try:
        payload = json.loads(idx.read_text(encoding="utf-8"))
        rel = payload.get("interactive", {}).get("boundary_overlay_1km")
        return data_root / rel if rel else None
    except Exception:
        return None


def anomaly_colormap():
    colors = ["#313695","#4575b4","#74add1","#abd9e9","#f7f7f7","#fdae61","#f46d43","#d73027","#a50026"]
    return LinearSegmentedColormap.from_list("hyras_live_temp_anomaly", colors)


def render_anomaly(
    arr: np.ndarray,
    overlay_path: Path | None,
    output: Path,
    config: ParameterConfig,
    label: str,
    start_date: str,
    end_date: str,
) -> None:
    fig = plt.figure(figsize=(7.4, 9.4), dpi=150)
    ax = fig.add_axes([0.055, 0.105, 0.89, 0.80])
    image = ax.imshow(arr, cmap=anomaly_colormap(), vmin=-6.0, vmax=6.0, interpolation="nearest")
    ax.set_axis_off()

    if overlay_path and overlay_path.exists():
        overlay = np.asarray(Image.open(overlay_path).convert("RGBA"))
        if overlay.shape[:2] == arr.shape:
            ax.imshow(overlay, interpolation="nearest")

    fig.suptitle(f"HYRAS {config.label} · {label}", fontsize=15, fontweight="bold", y=0.965)
    fig.text(
        0.5, 0.925,
        f"Abweichung zum Mittel 1991–2020 · {start_date} bis {end_date}",
        ha="center", va="center", fontsize=9,
    )
    cax = fig.add_axes([0.14, 0.055, 0.72, 0.025])
    colorbar = fig.colorbar(image, cax=cax, orientation="horizontal")
    colorbar.set_label("K", fontsize=9)
    colorbar.ax.tick_params(labelsize=8)
    fig.text(
        0.055, 0.018,
        f"Quelle: Deutscher Wetterdienst · {config.source_label} · Referenz 1991–2020",
        fontsize=7, color="#555555",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, facecolor="white", bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


def quantize(arr: np.ndarray) -> np.ndarray:
    out = np.full(arr.shape, MISSING_I16, dtype="<i2")
    valid = np.isfinite(arr)
    values = np.rint(arr[valid] * SCALE)
    out[valid] = np.clip(values, -32767, 32767).astype(np.int16)
    return out


def write_i16_gz(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=6) as handle:
        handle.write(quantize(arr).tobytes(order="C"))


def process_tmean(data_root: Path, work: Path) -> None:
    config = CONFIGS["tmean"]
    troot = data_root / "tmean"
    index_path = troot / "index.json"
    maps_path = troot / "regions/map_downloads.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    maps = json.loads(maps_path.read_text(encoding="utf-8"))
    year = int(index["year"])
    data_through = str(index["data_through"])
    month = int(data_through[5:7])
    current_nc = work / str(index["current_source_file"])
    if not current_nc.exists():
        download(f"{config.daily_base}/{index['current_source_file']}", current_nc)

    _, x, y = current_mean(current_nc, config, f"{year}-{month:02d}-01", data_through)
    month_ref = build_month_reference(data_root, work, config, month, x, y)
    clim_listing = listing(config.clim_base)
    overlay = boundary_overlay(data_root)

    periods_by_key = {str(item["key"]): item for item in index.get("periods", [])}
    for key, item in periods_by_key.items():
        if str(item.get("end_date")) != data_through or not bool(item.get("live")):
            continue
        start_date = str(item["start_date"])
        end_date = str(item["end_date"])
        current, cx, cy = current_mean(current_nc, config, start_date, end_date)
        if not grid_ok(cx, cy, x, y):
            raise RuntimeError(f"Tmean: aktuelles Raster passt bei {key} nicht.")
        reference = period_reference(
            data_root, work, config, start_date, end_date,
            x, y, month_ref, clim_listing,
        )
        anomaly = current - reference

        anomaly_rel = f"current/{key}_anomaly.i16.gz"
        write_i16_gz(troot / anomaly_rel, anomaly)
        item["anomaly"] = anomaly_rel
        item["reference_exact"] = True
        item["reference_note"] = (
            "Tagesgenauer Vergleich mit demselben Kalenderabschnitt des "
            "HYRAS-Mittels 1991–2020."
        )
        item.setdefault("stats", {})["reference_mean_c"] = round(float(np.nanmean(reference)), 2)
        item["stats"]["anomaly_mean_k"] = round(float(np.nanmean(anomaly)), 2)

        map_item = maps.setdefault("periods", {}).setdefault(key, {"label":item.get("label", key)})
        png_rel = f"download_maps/{key}_anomaly.png"
        render_anomaly(
            anomaly, overlay, troot / png_rel, config,
            str(item.get("label", key)), start_date, end_date,
        )
        map_item["anomaly"] = png_rel
        map_item["reference_exact"] = True
        map_item["reference_note"] = item["reference_note"]
        print(f"Tmean Live-Anomalie: {key}", flush=True)

    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    maps_path.write_text(json.dumps(maps, ensure_ascii=False, indent=2), encoding="utf-8")


def current_nc_for_regions(
    data_root: Path,
    work: Path,
    config: ParameterConfig,
    year: int,
) -> Path:
    files = annual_files(config, listing(config.daily_base))
    filename = files.get(year)
    if not filename:
        raise RuntimeError(f"{config.key}: aktuelle Jahresdatei {year} fehlt.")
    target = work / filename
    if not target.exists():
        download(f"{config.daily_base}/{filename}", target)
    return target


def process_extreme(data_root: Path, work: Path, parameter: str) -> None:
    config = CONFIGS[parameter]
    root = data_root / parameter
    index_path = root / "regions/index.json"
    maps_path = root / "regions/map_downloads.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    maps = json.loads(maps_path.read_text(encoding="utf-8"))
    year = int(index["year"])
    data_through = str(index["data_through"])
    month = int(data_through[5:7])
    current_nc = current_nc_for_regions(data_root, work, config, year)

    _, x, y = current_mean(current_nc, config, f"{year}-{month:02d}-01", data_through)
    month_ref = build_month_reference(data_root, work, config, month, x, y)
    clim_listing = listing(config.clim_base)
    overlay = boundary_overlay(data_root)

    for period in index.get("periods", []):
        key = str(period["key"])
        if str(period.get("end_date")) != data_through:
            continue
        map_item = maps.setdefault("periods", {}).get(key)
        if map_item is None or map_item.get("anomaly"):
            continue

        start_date = str(period["start_date"])
        end_date = str(period["end_date"])
        current, cx, cy = current_mean(current_nc, config, start_date, end_date)
        if not grid_ok(cx, cy, x, y):
            raise RuntimeError(f"{config.label}: aktuelles Raster passt bei {key} nicht.")
        reference = period_reference(
            data_root, work, config, start_date, end_date,
            x, y, month_ref, clim_listing,
        )
        anomaly = current - reference
        png_rel = f"download_maps/{key}_anomaly.png"
        render_anomaly(
            anomaly, overlay, root / png_rel, config,
            str(period.get("label", key)), start_date, end_date,
        )
        map_item["anomaly"] = png_rel
        map_item["reference_exact"] = True
        map_item["reference_note"] = (
            "Tagesgenauer Vergleich mit demselben Kalenderabschnitt des "
            "HYRAS-Mittels 1991–2020."
        )
        print(f"{config.label} Live-Anomalie: {key}", flush=True)

    maps_path.write_text(json.dumps(maps, ensure_ascii=False, indent=2), encoding="utf-8")


def update_reference_index(data_root: Path) -> None:
    ref_root = data_root / "_temperature_reference"
    ref_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "reference": f"{REFERENCE_START}-{REFERENCE_END}",
        "method": (
            "Tagesgenaue HYRAS-Rasterklimatologie des jeweils laufenden Monats. "
            "Die 30 historischen Jahresdateien werden nur beim Monatswechsel "
            "einmalig verarbeitet; danach wird der kompakte Monatscache wiederverwendet."
        ),
        "files": {},
    }
    for key in CONFIGS:
        path = month_reference_cache_path(data_root, CONFIGS[key])
        if not path.exists():
            continue
        try:
            with np.load(path, allow_pickle=False) as data:
                payload["files"][key] = {
                    "file": path.name,
                    "month": int(data["month"]),
                    "reference_start": int(data["reference_start"]),
                    "reference_end": int(data["reference_end"]),
                    "size_mb": round(path.stat().st_size / 1024 / 1024, 1),
                }
        except Exception:
            pass
    (ref_root / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def validate_live_anomalies(data_root: Path) -> None:
    errors: list[str] = []

    tmean_index = json.loads((data_root / "tmean/index.json").read_text())
    tmean_maps = json.loads((data_root / "tmean/regions/map_downloads.json").read_text())
    through = str(tmean_index["data_through"])
    for item in tmean_index.get("periods", []):
        if bool(item.get("live")) and str(item.get("end_date")) == through:
            key = str(item["key"])
            if not item.get("anomaly"):
                errors.append(f"tmean index ohne Live-Anomalie: {key}")
            if not tmean_maps.get("periods", {}).get(key, {}).get("anomaly"):
                errors.append(f"tmean maps ohne Live-Anomalie: {key}")

    for parameter in ("tmax","tmin"):
        idx = json.loads((data_root / parameter / "regions/index.json").read_text())
        maps = json.loads((data_root / parameter / "regions/map_downloads.json").read_text())
        through = str(idx["data_through"])
        for period in idx.get("periods", []):
            if str(period.get("end_date")) != through:
                continue
            key = str(period["key"])
            if not maps.get("periods", {}).get(key, {}).get("anomaly"):
                errors.append(f"{parameter} maps ohne Live-Anomalie: {key}")

    if errors:
        raise RuntimeError("\n".join(errors))
    print("Live-Anomalieprüfung OK.", flush=True)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="/tmp/hyras-data")
    parser.add_argument("--tmean-work", default="/tmp/hyras-tmean-work")
    parser.add_argument("--tmax-work", default="/tmp/hyras-tmax-work")
    parser.add_argument("--tmin-work", default="/tmp/hyras-tmin-work")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    print("=== HYRAS TEMPERATUR · TAGESGENAUE LIVE-ANOMALIEN 1991–2020 ===", flush=True)

    process_tmean(data_root, Path(args.tmean_work))
    process_extreme(data_root, Path(args.tmax_work), "tmax")
    process_extreme(data_root, Path(args.tmin_work), "tmin")
    update_reference_index(data_root)
    validate_live_anomalies(data_root)

    print("Tagesgenaue Temperatur-Live-Anomalien fertig.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
