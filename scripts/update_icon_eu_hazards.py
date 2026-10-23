#!/usr/bin/env python3
"""Build five non-overlapping 24-hour hazard maps from DWD ICON-EU GRIB2.

All severities are model-based indicators, NOT official weather warnings.
The script refuses stale/incomplete cycles and never invents missing fields.
Requires numpy and eccodes (ecCodes Python bindings).
"""
from __future__ import annotations
import argparse
import base64
import bz2
import datetime as dt
import json
import logging
import math
import pathlib
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import eccodes

ROOT = "https://opendata.dwd.de/weather/nwp/icon-eu/grib"
PREFIX = "icon-eu_europe_regular-lat-lon_single-level"
PARAMETERS = ("VMAX_10M", "TOT_PREC", "SNOW_GSP", "SNOW_CON", "TMAX_2M", "TMIN_2M", "VIS")
# 0.125° is the aggregation grid, not the native ICON-EU model resolution.
# It divides the older 0.25° cells into four independently classified areas.
LAT_MIN, LON_MIN, STEP, ROWS, COLS = 27.0, -26.0, 0.125, 368, 688
DURATIONS = (6, 12, 24)
WINDOWS = tuple((h, h + duration) for duration in DURATIONS
                for h in range(0, 120, duration))

RAIN_LIMITS = {1: (10, 15, 25, 40), 3: (15, 20, 30, 50),
               6: (15, 20, 35, 60), 24: (20, 30, 50, 80)}
LIMITS = {
    "wind": (65, 85, 105, 120),   # 10-m max gust, km/h
    "rain": RAIN_LIMITS,
    "snow": (5, 10, 20, 40),      # 24-h snow-water equivalent, mm

    "heat": (30, 35, 38, 40),     # max 2-m temp, Celsius
    "cold": (-5, -10, -15, -20),  # min 2-m temp, Celsius
    "fog": (500,),  # visibility below 500 m: yellow only (level 1)
}
# Experimental shorter-period snow-water-equivalent guidance (mm).
SNOW_LIMITS = {6: (2.5, 5, 10, 20), 12: (3.5, 7, 15, 30), 24: LIMITS["snow"]}
HAZARDS = tuple(LIMITS)
HTTP_HEADERS = {"User-Agent": "ClimateDashboardICONHazardMonitor/1.0 (public open-data processing)"}
log = logging.getLogger("icon-hazards")


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def request_bytes(url, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HTTP_HEADERS), timeout=50) as resp:
                return resp.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (403, 404):
                return None
            if attempt == retries - 1:
                log.warning("Download fehlgeschlagen %s: %s", url, exc)
                return None
            time.sleep((attempt + 1) * 3)
    return None


def url_for(cycle, parameter, hour):
    run = cycle.strftime("%Y%m%d%H")
    filename = "%s_%s_%03d_%s.grib2.bz2" % (PREFIX, run, hour, parameter)
    return "%s/%02d/%s/%s" % (ROOT, cycle.hour, parameter.lower(), filename)


def choose_cycle(now):
    # Complete 120-h forecasts are required for all five 24-hour windows.
    start = now.replace(minute=0, second=0, microsecond=0)
    start -= dt.timedelta(hours=start.hour % 6)
    for i in range(1, 5):
        candidate = start - dt.timedelta(hours=i * 6)
        targets = (url_for(candidate, "VMAX_10M", 120),
                   url_for(candidate, "TOT_PREC", 120))
        if all(request_bytes(u, retries=1) for u in targets):
            return candidate
    raise RuntimeError("Kein vollständiger ICON-EU-Hauptlauf mit +120 h verfügbar")


def decode(raw):
    if raw is None:
        return None
    handle = None
    try:
        data = bz2.decompress(raw)
        import tempfile
        # ecCodes requires a real fileno() -- BytesIO is not supported.
        with tempfile.TemporaryFile() as source:
            source.write(data)
            source.seek(0)
            handle = eccodes.codes_grib_new_from_file(source)
            if handle is None:
                return None
            values = np.asarray(eccodes.codes_get_values(handle), dtype=np.float32)
            # ecCodes may return "0m" for GRIB files at +0 h.
            def to_hours(value):
                if isinstance(value, (int, float)):
                    return float(value)
                value = str(value).strip().lower()
                if value.endswith("m"):
                    return float(value[:-1]) / 60
                if value.endswith("s"):
                    return float(value[:-1]) / 3600
                if value.endswith("h"):
                    return float(value[:-1])
                return float(value)
            start_step = to_hours(eccodes.codes_get(handle, "startStep"))
            end_step = to_hours(eccodes.codes_get(handle, "endStep"))
            layout = (
                int(eccodes.codes_get(handle, "numberOfPoints")),
                str(eccodes.codes_get(handle, "gridType")),
            )
        result = (values, start_step, end_step, layout, handle)
        handle = None  # The caller releases the returned GRIB handle.
        return result
    except Exception as exc:
        log.warning("GRIB-Dekodierung: %s", exc)
        return None
    finally:
        if handle is not None:
            eccodes.codes_release(handle)


