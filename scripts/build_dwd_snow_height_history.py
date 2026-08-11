#!/usr/bin/env python3
"""Build the reusable historical DWD snow-height cache through 2025.

Step 2 of the snow-height project:
  * no website changes
  * no public production JSON yet
  * no current hydrological-year integration yet

Candidate rule:
  current DWD daily-KL network
  + official DWD SHK_TAG >=30-year overview
  + at least 30 net years (Anzahl_Jahre - Fehl_Jahre)

For every candidate station, all available historical daily KL archive files
are downloaded and merged. Only real, valid SHK_TAG measurements are cached;
missing values remain missing and are NEVER converted to 0 cm.

Cache:
  .cache/dwd-snow-height/history_v1/<station_id>.json.gz
  .cache/dwd-snow-height/history_manifest_v1.json

The build also evaluates hydrological years (01 Nov - 31 Oct) at 90%, 95%,
and 98% valid-day coverage. This is diagnostic only; the final dashboard
quality threshold is intentionally not fixed in this step.
"""
from __future__ import annotations

import csv
import gzip
import html
import io
import json
import math
import re
import sys
import time
import urllib.request
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

BASE = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl"
)
RECENT_URL = BASE + "/recent/"
HISTORICAL_URL = BASE + "/historical/"
OVERVIEW_URL = (
    BASE
    + "/timeseries_overview/"
    + "ZeitReihen_klima_tag_GE_30Jahre_SHK_TAG.html"
)
META_URL = RECENT_URL + "KL_Tageswerte_Beschreibung_Stationen.txt"

CACHE_ROOT = Path(".cache/dwd-snow-height")
CACHE_DIR = CACHE_ROOT / "history_v1"
MANIFEST = CACHE_ROOT / "history_manifest_v1.json"
CACHE_VERSION = 1
HISTORICAL_THROUGH = date(2025, 12, 31)
LAST_COMPLETE_HYDRO_YEAR = 2025
REFERENCE_START = 1991
REFERENCE_END = 2020
COVERAGE_THRESHOLDS = (0.90, 0.95, 0.98)

UA = "climate-dashboard-dwd-snow-history/1.0 (+GitHub Actions)"
TIMEOUT = 120
TRIES = 4

GERMAN_STATES = (
    "Baden-Württemberg",
    "Bayern",
    "Berlin",
    "Brandenburg",
    "Bremen",
    "Hamburg",
    "Hessen",
    "Mecklenburg-Vorpommern",
    "Niedersachsen",
    "Nordrhein-Westfalen",
    "Rheinland-Pfalz",
    "Saarland",
    "Sachsen",
    "Sachsen-Anhalt",
    "Schleswig-Holstein",
    "Thüringen",
)

STATE_ALIASES = {
    "Baden-Wuerttemberg": "Baden-Württemberg",
    "Baden Württemberg": "Baden-Württemberg",
    "Mecklenburg Vorpommern": "Mecklenburg-Vorpommern",
    "Nordrhein Westfalen": "Nordrhein-Westfalen",
    "Rheinland Pfalz": "Rheinland-Pfalz",
    "Sachsen Anhalt": "Sachsen-Anhalt",
    "Schleswig Holstein": "Schleswig-Holstein",
}


@dataclass(frozen=True)
class StationMeta:
    station_id: str
    name: str
    state: str
    height: float | None
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class OverviewRow:
    station_id: str
    start: str
    end: str
    span_years: float
    missing_years: float
    name: str
    state: str

    @property
    def net_years(self) -> float:
        return max(0.0, self.span_years - self.missing_years)


class HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if (
            tag in ("td", "th")
            and self._row is not None
            and self._cell is not None
        ):
            value = html.unescape("".join(self._cell))
            self._row.append(" ".join(value.split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def log(message: str = "") -> None:
    print(message, flush=True)


def request_bytes(url: str, attempts: int = TRIES) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last_error}")


def request_text(url: str) -> str:
    raw = request_bytes(url)
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1", errors="replace")


def normalize_state(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    cleaned = STATE_ALIASES.get(cleaned, cleaned)
    return cleaned if cleaned in GERMAN_STATES else "Unbekannt"


def parse_metadata(text: str) -> dict[str, StationMeta]:
    lines = text.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "Stations_id" in line
            and "von_datum" in line
            and "Stationsname" in line
            and "Bundesland" in line
        ),
        None,
    )
    if header_index is None:
        raise RuntimeError("DWD-Stationskopfzeile nicht gefunden.")

    prefix_pattern = re.compile(
        r"^\s*(\d{1,5})\s+"
        r"(\d{8})\s+"
        r"(\d{8})\s+"
        r"(-?\d+(?:[.,]\d+)?)\s+"
        r"(-?\d+(?:[.,]\d+)?)\s+"
        r"(-?\d+(?:[.,]\d+)?)\s+"
        r"(.+?)\s*$"
    )

    state_candidates = sorted(
        set(GERMAN_STATES) | set(STATE_ALIASES),
        key=len,
        reverse=True,
    )
    state_patterns = [
        (state, re.compile(rf"(?<!\S){re.escape(state)}(?=\s|$)"))
        for state in state_candidates
    ]

    result: dict[str, StationMeta] = {}

    for raw_line in lines[header_index + 1 :]:
        match = prefix_pattern.match(raw_line.rstrip())
        if not match:
            continue

        sid, _start, _end, height, lat, lon, tail = match.groups()

        best_state = None
        best_start = -1
        for raw_state, pattern in state_patterns:
            for state_match in pattern.finditer(tail):
                if state_match.start() > best_start:
                    best_start = state_match.start()
                    best_state = raw_state

        if best_state is None:
            name = tail.strip()
            state = "Unbekannt"
        else:
            name = tail[:best_start].strip()
            state = normalize_state(best_state)

        def as_float(value: str) -> float | None:
            try:
                return float(value.replace(",", "."))
            except ValueError:
                return None

        station_id = sid.zfill(5)
        result[station_id] = StationMeta(
            station_id=station_id,
            name=name or f"Station {station_id}",
            state=state,
            height=as_float(height),
            lat=as_float(lat),
            lon=as_float(lon),
        )

    if len(result) < 300:
        raise RuntimeError(
            f"Unerwartet wenige Stationsmetadaten: {len(result)}."
        )

    known = sum(item.state != "Unbekannt" for item in result.values())
    if known < max(100, len(result) // 2):
        raise RuntimeError(
            f"Zu wenige Bundesländer erkannt: {known}/{len(result)}."
        )

    return result


def parse_number(value: str) -> float:
    value = value.strip().replace(",", ".")
    if value.startswith("."):
        value = "0" + value
    if value in ("", "-", "–"):
        return 0.0
    return float(value)


def parse_overview(text: str) -> dict[str, OverviewRow]:
    parser = HtmlTableParser()
    parser.feed(text)

    result: dict[str, OverviewRow] = {}

    for cells in parser.rows:
        if len(cells) < 9 or not cells[0].strip().isdigit():
            continue

        try:
            station_id = cells[0].zfill(5)
            span_years = parse_number(cells[3])
            missing_years = parse_number(cells[4])
        except (IndexError, ValueError):
            continue

        result[station_id] = OverviewRow(
            station_id=station_id,
            start=cells[1],
            end=cells[2],
            span_years=span_years,
            missing_years=missing_years,
            name=cells[7],
            state=normalize_state(cells[8]),
        )

    if len(result) < 300:
        raise RuntimeError(
            f"SHK_TAG-Zeitreihenübersicht unplausibel: {len(result)} Einträge."
        )

    return result


def list_recent_station_ids() -> set[str]:
    listing = request_text(RECENT_URL)
    ids = set(
        re.findall(
            r"tageswerte_KL_(\d{5})_akt\.zip",
            listing,
            flags=re.I,
        )
    )
    if len(ids) < 300:
        raise RuntimeError(
            f"Unerwartet wenige aktuelle KL-Stationen: {len(ids)}."
        )
    return ids


def list_historical_files() -> dict[str, list[dict[str, str]]]:
    listing = request_text(HISTORICAL_URL)
    pattern = re.compile(
        r"(tageswerte_KL_(\d{5})_(\d{8})_(\d{8})_hist\.zip)",
        flags=re.I,
    )

    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for filename, station_id, start, end in pattern.findall(listing):
        result[station_id].append(
            {
                "filename": filename,
                "start": start,
                "end": end,
            }
        )

    for station_id in result:
        result[station_id].sort(
            key=lambda item: (
                item["start"],
                item["end"],
                item["filename"],
            )
        )

    if len(result) < 500:
        raise RuntimeError(
            f"Unerwartet wenige historische KL-Stationen: {len(result)}."
        )

    return dict(result)


def decode_product(data: bytes) -> str:
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "MESS_DATUM" in text:
            return text
    return data.decode("latin-1", errors="replace")


def parse_historical_zip(raw: bytes) -> dict[date, float]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".txt")
            and name.split("/")[-1].lower().startswith("produkt_")
        ]
        if not members:
            raise RuntimeError("Keine produkt_*.txt im historischen KL-ZIP.")

        # A DWD KL ZIP should normally contain one product file, but merge all
        # product_ text members defensively.
        product_bytes = [archive.read(name) for name in members]

    values: dict[date, float] = {}

    for data in product_bytes:
        reader = csv.DictReader(
            io.StringIO(decode_product(data)),
            delimiter=";",
        )
        fields = [(field or "").strip() for field in (reader.fieldnames or [])]
        lookup = {field.upper(): field for field in fields}
        snow_field = lookup.get("SHK_TAG") or lookup.get("SHK")
        if not snow_field:
            raise RuntimeError(
                f"SHK_TAG/SHK fehlt. Header={fields}"
            )

        for raw_row in reader:
            row = {
                (key or "").strip(): (
                    value.strip() if isinstance(value, str) else value
                )
                for key, value in raw_row.items()
            }

            stamp = str(row.get("MESS_DATUM") or "").strip()
            try:
                day = datetime.strptime(stamp, "%Y%m%d").date()
            except ValueError:
                continue

            if day > HISTORICAL_THROUGH:
                continue

            raw_value = row.get(snow_field)
            if raw_value in (None, ""):
                continue

            try:
                value = float(str(raw_value).replace(",", "."))
            except ValueError:
                continue

            if not math.isfinite(value) or value <= -900 or value < 0:
                continue

            values[day] = round(value, 1)

    return values


