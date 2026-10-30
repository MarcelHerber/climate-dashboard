#!/usr/bin/env python3
"""Verified ECMWF IFS ENS 60°N / 10 hPa zonal U-wind (50 perturbations + control).

Operational open data after IFS 50r1: stream=enfo/type=ef has 50 perturbations,
while the control is stream=oper/type=fc. Never treat lagged IFS runs as EPS.
Only publish complete original forecasts; missing members are never imputed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import tempfile

import numpy as np

LOG = logging.getLogger("ecmwf-ens-u60")
STEPS = list(range(0, 361, 24))
MEMBERS = ["c00"] + [f"p{i:02d}" for i in range(1, 51)]
EXPECTED_LONS = 1440
MAX_AGE_HOURS = 72
MAX_ARCHIVE_AGE_HOURS = 168


def mean_u60(lat, lon, wind):
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    wind = np.asarray(wind, dtype=np.float64)
    if not (lat.shape == lon.shape == wind.shape):
        raise ValueError("Unequal ECMWF latitude/longitude/U shapes")
    ring = np.isclose(lat, 60.0, atol=0.002)
    longitudes = np.mod(lon[ring], 360.0)
    samples = wind[ring]
    if len(samples) != EXPECTED_LONS or len(np.unique(np.rint(longitudes * 4).astype(int))) != EXPECTED_LONS:
        raise ValueError("Missing or duplicated longitudes on 60N/0.25 degree circle")
    if not np.isfinite(samples).all() or np.any((samples <= -160) | (samples >= 170)):
        raise ValueError("Invalid ECMWF U wind values on 60N")
    return round(float(np.mean(samples, dtype=np.float64)), 3)


def decode_step(path, cycle, lead, perturbed):
    """Decode a single step's GRIB messages, rejecting duplicates and missing members."""
    import eccodes
    found = {}
    with path.open("rb") as file:
        while True:
            handle = eccodes.codes_grib_new_from_file(file)
            if handle is None:
                break
            try:
                if str(eccodes.codes_get(handle, "shortName")).lower() != "u":
                    raise ValueError("Unexpected field: not U wind")
                if str(eccodes.codes_get(handle, "typeOfLevel")) != "isobaricInhPa" or int(eccodes.codes_get(handle, "level")) != 10:
                    raise ValueError("Unexpected ECMWF pressure level")
                if int(eccodes.codes_get(handle, "dataDate")) != int(cycle.strftime("%Y%m%d")) or int(eccodes.codes_get(handle, "dataTime")) != cycle.hour * 100:
                    raise ValueError("Unexpected ECMWF initialization")
                if int(eccodes.codes_get(handle, "endStep")) != lead:
                    raise ValueError("Unexpected ECMWF lead hour")
                number = int(eccodes.codes_get(handle, "number")) if perturbed else 0
                if number not in (range(1, 51) if perturbed else (0,)):
                    raise ValueError(f"Unexpected perturbation {number}")
                key = f"p{number:02d}" if perturbed else "c00"
                if key in found:
                    raise ValueError(f"Duplicate ECMWF member {key}")
                vals = np.asarray(eccodes.codes_get_values(handle), dtype=np.float64)
                lat = eccodes.codes_get_array(handle, "latitudes")
                lon = eccodes.codes_get_array(handle, "longitudes")
                found[key] = mean_u60(lat, lon, vals)
            finally:
                eccodes.codes_release(handle)
    expected = set(MEMBERS[1:]) if perturbed else {"c00"}
    if set(found) != expected:
        raise ValueError(f"Incomplete ECMWF {'ensemble' if perturbed else 'control'} at +{lead}h: {len(found)}/{len(expected)}")
    return found


def validate(payload, now=None, max_age_hours=MAX_AGE_HOURS):
    now = now or datetime.now(timezone.utc)
    try:
        if payload.get("schema_version") != 1 or payload.get("provider") != "ECMWF IFS ENS":
            return False
        if payload.get("level_hpa") != 10 or payload.get("latitude_deg") != 60 or payload.get("units") != "m/s":
            return False
        if payload.get("forecast_step_hours") != STEPS or payload.get("member_count") != 51 or payload.get("perturbed_count") != 50:
            return False
        cycle = datetime.fromisoformat(payload["cycle_utc"].replace("Z", "+00:00"))
        age = now - cycle
        if cycle.hour not in (0, 12) or cycle.minute != 0 or cycle.tzinfo is None or payload.get("valid_hour_utc") != cycle.hour or not timedelta(0) <= age <= timedelta(hours=max_age_hours):
            return False
        expected_dates = [(cycle + timedelta(hours=h)).strftime("%Y-%m-%d") for h in STEPS]
        if payload.get("valid_dates") != expected_dates:
            return False
        members = payload.get("members", {})
        if set(members) != set(MEMBERS):
            return False
        return all(isinstance(values, list) and len(values) == len(STEPS) and
                   all(isinstance(v, (float, int)) and np.isfinite(v) and -160 < v < 170 for v in values)
                   for values in members.values())
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def request(client, cycle, lead, target, perturbed):
    options = dict(date=cycle.strftime("%Y%m%d"), time=cycle.hour, stream="enfo" if perturbed else "oper",
                   type="ef" if perturbed else "fc", levtype="pl", levelist=10,
                   param="u", step=lead, target=str(target))
    if perturbed:
        options["number"] = list(range(1, 51))
    client.retrieve(**options)


