#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Rectangle
import numpy as np
import xarray as xr

try:
    from build_hyras_temperature_rank_shard import _source_module, _unpack_prepared
    from update_hyras_maps import draw_boundaries, guess_crs_from_xy, load_boundaries
except ModuleNotFoundError:
    from scripts.build_hyras_temperature_rank_shard import _source_module, _unpack_prepared
    from scripts.update_hyras_maps import draw_boundaries, guess_crs_from_xy, load_boundaries


REFERENCES = ("1991-2020", "1961-1990")
PARAM_LABELS = {
    "tmean": "Tmean · 2-m-Temperaturmittel",
    "tmax": "Tmax · 2-m-Tagesmaximum",
    "tmin": "Tmin · 2-m-Tagesminimum",
}

# NUR für tägliche Temperaturabweichungskarten.
DAILY_ANOMALY_TICKS = [
    -18, -16, -14, -12, -10, -8, -6, -4, -2, -1,
    1, 2, 4, 6, 8, 10, 12, 14, 16, 18,
]
DAILY_ANOMALY_BOUNDARIES = [
    -99, -18, -16, -14, -12, -10, -8, -6, -4, -2, -1,
    1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 99,
]
DAILY_ANOMALY_COLORS = [
    "#08306b", "#08519c", "#2171b5", "#4292c6", "#6baed6",
    "#8fbfe3", "#b3d4ee", "#d1e4f5", "#e4eff9", "#f2f7fb",
    "#fffdfd",
    "#fdecec", "#fbd6d6", "#f9bcbc", "#f79f9f", "#f77d7d",
    "#f65d5d", "#ef3b2c", "#d92523", "#b70f16", "#8b0000",
]


def _load_reference_fields(shard_dir: Path, parameter: str):
    files = sorted(shard_dir.glob(f"daily_anomaly_ref_{parameter}_*.npz"))
    if not files:
        raise RuntimeError(f"Keine Tagesanomalie-Referenzshards für {parameter}")

    sums = counts = None
    codes_ref = x_ref = y_ref = refs_ref = None
    all_years: list[int] = []
    display_factor = None

    for path in files:
        with np.load(path, allow_pickle=False) as data:
            p = str(np.asarray(data["parameter"]).item())
            if p != parameter:
                raise RuntimeError(f"{path}: Parameter {p}, erwartet {parameter}")
            refs = np.asarray(data["references"]).astype(str)
            codes = np.asarray(data["date_codes"], dtype=np.uint16)
            x = np.asarray(data["x"], dtype=np.float64)
            y = np.asarray(data["y"], dtype=np.float64)
            part_sums = np.asarray(data["sums"], dtype=np.float32)
            part_counts = np.asarray(data["counts"], dtype=np.uint8)
            years = np.asarray(data["years"], dtype=int).tolist()
            factor = int(np.asarray(data["display_factor"]).item())

        if sums is None:
            refs_ref = refs
            codes_ref = codes
            x_ref = x
            y_ref = y
            display_factor = factor
            sums = np.zeros(part_sums.shape, dtype=np.float64)
            counts = np.zeros(part_counts.shape, dtype=np.uint16)
        else:
            if not np.array_equal(refs, refs_ref):
                raise RuntimeError(f"{path}: Referenzreihenfolge weicht ab")
            if not np.array_equal(codes, codes_ref):
                raise RuntimeError(f"{path}: Sommertage weichen ab")
            if factor != display_factor:
                raise RuntimeError(f"{path}: Darstellungsfaktor weicht ab")
            if (
                x.shape != x_ref.shape
                or y.shape != y_ref.shape
                or not np.allclose(x, x_ref)
                or not np.allclose(y, y_ref)
            ):
                raise RuntimeError(f"{path}: Raster weicht ab")

        sums += part_sums
        counts += part_counts
        all_years.extend(years)

    expected = list(range(1961, 2021))
    if sorted(all_years) != expected:
        raise RuntimeError(
            f"Referenzjahre unvollständig: {sorted(all_years)[:3]} … "
            f"{sorted(all_years)[-3:]} · {len(all_years)} Jahre"
        )

    assert refs_ref is not None and codes_ref is not None
    assert x_ref is not None and y_ref is not None
    assert sums is not None and counts is not None
    assert display_factor is not None

    means = np.full(sums.shape, np.nan, dtype=np.float32)
    valid = counts > 0
    means[valid] = (sums[valid] / counts[valid]).astype(np.float32)

    by_reference = {
        str(ref): means[i]
        for i, ref in enumerate(refs_ref)
    }
    return codes_ref, x_ref, y_ref, by_reference, display_factor


