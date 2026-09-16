from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Region:
    id: str
    label: str
    west: float
    south: float
    east: float
    north: float
    width_px: int = 1600
    height_px: int = 1050
    fetch_bounds: tuple[float, float, float, float] | None = None

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Final plot extent as west, south, east, north."""
        return (self.west, self.south, self.east, self.north)

    @property
    def download_bounds(self) -> tuple[float, float, float, float]:
        """Buffered source extent used before cropping to the final plot extent."""
        return self.fetch_bounds or self.bounds


REGIONS = {
    "europe": Region(
        "europe",
        "Europa gesamt",
        -30.0,
        25.0,
        45.0,
        72.0,
        fetch_bounds=(-31.5, 23.5, 46.5, 73.5),
    ),
    "mediterranean": Region(
        "mediterranean",
        "Mittelmeer",
        -16.0,
        30.0,
        36.0,
        46.0,
        fetch_bounds=(-17.5, 28.5, 37.5, 47.5),
    ),
    "north_atlantic": Region(
        "north_atlantic",
        "Nordatlantik",
        -65.0,
        20.0,
        25.0,
        78.0,
        fetch_bounds=(-66.5, 18.5, 26.5, 79.5),
    ),
    "nordic_seas": Region(
        "nordic_seas",
        "Nordmeer / Skandinavien",
        -35.0,
        50.0,
        50.0,
        84.0,
        fetch_bounds=(-36.5, 48.5, 51.5, 85.0),
    ),
}

ABSOLUTE_RANGE = (-2.0, 34.0)
ANOMALY_RANGE = (-6.0, 6.0)
SEA_ICE_THRESHOLD = 0.15
ARCHIVE_START = date(2020, 1, 1)
MUR_COLLECTION_ID = "C1996881146-POCLOUD"
MUR_HARMONY_BASE = (
    f"https://harmony.earthdata.nasa.gov/{MUR_COLLECTION_ID}/"
    "ogc-api-coverages/1.0.0/collections/all/coverage/rangeset"
)
NOAA_NORMALS_BASE = (
    "https://psl.noaa.gov/thredds/catalog/Datasets/"
    "noaa.oisst.v2.highres/catalog.html"
)
NOAA_NORMALS_FILENAME = "sst.day.mean.ltm.1991-2020.nc"
NOAA_NORMALS_NCSS = (
    "https://psl.noaa.gov/thredds/ncss/grid/Datasets/"
    "noaa.oisst.v2.highres/sst.day.mean.ltm.1991-2020.nc"
)
