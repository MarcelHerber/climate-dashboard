#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import xarray as xr

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_hyras_tmean_regions as tmean
import build_hyras_tmax_regions as tmax
import build_hyras_tmin_regions as tmin

MODULES = {
    "tmean": tmean,
    "tmax": tmax,
    "tmin": tmin,
}
LABELS = {
    "tmean": "Temperaturmittel",
    "tmax": "Tagesmaximum",
    "tmin": "Tagesminimum",
}
REFERENCE_START = 1961
REFERENCE_END = 1990


def _xy_from_dataset(module, ds: xr.Dataset) -> tuple[np.ndarray, np.ndarray]:
    prepared = module.prepare_da(ds)
    x = np.asarray(prepared[-2], dtype=np.float64)
    y = np.asarray(prepared[-1], dtype=np.float64)
    return x, y


def _empty(region_names: list[str]):
    sums = {name: {} for name in region_names}
    counts = {name: {} for name in region_names}
    return sums, counts


def _update(sums, counts, dates, values):
    for region, series in values.items():
        for iso, value in zip(dates, series):
            if value is None:
                continue
            number = float(value)
            if not np.isfinite(number):
                continue
            mmdd = iso[5:10]
            sums[region][mmdd] = sums[region].get(mmdd, 0.0) + number
            counts[region][mmdd] = counts[region].get(mmdd, 0) + 1


def _payload(parameter: str, module, sums, counts, x, y):
    regions = {}
    sample_counts = {}
    for region in sums:
        regions[region] = {}
        sample_counts[region] = {}
        for mmdd in sorted(sums[region]):
            n = int(counts[region].get(mmdd, 0))
            if not n:
                continue
            regions[region][mmdd] = round(float(sums[region][mmdd]) / n, 3)
            sample_counts[region][mmdd] = n

    return {
        "schema_version": 1,
        "method_version": int(getattr(module, "METHOD_VERSION", 1)),
        "parameter": parameter,
        "label": LABELS[parameter],
        "unit": "°C",
        "reference": f"{REFERENCE_START}-{REFERENCE_END}",
        "grid_signature": module.grid_signature(x, y),
        "regions": regions,
        "sample_counts": sample_counts,
        "note": (
            f"Tägliches HYRAS-{parameter}-Gebietsmittel: zuerst räumliches "
            f"Gebietsmittel je Tag und Jahr, danach Kalendertagsmittel "
            f"{REFERENCE_START}–{REFERENCE_END}."
        ),
    }


def build(parameter: str, output: Path, work: Path) -> None:
    module = MODULES[parameter]
    files = module.latest_daily_files(module.daily_listing())
    missing = [
        year for year in range(REFERENCE_START, REFERENCE_END + 1)
        if year not in files
    ]
    if missing:
        raise RuntimeError(
            f"HYRAS-{parameter}: Tagesdateien fehlen für {missing}"
        )

    work.mkdir(parents=True, exist_ok=True)
    year_work = work / "years"
    year_work.mkdir(parents=True, exist_ok=True)

    masks = None
    sums = counts = None
    x_ref = y_ref = None

    for pos, year in enumerate(range(REFERENCE_START, REFERENCE_END + 1), 1):
        filename = files[year]
        target = year_work / filename
        if not target.exists():
            module.download(f"{module.DAILY_BASE}/{filename}", target)

        print(
            f"{parameter}: Referenz {REFERENCE_START}-{REFERENCE_END} "
            f"{pos}/30 · {year}",
            flush=True,
        )

        with xr.open_dataset(target, decode_times=True) as ds:
            if masks is None:
                x_ref, y_ref = _xy_from_dataset(module, ds)
                masks = tmean.build_masks(tmean.load_states(work), x_ref, y_ref)
                sums, counts = _empty(list(masks.keys()))
            dates, values, x, y = module.extract_region_daily(
                ds, masks, x_ref, y_ref
            )

        if (
            x.shape != x_ref.shape
            or y.shape != y_ref.shape
            or not np.allclose(x, x_ref)
            or not np.allclose(y, y_ref)
        ):
            raise RuntimeError(f"HYRAS-{parameter}: Rasterabweichung in {year}")

        _update(sums, counts, dates, values)
        target.unlink(missing_ok=True)

    assert masks is not None and sums is not None and counts is not None
    assert x_ref is not None and y_ref is not None
    payload = _payload(parameter, module, sums, counts, x_ref, y_ref)

    expected_regions = ["Deutschland", *tmean.EXPECTED_STATES]
    missing_regions = [
        name for name in expected_regions
        if name not in payload["regions"]
    ]
    if missing_regions:
        raise RuntimeError(
            f"HYRAS-{parameter}: Gebiete fehlen: {missing_regions}"
        )
    if len(payload["regions"]["Deutschland"]) < 365:
        raise RuntimeError(
            f"HYRAS-{parameter}: Referenzkurve Deutschland unvollständig"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"Fertig: {parameter} · {REFERENCE_START}-{REFERENCE_END} · "
        f"{len(payload['regions'])} Gebiete · {output}",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parameter", choices=sorted(MODULES), required=True
    )
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--work", default="/tmp/hyras-region-reference-1961-1990"
    )
    args = parser.parse_args()

    build(
        parameter=args.parameter,
        output=Path(args.output),
        work=Path(args.work) / args.parameter,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