def grid_index(handle):
    lat = np.asarray(eccodes.codes_get_array(handle, "latitudes"), dtype=np.float32)
    lon = np.asarray(eccodes.codes_get_array(handle, "longitudes"), dtype=np.float32)
    lon = np.where(lon > 180, lon - 360, lon)
    r = np.floor((lat - LAT_MIN) / STEP).astype(np.int32)
    c = np.floor((lon - LON_MIN) / STEP).astype(np.int32)
    valid = (r >= 0) & (r < ROWS) & (c >= 0) & (c < COLS)
    return r[valid] * COLS + c[valid], valid


class Aggregator:
    def __init__(self):
        self.index = None
        self.mask = None
        self.layout = None
        self.size = ROWS * COLS
        # The fixed output raster is larger than the actual model domain.
        # Record geographic cells with valid ICON data, including level zero.
        self.domain_cells = np.zeros(self.size, dtype=bool)
        self.domain_initialized = False
        self.data = {key: [np.zeros(self.size, dtype=np.uint8) for _ in WINDOWS]
                     for key in HAZARDS}
        self.metrics = {key: [None for _ in WINDOWS] for key in HAZARDS}
        self.coverage = {key: [0 for _ in WINDOWS] for key in HAZARDS}

    def ingest(self, raw):
        decoded = decode(raw)
        if decoded is None:
            return None
        values, begin, end, layout, handle = decoded
        try:
            if self.layout is None:
                self.index, self.mask = grid_index(handle)
                self.layout = layout
            elif layout != self.layout:
                raise ValueError("GRIB-Raster ist nicht mit den anderen Parametern identisch")
            return values, begin, end
        finally:
            eccodes.codes_release(handle)

    def aggregate(self, values, reducer="max"):
        if len(values) != len(self.mask):
            raise ValueError("GRIB-Feld hat unerwartete Rastergröße")
        relevant = values[self.mask]
        good = np.isfinite(relevant) & (np.abs(relevant) < 1e15)
        if not self.domain_initialized and np.any(good):
            self.domain_cells[self.index[good]] = True
            self.domain_initialized = True
        out = np.full(self.size, -np.inf if reducer == "max" else np.inf, np.float32)
        if reducer == "max":
            np.maximum.at(out, self.index[good], relevant[good])
        else:
            np.minimum.at(out, self.index[good], relevant[good])
        return out

    def classify(self, key, values, duration=None):
        if key == "wind":
            arr = np.searchsorted(LIMITS["wind"], values * 3.6, side="right")
        elif key == "rain":
            arr = np.searchsorted(RAIN_LIMITS[duration], values, side="right")
        elif key == "snow":
            arr = np.searchsorted(SNOW_LIMITS[duration], values, side="right")
        elif key == "heat":
            arr = np.searchsorted(LIMITS["heat"], values - 273.15, side="right")
        elif key == "cold":
            arr = np.searchsorted((5, 10, 15, 20), 273.15 - values, side="right")
        elif key == "fog":
            # Fog is an informational yellow indicator only, regardless of visibility.
            arr = (values < LIMITS["fog"][0]).astype(np.uint8)
        else:
            raise KeyError(key)
        arr[~np.isfinite(values)] = 0
        return np.asarray(arr, dtype=np.uint8)

    def add(self, key, window, values, duration=None):
        levels = self.classify(key, values, duration)
        np.maximum(self.data[key][window], levels, out=self.data[key][window])
        self.coverage[key][window] += 1


def hours_for(param):
    if param in ("SNOW_GSP", "SNOW_CON"):
        # Six-hour endpoints permit genuine non-overlapping 6/12/24-h sums.
        return list(range(0, 121, 6))
    if param in ("TMAX_2M", "TMIN_2M"):
        # ICON-EU extrema: hourly through +51 h, later six-hour products.
        return list(range(1, 52)) + list(range(54, 121, 6))
    # Regular-grid ICON-EU main cycles: hourly through +78 h,
    # 3-hourly thereafter (never infer one-hour rain peaks from 3-h data).
    # Missing files are explicitly skipped and coverage is reported.
    return list(range(0, 79)) + list(range(81, 121, 3))


