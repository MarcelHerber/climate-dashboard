#!/usr/bin/env python3
"""Build compact European station-record datasets for the static Climate Dashboard.

Stations-V4 architecture
------------------------
* Germany: DWD CDC daily KL data are authoritative for the dashboard module.
  Historical *_hist.zip files build a cached DWD baseline; *_akt.zip files
  supply the current calendar year.
* France: official Météo-France daily climatological CSV.gz resources from
  meteo.data.gouv.fr/data.gouv.fr are authoritative. Both the principal and
  complementary station datasets are read; TX/TN are used.
* Rest of Europe: NOAA/NCEI GHCN-Daily remains the fallback/base source.
  Germany and France are deliberately removed from GHCN to avoid duplicates.
* Frontend contract stays compatible with Stations-V2:
    europe_stations/index.json
    europe_stations/calendar/MM-DD.json.gz

The large GHCN archive is streamed and cached. DWD and Météo-France historical
files are only needed when their separate baseline caches are missing or explicitly
rebuilt.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import gzip
import html
import io
import json
import math
import os
import pickle
import re
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

GHCN_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
STATIONS_URL = f"{GHCN_BASE}/ghcnd-stations.txt"
COUNTRIES_URL = f"{GHCN_BASE}/ghcnd-countries.txt"
ARCHIVE_URL = f"{GHCN_BASE}/ghcnd_all.tar.gz"
BY_YEAR_URL = f"{GHCN_BASE}/by_year/{{year}}.csv.gz"

DWD_BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl"
DWD_HIST = f"{DWD_BASE}/historical/"
DWD_RECENT = f"{DWD_BASE}/recent/"
DWD_STATIONS_URL = f"{DWD_HIST}KL_Tageswerte_Beschreibung_Stationen.txt"

MF_DATASET_API = "https://www.data.gouv.fr/api/1/datasets/donnees-climatologiques-de-base-quotidiennes/"
MF_COMP_DATASET_API = "https://www.data.gouv.fr/api/1/datasets/donnees-climatologiques-de-base-quotidiennes-stations-complementaires/"
MF_PUBLIC_BASE = "https://meteo.data.gouv.fr/datasets/donnees-climatologiques-de-base-quotidiennes/"

PAYLOAD_VERSION = 4
GHCN_BASELINE_FORMAT_VERSION = 2
DWD_BASELINE_FORMAT_VERSION = 1
MF_BASELINE_FORMAT_VERSION = 1
GHCN_SOURCE = "GHCN-Daily"
DWD_SOURCE = "DWD CDC"
MF_SOURCE = "Météo-France"

# Metropolitan departments. Department 20 is kept as a compatibility fallback
# for older Corsica resource naming; current resources normally use 2A/2B.
MF_METRO_DEPTS = ({f"{i:02d}" for i in range(1, 96) if i != 20} | {"20", "2A", "2B"})

# GHCN FIPS country codes. Germany (GM) and France (FR) remain listed for
# parsing compatibility, but are removed before baseline/current processing.
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

LAT_MIN, LAT_MAX = 34.0, 72.5
LON_MIN, LON_MAX = -25.5, 45.5


def log(message: str) -> None:
    print(message, flush=True)


def http_open(url: str, attempts: int = 5, timeout: int = 180):
    headers = {"User-Agent": "climate-dashboard-stations/4.0 (+GitHub Actions)"}
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            return urllib.request.urlopen(req, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            wait = min(10 * attempt, 45)
            log(f"HTTP-Fehler für {url} (Versuch {attempt}/{attempts}): {exc}; neuer Versuch in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Download fehlgeschlagen: {url}: {last_error}")


def read_url_bytes(url: str, attempts: int = 5, timeout: int = 180) -> bytes:
    with http_open(url, attempts=attempts, timeout=timeout) as response:
        return response.read()


def read_url_text(url: str, encoding: str = "utf-8") -> str:
    return read_url_bytes(url).decode(encoding, errors="replace")


def decode_text_smart(data: bytes) -> str:
    """Prefer UTF-8, fall back to Latin-1 for older DWD metadata files."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


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
    source: str
    quality_rule: str


def parse_ghcn_stations(text: str, countries: Dict[str, str]) -> Dict[str, StationMeta]:
    stations: Dict[str, StationMeta] = {}
    for raw in text.splitlines():
        if len(raw) < 42:
            continue
        sid = raw[0:11].strip()
        code = sid[:2]
        if code not in EUROPE_CODES or code in {"GM", "FR"}:  # DWD/Météo-France replace Germany/France in V4.
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
        stations[sid] = StationMeta(
            sid, lat, lon, elev, name, code, country, GHCN_SOURCE,
            "GHCN-Daily: nur TMAX/TMIN mit leerem Q-FLAG; Werte mit gesetztem Qualitätsflag werden verworfen.",
        )
    return stations


