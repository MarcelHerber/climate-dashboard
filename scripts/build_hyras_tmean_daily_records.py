#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from build_hyras_tmean_regions import (
    DAILY_BASE,
    EXPECTED_STATES,
    build_masks,
    daily_listing,
    download,
    extract_region_daily,
    grid_signature,
    latest_daily_files,
    load_states,
    prepare_da,
)

RECORD_FIRST_YEAR = 1951
RECORD_METHOD_VERSION = 1


def empty_records(region_names: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    return {name: {} for name in region_names}


def update_records(
    records: dict[str, dict[str, dict[str, Any]]],
    dates: list[str],
    values: dict[str, list[float | None]],
    year: int,
) -> None:
    for region, series in values.items():
        region_records = records.setdefault(region, {})
        for date, value in zip(dates, series):
            if value is None or not np.isfinite(value):
                continue

            v = round(float(value), 3)
            mmdd = date[5:10]
            rec = region_records.get(mmdd)

            if rec is None:
                region_records[mmdd] = {
                    "max": v,
                    "max_years": [int(year)],
                    "min": v,
                    "min_years": [int(year)],
                }
                continue

            old_max = float(rec["max"])
            old_min = float(rec["min"])

            if v > old_max:
                rec["max"] = v
                rec["max_years"] = [int(year)]
            elif v == old_max and int(year) not in rec.get("max_years", []):
                rec.setdefault("max_years", []).append(int(year))

            if v < old_min:
                rec["min"] = v
                rec["min_years"] = [int(year)]
            elif v == old_min and int(year) not in rec.get("min_years", []):
                rec.setdefault("min_years", []).append(int(year))


def load_reusable_records(
    path: Path,
    x: np.ndarray,
    y: np.ndarray,
    target_last_year: int,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if data.get("schema_version") != 1:
        return None
    if data.get("method_version") != RECORD_METHOD_VERSION:
        return None
    if data.get("first_year") != RECORD_FIRST_YEAR:
        return None
    if data.get("grid_signature") != grid_signature(x, y):
        return None
    if not all(name in data.get("regions", {}) for name in ["Deutschland", *EXPECTED_STATES]):
        return None

    last_year = int(data.get("last_year", 0) or 0)
    if last_year < RECORD_FIRST_YEAR - 1 or last_year > target_last_year:
        return None
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default="/tmp/hyras-data")
    ap.add_argument("--work", default="/tmp/hyras-tmean-work")
    ap.add_argument("--force-records", action="store_true")
    args = ap.parse_args()

    data_root = Path(args.data_root)
    work = Path(args.work)
    troot = data_root / "tmean"
    regions_dir = troot / "regions"
    regions_dir.mkdir(parents=True, exist_ok=True)

    tmean_index_path = troot / "index.json"
    region_index_path = regions_dir / "index.json"
    if not tmean_index_path.exists() or not region_index_path.exists():
        raise RuntimeError("Tmean- oder Regionen-Index fehlt.")

    tmean_index = json.loads(tmean_index_path.read_text(encoding="utf-8"))
    region_index = json.loads(region_index_path.read_text(encoding="utf-8"))

    current_year = int(tmean_index["year"])
    target_last_year = current_year - 1
    if target_last_year < RECORD_FIRST_YEAR:
        raise RuntimeError(f"Ungültiges Rekord-Endjahr: {target_last_year}")

    current_source = str(tmean_index["current_source_file"])
    current_nc = work / current_source
    if not current_nc.exists():
        download(f"{DAILY_BASE}/{current_source}", current_nc)

    with xr.open_dataset(current_nc, decode_times=True) as ds:
        _, _, _, _, x, y = prepare_da(ds)

    masks = build_masks(load_states(work), x, y)
    region_names = list(masks.keys())
    signature = grid_signature(x, y)

    records_path = regions_dir / "daily_records.json"
    existing = None if args.force_records else load_reusable_records(
        records_path, x, y, target_last_year
    )

    if existing is not None and int(existing.get("last_year", 0)) == target_last_year:
        print(
            f"Verwende vorhandene Tmean-Tagesrekorde "
            f"{existing['first_year']}–{existing['last_year']}.",
            flush=True,
        )
        records_payload = existing
    else:
        if existing is None:
            records = empty_records(region_names)
            start_year = RECORD_FIRST_YEAR
            print(
                f"Baue Tmean-Tagesrekorde {RECORD_FIRST_YEAR}–{target_last_year} "
                "einmalig neu …",
                flush=True,
            )
        else:
            records = existing["regions"]
            start_year = int(existing["last_year"]) + 1
            print(
                f"Erweitere Tmean-Tagesrekorde von {existing['last_year']} "
                f"bis {target_last_year} …",
                flush=True,
            )

        files = latest_daily_files(daily_listing())
        missing = [
            year for year in range(start_year, target_last_year + 1)
            if year not in files
        ]
        if missing:
            raise RuntimeError(
                "Für folgende HYRAS-Tmean-Jahre fehlen Tagesdateien: "
                + ", ".join(map(str, missing))
            )

        records_work = work / "regional_record_years"
        records_work.mkdir(parents=True, exist_ok=True)

        for year in range(start_year, target_last_year + 1):
            filename = files[year]
            target = records_work / filename
            if not target.exists():
                download(f"{DAILY_BASE}/{filename}", target)

            print(
                f"Historische Tmean-Tagesrekorde {year}: {filename}",
                flush=True,
            )
            with xr.open_dataset(target, decode_times=True) as ds:
                dates, values, _, _ = extract_region_daily(ds, masks, x, y)

            update_records(records, dates, values, year)
            target.unlink(missing_ok=True)

        records_payload = {
            "schema_version": 1,
            "method_version": RECORD_METHOD_VERSION,
            "parameter": "tmean",
            "unit": "°C",
            "first_year": RECORD_FIRST_YEAR,
            "last_year": target_last_year,
            "grid_signature": signature,
            "regions": records,
            "note": (
                "Historische tägliche absolute Maxima und Minima der "
                "HYRAS-Tmean-Gebietsmittel. Pro Kalendertag werden alle Jahre "
                f"{RECORD_FIRST_YEAR}–{target_last_year} verglichen; bei exakt "
                "gleichen Gebietsmitteln werden alle Rekordjahre gespeichert."
            ),
        }
        records_path.write_text(
            json.dumps(
                records_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    region_index["records_file"] = records_path.name
    region_index["records_first_year"] = int(records_payload["first_year"])
    region_index["records_last_year"] = int(records_payload["last_year"])
    region_index["records_note"] = records_payload["note"]
    region_index_path.write_text(
        json.dumps(region_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for name in region_names:
        count = len(records_payload["regions"].get(name, {}))
        if count < 365:
            raise RuntimeError(
                f"Zu wenige Rekord-Kalendertage für {name}: {count}"
            )

    print("Tmean-Tagesrekorde fertig.", flush=True)
    print(
        f"Historie: {records_payload['first_year']}–"
        f"{records_payload['last_year']}",
        flush=True,
    )
    print("Gebiete:", len(records_payload["regions"]), flush=True)
    print(
        "Kalendertage Deutschland:",
        len(records_payload["regions"]["Deutschland"]),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