def hydro_year_for_day(day: date) -> int:
    return day.year + 1 if day.month >= 11 else day.year


def hydro_year_bounds(hydro_year: int) -> tuple[date, date]:
    return date(hydro_year - 1, 11, 1), date(hydro_year, 10, 31)


def expected_days_in_hydro_year(hydro_year: int) -> int:
    start, end = hydro_year_bounds(hydro_year)
    return (end - start).days + 1


def coverage_by_hydro_year(
    rows: list[list[Any]],
) -> dict[int, tuple[int, int, float]]:
    counts: Counter[int] = Counter()

    for day_text, _value in rows:
        day = date.fromisoformat(day_text)
        hydro_year = hydro_year_for_day(day)
        if hydro_year <= LAST_COMPLETE_HYDRO_YEAR:
            counts[hydro_year] += 1

    result: dict[int, tuple[int, int, float]] = {}
    for hydro_year, valid_days in counts.items():
        expected = expected_days_in_hydro_year(hydro_year)
        result[hydro_year] = (
            valid_days,
            expected,
            valid_days / expected,
        )
    return result


def cache_file_for_station(root: Path, station_id: str) -> Path:
    return root / CACHE_DIR / f"{station_id}.json.gz"


def read_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def write_gzip_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(
        tmp,
        "wt",
        encoding="utf-8",
        compresslevel=6,
    ) as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    tmp.replace(path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def expected_source_signature(
    historical_files: list[dict[str, str]],
) -> list[str]:
    return [
        item["filename"]
        for item in historical_files
    ]


def cached_station_is_current(
    path: Path,
    station_id: str,
    source_files: list[dict[str, str]],
) -> bool:
    if not path.exists():
        return False

    try:
        payload = read_gzip_json(path)
    except Exception:
        return False

    return (
        payload.get("version") == CACHE_VERSION
        and payload.get("station_id") == station_id
        and payload.get("source_files")
        == expected_source_signature(source_files)
        and payload.get("historical_through")
        == HISTORICAL_THROUGH.isoformat()
        and isinstance(payload.get("rows"), list)
    )


def build_one_station(
    root: Path,
    station_id: str,
    meta: StationMeta,
    overview: OverviewRow,
    source_files: list[dict[str, str]],
) -> tuple[str, dict[str, Any] | None, str | None]:
    target = cache_file_for_station(root, station_id)

    if cached_station_is_current(
        target,
        station_id,
        source_files,
    ):
        try:
            payload = read_gzip_json(target)
            return (
                station_id,
                {
                    "cached": True,
                    "row_count": len(payload["rows"]),
                },
                None,
            )
        except Exception:
            pass

    merged: dict[date, float] = {}
    duplicate_conflicts = 0

    try:
        for source in source_files:
            raw = request_bytes(HISTORICAL_URL + source["filename"])
            parsed = parse_historical_zip(raw)

            for day, value in parsed.items():
                old = merged.get(day)
                if old is not None and old != value:
                    duplicate_conflicts += 1
                merged[day] = value

        if not merged:
            raise RuntimeError("Keine gültigen historischen SHK_TAG-Werte.")

        rows = [
            [day.isoformat(), value]
            for day, value in sorted(merged.items())
        ]

        payload = {
            "version": CACHE_VERSION,
            "station_id": station_id,
            "name": meta.name,
            "state": meta.state,
            "height": meta.height,
            "lat": meta.lat,
            "lon": meta.lon,
            "overview": {
                "start": overview.start,
                "end": overview.end,
                "span_years": round(overview.span_years, 2),
                "missing_years": round(overview.missing_years, 2),
                "net_years": round(overview.net_years, 2),
            },
            "historical_through": HISTORICAL_THROUGH.isoformat(),
            "source_files": expected_source_signature(source_files),
            "duplicate_conflicts": duplicate_conflicts,
            "rows": rows,
        }

        write_gzip_json(target, payload)

        return (
            station_id,
            {
                "cached": False,
                "row_count": len(rows),
                "duplicate_conflicts": duplicate_conflicts,
            },
            None,
        )
    except Exception as exc:
        return station_id, None, str(exc)


def station_qc(
    payload: dict[str, Any],
) -> dict[str, Any]:
    rows = payload.get("rows") or []
    coverage = coverage_by_hydro_year(rows)

    threshold_counts = {}
    reference_counts = {}

    for threshold in COVERAGE_THRESHOLDS:
        key = str(int(round(threshold * 100)))
        threshold_counts[key] = sum(
            fraction >= threshold
            for _valid, _expected, fraction in coverage.values()
        )
        reference_counts[key] = sum(
            1
            for hydro_year in range(REFERENCE_START, REFERENCE_END + 1)
            if hydro_year in coverage
            and coverage[hydro_year][2] >= threshold
        )

    years = sorted(coverage)
    return {
        "first_hydro_year": years[0] if years else None,
        "last_complete_hydro_year": years[-1] if years else None,
        "complete_year_counts": threshold_counts,
        "reference_year_counts": reference_counts,
    }


def main() -> int:
    root = Path(".").resolve()
    workers = 8

    log("=== DWD SCHNEEHÖHE · SCHRITT 2 ===")
    log("Historischer Cache bis 31.12.2025")
    log("Hydrologisches Jahr: 01.11.–31.10.")
    log("Noch keine Website-Änderung.")
    log()

    metadata = parse_metadata(request_text(META_URL))
    current_kl_ids = list_recent_station_ids()
    overview = parse_overview(request_text(OVERVIEW_URL))
    historical = list_historical_files()

    candidates = sorted(
        station_id
        for station_id in current_kl_ids
        if station_id in overview
        and overview[station_id].net_years >= 30
        and station_id in metadata
    )

    log(f"Aktuelle DWD-KL-Stationen: {len(current_kl_ids):,}")
    log(f"SHK_TAG-Übersicht >=30 Jahre: {len(overview):,}")
    log(f"Vollaufbau-Kandidaten >=30 Netto-Jahre: {len(candidates):,}")

    # The preceding probe produced 299 candidates. Allow a small amount of
    # natural DWD inventory drift, but fail loudly on a major mismatch.
    if not 280 <= len(candidates) <= 330:
        raise RuntimeError(
            f"Kandidatenzahl unplausibel: {len(candidates)} "
            "(erwartet grob 299)."
        )

    missing_historical = [
        station_id
        for station_id in candidates
        if station_id not in historical
    ]
    if missing_historical:
        log(
            f"FEHLER: {len(missing_historical)} Kandidaten ohne "
            "historisches KL-Archiv."
        )
        for station_id in missing_historical[:30]:
            log(f"  - {station_id} {metadata[station_id].name}")
        raise RuntimeError(
            "Nicht alle Vollaufbau-Kandidaten besitzen historische KL-Dateien."
        )

    CACHE_DIR_ABS = root / CACHE_DIR
    CACHE_DIR_ABS.mkdir(parents=True, exist_ok=True)

    log()
    log("Baue/prüfe Stations-Caches ...")

    results: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                build_one_station,
                root,
                station_id,
                metadata[station_id],
                overview[station_id],
                historical[station_id],
            ): station_id
            for station_id in candidates
        }

        for index, future in enumerate(as_completed(futures), start=1):
            station_id = futures[future]
            try:
                sid, info, error = future.result()
            except Exception as exc:
                sid, info, error = station_id, None, str(exc)

            if info:
                results[sid] = info
            if error:
                errors.append(f"{sid}: {error}")

            if index % 20 == 0 or index == len(futures):
                cached_count = sum(
                    bool(item.get("cached"))
                    for item in results.values()
                )
                built_count = len(results) - cached_count
                log(
                    f"  {index:,}/{len(futures):,} | "
                    f"neu gebaut {built_count:,} | "
                    f"aus Cache {cached_count:,} | "
                    f"Fehler {len(errors):,}"
                )

    if errors:
        log()
        log("FEHLER BEIM HISTORISCHEN VOLLAUFBAU:")
        for error in errors[:50]:
            log(f"  - {error}")
        raise RuntimeError(
            f"{len(errors)} Stations-Caches konnten nicht aufgebaut werden."
        )

    if len(results) != len(candidates):
        raise RuntimeError(
            f"Nur {len(results)}/{len(candidates)} Stations-Caches vorhanden."
        )

    # Remove stale station cache files not part of the current candidate set.
    candidate_set = set(candidates)
    for old in CACHE_DIR_ABS.glob("*.json.gz"):
        if old.name.endswith(".json.gz"):
            station_id = old.name[:5]
            if station_id not in candidate_set:
                old.unlink()

    log()
    log("Berechne Qualitätsdiagnostik der hydrologischen Jahre ...")

    station_summaries = []
    qc_by_station: dict[str, dict[str, Any]] = {}

    network_counts = {
        str(int(round(threshold * 100))): 0
        for threshold in COVERAGE_THRESHOLDS
    }
    reference_all30 = {
        str(int(round(threshold * 100))): 0
        for threshold in COVERAGE_THRESHOLDS
    }
    reference_atleast25 = {
        str(int(round(threshold * 100))): 0
        for threshold in COVERAGE_THRESHOLDS
    }

    total_rows = 0

    for station_id in candidates:
        payload = read_gzip_json(
            cache_file_for_station(root, station_id)
        )
        total_rows += len(payload["rows"])
        qc = station_qc(payload)
        qc_by_station[station_id] = qc

        for threshold in COVERAGE_THRESHOLDS:
            key = str(int(round(threshold * 100)))
            if qc["complete_year_counts"][key] >= 30:
                network_counts[key] += 1
            if qc["reference_year_counts"][key] == 30:
                reference_all30[key] += 1
            if qc["reference_year_counts"][key] >= 25:
                reference_atleast25[key] += 1

        station_summaries.append(
            {
                "station_id": station_id,
                "name": metadata[station_id].name,
                "state": metadata[station_id].state,
                "height": metadata[station_id].height,
                "overview_net_years": round(
                    overview[station_id].net_years,
                    2,
                ),
                "row_count": len(payload["rows"]),
                "qc": qc,
                "source_files": payload["source_files"],
            }
        )

    states = Counter(
        metadata[station_id].state
        for station_id in candidates
    )

    manifest = {
        "version": CACHE_VERSION,
        "built_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "historical_through": HISTORICAL_THROUGH.isoformat(),
        "candidate_rule": (
            "current DWD daily-KL network + SHK_TAG overview "
            ">=30 net years"
        ),
        "candidate_count": len(candidates),
        "total_valid_shk_rows": total_rows,
        "hydrological_year": "01-11 to 31-10",
        "last_complete_hydrological_year": LAST_COMPLETE_HYDRO_YEAR,
        "reference_hydrological_years": [
            REFERENCE_START,
            REFERENCE_END,
        ],
        "coverage_diagnostics": {
            "stations_with_at_least_30_hydro_years": network_counts,
            "stations_with_all_30_reference_years": reference_all30,
            "stations_with_at_least_25_reference_years": reference_atleast25,
        },
        "states": dict(states),
        "stations": station_summaries,
    }

    write_json(root / MANIFEST, manifest)

    log()
    log("=" * 92)
    log("HISTORISCHER SCHNEEHÖHEN-CACHE FERTIG")
    log("=" * 92)
    log(f"Stations-Caches: {len(candidates):,}")
    log(f"Gültige historische SHK_TAG-Tageswerte: {total_rows:,}")
    log(f"Cache-Verzeichnis: {CACHE_DIR}")
    log(f"Manifest: {MANIFEST}")
    log()

    log("Stationen mit mindestens 30 hydrologischen Jahren:")
    for threshold in COVERAGE_THRESHOLDS:
        key = str(int(round(threshold * 100)))
        log(
            f"  >= {key}% Tagesabdeckung: "
            f"{network_counts[key]:,}/{len(candidates):,}"
        )

    log()
    log("Referenz 1991–2020 vollständig verfügbar:")
    for threshold in COVERAGE_THRESHOLDS:
        key = str(int(round(threshold * 100)))
        log(
            f"  alle 30 Referenzjahre >= {key}%: "
            f"{reference_all30[key]:,}/{len(candidates):,}"
        )
        log(
            f"  mindestens 25/30 Referenzjahre >= {key}%: "
            f"{reference_atleast25[key]:,}/{len(candidates):,}"
        )

    log()
    log("Bundesländer der 299/aktuellen Kandidaten:")
    for state in GERMAN_STATES:
        log(f"  {state}: {states.get(state, 0)}")

    log()
    log("Stichproben Qualitätskontrolle:")
    preferred = (
        "05792",  # Zugspitze
        "00722",  # Brocken
        "01358",  # Fichtelberg Sachsen
        "05371",  # Wasserkuppe
        "03730",  # Oberstdorf
        "02483",  # Kahler Asten
        "01443",  # Freiburg
        "01420",  # Frankfurt
        "04336",  # Saarbrücken-Ensheim
    )

    for station_id in preferred:
        if station_id not in qc_by_station:
            continue
        qc = qc_by_station[station_id]
        meta = metadata[station_id]
        log(
            f"  {station_id} | {meta.name} | {meta.state} | "
            f"hydrol. Jahre >=90/95/98%: "
            f"{qc['complete_year_counts']['90']}/"
            f"{qc['complete_year_counts']['95']}/"
            f"{qc['complete_year_counts']['98']} | "
            f"Ref 1991–2020 >=90/95/98%: "
            f"{qc['reference_year_counts']['90']}/"
            f"{qc['reference_year_counts']['95']}/"
            f"{qc['reference_year_counts']['98']}"
        )

    log()
    log(
        "Nächster Schritt erst nach Sichtung dieses Logs: "
        "Qualitätsgrenze festlegen und daraus die kompakten "
        "Schneehöhen-Profile berechnen."
    )
    return 0


