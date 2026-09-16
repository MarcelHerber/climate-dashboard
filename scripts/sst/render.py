from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from PIL import Image

from .config import ABSOLUTE_RANGE, ANOMALY_RANGE, Region
from .processing import ProcessedFields


def view_scale(view: str) -> tuple[float, float, str, str]:
    if view == "absolute":
        return ABSOLUTE_RANGE[0], ABSOLUTE_RANGE[1], "turbo", "°C"
    if view == "anomaly":
        return ANOMALY_RANGE[0], ANOMALY_RANGE[1], "RdBu_r", "°C"
    raise ValueError(f"Unbekannte SST-Ansicht: {view}")


def render_map(fields: ProcessedFields, region: Region, day: date, view: str, output_path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    vmin, vmax, cmap, unit = view_scale(view)
    data = fields.absolute_c if view == "absolute" else fields.anomaly_c
    subtitle = "SST absolut" if view == "absolute" else "Abweichung zu 1991–2020"
    source = "Quelle: NASA/JPL MUR SST v4.1"
    if view == "anomaly":
        source += " · Referenz: NOAA OISST 1991–2020"

    dpi = 100
    figure = plt.figure(figsize=(region.width_px / dpi, region.height_px / dpi), dpi=dpi, facecolor="white")
    ax = figure.add_axes([0.055, 0.16, 0.89, 0.73], projection=ccrs.PlateCarree())
    ax.set_extent(region.bounds, crs=ccrs.PlateCarree())
    mesh = ax.pcolormesh(
        fields.lon.values,
        fields.lat.values,
        data.values,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        shading="auto",
        transform=ccrs.PlateCarree(),
        rasterized=True,
        zorder=1,
    )
    ax.add_feature(cfeature.LAND, facecolor="#eeeeee", zorder=4)
    ax.coastlines(resolution="50m", linewidth=0.55, color="#3e454b", zorder=5)
    ax.add_feature(cfeature.BORDERS, linewidth=0.35, edgecolor="#70777d", zorder=5)

    figure.text(0.055, 0.955, f"Meeresoberflächentemperatur · {region.label}", ha="left", va="top", fontsize=20, weight="bold")
    figure.text(0.055, 0.918, f"{day.isoformat()} · {subtitle}", ha="left", va="top", fontsize=14)
    figure.text(0.945, 0.955, source, ha="right", va="top", fontsize=9, color="#4a4f54")

    colorbar_ax = figure.add_axes([0.16, 0.095, 0.68, 0.028])
    colorbar = figure.colorbar(mesh, cax=colorbar_ax, orientation="horizontal", extend="both")
    colorbar.ax.tick_params(labelsize=10)
    colorbar.set_label(unit, fontsize=11)
    figure.text(0.5, 0.038, "Land und stark meereisbedeckte Zellen neutral maskiert", ha="center", va="center", fontsize=9, color="#666666")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        png_path = Path(handle.name)
    try:
        figure.savefig(png_path, dpi=dpi, facecolor="white", edgecolor="none")
        plt.close(figure)
        with Image.open(png_path) as image:
            image = image.convert("RGB")
            if image.size != (region.width_px, region.height_px):
                image = image.resize((region.width_px, region.height_px), Image.Resampling.LANCZOS)
            image.save(output_path, format="WEBP", quality=82, method=6)
    finally:
        plt.close(figure)
        png_path.unlink(missing_ok=True)
    return output_path


def validate_rendered_map(path: Path, region: Region) -> None:
    if not path.exists():
        raise RuntimeError(f"SST-Karte fehlt: {path}")
    if path.stat().st_size <= 10_000:
        raise RuntimeError(f"SST-Karte ist zu klein/leer: {path.stat().st_size} Bytes")
    with Image.open(path) as image:
        if image.format != "WEBP":
            raise RuntimeError(f"Falsches Kartenformat: {image.format}")
        if image.size != (region.width_px, region.height_px):
            raise RuntimeError(f"Falsche Kartengröße: {image.size}")
