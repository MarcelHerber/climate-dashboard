#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import gzip
import json
import math
import pickle
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1
SOURCE = "Administrația Națională de Meteorologie (ANM România) INSPIRE/WFS CLIMAT"
COUNTRY = "Rumänien"
COUNTRY_CODE = "RO"
NETWORK = "ANM RBSN essential stations"
PUBLIC_URL = "https://data.gov.ro/ro/dataset/statiile-meteorologice-esentiale-din-romania"

BASE = "https://inspire.meteoromania.ro"
UA = "climate-dashboard-anm-romania-baseline/1.0"

TIMEOUT = 120
RETRIES = 3
MAX_BYTES = 70 * 1024 * 1024
DEFAULT_WORKERS = 6

MAX_TOKEN = "TemperatureMaximumDailyCLIMAT"
MIN_TOKEN = "TemperatureMinimumDailyCLIMAT"
ALL_VALUES_TOKEN = "AllValuesWML20"

DATE_PREFIX_RE = re.compile(r"^((?:18|19|20)\d{2}-\d{2}-\d{2})")

STATION_NAMES: dict[str, str] = {
    "15015": "Ocna Sugatag",
    "15020": "Botosani",
    "15090": "Iasi",
    "15108": "Ceahlau Toaca",
    "15120": "Cluj-Napoca",
    "15150": "Bacau",
    "15170": "Miercurea Ciuc",
    "15200": "Arad",
    "15230": "Deva",
    "15260": "Sibiu",
    "15280": "Varfu Omu",
    "15292": "Caransebes",
    "15310": "Galati",
    "15335": "Tulcea",
    "15346": "Ramnicu Valcea",
    "15350": "Buzau",
    "15360": "Sulina",
    "15410": "Drobeta Turnu Severin",
    "15420": "Bucuresti-Baneasa",
    "15450": "Craiova",
    "15460": "Calarasi",
    "15470": "Rosiorii de Vede",
    "15480": "Constanta",
}
ACTIVE_STATION_CODES = tuple(STATION_NAMES)


def cache_dir_default() -> Path:
    return Path(".cache/europe-stations")


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"anm_romania_daily_baseline_through_{cutoff_year}_v1.pkl.gz"


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"anm_romania_progress_through_{cutoff_year}_v1.pkl.gz"


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"anm_romania_status_through_{cutoff_year}.json"


def request_bytes(url: str) -> tuple[bytes, dict[str, str], int]:
    headers = {
        "User-Agent": UA,
        "Accept": "application/gml+xml,application/xml,text/xml,*/*",
    }
    last: Exception | None = None

    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise RuntimeError(f"Antwort > {MAX_BYTES:,} Bytes: {url}")
                return raw, dict(resp.headers.items()), int(resp.status)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(attempt * 2.0)

    raise RuntimeError(f"Request fehlgeschlagen: {url}: {last}")


def parse_xml(raw: bytes, url: str) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        sample = raw[:800].decode("utf-8", "replace")
        raise RuntimeError(f"XML-Parsefehler {url}: {exc}; sample={sample!r}")


def local(tag: str) -> str:
    return tag.split("}")[-1]


def hrefs(root: ET.Element) -> list[str]:
    out: set[str] = set()
    for elem in root.iter():
        for key, value in elem.attrib.items():
            if key.endswith("href") or key == "href":
                val = str(value).strip()
                if val:
                    out.add(urllib.parse.urljoin(BASE, val.replace("&amp;", "&")))
    return sorted(out)


def metadata_url(station_code: str, element: str) -> str:
    token = MAX_TOKEN if element == "TMAX" else MIN_TOKEN
    return (
        f"{BASE}/ids/"
        f"OM_Observation.EnvironmentalMonitoringFacility.{station_code}/{token}"
    )


def all_values_link(meta_url: str, element: str) -> str:
    raw, _, _ = request_bytes(meta_url)
    root = parse_xml(raw, meta_url)

    wanted = MAX_TOKEN if element == "TMAX" else MIN_TOKEN

    exact = [
        u
        for u in hrefs(root)
        if ALL_VALUES_TOKEN.lower() in u.lower()
        and wanted.lower() in u.lower()
    ]
    if exact:
        return exact[0]

    fallback = [
        u
        for u in hrefs(root)
        if ALL_VALUES_TOKEN.lower() in u.lower()
    ]
    if fallback:
        return fallback[0]

    raise RuntimeError(f"Kein AllValuesWML20-Link: {meta_url}")


def find_desc_text(elem: ET.Element, names: set[str]) -> str | None:
    for sub in elem.iter():
        if local(sub.tag) in names and sub.text and sub.text.strip():
            return sub.text.strip()
    return None


