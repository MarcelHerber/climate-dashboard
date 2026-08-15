#!/usr/bin/env python3
from __future__ import annotations

import calendar
import json
import re
from datetime import datetime
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

from build_hyras_tmax_regions import (
    DAILY_BASE,
    USER_AGENT,
    download,
    latest_daily_files,
    pick_var,
    prepare_da,
    to_celsius,
)

CLIM_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/multi_annual/hyras_de/air_temperature_max"
REFERENCE_START = 1991
REFERENCE_END = 2020
MONTH_ABBR = {
    1:"JAN",2:"FEB",3:"MAR",4:"APR",5:"MAY",6:"JUN",
    7:"JUL",8:"AUG",9:"SEP",10:"OCT",11:"NOV",12:"DEC",
}


def get(url: str, timeout: int = 120) -> requests.Response:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response


def listing(url: str) -> str:
    return get(url + "/", 90).text


def latest_clim_filename(month: int, text: str | None = None) -> str:
    text = text if text is not None else listing(CLIM_BASE)
    abbr = MONTH_ABBR[month]
    pattern = re.compile(
        rf'href="(?P<filename>tasmax_hyras_1_{REFERENCE_START}_{REFERENCE_END}_'
        rf'v(?P<major>\d+)-(?P<minor>\d+)_de_{abbr}\.nc)"'
    )
    matches: list[tuple[int,int,str]] = []
    for match in pattern.finditer(text):
        matches.append((
            int(match.group("major")),
            int(match.group("minor")),
            match.group("filename"),
        ))
    if not matches:
        raise RuntimeError(f"Keine Tmax-Klimadatei für {abbr} gefunden.")
    matches.sort()
    return matches[-1][2]


def static_2d(ds: xr.Dataset) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    da = to_celsius(pick_var(ds)).squeeze(drop=True)
    while da.ndim > 2:
        da = da.isel({da.dims[0]: 0})
    if da.ndim != 2:
        raise RuntimeError(f"Keine statische 2D-Tmax-Klimatologie: {da.dims}")

    dims = list(da.dims)
    ydim = next((d for d in dims if d.lower() in {"y","lat","latitude","rlat"}), dims[0])
    xdim = next((d for d in dims if d.lower() in {"x","lon","longitude","rlon"}), dims[1])
    da = da.transpose(ydim, xdim)

    arr = np.asarray(da.values, dtype=np.float32)
    x = np.asarray(da[xdim].values, dtype=np.float64)
    y = np.asarray(da[ydim].values, dtype=np.float64)
    arr[~np.isfinite(arr)] = np.nan
    return arr, x, y


def period_current_mean(
    daily: xr.DataArray,
    td: str,
    start_date: str,
    end_date: str,
) -> np.ndarray:
    selected = daily.where(
        (daily[td] >= np.datetime64(start_date))
        & (daily[td] <= np.datetime64(end_date)),
        drop=True,
    )
    if selected.sizes.get(td, 0) == 0:
        raise RuntimeError(f"Keine Tmax-Tage für {start_date} bis {end_date}.")
    arr = np.asarray(selected.mean(td, skipna=True).values, dtype=np.float32)
    arr[~np.isfinite(arr)] = np.nan
    return arr


def complete_reference_months(period: dict[str, Any]) -> list[int] | None:
    start = datetime.strptime(period["start_date"], "%Y-%m-%d").date()
    end = datetime.strptime(period["end_date"], "%Y-%m-%d").date()

    if period["key"].startswith("month_"):
        if start.day != 1 or start.month != end.month or start.year != end.year:
            return None
        if end.day != calendar.monthrange(end.year, end.month)[1]:
            return None
        return [start.month]

    season_months = {
        "spring": [3,4,5],
        "summer": [6,7,8],
        "autumn": [9,10,11],
    }
    months = season_months.get(period["key"])
    if not months:
        return None

    expected_start = datetime(start.year, months[0], 1).date()
    expected_end = datetime(
        start.year,
        months[-1],
        calendar.monthrange(start.year, months[-1])[1],
    ).date()
    if start == expected_start and end == expected_end:
        return months
    return None


def reference_for_months(
    months: list[int],
    year: int,
    work: Path,
    listing_text: str,
    expected_x: np.ndarray,
    expected_y: np.ndarray,
) -> np.ndarray:
    weighted: np.ndarray | None = None
    total_days = 0

    for month in months:
        filename = latest_clim_filename(month, listing_text)
        target = work / "climatology" / filename
        if not target.exists():
            download(f"{CLIM_BASE}/{filename}", target)

        with xr.open_dataset(target, decode_times=True) as ds:
            arr, x, y = static_2d(ds)

        if (
            x.shape != expected_x.shape
            or y.shape != expected_y.shape
            or not np.allclose(x, expected_x)
            or not np.allclose(y, expected_y)
        ):
            raise RuntimeError(f"Tmax-Klimaraster {filename} passt nicht zum aktuellen Gitter.")

        days = calendar.monthrange(year, month)[1]
        weighted = arr * float(days) if weighted is None else weighted + arr * float(days)
        total_days += days

    if weighted is None or total_days <= 0:
        raise RuntimeError("Keine Tmax-Referenzmonate vorhanden.")
    return weighted / float(total_days)


