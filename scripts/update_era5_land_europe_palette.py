#!/usr/bin/env python3
from __future__ import annotations

"""ERA5-Land Europa mit der abgestimmten diskreten Temperatur-Anomalieskala.

Der bestehende Generator bleibt unverändert. Nur kind='temp_anomaly' wird hier
überschrieben; alle anderen Karten werden 1:1 vom bisherigen Renderer erzeugt.
"""

import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap

import cartopy.crs as ccrs
import cartopy.feature as cfeature

import update_era5_land_europe as base


TEMP_ANOMALY_LEVELS = [
    -8.0, -7.0, -6.0, -5.0, -4.0, -3.0, -2.0, -1.0, -0.5,
     0.0,
     0.5,  1.0,  2.0,  3.0,  4.0,  5.0,  6.0,  7.0,  8.0,
]

TEMP_ANOMALY_COLORS = [
    "#3A006F",  # -8
    "#51009E",  # -7
    "#6B03C6",  # -6
    "#5E4FFC",  # -5
    "#187DFD",  # -4
    "#70B1FB",  # -3
    "#C6E4FB",  # -2
    "#DDEBF9",  # -1
    "#EDF4FA",  # -0.5
    "#FDFCFC",  #  0
    "#FDF0BC",  # +0.5
    "#FDE47C",  # +1
    "#FDBD3E",  # +2
    "#FC691C",  # +3
    "#F93A19",  # +4
    "#E51B75",  # +5
    "#FC579B",  # +6
    "#FC83B4",  # +7
    "#FDAFCB",  # +8
]


def temperature_anomaly_style():
    levels = np.asarray(TEMP_ANOMALY_LEVELS, dtype=float)
    mids = (levels[:-1] + levels[1:]) / 2.0
    bounds = np.concatenate(([levels[0] - 0.5], mids, [levels[-1] + 0.5]))
    cmap = ListedColormap(TEMP_ANOMALY_COLORS, name="era5_europe_temperature_anomaly")
    norm = BoundaryNorm(bounds, cmap.N, clip=True)
    return cmap, norm, bounds


def anomaly_ticklabels() -> list[str]:
    labels: list[str] = []
    for value in TEMP_ANOMALY_LEVELS:
        if value == 0:
            labels.append("0")
        elif abs(value) == 0.5:
            labels.append(f"{value:+.1f}")
        elif value > 0:
            labels.append(f"{value:+.0f}")
        else:
            labels.append(f"{value:.0f}")
    return labels


_original_render_map = base.render_map


def render_map(field, lat, lon, *, title, subtitle, unit, filename, kind):
    if kind != "temp_anomaly":
        return _original_render_map(
            field, lat, lon,
            title=title,
            subtitle=subtitle,
            unit=unit,
            filename=filename,
            kind=kind,
        )

    filename.parent.mkdir(parents=True, exist_ok=True)
    base.cartopy.config["data_dir"] = str(base.CARTOPY_DIR)
    base.CARTOPY_DIR.mkdir(parents=True, exist_ok=True)

    fig = base.plt.figure(figsize=(13.2, 8.1), dpi=150)
    ax = fig.add_axes([0.07, 0.18, 0.89, 0.66], projection=ccrs.PlateCarree())
    ax.set_extent([base.AREA[1], base.AREA[3], base.AREA[2], base.AREA[0]], crs=ccrs.PlateCarree())

    data = np.ma.masked_invalid(np.asarray(field, dtype=float))
    cmap, norm, bounds = temperature_anomaly_style()

    mesh = ax.pcolormesh(
        lon,
        lat,
        data,
        transform=ccrs.PlateCarree(),
        cmap=cmap,
        norm=norm,
        shading="auto",
    )

    ax.add_feature(cfeature.COASTLINE.with_scale("50m"), linewidth=0.55, edgecolor="#39434a")
    ax.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.4, edgecolor="#66727a")
    ax.add_feature(
        cfeature.LAKES.with_scale("50m"),
        facecolor="#f4f7f8",
        edgecolor="#89949a",
        linewidth=0.25,
        zorder=3,
    )
    ax.set_facecolor("#eef3f5")

    gl = ax.gridlines(
        draw_labels=True,
        linewidth=0.25,
        color="#7f8c92",
        alpha=0.45,
        linestyle="--",
    )
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"size": 8, "color": "#59656c"}
    gl.ylabel_style = {"size": 8, "color": "#59656c"}

    cax = fig.add_axes([0.14, 0.085, 0.75, 0.032])
    cbar = base.plt.colorbar(
        mesh,
        cax=cax,
        orientation="horizontal",
        boundaries=bounds,
        ticks=TEMP_ANOMALY_LEVELS,
        spacing="uniform",
    )
    cbar.set_label(unit, fontsize=10)
    cbar.ax.tick_params(labelsize=7)
    cbar.ax.set_xticklabels(anomaly_ticklabels())

    # Dünne schwarze Markierung exakt bei 0 K.
    cbar.ax.axvline(0.0, color="black", linewidth=0.9, zorder=10)

    fig.suptitle(title, x=0.075, y=0.97, ha="left", va="top", fontsize=17, fontweight="bold")
    fig.text(0.075, 0.925, subtitle, ha="left", va="top", fontsize=10, color="#56636a")
    fig.text(
        0.075,
        0.025,
        "Quelle: Copernicus Climate Change Service / ECMWF · ERA5-Land · 0,1° · Landflächen",
        ha="left",
        va="bottom",
        fontsize=8,
        color="#68757c",
    )

    base.plt.savefig(filename, facecolor="white")
    base.plt.close(fig)


# make_period_maps() greift zur Laufzeit auf base.render_map zu.
base.render_map = render_map


if __name__ == "__main__":
    raise SystemExit(base.main())