def self_test() -> None:
    assert hydro_year_for_day(date(2025, 10, 31)) == 2025
    assert hydro_year_for_day(date(2025, 11, 1)) == 2026
    assert hydro_year_for_day(date(2026, 1, 15)) == 2026

    start, end = hydro_year_bounds(2026)
    assert start == date(2025, 11, 1)
    assert end == date(2026, 10, 31)
    assert expected_days_in_hydro_year(2024) == 366
    assert expected_days_in_hydro_year(2025) == 365

    rows = []
    start = date(2019, 11, 1)
    end = date(2020, 10, 31)
    day = start
    while day <= end:
        rows.append([day.isoformat(), 0.0])
        day += timedelta(days=1)

    coverage = coverage_by_hydro_year(rows)
    assert 2020 in coverage
    assert coverage[2020][0] == 366
    assert abs(coverage[2020][2] - 1.0) < 1e-12

    # Missing remains missing; zero is a valid measured snow depth.
    product = (
        "STATIONS_ID;MESS_DATUM;QN_4;SHK_TAG;eor\n"
        "1420;20250101;10;0;eor\n"
        "1420;20250102;10;12;eor\n"
        "1420;20250103;10;-999;eor\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "produkt_klima_tag_test.txt",
            product,
        )

    parsed = parse_historical_zip(buffer.getvalue())
    assert len(parsed) == 2
    assert parsed[date(2025, 1, 1)] == 0.0
    assert parsed[date(2025, 1, 2)] == 12.0
    assert date(2025, 1, 3) not in parsed

    print("DWD snow-height historical cache self-test OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