def download_parameter(cycle, name):
    result = {}
    hours = hours_for(name)
    # Four concurrent requests at most to be considerate of the public server.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(request_bytes, url_for(cycle, name, hour)): hour for hour in hours}
        for future in as_completed(futures):
            hour = futures[future]
            raw = future.result()
            if raw:
                result[hour] = raw
    log.info("%s: %d/%d GRIB-Dateien", name, len(result), len(hours))
    return result


def cumulative_fields(raws, agg, name):
    result = {}
    for h, raw in sorted(raws.items()):
        decoded = agg.ingest(raw)
        if decoded is None:
            continue
        values, begin, end = decoded
        if end != h:
            log.warning("%s +%s: GRIB-Endstunde %s abweichend", name, h, end)
            continue
        if begin != 0:
            # Never falsely calculate accumulated precipitation differences.
            log.warning("%s +%s: StartStep %s statt 0", name, h, begin)
            continue
        result[h] = values
    return result


def difference(current, previous):
    diff = current - previous
    # A significant reset or change in accumulation convention is unsafe.
    good = np.isfinite(diff)
    if np.count_nonzero(good) == 0:
        return None
    if np.count_nonzero(diff[good] < -0.3) > max(50, int(diff.size * .001)):
        return None
    return np.maximum(diff, 0)


def add_wind(agg, raws):
    for h, raw in sorted(raws.items()):
        if h == 0:
            continue
        decoded = agg.ingest(raw)
        if decoded is None:
            continue
        val, begin, end = decoded
        if end != h or begin < 0 or begin >= h:
            continue
        coarse = agg.aggregate(val)
        for wi, (a, b) in enumerate(WINDOWS):
            if begin >= a and end <= b:
                agg.add("wind", wi, coarse)


def add_accum_rain(agg, totals):
    for wi, (start, stop) in enumerate(WINDOWS):
        for duration in RAIN_LIMITS:
            if duration > stop - start:
                continue
            for end in range(start + duration, stop + 1):
                begin = end - duration
                if begin not in totals or end not in totals:
                    continue
                diff = difference(totals[end], totals[begin])
                if diff is None:
                    continue
                agg.add("rain", wi, agg.aggregate(diff), duration=duration)
        if start not in totals or stop not in totals:
            raise RuntimeError("ICON-EU Regen +%d..+%d: benötigte Akkumulation fehlt" % (start, stop))


def add_snow(agg, snow_gsp, snow_con):
    for wi, (start, stop) in enumerate(WINDOWS):
        if not all(h in arr for h in (start, stop) for arr in (snow_gsp, snow_con)):
            continue
        a = difference(snow_gsp[stop], snow_gsp[start])
        b = difference(snow_con[stop], snow_con[start])
        if a is None or b is None:
            continue
        agg.add("snow", wi, agg.aggregate(a + b), duration=stop - start)


def add_extreme(agg, raws, key):
    for h, raw in sorted(raws.items()):
        decoded = agg.ingest(raw)
        if decoded is None:
            continue
        values, begin, end = decoded
        if end != h or begin < 0 or begin >= h and key != "fog":
            continue
        coarse = agg.aggregate(values, "min" if key in ("cold", "fog") else "max")
        for wi, (a, b) in enumerate(WINDOWS):
            if a < end <= b and (key == "fog" or begin >= a):
                agg.add(key, wi, coarse)


