from __future__ import annotations

import json
import math
import os
import tempfile
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import xarray as xr

from dwd_common import atomic_write_json, read_json

STATE_VERSION = 1
OUTPUT_VERSION = 1
REFERENCE_START = 1991
REFERENCE_END = 2020
FULL_REBUILD_DAYS = 365
MONTHLY_REFRESH_DAYS = 7

PSL_NCSS_BASE = "https://psl.noaa.gov/thredds/ncss/grid/Datasets/noaa.oisst.v2.highres"
DAILY_URL = PSL_NCSS_BASE + "/sst.day.mean.{year}.nc"
MONTHLY_URL = PSL_NCSS_BASE + "/sst.mon.mean.nc"

# Das Polygon schneidet Atlantik und Schwarzes Meer grob ab. Landpunkte werden
# zusätzlich automatisch über die Fehlwertmaske von OISST ausgeschlossen.
MEDITERRANEAN_POLYGON = [
    (-5.8, 35.4), (-5.0, 36.6), (-2.0, 37.8), (0.0, 40.2),
    (2.5, 42.3), (6.0, 43.5), (9.5, 44.2), (12.0, 45.8),
    (15.0, 45.5), (18.2, 44.5), (20.0, 41.6), (23.0, 40.2),
    (26.0, 41.0), (28.0, 40.2), (29.3, 37.8), (33.0, 36.2),
    (36.6, 36.8), (36.8, 31.0), (32.0, 30.2), (27.0, 30.0),
    (22.0, 30.0), (18.0, 30.5), (15.0, 32.0), (12.5, 34.0),
    (10.0, 36.0), (7.0, 36.8), (4.0, 36.0), (1.0, 35.0),
    (-2.0, 35.0), (-5.8, 35.4),
]

