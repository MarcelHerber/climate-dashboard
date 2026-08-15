#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import requests
import xarray as xr

from build_hyras_tmean_regions import (
    EXPECTED_STATES,
    build_masks,
    load_states,
)

DAILY_BASE = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/daily/hyras_de/air_temperature_min"
USER_AGENT = "climate-dashboard-hyras-tmin-regions/1.1 (+GitHub Actions; DWD Open Data)"
REFERENCE_START = 1991
REFERENCE_END = 2020
RECORD_FIRST_YEAR = 1951
METHOD_VERSION = 1

MONTH_DE = {
    1:"Januar", 2:"Februar", 3:"März", 4:"April", 5:"Mai", 6:"Juni",
    7:"Juli", 8:"August", 9:"September", 10:"Oktober", 11:"November", 12:"Dezember",
}


def get(url: str, timeout: int = 120) -> requests.Response:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Download: {url}", flush=True)
    with requests.get(url, stream=True, timeout=420, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    print(f"  -> {target.name}: {target.stat().st_size / 1024 / 1024:.1f} MB", flush=True)


def daily_listing() -> str:
    return get(DAILY_BASE + "/", 90).text


def latest_daily_files(text: str) -> dict[int, str]:
    pat = re.compile(
        r'href="(?P<filename>tasmin_hyras_1_(?P<year>\d{4})_'
        r'v(?P<major>\d+)-(?P<minor>\d+)_de\.nc)"'
    )
    best: dict[int, tuple[int, int, str]] = {}
    for m in pat.finditer(text):
        year = int(m.group("year"))
        item = (int(m.group("major")), int(m.group("minor")), m.group("filename"))
        if year not in best or item[:2] > best[year][:2]:
            best[year] = item
    return {year: item[2] for year, item in best.items()}


def pick_var(ds: xr.Dataset) -> xr.DataArray:
    for name in ("tasmin", "tmin", "air_temperature_min", "temperature"):
        if name in ds.data_vars and ds[name].ndim >= 2:
            return ds[name]
    for name, da in ds.data_vars.items():
        if da.ndim >= 2:
            print(f"Hinweis: verwende Tmin-Variable {name}", flush=True)
            return da
    raise RuntimeError(f"Keine HYRAS-Tmin-Variable gefunden: {list(ds.data_vars)}")


def time_dim(da: xr.DataArray) -> str:
    for d in da.dims:
        if d.lower() == "time":
            return d
    for d in da.dims:
        c = da.coords.get(d)
        if c is not None and np.issubdtype(c.dtype, np.datetime64):
            return d
    raise RuntimeError("Keine Zeitdimension gefunden.")


def spatial_dims(da: xr.DataArray) -> tuple[str, str]:
    td = time_dim(da)
    dims = [d for d in da.dims if d != td]
    if len(dims) != 2:
        raise RuntimeError(f"Unerwartete HYRAS-Tmin-Dimensionen: {da.dims}")
    y = next((d for d in dims if d.lower() in {"y","lat","latitude","rlat"}), dims[0])
    x = next((d for d in dims if d.lower() in {"x","lon","longitude","rlon"}), dims[1])
    if x == y:
        raise RuntimeError(f"Raumdimensionen konnten nicht bestimmt werden: {da.dims}")
    return y, x


def to_celsius(da: xr.DataArray) -> xr.DataArray:
    units = str(da.attrs.get("units", "")).lower().strip()
    if units == "k" or "kelvin" in units:
        return da - 273.15
    try:
        probe = float(da.isel({d: 0 for d in da.dims[:-2]}).mean(skipna=True).values)
        if np.isfinite(probe) and probe > 100:
            return da - 273.15
    except Exception:
        pass
    return da


def prepare_da(ds: xr.Dataset) -> tuple[xr.DataArray, str, np.ndarray, np.ndarray]:
    da = to_celsius(pick_var(ds)).squeeze(drop=True)
    td = time_dim(da)
    ydim, xdim = spatial_dims(da)
    da = da.transpose(td, ydim, xdim)
    x = np.asarray(da[xdim].values, dtype=np.float64)
    y = np.asarray(da[ydim].values, dtype=np.float64)
    if x.ndim != 1 or y.ndim != 1:
        raise RuntimeError("HYRAS-Tmin x/y-Koordinaten sind nicht eindimensional.")
    return da, td, x, y


def grid_signature(x: np.ndarray, y: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(np.asarray(x, dtype="<f8").tobytes())
    h.update(np.asarray(y, dtype="<f8").tobytes())
    return h.hexdigest()[:20]


def extract_region_daily(
    ds: xr.Dataset,
    masks: dict[str, np.ndarray],
    expected_x: np.ndarray | None = None,
    expected_y: np.ndarray | None = None,
    chunk_days: int = 16,
) -> tuple[list[str], dict[str, list[float | None]], np.ndarray, np.ndarray]:
    da, td, x, y = prepare_da(ds)

    if expected_x is not None and (x.shape != expected_x.shape or not np.allclose(x, expected_x)):
        raise RuntimeError("Historisches HYRAS-Tmin-x-Gitter weicht vom aktuellen Gitter ab.")
    if expected_y is not None and (y.shape != expected_y.shape or not np.allclose(y, expected_y)):
        raise RuntimeError("Historisches HYRAS-Tmin-y-Gitter weicht vom aktuellen Gitter ab.")

    dates = [str(v) for v in da[td].values.astype("datetime64[D]")]
    out = {name: [None] * len(dates) for name in masks}
    indices = {name: np.flatnonzero(mask.ravel()) for name, mask in masks.items()}

    for start in range(0, len(dates), chunk_days):
        end = min(len(dates), start + chunk_days)
        block = np.asarray(da.isel({td: slice(start, end)}).values, dtype=np.float32)
        flat = block.reshape(block.shape[0], -1)

        for name, idx in indices.items():
            vals = flat[:, idx]
            with np.errstate(invalid="ignore"):
                means = np.nanmean(vals, axis=1)
            for j, value in enumerate(means):
                out[name][start + j] = round(float(value), 3) if np.isfinite(value) else None

    return dates, out, x, y


def date_periods(year: int, data_through: str) -> list[dict[str, Any]]:
    end = datetime.strptime(data_through, "%Y-%m-%d").date()
    periods: list[dict[str, Any]] = [{
        "key": "year_current",
        "label": f"Jahr aktuell {year}",
        "start_date": f"{year}-01-01",
        "end_date": data_through,
    }]

    for sid, label, sm, sd, em, ed in [
        ("spring", "Frühling", 3, 1, 5, 31),
        ("summer", "Sommer", 6, 1, 8, 31),
        ("autumn", "Herbst", 9, 1, 11, 30),
    ]:
        start = datetime(year, sm, sd).date()
        finish = datetime(year, em, ed).date()
        if end >= start:
            clipped = min(end, finish)
            live = clipped < finish
            periods.append({
                "key": sid,
                "label": f"{label}{' aktuell' if live else ''} {year}",
                "start_date": start.isoformat(),
                "end_date": clipped.isoformat(),
            })

    for month in range(1, end.month + 1):
        last = calendar.monthrange(year, month)[1]
        month_end = datetime(year, month, last).date()
        clipped = min(end, month_end)
        live = clipped < month_end
        periods.append({
            "key": f"month_{month:02d}",
            "label": f"{MONTH_DE[month]}{' aktuell' if live else ''} {year}",
            "start_date": f"{year}-{month:02d}-01",
            "end_date": clipped.isoformat(),
        })

    return periods


def empty_climate(region_names: list[str]) -> tuple[dict, dict]:
    sums = {name: {} for name in region_names}
    counts = {name: {} for name in region_names}
    return sums, counts


def empty_records(region_names: list[str]) -> dict:
    return {name: {} for name in region_names}


def update_climate(
    sums: dict,
    counts: dict,
    dates: list[str],
    values: dict[str, list[float | None]],
) -> None:
    for region, series in values.items():
        for date, value in zip(dates, series):
            if value is None:
                continue
            mmdd = date[5:10]
            sums[region][mmdd] = sums[region].get(mmdd, 0.0) + float(value)
            counts[region][mmdd] = counts[region].get(mmdd, 0) + 1


def update_records(
    records: dict,
    dates: list[str],
    values: dict[str, list[float | None]],
    year: int,
) -> None:
    for region, series in values.items():
        rr = records[region]
        for date, value in zip(dates, series):
            if value is None or not np.isfinite(value):
                continue
            v = round(float(value), 3)
            mmdd = date[5:10]
            rec = rr.get(mmdd)

            if rec is None:
                rr[mmdd] = {
                    "max": v, "max_years": [int(year)],
                    "min": v, "min_years": [int(year)],
                }
                continue

            if v > float(rec["max"]):
                rec["max"] = v
                rec["max_years"] = [int(year)]
            elif v == float(rec["max"]) and int(year) not in rec.get("max_years", []):
                rec.setdefault("max_years", []).append(int(year))

            if v < float(rec["min"]):
                rec["min"] = v
                rec["min_years"] = [int(year)]
            elif v == float(rec["min"]) and int(year) not in rec.get("min_years", []):
                rec.setdefault("min_years", []).append(int(year))


def climate_payload(
    sums: dict,
    counts: dict,
    x: np.ndarray,
    y: np.ndarray,
) -> dict[str, Any]:
    regions = {}
    sample_counts = {}
    for name in sums:
        regions[name] = {}
        sample_counts[name] = {}
        for mmdd in sorted(sums[name]):
            n = int(counts[name].get(mmdd, 0))
            if n:
                regions[name][mmdd] = round(float(sums[name][mmdd]) / n, 3)
                sample_counts[name][mmdd] = n

    return {
        "schema_version": 1,
        "method_version": METHOD_VERSION,
        "parameter": "tmin",
        "label": "Tagesminimum",
        "unit": "°C",
        "reference": f"{REFERENCE_START}-{REFERENCE_END}",
        "grid_signature": grid_signature(x, y),
        "regions": regions,
        "sample_counts": sample_counts,
        "note": (
            "Tägliches HYRAS-Tmin-Gebietsmittel: zuerst räumliches Mittel der "
            "Tagesminima je Gebiet und Tag, danach Kalendertagsmittel 1991–2020."
        ),
    }


def reusable_summary(
    climate_path: Path,
    records_path: Path,
    x: np.ndarray,
    y: np.ndarray,
    record_last_year: int,
) -> bool:
    if not climate_path.exists() or not records_path.exists():
        return False
    try:
        climate = json.loads(climate_path.read_text(encoding="utf-8"))
        records = json.loads(records_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    sig = grid_signature(x, y)
    return (
        climate.get("parameter") == "tmin"
        and climate.get("reference") == f"{REFERENCE_START}-{REFERENCE_END}"
        and climate.get("grid_signature") == sig
        and records.get("parameter") == "tmin"
        and records.get("first_year") == RECORD_FIRST_YEAR
        and records.get("last_year") == record_last_year
        and records.get("grid_signature") == sig
        and all(name in climate.get("regions", {}) for name in ["Deutschland", *EXPECTED_STATES])
        and all(name in records.get("regions", {}) for name in ["Deutschland", *EXPECTED_STATES])
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default="/tmp/hyras-data")
    ap.add_argument("--work", default="/tmp/hyras-tmin-work")
    ap.add_argument("--force-history-summary", action="store_true")
    args = ap.parse_args()

    data_root = Path(args.data_root)
    work = Path(args.work)
    out_root = data_root / "tmin"
    regions_dir = out_root / "regions"
    regions_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    files = latest_daily_files(daily_listing())
    if not files:
        raise RuntimeError("Keine HYRAS-Tmin-Tagesdateien gefunden.")

    current_year = max(files)
    current_filename = files[current_year]
    current_nc = work / current_filename
    if not current_nc.exists():
        download(f"{DAILY_BASE}/{current_filename}", current_nc)

    with xr.open_dataset(current_nc, decode_times=True) as ds:
        _, _, x, y = prepare_da(ds)

    # WICHTIG: wie bei Tmean/Tmax direkt aus den Bundesland-Geometrien erzeugen.
    masks = build_masks(load_states(work), x, y)
    region_names = list(masks.keys())

    with xr.open_dataset(current_nc, decode_times=True) as ds:
        current_dates, current_values, cx, cy = extract_region_daily(ds, masks)

    if not current_dates:
        raise RuntimeError("Aktuelle HYRAS-Tmin-Datei enthält keine Tage.")

    data_through = current_dates[-1]
    current_payload = {
        "schema_version": 1,
        "method_version": METHOD_VERSION,
        "parameter": "tmin",
        "label": "Tagesminimum",
        "unit": "°C",
        "year": current_year,
        "first_date": current_dates[0],
        "data_through": data_through,
        "dates": current_dates,
        "regions": current_values,
    }
    current_path = regions_dir / f"current_{current_year}.json"
    current_path.write_text(
        json.dumps(current_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    climate_path = regions_dir / "climate_1991_2020.json"
    records_path = regions_dir / "daily_records.json"
    record_last_year = current_year - 1

    if (
        not args.force_history_summary
        and reusable_summary(climate_path, records_path, cx, cy, record_last_year)
    ):
        print(
            f"Verwende vorhandene Tmin-Klimakurve {REFERENCE_START}–{REFERENCE_END} "
            f"und Tagesrekorde {RECORD_FIRST_YEAR}–{record_last_year}.",
            flush=True,
        )
    else:
        print(
            f"Baue Tmin-Klimakurve {REFERENCE_START}–{REFERENCE_END} und "
            f"Tagesrekorde {RECORD_FIRST_YEAR}–{record_last_year} in einem Lauf …",
            flush=True,
        )

        missing = [
            year for year in range(RECORD_FIRST_YEAR, record_last_year + 1)
            if year not in files
        ]
        if missing:
            raise RuntimeError(
                "HYRAS-Tmin-Tagesdateien fehlen für: " + ", ".join(map(str, missing))
            )

        sums, counts = empty_climate(region_names)
        records = empty_records(region_names)
        history_work = work / "history_years"
        history_work.mkdir(parents=True, exist_ok=True)

        for year in range(RECORD_FIRST_YEAR, record_last_year + 1):
            filename = files[year]
            target = history_work / filename
            if not target.exists():
                download(f"{DAILY_BASE}/{filename}", target)

            print(f"Tmin Historie {year}: {filename}", flush=True)
            with xr.open_dataset(target, decode_times=True) as ds:
                dates, values, _, _ = extract_region_daily(ds, masks, cx, cy)

            update_records(records, dates, values, year)
            if REFERENCE_START <= year <= REFERENCE_END:
                update_climate(sums, counts, dates, values)

            target.unlink(missing_ok=True)

        climate = climate_payload(sums, counts, cx, cy)
        climate_path.write_text(
            json.dumps(climate, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

        records_payload = {
            "schema_version": 1,
            "method_version": METHOD_VERSION,
            "parameter": "tmin",
            "label": "Tagesminimum",
            "unit": "°C",
            "first_year": RECORD_FIRST_YEAR,
            "last_year": record_last_year,
            "grid_signature": grid_signature(cx, cy),
            "regions": records,
            "note": (
                "Historische tägliche Maxima und Minima des räumlichen "
                "HYRAS-Tmin-Gebietsmittels je Kalendertag."
            ),
        }
        records_path.write_text(
            json.dumps(records_payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    index = {
        "schema_version": 1,
        "method_version": METHOD_VERSION,
        "parameter": "tmin",
        "label": "Tagesminimum",
        "unit": "°C",
        "reference": f"{REFERENCE_START}-{REFERENCE_END}",
        "year": current_year,
        "data_through": data_through,
        "regions": ["Deutschland", *EXPECTED_STATES],
        "current_file": current_path.name,
        "climate_file": climate_path.name,
        "records_file": records_path.name,
        "records_first_year": RECORD_FIRST_YEAR,
        "records_last_year": record_last_year,
        "periods": date_periods(current_year, data_through),
        "method_note": (
            "HYRAS-DE-TASMIN: tägliches räumliches Mittel aller 1-km-Gitterzellen "
            "mit Zellmittelpunkt im jeweiligen Bundesland; Deutschland ist die "
            "Vereinigung der 16 Landesmasken."
        ),
    }
    (regions_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    climate = json.loads(climate_path.read_text(encoding="utf-8"))
    records = json.loads(records_path.read_text(encoding="utf-8"))

    if len(index["regions"]) != 17:
        raise RuntimeError(f"Unerwartete Gebietszahl: {len(index['regions'])}")
    if len(climate["regions"].get("Deutschland", {})) < 365:
        raise RuntimeError("Tmin-Klimakurve Deutschland ist unvollständig.")
    if len(records["regions"].get("Deutschland", {})) < 365:
        raise RuntimeError("Tmin-Rekordkalender Deutschland ist unvollständig.")

    print("HYRAS Tmin Datenbasis fertig.", flush=True)
    print("Datenstand:", data_through, flush=True)
    print("Gebiete:", len(index["regions"]), flush=True)
    print("Perioden:", len(index["periods"]), flush=True)
    print("Klima:", f"{REFERENCE_START}–{REFERENCE_END}", flush=True)
    print("Rekorde:", f"{RECORD_FIRST_YEAR}–{record_last_year}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