def parse_dwd_stations(text: str) -> Dict[str, StationMeta]:
    """Parse DWD KL_Tageswerte_Beschreibung_Stationen.txt.

    The file is fixed-width-ish but station names contain spaces. Splitting into
    at most 8 columns is robust across the current DWD station list layout:
    Stations_id von_datum bis_datum Stationshoehe geoBreite geoLaenge Stationsname Bundesland
    """
    stations: Dict[str, StationMeta] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("stations") or set(line) <= {"-", " "}:
            continue
        m = re.match(r"^(\d+)\s+(\d{8})\s+(\d{8})\s+(-?\d+(?:[.,]\d+)?)\s+(-?\d+(?:[.,]\d+)?)\s+(-?\d+(?:[.,]\d+)?)\s+(.+)$", line)
        if not m:
            continue
        sid_raw = m.group(1).zfill(5)
        try:
            elev = float(m.group(4).replace(",", "."))
            lat = float(m.group(5).replace(",", "."))
            lon = float(m.group(6).replace(",", "."))
        except ValueError:
            continue
        remainder = m.group(7).strip()
        # Station name and Bundesland are separated by a wide whitespace field.
        # If that spacing was normalized upstream, strip a known Bundesland suffix.
        name = re.split(r"\s{2,}", remainder, maxsplit=1)[0].strip()
        if name == remainder:
            states = ["Baden-Württemberg","Bayern","Berlin","Brandenburg","Bremen","Hamburg","Hessen","Mecklenburg-Vorpommern","Niedersachsen","Nordrhein-Westfalen","Rheinland-Pfalz","Saarland","Sachsen","Sachsen-Anhalt","Schleswig-Holstein","Thüringen"]
            for state_name in states:
                suffix = " " + state_name
                if name.endswith(suffix):
                    name = name[:-len(suffix)].rstrip(); break
        name = name or f"DWD {sid_raw}"
        sid = f"DWD:{sid_raw}"
        stations[sid] = StationMeta(
            sid, lat, lon, None if elev <= -999 else round(elev, 1), name,
            "DE", "Deutschland", DWD_SOURCE,
            "DWD CDC Tageswerte KL: TXK/TNK; DWD-Fehlwerte (-999) werden verworfen.",
        )
    return stations


def better(element: str, new_value: int, old_value: Optional[int]) -> bool:
    if old_value is None:
        return True
    return new_value > old_value if element == "TMAX" else new_value < old_value


def empty_state() -> dict:
    return {
        "TMAX": {"abs": None, "cal": {}, "start": None, "end": None, "years": 0},
        "TMIN": {"abs": None, "cal": {}, "start": None, "end": None, "years": 0},
    }


def update_record(record: Optional[Tuple[int, int, int]], value: int, date_int: int, element: str) -> Tuple[int, int, int]:
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


def build_ghcn_baseline(stations: Dict[str, StationMeta], cutoff_year: int, archive_url: str = ARCHIVE_URL) -> dict:
    log(f"Baue historischen GHCN-Basisbestand (ohne Deutschland/Frankreich) bis {cutoff_year} …")
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
                    log(f"  {seen:,} europäische GHCN-Stationsdateien verarbeitet …")
    log(f"GHCN-Basisbestand fertig: {len(states):,} Stationen (Deutschland/Frankreich ausgeschlossen).")
    return {
        "format_version": GHCN_BASELINE_FORMAT_VERSION,
        "cutoff_year": cutoff_year,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "states": states,
    }


def load_or_build_ghcn_baseline(cache_file: Path, stations: Dict[str, StationMeta], cutoff_year: int, force: bool) -> dict:
    if cache_file.exists() and not force:
        try:
            with gzip.open(cache_file, "rb") as handle:
                payload = pickle.load(handle)
            if payload.get("format_version") == GHCN_BASELINE_FORMAT_VERSION and payload.get("cutoff_year") == cutoff_year:
                # A V2 cache may still contain German states. That is harmless:
                # only IDs present in the V3 GHCN metadata set are used later.
                log(f"Verwende historischen GHCN-Cache: {cache_file}")
                return payload
        except Exception as exc:
            log(f"GHCN-Cache konnte nicht gelesen werden ({exc}); Neuaufbau.")
    payload = build_ghcn_baseline(stations, cutoff_year)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=5) as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(cache_file)
    log(f"GHCN-Cache gespeichert: {cache_file} ({cache_file.stat().st_size/1024/1024:.1f} MB)")
    return payload


def parse_current_ghcn_year(year: int, stations: Dict[str, StationMeta]) -> dict:
    url = BY_YEAR_URL.format(year=year)
    log(f"Lade laufendes GHCN-Jahr {year} (ohne Deutschland/Frankreich): {url}")
    current: Dict[str, dict] = {}
    with http_open(url, attempts=6, timeout=240) as response:
        with gzip.GzipFile(fileobj=response) as gz:
            text = io.TextIOWrapper(gz, encoding="utf-8", errors="replace", newline="")
            reader = csv.reader(text)
            rows = kept = 0
            for row in reader:
                rows += 1
                if len(row) < 7:
                    continue
                sid, datestr, element = row[0], row[1], row[2]
                if sid not in stations or element not in ("TMAX", "TMIN"):
                    continue
                if row[5].strip():
                    continue
                try:
                    value = int(row[3]); date_obj = dt.datetime.strptime(datestr, "%Y%m%d").date()
                except (ValueError, TypeError):
                    continue
                if value == -9999:
                    continue
                mmdd = date_obj.strftime("%m-%d")
                station = current.setdefault(sid, {"TMAX": {}, "TMIN": {}})
                station[element][mmdd] = (value, int(datestr))
                kept += 1
                if rows % 1_000_000 == 0:
                    log(f"  {rows:,} GHCN-Jahreszeilen gelesen, {kept:,} Europa-TMAX/TMIN-Werte behalten …")
    log(f"GHCN {year}: {len(current):,} Stationen außerhalb Deutschlands/Frankreichs mit TMAX/TMIN.")
    return current


# ----------------------------- DWD adapter -----------------------------

def list_directory_files(base_url: str, pattern: str) -> List[str]:
    text = read_url_text(base_url, encoding="utf-8")
    names = sorted(set(re.findall(pattern, text)))
    return [urllib.parse.urljoin(base_url, html.unescape(name)) for name in names]


def dwd_float_to_tenths(raw: str) -> Optional[int]:
    value = str(raw or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number) or number <= -998.0:
        return None
    return int(round(number * 10.0))