REGIONS = [
    {"id": "med", "label": "Gesamtes Mittelmeer", "bounds": [-6.0, 37.0, 30.0, 46.0]},
    {"id": "west", "label": "Westliches Mittelmeer", "bounds": [-6.0, 9.5, 30.0, 46.0]},
    {"id": "central", "label": "Zentrales Mittelmeer", "bounds": [9.5, 20.0, 30.0, 46.0]},
    {"id": "east", "label": "Östliches Mittelmeer", "bounds": [20.0, 37.0, 30.0, 46.0]},
    {"id": "adriatic", "label": "Adriatisches Meer", "bounds": [12.0, 20.5, 39.0, 46.0]},
    {"id": "aegean", "label": "Ägäisches Meer", "bounds": [22.0, 29.5, 34.0, 41.5]},
    {"id": "tyrrhenian", "label": "Tyrrhenisches Meer", "bounds": [8.0, 16.5, 36.0, 44.5]},
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _days_since(value: str | None) -> int:
    if not value:
        return 10_000
    try:
        then = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return 10_000
    return (date.today() - then).days


def _download_subset(url: str, params: dict[str, str], label: str) -> Path:
    last_error: Exception | None = None
    for attempt in range(1, 5):
        path: Path | None = None
        try:
            with requests.get(
                url,
                params=params,
                timeout=(30, 360),
                stream=True,
                headers={"User-Agent": "climate-dashboard/1.0 (GitHub Actions)"},
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" in content_type:
                    snippet = response.text[:300]
                    raise RuntimeError(f"{label}: Server lieferte HTML statt NetCDF: {snippet}")
                fd, filename = tempfile.mkstemp(prefix="med_sst_", suffix=".nc")
                os.close(fd)
                path = Path(filename)
                size = 0
                with path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        size += len(chunk)
                if size < 10_000:
                    raise RuntimeError(f"{label}: NetCDF-Antwort ist unerwartet klein ({size} Bytes).")
                return path
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if path is not None:
                path.unlink(missing_ok=True)
            if attempt < 4:
                time.sleep(attempt * 5)
    raise RuntimeError(f"{label} konnte nicht geladen werden: {last_error}")


def _open_subset(path: Path) -> xr.Dataset:
    try:
        with xr.open_dataset(path, engine="scipy", decode_times=True) as dataset:
            loaded = dataset.load()
    finally:
        path.unlink(missing_ok=True)
    if "sst" not in loaded:
        raise RuntimeError("NOAA-NetCDF enthält keine Variable 'sst'.")
    if not {"time", "lat", "lon"}.issubset(loaded.coords):
        raise RuntimeError("NOAA-NetCDF enthält nicht alle Koordinaten time/lat/lon.")
    return loaded


def _subset_params(time_value: str = "all") -> dict[str, str]:
    return {
        "var": "sst",
        "north": "46",
        "south": "30",
        "west": "-6",
        "east": "37",
        "time": time_value,
        "accept": "netcdf",
        "addLatLon": "true",
    }


def _polygon_mask(lon: np.ndarray, lat: np.ndarray, polygon: list[tuple[float, float]]) -> np.ndarray:
    x = np.asarray(lon, dtype=float)
    y = np.asarray(lat, dtype=float)
    inside = np.zeros(np.broadcast(x, y).shape, dtype=bool)
    x = np.broadcast_to(x, inside.shape)
    y = np.broadcast_to(y, inside.shape)
    xj, yj = polygon[-1]
    for xi, yi in polygon:
        crosses = (yi > y) != (yj > y)
        denom = (yj - yi) if abs(yj - yi) > 1e-12 else 1e-12
        edge_x = (xj - xi) * (y - yi) / denom + xi
        inside ^= crosses & (x < edge_x)
        xj, yj = xi, yi
    return inside


def _prepare_dataarray(dataset: xr.Dataset) -> xr.DataArray:
    data = dataset["sst"].squeeze(drop=True)
    extra_dims = [dim for dim in data.dims if dim not in {"time", "lat", "lon"}]
    for dim in extra_dims:
        data = data.isel({dim: 0}, drop=True)
    data = data.transpose("time", "lat", "lon")
    lon = ((data["lon"] + 180) % 360) - 180
    data = data.assign_coords(lon=lon).sortby("lon")
    return data.where(np.isfinite(data))


def _region_masks(data: xr.DataArray) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    lon2d, lat2d = np.meshgrid(data["lon"].values, data["lat"].values)
    med_mask = _polygon_mask(lon2d, lat2d, MEDITERRANEAN_POLYGON)
    masks: dict[str, np.ndarray] = {}
    counts: dict[str, int] = {}
    sample_valid = np.isfinite(data.isel(time=0).values)
    for region in REGIONS:
        west, east, south, north = region["bounds"]
        box = (lon2d >= west) & (lon2d < east) & (lat2d >= south) & (lat2d <= north)
        mask = med_mask & box
        masks[region["id"]] = mask
        counts[region["id"]] = int(np.count_nonzero(mask & sample_valid))
    if counts.get("med", 0) < 1000:
        raise RuntimeError(f"Mittelmeer-Maske enthält unerwartet wenige Ozeangitterpunkte: {counts.get('med', 0)}")
    return masks, counts


def _weighted_region_means(dataset: xr.Dataset) -> tuple[pd.DatetimeIndex, dict[str, np.ndarray], dict[str, int]]:
    data = _prepare_dataarray(dataset)
    masks, counts = _region_masks(data)
    values = np.asarray(data.values, dtype=np.float64)
    lat_weights = np.cos(np.deg2rad(data["lat"].values))[:, None]
    result: dict[str, np.ndarray] = {}
    for region in REGIONS:
        region_id = region["id"]
        spatial_weight = np.where(masks[region_id], lat_weights, 0.0)
        valid = np.isfinite(values)
        weighted = np.where(valid, values * spatial_weight[None, :, :], 0.0)
        denominator = np.where(valid, spatial_weight[None, :, :], 0.0).sum(axis=(1, 2))
        numerator = weighted.sum(axis=(1, 2))
        means = np.divide(
            numerator,
            denominator,
            out=np.full(numerator.shape, np.nan, dtype=float),
            where=denominator > 0,
        )
        result[region_id] = means
    times = pd.DatetimeIndex(pd.to_datetime(data["time"].values))
    return times, result, counts


def _non_leap_keys() -> list[str]:
    base = pd.date_range("2001-01-01", "2001-12-31", freq="D")
    return [timestamp.strftime("%m-%d") for timestamp in base]


def _round_or_none(value: Any, digits: int = 3) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def _build_daily_climatology() -> tuple[dict[str, dict[str, list[float | None]]], dict[str, int]]:
    keys = _non_leap_keys()
    samples: dict[str, dict[str, list[float]]] = {
        region["id"]: {key: [] for key in keys} for region in REGIONS
    }
    point_counts: dict[str, int] = {}
    for year in range(REFERENCE_START, REFERENCE_END + 1):
        print(f"Mittelmeer-SST: Tagesklimatologie {year}")
        path = _download_subset(DAILY_URL.format(year=year), _subset_params(), f"OISST-Tagesdaten {year}")
        dataset = _open_subset(path)
        times, means, counts = _weighted_region_means(dataset)
        point_counts = counts
        for index, timestamp in enumerate(times):
            key = timestamp.strftime("%m-%d")
            if key == "02-29" or key not in samples["med"]:
                continue
            for region in REGIONS:
                value = means[region["id"]][index]
                if math.isfinite(float(value)):
                    samples[region["id"]][key].append(float(value))

    climatology: dict[str, dict[str, list[float | None]]] = {}
    for region in REGIONS:
        region_id = region["id"]
        stats = {name: [] for name in ("mean", "p05", "p95", "min", "max", "count")}
        for key in keys:
            values = np.asarray(samples[region_id][key], dtype=float)
            if values.size < 25:
                raise RuntimeError(
                    f"Zu wenige Referenzwerte für {region['label']} am {key}: {values.size}."
                )
            stats["mean"].append(_round_or_none(np.mean(values)))
            stats["p05"].append(_round_or_none(np.percentile(values, 5)))
            stats["p95"].append(_round_or_none(np.percentile(values, 95)))
            stats["min"].append(_round_or_none(np.min(values)))
            stats["max"].append(_round_or_none(np.max(values)))
            stats["count"].append(int(values.size))
        climatology[region_id] = stats
    return climatology, point_counts


def _build_monthly_history() -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    print("Mittelmeer-SST: monatliche Zeitreihe wird aktualisiert")
    path = _download_subset(MONTHLY_URL, _subset_params(), "OISST-Monatsdaten")
    dataset = _open_subset(path)
    times, means, counts = _weighted_region_means(dataset)
    raw: dict[str, list[dict[str, Any]]] = {region["id"]: [] for region in REGIONS}
    for index, timestamp in enumerate(times):
        month_key = timestamp.strftime("%Y-%m")
        for region in REGIONS:
            value = _round_or_none(means[region["id"]][index])
            if value is not None:
                raw[region["id"]].append({"date": month_key, "sst": value})

    result: dict[str, list[dict[str, Any]]] = {}
    for region in REGIONS:
        region_id = region["id"]
        climate_by_month: dict[int, float] = {}
        for month in range(1, 13):
            climate_values = [
                item["sst"]
                for item in raw[region_id]
                if REFERENCE_START <= int(item["date"][:4]) <= REFERENCE_END
                and int(item["date"][5:7]) == month
            ]
            if len(climate_values) < 25:
                raise RuntimeError(
                    f"Zu wenige Monatswerte für die Klimatologie {region['label']} Monat {month}: {len(climate_values)}."
                )
            climate_by_month[month] = float(np.mean(climate_values))
        result[region_id] = [
            {
                "date": item["date"],
                "sst": item["sst"],
                "anomaly": _round_or_none(item["sst"] - climate_by_month[int(item["date"][5:7])]),
            }
            for item in raw[region_id]
        ]
    return result, counts


def _current_year_daily(
    climatology: dict[str, dict[str, list[float | None]]],
) -> tuple[dict[str, dict[str, Any]], str, dict[str, int]]:
    year = date.today().year
    print(f"Mittelmeer-SST: aktuelles Jahr {year}")
    path = _download_subset(DAILY_URL.format(year=year), _subset_params(), f"OISST-Tagesdaten {year}")
    dataset = _open_subset(path)
    times, means, counts = _weighted_region_means(dataset)
    keys = _non_leap_keys()
    key_index = {key: index for index, key in enumerate(keys)}
    current: dict[str, dict[str, Any]] = {}
    latest_date = None
    for region in REGIONS:
        region_id = region["id"]
        daily: list[dict[str, Any]] = []
        anomalies: list[float] = []
        sst_values: list[float] = []
        for index, timestamp in enumerate(times):
            key = timestamp.strftime("%m-%d")
            if key == "02-29" or key not in key_index:
                continue
            value = float(means[region_id][index])
            climate = climatology[region_id]["mean"][key_index[key]]
            if not math.isfinite(value) or climate is None:
                continue
            anomaly = value - float(climate)
            date_text = timestamp.strftime("%Y-%m-%d")
            daily.append({
                "date": date_text,
                "sst": _round_or_none(value),
                "anomaly": _round_or_none(anomaly),
            })
            anomalies.append(anomaly)
            sst_values.append(value)
            latest_date = max(latest_date, date_text) if latest_date else date_text

        latest_month = int(daily[-1]["date"][5:7]) if daily else None
        current_month_rows = [item for item in daily if int(item["date"][5:7]) == latest_month] if latest_month else []
        current[region_id] = {
            "daily": daily,
            "latest_sst": daily[-1]["sst"] if daily else None,
            "latest_anomaly": daily[-1]["anomaly"] if daily else None,
            "ytd_mean_sst": _round_or_none(np.mean(sst_values)) if sst_values else None,
            "ytd_mean_anomaly": _round_or_none(np.mean(anomalies)) if anomalies else None,
            "current_month": {
                "month": latest_month,
                "days": len(current_month_rows),
                "sst": _round_or_none(np.mean([item["sst"] for item in current_month_rows])) if current_month_rows else None,
                "anomaly": _round_or_none(np.mean([item["anomaly"] for item in current_month_rows])) if current_month_rows else None,
                "provisional": True,
            },
        }
    if not latest_date:
        raise RuntimeError("Aktuelle OISST-Datei enthält keine verwertbaren Mittelmeerwerte.")
    return current, latest_date, counts


def _annual_from_monthly(monthly: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    annual: dict[str, list[dict[str, Any]]] = {}
    for region in REGIONS:
        region_id = region["id"]
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in monthly[region_id]:
            grouped[int(item["date"][:4])].append(item)
        rows = []
        for year, items in sorted(grouped.items()):
            by_month = {int(item["date"][5:7]): item for item in items}
            if len(by_month) != 12:
                continue
            weights = np.array([pd.Period(f"{year}-{month:02d}").days_in_month for month in range(1, 13)], dtype=float)
            sst = np.array([by_month[month]["sst"] for month in range(1, 13)], dtype=float)
            anomaly = np.array([by_month[month]["anomaly"] for month in range(1, 13)], dtype=float)
            rows.append({
                "year": year,
                "sst": _round_or_none(np.average(sst, weights=weights)),
                "anomaly": _round_or_none(np.average(anomaly, weights=weights)),
            })
        annual[region_id] = rows
    return annual


def _valid_state(state: Any) -> bool:
    return (
        isinstance(state, dict)
        and state.get("version") == STATE_VERSION
        and isinstance(state.get("daily_climatology"), dict)
        and isinstance(state.get("monthly"), dict)
    )


def update_med_sst(root: Path, force_full: bool = False) -> dict[str, Any]:
    output_path = root / "med_sst.json"
    state_path = root / "med_sst_state.json"
    state: dict[str, Any] = {}
    if state_path.exists():
        try:
            state = read_json(state_path)
        except (OSError, json.JSONDecodeError):
            state = {}

    full_rebuild = force_full or not _valid_state(state) or _days_since(state.get("full_built_at")) >= FULL_REBUILD_DAYS
    if full_rebuild:
        daily_climatology, point_counts = _build_daily_climatology()
        monthly, monthly_counts = _build_monthly_history()
        point_counts.update(monthly_counts)
        state = {
            "version": STATE_VERSION,
            "full_built_at": _iso_now(),
            "monthly_checked_at": _iso_now(),
            "daily_climatology": daily_climatology,
            "monthly": monthly,
            "point_counts": point_counts,
        }
    else:
        daily_climatology = state["daily_climatology"]
        monthly = state["monthly"]
        point_counts = state.get("point_counts", {})
        if _days_since(state.get("monthly_checked_at")) >= MONTHLY_REFRESH_DAYS:
            monthly, monthly_counts = _build_monthly_history()
            point_counts.update(monthly_counts)
            state["monthly"] = monthly
            state["monthly_checked_at"] = _iso_now()
            state["point_counts"] = point_counts

    current, data_through, current_counts = _current_year_daily(daily_climatology)
    point_counts.update(current_counts)
    state["point_counts"] = point_counts
    state["last_updated_at"] = _iso_now()
    annual = _annual_from_monthly(monthly)

    regions = []
    for region in REGIONS:
        region_id = region["id"]
        regions.append({
            "id": region_id,
            "label": region["label"],
            "point_count": int(point_counts.get(region_id, 0)),
        })

    output = {
        "ready": True,
        "version": OUTPUT_VERSION,
        "generated_at": _iso_now(),
        "data_through": data_through,
        "current_year": date.today().year,
        "reference_period": f"{REFERENCE_START}–{REFERENCE_END}",
        "daily_keys": _non_leap_keys(),
        "regions": regions,
        "daily_climatology": daily_climatology,
        "current": current,
        "monthly": monthly,
        "annual": annual,
        "source": {
            "name": "NOAA/NCEI OISST v2.1",
            "product": "NOAA 1/4° Daily Optimum Interpolation Sea Surface Temperature, Version 2.1",
            "provider": "NOAA Physical Sciences Laboratory / NOAA NCEI",
            "reference": f"Eigene flächengewichtete Anomalien gegenüber {REFERENCE_START}–{REFERENCE_END}",
            "note": "Die Teilgebiete verwenden feste geografische Masken des Climate Dashboards und sind keine offiziellen MEDMOS-Regionen. Sehr aktuelle OISST-Werte können nachträglich revidiert werden.",
        },
    }

    atomic_write_json(state_path, state)
    atomic_write_json(output_path, output)
    return {
        "data_through": data_through,
        "current_year": date.today().year,
        "region_count": len(regions),
        "reference_period": output["reference_period"],
        "full_rebuild": full_rebuild,
        "monthly_latest": max(
            item["date"] for rows in monthly.values() for item in rows
        ),
        "source": "NOAA/NCEI OISST v2.1",
    }