def build(output, now=None):
    from ecmwf.opendata import Client
    now = now or datetime.now(timezone.utc)
    # All full-horizon IFS ENS runs: 00 and 12 UTC (06/18 reach only +144h).
    # Allow processing time for complete 360h data on the public server.
    ready = now - timedelta(hours=8)
    cycle = ready.replace(hour=12 if ready.hour>=12 else 0,
                          minute=0,second=0,microsecond=0)
    if output.exists():
        try:
            old=json.loads(output.read_text(encoding="utf-8"))
            if old.get("cycle_utc", "")>cycle.strftime("%Y-%m-%dT%H:00:00Z"):
                raise RuntimeError("Never overwrite a newer published ECMWF ENS run")
        except (OSError,ValueError): pass
    if output.is_file():
        try:
            previous=json.loads(output.read_text(encoding="utf-8"))
            if (previous.get("cycle_utc")==cycle.strftime("%Y-%m-%dT%H:00:00Z")
                    and validate(previous,now)
                    and (output.parent/"ens_index.json").is_file()):
                LOG.info("Already published complete ECMWF ENS %s; skipping duplicate downloads",previous["cycle_utc"])
                return previous
        except (OSError,ValueError): pass
    client = Client(source="ecmwf", model="ifs", resol="0p25")
    members = {key: [] for key in MEMBERS}
    with tempfile.TemporaryDirectory(prefix="ecmwf-ens-") as td:
        temp = Path(td)
        for lead in STEPS:
            for perturbed in (False, True):
                target = temp / ("ens" if perturbed else "control")
                target = target.with_suffix(".grib2")
                request(client, cycle, lead, target, perturbed)
                if not target.exists() or target.stat().st_size < 10000:
                    raise RuntimeError(f"No original ECMWF GRIB for +{lead}h")
                row = decode_step(target, cycle, lead, perturbed)
                for key, value in row.items():
                    members[key].append(value)
                target.unlink()
            LOG.info("Decoded 10 hPa, 60N: +%03d h, all 51 members", lead)
    payload = dict(
        schema_version=1, provider="ECMWF IFS ENS", model="ifs", stream_ensemble="enfo/ef",
        stream_control="oper/fc", resolution_degrees=0.25, parameter="u",
        level_hpa=10, latitude_deg=60, units="m/s",
        statistic="signed zonal average of the complete 1440-longitude 60N ring",
        cycle_utc=cycle.strftime("%Y-%m-%dT%H:00:00Z"),
        generated_utc=now.isoformat(), forecast_step_hours=STEPS,
        forecast_horizon_days=15, valid_hour_utc=cycle.hour,
        valid_dates=[(cycle + timedelta(hours=lead)).strftime("%Y-%m-%d") for lead in STEPS],
        member_count=51, perturbed_count=50, members=members,
        probability_denominator=51, license="CC BY 4.0",
        source="ECMWF IFS Open Data, https://www.ecmwf.int/en/forecasts/datasets/open-data"
    )
    if not validate(payload, now):
        raise ValueError("Refusing incomplete, stale or invalid IFS ENS product")
    output.parent.mkdir(parents=True, exist_ok=True)
    archive = output.parent / "runs"
    archive.mkdir(parents=True, exist_ok=True)
    previous = None
    if output.is_file():
        try: previous=json.loads(output.read_text(encoding="utf-8"))
        except (OSError,ValueError): pass
    def archive_run(run):
        if not run or not validate(run,now,max_age_hours=MAX_ARCHIVE_AGE_HOURS) or run.get("cycle_utc")>payload["cycle_utc"]:
            return
        stamp=run["cycle_utc"].replace("-","").replace(":","").replace("T","_").replace("Z","")
        file=archive/(stamp+".json")
        file.write_text(json.dumps(run,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n",encoding="utf-8")
    archive_run(previous)
    archive_run(payload)
    stage=output.with_suffix(".tmp")
    stage.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n",encoding="utf-8")
    stage.replace(output)
    records=[]
    for file in archive.glob("*.json"):
        try:
            run=json.loads(file.read_text(encoding="utf-8"))
            if validate(run,now,max_age_hours=MAX_ARCHIVE_AGE_HOURS):
                records.append({"cycle_utc":run["cycle_utc"],"path":"runs/"+file.name,
                                "forecast_horizon_days":run["forecast_horizon_days"]})
            else:
                LOG.warning("Removing incomplete/stale ECMWF archived run %s",file.name)
                file.unlink(missing_ok=True)
        except (ValueError,OSError,KeyError):
            LOG.warning("Removing unreadable ECMWF archived run %s",file.name)
            file.unlink(missing_ok=True)
    records.sort(key=lambda row:row["cycle_utc"],reverse=True)
    for item in records[10:]:
        (archive/Path(item["path"]).name).unlink(missing_ok=True)
    index={"schema_version":1,"provider":"ECMWF IFS ENS",
           "latest_cycle_utc":records[0]["cycle_utc"],"runs":records[:10]}
    (output.parent/"ens_index.json").write_text(json.dumps(index,separators=(",",":"))+"\n",encoding="utf-8")
    LOG.info("Validated EPS %s, 50+1 real members x %s dates", payload["cycle_utc"], len(STEPS))
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/stratosphere/ecmwf/ens_current.json"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build(args.output)


if __name__ == "__main__":
    main()