def time_value_pairs(root: ET.Element) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []

    for elem in root.iter():
        if local(elem.tag) not in ("MeasurementTVP", "TVP"):
            continue

        stamp = find_desc_text(elem, {"time", "timePosition"})
        raw_value = find_desc_text(elem, {"value"})
        if not stamp or not raw_value:
            continue

        try:
            value = float(raw_value.replace(",", "."))
        except ValueError:
            continue

        pairs.append((stamp, value))

    if not pairs:
        for elem in root.iter():
            if local(elem.tag) != "point":
                continue

            stamp = find_desc_text(elem, {"time", "timePosition"})
            raw_value = find_desc_text(elem, {"value"})
            if not stamp or not raw_value:
                continue

            try:
                value = float(raw_value.replace(",", "."))
            except ValueError:
                continue

            pairs.append((stamp, value))

    out: list[tuple[str, float]] = []
    seen: set[tuple[str, float]] = set()

    for item in pairs:
        if item not in seen:
            seen.add(item)
            out.append(item)

    return out


def unit_candidates(root: ET.Element) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for elem in root.iter():
        lname = local(elem.tag)

        if lname.lower() in ("uom", "unitofmeasure", "unit"):
            rows.append({
                "tag": lname,
                "text": (elem.text or "").strip() or None,
                "attrs": dict(elem.attrib),
            })

        for key, value in elem.attrib.items():
            lowk = key.lower()
            lowv = str(value).lower()

            if (
                "uom" in lowk
                or "unit" in lowk
                or "kelvin" in lowv
                or lowv.endswith("/k")
            ):
                rows.append({
                    "tag": lname,
                    "attribute": key,
                    "value": str(value),
                })

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(row)

    return unique[:100]


def explicit_kelvin(units: list[dict[str, Any]]) -> bool:
    blob = json.dumps(units, ensure_ascii=False).lower()
    return (
        "kelvin" in blob
        or '"k"' in blob
        or "/k" in blob
        or "unit:k" in blob
    )


def to_celsius(kelvin: float) -> float:
    return round(kelvin - 273.15, 1)


def daily_series(station_code: str, element: str, cutoff_year: int) -> dict[str, float]:
    meta_url = metadata_url(station_code, element)
    values_url = all_values_link(meta_url, element)

    raw, _, _ = request_bytes(values_url)
    root = parse_xml(raw, values_url)

    units = unit_candidates(root)
    if not explicit_kelvin(units):
        raise RuntimeError(
            f"{station_code} {element}: Kelvin-Einheit nicht explizit bestätigt."
        )

    daily: dict[str, float] = {}

    for stamp, raw_value in time_value_pairs(root):
        match = DATE_PREFIX_RE.match(stamp)
        if not match:
            continue

        day = match.group(1)
        year = int(day[:4])
        if year > cutoff_year:
            continue

        value_c = to_celsius(raw_value)

        if element == "TMAX":
            if not (-60.0 <= value_c <= 55.0):
                continue
        else:
            if not (-65.0 <= value_c <= 45.0):
                continue

        daily[day] = value_c

    if not daily:
        raise RuntimeError(
            f"{station_code} {element}: keine Tageswerte bis {cutoff_year}."
        )

    return daily


def empty_record() -> dict[str, Any]:
    return {
        "first_date": None,
        "last_date": None,
        "observation_days": 0,
        "tmax_abs": None,
        "tmin_abs": None,
        "calendar_tmax": {},
        "calendar_tmin": {},
        "provenance_days": {"ANM_CLIMAT_WML20": 0},
    }


def better_max(old: list[Any] | None, value: float) -> bool:
    return old is None or value > float(old[0])


def better_min(old: list[Any] | None, value: float) -> bool:
    return old is None or value < float(old[0])


