#!/usr/bin/env python3
"""Real hourly rain/snow water-equivalent from ICON-D2 component accumulations.

Separate publication from cloud fields: no precipitation product can break clouds.
RAIN = RAIN_GSP + RAIN_CON; SNOW = SNOW_GSP + SNOW_CON.
The four components accumulate from model start. Compute t - (t-1);
+0 has no preceding full hour and is deliberately omitted.
"""
from __future__ import annotations
import argparse
import bz2
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import tempfile
import time
import numpy as np
from PIL import Image
import eccodes

from build_icon_d2_cloud_film import (
    ROOT, PREFIX, HOURS, WIDTH, HEIGHT, STEP, WEST, EAST, SOUTH, NORTH,
    build_mapping,
)

LOG = logging.getLogger("icon-d2-precip")
COMPONENTS = ("RAIN_GSP", "RAIN_CON", "SNOW_GSP", "SNOW_CON")
MAX_MM_H = 30.0


def url_for(run, kind, hour):
    basename = f"{PREFIX}_{run:%Y%m%d%H}_{hour:03d}_2d_{kind.lower()}.grib2.bz2"
    return f"{ROOT}/{run.hour:02d}/{kind.lower()}/{basename}"


def retrieve(url, retries=3):
    # Snow convection can be an entirely zero field, compressed to <1 KB.
    # Validate bz2/GRIB payload rather than incorrectly enforcing >9 KB.
    for attempt in range(retries):
        try:
            with urlopen(Request(url, headers={"User-Agent": "ClimateDashboard-ICON-D2-Precip/1.0"}), timeout=75) as response:
                raw = response.read()
            if len(raw) < 80 or not raw.startswith(b"BZh"):
                raise ValueError("Keine gültige BZip2-GRIB-Datei")
            return raw
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            if attempt == retries - 1 or isinstance(exc, HTTPError) and exc.code == 404:
                raise RuntimeError(f"ICON-D2-Niederschlagsdatei fehlt/ist fehlerhaft: {url}: {exc}") from exc
            time.sleep(2 ** attempt * 3)
    raise AssertionError("unreachable")


def decode_precip(raw):
    with tempfile.TemporaryFile() as file:
        file.write(bz2.decompress(raw))
        file.seek(0)
        handle = eccodes.codes_grib_new_from_file(file)
        if handle is None:
            raise ValueError("GRIB2 enthält kein Niederschlagsfeld")
        try:
            lat = np.asarray(eccodes.codes_get_array(handle, "latitudes"), dtype=np.float32)
            lon = np.asarray(eccodes.codes_get_array(handle, "longitudes"), dtype=np.float32)
            val = np.asarray(eccodes.codes_get_values(handle), dtype=np.float32)
            unit = str(eccodes.codes_get(handle, "units"))
            step_type = str(eccodes.codes_get(handle, "stepType"))
            grid = str(eccodes.codes_get(handle, "gridType"))
            start_step = int(eccodes.codes_get(handle, "startStep"))
            if lat.size < 100000 or lat.size != lon.size or lat.size != val.size:
                raise ValueError("ICON-D2-Niederschlagsgitter ungültig")
            normalized = unit.replace(" ", "").lower()
            if not (normalized in ("mm", "kgm**-2", "kgm-2", "kgm^-2", "kg/m2", "kgm**-2s**0")):
                raise ValueError(f"Unerwartete Niederschlagseinheit: {unit}")
            if step_type != "accum" or start_step != 0:
                raise ValueError(f"Niederschlag nicht seit Modellstart kumuliert: {step_type}, start={start_step}")
            if grid not in ("rotated_ll", "regular_ll"):
                raise ValueError(f"Unerwartete Projektion: {grid}")
            return lat, lon, val, grid
        finally:
            eccodes.codes_release(handle)


def get_sample(run, kind, hour, mapping, reference):
    raw = retrieve(url_for(run, kind, hour))
    lat, lon, values, grid = decode_precip(raw)
    for k in (0, 101, 1001, 20001):
        if k < len(lat) and (abs(float(lat[k]) - float(reference[0][k])) > 0.0001
                             or abs(float(lon[k]) - float(reference[1][k])) > 0.0001):
            raise ValueError(f"Unterschiedliche Georeferenzierung in {kind} +{hour}")
    idx, valid = mapping
    sampled = values[idx].astype(np.float32, copy=True)
    sampled[~valid] = np.nan
    if np.count_nonzero(np.isfinite(sampled) & (sampled >= -0.01)) < valid.sum() * 0.98:
        raise ValueError(f"Fehlende/ungültige Niederschlagswerte {kind}+{hour}")
    if np.nanmin(sampled) < -0.01:
        raise ValueError(f"Negative kumulierte Niederschlagsmenge {kind}+{hour}")
    return hour, kind, sampled


