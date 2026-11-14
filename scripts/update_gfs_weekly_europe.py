#!/usr/bin/env python3
"""Seven-day Europe GFS 2m-temperature *forecast* anomaly on genuine NOAA 0.5° fields.

Scientific difference to the historical Haustein map is intentional:
- current single-run GFS forecasts every 6 h, lead +3 to +165 inclusive
- genuine CFSR/CFSv2 f003 1991–2020 normal (Haustein uses 1981–2010)
- no f000 substitutions; no artificial extrapolation; no interpolated hours
- subtract correct *valid-date* daily normal before averaging all 28 fields
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time

import numpy as np
import requests

from scripts import update_gfs_f003_europe as daily

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "gfs_analysis_europe" / "weekly_f003.json"
LEADS = tuple(range(3, 166, 6))
assert len(LEADS) == 28 and LEADS[0] == 3 and LEADS[-1] == 165
USER_AGENT = {"User-Agent": "climate-dashboard-GFS-weekly/1.0"}
HOSTS = ("s3", "nomads")


def source_url(run: datetime, lead: int, host: str) -> str:
    if run.tzinfo is None or run.utcoffset() != timedelta(0):
        raise ValueError("Run must have UTC timezone")
    if run.hour not in (0, 6, 12, 18) or run.minute or run.second:
        raise ValueError("Run must be initialised at 00/06/12/18 UTC")
    if lead not in LEADS:
        raise ValueError("Only genuine 6-hour sequence f003..f165 accepted")
    suffix = (f"gfs.{run:%Y%m%d}/{run:%H}/atmos/"
              f"gfs.t{run:%H}z.pgrb2.0p50.f{lead:03d}")
    if host == "s3":
        return "https://noaa-gfs-bdp-pds.s3.amazonaws.com/" + suffix
    if host == "nomads":
        return "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/" + suffix
    raise ValueError("Unsupported official GFS source host")


def field_range(idx: str, run: datetime, lead: int) -> tuple[int, int]:
    """Extract exactly the instant TMP 2m field from the official wgrib2 .idx."""
    records = [line.split(":") for line in idx.splitlines() if line.strip()]
    target = f"d={run:%Y%m%d%H}"
    requested = f"{lead} hour fcst"
    candidates = [
        i for i, fields in enumerate(records)
        if len(fields) >= 6 and fields[2] == target
        and fields[3] == "TMP" and fields[4] == "2 m above ground"
        and fields[5].strip().lower() == requested
    ]
    if len(candidates) != 1 or candidates[0] + 1 >= len(records):
        raise ValueError(f"No unique 2m TMP f{lead:03d} field in official index")
    i = candidates[0]
    first, last = int(records[i][1]), int(records[i + 1][1]) - 1
    if not 0 <= first < last or not 20_000 <= last - first + 1 <= 2_000_000:
        raise ValueError("Unsafe or unexpected GFS TMP2m byte range")
    return first, last


def decode_grib(raw: bytes, run: datetime, lead: int) -> np.ndarray:
    import eccodes as ec

    if len(raw) < 20_000 or not raw.startswith(b"GRIB"):
        raise ValueError("GFS field is missing or not GRIB2")
    with tempfile.TemporaryFile(mode="w+b") as f:
        f.write(raw)
        f.seek(0)
        gid = ec.codes_grib_new_from_file(f)
        if gid is None:
            raise ValueError("GFS field is empty")
        try:
            def get(name):
                return ec.codes_get(gid, name)
            valid = run + timedelta(hours=lead)
            if (int(get("edition")) != 2
                or int(get("discipline")) != 0
                or int(get("parameterCategory")) != 0
                or int(get("parameterNumber")) != 0
                or str(get("typeOfLevel")) != "heightAboveGround"
                or int(get("level")) != 2
                or int(get("forecastTime")) != lead
                or str(get("stepRange")) not in (str(lead), f"{lead}-{lead}")
                or int(get("dataDate")) != int(run.strftime("%Y%m%d"))
                or int(get("dataTime")) != run.hour * 100
                or int(get("validityDate")) != int(valid.strftime("%Y%m%d"))
                or int(get("validityTime")) != valid.hour * 100
                or (int(get("Ni")), int(get("Nj"))) != (720, 361)
                or abs(float(get("latitudeOfFirstGridPointInDegrees"))-90)>0.01):
                raise ValueError(f"GFS f{lead:03d} GRIB field provenance/time mismatch")
            values = np.asarray(ec.codes_get_values(gid), dtype=np.float32).reshape(361, 720)
            west, east = values[36:113, 670:720], values[36:113, :91]
            europe = np.concatenate((west, east), axis=1)
            if europe.shape != (77, 141) or not np.isfinite(europe).all():
                raise ValueError("GFS 0.5 degree native Europe coverage invalid")
            shifted = (europe[:-1, :-1] + europe[:-1, 1:] +
                       europe[1:, :-1] + europe[1:, 1:]) * np.float32(.25)
            if shifted.shape != (76, 140) or not np.all((shifted > 170) & (shifted < 340)):
                raise ValueError("Impossible GFS f003..f165 2m temperatures")
            return shifted.astype(np.float32) - np.float32(273.15)
        finally:
            ec.codes_release(gid)


def fetch_field(run: datetime, lead: int) -> tuple[np.ndarray, dict]:
    errors = []
    for host in HOSTS:
        url = source_url(run, lead, host)
        for attempt in range(2):
            try:
                idx = requests.get(url + ".idx", headers=USER_AGENT, timeout=(15, 45))
                idx.raise_for_status()
                first, last = field_range(idx.text, run, lead)
                with requests.get(
                    url, headers={**USER_AGENT, "Range": f"bytes={first}-{last}"},
                    timeout=(20, 70), stream=True
                ) as res:
                    if res.status_code != 206:
                        raise ValueError(f"Official GRIB Range not honored: {res.status_code}")
                    res.raise_for_status()
                    raw = res.content
                if len(raw) != last-first+1:
                    raise ValueError("Truncated GFS GRIB2 byte range")
                grid = decode_grib(raw, run, lead)
                valid = run + timedelta(hours=lead)
                return grid, {
                    "forecast_hour": lead,
                    "valid_utc": valid.isoformat().replace("+00:00", "Z"),
                    "source_url": url,
                    "byte_range": f"bytes={first}-{last}",
                    "sha256": sha256(raw).hexdigest(),
                    "bytes": len(raw)
                }
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"{host}/attempt{attempt+1}: {exc}")
                if attempt == 0:
                    time.sleep(1)
    raise RuntimeError(f"GFS f{lead:03d} not verified: " + " | ".join(errors[-4:]))


def run_candidates(now: datetime, *, cycle: int | None = None, day: date | None = None) -> list[datetime]:
    if now.tzinfo is None:
        raise ValueError("Current time must be timezone aware")
    if day is not None or cycle is not None:
        if day is None or cycle not in (0, 6, 12, 18):
            raise ValueError("Explicit run requires date and 00/06/12/18 cycle")
        return [datetime(day.year, day.month, day.day, cycle, tzinfo=timezone.utc)]
    t = (now.astimezone(timezone.utc)-timedelta(hours=5)).replace(minute=0, second=0, microsecond=0)
    t = t.replace(hour=(t.hour // 6)*6)
    return [t-timedelta(hours=6*i) for i in range(3)]


def calculate(run: datetime, source: list[np.ndarray],
              reference: np.ndarray) -> dict:
    if len(source) != len(LEADS) or reference.shape != (365,76,140):
        raise ValueError("Need 28 actual forecast fields and 30-year gridded normals")
    if any(item.shape != (76,140) or not np.isfinite(item).all() for item in source):
        raise ValueError("Invalid forecast dimensions, no missing fields accepted")
    # Four 6-hourly samples per day, valid times 03/09/15/21 UTC for 00z;
    # data from other model cycles likewise cover 7 consecutive 24-hour blocks.
    valid_times = [run + timedelta(hours=step) for step in LEADS]
    anomalies = [
        field - daily.normal_for_date(reference, valid.date())
        for field,valid in zip(source,valid_times)
    ]
    forecast_mean = np.mean(np.stack(source), axis=0, dtype=np.float64).astype(np.float32)
    anomaly_mean = np.mean(np.stack(anomalies), axis=0, dtype=np.float64).astype(np.float32)
    return {
        "schema":1,
        "type":"model_forecast_7day_not_observation",
        "provider":"NOAA NCEP GFS 0.5° short-to-medium-range forecast",
        "run_utc":run.isoformat().replace("+00:00","Z"),
        "valid_from_utc":valid_times[0].isoformat().replace("+00:00","Z"),
        "valid_to_utc":valid_times[-1].isoformat().replace("+00:00","Z"),
        "lead_hours":list(LEADS), "sample_count":28, "period_days":7,
        "grid_degrees":0.5,"width":140,"height":76,
        "lat_north":71.75,"lat_south":34.25,"lon_west":-24.75,"lon_east":44.75,
        "reference":"CFSR 1991-03/2011 + CFSv2 04/2011-2020; f003; 1991–2020",
        "reference_version":"cfsr-cfsv2-t2m-f003-v1",
        "forecast_mean_q10_b64":daily.encode_q10(forecast_mean),
        "anomaly_mean_q10_b64":daily.encode_q10(anomaly_mean),
        "method":"One run; 28 genuine NOAA GFS 0.5° TMP2m f003–f165 every 6 h; "
                 "subtract matching valid-date 30-year CFSR/CFSv2 f003 daily normal before averaging. "
                 "Independent of Haustein's 1981–2010 reference and polar map projection."
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-date", type=date.fromisoformat)
    ap.add_argument("--cycle", type=int)
    ap.add_argument("--output", type=Path, default=DEST)
    opts = ap.parse_args()
    normal = daily.read_normals(daily.BASELINE)
    if normal is None:
        raise RuntimeError("Verified 1991–2020 CFSR/CFSv2 f003 climatology missing")
    baseline,metadata = normal
    if (metadata.get("forecast_hour")!=3 or metadata.get("source_months")!=360
        or metadata.get("years")!=30):
        raise RuntimeError("Wrong or incomplete historical CFS reference")
    failures=[]
    for run in run_candidates(datetime.now(timezone.utc),cycle=opts.cycle,day=opts.run_date):
        try:
            samples, origins = [], []
            for lead in LEADS:
                field, details = fetch_field(run, lead)
                samples.append(field)
                origins.append(details)
                print(f"Verified GFS {run:%Y%m%d} {run:%HZ} f{lead:03d}",flush=True)
            payload = calculate(run,samples,baseline)
            payload["sources"] = origins
            payload["reference_metadata"] = {
                "source": metadata["source"],
                "reference_version":metadata["reference_version"],
                "first_year":metadata["first_year"],
                "last_year":metadata["last_year"],
                "years":metadata["years"],
                "forecast_hour":metadata["forecast_hour"],
                "source_months":metadata["source_months"],
            }
            opts.output.parent.mkdir(parents=True,exist_ok=True)
            opts.output.write_text(json.dumps(payload,separators=(",",":"),ensure_ascii=False),encoding="utf-8")
            print(f"GFS genuine 7-day f003..165 forecast and 1991–2020 anomaly: "
                  f"{opts.output} run={payload['run_utc']} 28 verified fields",flush=True)
            return
        except (RuntimeError,ValueError) as exc:
            failures.append(f"{run.isoformat()}: {exc}")
            print(f"Candidate GFS run not complete: {failures[-1]}",flush=True)
    raise RuntimeError("No fully verified NOAA GFS 7-day forecast run: "+" | ".join(failures))


if __name__ == "__main__":
    main()