def consume_station(
    station_code: str,
    cutoff_year: int,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    tmax = daily_series(station_code, "TMAX", cutoff_year)
    tmin = daily_series(station_code, "TMIN", cutoff_year)

    common = sorted(set(tmax).intersection(tmin))
    violations = [
        day
        for day in common
        if tmax[day] < tmin[day]
    ]

    if violations:
        raise RuntimeError(
            f"{station_code}: {len(violations)} Tage mit Tmax<Tmin; "
            f"erstes Beispiel={violations[0]}"
        )

    all_days = sorted(set(tmax).union(tmin))
    rec = empty_record()

    for day in all_days:
        vmax = tmax.get(day)
        vmin = tmin.get(day)

        if vmax is None and vmin is None:
            continue

        if rec["first_date"] is None or day < rec["first_date"]:
            rec["first_date"] = day
        if rec["last_date"] is None or day > rec["last_date"]:
            rec["last_date"] = day

        rec["observation_days"] += 1
        rec["provenance_days"]["ANM_CLIMAT_WML20"] += 1

        mmdd = day[5:10]

        if vmax is not None:
            if better_max(rec["tmax_abs"], vmax):
                rec["tmax_abs"] = [float(vmax), day]

            old = rec["calendar_tmax"].get(mmdd)
            if better_max(old, vmax):
                rec["calendar_tmax"][mmdd] = [float(vmax), day]

        if vmin is not None:
            if better_min(rec["tmin_abs"], vmin):
                rec["tmin_abs"] = [float(vmin), day]

            old = rec["calendar_tmin"].get(mmdd)
            if better_min(old, vmin):
                rec["calendar_tmin"][mmdd] = [float(vmin), day]

    if rec["tmax_abs"] is None or rec["tmin_abs"] is None:
        raise RuntimeError(f"{station_code}: Tmax/Tmin-Absolutrekord fehlt.")

    meta = {
        "id": station_code,
        "name": STATION_NAMES[station_code],
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "lat": None,
        "lon": None,
        "elevation_m": None,
        "network": NETWORK,
        "source": SOURCE,
        "wmo_id": station_code,
    }

    stats = {
        "tmax_days": len(tmax),
        "tmin_days": len(tmin),
        "common_days": len(common),
        "first_date": rec["first_date"],
        "last_date": rec["last_date"],
        "tmax_abs": rec["tmax_abs"],
        "tmin_abs": rec["tmin_abs"],
    }

    return station_code, rec, {"meta": meta, "stats": stats}


def load_pickle_gzip(path: Path) -> Any:
    with gzip.open(path, "rb") as fh:
        return pickle.load(fh)


def save_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def valid_final(path: Path, cutoff_year: int) -> bool:
    if not path.exists():
        return False

    try:
        obj = load_pickle_gzip(path)
    except Exception:
        return False

    if not isinstance(obj, dict):
        return False

    return (
        obj.get("format_version") == FORMAT_VERSION
        and obj.get("source") == SOURCE
        and obj.get("country") == COUNTRY
        and obj.get("cutoff_year") == cutoff_year
        and obj.get("complete") is True
        and len(obj.get("records", {})) == len(ACTIVE_STATION_CODES)
        and set(obj.get("records", {})) == set(ACTIVE_STATION_CODES)
    )


def initial_progress(cutoff_year: int) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "network": NETWORK,
        "cutoff_year": cutoff_year,
        "complete": False,
        "inventory": {},
        "records": {},
        "station_stats": {},
        "completed_station_codes": [],
        "expected_station_codes": list(ACTIVE_STATION_CODES),
    }


def build_baseline(
    cache_dir: Path,
    cutoff_year: int,
    *,
    force: bool = False,
    workers: int = DEFAULT_WORKERS,
) -> Path:
    final = baseline_path(cache_dir, cutoff_year)
    progress_file = progress_path(cache_dir, cutoff_year)

    if not force and valid_final(final, cutoff_year):
        print(f"Verwende vorhandenen ANM-Rumänien-Baselinecache: {final}")
        return final

    if force:
        final.unlink(missing_ok=True)
        progress_file.unlink(missing_ok=True)

    if progress_file.exists():
        try:
            progress = load_pickle_gzip(progress_file)
        except Exception:
            progress = initial_progress(cutoff_year)
    else:
        progress = initial_progress(cutoff_year)

    if (
        not isinstance(progress, dict)
        or progress.get("format_version") != FORMAT_VERSION
        or progress.get("cutoff_year") != cutoff_year
    ):
        progress = initial_progress(cutoff_year)

    completed = set(str(x) for x in progress.get("completed_station_codes", []))
    todo = [
        sid
        for sid in ACTIVE_STATION_CODES
        if sid not in completed
    ]

    workers = max(1, min(int(workers), 10))

    print("=== ANM RUMÄNIEN HISTORICAL BASELINE ===")
    print(f"Cutoff: {cutoff_year}-12-31")
    print(f"Festes RBSN-Netz: {len(ACTIVE_STATION_CODES)} Stationen")
    print(f"Schon fertig: {len(completed)}")
    print(f"Noch offen: {len(todo)}")
    print(f"Parallelität: {workers}")
    print()

    if todo:
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(consume_station, sid, cutoff_year): sid
                for sid in todo
            }

            for fut in cf.as_completed(future_map):
                sid = future_map[fut]
                try:
                    station_code, rec, extra = fut.result()
                except Exception as exc:
                    raise RuntimeError(f"ANM {sid} fehlgeschlagen: {exc}") from exc

                progress["records"][station_code] = rec
                progress["inventory"][station_code] = extra["meta"]
                progress["station_stats"][station_code] = extra["stats"]

                completed.add(station_code)
                progress["completed_station_codes"] = sorted(completed)
                save_pickle_gzip(progress_file, progress)

                stat = extra["stats"]
                print(
                    f"{len(completed):02d}/{len(ACTIVE_STATION_CODES):02d} "
                    f"{station_code} {STATION_NAMES[station_code]} | "
                    f"{stat['first_date']} .. {stat['last_date']} | "
                    f"Tmax-Tage={stat['tmax_days']:,} | "
                    f"Tmin-Tage={stat['tmin_days']:,} | "
                    f"Tmax={stat['tmax_abs'][0]:.1f}°C | "
                    f"Tmin={stat['tmin_abs'][0]:.1f}°C"
                )

    records = progress.get("records", {})
    inventory = progress.get("inventory", {})

    if set(records) != set(ACTIVE_STATION_CODES):
        missing = sorted(set(ACTIVE_STATION_CODES) - set(records))
        raise RuntimeError(f"Baseline unvollständig; fehlend={missing}")

    if set(inventory) != set(ACTIVE_STATION_CODES):
        missing = sorted(set(ACTIVE_STATION_CODES) - set(inventory))
        raise RuntimeError(f"Inventar unvollständig; fehlend={missing}")

    first_dates = [
        rec["first_date"]
        for rec in records.values()
        if rec.get("first_date")
    ]
    last_dates = [
        rec["last_date"]
        for rec in records.values()
        if rec.get("last_date")
    ]

    payload = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "public_url": PUBLIC_URL,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "network": NETWORK,
        "cutoff_year": cutoff_year,
        "complete": True,
        "expected_active_station_count": len(ACTIVE_STATION_CODES),
        "station_count": len(records),
        "inventory_count": len(inventory),
        "first_date": min(first_dates) if first_dates else None,
        "last_date": max(last_dates) if last_dates else None,
        "inventory": inventory,
        "records": records,
        "station_stats": progress.get("station_stats", {}),
    }

    save_pickle_gzip(final, payload)

    progress["complete"] = True
    save_pickle_gzip(progress_file, progress)

    write_status(cache_dir, cutoff_year, payload)

    if not valid_final(final, cutoff_year):
        raise RuntimeError("Finaler ANM-Rumänien-Baselinecache besteht Validierung nicht.")

    return final


