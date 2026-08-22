#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
from PIL import Image

DATA_ROOT = Path("/tmp/hyras-data")
OUT_PNG = Path("/tmp/hyras_tmean_august_2026_diskret.png")
OUT_B64 = Path("preview/hyras_tmean_august_2026_diskret.b64")
MISSING = -32768
SCALE = 100.0


def load_current_august() -> tuple[np.ndarray, dict, int, int]:
    index = json.loads((DATA_ROOT / "tmean/index.json").read_text(encoding="utf-8"))
    period = next(
        p for p in index["periods"]
        if p.get("period_type") == "month_live" and p.get("live") is True
    )
    height = int(index["grid_1km"]["height"])
    width = int(index["grid_1km"]["width"])
    anomaly_path = DATA_ROOT / "tmean" / period["anomaly"]
    with gzip.open(anomaly_path, "rb") as handle:
        raw = handle.read()
    values = np.frombuffer(raw, dtype="<i2")
    if values.size != height * width:
        raise RuntimeError(f"Rastergröße unerwartet: {values.size} != {height}x{width}")
    arr = values.reshape(height, width).astype(np.float32)
    arr[arr == MISSING] = np.nan
    arr /= SCALE
    return arr, period, height, width


def load_overlay(height: int, width: int) -> np.ndarray | None:
    try:
        root_index = json.loads((DATA_ROOT / "hyras_index.json").read_text(encoding="utf-8"))
        rel = root_index.get("interactive", {}).get("boundary_overlay_1km")
        if not rel:
            return None
        path = DATA_ROOT / rel
        if not path.exists():
            return None
        overlay = np.asarray(Image.open(path).convert("RGBA"))
        if overlay.shape[:2] != (height, width):
            return None
        return overlay
    except Exception:
        return None


def crop_window(arr: np.ndarray, pad: int = 12) -> tuple[slice, slice]:
    finite = np.isfinite(arr)
    rows = np.where(finite.any(axis=1))[0]
    cols = np.where(finite.any(axis=0))[0]
    if not len(rows) or not len(cols):
        return slice(None), slice(None)
    r0 = max(int(rows[0]) - pad, 0)
    r1 = min(int(rows[-1]) + pad + 1, arr.shape[0])
    c0 = max(int(cols[0]) - pad, 0)
    c1 = min(int(cols[-1]) + pad + 1, arr.shape[1])
    return slice(r0, r1), slice(c0, c1)


def palette() -> tuple[ListedColormap, BoundaryNorm, list[float]]:
    bounds = [-6, -5, -4, -3, -2, -1, -0.5, 0.5, 1, 2, 3, 4, 5, 6]
    colors = [
        "#5527A3",  # -6 ... -5
        "#4039A8",  # -5 ... -4
        "#2F56A6",  # -4 ... -3
        "#5F8FC7",  # -3 ... -2
        "#9FC3DF",  # -2 ... -1
        "#DBEAF2",  # -1 ... -0.5
        "#F3F2EE",  # -0.5 ... +0.5
        "#FFF3A0",  # +0.5 ... +1
        "#FFD45C",  # +1 ... +2
        "#FF9F3A",  # +2 ... +3
        "#EF5A3A",  # +3 ... +4
        "#EA3F72",  # +4 ... +5
        "#D52A90",  # +5 ... +6
    ]
    cmap = ListedColormap(colors, name="hyras_temp_anomaly_discrete")
    cmap.set_under("#6D1CA8")
    cmap.set_over("#AD0F8F")
    norm = BoundaryNorm(bounds, cmap.N, clip=False)
    return cmap, norm, bounds


def main() -> int:
    arr, period, height, width = load_current_august()
    overlay = load_overlay(height, width)
    rs, cs = crop_window(arr)
    shown = arr[rs, cs]
    shown_overlay = overlay[rs, cs] if overlay is not None else None

    cmap, norm, bounds = palette()

    fig = plt.figure(figsize=(8.0, 10.0), dpi=180)
    ax = fig.add_axes([0.07, 0.17, 0.78, 0.72])
    image = ax.imshow(shown, cmap=cmap, norm=norm, interpolation="nearest")
    if shown_overlay is not None:
        ax.imshow(shown_overlay, interpolation="nearest")
    ax.set_axis_off()

    fig.suptitle(
        "HYRAS · Abweichung der Mitteltemperatur",
        fontsize=18,
        fontweight="bold",
        y=0.965,
    )
    fig.text(
        0.46,
        0.925,
        f"August aktuell 2026 · {period['start_date']} bis {period['end_date']} · Referenz 1991–2020",
        ha="center",
        va="center",
        fontsize=10.5,
    )

    mean_value = float(np.nanmean(arr))
    fig.text(
        0.89,
        0.82,
        f"Deutschlandmittel\n{mean_value:+.2f} K",
        ha="center",
        va="center",
        fontsize=11,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.45", facecolor="white", edgecolor="#777777", alpha=0.92),
    )

    cax = fig.add_axes([0.13, 0.095, 0.70, 0.032])
    cbar = fig.colorbar(
        image,
        cax=cax,
        orientation="horizontal",
        boundaries=bounds,
        ticks=list(range(-6, 7)),
        spacing="proportional",
        extend="both",
        drawedges=True,
    )
    cbar.set_label("Temperaturabweichung in K", fontsize=10)
    cbar.ax.tick_params(labelsize=9)
    cbar.dividers.set_linewidth(0.7)

    fig.text(
        0.07,
        0.035,
        "Quelle: Deutscher Wetterdienst · HYRAS-DE-TAS · tagesgenauer Vergleich 1991–2020",
        fontsize=8,
        color="#555555",
    )
    fig.text(
        0.07,
        0.018,
        "Vorschau der diskreten Farbskala · Datenstand 21.08.2026",
        fontsize=8,
        color="#555555",
    )

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, facecolor="white", bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)

    OUT_B64.parent.mkdir(parents=True, exist_ok=True)
    OUT_B64.write_text(base64.b64encode(OUT_PNG.read_bytes()).decode("ascii"), encoding="ascii")
    print(f"Preview geschrieben: {OUT_PNG} ({OUT_PNG.stat().st_size/1024:.1f} KiB)")
    print(f"Base64 geschrieben: {OUT_B64}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
