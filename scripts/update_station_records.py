from __future__ import annotations

import argparse
import csv
import heapq
import io
import json
import os
import re
import tempfile
import threading
import time
import zipfile
from bisect import bisect_right
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import requests

from dwd_common import USER_AGENT, download, read_json

BASE_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl"
)
HISTORICAL_URL = f"{BASE_URL}/historical/"
RECENT_URL = f"{BASE_URL}/recent/"
METADATA_URL = f"{RECENT_URL}KL_Tageswerte_Beschreibung_Stationen.txt"

HISTORICAL_PATTERN = re.compile(
    r'href=["\'](tageswerte_KL_\d{5}_\d{8}_\d{8}_hist\.zip)["\']',
    re.IGNORECASE,
)
RECENT_PATTERN = re.compile(
    r'href=["\'](tageswerte_KL_\d{5}_akt\.zip)["\']',
    re.IGNORECASE,
)
STATION_ID_PATTERN = re.compile(r"tageswerte_KL_(\d{5})_", re.IGNORECASE)

TOP_K = 50
STATE_VERSION = 1
FULL_REBUILD_AFTER_DAYS = 45

STATE_ORDER = [
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
]
INTERNAL_UNKNOWN = "__Unbekannt__"
AREAS = ["Deutschland", *STATE_ORDER]

STATE_ALIASES = {
    "Baden-Wuerttemberg": "Baden-Württemberg",
    "Baden Württemberg": "Baden-Württemberg",
    "Mecklenburg Vorpommern": "Mecklenburg-Vorpommern",
    "Nordrhein Westfalen": "Nordrhein-Westfalen",
    "Rheinland Pfalz": "Rheinland-Pfalz",
    "Sachsen Anhalt": "Sachsen-Anhalt",
    "Schleswig Holstein": "Schleswig-Holstein",
    "Thueringen": "Thüringen",
}

METRICS = {
    "txk_high": {"column": "TXK", "direction": "desc", "unit": "°C", "label": "Höchste Tagesmaxima"},
    "tnk_low": {"column": "TNK", "direction": "asc", "unit": "°C", "label": "Tiefste Tagesminima"},
    "tnk_high": {"column": "TNK", "direction": "desc", "unit": "°C", "label": "Höchste Tagestiefsttemperaturen"},
    "rsk_high": {"column": "RSK", "direction": "desc", "unit": "mm", "label": "Höchste Tagesniederschläge"},
}

PERIODS = [
    {"id": "all", "label": "Gesamte Messreihe", "kind": "all"},
    {"id": "year", "label": "Einzeljahr", "kind": "year"},
    {"id": "season-winter", "label": "Winter (DJF)", "kind": "season"},
    {"id": "season-spring", "label": "Frühling (MAM)", "kind": "season"},
    {"id": "season-summer", "label": "Sommer (JJA)", "kind": "season"},
    {"id": "season-autumn", "label": "Herbst (SON)", "kind": "season"},
    *[
        {"id": f"month-{month:02d}", "label": label, "kind": "month"}
        for month, label in enumerate(
            [
                "Januar", "Februar", "März", "April", "Mai", "Juni",
                "Juli", "August", "September", "Oktober", "November", "Dezember",
            ],
            start=1,
        )
    ],
]

_thread_local = threading.local()


class NoUsableProductFileError(ValueError):
    """A DWD archive is valid, but contains no daily climate product."""


@dataclass(frozen=True)
class MetadataSegment:
    key: str
    station_id: str
    start: date
    end: date
    height: Optional[int]
    latitude: Optional[float]
    longitude: Optional[float]
    name: str
    state: str