def write_status(cache_dir: Path, cutoff_year: int, payload: dict[str, Any]) -> Path:
    path = status_path(cache_dir, cutoff_year)
    path.parent.mkdir(parents=True, exist_ok=True)

    records = payload.get("records", {})
    total_obs_days = sum(
        int(rec.get("observation_days") or 0)
        for rec in records.values()
        if isinstance(rec, dict)
    )

    status = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "country": COUNTRY,
        "network": NETWORK,
        "cutoff_year": cutoff_year,
        "complete": payload.get("complete") is True,
        "baseline_file": str(baseline_path(cache_dir, cutoff_year)),
        "expected_active_station_count": len(ACTIVE_STATION_CODES),
        "station_count": len(records),
        "inventory_count": len(payload.get("inventory", {})),
        "first_date": payload.get("first_date"),
        "last_date": payload.get("last_date"),
        "observation_days_sum": total_obs_days,
        "stores_only": [
            "highest Tmax absolute record",
            "lowest Tmin absolute record",
            "calendar-day highest Tmax records",
            "calendar-day lowest Tmin records",
        ],
    }

    path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def self_test() -> None:
    assert len(STATION_NAMES) == 23
    assert STATION_NAMES["15015"] == "Ocna Sugatag"
    assert STATION_NAMES["15480"] == "Constanta"

    rec = empty_record()
    assert "tmax_low_abs" not in rec
    assert "tmin_high_abs" not in rec

    assert to_celsius(299.15) == 26.0
    assert metadata_url("15020", "TMAX").endswith(
        "EnvironmentalMonitoringFacility.15020/TemperatureMaximumDailyCLIMAT"
    )
    assert metadata_url("15020", "TMIN").endswith(
        "EnvironmentalMonitoringFacility.15020/TemperatureMinimumDailyCLIMAT"
    )

    print("ANM Romania historical baseline self-test OK.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", default=str(cache_dir_default()))
    parser.add_argument(
        "--cutoff-year",
        type=int,
        default=dt.datetime.now(dt.timezone.utc).year - 1,
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    cache_dir = Path(args.cache_dir)
    path = build_baseline(
        cache_dir,
        args.cutoff_year,
        force=args.force,
        workers=args.workers,
    )

    payload = load_pickle_gzip(path)
    status_file = status_path(cache_dir, args.cutoff_year)

    print()
    print("=== ANM RUMÄNIEN BASELINE FERTIG ===")
    print(f"Datei: {path}")
    print(f"Status: {status_file}")
    print(f"Stationen: {payload['station_count']}")
    print(f"Datumsbereich: {payload['first_date']} .. {payload['last_date']}")
    print("ANM Rumänien Baseline-Prüfung OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