def get_colormap(mode: str):
    if mode == "anomaly":
        colors = [
            "#313695","#4575b4","#74add1","#abd9e9","#f7f7f7",
            "#fdae61","#f46d43","#d73027","#a50026",
        ]
        return LinearSegmentedColormap.from_list("hyras_tmax_anomaly", colors), -6.0, 6.0, "K"

    colors = [
        "#313695","#4575b4","#74add1","#abd9e9","#e0f3f8",
        "#ffffbf","#fee090","#fdae61","#f46d43","#d73027","#a50026",
    ]
    return LinearSegmentedColormap.from_list("hyras_tmax_absolute", colors), -15.0, 45.0, "°C"


def render_map(
    arr: np.ndarray,
    boundary_path: Path | None,
    output: Path,
    title: str,
    subtitle: str,
    mode: str,
) -> None:
    cmap, vmin, vmax, unit = get_colormap(mode)

    fig = plt.figure(figsize=(7.4, 9.4), dpi=150)
    ax = fig.add_axes([0.055, 0.105, 0.89, 0.80])
    image = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_axis_off()

    if boundary_path and boundary_path.exists():
        overlay = np.asarray(Image.open(boundary_path).convert("RGBA"))
        if overlay.shape[:2] == arr.shape:
            ax.imshow(overlay, interpolation="nearest")

    fig.suptitle(title, fontsize=15, fontweight="bold", y=0.965)
    fig.text(0.5, 0.925, subtitle, ha="center", va="center", fontsize=9)

    cax = fig.add_axes([0.14, 0.055, 0.72, 0.025])
    colorbar = fig.colorbar(image, cax=cax, orientation="horizontal")
    colorbar.set_label(unit, fontsize=9)
    colorbar.ax.tick_params(labelsize=8)

    fig.text(
        0.055,
        0.018,
        "Quelle: Deutscher Wetterdienst · HYRAS-DE-TASMAX · Referenz 1991–2020",
        fontsize=7,
        color="#555555",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, facecolor="white", bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


def boundary_overlay(data_root: Path) -> Path | None:
    pidx_path = data_root / "hyras_index.json"
    if not pidx_path.exists():
        return None
    try:
        pidx = json.loads(pidx_path.read_text(encoding="utf-8"))
        rel = pidx.get("interactive", {}).get("boundary_overlay_1km")
        return data_root / rel if rel else None
    except Exception:
        return None


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="/tmp/hyras-data")
    parser.add_argument("--work", default="/tmp/hyras-tmax-work")
    args = parser.parse_args()

    data_root = Path(args.data_root)
    work = Path(args.work)
    troot = data_root / "tmax"
    regions_dir = troot / "regions"

    index_path = regions_dir / "index.json"
    if not index_path.exists():
        raise RuntimeError("Tmax-Regionsindex fehlt.")

    index = json.loads(index_path.read_text(encoding="utf-8"))
    year = int(index["year"])

    files = latest_daily_files(listing(DAILY_BASE))
    current_filename = files.get(year)
    if not current_filename:
        raise RuntimeError(f"Keine aktuelle Tmax-Datei für {year} gefunden.")

    current_nc = work / current_filename
    if not current_nc.exists():
        download(f"{DAILY_BASE}/{current_filename}", current_nc)

    with xr.open_dataset(current_nc, decode_times=True) as ds:
        daily, td, x, y = prepare_da(ds)
        daily = daily.load()

    out_dir = troot / "download_maps"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()

    climatology_listing = listing(CLIM_BASE)
    overlay = boundary_overlay(data_root)
    result: dict[str, Any] = {}

    for period in index.get("periods", []):
        key = str(period["key"])
        label = str(period.get("label", key))
        start_date = str(period["start_date"])
        end_date = str(period["end_date"])

        current = period_current_mean(daily, td, start_date, end_date)

        absolute_rel = f"download_maps/{key}_absolute.png"
        render_map(
            current,
            overlay,
            troot / absolute_rel,
            f"HYRAS Tmax · {label}",
            f"2-m-Tagesmaximum · {start_date} bis {end_date}",
            "absolute",
        )

        item: dict[str, Any] = {
            "label": label,
            "absolute": absolute_rel,
            "start_date": start_date,
            "end_date": end_date,
        }

        months = complete_reference_months(period)
        if months:
            reference = reference_for_months(
                months, year, work, climatology_listing, x, y
            )
            anomaly = current - reference
            anomaly_rel = f"download_maps/{key}_anomaly.png"
            render_map(
                anomaly,
                overlay,
                troot / anomaly_rel,
                f"HYRAS Tmax · {label}",
                f"Abweichung zum Mittel 1991–2020 · {start_date} bis {end_date}",
                "anomaly",
            )
            item["anomaly"] = anomaly_rel
            item["reference_exact"] = True
        else:
            item["reference_exact"] = False
            item["reference_note"] = (
                "Für laufende Teilmonate/-jahreszeiten wird keine Rasteranomalie "
                "veröffentlicht; die Gebietskurve nutzt weiterhin die tagesgenaue "
                "1991–2020-Referenz."
            )

        result[key] = item
        print(
            f"Tmax Downloadkarte {key}: absolut"
            + (" + Anomalie" if "anomaly" in item else ""),
            flush=True,
        )

    manifest = {
        "schema_version": 1,
        "parameter": "tmax",
        "reference": "1991-2020",
        "data_through": index.get("data_through"),
        "periods": result,
    }
    manifest_path = regions_dir / "map_downloads.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    index["map_downloads_file"] = manifest_path.name
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Tmax-Kartendownloads fertig.", flush=True)
    print("Perioden:", len(result), flush=True)
    print(
        "Mit exakter Anomaliekarte:",
        sum(1 for item in result.values() if item.get("anomaly")),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
