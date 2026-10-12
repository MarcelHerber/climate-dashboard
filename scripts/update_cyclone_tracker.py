#!/usr/bin/env python3
"""ECMWF Open Data tropical-cyclone model track ingestion.

The operational/ensemble BUFR type=tf product gives positions, MSLP and 10 m
maximum wind. It does NOT contain Hart cyclone phase-space diagnostics (B,
-V_T^L, -V_T^U); no thermal-core class is inferred from these data.

Designed for unattended GitHub Actions. On a request error retain existing
valid files and publish transparent model-status metadata.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import os
from pathlib import Path
import tempfile

from ecmwf.opendata import Client
from eccodes import (
    CODES_MISSING_DOUBLE,
    CODES_MISSING_LONG,
    CodesInternalError,
    codes_bufr_new_from_file,
    codes_get,
    codes_get_array,
    codes_release,
    codes_set,
)

UTC = dt.timezone.utc
MODELS = (
    {"id": "ifs", "label": "ECMWF IFS", "model": None,
     "stream": "oper", "step": 360, "type": "tf"},
    {"id": "aifs", "label": "ECMWF AIFS", "model": "aifs-single",
     "stream": "oper", "step": 360, "type": "tf"},
    {"id": "ens", "label": "ECMWF IFS ENS", "model": None,
     "stream": "enfo", "step": 360, "type": "tf"},
)
MISSING_LIMIT = 1e30


def safe_arr(handle, key: str):
    try:
        value = codes_get_array(handle, key)
        return list(value)
    except (CodesInternalError, ValueError, KeyError):
        try:
            return [codes_get(handle, key)]
        except (CodesInternalError, ValueError, KeyError):
            return []


def pick(arr, i: int, total: int):
    if not arr:
        return None
    if len(arr) == 1:
        return arr[0]
    if i < len(arr):
        return arr[i]
    return None


def finite(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and abs(v) < MISSING_LIMIT and v not in (CODES_MISSING_DOUBLE, CODES_MISSING_LONG) else None


def get_field(handle, name, rank: int, i: int, count: int):
    return finite(pick(safe_arr(handle, f"#{rank}#{name}"), i, count))


def forecast_hours(handle, rank):
    arr = safe_arr(handle, f"#{rank}#timePeriod")
    for x in arr:
        value = finite(x)
        if value is not None and value >= 0 and value <= 400:
            return int(value)
    return None


def build_position(lat, lon, pressure, wind, step, start):
    if lat is None or lon is None or not (-90 <= lat <= 90):
        return None
    lon = (lon + 180) % 360 - 180
    if pressure is not None:
        if 80000 <= pressure <= 110000:
            pressure /= 100
        if not 800 <= pressure <= 1100:
            pressure = None
    if wind is not None and not 0 <= wind <= 150:
        wind = None
    return {
        "h": step,
        "time": (start + dt.timedelta(hours=step)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lat": round(lat, 3), "lon": round(lon, 3),
        "mslp_hpa": round(pressure, 1) if pressure is not None else None,
        "vmax_ms": round(wind, 1) if wind is not None else None,
        "cps": None,
    }


def decode_bufr(filename: Path, model: dict) -> list[dict]:
    tracks = []
    with filename.open("rb") as handle:
        while True:
            message = codes_bufr_new_from_file(handle)
            if message is None:
                break
            try:
                codes_set(message, "unpack", 1)
                start = dt.datetime(
                    int(codes_get(message, "year")), int(codes_get(message, "month")),
                    int(codes_get(message, "day")), int(codes_get(message, "hour")),
                    tzinfo=UTC,
                )
                identifier = str(codes_get(message, "stormIdentifier") or "").strip()
                try:
                    name = str(codes_get(message, "stormName") or "").strip()
                except (CodesInternalError, ValueError):
                    name = ""
                if not identifier:
                    identifier = f"system-{len(tracks)+1}"
                members = safe_arr(message, "ensembleMemberNumber")
                # A deterministic product may contain no explicit member number.
                if not members:
                    members = [0]
                # ECMWF local BUFR repeated fields: initial track position rank 2,
                # wind rank 3; forecast ranks 4/5, 6/7, ... (see ECMWF examples).
                steps = [0]
                for r in range(1, 100):
                    h = forecast_hours(message, r)
                    if h is None:
                        break
                    if h not in steps:
                        steps.append(h)
                if len(steps) == 1:
                    logging.warning("No forecast periods for %s (%s)", identifier, model["id"])
                    continue
                for i, member in enumerate(members):
                    coords = []
                    for j, lead in enumerate(steps):
                        position_rank = 2 if j == 0 else 2 * j + 2
                        wind_rank = 3 if j == 0 else 2 * j + 3
                        pressure_rank = 1 if j == 0 else j + 1
                        lat = get_field(message, "latitude", position_rank, i, len(members))
                        lon = get_field(message, "longitude", position_rank, i, len(members))
                        pressure = get_field(message, "pressureReducedToMeanSeaLevel", pressure_rank, i, len(members))
                        wind = get_field(message, "windSpeedAt10M", j + 1, i, len(members))
                        point = build_position(lat, lon, pressure, wind, lead, start)
                        if point:
                            coords.append(point)
                    if len(coords) < 2:
                        continue
                    try:
                        member_id = int(member)
                    except (TypeError, ValueError):
                        member_id = 0
                    tracks.append({
                        "id": f"{model['id']}-{identifier}-{member_id}",
                        "model": model["id"], "storm_id": identifier,
                        "name": name if name and name.lower() not in ("missing", "none") else identifier,
                        "member": member_id, "is_ensemble": model["id"] == "ens",
                        "run": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "points": sorted(coords, key=lambda p: p["h"]),
                    })
            except Exception as exc:
                logging.warning("One BUFR message skipped: %s", exc)
            finally:
                codes_release(message)
    # Dedup if a name appears twice in the same message stream.
    out = {}
    for t in tracks:
        if t["id"] not in out or len(t["points"]) > len(out[t["id"]]["points"]):
            out[t["id"]] = t
    # ECMWF's "pre-existing" and "genesis" categories may encode the
    # same model trajectory with different storm identifiers (e.g. 34W/70W).
    # Keep one exact trajectory per member while preserving distinct tracks.
    unique = {}
    for track in out.values():
        signature = (
            track["member"],
            tuple((p["h"], p["lat"], p["lon"], p["mslp_hpa"]) for p in track["points"]),
        )
        prior = unique.get(signature)
        if prior is None:
            unique[signature] = track
        else:
            # Prefer an established identifier over a numbered genesis ID.
            def preferred(t):
                try:
                    return int(t["storm_id"][:2]) < 70
                except (ValueError, TypeError):
                    return False
            if preferred(track) and not preferred(prior):
                unique[signature] = track
    return list(unique.values())


def candidate_runs(now: dt.datetime):
    today = now.date()
    runs = []
    for days_back in range(0, 4):
        date = today - dt.timedelta(days=days_back)
        for hour in (12, 0):
            stamp = dt.datetime.combine(date, dt.time(hour), tzinfo=UTC)
            if stamp <= now - dt.timedelta(hours=3):
                runs.append(stamp)
    return runs


def load_model(model, now):
    client = Client(source="ecmwf", model=model["model"]) if model["model"] else Client(source="ecmwf")
    failures = []
    for run in candidate_runs(now):
        with tempfile.TemporaryDirectory(prefix="cps-") as temp:
            target = Path(temp) / "tracks.bufr"
            kwargs = dict(date=run.strftime("%Y-%m-%d"), time=run.hour,
                          stream=model["stream"], type=model["type"], step=model["step"],
                          target=str(target))
            try:
                client.retrieve(**kwargs)
                if not target.exists() or target.stat().st_size < 80:
                    raise ValueError("BUFR empty")
                records = decode_bufr(target, model)
                # A valid BUFR may contain no cyclones, which is not an error.
                return {
                    "model": model["id"], "run": run.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": "ok" if records else "no_storms",
                    "tracks": records, "error": None,
                }
            except Exception as exc:
                failures.append(f"{run:%Y%m%d%H}: {str(exc)[:140]}")
                logging.warning("%s %s failed: %s", model["id"], run, exc)
    return {"model": model["id"], "run": None, "status": "unavailable",
            "tracks": [], "error": "No usable ECMWF BUFR file in last 4 days: " + "; ".join(failures[-2:])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("data/cyclone-tracker"))
    args = parser.parse_args()
    now = dt.datetime.now(UTC)
    args.out.mkdir(parents=True, exist_ok=True)
    models, tracks = [], []
    previous = args.out / "tracks.json"
    old_data = None
    if previous.exists():
        try:
            old_data = json.loads(previous.read_text(encoding="utf-8"))
        except Exception:
            old_data = None
    for model in MODELS:
        result = load_model(model, now)
        models.append({key: result[key] for key in ("model", "run", "status", "error")})
        tracks.extend(result["tracks"])
    live_runs = sum(m["status"] in ("ok", "no_storms") for m in models)
    # Do not overwrite a successfully collected dataset on a global outage.
    if not live_runs and old_data and old_data.get("models"):
        old_data["refresh_attempt_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        old_data["refresh_errors"] = models
        previous.write_text(json.dumps(old_data, ensure_ascii=False, separators=(",", ":")) + "\n")
        logging.warning("No fresh models; keeping prior tracks explicitly tagged as stale")
        return
    payload = {
        "schema": 1, "updated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "ECMWF Open Data BUFR type=tf",
        "cps_available": False,
        "cps_note": "BUFR tracks alone do not supply Hart CPS (B, -VT lower, -VT upper).",
        "models": models, "tracks": tracks,
    }
    previous.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"updated": payload["updated_utc"],
                      "status": models, "tracks": len(tracks)}, ensure_ascii=False))
    if not live_runs:
        raise SystemExit("No usable model feeds yet; re-try later")


if __name__ == "__main__":
    main()
