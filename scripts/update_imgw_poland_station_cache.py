#!/usr/bin/env python3
"""Build a resumable IMGW-PIB Poland daily temperature cache.

Official source: IMGW-PIB public measurement/observation archive,
``dane_meteorologiczne/dobowe/klimat``.  The full ``k_d`` CSV inside each
ZIP contains daily TMAX/TMIN fields.  The reduced ``k_d_t`` product contains
TEMP but no TMAX/TMIN and must therefore not be used for station records.

Historical layout:

* 1951-2000: annual ZIPs inside five-year directories
* 2001+: monthly ZIPs inside year directories

Every successfully parsed ZIP is persisted as a small shard. A failed first
pass therefore never destroys previous progress. The final baseline covers
all available TMAX/TMIN observations through ``current_year - 1``.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import json
import math
import pickle
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import update_europe_station_records as core

BASE = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_meteorologiczne"
DAILY = f"{BASE}/dobowe/klimat"
STATION_CATALOG_URL = f"{BASE}/wykaz_stacji.csv"

# IMPORTANT: k_d is the full daily climate product. k_d_t only contains TEMP
# and does not provide TMAX/TMIN.
HEADER_NAME = "k_d_nagłówek.csv"
HEADER_URL = DAILY + "/" + urllib.parse.quote(HEADER_NAME)

PUBLIC_URL = "https://danepubliczne.imgw.pl/"
SOURCE = "IMGW-PIB"

# V2 deliberately invalidates shards/baselines created with the former k_d_t
# parser so they cannot be mixed with correctly parsed k_d data.
BASELINE_FORMAT_VERSION = 2
RESOURCE_FORMAT_VERSION = 2
START_YEAR = 1951


def log(msg: str) -> None:
    print(msg, flush=True)


def read_bytes(url: str, attempts: int = 4, timeout: int = 120) -> bytes:
    last = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "climate-dashboard-poland/2.0 (+GitHub Actions)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last = exc
            if attempt >= attempts:
                break
            time.sleep(min(3 * attempt, 12))
    raise RuntimeError(f"IMGW Download fehlgeschlagen: {url}: {last}")


def decode_polish(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1250", "iso-8859-2", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1250", errors="replace")


def norm(text: object) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:5])
    counts = {delimiter: sample.count(delimiter) for delimiter in (";", ",", "\t")}
    return max(counts, key=counts.get)


def parse_float(value: object) -> Optional[float]:
    text = str(value or "").strip().replace(" ", "")
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def parse_coord(value: object, is_lat: bool) -> Optional[float]:
    number = parse_float(value)
    limit = 90 if is_lat else 180
    if number is not None and abs(number) <= limit:
        return number

    text = str(value or "").strip().replace(",", ".")
    numbers = [float(v) for v in re.findall(r"[-+]?\d+(?:\.\d+)?", text)]
    if not numbers:
        return None
    sign = -1 if any(c in text.upper() for c in ("S", "W")) or text.lstrip().startswith("-") else 1
    degrees = abs(numbers[0])
    minutes = numbers[1] if len(numbers) > 1 else 0
    seconds = numbers[2] if len(numbers) > 2 else 0
    result = sign * (degrees + minutes / 60 + seconds / 3600)
    return result if abs(result) <= limit else None


def first_index(headers: List[str], predicates: Iterable) -> Optional[int]:
    normalized = [norm(header) for header in headers]
    for predicate in predicates:
        for index, header in enumerate(normalized):
            if predicate(header):
                return index
    return None


def _exact_index(normalized_headers: List[str], *names: str) -> Optional[int]:
    wanted = {norm(name) for name in names}
    for index, header in enumerate(normalized_headers):
        if header in wanted:
            return index
    return None


def load_temperature_schema() -> dict:
    text = decode_polish(read_bytes(HEADER_URL))
    delimiter = detect_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        raise RuntimeError("IMGW k_d Headerdatei ist leer.")

    headers = [value.strip() for value in rows[0] if str(value).strip()]
    if len(headers) < 7:
        # Some IMGW header files are one-column lists. Accept that form too.
        headers = [row[0].strip() for row in rows if row and row[0].strip()]

    normalized = [norm(value) for value in headers]

    def semantic(words: List[str]) -> Optional[int]:
        for index, header in enumerate(normalized):
            if all(word in header for word in words):
                return index
        return None

    # The official short k_d header currently is:
    # NSP,POST,ROK,MC,DZ,TMAX,WTMAX,TMIN,WTMIN,...
    # Keep both exact short-name recognition and long-name fallbacks so the
    # parser remains robust if IMGW changes the header presentation.
    schema = {
        "headers": headers,
        "station": _exact_index(normalized, "NSP"),
        "name": _exact_index(normalized, "POST"),
        "year": _exact_index(normalized, "ROK"),
        "month": _exact_index(normalized, "MC"),
        "day": _exact_index(normalized, "DZ"),
        "tmax": _exact_index(normalized, "TMAX"),
        "tmin": _exact_index(normalized, "TMIN"),
    }

    if schema["station"] is None:
        schema["station"] = semantic(["kod", "stacji"])
    if schema["name"] is None:
        schema["name"] = semantic(["nazwa", "stacji"])
    if schema["year"] is None:
        schema["year"] = semantic(["rok"])
    if schema["month"] is None:
        schema["month"] = semantic(["miesiac"])
    if schema["day"] is None:
        schema["day"] = semantic(["dzien"])

    if schema["tmax"] is None:
        schema["tmax"] = next(
            (
                index
                for index, header in enumerate(normalized)
                if "status" not in header
                and "temperatur" in header
                and ("maks" in header or "max" in header or "tmax" in header)
            ),
            None,
        )
    if schema["tmin"] is None:
        schema["tmin"] = next(
            (
                index
                for index, header in enumerate(normalized)
                if "status" not in header
                and "temperatur" in header
                and ("min" in header or "tmin" in header)
            ),
            None,
        )

    # Positional fallback only for identifiers. TMAX/TMIN must be recognized
    # explicitly so a wrong IMGW product can never silently be interpreted.
    for key, fallback in (("station", 0), ("name", 1), ("year", 2), ("month", 3), ("day", 4)):
        if schema[key] is None and len(headers) > fallback:
            schema[key] = fallback

    if schema["tmax"] is None or schema["tmin"] is None:
        raise RuntimeError(f"IMGW k_d Header ohne erkennbare TMAX/TMIN-Spalten: {headers}")

    return schema


def parse_station_catalog() -> Dict[str, core.StationMeta]:
    text = decode_polish(read_bytes(STATION_CATALOG_URL))
    delimiter = detect_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        raise RuntimeError("IMGW Stationsverzeichnis ist leer.")

    headers = [value.strip() for value in rows[0]]
    normalized = [norm(value) for value in headers]

    def find_any(groups: List[Tuple[str, ...]]) -> Optional[int]:
        for group in groups:
            for index, header in enumerate(normalized):
                if all(word in header for word in group):
                    return index
        return None

    i_code = find_any([("kod", "stacji"), ("kod",), ("id",)])
    i_name = find_any([("nazwa", "stacji"), ("nazwa",), ("station", "name")])
    i_lat = find_any([("szerokosc",), ("latitude",), ("lat",)])
    i_lon = find_any([("dlugosc",), ("longitude",), ("lon",)])
    i_elev = find_any([("wysokosc",), ("elevation",), ("altitude",)])

    if i_code is None or i_name is None or i_lat is None or i_lon is None:
        raise RuntimeError(
            f"IMGW wykaz_stacji.csv ohne erkennbare Code/Name/Koordinaten-Spalten: {headers}"
        )

    output: Dict[str, core.StationMeta] = {}
    for row in rows[1:]:
        if max(i_code, i_name, i_lat, i_lon) >= len(row):
            continue
        raw = row[i_code].strip().replace(".0", "")
        if not raw:
            continue
        lat = parse_coord(row[i_lat], True)
        lon = parse_coord(row[i_lon], False)
        if lat is None or lon is None or not (48.5 <= lat <= 55.5 and 13.5 <= lon <= 24.5):
            continue
        elev = parse_float(row[i_elev]) if i_elev is not None and i_elev < len(row) else None
        name = row[i_name].strip() or raw
        sid = f"IMGW:{raw}"
        output[sid] = core.StationMeta(
            sid,
            lat,
            lon,
            None if elev is None or elev < -100 else round(elev, 1),
            name,
            "PL",
            "Polen",
            SOURCE,
            "IMGW-PIB tägliche Klimadaten k_d: veröffentlichte TMAX/TMIN-Werte; nichtnumerische/fehlende Werte werden verworfen.",
        )

    if not output:
        raise RuntimeError("Keine polnischen IMGW-Stationen mit Koordinaten aus wykaz_stacji.csv gelesen.")
    return output


def resource_urls(cutoff_year: int) -> List[dict]:
    output = []
    for year in range(START_YEAR, cutoff_year + 1):
        if year <= 2000:
            first = START_YEAR + ((year - START_YEAR) // 5) * 5
            last = first + 4
            url = f"{DAILY}/{first}_{last}/{year}_k.zip"
            output.append({"year": year, "month": None, "url": url, "key": f"{year}"})
        else:
            for month in range(1, 13):
                url = f"{DAILY}/{year}/{year}_{month:02d}_k.zip"
                output.append(
                    {"year": year, "month": month, "url": url, "key": f"{year}_{month:02d}"}
                )
    return output


def current_resource_urls(year: int) -> List[dict]:
    index_url = f"{DAILY}/{year}/"
    html = decode_polish(read_bytes(index_url, attempts=3, timeout=90))
    months = sorted(
        {
            int(value)
            for value in re.findall(rf"{year}_(\d{{2}})_k\.zip", html)
            if 1 <= int(value) <= 12
        }
    )
    return [
        {
            "year": year,
            "month": month,
            "url": f"{DAILY}/{year}/{year}_{month:02d}_k.zip",
            "key": f"{year}_{month:02d}",
        }
        for month in months
    ]


def partial_state() -> dict:
    return core.mf_empty_partial_state()


def temp_tenths(value: object) -> Optional[int]:
    number = parse_float(value)
    if number is None or number < -70 or number > 60:
        return None
    return int(round(number * 10))


def _daily_members(zf: zipfile.ZipFile) -> List[str]:
    """Return only full k_d CSVs, explicitly excluding reduced k_d_t files."""
    members = []
    for member in zf.namelist():
        basename = Path(member).name.lower()
        if not basename.endswith(".csv"):
            continue
        if basename.startswith("k_d_t_"):
            continue
        if basename.startswith("k_d_"):
            members.append(member)
    return members


def parse_zip(
    data: bytes,
    schema: dict,
    *,
    cutoff_year: Optional[int] = None,
    exact_year: Optional[int] = None,
):
    partial: Dict[str, dict] = {}
    current: Dict[str, dict] = {}
    names: Dict[str, str] = {}

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise RuntimeError("ungültiges ZIP") from exc

    members = _daily_members(zf)
    if not members:
        raise RuntimeError(f"IMGW ZIP enthält keine vollständige k_d CSV: {zf.namelist()[:20]}")

    indexes = [schema[key] for key in ("station", "name", "year", "month", "day", "tmax", "tmin")]
    max_index = max(index for index in indexes if index is not None)

    for member in members:
        text = decode_polish(zf.read(member))
        delimiter = detect_delimiter(text)
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            if len(row) <= max_index:
                continue

            raw = row[schema["station"]].strip().replace(".0", "")
            if not raw:
                continue

            try:
                year = int(float(row[schema["year"]]))
                month = int(float(row[schema["month"]]))
                day = int(float(row[schema["day"]]))
                date = dt.date(year, month, day)
            except (ValueError, TypeError):
                continue

            if cutoff_year is not None and year > cutoff_year:
                continue
            if exact_year is not None and year != exact_year:
                continue

            sid = f"IMGW:{raw}"
            names[sid] = row[schema["name"]].strip() if schema["name"] is not None else raw
            date_int = int(date.strftime("%Y%m%d"))
            mmdd = date.strftime("%m-%d")

            for field, element in (("tmax", "TMAX"), ("tmin", "TMIN")):
                value = temp_tenths(row[schema[field]])
                if value is None:
                    continue

                if exact_year is not None:
                    station = current.setdefault(sid, {"TMAX": {}, "TMIN": {}})
                    old = station[element].get(mmdd)
                    if old is None or core.better(element, value, old[0]):
                        station[element][mmdd] = (value, date_int)
                else:
                    station = partial.setdefault(sid, partial_state())
                    block = station[element]
                    block["abs"] = core.update_record(block.get("abs"), value, date_int, element)
                    block["cal"][mmdd] = core.update_record(
                        block["cal"].get(mmdd), value, date_int, element
                    )
                    block["start"] = date_int if block["start"] is None else min(block["start"], date_int)
                    block["end"] = date_int if block["end"] is None else max(block["end"], date_int)
                    block["year_set"].add(year)

    return partial, current, names


def resource_dir(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"imgw_poland_resources_through_{cutoff_year}_v{RESOURCE_FORMAT_VERSION}"


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"imgw_poland_daily_baseline_through_{cutoff_year}_v{BASELINE_FORMAT_VERSION}.pkl.gz"


def shard_path(cache_dir: Path, cutoff_year: int, key: str) -> Path:
    return resource_dir(cache_dir, cutoff_year) / f"{key}.pkl.gz"


def save_shard(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=5) as handle:
        pickle.dump(payload, handle, pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def load_shard(path: Path, cutoff_year: int) -> Optional[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with gzip.open(path, "rb") as handle:
            payload = pickle.load(handle)
        if payload.get("format_version") != RESOURCE_FORMAT_VERSION:
            return None
        if payload.get("cutoff_year") != cutoff_year:
            return None
        return payload
    except Exception:
        return None


def merge_partial(target: dict, source: dict) -> None:
    core.merge_mf_partial(target, source)


def process_resource(
    resource: dict,
    schema: dict,
    cache_dir: Path,
    cutoff_year: int,
    force: bool = False,
):
    path = shard_path(cache_dir, cutoff_year, resource["key"])
    if not force:
        cached = load_shard(path, cutoff_year)
        if cached is not None:
            return cached, "cache", None

    try:
        data = read_bytes(resource["url"], attempts=3, timeout=120)
        partial, _current, names = parse_zip(data, schema, cutoff_year=cutoff_year)
        payload = {
            "format_version": RESOURCE_FORMAT_VERSION,
            "cutoff_year": cutoff_year,
            "key": resource["key"],
            "url": resource["url"],
            "partial": partial,
            "names": names,
        }
        save_shard(path, payload)
        return payload, "download", None
    except Exception as exc:
        return None, "error", str(exc)


def build_baseline(
    current_year: int,
    cache_dir: Path,
    workers: int = 8,
    force: bool = False,
) -> dict:
    cutoff = current_year - 1
    cache_dir.mkdir(parents=True, exist_ok=True)

    schema = load_temperature_schema()
    log(
        "IMGW k_d Schema: "
        f"TMAX={schema['tmax']} ({schema['headers'][schema['tmax']]}), "
        f"TMIN={schema['tmin']} ({schema['headers'][schema['tmin']]})."
    )
    stations_catalog = parse_station_catalog()
    resources = resource_urls(cutoff)

    log(f"IMGW-PIB Stationsverzeichnis: {len(stations_catalog):,} Stationen mit Koordinaten.")
    log(
        f"Historischer Plan {START_YEAR}-{cutoff}: {len(resources):,} ZIP-Ressourcen; "
        f"{workers} parallele Downloads; jede erfolgreiche ZIP wird einzeln gecacht."
    )

    partial: Dict[str, dict] = {}
    names: Dict[str, str] = {}
    failures = []
    counts = {"cache": 0, "download": 0, "error": 0}
    done = 0

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(process_resource, resource, schema, cache_dir, cutoff, force): resource
            for resource in resources
        }
        for future in as_completed(futures):
            resource = futures[future]
            payload, mode, error = future.result()
            done += 1
            counts[mode] += 1

            if payload:
                merge_partial(partial, payload.get("partial", {}))
                names.update(payload.get("names", {}))
            else:
                failures.append({"key": resource["key"], "url": resource["url"], "error": error})
                log(f"FEHLER IMGW {resource['key']}: {error}")

            if done == 1 or done % 25 == 0 or done == len(resources):
                log(
                    f"  IMGW historical: {done}/{len(resources)} ZIPs | "
                    f"Cache {counts['cache']} | neu {counts['download']} | "
                    f"fehlerhaft {counts['error']} | {len(partial):,} Stationscodes …"
                )

    states_all = core.finalize_mf_states(partial)
    states = {
        sid: state
        for sid, state in states_all.items()
        if sid in stations_catalog
        and (state["TMAX"]["abs"] is not None or state["TMIN"]["abs"] is not None)
    }
    stations = {sid: stations_catalog[sid] for sid in states}
    unmatched = len(states_all) - len(states)
    complete = not failures

    status = {
        "source": SOURCE,
        "cutoff_year": cutoff,
        "resource_count": len(resources),
        "available": len(resources) - len(failures),
        "missing": len(failures),
        "complete": complete,
        "station_count": len(states),
        "unmatched_station_codes": unmatched,
        "failures": failures,
    }
    (cache_dir / f"imgw_poland_status_through_{cutoff}.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if complete:
        payload = {
            "format_version": BASELINE_FORMAT_VERSION,
            "cutoff_year": cutoff,
            "states": states,
            "stations": stations,
            "resource_count": len(resources),
            "source": SOURCE,
        }
        path = baseline_path(cache_dir, cutoff)
        with gzip.open(path, "wb", compresslevel=5) as handle:
            pickle.dump(payload, handle, pickle.HIGHEST_PROTOCOL)
        log(
            f"IMGW POLAND OK: {len(states):,} Stationsreihen mit TMAX/TMIN bis {cutoff} | "
            f"{len(resources)} historische ZIP-Ressourcen."
        )
        return payload

    log(
        f"IMGW POLAND noch unvollständig: {len(failures)} von {len(resources)} ZIPs fehlen. "
        "Erfolgreiche Einzelcaches bleiben erhalten."
    )
    return {
        "format_version": BASELINE_FORMAT_VERSION,
        "cutoff_year": cutoff,
        "states": states,
        "stations": stations,
        "resource_count": len(resources),
        "complete": False,
    }


def load_baseline(cache_dir: Path, cutoff_year: int) -> dict:
    path = baseline_path(cache_dir, cutoff_year)
    if not path.exists():
        raise RuntimeError(f"IMGW-Polen-Cache fehlt: {path}")
    with gzip.open(path, "rb") as handle:
        payload = pickle.load(handle)
    if (
        payload.get("format_version") != BASELINE_FORMAT_VERSION
        or payload.get("cutoff_year") != cutoff_year
        or not payload.get("states")
    ):
        raise RuntimeError("IMGW-Polen-Cache ungültig oder leer.")
    return payload


def parse_current_year(
    year: int,
    stations: Dict[str, core.StationMeta],
    workers: int = 6,
):
    schema = load_temperature_schema()
    resources = current_resource_urls(year)
    if not resources:
        raise RuntimeError(f"IMGW hat für {year} noch keine täglichen Klimadateien veröffentlicht.")

    output: Dict[str, dict] = {}
    failures = []

    def one(resource: dict):
        data = read_bytes(resource["url"], attempts=3, timeout=120)
        _partial, current, _names = parse_zip(data, schema, exact_year=year)
        return current

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(one, resource): resource for resource in resources}
        for future in as_completed(futures):
            resource = futures[future]
            try:
                current = future.result()
                for sid, state in current.items():
                    if sid not in stations:
                        continue
                    destination = output.setdefault(sid, {"TMAX": {}, "TMIN": {}})
                    for element in ("TMAX", "TMIN"):
                        destination[element].update(state.get(element, {}))
            except Exception as exc:
                failures.append((resource["key"], str(exc)))

    if failures:
        log(
            f"WARNUNG IMGW current {year}: {len(failures)} Monatsdateien fehlgeschlagen: "
            f"{failures[:5]}"
        )
    latest = max(resource["month"] for resource in resources)
    log(
        f"IMGW {year}: {len(output):,} Stationen mit laufenden TMAX/TMIN-Daten aus "
        f"{len(resources)} veröffentlichten Monats-ZIPs (bis Monat {latest:02d})."
    )
    return output, latest


def self_test() -> None:
    # This deliberately mirrors the official compact k_d header names and also
    # includes a k_d_t CSV in the same archive. The parser must use only k_d.
    headers = [
        "NSP",
        "POST",
        "ROK",
        "MC",
        "DZ",
        "TMAX",
        "WTMAX",
        "TMIN",
        "WTMIN",
        "STD",
        "WSTD",
        "TMNG",
        "WTMNG",
        "SMDB",
        "WSMDB",
        "ROOP",
        "PKSN",
        "WPKSN",
    ]
    schema = {
        "headers": headers,
        "station": 0,
        "name": 1,
        "year": 2,
        "month": 3,
        "day": 4,
        "tmax": 5,
        "tmin": 7,
    }
    csv_text = (
        '123456789,"TEST",2025,7,1,35.2,,18.1,,,,,,,,,,\n'
        '123456789,"TEST",2025,7,2,36.4,,17.5,,,,,,,,,,\n'
    )
    reduced_text = '123456789,"TEST",2025,7,1,99.9,,,,,,,,\n'

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("k_d_2025.csv", csv_text.encode("cp1250"))
        archive.writestr("k_d_t_2025.csv", reduced_text.encode("cp1250"))

    partial, current, names = parse_zip(buffer.getvalue(), schema, cutoff_year=2025)
    sid = "IMGW:123456789"
    assert partial[sid]["TMAX"]["abs"][0] == 364
    assert partial[sid]["TMIN"]["abs"][0] == 175
    assert names[sid] == "TEST" and not current

    urls = resource_urls(2001)
    assert urls[0]["url"].endswith("1951_1955/1951_k.zip")
    assert urls[-1]["url"].endswith("2001/2001_12_k.zip")
    print("IMGW Poland k_d self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--cache-dir", default=".cache/europe-stations")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    log("=== IMGW POLAND ONLY BASELINE ===")
    log("Quelle: IMGW-PIB tägliche Klimadaten k_d; nur Polen, keine anderen Länder werden bearbeitet.")
    build_baseline(args.year, Path(args.cache_dir), workers=args.workers, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