def parse_dwd_product_bytes(data: bytes, cutoff_year: Optional[int] = None, exact_year: Optional[int] = None) -> dict:
    """Parse one DWD KL zip and return the common record state/current format."""
    historical = exact_year is None
    state = empty_state() if historical else {"TMAX": {}, "TMIN": {}}
    observed_years = {"TMAX": set(), "TMIN": set()}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        candidates = [n for n in zf.namelist() if re.search(r"produkt_klima_tag_.*\.txt$", n, re.I)]
        if not candidates:
            candidates = [n for n in zf.namelist() if n.lower().endswith(".txt") and "produkt" in n.lower()]
        for member in candidates:
            with zf.open(member) as raw:
                text = io.TextIOWrapper(raw, encoding="latin-1", errors="replace", newline="")
                reader = csv.DictReader(text, delimiter=";")
                if not reader.fieldnames:
                    continue
                # DWD headers often contain surrounding spaces.
                field_map = {str(k).strip(): k for k in reader.fieldnames if k is not None}
                date_key = field_map.get("MESS_DATUM")
                tx_key = field_map.get("TXK")
                tn_key = field_map.get("TNK")
                if not date_key or (not tx_key and not tn_key):
                    continue
                for row in reader:
                    datestr = str(row.get(date_key, "")).strip()
                    if not re.fullmatch(r"\d{8}", datestr):
                        continue
                    year = int(datestr[:4])
                    if cutoff_year is not None and year > cutoff_year:
                        continue
                    if exact_year is not None and year != exact_year:
                        continue
                    try:
                        date_obj = dt.datetime.strptime(datestr, "%Y%m%d").date()
                    except ValueError:
                        continue
                    date_int = int(datestr); mmdd = date_obj.strftime("%m-%d")
                    for element, key in (("TMAX", tx_key), ("TMIN", tn_key)):
                        if not key:
                            continue
                        value = dwd_float_to_tenths(row.get(key, ""))
                        if value is None:
                            continue
                        if historical:
                            block = state[element]
                            block["abs"] = update_record(block["abs"], value, date_int, element)
                            block["cal"][mmdd] = update_record(block["cal"].get(mmdd), value, date_int, element)
                            block["start"] = date_int if block["start"] is None else min(block["start"], date_int)
                            block["end"] = date_int if block["end"] is None else max(block["end"], date_int)
                            observed_years[element].add(year)
                        else:
                            state[element][mmdd] = (value, date_int)
    if historical:
        for element in ("TMAX", "TMIN"):
            state[element]["years"] = len(observed_years[element])
    return state


def dwd_station_id_from_url(url: str) -> Optional[str]:
    name = Path(urllib.parse.urlparse(url).path).name
    m = re.search(r"tageswerte_KL_(\d{5})_", name, re.I)
    return f"DWD:{m.group(1)}" if m else None


def fetch_parse_dwd(url: str, *, cutoff_year: Optional[int] = None, exact_year: Optional[int] = None):
    sid = dwd_station_id_from_url(url)
    if not sid:
        return None, None
    data = read_url_bytes(url, attempts=5, timeout=180)
    return sid, parse_dwd_product_bytes(data, cutoff_year=cutoff_year, exact_year=exact_year)


def build_dwd_baseline(stations: Dict[str, StationMeta], cutoff_year: int, workers: int = 6) -> dict:
    log(f"Baue DWD-Deutschland-Basisbestand bis {cutoff_year} …")
    urls = list_directory_files(DWD_HIST, r'href="(tageswerte_KL_\d{5}_\d{8}_\d{8}_hist\.zip)"')
    wanted = set(stations)
    urls = [u for u in urls if dwd_station_id_from_url(u) in wanted]
    log(f"DWD historical: {len(urls):,} Stations-ZIP-Dateien gefunden; {workers} parallele Downloads.")
    states: Dict[str, dict] = {}
    failures: List[Tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch_parse_dwd, u, cutoff_year=cutoff_year): u for u in urls}
        done = 0
        for future in as_completed(futures):
            url = futures[future]; done += 1
            try:
                sid, state = future.result()
                if sid and state and (state["TMAX"]["abs"] is not None or state["TMIN"]["abs"] is not None):
                    states[sid] = state
            except Exception as exc:
                failures.append((url, str(exc)))
                log(f"WARNUNG DWD historical: {Path(urllib.parse.urlparse(url).path).name}: {exc}")
            if done % 100 == 0 or done == len(urls):
                log(f"  DWD historical: {done:,}/{len(urls):,} ZIPs verarbeitet, {len(states):,} Stationen mit Daten …")
    if failures and len(failures) > max(10, int(len(urls) * 0.03)):
        raise RuntimeError(f"Zu viele DWD-Historical-Fehler: {len(failures)} von {len(urls)}")
    log(f"DWD-Basisbestand fertig: {len(states):,} Stationen; fehlgeschlagene Dateien: {len(failures)}.")
    return {
        "format_version": DWD_BASELINE_FORMAT_VERSION,
        "cutoff_year": cutoff_year,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "states": states,
    }


def load_or_build_dwd_baseline(cache_file: Path, stations: Dict[str, StationMeta], cutoff_year: int, force: bool, workers: int) -> dict:
    if cache_file.exists() and not force:
        try:
            with gzip.open(cache_file, "rb") as handle:
                payload = pickle.load(handle)
            if payload.get("format_version") == DWD_BASELINE_FORMAT_VERSION and payload.get("cutoff_year") == cutoff_year:
                log(f"Verwende historischen DWD-Cache: {cache_file}")
                return payload
        except Exception as exc:
            log(f"DWD-Cache konnte nicht gelesen werden ({exc}); Neuaufbau.")
    payload = build_dwd_baseline(stations, cutoff_year, workers=workers)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=5) as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(cache_file)
    log(f"DWD-Cache gespeichert: {cache_file} ({cache_file.stat().st_size/1024/1024:.1f} MB)")
    return payload


