#!/usr/bin/env python3
"""Compact station inventory for the dashboard's annual DWD observation viewer.

Derived from committed official DWD indices at Pages-build time. No interpolation
or synthetic observations. A capability is offered only if its backing file exists.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load(root: Path, filename: str) -> dict:
    path = root / filename
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) and data.get("ready") else {}


def build(root: Path) -> dict:
    stations: dict[str, dict] = {}
    sources = [
        ("temp", "station_climate_days_index.json"),
        ("precip", "station_precip_index.json"),
        ("snow", "station_snow_height_index.json"),
        ("snow", "station_snow_height_additional_index.json"),
    ]
    for kind, index_path in sources:
        for source in load(root, index_path).get("stations", []):
            sid = str(source.get("id", "")).zfill(5)
            if not sid.isdigit() or len(sid) != 5:
                continue
            if kind == "temp":
                filename = f"station_threshold_daily/{sid}.json"
                if not (root / filename).is_file():
                    continue
            elif kind == "precip":
                filename = source.get("file") or f"station_precip_climate/{sid}.json"
                if not (root / filename).is_file():
                    continue
            else:
                filename = source.get("year_file") or f"station_snow_height_years/{sid}.json"
                if not (root / filename).is_file():
                    continue
            entry = stations.setdefault(sid, {
                "id": sid, "name": str(source.get("name") or sid),
                "state": source.get("state") or "", "temp": False,
                "precip": False, "snow": False,
            })
            # Geographic selection for the new Phase 3 station record laboratory.
            # Coordinates originate in the same official DWD station indices.
            if entry.get("lat") is None or entry.get("lon") is None:
                try:
                    lat = float(source.get("lat", source.get("latitude")))
                    lon = float(source.get("lon", source.get("longitude")))
                    if 45 <= lat <= 57 and 4 <= lon <= 17:
                        entry["lat"], entry["lon"] = round(lat, 5), round(lon, 5)
                except (TypeError, ValueError):
                    pass
            entry[kind] = True
            entry[kind + "_file"] = str(filename)
            if kind == "snow":
                entry["snow_profile"] = source.get("file") or f"station_snow_height_profiles/{sid}.json"
                entry["snow_current"] = f"station_snow_height_current/{sid}.json"
            if not entry["name"] or entry["name"] == sid:
                entry["name"] = str(source.get("name") or sid)
            if not entry["state"]:
                entry["state"] = source.get("state") or ""
    rows = sorted(stations.values(), key=lambda s: (s["name"].casefold(), s["id"]))
    totals = {kind: sum(1 for s in rows if s[kind]) for kind in ("temp", "precip", "snow")}
    return {"schema": 1, "reference": "1991-2020",
            "source": "DWD CDC · bereits veröffentlichte Originaldatenarchive",
            "stations": rows, "totals": totals}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "_site/station_jahresanalyse_catalog.json"
    doc = build(root)
    if not doc["stations"] or doc["totals"]["temp"] < 50 or doc["totals"]["precip"] < 100:
        raise SystemExit("Stations-Jahresanalyse: zu wenige echte Archivdateien")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print("Stations-Jahresanalyse: ", len(doc["stations"]), "Stationen", doc["totals"])


if __name__ == "__main__":
    main()
