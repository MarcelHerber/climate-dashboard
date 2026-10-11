#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import cdsapi
import numpy as np
import xarray as xr

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm
import cartopy.crs as ccrs
import cartopy.feature as cfeature

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "era5_europe"
MAP_DIR = OUT_DIR / "maps"
ARCHIVE_DIR = OUT_DIR / "archive"
INDEX_PATH = OUT_DIR / "index.json"
CACHE_DIR = ROOT / ".era5_europe_cache"

PRESSURE_DATASET = "reanalysis-era5-pressure-levels-monthly-means"
SINGLE_DATASET = "reanalysis-era5-single-levels-monthly-means"
HISTORY_START = 1940
REFERENCE_START = 1991
REFERENCE_END = 2020
AREA = [80.0, -40.0, 20.0, 50.0]
GRID = [0.25, 0.25]

PRODUCTS = {
    "t850": {
        "label": "Temperatur 850 hPa",
        "short_label": "T850",
        "dataset": "pressure",
        "variable": "temperature",
        "aliases": ("t", "temperature"),
        "level": "850",
        "unit": "°C",
        "rank_label": "1 = wärmster",
        "absolute_cmap": "coolwarm",
        "anomaly_cmap": "RdBu_r",
        "anomaly_bounds": [-8, -6, -4, -3, -2, -1, -0.5, 0, 0.5, 1, 2, 3, 4, 6, 8],
    },
    "z500": {
        "label": "Geopotentialhöhe 500 hPa",
        "short_label": "Z500",
        "dataset": "pressure",
        "variable": "geopotential",
        "aliases": ("z", "geopotential"),
        "level": "500",
        "unit": "gpm",
        "rank_label": "1 = höchste Geopotentialhöhe",
        "absolute_cmap": "viridis",
        "anomaly_cmap": "RdBu_r",
        "anomaly_bounds": [-240, -180, -120, -80, -50, -30, -15, 0, 15, 30, 50, 80, 120, 180, 240],
    },
    "wind300": {
        "label": "Wind 300 hPa",
        "short_label": "300-hPa-Wind",
        "dataset": "pressure_wind",
        "variables": ("u_component_of_wind", "v_component_of_wind"),
        "aliases_u": ("u", "u_component_of_wind"),
        "aliases_v": ("v", "v_component_of_wind"),
        "level": "300",
        "unit": "m/s",
        "rank_label": "1 = stärkster Wind",
        "absolute_cmap": "plasma",
        "anomaly_cmap": "RdBu_r",
        "anomaly_bounds": [-18, -14, -10, -7, -5, -3, -1.5, 0, 1.5, 3, 5, 7, 10, 14, 18],
    },
    "mslp": {
        "label": "Luftdruck auf Meereshöhe",
        "short_label": "MSLP",
        "dataset": "single",
        "variable": "mean_sea_level_pressure",
        "aliases": ("msl", "mean_sea_level_pressure"),
        "unit": "hPa",
        "rank_label": "1 = höchster Luftdruck",
        "absolute_cmap": "viridis",
        "anomaly_cmap": "RdBu_r",
        "anomaly_bounds": [-16, -12, -9, -6, -4, -2, -1, 0, 1, 2, 4, 6, 9, 12, 16],
    },
}

MONTH_NAMES = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}


def previous_month(year: int, month: int, offset: int = 1) -> tuple[int, int]:
    value = year * 12 + month - 1 - offset
    return value // 12, value % 12 + 1


def latest_complete_month(today: date) -> tuple[int, int]:
    # ERA5-Monatsmittel sind typischerweise um den 6. des Folgemonats verfügbar.
    return previous_month(today.year, today.month, 1 if today.day >= 8 else 2)


def cds_client() -> cdsapi.Client:
    return cdsapi.Client(quiet=False, progress=False)


def find_name(container, aliases: tuple[str, ...]) -> str:
    names = [str(name) for name in container]
    lower = {name.lower(): name for name in names}
    for alias in aliases:
        if alias.lower() in lower:
            return lower[alias.lower()]
    for name in names:
        lname = name.lower()
        if any(alias.lower() in lname for alias in aliases):
            return name
    raise KeyError(f"Keine passende Variable für {aliases}; vorhanden: {names[:30]}")


def time_name(ds: xr.Dataset, da: xr.DataArray) -> str:
    for candidate in ("valid_time", "time", "date"):
        if candidate in da.coords or candidate in ds.coords:
            return candidate
    for dim in da.dims:
        coord = da.coords.get(dim)
        if coord is not None and np.issubdtype(coord.dtype, np.datetime64):
            return str(dim)
    raise RuntimeError(f"Keine Zeitdimension erkannt: {da.dims}")


