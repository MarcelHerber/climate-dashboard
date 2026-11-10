#!/usr/bin/env python3
"""Build a genuine five-layer ECMWF IFS upper-air dynamics film.

Sources: ECMWF IFS 0.25 degree Open Data / CC BY 4.0.
For +0..+48 every three hours: TCWV, 250-hPa wind, mean 400-600-hPa
upward omega, layer-mean 200-300-hPa Ertel PV, and regional divergent wind.
PV and divergent wind are diagnosed, not native ECMWF fields. The latter is
a limited-domain Poisson approximation (Neumann boundaries), not a global
spherical-harmonic Helmholtz decomposition.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import tempfile

import eccodes
from ecmwf.opendata import Client
import numpy as np
from PIL import Image
from scipy.fft import dctn, idctn

LOG = logging.getLogger("ifs-dynamics")
WEST, EAST, SOUTH, NORTH, STEP = -70., 45., 12., 75., 0.25
WIDTH = round((EAST-WEST)/STEP)+1
HEIGHT = round((NORTH-SOUTH)/STEP)+1
HOURS = tuple(range(0, 49, 3))
LEVELS = (200, 250, 300)
OMEGA_LEVELS = (400, 500, 600)
PARAMETERS = ("u", "v", "t", "vo", "d")
SCALES = {
    "tcwv": (0., 70.),
    "jet": (0., 110.),
    "ascent": (0., 1.5),
    "pv": (-2., 15.),
    "iru": (-45., 45.),
    "irv": (-45., 45.),
}
G = 9.80665
OMEGA = 7.2921159e-5


def decode_grib(path: Path, required: set[str]) -> dict[str, np.ndarray]:
    result = {}
    with path.open("rb") as stream:
        while True:
            message = eccodes.codes_grib_new_from_file(stream)
            if message is None:
                break
            try:
                param = str(eccodes.codes_get(message, "shortName"))
                kind = str(eccodes.codes_get(message, "typeOfLevel"))
                # TCWV can carry atmosphereSingleLayer rather than a surface level.
                key = param if param == "tcwv" else param + str(int(eccodes.codes_get(message, "level")))
                if key not in required:
                    continue
                if key in result:
                    raise ValueError("Duplicate GRIB field " + key)
                lat = np.asarray(eccodes.codes_get_array(message, "latitudes"), dtype=np.float32)
                lon = np.asarray(eccodes.codes_get_array(message, "longitudes"), dtype=np.float32)
                values = np.asarray(eccodes.codes_get_values(message), dtype=np.float32)
                if not (len(lat) == len(lon) == len(values)):
                    raise ValueError("Inconsistent GRIB grid for " + key)
                lon = np.where(lon > 180., lon-360., lon)
                rows = np.rint((NORTH-lat)/STEP).astype(np.int32)
                cols = np.rint((lon-WEST)/STEP).astype(np.int32)
                valid = (rows >= 0) & (rows < HEIGHT) & (cols >= 0) & (cols < WIDTH)
                valid &= (np.abs((NORTH-rows*STEP)-lat) < .02)
                valid &= (np.abs((WEST+cols*STEP)-lon) < .02)
                valid &= np.isfinite(values)
                grid = np.full((HEIGHT, WIDTH), np.nan, dtype=np.float32)
                grid[rows[valid], cols[valid]] = values[valid]
                if np.isfinite(grid).mean() < .99:
                    raise ValueError("Insufficient geographic coverage of " + key)
                result[key] = grid
            finally:
                eccodes.codes_release(message)
    if result.keys() != required:
        raise RuntimeError("GRIB missing keys: " + ", ".join(sorted(required-set(result))))
    return result


def read_fields(client: Client, run: datetime, hour: int) -> dict[str, np.ndarray]:
    base = {"date": run.strftime("%Y%m%d"), "time": run.hour,
            "step": hour, "stream": "oper", "type": "fc", "resol": "0p25"}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        sfc = root / "vapor.grib"
        upper = root / "upper.grib"
        vertical = root / "omega.grib"
        client.retrieve(**base, levtype="sfc", param="tcwv", target=str(sfc))
        client.retrieve(**base, levtype="pl", param=list(PARAMETERS),
                        levelist=list(LEVELS), target=str(upper))
        client.retrieve(**base, levtype="pl", param="w",
                        levelist=list(OMEGA_LEVELS), target=str(vertical))
        fields = decode_grib(sfc, {"tcwv"})
        fields.update(decode_grib(upper, {p+str(z) for p in PARAMETERS for z in LEVELS}))
        fields.update(decode_grib(vertical, {"w"+str(z) for z in OMEGA_LEVELS}))
    return fields


def erte_pv(fields: dict[str, np.ndarray]) -> np.ndarray:
    """Three-level, isobaric Ertel PV diagnostic including tilting terms (PVU).

    Uses centered pressure differences at 250 hPa and one-sided at 200/300;
    a layer average cannot resolve fine tropopause folds as well as model-level PV.
    """
    p = np.array(LEVELS, dtype=np.float64) * 100.
    t = np.stack([fields["t"+str(z)] for z in LEVELS]).astype(np.float64)
    u = np.stack([fields["u"+str(z)] for z in LEVELS]).astype(np.float64)
    v = np.stack([fields["v"+str(z)] for z in LEVELS]).astype(np.float64)
    vo = np.stack([fields["vo"+str(z)] for z in LEVELS]).astype(np.float64)
    theta = t * (100000./p[:, None, None]) ** .2854
    theta_p = np.gradient(theta, p, axis=0, edge_order=2)
    u_p = np.gradient(u, p, axis=0, edge_order=2)
    v_p = np.gradient(v, p, axis=0, edge_order=2)
    lat = np.deg2rad(NORTH-np.arange(HEIGHT)*STEP)
    dx = (111195.*STEP * np.maximum(np.cos(lat), .12))[None, :, None]
    dy = 111195.*STEP
    theta_x = np.gradient(theta, axis=2)/dx
    theta_y = -np.gradient(theta, axis=1)/dy
    coriolis = (2*OMEGA*np.sin(lat))[None, :, None]
    pv = -G*((vo+coriolis)*theta_p + u_p*theta_y - v_p*theta_x)*1e6
    return np.nanmean(pv, axis=0).astype(np.float32)


def divergent_wind(fields: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Regional Poisson inversion of observed 200/250/300 hPa divergence.

    Neumann boundaries, constant 45-degree latitude metric; use as a diagnostic,
    NOT as an exact global Helmholtz decomposition.
    """
    div = np.mean(np.stack([fields["d"+str(z)] for z in LEVELS]), axis=0)
    if not np.isfinite(div).all():
        raise ValueError("Missing divergence in region")
    div = div.astype(np.float64)-float(div.mean())
    dy = 111195.*STEP
    dx = dy*np.cos(np.deg2rad(45.))
    ny, nx = div.shape
    kx = np.arange(nx)
    ky = np.arange(ny)
    eig = (2*np.cos(np.pi*kx/nx)-2)[None, :]/(dx*dx) + \
          (2*np.cos(np.pi*ky/ny)-2)[:, None]/(dy*dy)
    eig[0, 0] = 1.
    source = dctn(div, norm="ortho")
    source[0, 0] = 0.
    potential = idctn(source/eig, norm="ortho")
    ui = np.gradient(potential, axis=1)/dx
    vi = -np.gradient(potential, axis=0)/dy
    return ui.astype(np.float32), vi.astype(np.float32)