def parse_current_dwd_year(year: int, stations: Dict[str, StationMeta], workers: int = 8) -> dict:
    urls = list_directory_files(DWD_RECENT, r'href="(tageswerte_KL_\d{5}_akt\.zip)"')
    wanted = set(stations)
    urls = [u for u in urls if dwd_station_id_from_url(u) in wanted]
    log(f"Lade DWD recent für {year}: {len(urls):,} aktive Stations-ZIPs; {workers} parallele Downloads.")
    current: Dict[str, dict] = {}
    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch_parse_dwd, u, exact_year=year): u for u in urls}
        done = 0
        for future in as_completed(futures):
            done += 1
            try:
                sid, state = future.result()
                if sid and state and (state["TMAX"] or state["TMIN"]):
                    current[sid] = state
            except Exception as exc:
                failures += 1
                log(f"WARNUNG DWD recent: {Path(urllib.parse.urlparse(futures[future]).path).name}: {exc}")
            if done % 100 == 0 or done == len(urls):
                log(f"  DWD recent: {done:,}/{len(urls):,} ZIPs verarbeitet, {len(current):,} Stationen mit {year}-Daten …")
    if failures > max(10, int(len(urls) * 0.05)):
        raise RuntimeError(f"Zu viele DWD-Recent-Fehler: {failures} von {len(urls)}")
    return current



# ------------------------- Météo-France adapter -------------------------

def read_url_json(url: str) -> dict:
    return json.loads(read_url_text(url, encoding="utf-8"))


def mf_station_id(raw: str) -> Optional[str]:
    value = str(raw or "").strip()
    if value.endswith(".0"):
        value = value[:-2]
    value = re.sub(r"\D", "", value)
    if not value:
        return None
    return f"MF:{value.zfill(8)}"