def normalize_dataarray(ds: xr.Dataset, aliases: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    var = find_name(ds.data_vars, aliases)
    lat_name = find_name(ds.coords, ("latitude", "lat"))
    lon_name = find_name(ds.coords, ("longitude", "lon"))
    da = ds[var]
    tname = time_name(ds, da)

    for dim in list(da.dims):
        if dim not in {tname, lat_name, lon_name} and da.sizes.get(dim, 0) == 1:
            da = da.isel({dim: 0}, drop=True)
    extra = [dim for dim in da.dims if dim not in {tname, lat_name, lon_name}]
    if extra:
        raise RuntimeError(f"Unerwartete Dimensionen in {var}: {extra}")

    da = da.transpose(tname, lat_name, lon_name)
    lat = np.asarray(da[lat_name].values, dtype=np.float64)
    lon = np.asarray(da[lon_name].values, dtype=np.float64)
    if lat[0] < lat[-1]:
        da = da.sortby(lat_name, ascending=False)
        lat = np.asarray(da[lat_name].values, dtype=np.float64)
    if lon.max() > 180:
        new_lon = ((da[lon_name] + 180) % 360) - 180
        da = da.assign_coords({lon_name: new_lon}).sortby(lon_name)
        lon = np.asarray(da[lon_name].values, dtype=np.float64)
    times = np.asarray(da[tname].values)
    values = np.asarray(da.values, dtype=np.float32)
    return lat, lon, times, values


def years_from_times(times: np.ndarray) -> np.ndarray:
    return np.asarray(
        [int(np.datetime_as_string(np.datetime64(value), unit="D")[:4]) for value in times],
        dtype=int,
    )


def request_pressure(
    client: cdsapi.Client,
    *,
    variable: list[str],
    level: str,
    years: list[int],
    month: int,
    target: Path,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": variable,
        "pressure_level": [str(level)],
        "year": [f"{year:04d}" for year in years],
        "month": [f"{month:02d}"],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA,
        "grid": GRID,
    }
    print(
        f"CDS ERA5 pressure: {variable} · {level} hPa · {years[0]}–{years[-1]} · {month:02d}",
        flush=True,
    )
    client.retrieve(PRESSURE_DATASET, request, str(target))


def request_single(
    client: cdsapi.Client,
    *,
    variable: str,
    years: list[int],
    month: int,
    target: Path,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": [variable],
        "year": [f"{year:04d}" for year in years],
        "month": [f"{month:02d}"],
        "time": ["00:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA,
        "grid": GRID,
    }
    print(
        f"CDS ERA5 single level: {variable} · {years[0]}–{years[-1]} · {month:02d}",
        flush=True,
    )
    client.retrieve(SINGLE_DATASET, request, str(target))


def load_product(client: cdsapi.Client, key: str, year: int, month: int, force: bool):
    meta = PRODUCTS[key]
    years = list(range(HISTORY_START, year + 1))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}_{month:02d}_{HISTORY_START}_{year}.nc"
    if force and path.exists():
        path.unlink()

    if not path.exists():
        if meta["dataset"] == "pressure":
            request_pressure(
                client,
                variable=[str(meta["variable"])],
                level=str(meta["level"]),
                years=years,
                month=month,
                target=path,
            )
        elif meta["dataset"] == "pressure_wind":
            request_pressure(
                client,
                variable=list(meta["variables"]),
                level=str(meta["level"]),
                years=years,
                month=month,
                target=path,
            )
        else:
            request_single(
                client,
                variable=str(meta["variable"]),
                years=years,
                month=month,
                target=path,
            )

    ds = xr.open_dataset(path)
    try:
        if key == "wind300":
            lat, lon, times, u = normalize_dataarray(ds, tuple(meta["aliases_u"]))
            lat2, lon2, times2, v = normalize_dataarray(ds, tuple(meta["aliases_v"]))
            if not (np.allclose(lat, lat2) and np.allclose(lon, lon2) and np.array_equal(times, times2)):
                raise RuntimeError("U/V-Raster oder Zeitachse stimmen nicht überein.")
            values = np.hypot(u, v).astype(np.float32)
        else:
            lat, lon, times, values = normalize_dataarray(ds, tuple(meta["aliases"]))

        if key == "t850":
            values = (values - 273.15).astype(np.float32)
        elif key == "z500":
            values = (values / 9.80665).astype(np.float32)
        elif key == "mslp":
            values = (values / 100.0).astype(np.float32)

        data_years = years_from_times(times)
        order = np.argsort(data_years)
        data_years = data_years[order]
        values = values[order]
        expected = np.arange(HISTORY_START, year + 1, dtype=int)
        if not np.array_equal(data_years, expected):
            raise RuntimeError(
                f"{key}: Jahre unvollständig. Erwartet {expected[0]}–{expected[-1]}, "
                f"erhalten {data_years[:3].tolist()}…{data_years[-3:].tolist()}"
            )
        return lat, lon, data_years, values
    finally:
        ds.close()


def area_weighted_mean(field: np.ndarray, lat: np.ndarray) -> float:
    values = np.asarray(field, dtype=float)
    weights = np.cos(np.deg2rad(np.asarray(lat, dtype=float)))[:, None]
    valid = np.isfinite(values)
    if not valid.any():
        return float("nan")
    numerator = np.nansum(np.where(valid, values * weights, 0.0))
    denominator = np.sum(np.where(valid, weights, 0.0))
    return float(numerator / denominator) if denominator else float("nan")


def area_weighted_fraction(mask: np.ndarray, valid: np.ndarray, lat: np.ndarray) -> float:
    mask = np.asarray(mask, dtype=bool)
    valid = np.asarray(valid, dtype=bool)
    weights = np.cos(np.deg2rad(np.asarray(lat, dtype=float)))[:, None]
    denom = np.sum(np.where(valid, weights, 0.0))
    if not denom:
        return float("nan")
    num = np.sum(np.where(valid & mask, weights, 0.0))
    return float(num / denom * 100.0)


def rank_field(current: np.ndarray, history: np.ndarray) -> np.ndarray:
    current = np.asarray(current, dtype=np.float32)
    history = np.asarray(history, dtype=np.float32)
    valid_current = np.isfinite(current)
    valid_history = np.isfinite(history)
    rank = 1 + np.sum(valid_history & (history > current[None, ...]), axis=0)
    rank = rank.astype(np.float32)
    rank[~valid_current] = np.nan
    return rank


def setup_axis(ax) -> None:
    ax.set_extent([AREA[1], AREA[3], AREA[2], AREA[0]], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m", linewidth=0.7)
    ax.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.45)
    ax.add_feature(cfeature.LAKES.with_scale("50m"), facecolor="none", edgecolor="0.45", linewidth=0.35)


def render_field(
    field: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    *,
    title: str,
    subtitle: str,
    unit: str,
    filename: Path,
    cmap: str,
    bounds: list[float] | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
) -> None:
    filename.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(12.6, 8.2), dpi=150)
    ax = plt.axes(projection=ccrs.PlateCarree())
    setup_axis(ax)
    kwargs = {"cmap": cmap, "shading": "auto", "transform": ccrs.PlateCarree()}
    if bounds is not None:
        norm = BoundaryNorm(bounds, plt.get_cmap(cmap).N, clip=True)
        kwargs["norm"] = norm
    else:
        kwargs["vmin"] = vmin
        kwargs["vmax"] = vmax
    mesh = ax.pcolormesh(lon, lat, field, **kwargs)
    ax.set_title(title, fontsize=15, fontweight="bold", pad=12)
    ax.text(
        0.5, 1.005, subtitle, transform=ax.transAxes, ha="center", va="bottom",
        fontsize=9.5, color="0.35"
    )
    cb = fig.colorbar(mesh, ax=ax, orientation="horizontal", pad=0.045, fraction=0.055)
    cb.set_label(unit)
    fig.tight_layout()
    fig.savefig(filename, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def robust_range(field: np.ndarray, low: float = 2.0, high: float = 98.0) -> tuple[float, float]:
    valid = np.asarray(field, dtype=float)
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        return 0.0, 1.0
    a, b = np.percentile(valid, [low, high])
    if not np.isfinite(a) or not np.isfinite(b) or math.isclose(float(a), float(b)):
        return float(np.nanmin(valid)), float(np.nanmax(valid) + 1e-6)
    return float(a), float(b)


def build(year: int, month: int, force: bool = False) -> Path:
    if year < REFERENCE_END:
        raise ValueError("Zieljahr liegt vor dem Referenzzeitraum.")
    MAP_DIR.mkdir(parents=True, exist_ok=True)
    client = cds_client()
    period_key = f"{year:04d}-{month:02d}"
    month_label = f"{MONTH_NAMES[month]} {year}"

    payload_products: dict[str, dict] = {}
    grid_meta = None

    for key, meta in PRODUCTS.items():
        lat, lon, years, values = load_product(client, key, year, month, force)
        if grid_meta is None:
            grid_meta = {
                "north": float(lat[0]),
                "south": float(lat[-1]),
                "west": float(lon[0]),
                "east": float(lon[-1]),
                "nlat": int(lat.size),
                "nlon": int(lon.size),
                "resolution": "0,25°",
            }

        current_mask = years == year
        ref_mask = (years >= REFERENCE_START) & (years <= REFERENCE_END)
        history_mask = years < year
        if current_mask.sum() != 1 or ref_mask.sum() != (REFERENCE_END - REFERENCE_START + 1):
            raise RuntimeError(f"{key}: aktuelle oder Referenzjahre unvollständig.")

        current = values[current_mask][0]
        reference = np.nanmean(values[ref_mask], axis=0).astype(np.float32)
        anomaly = (current - reference).astype(np.float32)
        history = values[history_mask]
        rank = rank_field(current, history)
        valid = np.isfinite(rank)
        comparison_years = int(history.shape[0])
        total_positions = comparison_years + 1

        abs_file = MAP_DIR / f"{key}_absolute.png"
        anom_file = MAP_DIR / f"{key}_anomaly.png"
        rank_file = MAP_DIR / f"{key}_rank.png"

        vmin, vmax = robust_range(current)
        render_field(
            current, lat, lon,
            title=f"{meta['label']} · {month_label}",
            subtitle="ERA5 Monatsmittel",
            unit=str(meta["unit"]),
            filename=abs_file,
            cmap=str(meta["absolute_cmap"]),
            vmin=vmin,
            vmax=vmax,
        )
        render_field(
            anomaly, lat, lon,
            title=f"{meta['label']} · Abweichung {month_label}",
            subtitle=f"gegenüber {REFERENCE_START}–{REFERENCE_END}",
            unit="K" if key == "t850" else str(meta["unit"]),
            filename=anom_file,
            cmap=str(meta["anomaly_cmap"]),
            bounds=list(meta["anomaly_bounds"]),
        )
        render_field(
            rank, lat, lon,
            title=f"{meta['label']} · historischer Rang {month_label}",
            subtitle=f"{HISTORY_START}–{year} · {meta['rank_label']}",
            unit=f"Rang 1–{total_positions}",
            filename=rank_file,
            cmap="Spectral",
            vmin=1,
            vmax=total_positions,
        )

        payload_products[key] = {
            "label": meta["label"],
            "short_label": meta["short_label"],
            "unit": meta["unit"],
            "level_hpa": int(meta["level"]) if "level" in meta else None,
            "absolute": {"file": abs_file.relative_to(ROOT).as_posix()},
            "anomaly": {
                "file": anom_file.relative_to(ROOT).as_posix(),
                "reference_period": f"{REFERENCE_START}–{REFERENCE_END}",
            },
            "rank": {
                "file": rank_file.relative_to(ROOT).as_posix(),
                "history_start": HISTORY_START,
                "history_end": year,
                "comparison_years": comparison_years,
                "total_rank_positions": total_positions,
                "direction": meta["rank_label"],
                "rank1_area_percent": area_weighted_fraction(rank <= 1, valid, lat),
                "top3_area_percent": area_weighted_fraction(rank <= 3, valid, lat),
            },
            "stats": {
                "current_area_mean": area_weighted_mean(current, lat),
                "reference_area_mean": area_weighted_mean(reference, lat),
                "anomaly_area_mean": area_weighted_mean(anomaly, lat),
            },
        }

    archive_dir = ARCHIVE_DIR / period_key
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_products = {}
    for key, item in payload_products.items():
        archived = json.loads(json.dumps(item))
        for view in ("absolute", "anomaly", "rank"):
            source = ROOT / archived[view]["file"]
            dest = archive_dir / source.name
            shutil.copy2(source, dest)
            archived[view]["file"] = dest.relative_to(ROOT).as_posix()
        archived_products[key] = archived

    archive_index = archive_dir / "index.json"
    archive_payload = {
        "ready": True,
        "period": period_key,
        "year": year,
        "month": month,
        "label": month_label,
        "products": archived_products,
    }
    archive_index.write_text(
        json.dumps(archive_payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    available_periods = sorted(
        path.parent.name for path in ARCHIVE_DIR.glob("????-??/index.json")
    )
    payload = {
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest_month_key": period_key,
        "data_through": f"{year:04d}-{month:02d}",
        "label": month_label,
        "source": "Copernicus Climate Change Service / ECMWF · ERA5 monthly means",
        "datasets": {
            "pressure_levels": PRESSURE_DATASET,
            "single_levels": SINGLE_DATASET,
        },
        "history_start": HISTORY_START,
        "reference_period": f"{REFERENCE_START}–{REFERENCE_END}",
        "coverage": {
            "north": AREA[0], "west": AREA[1], "south": AREA[2], "east": AREA[3]
        },
        "grid": grid_meta,
        "products": payload_products,
        "available_periods": available_periods,
        "archive_index_pattern": "era5_europe/archive/{period}/index.json",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"ERA5 Europa fertig: {month_label} · {len(payload_products)} Produkte · "
        f"Historie {HISTORY_START}–{year}",
        flush=True,
    )
    return INDEX_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="ERA5-Europa-Monatskarten für freie Atmosphäre und MSLP.")
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.year is None or args.month is None:
        year, month = latest_complete_month(date.today())
    else:
        year, month = int(args.year), int(args.month)
    if not 1 <= month <= 12:
        raise SystemExit("month muss 1–12 sein.")

    build(year, month, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
