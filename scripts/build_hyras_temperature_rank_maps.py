#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Rectangle
import numpy as np
from PIL import Image
import xarray as xr

try:
    from hyras_temperature_rank import (
        HISTORY_END, HISTORY_START, PRODUCTS, RANK_BOUNDARIES, RANK_CLASS_LABELS,
        RANK_COLORS, extract_products, historical_years, rank_field,
    )
    from build_hyras_temperature_rank_shard import DEFAULT_FACTOR, PARAM_MODULES, _unpack_prepared
except ModuleNotFoundError:
    from scripts.hyras_temperature_rank import (
        HISTORY_END, HISTORY_START, PRODUCTS, RANK_BOUNDARIES, RANK_CLASS_LABELS,
        RANK_COLORS, extract_products, historical_years, rank_field,
    )
    from scripts.build_hyras_temperature_rank_shard import DEFAULT_FACTOR, PARAM_MODULES, _unpack_prepared

PARAM_LABELS = {
    "tmean": "Tmean · 2-m-Temperaturmittel",
    "tmax": "Tmax · 2-m-Tagesmaximum",
    "tmin": "Tmin · 2-m-Tagesminimum",
}


def period_label(product: str, target: date) -> str:
    if product == "day":
        return target.strftime("%d.%m.%Y")
    if product == "month_to_date":
        return f"01.–{target.day:02d}.{target.month:02d}.{target.year}"
    if product == "summer_to_date":
        return f"01.06.–{target.day:02d}.{target.month:02d}.{target.year}"
    raise ValueError(product)


def _source_module(parameter: str):
    return importlib.import_module(PARAM_MODULES[parameter])


def _current_products(parameter: str, target: date, factor: int, work: Path):
    module = _source_module(parameter)
    files = module.latest_daily_files(module.daily_listing())
    filename = files.get(target.year)
    if not filename:
        raise RuntimeError(f"HYRAS-{parameter}: aktuelle Tagesdatei {target.year} fehlt")
    work.mkdir(parents=True, exist_ok=True)
    nc_path = work / filename
    if not nc_path.exists():
        module.download(f"{module.DAILY_BASE}/{filename}", nc_path)
    with xr.open_dataset(nc_path, decode_times=True) as ds:
        da, td, ydim, xdim, x, y = _unpack_prepared(module, ds)
        times = np.asarray(da[td].values).astype("datetime64[D]")
        start = np.datetime64(f"{target.year:04d}-06-01")
        stop = np.datetime64(target.isoformat())
        keep = np.flatnonzero((times >= start) & (times <= stop))
        sampled = da.isel({td: keep, ydim: slice(None, None, factor), xdim: slice(None, None, factor)})
        cube = np.asarray(sampled.values, dtype=np.float32)
        cube[~np.isfinite(cube)] = np.nan
        products = extract_products(times[keep], cube, target)
        return x[::factor], y[::factor], products


def _load_history(shard_dir: Path, parameter: str, target: date):
    files = sorted(shard_dir.glob(f"{parameter}_*_{target.isoformat()}.npz"))
    if not files:
        raise RuntimeError(f"Keine HYRAS-{parameter}-Rangshards für {target} gefunden")
    parts = []
    x_ref = y_ref = None
    for path in files:
        with np.load(path, allow_pickle=False) as data:
            years = np.asarray(data["years"], dtype=int)
            x = np.asarray(data["x"], dtype=float)
            y = np.asarray(data["y"], dtype=float)
            fields = {key: np.asarray(data[key], dtype=np.float32) for key in PRODUCTS}
        if x_ref is None:
            x_ref, y_ref = x, y
        elif x.shape != x_ref.shape or y.shape != y_ref.shape or not np.allclose(x, x_ref) or not np.allclose(y, y_ref):
            raise RuntimeError(f"Rasterabweichung in {path.name}")
        parts.append((years, fields))
    years = np.concatenate([p[0] for p in parts])
    order = np.argsort(years)
    years = years[order]
    expected = historical_years()
    if not np.array_equal(years, expected):
        raise RuntimeError(f"HYRAS-{parameter}-Historie unvollständig: {years.tolist()}")
    history = {
        key: np.concatenate([p[1][key] for p in parts], axis=0)[order]
        for key in PRODUCTS
    }
    assert x_ref is not None and y_ref is not None
    return x_ref, y_ref, history


def _boundary_overlay(data_root: Path, shape: tuple[int, int], factor: int):
    idx_path = data_root / "hyras_index.json"
    if not idx_path.exists():
        return None
    try:
        rel = json.loads(idx_path.read_text(encoding="utf-8")).get("interactive", {}).get("boundary_overlay_1km")
    except Exception:
        return None
    if not rel:
        return None
    path = data_root / rel
    if not path.exists():
        return None
    image = Image.open(path).convert("RGBA")
    arr = np.asarray(image)
    sampled = arr[::factor, ::factor]
    if sampled.shape[:2] == shape:
        return sampled
    return np.asarray(image.resize((shape[1], shape[0]), Image.Resampling.NEAREST))