def _load_current(parameter: str, target: date, factor: int, work: Path):
    module = _source_module(parameter)
    files = module.latest_daily_files(module.daily_listing())
    filename = files.get(target.year)
    if not filename:
        raise RuntimeError(f"HYRAS-{parameter}: Jahresdatei {target.year} fehlt")

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
        if keep.size == 0:
            raise RuntimeError(f"HYRAS-{parameter}: keine Sommertage bis {target}")
        sampled = da.isel({
            td: keep,
            ydim: slice(None, None, factor),
            xdim: slice(None, None, factor),
        })
        cube = np.asarray(sampled.values, dtype=np.float32)
        cube[~np.isfinite(cube)] = np.nan
        dates = np.asarray(times[keep]).astype(str)
        sx = np.asarray(x[::factor], dtype=np.float64)
        sy = np.asarray(y[::factor], dtype=np.float64)

    return dates, sx, sy, cube


def _plot_bounds(field: np.ndarray, x: np.ndarray, y: np.ndarray):
    valid = np.isfinite(field)
    if not valid.any():
        return float(x.min()), float(x.max()), float(y.min()), float(y.max())
    rows = np.where(valid.any(axis=1))[0]
    cols = np.where(valid.any(axis=0))[0]
    xmin, xmax = float(x[cols[0]]), float(x[cols[-1]])
    ymin, ymax = float(y[rows[0]]), float(y[rows[-1]])
    if xmin > xmax:
        xmin, xmax = xmax, xmin
    if ymin > ymax:
        ymin, ymax = ymax, ymin
    padx = max((xmax - xmin) * 0.03, 1.0)
    pady = max((ymax - ymin) * 0.03, 1.0)
    return xmin - padx, xmax + padx, ymin - pady, ymax + pady


def _draw_legend(fig) -> None:
    ax = fig.add_axes([0.055, 0.042, 0.89, 0.062])
    n = len(DAILY_ANOMALY_COLORS)
    ax.set_xlim(0, n)
    ax.set_ylim(0, 1)

    for i, color in enumerate(DAILY_ANOMALY_COLORS):
        ax.add_patch(Rectangle(
            (i, 0.45), 1, 0.47,
            facecolor=color,
            edgecolor="white",
            linewidth=0.55,
        ))

    labels = [
        "≤−18", "−16", "−14", "−12", "−10", "−8", "−6", "−4", "−2", "−1",
        "0", "+1", "+2", "+4", "+6", "+8", "+10", "+12", "+14", "+16", "≥+18",
    ]
    for i, label in enumerate(labels):
        ax.text(i + 0.5, 0.12, label, ha="center", va="center", fontsize=6.3)
    ax.text(n + 0.08, 0.12, "K", ha="left", va="center", fontsize=8)
    ax.axis("off")


def _render(
    anomaly: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    geojson,
    data_crs,
    output: Path,
    parameter: str,
    target_text: str,
    reference: str,
    factor: int,
) -> None:
    cmap = ListedColormap(
        DAILY_ANOMALY_COLORS,
        name="hyras_daily_temperature_anomaly",
    )
    norm = BoundaryNorm(
        DAILY_ANOMALY_BOUNDARIES,
        cmap.N,
        clip=True,
    )

    xmin, xmax, ymin, ymax = _plot_bounds(anomaly, x, y)
    fig = plt.figure(figsize=(7.7, 9.4), dpi=180)
    ax = fig.add_axes([0.055, 0.12, 0.89, 0.79])
    ax.pcolormesh(
        x,
        y,
        np.ma.masked_invalid(anomaly),
        shading="auto",
        cmap=cmap,
        norm=norm,
        rasterized=True,
    )
    draw_boundaries(ax, geojson, data_crs)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal")
    ax.set_axis_off()

    display_ref = reference.replace("-", "–")
    display_date = date.fromisoformat(target_text).strftime("%d.%m.%Y")
    fig.suptitle(
        f"HYRAS {PARAM_LABELS[parameter]} · Tagesabweichung",
        fontsize=14.5,
        fontweight="bold",
        y=0.965,
    )
    fig.text(
        0.5, 0.925,
        f"{display_date} · Abweichung gegenüber {display_ref}",
        ha="center",
        va="center",
        fontsize=10,
    )
    fig.text(
        0.5, 0.901,
        f"Eigene Tagesanomalie-Skala −18 bis +18 K · Darstellung ca. {factor} km",
        ha="center",
        va="center",
        fontsize=8.3,
        color="#555555",
    )
    _draw_legend(fig)
    fig.text(
        0.055,
        0.012,
        "Quelle: Deutscher Wetterdienst · HYRAS-DE · tägliche 2-m-Temperaturfelder",
        fontsize=7,
        color="#555555",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        output,
        facecolor="white",
        bbox_inches="tight",
        pad_inches=0.12,
        dpi=180,
    )
    plt.close(fig)


