#!/usr/bin/env python3
"""Build compact European station-record datasets for the static Climate Dashboard.

Primary source in Stations-V1: NOAA/NCEI GHCN-Daily.

Architecture
------------
* Historical baseline: all quality-passed TMAX/TMIN observations before the
  current calendar year, streamed from ghcnd_all.tar.gz and cached by GitHub
  Actions. The large archive is never written to disk.
* Daily update: only the current YYYY.csv.gz by-year file is downloaded.
* Frontend output:
    europe_stations/index.json
    europe_stations/calendar/MM-DD.json.gz  (366 compact day packs)

The JSON schema deliberately contains a ``source`` field so national providers
(DWD, Meteo-France, AEMET, ...) can replace GHCN country-by-country later without
changing the frontend contract.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import pickle
import sys
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
STATIONS_URL = f"{BASE}/ghcnd-stations.txt"
COUNTRIES_URL = f"{BASE}/ghcnd-countries.txt"
ARCHIVE_URL = f"{BASE}/ghcnd_all.tar.gz"
BY_YEAR_URL = f"{BASE}/by_year/{{year}}.csv.gz"

PAYLOAD_VERSION = 1
BASELINE_FORMAT_VERSION = 2
SOURCE_NAME = "GHCN-Daily"

# GHCN FIPS country codes. Russia/Turkey/Caucasus are additionally clipped to
# the dashboard's Europe map extent below.
EUROPE_CODES = {
    "AL", "AU", "BE", "BK", "BO", "BU", "CY", "DA", "EI", "EN", "EZ",
    "FI", "FR", "GG", "GI", "GM", "GR", "HR", "HU", "IC", "IT", "JN",
    "LG", "LH", "LO", "LU", "MD", "MJ", "MK", "MT", "NL", "NO", "PL",
    "PO", "RI", "RO", "RS", "SI", "SP", "SV", "SW", "SZ", "TU", "UK",
    "UP", "AM", "AJ", "KZ",
}

COUNTRY_NAME_DE = {
    "AL":"Albanien", "AU":"Österreich", "BE":"Belgien", "BK":"Bosnien und Herzegowina",
    "BO":"Belarus", "BU":"Bulgarien", "CY":"Zypern", "DA":"Dänemark", "EI":"Irland",
    "EN":"Estland", "EZ":"Tschechien", "FI":"Finnland", "FR":"Frankreich", "GG":"Georgien",
    "GI":"Gibraltar", "GM":"Deutschland", "GR":"Griechenland", "HR":"Kroatien", "HU":"Ungarn",
    "IC":"Island", "IT":"Italien", "JN":"Jan Mayen", "LG":"Lettland", "LH":"Litauen",
    "LO":"Slowakei", "LU":"Luxemburg", "MD":"Moldau", "MJ":"Montenegro", "MK":"Nordmazedonien",
    "MT":"Malta", "NL":"Niederlande", "NO":"Norwegen", "PL":"Polen", "PO":"Portugal",
    "RI":"Serbien", "RO":"Rumänien", "RS":"Russland", "SI":"Slowenien", "SP":"Spanien",
    "SV":"Svalbard", "SW":"Schweden", "SZ":"Schweiz", "TU":"Türkei", "UK":"Vereinigtes Königreich",
    "UP":"Ukraine", "AM":"Armenien", "AJ":"Aserbaidschan", "KZ":"Kasachstan",
}

# Broad Europe display extent used by the dashboard. Country-code filtering
# prevents North African/Middle Eastern stations from entering the set.
LAT_MIN, LAT_MAX = 34.0, 72.5
LON_MIN, LON_MAX = -25.5, 45.5


def log(message: str) -> None:
    print(message, flush=True)


def http_open(url: str, attempts: int = 5, timeout: int = 180):
    headers = {"User-Agent": "climate-dashboard-ghcn/1.0 (+GitHub Actions)"}
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            return urllib.request.urlopen(req, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            wait = min(15 * attempt, 60)
            log(f"HTTP-Fehler für {url} (Versuch {attempt}/{attempts}): {exc}; neuer Versuch in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Download fehlgeschlagen: {url}: {last_error}")


def read_url_text(url: str) -> str:
    with http_open(url) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_countries(text: str) -> Dict[str, str]:
    result = {}
    for raw in text.splitlines():
        if len(raw) >= 4:
            result[raw[:2]] = raw[3:].strip()
    return result


@dataclass(frozen=True)
class StationMeta:
    id: str
    lat: float
    lon: float
    elev: Optional[float]
    name: str
    country_code: str
    country: str


def parse_stations(text: str, countries: Dict[str, str]) -> Dict[str, StationMeta]:
    stations: Dict[str, StationMeta] = {}
    for raw in text.splitlines():
        if len(raw) < 42:
            continue
        sid = raw[0:11].strip()
        code = sid[:2]
        if code not in EUROPE_CODES:
            continue
        try:
            lat = float(raw[12:20])
            lon = float(raw[21:30])
            elev_raw = float(raw[31:37])
        except ValueError:
            continue
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            continue
        elev = None if elev_raw <= -999 else round(elev_raw, 1)
        name = raw[41:71].strip() or sid
        country = COUNTRY_NAME_DE.get(code, countries.get(code, code))
        stations[sid] = StationMeta(sid, lat, lon, elev, name, code, country)
    return stations


def better(element: str, new_value: int, old_value: Optional[int]) -> bool:
    if old_value is None:
        return True
    return new_value > old_value if element == "TMAX" else new_value < old_value


def equal_record(new_value: int, old_value: Optional[int]) -> bool:
    return old_value is not None and new_value == old_value


def empty_state() -> dict:
    return {
        "TMAX": {"abs": None, "cal": {}, "start": None, "end": None, "years": 0},
        "TMIN": {"abs": None, "cal": {}, "start": None, "end": None, "years": 0},
    }


def update_record(record: Optional[Tuple[int, int, int]], value: int, date_int: int, element: str) -> Tuple[int, int, int]:
    """record = (value, first_date, tie_count)."""
    if record is None or better(element, value, record[0]):
        return (value, date_int, 1)
    if value == record[0]:
        return (record[0], record[1], record[2] + 1)
    return record


def parse_dly_station(stream: io.BufferedReader, cutoff_year: int) -> dict:
    state = empty_state()
    observed_years = {"TMAX": set(), "TMIN": set()}
    for raw in stream:
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("ascii", errors="ignore")
        if len(raw) < 21:
            continue
        try:
            year = int(raw[11:15]); month = int(raw[15:17])
        except ValueError:
            continue
        if year > cutoff_year:
            continue
        element = raw[17:21]
        if element not in ("TMAX", "TMIN"):
            continue
        max_day = calendar.monthrange(year, month)[1]
        for day in range(1, max_day + 1):
            pos = 21 + (day - 1) * 8
            if pos + 8 > len(raw):
                break
            try:
                value = int(raw[pos:pos+5])
            except ValueError:
                continue
            if value == -9999:
                continue
            qflag = raw[pos+6:pos+7]
            if qflag.strip():
                continue
            date_obj = dt.date(year, month, day)
            date_int = int(date_obj.strftime("%Y%m%d"))
            mmdd = date_obj.strftime("%m-%d")
            block = state[element]
            block["abs"] = update_record(block["abs"], value, date_int, element)
            block["cal"][mmdd] = update_record(block["cal"].get(mmdd), value, date_int, element)
            block["start"] = date_int if block["start"] is None else min(block["start"], date_int)
            block["end"] = date_int if block["end"] is None else max(block["end"], date_int)
            observed_years[element].add(year)
    for element in ("TMAX", "TMIN"):
        state[element]["years"] = len(observed_years[element])
    return state


def build_baseline(stations: Dict[str, StationMeta], cutoff_year: int, archive_url: str = ARCHIVE_URL) -> dict:
    log(f"Baue historischen GHCN-Basisbestand bis {cutoff_year} …")
    states = {}
    wanted = set(stations)
    seen = 0
    with http_open(archive_url, attempts=6, timeout=300) as response:
        with tarfile.open(fileobj=response, mode="r|gz") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".dly"):
                    continue
                sid = Path(member.name).stem
                if sid not in wanted:
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                state = parse_dly_station(extracted, cutoff_year)
                if state["TMAX"]["abs"] is not None or state["TMIN"]["abs"] is not None:
                    states[sid] = state
                seen += 1
                if seen % 250 == 0:
                    log(f"  {seen:,} europäische Stationsdateien verarbeitet …")
    log(f"Historischer Basisbestand fertig: {len(states):,} Stationen mit TMAX/TMIN.")
    return {
        "format_version": BASELINE_FORMAT_VERSION,
        "cutoff_year": cutoff_year,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "states": states,
    }


def load_or_build_baseline(cache_file: Path, stations: Dict[str, StationMeta], cutoff_year: int, force: bool) -> dict:
    if cache_file.exists() and not force:
        try:
            with gzip.open(cache_file, "rb") as handle:
                payload = pickle.load(handle)
            if payload.get("format_version") == BASELINE_FORMAT_VERSION and payload.get("cutoff_year") == cutoff_year:
                log(f"Verwende historischen Cache: {cache_file}")
                return payload
            log("Historischer Cache hat eine andere Version/Jahresgrenze und wird neu gebaut.")
        except Exception as exc:
            log(f"Historischer Cache konnte nicht gelesen werden ({exc}); Neuaufbau.")
    payload = build_baseline(stations, cutoff_year)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=5) as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(cache_file)
    log(f"Historischer Cache gespeichert: {cache_file} ({cache_file.stat().st_size/1024/1024:.1f} MB)")
    return payload


def parse_current_year(year: int, stations: Dict[str, StationMeta]) -> dict:
    """Return current-year observations as station -> element -> mmdd -> (value,date)."""
    url = BY_YEAR_URL.format(year=year)
    log(f"Lade laufendes GHCN-Jahr {year}: {url}")
    current: Dict[str, dict] = {}
    with http_open(url, attempts=6, timeout=240) as response:
        with gzip.GzipFile(fileobj=response) as gz:
            text = io.TextIOWrapper(gz, encoding="utf-8", errors="replace", newline="")
            reader = csv.reader(text)
            rows = 0
            kept = 0
            for row in reader:
                rows += 1
                if len(row) < 7:
                    continue
                sid, datestr, element = row[0], row[1], row[2]
                if sid not in stations or element not in ("TMAX", "TMIN"):
                    continue
                if row[5].strip():  # Q-FLAG: reject values that failed QA.
                    continue
                try:
                    value = int(row[3]); date_obj = dt.datetime.strptime(datestr, "%Y%m%d").date()
                except (ValueError, TypeError):
                    continue
                if value == -9999:
                    continue
                mmdd = date_obj.strftime("%m-%d")
                date_int = int(datestr)
                station = current.setdefault(sid, {"TMAX": {}, "TMIN": {}})
                # There should normally be one blended GHCN value per station/day/element.
                station[element][mmdd] = (value, date_int)
                kept += 1
                if rows % 1_000_000 == 0:
                    log(f"  {rows:,} Jahreszeilen gelesen, {kept:,} europäische TMAX/TMIN-Werte behalten …")
    log(f"Laufendes Jahr eingelesen: {len(current):,} europäische Stationen mit TMAX/TMIN.")
    return current


def date_str(date_int: Optional[int]) -> Optional[str]:
    if not date_int:
        return None
    s = str(int(date_int))
    if len(s) != 8:
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def record_json(record: Optional[Tuple[int, int, int]]) -> Optional[dict]:
    if record is None:
        return None
    return {"value": record[0] / 10.0, "date": date_str(record[1]), "ties": int(record[2])}


def combine_record(base: Optional[Tuple[int, int, int]], current: Optional[Tuple[int, int]], element: str):
    """Return final record, strict-new flag and delta versus pre-current baseline."""
    if current is None:
        return base, False, None
    value, date_int = current
    if base is None:
        return (value, date_int, 1), False, None  # no meaningful previous record
    if better(element, value, base[0]):
        delta = (value - base[0]) / 10.0 if element == "TMAX" else (base[0] - value) / 10.0
        return (value, date_int, 1), True, delta
    if value == base[0]:
        return (base[0], base[1], base[2] + 1), False, 0.0
    return base, False, ((value - base[0]) / 10.0 if element == "TMAX" else (base[0] - value) / 10.0)


def all_mmdd() -> List[str]:
    leap = 2024
    return [(dt.date(leap, 1, 1) + dt.timedelta(days=i)).strftime("%m-%d") for i in range(366)]


def merge_and_write(output_dir: Path, stations: Dict[str, StationMeta], baseline: dict, current: dict, current_year: int) -> None:
    states: Dict[str, dict] = baseline["states"]
    eligible_ids = sorted(set(states) | set(current))
    station_rows = []

    for sid in eligible_ids:
        meta = stations.get(sid)
        if meta is None:
            continue
        base_state = states.get(sid, empty_state())
        cur_state = current.get(sid, {"TMAX": {}, "TMIN": {}})
        element_summary = {}
        new_counts = {}
        last_new = {}

        for element, pack_key in (("TMAX", "tmax"), ("TMIN", "tmin")):
            base_block = base_state[element]
            cur_values = cur_state.get(element, {})
            cur_abs = None
            for mmdd, obs in cur_values.items():
                if cur_abs is None or better(element, obs[0], cur_abs[0]):
                    cur_abs = obs
            final_abs, new_abs, abs_delta = combine_record(base_block.get("abs"), cur_abs, element)
            years = int(base_block.get("years", 0)) + (1 if cur_values else 0)
            start = base_block.get("start")
            end = base_block.get("end")
            if cur_values:
                cur_dates = [d for _, d in cur_values.values()]
                start = min([x for x in [start, min(cur_dates)] if x is not None])
                end = max([x for x in [end, max(cur_dates)] if x is not None])
            element_summary[element] = {
                "record": record_json(final_abs),
                "previous": record_json(base_block.get("abs")) if new_abs else None,
                "new_absolute_current_year": bool(new_abs),
                "new_absolute_delta": round(abs_delta, 1) if new_abs and abs_delta is not None else None,
                "start": date_str(start),
                "end": date_str(end),
                "years": years,
            }

            new_count = 0
            last_new_date = None
            cal_base = base_block.get("cal", {})
            for mmdd in set(cal_base) | set(cur_values):
                b = cal_base.get(mmdd)
                c = cur_values.get(mmdd)
                _final, is_new, _delta = combine_record(b, c, element)
                if is_new:
                    new_count += 1
                    last_new_date = c[1]
            new_counts[element] = new_count
            last_new[element] = date_str(last_new_date)

        if not element_summary["TMAX"]["record"] and not element_summary["TMIN"]["record"]:
            continue
        station_rows.append({
            "id": meta.id,
            "name": meta.name,
            "country_code": meta.country_code,
            "country": meta.country,
            "lat": round(meta.lat, 4),
            "lon": round(meta.lon, 4),
            "elevation": meta.elev,
            "source": SOURCE_NAME,
            "tmax": element_summary["TMAX"],
            "tmin": element_summary["TMIN"],
            "new_current_year": {
                "tmax_calendar": new_counts["TMAX"],
                "tmin_calendar": new_counts["TMIN"],
                "tmax_last": last_new["TMAX"],
                "tmin_last": last_new["TMIN"],
            },
        })

    # Build compact day packs after the final station order is known.
    daypacks = {mmdd: {"tmax": [], "tmin": []} for mmdd in all_mmdd()}
    for idx, row in enumerate(station_rows):
        sid = row["id"]
        base_state = states.get(sid, empty_state())
        cur_state = current.get(sid, {"TMAX": {}, "TMIN": {}})
        for element, pack_key in (("TMAX", "tmax"), ("TMIN", "tmin")):
            bcal = base_state[element].get("cal", {})
            ccal = cur_state.get(element, {})
            for mmdd in set(bcal) | set(ccal):
                b = bcal.get(mmdd); c = ccal.get(mmdd)
                final, is_new, delta = combine_record(b, c, element)
                if final is None:
                    continue
                daypacks[mmdd][pack_key].append([
                    idx, final[0], final[1],
                    b[0] if b else None, b[1] if b else None,
                    c[0] if c else None, c[1] if c else None,
                    1 if is_new else 0,
                    int(round(delta * 10)) if delta is not None else None,
                ])

    output_dir.mkdir(parents=True, exist_ok=True)
    cal_dir = output_dir / "calendar"
    cal_dir.mkdir(parents=True, exist_ok=True)

    countries = sorted({row["country"] for row in station_rows})
    payload = {
        "payload_version": PAYLOAD_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "current_year": current_year,
        "historical_through": current_year - 1,
        "source": SOURCE_NAME,
        "source_url": BASE,
        "quality_rule": "Nur TMAX/TMIN mit leerem GHCN Q-FLAG; Werte in 0,1 °C eingelesen.",
        "history_scope": "vollständige verfügbare GHCN-Daily-Messreihe vor dem laufenden Jahr + laufendes Jahr separat",
        "station_count": len(station_rows),
        "country_count": len(countries),
        "countries": countries,
        "calendar_url_pattern": "europe_stations/calendar/{mmdd}.json.gz",
        "calendar_schema": ["station_index", "record_tenths_c", "record_date_yyyymmdd", "previous_tenths_c", "previous_date_yyyymmdd", "current_tenths_c", "current_date_yyyymmdd", "strict_new_record", "difference_tenths_c"],
        "stations": station_rows,
    }
    (output_dir / "index.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    for mmdd, pack in daypacks.items():
        obj = {
            "payload_version": PAYLOAD_VERSION,
            "mmdd": mmdd,
            "current_year": current_year,
            "tmax": pack["tmax"],
            "tmin": pack["tmin"],
        }
        target = cal_dir / f"{mmdd}.json.gz"
        with gzip.open(target, "wt", encoding="utf-8", compresslevel=7) as handle:
            json.dump(obj, handle, ensure_ascii=False, separators=(",", ":"))

    total_gz = sum(p.stat().st_size for p in cal_dir.glob("*.json.gz"))
    log(f"Frontend-Daten geschrieben: {len(station_rows):,} Stationen, 366 Tagesarchive, {total_gz/1024/1024:.1f} MB Tagesarchive komprimiert.")


def self_test() -> None:
    # Minimal DLY line: verifies fixed-width value/QFLAG parsing and record comparison.
    sid = "GM000001234"
    prefix = f"{sid}202501TMAX"
    chars = list(prefix + ("-9999   " * 31))
    # day 1 = 123 tenths C, blank qflag
    chars[21:29] = list("  123   ")
    line = "".join(chars)
    state = parse_dly_station(io.BytesIO((line + "\n").encode("ascii")), 2025)
    assert state["TMAX"]["abs"][0] == 123
    assert state["TMAX"]["cal"]["01-01"][0] == 123
    final, new, delta = combine_record((123, 20250101, 1), (130, 20260101), "TMAX")
    assert new and final[0] == 130 and abs(delta - 0.7) < 1e-9
    final, new, delta = combine_record((-50, 20250101, 1), (-60, 20260101), "TMIN")
    assert new and final[0] == -60 and abs(delta - 1.0) < 1e-9
    print("Self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="europe_stations", help="Frontend output directory")
    parser.add_argument("--cache-dir", default=".cache/europe-stations", help="Historical baseline cache")
    parser.add_argument("--force-baseline", action="store_true", help="Ignore an existing historical cache")
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test(); return 0

    current_year = args.year
    cutoff_year = current_year - 1
    countries = parse_countries(read_url_text(COUNTRIES_URL))
    stations = parse_stations(read_url_text(STATIONS_URL), countries)
    log(f"Europäische Stationsmetadaten im Kartenfenster: {len(stations):,}")
    if not stations:
        raise RuntimeError("Keine europäischen GHCN-Stationen gefunden.")

    cache_file = Path(args.cache_dir) / f"ghcn_europe_baseline_through_{cutoff_year}_v{BASELINE_FORMAT_VERSION}.pkl.gz"
    baseline = load_or_build_baseline(cache_file, stations, cutoff_year, args.force_baseline)
    current = parse_current_year(current_year, stations)
    merge_and_write(Path(args.output), stations, baseline, current, current_year)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        raise
