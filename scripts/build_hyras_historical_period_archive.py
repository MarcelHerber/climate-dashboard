#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from calendar import monthrange
from pathlib import Path

import numpy as np

RESOLUTION_KM = 1
VALUE_SCALE = 100
MISSING_I16 = -32768
PERIOD_KEYS = tuple(
    [f"month_{m:02d}" for m in range(1, 13)]
    + ["spring", "summer", "autumn", "winter", "year"]
)
PARAM_LABELS = {
    "tmean": "2-m-Temperaturmittel",
    "tmax": "2-m-Tagesmaximum",
    "tmin": "2-m-Tagesminimum",
}
SEASONS = {
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "autumn": (9, 10, 11),
}
MONTH_NAMES = [
    "", "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_daily(path: Path, parameter: str, year: int) -> dict:
    with np.load(path, allow_pickle=False) as data:
        p = str(np.asarray(data["parameter"]).item())
        y = int(np.asarray(data["year"]).item())
        resolution = int(np.asarray(data["resolution_km"]).item())
        scale = int(np.asarray(data["value_scale"]).item())
        missing = int(np.asarray(data["missing_value"]).item())
        codes = np.asarray(data["date_codes"], dtype=np.uint16)
        x = np.asarray(data["x"], dtype=np.float64)
        yy = np.asarray(data["y"], dtype=np.float64)
        values = np.asarray(data["values"], dtype=np.int16)
    if p != parameter or y != year:
        raise RuntimeError(f"Falsches Tagesarchiv: {p} {y}, erwartet {parameter} {year}")
    if resolution != RESOLUTION_KM or scale != VALUE_SCALE or missing != MISSING_I16:
        raise RuntimeError("Tagesarchiv besitzt unerwartete Raster-/Quantisierungsmetadaten")
    if values.ndim != 3 or values.shape[0] != codes.size or values.shape[1:] != (yy.size, x.size):
        raise RuntimeError("Ungültige Tagesarchiv-Geometrie")
    return {"year": year, "date_codes": codes, "x": x, "y": yy, "values": values}


def sum_count(values: np.ndarray, indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ny, nx = values.shape[1:]
    total = np.zeros((ny, nx), dtype=np.int64)
    count = np.zeros((ny, nx), dtype=np.uint16)
    for start in range(0, indices.size, 8):
        block = np.asarray(values[indices[start:start + 8]], dtype=np.int16)
        valid = block != MISSING_I16
        total += np.where(valid, block, 0).sum(axis=0, dtype=np.int64)
        count += valid.sum(axis=0, dtype=np.uint16)
    return total, count


def mean_packed(parts: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    if not parts:
        raise ValueError("Keine Teilperioden angegeben")
    total = np.zeros(parts[0][0].shape, dtype=np.int64)
    count = np.zeros(parts[0][1].shape, dtype=np.uint16)
    for s, n in parts:
        total += s
        count += n
    out = np.full(total.shape, MISSING_I16, dtype=np.int16)
    valid = count > 0
    if np.any(valid):
        out[valid] = np.clip(
            np.rint(total[valid] / count[valid].astype(np.float64)),
            -32767, 32767,
        ).astype(np.int16)
    return out


def period_meta(year: int, key: str, available: bool) -> dict:
    if key.startswith("month_"):
        m = int(key[-2:])
        start = f"{year:04d}-{m:02d}-01"
        end = f"{year:04d}-{m:02d}-{monthrange(year, m)[1]:02d}"
        label = f"{MONTH_NAMES[m]} {year}"
    elif key == "spring":
        start, end, label = f"{year}-03-01", f"{year}-05-31", f"Frühling {year}"
    elif key == "summer":
        start, end, label = f"{year}-06-01", f"{year}-08-31", f"Sommer {year}"
    elif key == "autumn":
        start, end, label = f"{year}-09-01", f"{year}-11-30", f"Herbst {year}"
    elif key == "winter":
        start = f"{year - 1}-12-01"
        end = f"{year}-02-{monthrange(year, 2)[1]:02d}"
        label = f"Winter {year - 1}/{str(year)[-2:]}"
    elif key == "year":
        start, end, label = f"{year}-01-01", f"{year}-12-31", f"Jahr {year}"
    else:
        raise ValueError(key)
    return {"key": key, "label": label, "start_date": start, "end_date": end, "available": available}


def build_stack(current: dict, previous: dict | None) -> tuple[np.ndarray, list[dict]]:
    year = int(current["year"])
    values = np.asarray(current["values"], dtype=np.int16)
    codes = np.asarray(current["date_codes"], dtype=np.uint16)
    months = codes // 100
    month_parts: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    month_planes: dict[int, np.ndarray] = {}
    for m in range(1, 13):
        idx = np.flatnonzero(months == m)
        expected = monthrange(year, m)[1]
        if idx.size != expected:
            raise RuntimeError(f"{year}-{m:02d}: {idx.size} statt {expected} Tage")
        part = sum_count(values, idx)
        month_parts[m] = part
        month_planes[m] = mean_packed([part])

    planes = [month_planes[m] for m in range(1, 13)]
    meta = [period_meta(year, f"month_{m:02d}", True) for m in range(1, 13)]

    for key, ms in SEASONS.items():
        planes.append(mean_packed([month_parts[m] for m in ms]))
        meta.append(period_meta(year, key, True))

    if previous is None:
        winter = np.full(values.shape[1:], MISSING_I16, dtype=np.int16)
        winter_available = False
    else:
        if int(previous["year"]) != year - 1:
            raise RuntimeError("Vorjahresarchiv besitzt falsches Jahr")
        if (
            previous["x"].shape != current["x"].shape
            or previous["y"].shape != current["y"].shape
            or not np.allclose(previous["x"], current["x"])
            or not np.allclose(previous["y"], current["y"])
        ):
            raise RuntimeError("Vorjahresarchiv besitzt anderes Raster")
        pcodes = np.asarray(previous["date_codes"], dtype=np.uint16)
        dec = np.flatnonzero((pcodes // 100) == 12)
        winter = mean_packed([
            sum_count(np.asarray(previous["values"], dtype=np.int16), dec),
            month_parts[1],
            month_parts[2],
        ])
        winter_available = True
    planes.append(winter)
    meta.append(period_meta(year, "winter", winter_available))

    planes.append(mean_packed([month_parts[m] for m in range(1, 13)]))
    meta.append(period_meta(year, "year", True))
    return np.stack(planes).astype(np.int16), meta


def build_year(parameter: str, year: int, daily: Path, previous_daily: Path | None,
               output_dir: Path, repository: str) -> dict:
    current = load_daily(daily, parameter, year)
    previous = load_daily(previous_daily, parameter, year - 1) if previous_daily else None
    values, periods = build_stack(current, previous)

    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"hyras-periods-{parameter}-{year}-1km.npz"
    path = output_dir / name
    np.savez_compressed(
        path,
        schema_version=np.asarray(1, dtype=np.int16),
        parameter=np.asarray(parameter),
        year=np.asarray(year, dtype=np.int16),
        resolution_km=np.asarray(1, dtype=np.int16),
        value_scale=np.asarray(VALUE_SCALE, dtype=np.int16),
        missing_value=np.asarray(MISSING_I16, dtype=np.int16),
        period_keys=np.asarray(PERIOD_KEYS),
        available=np.asarray([p["available"] for p in periods], dtype=np.uint8),
        x=np.asarray(current["x"], dtype=np.float64),
        y=np.asarray(current["y"], dtype=np.float64),
        values=values,
    )
    meta = {
        "schema_version": 1,
        "parameter": parameter,
        "label": PARAM_LABELS[parameter],
        "year": year,
        "unit": "°C",
        "resolution_km": 1,
        "width": int(current["x"].size),
        "height": int(current["y"].size),
        "value_scale": VALUE_SCALE,
        "missing_value": MISSING_I16,
        "period_keys": list(PERIOD_KEYS),
        "periods": periods,
        "archive_file": name,
        "archive_bytes": path.stat().st_size,
        "archive_sha256": sha256(path),
        "release_tag": "hyras-period-archive-1km",
        "release_asset_url": (
            f"https://github.com/{repository}/releases/download/hyras-period-archive-1km/{name}"
            if repository else None
        ),
    }
    (output_dir / f"hyras-periods-{parameter}-{year}-1km.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Periodenarchiv fertig: {parameter} {year} · 17 Perioden · {path.stat().st_size/1024/1024:.1f} MB", flush=True)
    return meta


def load_period(path: Path, parameter: str) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as data:
        p = str(np.asarray(data["parameter"]).item())
        year = int(np.asarray(data["year"]).item())
        resolution = int(np.asarray(data["resolution_km"]).item())
        scale = int(np.asarray(data["value_scale"]).item())
        missing = int(np.asarray(data["missing_value"]).item())
        keys = tuple(str(v) for v in np.asarray(data["period_keys"]).tolist())
        x = np.asarray(data["x"], dtype=np.float64)
        y = np.asarray(data["y"], dtype=np.float64)
        values = np.asarray(data["values"], dtype=np.int16)
    if (
        p != parameter
        or resolution != RESOLUTION_KM
        or scale != VALUE_SCALE
        or missing != MISSING_I16
        or keys != PERIOD_KEYS
        or values.shape != (17, y.size, x.size)
    ):
        raise RuntimeError(f"Ungültiges Periodenarchiv: {path.name}")
    return year, x, y, values


def build_reference(parameter: str, start_year: int, end_year: int,
                    input_dir: Path, output_dir: Path, repository: str) -> dict:
    if (start_year, end_year) not in ((1961, 1990), (1991, 2020)):
        raise ValueError("Referenz muss 1961–1990 oder 1991–2020 sein")
    sums = counts = None
    x_ref = y_ref = None
    for year in range(start_year, end_year + 1):
        path = input_dir / f"hyras-periods-{parameter}-{year}-1km.npz"
        y0, x, y, values = load_period(path, parameter)
        if y0 != year:
            raise RuntimeError(f"Falsches Jahr in {path.name}")
        if x_ref is None:
            x_ref, y_ref = x, y
            sums = np.zeros(values.shape, dtype=np.int64)
            counts = np.zeros(values.shape, dtype=np.uint16)
        elif (
            x.shape != x_ref.shape or y.shape != y_ref.shape
            or not np.allclose(x, x_ref) or not np.allclose(y, y_ref)
        ):
            raise RuntimeError(f"Rasterabweichung in {path.name}")
        valid = values != MISSING_I16
        sums += np.where(valid, values, 0)
        counts += valid.astype(np.uint16)

    assert sums is not None and counts is not None and x_ref is not None and y_ref is not None
    result = np.full(sums.shape, MISSING_I16, dtype=np.int16)
    valid = counts > 0
    result[valid] = np.clip(
        np.rint(sums[valid] / counts[valid].astype(np.float64)),
        -32767, 32767,
    ).astype(np.int16)

    output_dir.mkdir(parents=True, exist_ok=True)
    reference = f"{start_year}-{end_year}"
    name = f"hyras-period-reference-{parameter}-{reference}-1km.npz"
    path = output_dir / name
    np.savez_compressed(
        path,
        schema_version=np.asarray(1, dtype=np.int16),
        parameter=np.asarray(parameter),
        reference=np.asarray(reference),
        start_year=np.asarray(start_year, dtype=np.int16),
        end_year=np.asarray(end_year, dtype=np.int16),
        resolution_km=np.asarray(1, dtype=np.int16),
        value_scale=np.asarray(VALUE_SCALE, dtype=np.int16),
        missing_value=np.asarray(MISSING_I16, dtype=np.int16),
        period_keys=np.asarray(PERIOD_KEYS),
        x=x_ref,
        y=y_ref,
        values=result,
    )
    meta = {
        "schema_version": 1,
        "parameter": parameter,
        "label": PARAM_LABELS[parameter],
        "reference": reference,
        "start_year": start_year,
        "end_year": end_year,
        "unit": "°C",
        "resolution_km": 1,
        "width": int(x_ref.size),
        "height": int(y_ref.size),
        "value_scale": VALUE_SCALE,
        "missing_value": MISSING_I16,
        "period_keys": list(PERIOD_KEYS),
        "archive_file": name,
        "archive_bytes": path.stat().st_size,
        "archive_sha256": sha256(path),
        "release_tag": "hyras-period-archive-1km",
        "release_asset_url": (
            f"https://github.com/{repository}/releases/download/hyras-period-archive-1km/{name}"
            if repository else None
        ),
    }
    (output_dir / f"hyras-period-reference-{parameter}-{reference}-1km.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Referenz fertig: {parameter} {reference} · 17 Perioden", flush=True)
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    y = sub.add_parser("year")
    y.add_argument("--parameter", choices=tuple(PARAM_LABELS), required=True)
    y.add_argument("--year", type=int, required=True)
    y.add_argument("--daily-archive", required=True)
    y.add_argument("--previous-daily-archive")
    y.add_argument("--output-dir", required=True)
    y.add_argument("--repository", default="")

    r = sub.add_parser("reference")
    r.add_argument("--parameter", choices=tuple(PARAM_LABELS), required=True)
    r.add_argument("--start-year", type=int, required=True)
    r.add_argument("--end-year", type=int, required=True)
    r.add_argument("--input-dir", required=True)
    r.add_argument("--output-dir", required=True)
    r.add_argument("--repository", default="")

    args = ap.parse_args()
    if args.command == "year":
        build_year(
            args.parameter, args.year, Path(args.daily_archive),
            Path(args.previous_daily_archive) if args.previous_daily_archive else None,
            Path(args.output_dir), args.repository,
        )
    else:
        build_reference(
            args.parameter, args.start_year, args.end_year,
            Path(args.input_dir), Path(args.output_dir), args.repository,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