def build_maps(
    *,
    data_root: Path,
    shard_dir: Path,
    parameter: str,
    target: date,
    work: Path,
) -> dict:
    codes, rx, ry, references, factor = _load_reference_fields(
        shard_dir,
        parameter,
    )
    dates, cx, cy, current = _load_current(
        parameter,
        target,
        factor,
        work,
    )

    if (
        cx.shape != rx.shape
        or cy.shape != ry.shape
        or not np.allclose(cx, rx)
        or not np.allclose(cy, ry)
    ):
        raise RuntimeError(
            f"HYRAS-{parameter}: aktuelles und Referenzraster stimmen nicht überein"
        )

    code_lookup = {
        int(code): i
        for i, code in enumerate(codes)
    }
    geojson = load_boundaries()
    if not geojson:
        raise RuntimeError("Bundeslandgrenzen konnten nicht geladen werden")
    data_crs = guess_crs_from_xy(rx, ry)

    out_root = data_root / parameter / "regions"
    manifest_path = out_root / "daily_anomaly_maps.json"
    previous = {}
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    result_dates = dict(previous.get("dates") or {})
    rendered = 0

    for current_index, target_text in enumerate(dates):
        d = date.fromisoformat(str(target_text))
        code = d.month * 100 + d.day
        ref_index = code_lookup.get(code)
        if ref_index is None:
            continue

        date_entry = dict(result_dates.get(str(target_text)) or {})
        for reference in REFERENCES:
            ref_stack = references.get(reference)
            if ref_stack is None:
                raise RuntimeError(
                    f"HYRAS-{parameter}: Referenz {reference} fehlt"
                )
            anomaly = current[current_index] - ref_stack[ref_index]
            rel = (
                Path("daily_anomalies")
                / reference
                / f"{target_text}.png"
            )
            output = out_root / rel
            if not output.exists():
                _render(
                    anomaly,
                    rx,
                    ry,
                    geojson,
                    data_crs,
                    output,
                    parameter,
                    str(target_text),
                    reference,
                    factor,
                )
                rendered += 1
                print(
                    f"Tagesanomalie: {parameter} · {target_text} · {reference}",
                    flush=True,
                )
            date_entry[reference] = rel.as_posix()
        result_dates[str(target_text)] = date_entry

    available_dates = sorted(
        value
        for value, refs in result_dates.items()
        if all(ref in refs for ref in REFERENCES)
    )
    manifest = {
        "schema_version": 1,
        "parameter": parameter,
        "data_through": target.isoformat(),
        "references": list(REFERENCES),
        "default_reference": "1991-2020",
        "resolution_km": factor,
        "scale": {
            "type": "daily_temperature_anomaly",
            "unit": "K",
            "min": -18,
            "max": 18,
            "ticks": DAILY_ANOMALY_TICKS,
            "note": "Diese breite Skala gilt ausschließlich für Tagesanomalien.",
        },
        "available_dates": available_dates,
        "dates": {
            value: result_dates[value]
            for value in available_dates
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"{parameter}: Tagesanomalien fertig · {len(available_dates)} Tage · "
        f"{rendered} neue PNGs",
        flush=True,
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parameter",
        choices=("tmean", "tmax", "tmin"),
        required=True,
    )
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--shard-dir", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument(
        "--work",
        default="/tmp/hyras-daily-anomaly-current",
    )
    args = parser.parse_args()

    build_maps(
        data_root=Path(args.data_root),
        shard_dir=Path(args.shard_dir),
        parameter=args.parameter,
        target=date.fromisoformat(args.target_date),
        work=Path(args.work) / args.parameter,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