def _rank_stats(rank: np.ndarray) -> dict[str, float | int | None]:
    valid = np.isfinite(rank)
    n = int(valid.sum())
    if not n:
        return {"valid_gridpoints": 0, "rank1_percent": None, "top3_percent": None}
    return {
        "valid_gridpoints": n,
        "rank1_percent": round(100.0 * float(np.count_nonzero(valid & (rank <= 1))) / n, 3),
        "top3_percent": round(100.0 * float(np.count_nonzero(valid & (rank <= 3))) / n, 3),
    }


def _draw_legend(fig) -> None:
    ax = fig.add_axes([0.055, 0.045, 0.89, 0.055])
    n = len(RANK_COLORS)
    ax.set_xlim(0, n)
    ax.set_ylim(0, 1)
    for i, (color, label) in enumerate(zip(RANK_COLORS, RANK_CLASS_LABELS)):
        ax.add_patch(Rectangle((i, 0.43), 1, 0.5, facecolor=color, edgecolor="white", linewidth=0.8))
        ax.text(i + 0.5, 0.13, label, ha="center", va="center", fontsize=7.5)
    ax.text(n + 0.08, 0.13, "Rang", ha="left", va="center", fontsize=8)
    ax.axis("off")


def _render(rank: np.ndarray, overlay, output: Path, parameter: str, product: str, target: date, factor: int) -> None:
    cmap = ListedColormap(RANK_COLORS, name="hyras_temperature_rank")
    norm = BoundaryNorm(RANK_BOUNDARIES, cmap.N, clip=True)
    fig = plt.figure(figsize=(7.4, 9.4), dpi=150)
    ax = fig.add_axes([0.055, 0.12, 0.89, 0.79])
    ax.imshow(np.ma.masked_invalid(rank), cmap=cmap, norm=norm, interpolation="nearest")
    if overlay is not None and overlay.shape[:2] == rank.shape:
        ax.imshow(overlay, interpolation="nearest")
    ax.set_axis_off()
    fig.suptitle(
        f"HYRAS {PARAM_LABELS[parameter]} · Historischer Rang",
        fontsize=14.5, fontweight="bold", y=0.965,
    )
    fig.text(
        0.5, 0.925, period_label(product, target),
        ha="center", va="center", fontsize=10,
    )
    fig.text(
        0.5, 0.902,
        f"Vergleich {HISTORY_START}–{target.year} · Rang 1 = wärmster Wert · Darstellung ca. {factor} km",
        ha="center", va="center", fontsize=8.5, color="#555555",
    )
    _draw_legend(fig)
    fig.text(
        0.055, 0.012,
        "Quelle: Deutscher Wetterdienst · HYRAS-DE · tägliche 2-m-Temperaturfelder",
        fontsize=7, color="#555555",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, facecolor="white", bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


def build_maps(*, data_root: Path, shard_dir: Path, target: date, factor: int, work: Path) -> dict[str, Any]:
    out_root = data_root / "temperature_ranks"
    out_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "ready": True,
        "data_through": target.isoformat(),
        "history_start": HISTORY_START,
        "history_end": HISTORY_END,
        "historical_years": HISTORY_END - HISTORY_START + 1,
        "total_rank_positions": HISTORY_END - HISTORY_START + 2,
        "rank_direction": "1 = wärmster",
        "resolution_km": factor,
        "classes": [{"label": label, "color": color} for label, color in zip(RANK_CLASS_LABELS, RANK_COLORS)],
        "parameters": {},
    }

    for parameter in ("tmean", "tmax", "tmin"):
        hx, hy, history = _load_history(shard_dir, parameter, target)
        cx, cy, current = _current_products(parameter, target, factor, work / parameter)
        if cx.shape != hx.shape or cy.shape != hy.shape or not np.allclose(cx, hx) or not np.allclose(cy, hy):
            raise RuntimeError(f"HYRAS-{parameter}: aktuelles und historisches Raster stimmen nicht überein")
        parameter_payload = {"label": PARAM_LABELS[parameter], "products": {}}
        for product in PRODUCTS:
            rank = rank_field(current[product], history[product])
            overlay = _boundary_overlay(data_root, rank.shape, factor)
            rel = Path(parameter) / f"{product}_rank.png"
            _render(rank, overlay, out_root / rel, parameter, product, target, factor)
            parameter_payload["products"][product] = {
                "file": (Path("temperature_ranks") / rel).as_posix(),
                "label": period_label(product, target),
                "stats": _rank_stats(rank),
            }
            print(f"Render: {parameter} {product}", flush=True)
        manifest["parameters"][parameter] = parameter_payload

    (out_root / "index.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--shard-dir", required=True)
    ap.add_argument("--target-date", required=True)
    ap.add_argument("--factor", type=int, default=DEFAULT_FACTOR)
    ap.add_argument("--work", default="/tmp/hyras-temperature-rank-current")
    args = ap.parse_args()
    target = date.fromisoformat(args.target_date)
    manifest = build_maps(
        data_root=Path(args.data_root),
        shard_dir=Path(args.shard_dir),
        target=target,
        factor=args.factor,
        work=Path(args.work),
    )
    print(
        f"HYRAS Temperatur-Rangkarten fertig: {manifest['data_through']} · "
        f"{len(manifest['parameters']) * len(PRODUCTS)} PNGs",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
