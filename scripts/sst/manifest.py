from __future__ import annotations

import copy
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from .config import ABSOLUTE_RANGE, ANOMALY_RANGE, ARCHIVE_START, REGIONS

VIEWS = ("absolute", "anomaly")


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _expected_output_count() -> int:
    return len(REGIONS) * len(VIEWS)


def empty_manifest() -> dict:
    return {
        "schema_version": 1,
        "archive_start": ARCHIVE_START.isoformat(),
        "data_through": None,
        "generated_at": _generated_at(),
        "source": {
            "sst": "MUR-JPL-L4-GLOB-v4.1",
            "reference": "NOAA OISST 1991-2020",
        },
        "scales": {
            "absolute": [float(ABSOLUTE_RANGE[0]), float(ABSOLUTE_RANGE[1])],
            "anomaly": [float(ANOMALY_RANGE[0]), float(ANOMALY_RANGE[1])],
        },
        "regions": {
            region_id: {
                "label": region.label,
                "bounds": [region.west, region.south, region.east, region.north],
                "width_px": region.width_px,
                "height_px": region.height_px,
            }
            for region_id, region in REGIONS.items()
        },
        "available_dates": [],
        "dates": {},
    }


def archive_relpath(day: date, region_id: str, view: str) -> str:
    if region_id not in REGIONS:
        raise ValueError(f"Unbekannte SST-Region: {region_id}")
    if view not in VIEWS:
        raise ValueError(f"Unbekannte SST-Ansicht: {view}")
    return f"{day:%Y/%m}/{region_id}/{view}/{day.isoformat()}.webp"


def _validate_outputs(outputs: dict) -> None:
    expected = _expected_output_count()
    if set(outputs) != set(REGIONS):
        raise ValueError(
            f"SST-Datum benötigt exakt {expected} URLs "
            f"({len(REGIONS)} Regionen × {len(VIEWS)} Ansichten)."
        )
    count = 0
    for region_id in REGIONS:
        region_outputs = outputs.get(region_id)
        if not isinstance(region_outputs, dict) or set(region_outputs) != set(VIEWS):
            raise ValueError(
                f"SST-Datum benötigt exakt {expected} URLs "
                f"({len(REGIONS)} Regionen × {len(VIEWS)} Ansichten)."
            )
        for view in VIEWS:
            url = region_outputs[view]
            if not isinstance(url, str) or not url.strip():
                raise ValueError(f"SST-Datum benötigt exakt {expected} nichtleere URLs.")
            count += 1
    if count != expected:
        raise ValueError(f"SST-Datum benötigt exakt {expected} URLs.")


def register_date(manifest: dict, day: date, outputs: dict, reference_method: str) -> dict:
    _validate_outputs(outputs)
    day_key = day.isoformat()
    manifest.setdefault("dates", {})[day_key] = {
        "reference_method": reference_method,
        "regions": copy.deepcopy(outputs),
    }
    available = sorted(set(manifest.get("available_dates", [])) | {day_key})
    manifest["available_dates"] = available
    manifest["data_through"] = available[-1]
    manifest["generated_at"] = _generated_at()
    return manifest


def read_manifest(path: Path) -> dict:
    if not path.exists():
        return empty_manifest()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError(f"Nicht unterstütztes SST-Manifest: {payload.get('schema_version')}")
    return payload


def write_manifest_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