def mf_float(raw: str) -> Optional[float]:
    value = str(raw or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def mf_temp_to_tenths(raw: str) -> Optional[int]:
    number = mf_float(raw)
    if number is None or number <= -90 or number >= 70:
        return None
    return int(round(number * 10.0))


def mf_quality_ok(raw: str) -> bool:
    """Keep Météo-France values that are filtered/validated/protected.

    In Météo-France climatological files, 9 = filtered, 1 = validated,
    0 = protected/final. Code 2 denotes a doubtful value under review and is
    excluded from records. Blank quality is tolerated for older rows where the
    value exists but a quality code was not supplied.
    """
    value = str(raw or "").strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value in {"", "0", "1", "9"}


def mf_resource_period(text: str) -> Optional[Tuple[int, int]]:
    low = text.lower()
    if "avant-1949" in low:
        return (1800, 1949)
    m = re.search(r"(?:previous|latest)-(\d{4})-(\d{4})", low)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return None


def mf_resource_department(text: str) -> Optional[str]:
    name = Path(urllib.parse.urlparse(text).path).name
    m = re.search(r"(?:^|/)(?:Q|Q-COMP)_([0-9]{2,3}|2A|2B)_", name, re.I)
    if not m:
        m = re.search(r"(?:Q|Q-COMP)_([0-9]{2,3}|2A|2B)_", text, re.I)
    return m.group(1).upper() if m else None


def discover_mf_resources() -> List[dict]:
    """Read official data.gouv.fr resource metadata for both MF daily datasets."""
    resources: List[dict] = []
    for label, api_url in (("principal", MF_DATASET_API), ("complementary", MF_COMP_DATASET_API)):
        payload = read_url_json(api_url)
        found = payload.get("resources", [])
        if not isinstance(found, list):
            raise RuntimeError(f"Météo-France Ressourcenliste unerwartet für {label}: {api_url}")
        for res in found:
            if not isinstance(res, dict):
                continue
            url = str(res.get("url") or res.get("latest") or "")
            title = str(res.get("title") or res.get("name") or "")
            hay = f"{title} {url}"
            if not url.lower().endswith(".csv.gz"):
                continue
            if "rr-t-vent" not in hay.lower() or "autres-parametres" in hay.lower():
                continue
            dept = mf_resource_department(url or title)
            if dept not in MF_METRO_DEPTS:
                continue
            period = mf_resource_period(hay)
            if period is None:
                continue
            resources.append({"url": url, "title": title, "dataset": label, "dept": dept, "period": period})
    # URL de-duplication while preserving deterministic order.
    unique = {}
    for res in resources:
        unique[res["url"]] = res
    result = sorted(unique.values(), key=lambda r: (r["dept"], r["period"][0], r["dataset"], r["url"]))
    if not result:
        raise RuntimeError("Keine Météo-France RR-T-Vent-Tagesressourcen gefunden.")
    return result


def mf_empty_partial_state() -> dict:
    return {
        "TMAX": {"abs": None, "cal": {}, "start": None, "end": None, "year_set": set()},
        "TMIN": {"abs": None, "cal": {}, "start": None, "end": None, "year_set": set()},
    }


def merge_record_tuples(a: Optional[Tuple[int, int, int]], b: Optional[Tuple[int, int, int]], element: str):
    if a is None:
        return b
    if b is None:
        return a
    if better(element, b[0], a[0]):
        return b
    if better(element, a[0], b[0]):
        return a
    return (a[0], min(a[1], b[1]), int(a[2]) + int(b[2]))


def merge_mf_partial(target: dict, incoming: dict) -> None:
    for sid, src_state in incoming.items():
        dst_state = target.setdefault(sid, mf_empty_partial_state())
        for element in ("TMAX", "TMIN"):
            src = src_state[element]; dst = dst_state[element]
            dst["abs"] = merge_record_tuples(dst.get("abs"), src.get("abs"), element)
            for mmdd, rec in src.get("cal", {}).items():
                dst["cal"][mmdd] = merge_record_tuples(dst["cal"].get(mmdd), rec, element)
            vals = [x for x in (dst.get("start"), src.get("start")) if x is not None]
            dst["start"] = min(vals) if vals else None
            vals = [x for x in (dst.get("end"), src.get("end")) if x is not None]
            dst["end"] = max(vals) if vals else None
            dst.setdefault("year_set", set()).update(src.get("year_set", set()))


def finalize_mf_states(partial: dict) -> dict:
    out = {}
    for sid, state in partial.items():
        dst = empty_state()
        for element in ("TMAX", "TMIN"):
            src = state[element]
            dst[element]["abs"] = src.get("abs")
            dst[element]["cal"] = src.get("cal", {})
            dst[element]["start"] = src.get("start")
            dst[element]["end"] = src.get("end")
            dst[element]["years"] = len(src.get("year_set", set()))
        out[sid] = dst
    return out


def parse_mf_stream(fileobj, *, cutoff_year: Optional[int] = None, exact_year: Optional[int] = None):
    """Parse one official Météo-France Q_*_RR-T-Vent.csv.gz resource."""
    partial: Dict[str, dict] = {}
    current: Dict[str, dict] = {}
    metas: Dict[str, Tuple[StationMeta, int]] = {}
    with gzip.GzipFile(fileobj=fileobj) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.DictReader(text, delimiter=";")
        if not reader.fieldnames:
            return partial, current, metas
        fmap = {str(k).strip().upper(): k for k in reader.fieldnames if k is not None}
        required = ["NUM_POSTE", "AAAAMMJJ"]
        if any(k not in fmap for k in required) or not ({"TX", "TN"} & set(fmap)):
            raise RuntimeError(f"Météo-France CSV ohne erwartete Spalten: {list(fmap)[:20]}")
        for row in reader:
            sid = mf_station_id(row.get(fmap["NUM_POSTE"], ""))
            datestr = str(row.get(fmap["AAAAMMJJ"], "")).strip().replace(".0", "")
            if not sid or not re.fullmatch(r"\d{8}", datestr):
                continue
            year = int(datestr[:4])
            if cutoff_year is not None and year > cutoff_year:
                continue
            if exact_year is not None and year != exact_year:
                continue
            try:
                date_obj = dt.datetime.strptime(datestr, "%Y%m%d").date()
            except ValueError:
                continue
            lat = mf_float(row.get(fmap.get("LAT", ""), "")) if "LAT" in fmap else None
            lon = mf_float(row.get(fmap.get("LON", ""), "")) if "LON" in fmap else None
            if lat is None or lon is None or not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
                continue
            elev = mf_float(row.get(fmap.get("ALTI", ""), "")) if "ALTI" in fmap else None
            name = str(row.get(fmap.get("NOM_USUEL", ""), "")).strip() if "NOM_USUEL" in fmap else ""
            meta = StationMeta(
                sid, float(lat), float(lon), None if elev is None or elev <= -999 else round(float(elev), 1),
                name or sid.split(":", 1)[1], "FR", "Frankreich", MF_SOURCE,
                "Météo-France Tagesklima: TX/TN; Qualitätscodes 0/1/9 (sowie ältere leere Codes) akzeptiert, Code 2 (douteuse) verworfen.",
            )
            date_int = int(datestr)
            old_meta = metas.get(sid)
            if old_meta is None or date_int >= old_meta[1]:
                metas[sid] = (meta, date_int)
            mmdd = date_obj.strftime("%m-%d")
            for element, value_col, quality_col in (("TMAX", "TX", "QTX"), ("TMIN", "TN", "QTN")):
                if value_col not in fmap:
                    continue
                value = mf_temp_to_tenths(row.get(fmap[value_col], ""))
                qraw = row.get(fmap[quality_col], "") if quality_col in fmap else ""
                if value is None or not mf_quality_ok(qraw):
                    continue
                if exact_year is None:
                    state = partial.setdefault(sid, mf_empty_partial_state())
                    block = state[element]
                    block["abs"] = update_record(block["abs"], value, date_int, element)
                    block["cal"][mmdd] = update_record(block["cal"].get(mmdd), value, date_int, element)
                    block["start"] = date_int if block["start"] is None else min(block["start"], date_int)
                    block["end"] = date_int if block["end"] is None else max(block["end"], date_int)
                    block["year_set"].add(year)
                else:
                    station = current.setdefault(sid, {"TMAX": {}, "TMIN": {}})
                    station[element][mmdd] = (value, date_int)
    return partial, current, metas


def fetch_parse_mf(resource: dict, *, cutoff_year: Optional[int] = None, exact_year: Optional[int] = None):
    url = resource["url"]
    with http_open(url, attempts=5, timeout=240) as response:
        return parse_mf_stream(response, cutoff_year=cutoff_year, exact_year=exact_year)


def merge_mf_meta(target: Dict[str, Tuple[StationMeta, int]], incoming: Dict[str, Tuple[StationMeta, int]]) -> None:
    for sid, item in incoming.items():
        if sid not in target or item[1] >= target[sid][1]:
            target[sid] = item


def build_mf_baseline(cutoff_year: int, workers: int = 6) -> dict:
    resources = [r for r in discover_mf_resources() if r["period"][0] <= cutoff_year]
    log(f"Baue Météo-France-Basisbestand bis {cutoff_year}: {len(resources):,} RR-T-Vent-Dateien; {workers} parallele Downloads …")
    partial: Dict[str, dict] = {}
    metas: Dict[str, Tuple[StationMeta, int]] = {}
    failures: List[Tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch_parse_mf, r, cutoff_year=cutoff_year): r for r in resources}
        done = 0
        for future in as_completed(futures):
            r = futures[future]; done += 1
            try:
                states_part, _current, meta_part = future.result()
                merge_mf_partial(partial, states_part)
                merge_mf_meta(metas, meta_part)
            except Exception as exc:
                failures.append((r["url"], str(exc)))
                log(f"WARNUNG Météo-France historical {r['dept']} {Path(urllib.parse.urlparse(r['url']).path).name}: {exc}")
            if done % 25 == 0 or done == len(resources):
                log(f"  Météo-France historical: {done:,}/{len(resources):,} Dateien, {len(partial):,} Stationen …")
    if failures and len(failures) > max(12, int(len(resources) * 0.06)):
        raise RuntimeError(f"Zu viele Météo-France-Historical-Fehler: {len(failures)} von {len(resources)}")
    states = finalize_mf_states(partial)
    stations = {sid: item[0] for sid, item in metas.items() if sid in states}
    log(f"Météo-France-Basisbestand fertig: {len(states):,} Stationen; fehlgeschlagene Dateien: {len(failures)}.")
    return {
        "format_version": MF_BASELINE_FORMAT_VERSION,
        "cutoff_year": cutoff_year,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "states": states,
        "stations": stations,
    }


