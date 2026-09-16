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

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)


REGIONS = {
    "europe": Region("europe", "Europa gesamt", -30.0, 30.0, 45.0, 72.0),
    "mediterranean": Region("mediterranean", "Mittelmeer", -6.0, 29.0, 38.0, 47.0),
    "north_baltic": Region("north_baltic", "Nordsee + Ostsee", -12.0, 48.0, 32.0, 66.0),
    "north_atlantic": Region("north_atlantic", "Nordatlantik", -60.0, 25.0, 20.0, 70.0),
    "nordic_seas": Region("nordic_seas", "Nordmeer / Skandinavien", -45.0, 55.0, 50.0, 82.0),
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
