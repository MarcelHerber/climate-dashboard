#!/usr/bin/env python3
"""NOAA GFS 0.5 degree +3 hour forecast, 2m temperature Europe.

Compare genuine +3h 2m temperature to a uniform +3h CFSR/CFSv2 normal.
1991-2020 anomalies are only published after a verified CFSR (1991-03/2011) +
CFSv2 (04/2011-2020) 4-cycle +3h 2m-temperature reference is installed.
The display grid is shifted half a native cell to match the existing CPC
Europe country masks; this interpolation does not increase resolution.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import time
from urllib.parse import urlencode

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "gfs_analysis_europe"
RAW = OUT / "f003_daily"
BASELINE = OUT / "climatology_1991_2020_f003.npz"
WIDTH, HEIGHT = 140, 76
FILL = -32768
NOAA = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p50.pl"
CYCLES = (0, 6, 12, 18)
PALETTE_LABEL = "ERA5-Land Europe 19-class temperature anomaly palette"


def day_index(day: date) -> int:
    if (day.month, day.day) == (2, 29):
        return -1
    return (date(2001, day.month, day.day) - date(2001, 1, 1)).days


def normal_for_date(normals: np.ndarray, day: date) -> np.ndarray:
    if (day.month, day.day) == (2, 29):
        return (normals[58] + normals[59]) * 0.5
    return normals[day_index(day)]


def encode_q10(a: np.ndarray) -> str:
    values = np.asarray(a, dtype=np.float32)
    out = np.full(values.shape, FILL, dtype="<i2")
    good = np.isfinite(values) & (values > -100) & (values < 100)
    out[good] = np.rint(values[good] * 10).astype("<i2")
    return base64.b64encode(out.tobytes(order="C")).decode("ascii")


def decode_q10(data: str, shape: tuple[int, ...]) -> np.ndarray:
    a = np.frombuffer(base64.b64decode(data, validate=True), dtype="<i2")
    if a.size != int(np.prod(shape)):
        raise ValueError("GRIB temperature array size mismatch")
    a = a.reshape(shape).astype(np.float32)
    a[a == FILL] = np.nan
    return a / 10


def analysis_url(day: date, cycle: int) -> str:
    if cycle not in CYCLES:
        raise ValueError("Only 00,06,12,18 UTC model cycles")
    params = {
        "file": f"gfs.t{cycle:02d}z.pgrb2.0p50.f003",
        "lev_2_m_above_ground": "on",
        "var_TMP": "on",
        "dir": f"/gfs.{day:%Y%m%d}/{cycle:02d}/atmos",
    }
    return NOAA + "?" + urlencode(params)


def grib_2m_analysis(raw: bytes, day: date, cycle: int) -> np.ndarray:
    import eccodes as ec

    if len(raw) < 150 or not raw.startswith(b"GRIB"):
        raise ValueError("NOMADS did not return a GRIB2 f003 field")
    import tempfile
    with tempfile.TemporaryFile(mode='w+b') as f:
        f.write(raw)
        f.seek(0)
        gid = ec.codes_grib_new_from_file(f)
    if gid is None:
        raise ValueError("GRIB2 f003 was empty")
    try:
        def get(k):
            return ec.codes_get(gid, k)
        if (int(get("edition")) != 2
            or str(get("typeOfLevel")) != "heightAboveGround"
            or int(get("level")) != 2
            or int(get("forecastTime")) != 3
            or str(get("stepRange")) not in ("3", "3-3")):
            raise ValueError("Unexpected parameter or forecast lead: require 2m TMP f003")
        if (int(get("dataDate")) != int(day.strftime("%Y%m%d"))
            or int(get("dataTime")) != cycle * 100
            or int(get("validityDate")) != int(day.strftime("%Y%m%d"))
            or int(get("validityTime")) != cycle * 100 + 300):
            raise ValueError("GRIB f003 initialization date/cycle mismatch")
        if (int(get("Ni")), int(get("Nj"))) != (720, 361):
            raise ValueError("Wrong native GFS grid: expected global 0.5 degree")
        if abs(float(get("latitudeOfFirstGridPointInDegrees")) - 90.0) > 0.01:
            raise ValueError("Unexpected GFS GRIB latitude orientation")
        values = np.asarray(ec.codes_get_values(gid), dtype=np.float32).reshape(361, 720)
        # Source grid: lon 0..359.5, lat +90..-90.
        # Crop lon -25..45, lat +72..+34; then average four surrounding
        # genuine 0.5-degree pixels onto the established CPC pixel centers.
        west = values[36:113, 670:720]
        east = values[36:113, 0:91]
        europe = np.concatenate((west, east), axis=1)
        if europe.shape != (77, 141) or not np.isfinite(europe).all():
            raise ValueError("Invalid Europe coverage or missing native GFS cells")
        shifted = (europe[:-1, :-1] + europe[:-1, 1:] +
                   europe[1:, :-1] + europe[1:, 1:]) * 0.25
        if shifted.shape != (HEIGHT, WIDTH) or not np.all((shifted > 170) & (shifted < 340)):
            raise ValueError("Impossible GFS 2m temperatures")
        return shifted - 273.15
    finally:
        ec.codes_release(gid)


def object_url(day: date, cycle: int, *, host: str) -> str:
    if cycle not in CYCLES:
        raise ValueError("Not a supported model initialization cycle")
    suffix = f"gfs.{day:%Y%m%d}/{cycle:02d}/atmos/gfs.t{cycle:02d}z.pgrb2.0p50.f003"
    if host == "s3":
        return "https://noaa-gfs-bdp-pds.s3.amazonaws.com/" + suffix
    if host == "nomads":
        return "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/" + suffix
    raise ValueError("Unsupported official GFS host")


def read_byte_range(day: date, cycle: int, *, host: str) -> tuple[bytes, str, str]:
    """Official GRIB index byte offsets for exactly the +3h 2m TMP forecast field.

    Avoid pulling 140 MB whole-world model files. Only request the ~260 KB
    GFS f003 temperature message using HTTP 206 Range support.
    """
    url = object_url(day, cycle, host=host)
    index_res = requests.get(url + ".idx", timeout=(15, 40),
                             headers={"User-Agent": "climate-dashboard-europe/1.0"})
    index_res.raise_for_status()
    parts = [line.split(":") for line in index_res.text.splitlines() if line.strip()]
    candidates = [i for i, p in enumerate(parts)
                  if len(p) >= 6 and p[2] == f"d={day:%Y%m%d}{cycle:02d}"
                  and p[3] == "TMP" and p[4] == "2 m above ground"
                  and p[5] == "3 hour fcst"]
    if len(candidates) != 1:
        raise ValueError("Official .idx has no unique 2m TMP f003 forecast")
    i = candidates[0]
    if i + 1 >= len(parts):
        raise ValueError("2m TMP GRIB message is last, range end unknown")
    first = int(parts[i][1])
    last = int(parts[i + 1][1]) - 1
    if not 0 <= first < last or not 20_000 <= last - first + 1 <= 2_000_000:
        raise ValueError("Invalid GFS 2m TMP range, refuse whole-model download")
    with requests.get(url, timeout=(20, 60),
                      headers={"Range": f"bytes={first}-{last}",
                               "User-Agent": "climate-dashboard-europe/1.0"},
                      stream=True) as r:
        if r.status_code != 206:
            raise ValueError(f"Server did not honor GRIB byte range: {r.status_code}")
        r.raise_for_status()
        expected = last - first + 1
        if int(r.headers.get("Content-Length", expected)) != expected:
            raise ValueError("GRIB range length mismatch")
        raw = r.content
    if len(raw) != expected or not raw.startswith(b"GRIB"):
        raise ValueError("Downloaded GRIB field failed byte-range verification")
    return raw, url, f"bytes={first}-{last}"


def read_analysis(day: date, cycle: int) -> tuple[np.ndarray, dict]:
    errors = []
    for host in ("s3", "nomads"):
        for attempt in range(2):
            try:
                raw, url, selected_range = read_byte_range(day, cycle, host=host)
                field = grib_2m_analysis(raw, day, cycle)
                return field, {
                    "cycle_utc": f"{cycle:02d}:00", "forecast_hour": 3,
                    "source_url": url, "byte_range": selected_range,
                    "sha256": sha256(raw).hexdigest(), "bytes": len(raw),
                }
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                errors.append(f"{host}: {exc}")
                if attempt == 0:
                    time.sleep(1)
    # The NOAA/NCEP web filter is the final source; it may return HTTP 500.
    url = analysis_url(day, cycle)
    try:
        resp = requests.get(url, timeout=(20, 75),
                            headers={"User-Agent": "climate-dashboard-europe/1.0"})
        resp.raise_for_status()
        field = grib_2m_analysis(resp.content, day, cycle)
        return field, {
            "cycle_utc": f"{cycle:02d}:00", "forecast_hour": 3,
            "source_url": url, "sha256": sha256(resp.content).hexdigest(),
            "bytes": len(resp.content),
        }
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        errors.append(f"nomads-filter: {exc}")
    raise RuntimeError(f"GFS f003 forecast {day} {cycle:02d} UTC unavailable: "
                       + "; ".join(errors))



def save_day(day: date) -> Path:
    fields, provenance = [], []
    for cycle in CYCLES:
        values, source = read_analysis(day, cycle)
        fields.append(values)
        provenance.append(source)
    stack = np.stack(fields)
    daily = stack.mean(axis=0)
    if np.count_nonzero(np.isfinite(daily)) < WIDTH * HEIGHT * 0.99:
        raise ValueError("Incomplete GFS f003 coverage")
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{day.isoformat()}.json"
    info = {
        "schema": 1, "day": day.isoformat(), "kind": "GFS 3-hour forecast f003",
        "source": "NOAA GFS forecast f003 0.5 degree (S3/NOMADS)",
        "metric": "mean(03,09,15,21 UTC) 2m temperature; 00/06/12/18 UTC runs +3h",
        "grid": "CPC aligned, GFS 0.5 degree quarter-cell interpolation",
        "cycles_utc": [0, 6, 12, 18],
        "sources": provenance,
        "temperature_c_q10_b64": encode_q10(daily),
    }
    path.write_text(json.dumps(info, separators=(",", ":")), encoding="utf-8")
    return path


def read_normals(path: Path) -> tuple[np.ndarray, dict] | None:
    if not path.exists():
        return None
    with np.load(path, allow_pickle=False) as data:
        normals = np.asarray(data["normal_t2m_c"], dtype=np.float32)
        count = np.asarray(data["year_count"], dtype=np.int16)
        metadata = json.loads(str(data["metadata_json"]))
    if normals.shape != (365, HEIGHT, WIDTH) or count.shape != normals.shape:
        raise ValueError("Invalid CFSR/CFSv2 reference dimensions")
    expected = {
        "source": "CFSR 1991-03/2011 + CFSv2 04/2011-2020 (T2M f003)",
        "first_year": 1991, "last_year": 2020,
        "forecast_hour":3, "reference_version":"cfsr-cfsv2-t2m-f003-v1",
        "years": 30, "sample_hours_utc": [3, 9, 15, 21],
        "grid": "CPC-aligned GFS 0.5 degree Europe",
        "reference": "1991-2020",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(f"CFSR normal f003 provenance invalid: {key}")
    if (int(count.min()) != 30 or not np.isfinite(normals).all()
        or metadata.get("source_months")!=360):
        raise ValueError("CFSR normals do not cover all 30 years")
    if not np.all((normals > -95) & (normals < 65)):
        raise ValueError("CFSR normals outside physical 2m bounds")
    return normals, metadata


def load_days(days: int = 110) -> list[tuple[date, np.ndarray]]:
    collection = []
    for path in sorted(RAW.glob("????-??-??.json"))[-days:]:
        obj = json.loads(path.read_text(encoding="utf-8"))
        d = date.fromisoformat(obj["day"])
        if (obj.get("schema") != 1 or obj.get("kind") != "GFS 3-hour forecast f003"
            or obj.get("cycles_utc") != [0, 6, 12, 18]
            or len(obj.get("sources", [])) != 4):
            raise ValueError(f"Unverified GFS sample: {path}")
        if any(item.get("forecast_hour") != 3 for item in obj["sources"]):
            raise ValueError("Wrong forecast lead in GFS f003 archive")
        collection.append((d, decode_q10(obj["temperature_c_q10_b64"], (HEIGHT, WIDTH))))
    return collection


def publish_index(archive: list[tuple[date, np.ndarray]], *,
                  normal: tuple[np.ndarray, dict] | None, out: Path) -> dict:
    if not archive:
        raise RuntimeError("No verified GFS f003 forecast days")
    dates = [d for d, _ in archive]
    if dates != sorted(set(dates)):
        raise ValueError("GFS days not sorted or duplicated")
    temps = np.stack([field for _, field in archive])
    payload = {
        "schema": 1,
        "provider": "NOAA NCEP GFS 0.5° forecast f003",
        "type": "model_forecast_not_observation",
        "metric": "Mean of four genuine +3h 2m forecasts valid at 03/09/15/21 UTC",
        "source": "https://www.nco.ncep.noaa.gov/pmb/products/gfs/",
        "data_through": dates[-1].isoformat(),
        "first_date": dates[0].isoformat(),
        "dates": [d.isoformat() for d in dates],
        "width": WIDTH, "height": HEIGHT, "lat_north": 71.75,
        "lat_south": 34.25, "lon_west": -24.75, "lon_east": 44.75,
        "grid_degrees": 0.5,
        "reference_ready": normal is not None,
        "reference": "CFSR 1991-03/2011 + CFSv2 04/2011-2020, f003, 1991–2020",
        "temperature_q10_b64": encode_q10(temps),
        "anomaly_q10_b64": None,
        "method": "Only verified GFS f003 runs, compared against CFSR/CFSv2 f003; 0.5 degree grid",
    }
    if normal is not None:
        climatology, meta = normal
        anomaly = np.stack([temp - normal_for_date(climatology, d)
                            for d, temp in archive])
        payload["anomaly_q10_b64"] = encode_q10(anomaly)
        payload["reference_metadata"] = meta
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-back", type=int, default=3)
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--today", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    args = ap.parse_args()
    if not 1 <= args.days_back <= 6:
        raise ValueError("NOMADS rotating archive supports only a short lookback")
    if not args.no_download:
        successes = 0
        for n in range(args.days_back, 0, -1):
            d = args.today - timedelta(days=n)
            try:
                path = save_day(d)
                print(f"NOAA GFS complete real f003 forecast: {path}", flush=True)
                successes += 1
            except RuntimeError as exc:
                print(f"Skipping incomplete GFS day: {exc}", flush=True)
        if successes == 0 and not RAW.exists():
            raise RuntimeError("No complete genuine GFS f003 forecast day available")
    days = load_days()
    ref = read_normals(BASELINE)
    result = publish_index(days, normal=ref, out=OUT / "index_f003.json")
    print(f"GFS f003 forecast available until {result['data_through']}; "
          f"{len(days)} genuine f003 daily forecasts; verified 1991–2020 reference={bool(ref)}",
          flush=True)


if __name__ == "__main__":
    main()