class MetadataIndex:
    def __init__(self, segments: list[MetadataSegment]):
        self.segments = segments
        self.by_station: dict[str, list[MetadataSegment]] = defaultdict(list)
        for segment in segments:
            self.by_station[segment.station_id].append(segment)
        self.starts: dict[str, list[date]] = {}
        for station_id, items in self.by_station.items():
            items.sort(key=lambda item: item.start)
            self.starts[station_id] = [item.start for item in items]

    def segment_for(self, station_id: str, day: date) -> MetadataSegment:
        items = self.by_station.get(station_id)
        if not items:
            return MetadataSegment(
                key=f"{station_id}:unknown",
                station_id=station_id,
                start=date(1800, 1, 1),
                end=date(2100, 12, 31),
                height=None,
                latitude=None,
                longitude=None,
                name=f"Station {station_id}",
                state=INTERNAL_UNKNOWN,
            )
        starts = self.starts[station_id]
        index = bisect_right(starts, day) - 1
        if index < 0:
            index = 0
        candidate = items[index]
        if candidate.start <= day <= candidate.end:
            return candidate
        # Metadata can occasionally contain small gaps. Use the closest period.
        return min(items, key=lambda item: min(abs((day - item.start).days), abs((day - item.end).days)))

    def public_dict(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for segment in self.segments:
            result[segment.key] = {
                "id": segment.station_id,
                "name": segment.name,
                "state": None if segment.state == INTERNAL_UNKNOWN else segment.state,
                "height": segment.height,
                "lat": segment.latitude,
                "lon": segment.longitude,
                "from": segment.start.isoformat(),
                "to": segment.end.isoformat(),
            }
        return result


@dataclass(frozen=True)
class Observation:
    day: date
    metadata_key: str
    state: str
    station_id: str
    values: dict[str, float]
    preliminary: bool


Entry = list[Any]  # [value, ISO date, metadata key, preliminary]


def atomic_write_json_compact(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def normalize_state(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    cleaned = STATE_ALIASES.get(cleaned, cleaned)
    return cleaned if cleaned in STATE_ORDER else INTERNAL_UNKNOWN


def parse_optional_int(value: str) -> Optional[int]:
    value = value.strip()
    try:
        number = int(float(value.replace(",", ".")))
    except ValueError:
        return None
    return None if number <= -999 else number


def parse_optional_float(value: str) -> Optional[float]:
    value = value.strip().replace(",", ".")
    try:
        number = float(value)
    except ValueError:
        return None
    return None if number <= -999 else number


def parse_metadata(content: bytes) -> MetadataIndex:
    """Liest die DWD-Stationsmetadaten robust aus dem Textformat.

    Der DWD richtet die Datenzeilen nicht immer exakt an den Zeichenpositionen
    der Kopfzeile aus. Deshalb werden zuerst die sechs numerischen Felder
    gelesen; Stationsname und Bundesland werden anschließend aus dem Rest der
    Zeile bestimmt. Ein optionales Feld wie ``Abgabe`` am Zeilenende wird
    ignoriert.
    """
    text = content.decode("latin-1", errors="replace")
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
        raise ValueError("DWD-Stationsmetadaten enthalten keine erkennbare Kopfzeile.")

    # Die ersten sechs Felder sind numerisch und lassen sich unabhängig von
    # wechselnden Spaltenbreiten zuverlässig erkennen.
    prefix_pattern = re.compile(
        r"^\s*(\d{1,5})\s+"          # Stations-ID
        r"(\d{8})\s+"                 # von_datum
        r"(\d{8})\s+"                 # bis_datum
        r"(-?\d+(?:[.,]\d+)?)\s+"    # Stationshöhe
        r"(-?\d+(?:[.,]\d+)?)\s+"    # Breite
        r"(-?\d+(?:[.,]\d+)?)\s+"    # Länge
        r"(.+?)\s*$"                    # Stationsname, Bundesland, ggf. Abgabe
    )

    state_candidates = sorted(
        set(STATE_ORDER) | set(STATE_ALIASES.keys()),
        key=len,
        reverse=True,
    )
    state_patterns = [
        (state, re.compile(rf"(?<!\S){re.escape(state)}(?=\s|$)"))
        for state in state_candidates
    ]

    segments: list[MetadataSegment] = []
    skipped_examples: list[str] = []

    for line in lines[header_index + 1 :]:
        match = prefix_pattern.match(line)
        if not match:
            # Trennzeilen, wiederholte Kopfzeilen und Leerzeilen sind normal.
            if line.strip() and not set(line.strip()) <= {"-", " "}:
                if len(skipped_examples) < 3:
                    skipped_examples.append(line[:180])
            continue

        station_text, start_text, end_text, height_text, lat_text, lon_text, tail = match.groups()
        try:
            start = datetime.strptime(start_text, "%Y%m%d").date()
            end = datetime.strptime(end_text, "%Y%m%d").date()
        except ValueError:
            continue

        # Das Bundesland steht nach dem Stationsnamen. Seit 2025 kann dahinter
        # noch eine zusätzliche Spalte (z. B. "Abgabe") folgen. Wir suchen
        # deshalb das am weitesten rechts stehende bekannte Bundesland.
        best_state: Optional[str] = None
        best_start = -1
        for raw_state, pattern in state_patterns:
            for state_match in pattern.finditer(tail):
                if state_match.start() > best_start:
                    best_start = state_match.start()
                    best_state = raw_state

        if best_state is None:
            station_name = tail.strip()
            state = INTERNAL_UNKNOWN
        else:
            station_name = tail[:best_start].strip()
            state = normalize_state(best_state)

        station_id = station_text.zfill(5)
        key = f"{station_id}:{start_text}"
        segments.append(
            MetadataSegment(
                key=key,
                station_id=station_id,
                start=start,
                end=end,
                height=parse_optional_int(height_text),
                latitude=parse_optional_float(lat_text),
                longitude=parse_optional_float(lon_text),
                name=station_name or f"Station {station_id}",
                state=state,
            )
        )

    if len(segments) < 300:
        detail = ""
        if skipped_examples:
            detail = " Beispiele nicht gelesener Zeilen: " + " | ".join(skipped_examples)
        raise RuntimeError(
            f"Unerwartet wenige Stationsmetadaten gelesen: {len(segments)}.{detail}"
        )

    known_states = sum(segment.state != INTERNAL_UNKNOWN for segment in segments)
    if known_states < max(100, int(len(segments) * 0.5)):
        raise RuntimeError(
            "Zu wenige Stationsmetadaten konnten einem Bundesland zugeordnet werden: "
            f"{known_states} von {len(segments)}."
        )

    return MetadataIndex(segments)


def thread_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        _thread_local.session = session
    return session


def download_station_zip(base_url: str, filename: str, attempts: int = 5) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = thread_session().get(base_url + filename, timeout=90)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 12))
    raise RuntimeError(f"{filename}: {last_error}")


def list_station_files(base_url: str, pattern: re.Pattern[str], minimum: int) -> list[str]:
    html = download(base_url, timeout=90).decode("utf-8", errors="replace")
    files = sorted(set(pattern.findall(html)))
    if len(files) < minimum:
        raise RuntimeError(f"Im DWD-Verzeichnis {base_url} wurden nur {len(files)} Dateien gefunden.")
    return files


def plausible(metric: str, value: float) -> bool:
    if metric.startswith("txk") or metric.startswith("tnk"):
        return -60.0 <= value <= 60.0
    if metric == "rsk_high":
        return 0.0 <= value <= 1000.0
    return False


def parse_station_zip(
    content: bytes,
    station_id_hint: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> list[Observation]:
    observations: list[Observation] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        product_files = [
            name for name in archive.namelist()
            if name.lower().endswith(".txt") and "produkt_klima_tag" in name.lower()
        ]
        if not product_files:
            required = {"STATIONS_ID", "MESS_DATUM", "TXK", "TNK", "RSK"}
            for name in archive.namelist():
                if not name.lower().endswith(".txt"):
                    continue
                try:
                    with archive.open(name) as candidate:
                        first_line = candidate.readline().decode("latin-1", errors="replace")
                    if required.issubset({part.strip() for part in first_line.split(";")}):
                        product_files.append(name)
                except (KeyError, OSError):
                    continue
        if not product_files:
            raise NoUsableProductFileError("keine auswertbare Produktdatei")

        with archive.open(product_files[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
            reader = csv.reader(text, delimiter=";")
            header = [column.strip() for column in next(reader)]
            required_columns = ["STATIONS_ID", "MESS_DATUM", "TXK", "TNK", "RSK"]
            missing = [column for column in required_columns if column not in header]
            if missing:
                raise ValueError(f"Spalten fehlen: {', '.join(missing)}")
            indices = {column: header.index(column) for column in required_columns}
            maximum_index = max(indices.values())

            for row in reader:
                if len(row) <= maximum_index:
                    continue
                date_text = row[indices["MESS_DATUM"]].strip()
                try:
                    day = datetime.strptime(date_text, "%Y%m%d").date()
                except ValueError:
                    continue
                if day < start_date or day > end_date:
                    continue
                station_raw = row[indices["STATIONS_ID"]].strip()
                station_id = station_raw.zfill(5) if station_raw else station_id_hint
                segment = metadata.segment_for(station_id, day)
                values: dict[str, float] = {}
                for metric, specification in METRICS.items():
                    column = specification["column"]
                    raw_value = row[indices[column]].strip().replace(",", ".")
                    try:
                        value = float(raw_value)
                    except ValueError:
                        continue
                    if plausible(metric, value):
                        values[metric] = round(value, 1)
                if values:
                    observations.append(
                        Observation(
                            day=day,
                            metadata_key=segment.key,
                            state=segment.state,
                            station_id=station_id,
                            values=values,
                            preliminary=preliminary,
                        )
                    )
    return observations


def season_for_month(month: int) -> str:
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def entry_uid(entry: Entry) -> tuple[str, str]:
    return str(entry[1]), str(entry[2])


class TopK:
    def __init__(self, metric: str, k: int = TOP_K):
        self.metric = metric
        self.k = k
        self.direction = str(METRICS[metric]["direction"])
        self.heap: list[tuple[float, int, int, Entry]] = []
        self.seen: set[tuple[str, str]] = set()

    def _score(self, entry: Entry) -> tuple[float, int, int]:
        value = float(entry[0])
        metric_score = value if self.direction == "desc" else -value
        day = date.fromisoformat(str(entry[1]))
        station_text = str(entry[2]).split(":", 1)[0]
        station_number = int(station_text) if station_text.isdigit() else 99999
        # Higher score is better. Earlier dates and lower IDs win exact ties.
        return metric_score, -day.toordinal(), -station_number

    def add(self, entry: Entry) -> None:
        uid = entry_uid(entry)
        if uid in self.seen:
            return
        score = self._score(entry)
        item = (*score, entry)
        if len(self.heap) < self.k:
            heapq.heappush(self.heap, item)
            self.seen.add(uid)
            return
        if item[:3] <= self.heap[0][:3]:
            return
        removed = heapq.heapreplace(self.heap, item)
        self.seen.remove(entry_uid(removed[3]))
        self.seen.add(uid)

    def extend(self, entries: Iterable[Entry]) -> None:
        for entry in entries:
            self.add(list(entry))

    def entries(self) -> list[Entry]:
        entries = [item[3] for item in self.heap]
        if self.direction == "desc":
            return sorted(
                entries,
                key=lambda entry: (
                    -float(entry[0]),
                    str(entry[1]),
                    int(str(entry[2]).split(":", 1)[0]) if str(entry[2]).split(":", 1)[0].isdigit() else 99999,
                ),
            )
        return sorted(
            entries,
            key=lambda entry: (
                float(entry[0]),
                str(entry[1]),
                int(str(entry[2]).split(":", 1)[0]) if str(entry[2]).split(":", 1)[0].isdigit() else 99999,
            ),
        )


class PeriodAccumulator:
    """Top lists per metric, internal state and all/month/season period."""

    def __init__(self):
        self.data: dict[str, dict[str, dict[str, TopK]]] = defaultdict(
            lambda: defaultdict(dict)
        )

    def _bucket(self, metric: str, state: str, period: str) -> TopK:
        bucket = self.data[metric][state].get(period)
        if bucket is None:
            bucket = TopK(metric)
            self.data[metric][state][period] = bucket
        return bucket

    def add(self, observation: Observation) -> None:
        state = observation.state if observation.state in STATE_ORDER else INTERNAL_UNKNOWN
        periods = (
            "all",
            f"month-{observation.day.month:02d}",
            f"season-{season_for_month(observation.day.month)}",
        )
        day_text = observation.day.isoformat()
        for metric, value in observation.values.items():
            entry: Entry = [value, day_text, observation.metadata_key, 1 if observation.preliminary else 0]
            for period in periods:
                self._bucket(metric, state, period).add(entry)

    def load_serialized(self, serialized: dict[str, Any]) -> None:
        for metric, states in serialized.items():
            if metric not in METRICS:
                continue
            for state, periods in states.items():
                for period, entries in periods.items():
                    self._bucket(metric, state, period).extend(entries)

    def serialized_internal(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for metric in METRICS:
            metric_result: dict[str, Any] = {}
            for state, periods in self.data.get(metric, {}).items():
                state_result = {period: bucket.entries() for period, bucket in periods.items()}
                if state_result:
                    metric_result[state] = state_result
            result[metric] = metric_result
        return result

    def public_lists(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        internal_states = [*STATE_ORDER, INTERNAL_UNKNOWN]
        period_ids = [item["id"] for item in PERIODS if item["kind"] != "year"]
        for metric in METRICS:
            metric_result: dict[str, Any] = {}
            for state in STATE_ORDER:
                periods: dict[str, Any] = {}
                for period in period_ids:
                    bucket = self.data.get(metric, {}).get(state, {}).get(period)
                    periods[period] = bucket.entries() if bucket else []
                metric_result[state] = periods

            national_periods: dict[str, Any] = {}
            for period in period_ids:
                national = TopK(metric)
                for state in internal_states:
                    bucket = self.data.get(metric, {}).get(state, {}).get(period)
                    if bucket:
                        national.extend(bucket.entries())
                national_periods[period] = national.entries()
            metric_result["Deutschland"] = national_periods
            result[metric] = metric_result
        return result


class YearAccumulator:
    """Top lists per metric and state for one calendar year."""

    def __init__(self):
        self.data: dict[str, dict[str, TopK]] = defaultdict(dict)

    def _bucket(self, metric: str, state: str) -> TopK:
        bucket = self.data[metric].get(state)
        if bucket is None:
            bucket = TopK(metric)
            self.data[metric][state] = bucket
        return bucket

    def add(self, observation: Observation) -> None:
        state = observation.state if observation.state in STATE_ORDER else INTERNAL_UNKNOWN
        day_text = observation.day.isoformat()
        for metric, value in observation.values.items():
            self._bucket(metric, state).add(
                [value, day_text, observation.metadata_key, 1 if observation.preliminary else 0]
            )

    def public_lists(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for metric in METRICS:
            metric_result: dict[str, Any] = {}
            for state in STATE_ORDER:
                bucket = self.data.get(metric, {}).get(state)
                metric_result[state] = bucket.entries() if bucket else []
            national = TopK(metric)
            for state in [*STATE_ORDER, INTERNAL_UNKNOWN]:
                bucket = self.data.get(metric, {}).get(state)
                if bucket:
                    national.extend(bucket.entries())
            metric_result["Deutschland"] = national.entries()
            result[metric] = metric_result
        return result


def better(metric: str, new_value: float, old_value: float) -> bool:
    return new_value > old_value if METRICS[metric]["direction"] == "desc" else new_value < old_value


def update_best(best: dict[str, dict[str, Entry]], metric: str, station_id: str, entry: Entry) -> None:
    previous = best[metric].get(station_id)
    if previous is None or better(metric, float(entry[0]), float(previous[0])):
        best[metric][station_id] = entry
    elif previous is not None and float(entry[0]) == float(previous[0]) and str(entry[1]) < str(previous[1]):
        best[metric][station_id] = entry


def iter_downloaded_observations(
    filenames: list[str],
    base_url: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
    max_workers: int,
) -> Iterator[list[Observation]]:
    processed = 0
    skipped: list[str] = []
    batch_size = max(max_workers * 3, 12)
    for batch_start in range(0, len(filenames), batch_size):
        batch = filenames[batch_start : batch_start + batch_size]
        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for filename in batch:
                match = STATION_ID_PATTERN.search(filename)
                station_id = match.group(1) if match else "00000"
                future = executor.submit(
                    _download_and_parse,
                    base_url,
                    filename,
                    station_id,
                    metadata,
                    start_date,
                    end_date,
                    preliminary,
                )
                futures[future] = filename
            for future in as_completed(futures):
                filename = futures[future]
                try:
                    rows = future.result()
                    if rows:
                        yield rows
                except NoUsableProductFileError as exc:
                    skipped.append(f"{filename}: {exc}")
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{filename}: {exc}")
                processed += 1
                if processed % 50 == 0 or processed == len(filenames):
                    print(f"  verarbeitet: {processed}/{len(filenames)}")
        if failures:
            preview = "\n".join(failures[:10])
            raise RuntimeError(
                f"{len(failures)} DWD-Archive konnten nicht verarbeitet werden.\n{preview}"
            )
    if skipped:
        print(f"Warnung: {len(skipped)} Archive ohne Produktdatei übersprungen.")
        for message in skipped[:8]:
            print(f"  - {message}")


def _download_and_parse(
    base_url: str,
    filename: str,
    station_id: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> list[Observation]:
    content = download_station_zip(base_url, filename)
    return parse_station_zip(content, station_id, metadata, start_date, end_date, preliminary)


def state_is_stale(state: dict[str, Any], current_year: int) -> bool:
    if state.get("version") != STATE_VERSION:
        return True
    if state.get("base_through_year") != current_year - 1:
        return True
    built_at = state.get("built_at")
    if not built_at:
        return True
    try:
        built = datetime.fromisoformat(str(built_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - built > timedelta(days=FULL_REBUILD_AFTER_DAYS)


def write_year_file(root: Path, year: int, accumulator: YearAccumulator) -> None:
    payload = {
        "version": 1,
        "year": year,
        "top_lists": accumulator.public_lists(),
    }
    atomic_write_json_compact(root / "station_records_years" / f"{year}.json", payload)


def full_rebuild(root: Path, metadata: MetadataIndex, current_year: int, max_workers: int) -> dict[str, Any]:
    print("Stationsrekorde: vollständiger historischer Neuaufbau")
    files = list_station_files(HISTORICAL_URL, HISTORICAL_PATTERN, minimum=500)
    print(f"Historische DWD-Archive: {len(files)}")
    base_end = date(current_year - 1, 12, 31)
    base_accumulator = PeriodAccumulator()
    year_accumulators: dict[int, YearAccumulator] = {}
    baselines: dict[str, dict[str, Entry]] = {metric: {} for metric in METRICS}
    observation_count = 0
    data_start: Optional[date] = None
    data_end: Optional[date] = None

    def consume(observation: Observation) -> None:
        nonlocal observation_count, data_start, data_end
        observation_count += 1
        data_start = observation.day if data_start is None else min(data_start, observation.day)
        data_end = observation.day if data_end is None else max(data_end, observation.day)
        base_accumulator.add(observation)
        year_accumulators.setdefault(observation.day.year, YearAccumulator()).add(observation)
        day_text = observation.day.isoformat()
        for metric, value in observation.values.items():
            update_best(
                baselines,
                metric,
                observation.station_id,
                [value, day_text, observation.metadata_key, 1 if observation.preliminary else 0],
            )

    for observations in iter_downloaded_observations(
        files,
        HISTORICAL_URL,
        metadata,
        date(1750, 1, 1),
        base_end,
        preliminary=False,
        max_workers=max_workers,
    ):
        for observation in observations:
            consume(observation)

    # Around the turn of the year the historical directory can lag behind.
    # If it does, supplement the previous calendar year from the Recent files.
    if data_end is None or data_end < base_end:
        recent_files = list_station_files(RECENT_URL, RECENT_PATTERN, minimum=300)
        print(
            f"Historische Daten reichen nur bis {data_end}; "
            f"ergänze {current_year - 1} aus {len(recent_files)} Recent-Archiven."
        )
        for observations in iter_downloaded_observations(
            recent_files,
            RECENT_URL,
            metadata,
            date(current_year - 1, 1, 1),
            base_end,
            preliminary=True,
            max_workers=max_workers,
        ):
            for observation in observations:
                consume(observation)

    years = sorted(year_accumulators)
    if not years:
        raise RuntimeError("Aus den historischen DWD-Dateien wurden keine Rekorddaten gelesen.")
    year_dir = root / "station_records_years"
    year_dir.mkdir(parents=True, exist_ok=True)
    for year, accumulator in sorted(year_accumulators.items()):
        write_year_file(root, year, accumulator)
    for old_file in year_dir.glob("*.json"):
        if old_file.stem.isdigit() and int(old_file.stem) < current_year and int(old_file.stem) not in year_accumulators:
            old_file.unlink()

    state = {
        "version": STATE_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_through_year": current_year - 1,
        "historical_files": len(files),
        "historical_observations": observation_count,
        "historical_data_start": data_start.isoformat() if data_start else None,
        "historical_data_end": data_end.isoformat() if data_end else None,
        "available_years": years,
        "base_top_lists": base_accumulator.serialized_internal(),
        "station_baselines": baselines,
    }
    atomic_write_json_compact(root / "station_record_state.json", state)
    return state


def build_current_year(
    metadata: MetadataIndex,
    current_year: int,
    max_workers: int,
) -> tuple[PeriodAccumulator, YearAccumulator, dict[str, dict[str, Entry]], dict[str, Any]]:
    files = list_station_files(RECENT_URL, RECENT_PATTERN, minimum=300)
    print(f"Aktuelle DWD-Archive für Stationsrekorde: {len(files)}")
    observations_by_day: dict[date, list[Observation]] = defaultdict(list)

    for observations in iter_downloaded_observations(
        files,
        RECENT_URL,
        metadata,
        date(current_year, 1, 1),
        date.today(),
        preliminary=True,
        max_workers=max_workers,
    ):
        for observation in observations:
            observations_by_day[observation.day].append(observation)

    if not observations_by_day:
        raise RuntimeError(f"Keine DWD-Stationswerte für {current_year} gelesen.")

    all_days = sorted(observations_by_day)
    newest_raw_day = all_days[-1]
    reference_days = [
        day for day in all_days
        if newest_raw_day - timedelta(days=60) <= day <= newest_raw_day - timedelta(days=2)
    ]
    if len(reference_days) < 20:
        reference_days = all_days[-60:-2]
    counts = {day: len({item.station_id for item in items}) for day, items in observations_by_day.items()}
    if reference_days:
        sorted_counts = sorted(counts[day] for day in reference_days)
        reference_count = sorted_counts[len(sorted_counts) // 2]
    else:
        reference_count = max(counts.values())
    minimum_station_count = max(100, int(reference_count * 0.65))
    accepted_days = {day for day, count in counts.items() if count >= minimum_station_count}
    if not accepted_days:
        raise RuntimeError(
            f"Kein aktueller DWD-Tag erreicht die Mindestzahl von {minimum_station_count} Stationen."
        )

    current_accumulator = PeriodAccumulator()
    year_accumulator = YearAccumulator()
    current_best: dict[str, dict[str, Entry]] = {metric: {} for metric in METRICS}
    observation_count = 0
    for day in sorted(accepted_days):
        for observation in observations_by_day[day]:
            observation_count += 1
            current_accumulator.add(observation)
            year_accumulator.add(observation)
            day_text = observation.day.isoformat()
            for metric, value in observation.values.items():
                update_best(
                    current_best,
                    metric,
                    observation.station_id,
                    [value, day_text, observation.metadata_key, 1],
                )

    data_end = max(accepted_days)
    return current_accumulator, year_accumulator, current_best, {
        "recent_files": len(files),
        "current_year_observations": observation_count,
        "data_through": data_end.isoformat(),
        "newest_raw_dwd_date": newest_raw_day.isoformat(),
        "latest_station_count": counts[data_end],
        "minimum_station_count": minimum_station_count,
        "reference_station_count": reference_count,
    }


def combine_accumulators(base_serialized: dict[str, Any], current: PeriodAccumulator) -> PeriodAccumulator:
    combined = PeriodAccumulator()
    combined.load_serialized(base_serialized)
    combined.load_serialized(current.serialized_internal())
    return combined


def build_new_station_records(
    baselines: dict[str, dict[str, Entry]],
    current_best: dict[str, dict[str, Entry]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for metric in METRICS:
        records: list[dict[str, Any]] = []
        old_by_station = baselines.get(metric, {})
        for station_id, new_entry in current_best.get(metric, {}).items():
            old_entry = old_by_station.get(station_id)
            if old_entry is None:
                continue
            new_value = float(new_entry[0])
            old_value = float(old_entry[0])
            if not better(metric, new_value, old_value):
                continue
            improvement = new_value - old_value if METRICS[metric]["direction"] == "desc" else old_value - new_value
            records.append(
                {
                    "station_id": station_id,
                    "new": new_entry,
                    "old": old_entry,
                    "improvement": round(improvement, 1),
                }
            )
        records.sort(key=lambda item: (str(item["new"][1]), float(item["improvement"])), reverse=True)
        result[metric] = records
    return result


def update_station_records(root: Path, max_workers: int = 8, force_full: bool = False) -> dict[str, Any]:
    current_year = date.today().year
    metadata = parse_metadata(download(METADATA_URL, timeout=120))
    state_path = root / "station_record_state.json"
    state: dict[str, Any] = {}
    if state_path.exists():
        try:
            loaded = read_json(state_path)
            if isinstance(loaded, dict):
                state = loaded
        except (OSError, json.JSONDecodeError):
            state = {}

    rebuilt = force_full or state_is_stale(state, current_year)
    if rebuilt:
        state = full_rebuild(root, metadata, current_year, max_workers)
    else:
        print(
            "Stationsrekorde: historischer Zwischenspeicher wird verwendet "
            f"(Stand bis {state.get('base_through_year')})."
        )

    current_accumulator, current_year_accumulator, current_best, current_status = build_current_year(
        metadata, current_year, max_workers
    )
    combined = combine_accumulators(state["base_top_lists"], current_accumulator)
    write_year_file(root, current_year, current_year_accumulator)

    available_years = sorted(set(int(year) for year in state.get("available_years", [])) | {current_year})
    new_station_records = build_new_station_records(state["station_baselines"], current_best)
    payload = {
        "version": 1,
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_through": current_status["data_through"],
        "current_year": current_year,
        "source": "Deutscher Wetterdienst (DWD), Climate Data Center, tägliche KL-Stationsdaten",
        "source_note": "Werte des aktuellen Jahres stammen aus dem DWD-Recent-Verzeichnis und sind vorläufig.",
        "areas": AREAS,
        "periods": PERIODS,
        "parameters": [
            {
                "id": metric,
                "label": specification["label"],
                "unit": specification["unit"],
                "direction": specification["direction"],
            }
            for metric, specification in METRICS.items()
        ],
        "available_years": available_years,
        "stations": metadata.public_dict(),
        "top_lists": combined.public_lists(),
        "station_records_current_year": new_station_records,
    }
    atomic_write_json_compact(root / "station_records.json", payload)

    return {
        "ready": True,
        "data_through": current_status["data_through"],
        "current_year": current_year,
        "areas": len(AREAS),
        "parameters": len(METRICS),
        "available_years": len(available_years),
        "new_station_records": sum(len(items) for items in new_station_records.values()),
        "historical_rebuilt": rebuilt,
        "historical_files": state.get("historical_files"),
        "historical_observations": state.get("historical_observations"),
        **current_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Erstellt DWD-Stationsrekordlisten für das Climate Dashboard.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--full", action="store_true", help="Historischen Zwischenspeicher vollständig neu aufbauen")
    args = parser.parse_args()
    result = update_station_records(args.root, max_workers=args.workers, force_full=args.full)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
