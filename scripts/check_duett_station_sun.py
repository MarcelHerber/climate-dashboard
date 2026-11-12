#!/usr/bin/env python3
"""Optional regional plausibility comparison: DUETT vs DWD KL SDK.

The second source is the existing dashboard's provisional station-interpolated
SDK area estimate (12 km IDW). This is a *comparison* only, not a second
addition to DUETT, and not an independent validation: DUETT itself includes
some station information. Missing reference data never blocks publication.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path


def compare(duett: dict, station: dict, *, warn_relative: float = .25, warn_hours: float = 10.) -> dict:
    cutoff = station.get("data_through")
    days = duett.get("dates", [])
    outcome = {
        "comparison": "DWD KL daily SDK, provisional 12 km three-nearest-IDW area estimate; NOT independent of DUETT stations",
        "station_count": station.get("sun_station_count", 0),
        "cutoff": cutoff,
        "evaluated": [],
        "warnings": [],
        "complete": False,
    }
    if not station.get("source", {}).get("sun") or station.get("month") != duett.get("month"):
        return outcome
    if cutoff not in days:
        return outcome
    n = days.index(cutoff)
    for region, data in duett.get("regions", {}).items():
        reference = station.get("areas", {}).get(region, {}).get("sun")
        if not isinstance(reference, (int, float)) or not math.isfinite(reference):
            continue
        duett_value = data.get("running", [])[n]
        if not isinstance(duett_value, (int, float)) or not math.isfinite(duett_value):
            continue
        diff = float(duett_value - reference)
        rel = abs(diff) / max(float(reference), 2.0)
        item = {
            "region": region, "duett_h": round(duett_value, 2),
            "stations_h": round(reference, 2),
            "difference_h": round(diff, 2),
            "difference_relative": round(rel, 3),
        }
        outcome["evaluated"].append(item)
        if abs(diff) >= warn_hours and rel >= warn_relative:
            outcome["warnings"].append(item)
    outcome["complete"] = bool(outcome["evaluated"])
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--stations", type=Path, required=True)
    args = parser.parse_args()
    doc = json.loads(args.observed.read_text(encoding="utf-8"))
    if args.stations.is_file() and args.stations.stat().st_size:
        stations = json.loads(args.stations.read_text(encoding="utf-8"))
        doc["station_quality"] = compare(doc, stations)
        args.observed.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        check = doc["station_quality"]
        print("DUETT vs station SDK:", len(check["evaluated"]), "regions",
              len(check["warnings"]), "notable differences", "reference cutoff", check["cutoff"])
    else:
        print("No station-based sunshine estimate available; DUETT observations retained without a second summation.")


if __name__ == "__main__":
    main()
