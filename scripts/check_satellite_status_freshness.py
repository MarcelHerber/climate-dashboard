#!/usr/bin/env python3
"""Independent, network-free check that the committed MTG status is actually fresh.

A green GitHub Action alone does not prove new satellite imagery exists: keep
monitor execution age and verified *source image* age separate.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path("data/satellite_wms_times.json")
IMPORTANT_PRODUCTS = ("geocolour", "dust", "ir105", "firetemperature")


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def diagnose(data, *, now=None, monitor_max_minutes=150, image_max_minutes=150):
    now = now or datetime.now(timezone.utc)
    failures, warnings = [], []
    report_time = timestamp(data.get("generated_at"))
    if not report_time:
        failures.append("Kein gültiger UTC-Zeitstempel des WMS-Monitors.")
    else:
        age = (now - report_time).total_seconds() / 60
        if age < -10:
            failures.append("WMS-Status liegt unerwartet in der Zukunft.")
        elif age > monitor_max_minutes:
            failures.append(f"MTG-Monitor seit {age:.0f} Minuten nicht aktualisiert (> {monitor_max_minutes}).")
    recent = []
    for name in IMPORTANT_PRODUCTS:
        product = data.get("products", {}).get(name, {})
        valid = timestamp(product.get("latest_verified_time"))
        if not product.get("map_ok") or not valid:
            warnings.append(f"{name}: kein bestätigtes WMS-PNG")
            continue
        age = (now - valid).total_seconds() / 60
        if 0 <= age <= image_max_minutes:
            recent.append(name)
        else:
            warnings.append(f"{name}: letzte bestätigte Aufnahme {age:.0f} Minuten alt")
    if not recent:
        failures.append(f"Kein aktuelles überprüftes MTG-Bild in den letzten {image_max_minutes} Minuten.")
    return {"healthy": not failures, "errors": failures, "warnings": warnings,
            "recent_products": recent,
            "generated_at": data.get("generated_at")}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--monitor-max-minutes", type=int, default=150)
    parser.add_argument("--image-max-minutes", type=int, default=150)
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.file.read_text(encoding="utf-8"))
        result = diagnose(data, monitor_max_minutes=args.monitor_max_minutes,
                          image_max_minutes=args.image_max_minutes)
    except (OSError, json.JSONDecodeError) as exc:
        result = {"healthy": False, "errors": [str(exc)], "warnings": [],
                  "recent_products": [], "generated_at": None}
    print("MTG source-monitor watchdog")
    print("Report:", result["generated_at"] or "missing")
    print("Recently verified:", ", ".join(result["recent_products"]) or "none")
    for warning in result["warnings"]:
        print("WARNING:", warning)
    for error in result["errors"]:
        print("ERROR:", error)
    return 0 if result["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