def load_or_build_mf_baseline(cache_file: Path, cutoff_year: int, force: bool, workers: int) -> dict:
    if cache_file.exists() and not force:
        try:
            with gzip.open(cache_file, "rb") as handle:
                payload = pickle.load(handle)
            if payload.get("format_version") == MF_BASELINE_FORMAT_VERSION and payload.get("cutoff_year") == cutoff_year:
                log(f"Verwende historischen Météo-France-Cache: {cache_file}")
                return payload
        except Exception as exc:
            log(f"Météo-France-Cache konnte nicht gelesen werden ({exc}); Neuaufbau.")
    payload = build_mf_baseline(cutoff_year, workers=workers)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=5) as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(cache_file)
    log(f"Météo-France-Cache gespeichert: {cache_file} ({cache_file.stat().st_size/1024/1024:.1f} MB)")
    return payload


def parse_current_mf_year(year: int, workers: int = 8):
    resources = [r for r in discover_mf_resources() if r["period"][0] <= year <= r["period"][1]]
    log(f"Lade Météo-France {year}: {len(resources):,} RR-T-Vent-Dateien; {workers} parallele Downloads …")
    current: Dict[str, dict] = {}
    metas: Dict[str, Tuple[StationMeta, int]] = {}
    failures: List[Tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch_parse_mf, r, exact_year=year): r for r in resources}
        done = 0
        for future in as_completed(futures):
            r = futures[future]; done += 1
            try:
                _states_part, current_part, meta_part = future.result()
                for sid, st in current_part.items():
                    dst = current.setdefault(sid, {"TMAX": {}, "TMIN": {}})
                    dst["TMAX"].update(st.get("TMAX", {})); dst["TMIN"].update(st.get("TMIN", {}))
                merge_mf_meta(metas, meta_part)
            except Exception as exc:
                failures.append((r["url"], str(exc)))
                log(f"WARNUNG Météo-France current {r['dept']} {Path(urllib.parse.urlparse(r['url']).path).name}: {exc}")
            if done % 25 == 0 or done == len(resources):
                log(f"  Météo-France current: {done:,}/{len(resources):,} Dateien, {len(current):,} Stationen mit {year}-Daten …")
    if failures and len(failures) > max(12, int(len(resources) * 0.08)):
        raise RuntimeError(f"Zu viele Météo-France-Current-Fehler: {len(failures)} von {len(resources)}")
    return current, {sid: item[0] for sid, item in metas.items()}

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
    if current is None:
        return base, False, None
    value, date_int = current
    if base is None:
        return (value, date_int, 1), False, None
    if better(element, value, base[0]):
        delta = (value - base[0]) / 10.0 if element == "TMAX" else (base[0] - value) / 10.0
        return (value, date_int, 1), True, delta
    if value == base[0]:
        return (base[0], base[1], base[2] + 1), False, 0.0
    return base, False, ((value - base[0]) / 10.0 if element == "TMAX" else (base[0] - value) / 10.0)


def all_mmdd() -> List[str]:
    leap = 2024
    return [(dt.date(leap, 1, 1) + dt.timedelta(days=i)).strftime("%m-%d") for i in range(366)]