def derive(fields: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    u, v = fields["u250"], fields["v250"]
    ir_u, ir_v = divergent_wind(fields)
    return {
        "tcwv": fields["tcwv"],
        "jet": np.hypot(u, v),
        "ascent": np.maximum(0., -np.mean(
            np.stack([fields["w"+str(z)] for z in OMEGA_LEVELS]), axis=0)),
        "pv": erte_pv(fields),
        "iru": ir_u, "irv": ir_v,
    }


def encode(values: np.ndarray, lo: float, hi: float) -> Image.Image:
    if values.shape != (HEIGHT, WIDTH):
        raise ValueError("Unexpected field dimensions")
    good = np.isfinite(values)
    if np.mean(good) < .99:
        raise ValueError("Too many missing cells")
    # 0..254 encode a fixed interval; 255 alone indicates a missing grid cell.
    pixels = np.full(values.shape, 255, np.uint8)
    pixels[good] = np.rint(
        np.clip((values[good]-lo)/(hi-lo), 0, 1)*254
    ).astype(np.uint8)
    return Image.fromarray(pixels, mode="L")


def cycle_candidates() -> list[datetime]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    # Avoid selecting a still-incomplete cycle.
    cutoff = now-timedelta(hours=8)
    first = cutoff.replace(hour=12 if cutoff.hour >= 12 else 0)
    return [first-timedelta(hours=12*i) for i in range(4)]


def build(out: Path, hours: tuple[int, ...] = HOURS) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    client = Client(source="ecmwf", model="ifs", resol="0p25")
    cycle = None
    for candidate in cycle_candidates():
        try:
            # Require both pressure-level and surface data for final forecast step.
            read_fields(client, candidate, hours[-1])
            cycle = candidate
            break
        except Exception as exc:
            LOG.warning("ECMWF cycle %s not ready: %s", candidate, exc)
    if cycle is None:
        raise RuntimeError("No complete IFS cycle available; existing published data remain unchanged")
    oldfile = out/"current.json"
    if oldfile.exists():
        try:
            previous = json.loads(oldfile.read_text())
            if previous.get("cycle") == cycle.strftime("%Y%m%d%H") and \
               len(previous.get("frames", [])) == len(hours):
                if all((out/path).is_file() for frame in previous["frames"] for path in frame["images"].values()):
                    LOG.info("Full IFS cycle already present")
                    return previous
        except (KeyError, OSError, ValueError):
            pass
    frames = []
    folder = out/"frames"/cycle.strftime("%Y%m%d%H")
    folder.mkdir(parents=True, exist_ok=True)
    for hour in hours:
        data = derive(read_fields(client, cycle, hour))
        paths = {}
        for name, field in data.items():
            filename = f"{name}_{hour:03d}.png"
            target = folder/filename
            encode(field, *SCALES[name]).save(target, optimize=True)
            paths[name] = f"frames/{cycle:%Y%m%d%H}/{filename}"
        frames.append({"hour": hour,
                       "valid_utc": (cycle+timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
                       "images": paths})
        LOG.info("Verified IFS dynamics +%d hours", hour)
    manifest = {
        "schema": 1, "source": "ECMWF IFS Open Data 0.25 degree (CC BY 4.0)",
        "cycle": cycle.strftime("%Y%m%d%H"),
        "initialized_utc": cycle.isoformat().replace("+00:00", "Z"),
        "built_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "grid": {"west": WEST, "east": EAST, "south": SOUTH, "north": NORTH,
                 "width": WIDTH, "height": HEIGHT, "step": STEP},
        "units": {"tcwv": "mm", "jet": "m/s", "ascent": "Pa/s",
                  "pv": "PVU", "iru": "m/s", "irv": "m/s"},
        "encoding": {"type": "grayscale-png", "minmax": SCALES, "missing": 255,
                     "scale_max": 254},
        "diagnostics": {
            "pv": "Layer mean 200/250/300 hPa Ertel PV using 3 pressure levels; approximate vertical derivatives",
            "irrotational": "200/250/300 hPa divergent wind from regional Neumann Poisson inversion; boundary/metric approximation",
            "ascent": "positive upward motion from negative pressure velocity at 400/500/600 hPa"},
        "frames": frames,
    }
    (out/"current.json.tmp").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out/"current.json.tmp").replace(out/"current.json")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true", help="Fetch only first two timestamps for diagnostics")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build(args.out, (0, 3) if args.smoke else HOURS)