def pack_levels(arr):
    """Store two levels (0..4) in each byte to halve transfer and decode cost."""
    if np.any(arr > 4):
        raise ValueError("Gefahrenstufe ausserhalb 0..4")
    packed = np.zeros((arr.size + 1) // 2, dtype=np.uint8)
    packed[:] = arr[::2]
    packed[:arr[1::2].size] |= arr[1::2] << 4
    return base64.b64encode(packed.tobytes()).decode("ascii")


def encode_rle_levels(arr):
    """Compact lossless per-cell hazard severity in 3-byte (value, uint16-run) tuples.

    Unlike blurring/interpolation, this preserves every classified grid cell.
    Base64 payloads shrink dramatically for the large level-zero regions.
    """
    if arr.ndim != 1 or np.any(arr > 4):
        raise ValueError("Ungueltige Gefahrenstufen fuer RLE")
    changes = np.flatnonzero(arr[1:] != arr[:-1]) + 1
    stops = np.concatenate(([0], changes, [arr.size]))
    output = bytearray()
    for start, end in zip(stops[:-1], stops[1:]):
        remaining = int(end - start)
        value = int(arr[start])
        while remaining:
            count = min(remaining, 65535)
            output.extend((value, count & 255, count >> 8))
            remaining -= count
    return base64.b64encode(output).decode("ascii")


def build(cycle, output):
    agg = Aggregator()
    wind = download_parameter(cycle, "VMAX_10M")
    add_wind(agg, wind)
    rain = cumulative_fields(download_parameter(cycle, "TOT_PREC"), agg, "TOT_PREC")
    add_accum_rain(agg, rain)
    gs = cumulative_fields(download_parameter(cycle, "SNOW_GSP"), agg, "SNOW_GSP")
    cs = cumulative_fields(download_parameter(cycle, "SNOW_CON"), agg, "SNOW_CON")
    add_snow(agg, gs, cs)
    for parameter, key in (("TMAX_2M", "heat"), ("TMIN_2M", "cold"), ("VIS", "fog")):
        add_extreme(agg, download_parameter(cycle, parameter), key)
    for wi, (start, stop) in enumerate(WINDOWS):
        if not agg.coverage["wind"][wi] or not agg.coverage["rain"][wi]:
            raise RuntimeError("Wind/Regen im Zeitfenster %s–%s h nicht verfügbar" % (start, stop))
    # Bounding rectangle of VALID meteorological model points, not the
    # raster envelope and never the extent of non-zero warning colours.
    if not agg.domain_initialized:
        raise RuntimeError("Keine gültigen ICON-EU-Rasterpunkte für den Kartenausschnitt")
    occupied = np.flatnonzero(agg.domain_cells)
    row, col = np.divmod(occupied, COLS)
    coverage_bounds = {
        "south": LAT_MIN + int(row.min()) * STEP,
        "north": LAT_MIN + (int(row.max()) + 1) * STEP,
        "west": LON_MIN + int(col.min()) * STEP,
        "east": LON_MIN + (int(col.max()) + 1) * STEP,
    }
    log.info("ICON-EU Rasterabdeckung: %s", coverage_bounds)
    generated = utcnow().isoformat().replace("+00:00", "Z")
    for duration in DURATIONS:
        manifest = {
            "schema": 2,
            "product": "DWD ICON-EU Europa-Gefahrenmonitor",
            "run_utc": cycle.isoformat().replace("+00:00", "Z"),
            "generated_utc": generated,
            "duration_h": duration,
            "not_official_warning": True,
            "grid": {"lat_min": LAT_MIN, "lon_min": LON_MIN, "step": STEP,
                     "rows": ROWS, "cols": COLS, "encoding": "rle-u8-base64",
                     "coverage_bounds": coverage_bounds},
            "thresholds": {**LIMITS, "snow_by_duration": SNOW_LIMITS},
            "periods": [],
            "notes": {
                "wind": "Maximale 10-m-Böen über verfügbare Modell-Ausgabeintervalle",
                "rain": "Aus TOT_PREC differenzierte exakt verfügbare 1/3/6/24-h-Mengen; Intervalle dürfen nicht länger als das dargestellte Fenster sein",
                "snow": "SNOW_GSP + SNOW_CON, echtes Schneewasseräquivalent über gewählte Fensterlänge, keine Neuschneehöhe",
                "heat": "ICON-EU TMAX_2M, Maximum der verfügbaren Ausgabeintervalle",
                "cold": "ICON-EU TMIN_2M, Minimum der verfügbaren Ausgabeintervalle",
                "fog": "ICON-EU Sichtweite, Gelb bei < 500 m (maximal Stufe 1), nur solange VIS bereitgestellt wird",
                "convective": "Gewitter- und Hagelwarnungen werden nicht aus CAPE allein abgeleitet",
            },
        }
        for wi, (start, stop) in enumerate(WINDOWS):
            if stop - start != duration:
                continue
            manifest["periods"].append({
                "start_h": start,
                "end_h": stop,
                "layers": {key: encode_rle_levels(agg.data[key][wi])
                           if agg.coverage[key][wi] else None for key in HAZARDS},
                "samples": {key: agg.coverage[key][wi] for key in HAZARDS},
                "rain_intervals_available": {str(d): sum(
                    1 for h in range(start + d, stop + 1)
                    if h - d in rain and h in rain) if d <= duration else 0
                    for d in RAIN_LIMITS},
            })
        target = output if duration == 24 else output.with_name(
            output.stem + "_" + str(duration) + "h" + output.suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                          encoding="utf-8")
        log.info("%s-h Gefahrenkarte: %s (%.1f KiB)", duration, target,
                 target.stat().st_size / 1024)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--cycle", default=None, help="YYYYMMDDHH, sonst neuester vollständiger Hauptlauf")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cycle = (dt.datetime.strptime(args.cycle, "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
             if args.cycle else choose_cycle(utcnow()))
    log.info("ICON-EU Hauptlauf: %s UTC", cycle)
    build(cycle, args.output)


if __name__ == "__main__":
    main()