def merge_and_write(output_dir: Path, stations: Dict[str, StationMeta], states: Dict[str, dict], current: dict, current_year: int) -> None:
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

        for element in ("TMAX", "TMIN"):
            base_block = base_state[element]
            cur_values = cur_state.get(element, {})
            cur_abs = None
            for obs in cur_values.values():
                if cur_abs is None or better(element, obs[0], cur_abs[0]):
                    cur_abs = obs
            final_abs, new_abs, abs_delta = combine_record(base_block.get("abs"), cur_abs, element)
            years = int(base_block.get("years", 0)) + (1 if cur_values else 0)
            start = base_block.get("start"); end = base_block.get("end")
            if cur_values:
                cur_dates = [d for _, d in cur_values.values()]
                start = min([x for x in [start, min(cur_dates)] if x is not None])
                end = max([x for x in [end, max(cur_dates)] if x is not None])
            element_summary[element] = {
                "record": record_json(final_abs),
                "previous": record_json(base_block.get("abs")) if new_abs else None,
                "new_absolute_current_year": bool(new_abs),
                "new_absolute_delta": round(abs_delta, 1) if new_abs and abs_delta is not None else None,
                "start": date_str(start), "end": date_str(end), "years": years,
            }

            new_count = 0; last_new_date = None
            cal_base = base_block.get("cal", {})
            for mmdd in set(cal_base) | set(cur_values):
                b = cal_base.get(mmdd); c = cur_values.get(mmdd)
                _final, is_new, _delta = combine_record(b, c, element)
                if is_new:
                    new_count += 1
                    last_new_date = c[1] if last_new_date is None else max(last_new_date, c[1])
            new_counts[element] = new_count
            last_new[element] = date_str(last_new_date)

        if not element_summary["TMAX"]["record"] and not element_summary["TMIN"]["record"]:
            continue
        station_rows.append({
            "id": meta.id, "source_id": meta.id.split(":",1)[1] if ":" in meta.id else meta.id,
            "name": meta.name, "country_code": meta.country_code, "country": meta.country,
            "lat": round(meta.lat, 4), "lon": round(meta.lon, 4), "elevation": meta.elev,
            "source": meta.source, "quality_rule": meta.quality_rule,
            "tmax": element_summary["TMAX"], "tmin": element_summary["TMIN"],
            "new_current_year": {
                "tmax_calendar": new_counts["TMAX"], "tmin_calendar": new_counts["TMIN"],
                "tmax_last": last_new["TMAX"], "tmin_last": last_new["TMIN"],
            },
        })

    daypacks = {mmdd: {"tmax": [], "tmin": []} for mmdd in all_mmdd()}
    for idx, row in enumerate(station_rows):
        sid = row["id"]
        base_state = states.get(sid, empty_state())
        cur_state = current.get(sid, {"TMAX": {}, "TMIN": {}})
        for element, pack_key in (("TMAX", "tmax"), ("TMIN", "tmin")):
            bcal = base_state[element].get("cal", {}); ccal = cur_state.get(element, {})
            for mmdd in set(bcal) | set(ccal):
                b = bcal.get(mmdd); c = ccal.get(mmdd)
                final, is_new, delta = combine_record(b, c, element)
                if final is None:
                    continue
                daypacks[mmdd][pack_key].append([
                    idx, final[0], final[1], b[0] if b else None, b[1] if b else None,
                    c[0] if c else None, c[1] if c else None, 1 if is_new else 0,
                    int(round(delta * 10)) if delta is not None else None,
                ])

    output_dir.mkdir(parents=True, exist_ok=True)
    cal_dir = output_dir / "calendar"; cal_dir.mkdir(parents=True, exist_ok=True)
    countries = sorted({row["country"] for row in station_rows})
    source_counts: Dict[str, int] = {}
    for row in station_rows:
        source_counts[row["source"]] = source_counts.get(row["source"], 0) + 1
    payload = {
        "payload_version": PAYLOAD_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "current_year": current_year, "historical_through": current_year - 1,
        "source": "DWD CDC (Deutschland) + Météo-France (Frankreich) + GHCN-Daily (übriges Europa)",
        "source_url": MF_PUBLIC_BASE,
        "sources": [
            {"name": DWD_SOURCE, "scope": "Deutschland", "url": DWD_BASE, "stations": source_counts.get(DWD_SOURCE, 0)},
            {"name": MF_SOURCE, "scope": "Frankreich", "url": MF_PUBLIC_BASE, "stations": source_counts.get(MF_SOURCE, 0)},
            {"name": GHCN_SOURCE, "scope": "übriges Europa", "url": GHCN_BASE, "stations": source_counts.get(GHCN_SOURCE, 0)},
        ],
        "quality_rule": "Deutschland: DWD CDC Tageswerte KL (TXK/TNK, Fehlwerte verworfen). Frankreich: Météo-France TX/TN aus den täglichen Klimadateien; Qualitätscodes 0/1/9 bzw. ältere leere Codes akzeptiert, Code 2 verworfen. Übriges Europa: GHCN TMAX/TMIN nur mit leerem Q-FLAG.",
        "history_scope": "DWD-KL für Deutschland; Météo-France tägliche Klimadaten (Haupt- und Ergänzungsstationen) für Frankreich; GHCN-Daily für das übrige Europa. Das laufende Jahr wird separat aktualisiert.",
        "station_count": len(station_rows), "country_count": len(countries), "countries": countries,
        "calendar_url_pattern": "europe_stations/calendar/{mmdd}.json.gz",
        "calendar_schema": ["station_index", "record_tenths_c", "record_date_yyyymmdd", "previous_tenths_c", "previous_date_yyyymmdd", "current_tenths_c", "current_date_yyyymmdd", "strict_new_record", "difference_tenths_c"],
        "stations": station_rows,
    }
    (output_dir / "index.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    for mmdd, pack in daypacks.items():
        obj = {"payload_version": PAYLOAD_VERSION, "mmdd": mmdd, "current_year": current_year, "tmax": pack["tmax"], "tmin": pack["tmin"]}
        with gzip.open(cal_dir / f"{mmdd}.json.gz", "wt", encoding="utf-8", compresslevel=7) as handle:
            json.dump(obj, handle, ensure_ascii=False, separators=(",", ":"))

    total_gz = sum(p.stat().st_size for p in cal_dir.glob("*.json.gz"))
    log(f"Frontend-Daten geschrieben: {len(station_rows):,} Stationen ({source_counts}), 366 Tagesarchive, {total_gz/1024/1024:.1f} MB komprimiert.")


def self_test() -> None:
    sid = "FR000001234"
    prefix = f"{sid}202501TMAX"
    chars = list(prefix + ("-9999   " * 31)); chars[21:29] = list("  123   ")
    state = parse_dly_station(io.BytesIO(("".join(chars) + "\n").encode("ascii")), 2025)
    assert state["TMAX"]["abs"][0] == 123

    sample = (
        "STATIONS_ID;MESS_DATUM;QN_3;FX;FM;QN_4;RSK;RSKF;SDK;SHK_TAG;NM;VPM;PM;TMK;UPM;TXK;TNK;TGK;eor\n"
        "44;20250101;3;-999;-999;3;0.0;0;-999;-999;7.0;8.0;1000;2.0;90;12.3;-4.5;-6.0;eor\n"
    ).encode("latin-1")
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("produkt_klima_tag_20250101_20250101_00044.txt", sample)
    dwd = parse_dwd_product_bytes(bio.getvalue(), cutoff_year=2025)
    assert dwd["TMAX"]["abs"][0] == 123 and dwd["TMIN"]["abs"][0] == -45

    mf_csv = (
        "NUM_POSTE;NOM_USUEL;LAT;LON;ALTI;AAAAMMJJ;TN;QTN;TX;QTX\n"
        "75114001;PARIS-MONTSOURIS;48.8217;2.3378;75;20250101;-4.5;1;12.3;1\n"
        "75114001;PARIS-MONTSOURIS;48.8217;2.3378;75;20250102;-9.9;2;99.0;2\n"
    ).encode("utf-8")
    mf_gz = io.BytesIO()
    with gzip.GzipFile(fileobj=mf_gz, mode="wb") as gz:
        gz.write(mf_csv)
    assert mf_resource_department("https://host/BASE/QUOT/Q_01_latest-2025-2026_RR-T-Vent.csv.gz") == "01"
    assert mf_resource_department("https://host/BASE/QUOT_COMP/Q-COMP_45_avant-1949_RR-T-Vent.csv.gz") == "45"
    assert mf_resource_period("Q_75_latest-2025-2026_RR-T-Vent.csv.gz") == (2025, 2026)
    mf_gz.seek(0)
    mf_partial, _mf_cur, mf_meta = parse_mf_stream(mf_gz, cutoff_year=2025)
    mf_state = finalize_mf_states(mf_partial)["MF:75114001"]
    assert mf_state["TMAX"]["abs"][0] == 123 and mf_state["TMIN"]["abs"][0] == -45
    assert "MF:75114001" in mf_meta

    final, new, delta = combine_record((123, 20250101, 1), (130, 20260101), "TMAX")
    assert new and final[0] == 130 and abs(delta - 0.7) < 1e-9
    final, new, delta = combine_record((-50, 20250101, 1), (-60, 20260101), "TMIN")
    assert new and final[0] == -60 and abs(delta - 1.0) < 1e-9
    print("Self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="europe_stations")
    parser.add_argument("--cache-dir", default=".cache/europe-stations")
    parser.add_argument("--force-baseline", action="store_true", help="GHCN, DWD und Météo-France historische Baselines neu aufbauen")
    parser.add_argument("--force-dwd-baseline", action="store_true", help="Nur DWD-Baseline neu aufbauen")
    parser.add_argument("--force-mf-baseline", action="store_true", help="Nur Météo-France-Baseline neu aufbauen")
    parser.add_argument("--dwd-workers", type=int, default=6)
    parser.add_argument("--mf-workers", type=int, default=6)
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test(); return 0

    current_year = args.year; cutoff_year = current_year - 1

    countries = parse_countries(read_url_text(COUNTRIES_URL))
    ghcn_stations = parse_ghcn_stations(read_url_text(STATIONS_URL), countries)
    log(f"GHCN-Metadaten im Europa-Kartenfenster (Deutschland/Frankreich ausgeschlossen): {len(ghcn_stations):,}")
    if not ghcn_stations:
        raise RuntimeError("Keine europäischen GHCN-Stationen gefunden.")

    # DWD station metadata is Latin-1/Windows-compatible text on CDC.
    dwd_text = decode_text_smart(read_url_bytes(DWD_STATIONS_URL))
    dwd_stations = parse_dwd_stations(dwd_text)
    log(f"DWD-KL-Stationsmetadaten Deutschland: {len(dwd_stations):,}")
    if not dwd_stations:
        raise RuntimeError("Keine DWD-KL-Stationen gefunden.")

    cache_dir = Path(args.cache_dir)
    ghcn_cache = cache_dir / f"ghcn_europe_baseline_through_{cutoff_year}_v{GHCN_BASELINE_FORMAT_VERSION}.pkl.gz"
    dwd_cache = cache_dir / f"dwd_germany_kl_baseline_through_{cutoff_year}_v{DWD_BASELINE_FORMAT_VERSION}.pkl.gz"
    mf_cache = cache_dir / f"meteofrance_daily_baseline_through_{cutoff_year}_v{MF_BASELINE_FORMAT_VERSION}.pkl.gz"

    ghcn_baseline = load_or_build_ghcn_baseline(ghcn_cache, ghcn_stations, cutoff_year, args.force_baseline)
    dwd_baseline = load_or_build_dwd_baseline(dwd_cache, dwd_stations, cutoff_year, args.force_baseline or args.force_dwd_baseline, args.dwd_workers)
    mf_baseline = load_or_build_mf_baseline(mf_cache, cutoff_year, args.force_baseline or args.force_mf_baseline, args.mf_workers)

    ghcn_current = parse_current_ghcn_year(current_year, ghcn_stations)
    dwd_current = parse_current_dwd_year(current_year, dwd_stations, workers=max(4, args.dwd_workers))
    mf_current, mf_current_stations = parse_current_mf_year(current_year, workers=max(4, args.mf_workers))

    mf_stations = dict(mf_baseline.get("stations", {})); mf_stations.update(mf_current_stations)
    log(f"Météo-France-Stationsmetadaten Frankreich: {len(mf_stations):,}")
    if not mf_stations:
        raise RuntimeError("Keine Météo-France-Stationen gefunden.")

    stations = dict(ghcn_stations); stations.update(dwd_stations); stations.update(mf_stations)
    # Filter older GHCN caches to the V4 fallback metadata set, then add national sources.
    states = {sid: st for sid, st in ghcn_baseline.get("states", {}).items() if sid in ghcn_stations}
    states.update(dwd_baseline.get("states", {})); states.update(mf_baseline.get("states", {}))
    current = dict(ghcn_current); current.update(dwd_current); current.update(mf_current)

    merge_and_write(Path(args.output), stations, states, current, current_year)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        raise