def encode_hourly(values):
    # byte 0 = dry (<0.05 mm/h); 1..254 logarithmic 0..30+ mm/h; 255 = missing
    encoded = np.full(values.shape, 255, dtype=np.uint8)
    finite = np.isfinite(values)
    encoded[finite] = 0
    wet = finite & (values >= 0.05)
    scaled = np.log1p(np.clip(values[wet], 0, MAX_MM_H)) / np.log1p(MAX_MM_H)
    encoded[wet] = np.clip(np.rint(1 + 253 * scaled), 1, 254).astype(np.uint8)
    return encoded.reshape(HEIGHT, WIDTH)


def build(root: Path, workers: int):
    current = json.loads((root / "current.json").read_text(encoding="utf-8"))
    if current.get("schema") != 1 or current.get("model") != "DWD ICON-D2":
        raise RuntimeError("Zuerst einen vollständigen ICON-D2-Wolkenlauf veröffentlichen")
    if [f["hour"] for f in current["frames"]] != list(HOURS):
        raise RuntimeError("Wolkenlauf muss echte stündliche Daten enthalten")
    run = datetime.strptime(current["cycle"], "%Y%m%d%H").replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - run > timedelta(hours=24):
        raise RuntimeError("Wolkenlauf für Niederschlagsberechnung zu alt")
    output = root / "precip.json"
    if output.exists():
        try:
            old = json.loads(output.read_text(encoding="utf-8"))
            if (old.get("cycle") == current["cycle"] and len(old.get("frames", [])) == len(HOURS)
                and all((root / item).is_file()
                        for row in old["frames"][1:] for item in row.get("layers", {}).values())
                and all(set(row.get("layers", {})) == {"rain", "snow"} for row in old["frames"][1:])):
                LOG.info("Vollständiger Niederschlag für %s bereits vorhanden", current["cycle"])
                return
        except (ValueError, OSError):
            pass

    ref_raw = retrieve(url_for(run, "RAIN_GSP", 0))
    lat, lon, values, grid = decode_precip(ref_raw)
    mapping = build_mapping(lat, lon)
    reference = (lat, lon)
    # A single mapped source field is held per (parameter, hour). All hourly
    # rain/snow values are derived from original accumulation differences.
    samples = {(0, "RAIN_GSP"): get_sample(run, "RAIN_GSP", 0, mapping, reference)[2]}
    jobs = [(hour, kind) for hour in HOURS for kind in COMPONENTS
            if (hour, kind) != (0, "RAIN_GSP")]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(get_sample, run, kind, hour, mapping, reference): (hour, kind)
            for hour, kind in jobs
        }
        for future in as_completed(futures):
            hour, kind, arr = future.result()
            samples[hour, kind] = arr
            LOG.info("Echte ICON-D2-Niederschlagskomponente +%02d %s", hour, kind)
    frames = [{"hour": 0, "valid_utc": run.isoformat().replace("+00:00", "Z"),
               "layers": {}}]
    folder = root / "precip" / "frames" / current["cycle"]
    folder.mkdir(parents=True, exist_ok=True)
    for hour in HOURS[1:]:
        layers = {}
        for label, components in (("rain", ("RAIN_GSP", "RAIN_CON")),
                                  ("snow", ("SNOW_GSP", "SNOW_CON"))):
            now = samples[hour, components[0]] + samples[hour, components[1]]
            previous = samples[hour-1, components[0]] + samples[hour-1, components[1]]
            hourly = now - previous
            if np.nanmin(hourly) < -0.5:
                raise ValueError(f"Nicht monotone Akkumulation +{hour} {label}")
            hourly = np.where(hourly < 0, 0, hourly)
            name = f"{label}_{hour:03d}.png"
            Image.fromarray(encode_hourly(hourly), mode="L").save(folder / name, optimize=True)
            layers[label] = f"precip/frames/{current['cycle']}/{name}"
        frames.append({"hour": hour,
                       "valid_utc": (run + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
                       "layers": layers})

    manifest = {
        "schema": 1, "model": "DWD ICON-D2", "cycle": current["cycle"],
        "built_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "grid": current["grid"], "hours": list(HOURS), "frames": frames,
        "layers": {"rain": "Regen aus RAIN_GSP+RAIN_CON",
                   "snow": "Schnee aus SNOW_GSP+SNOW_CON"},
        "unit": "mm water-equivalent per 1 hour",
        "encoding": {"mode": "log1p", "max_mm_h": MAX_MM_H, "dry_code": 0,
                     "missing_code": 255, "wet_codes": [1, 254], "min_visible_mm_h": 0.05},
        "method": "Difference of cumulative ICON-D2 components at consecutive forecast hours; +0 unavailable",
        "note": "Snow is liquid-water equivalent, not centimetres of fresh snow. Graupel is not included.",
        "source": "DWD Open Data ICON-D2 GRIB2",
    }
    tmp = output.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(output)
    LOG.info("Niederschlag veröffentlicht: %s, %d Stunden, %d echte Bilder", current["cycle"], len(frames), (len(frames)-1)*2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build(args.out, args.max_workers)


if __name__ == "__main__":
    main()
