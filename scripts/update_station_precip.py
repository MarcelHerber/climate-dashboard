from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import math
import os
import re
import tempfile
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from dwd_common import atomic_write_json, download, read_json
from update_station_records import (
    MetadataIndex,
    NoUsableProductFileError,
    Observation,
    download_station_zip,
    list_station_files,
    parse_metadata,
)

RR_BASE_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/more_precip"
)
RR_HISTORICAL_URL = f"{RR_BASE_URL}/historical/"
RR_RECENT_URL = f"{RR_BASE_URL}/recent/"
RR_METADATA_URL = f"{RR_RECENT_URL}RR_Tageswerte_Beschreibung_Stationen.txt"
RR_HISTORICAL_PATTERN = re.compile(
    r'href=["\'](tageswerte_RR_\d{5}_\d{8}_\d{8}_hist\.zip)["\']',
    re.IGNORECASE,
)
RR_RECENT_PATTERN = re.compile(
    r'href=["\'](tageswerte_RR_\d{5}_akt\.zip)["\']',
    re.IGNORECASE,
)
RR_STATION_ID_PATTERN = re.compile(r"tageswerte_RR_(\d{5})_", re.IGNORECASE)

STATE_VERSION = 4
MIN_REFERENCE_YEARS = 5
MIN_HISTORY_YEARS = 5
MIN_CURRENT_STATIONS = 500
CURRENT_DAY_FRACTION = 0.65


@dataclass(frozen=True)
class StationProfile:
    station_id: str
    name: str
    state: str | None
    height: int | None
    latitude: float | None
    longitude: float | None
    start_year: int
    end_year: int
    reference_years: int
    history_years: int
    file: str


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


def station_id_from_filename(filename: str) -> str:
    match = RR_STATION_ID_PATTERN.search(filename)
    if not match:
        raise ValueError(f"Stations-ID kann aus Dateiname nicht gelesen werden: {filename}")
    return match.group(1)


def parse_rr_station_zip(
    content: bytes,
    station_id_hint: str,
    metadata: MetadataIndex,
    start_date: date,
    end_date: date,
    preliminary: bool,
) -> list[Observation]:
    """Liest tägliche Niederschlagssummen RS aus dem erweiterten DWD-RR-Netz."""
    observations: list[Observation] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        product_files: list[str] = []
        for name in archive.namelist():
            if not name.lower().endswith(".txt") or "produkt" not in name.lower():
                continue
            try:
                with archive.open(name) as candidate:
                    first_line = candidate.readline().decode("latin-1", errors="replace")
                columns = {part.strip() for part in first_line.split(";")}
                if {"STATIONS_ID", "MESS_DATUM", "RS"}.issubset(columns):
                    product_files.append(name)
            except (KeyError, OSError):
                continue
        if not product_files:
            raise NoUsableProductFileError("keine auswertbare RR-Produktdatei")

        with archive.open(product_files[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
            reader = csv.reader(text, delimiter=";")
            header = [column.strip() for column in next(reader)]
            required = ["STATIONS_ID", "MESS_DATUM", "RS"]
            missing = [column for column in required if column not in header]
            if missing:
                raise ValueError(f"Spalten fehlen: {', '.join(missing)}")
            indices = {column: header.index(column) for column in required}
            maximum_index = max(indices.values())
            for row in reader:
                if len(row) <= maximum_index:
                    continue
                try:
                    day = datetime.strptime(row[indices["MESS_DATUM"]].strip(), "%Y%m%d").date()
                except ValueError:
                    continue
                if day < start_date or day > end_date:
                    continue
                raw_value = row[indices["RS"]].strip().replace(",", ".")
                try:
                    value = float(raw_value)
                except ValueError:
                    continue
                if not 0.0 <= value <= 1000.0:
                    continue
                station_raw = row[indices["STATIONS_ID"]].strip()
                station_id = station_raw.zfill(5) if station_raw else station_id_hint
                segment = metadata.segment_for(station_id, day)
                observations.append(
                    Observation(
                        day=day,
                        metadata_key=segment.key,
                        state=segment.state,
                        station_id=station_id,
                        values={"rsk_high": round(value, 1)},
                        preliminary=preliminary,
                    )
                )
    return observations


def non_leap_index(day: date) -> int | None:
    if day.month == 2 and day.day == 29:
        return None
    offset = day.timetuple().tm_yday - 1
    if day.month > 2 and is_leap(day.year):
        offset -= 1
    return offset


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def labels_non_leap() -> list[str]:
    labels: list[str] = []
    cursor = date(2001, 1, 1)
    while cursor.year == 2001:
        labels.append(cursor.strftime("%m-%d"))
        cursor += timedelta(days=1)
    return labels


def cumulative(values: list[float]) -> list[float]:
    total = 0.0
    result: list[float] = []
    for value in values:
        total += value
        result.append(round(total, 1))
    return result


def round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def current_segment(metadata: MetadataIndex, station_id: str):
    return metadata.segment_for(station_id, date.today())


def observations_to_complete_curves(observations, current_year: int) -> dict[int, list[float]]:
    values_by_year: dict[int, list[float | None]] = defaultdict(lambda: [None] * 365)
    for observation in observations:
        if observation.day.year >= current_year:
            continue
        value = observation.values.get("rsk_high")
        if value is None:
            continue
        index = non_leap_index(observation.day)
        if index is None:
            continue
        values_by_year[observation.day.year][index] = float(value)

    curves: dict[int, list[float]] = {}
    for year, values in values_by_year.items():
        if all(value is not None for value in values):
            curves[year] = cumulative([float(value) for value in values])
    return curves


HISTORICAL_PERIOD_RANGES = {
    "spring": ("03-01", "05-31"),
    "summer": ("06-01", "08-31"),
    "autumn": ("09-01", "11-30"),
}


def build_historical_period_envelopes(curves: dict[int, list[float]]) -> dict[str, dict[str, Any]]:
    """Historische Hüllkurven, die am Beginn des gewählten Zeitraums bei 0 starten."""
    labels = labels_non_leap()
    label_index = {label: index for index, label in enumerate(labels)}
    result: dict[str, dict[str, Any]] = {}

    for period, (start_label, end_label) in HISTORICAL_PERIOD_RANGES.items():
        start_index = label_index[start_label]
        end_index = label_index[end_label]
        period_curves: dict[int, list[float]] = {}

        for year, curve in curves.items():
            if len(curve) <= end_index:
                continue
            base = curve[start_index - 1] if start_index > 0 else 0.0
            period_curves[year] = [
                round(curve[index] - base, 1)
                for index in range(start_index, end_index + 1)
            ]

        if not period_curves:
            continue

        historical_min: list[float] = []
        historical_max: list[float] = []
        historical_min_year: list[int] = []
        historical_max_year: list[int] = []

        for offset in range(end_index - start_index + 1):
            candidates = [(curve[offset], year) for year, curve in period_curves.items()]
            minimum = min(candidates, key=lambda item: (item[0], item[1]))
            maximum = max(candidates, key=lambda item: (item[0], -item[1]))
            historical_min.append(round(minimum[0], 1))
            historical_max.append(round(maximum[0], 1))
            historical_min_year.append(minimum[1])
            historical_max_year.append(maximum[1])

        result[period] = {
            "start_index": start_index,
            "end_index": end_index,
            "historical_min_cumulative": historical_min,
            "historical_max_cumulative": historical_max,
            "historical_min_year": historical_min_year,
            "historical_max_year": historical_max_year,
        }

    return result



def observations_to_monthly_history(observations, current_year: int) -> list[dict[str, Any]]:
    """Monatssummen je Jahr; nur vollständig vorliegende Kalendermonate erhalten einen Wert."""
    values_by_month: dict[tuple[int, int], dict[int, float]] = defaultdict(dict)
    for observation in observations:
        day = observation.day
        if day.year >= current_year:
            continue
        value = observation.values.get("rsk_high")
        if value is not None:
            values_by_month[(day.year, day.month)][day.day] = float(value)
    history: list[dict[str, Any]] = []
    for year in sorted({year for year, _ in values_by_month}):
        months: list[float | None] = []
        for month in range(1, 13):
            vals = values_by_month.get((year, month), {})
            days = calendar.monthrange(year, month)[1]
            complete = len(vals) == days and all(d in vals for d in range(1, days + 1))
            months.append(round(sum(vals[d] for d in range(1, days + 1)), 1) if complete else None)
        if any(v is not None for v in months):
            annual = round(sum(float(v) for v in months), 1) if all(v is not None for v in months) else None
            history.append({"year": year, "months": months, "annual": annual})
    return history


def build_profile_payload(
    station_id: str,
    observations,
    metadata: MetadataIndex,
    current_year: int,
) -> tuple[StationProfile, dict[str, Any]] | None:
    curves = observations_to_complete_curves(observations, current_year)
    monthly_history = observations_to_monthly_history(observations, current_year)
    if not curves:
        return None

    reference = {year: curve for year, curve in curves.items() if 1991 <= year <= 2020}
    if len(reference) < MIN_REFERENCE_YEARS or len(curves) < MIN_HISTORY_YEARS:
        return None

    years = sorted(curves)
    reference_years = sorted(reference)
    climate_mean = [
        round(sum(reference[year][index] for year in reference_years) / len(reference_years), 1)
        for index in range(365)
    ]

    historical_min: list[float] = []
    historical_max: list[float] = []
    historical_min_year: list[int] = []
    historical_max_year: list[int] = []
    for index in range(365):
        candidates = [(curve[index], year) for year, curve in curves.items()]
        minimum = min(candidates, key=lambda item: (item[0], item[1]))
        maximum = max(candidates, key=lambda item: (item[0], -item[1]))
        historical_min.append(round(minimum[0], 1))
        historical_max.append(round(maximum[0], 1))
        historical_min_year.append(minimum[1])
        historical_max_year.append(maximum[1])

    historical_periods = build_historical_period_envelopes(curves)

    segment = current_segment(metadata, station_id)
    profile = StationProfile(
        station_id=station_id,
        name=segment.name,
        state=None if segment.state == "__Unbekannt__" else segment.state,
        height=segment.height,
        latitude=segment.latitude,
        longitude=segment.longitude,
        start_year=years[0],
        end_year=years[-1],
        reference_years=len(reference_years),
        history_years=len(years),
        file=f"station_precip_climate/{station_id}.json",
    )
    payload = {
        "station_id": station_id,
        "name": profile.name,
        "state": profile.state,
        "height": profile.height,
        "latitude": profile.latitude,
        "longitude": profile.longitude,
        "history_start_year": years[0],
        "history_end_year": years[-1],
        "history_years": len(years),
        "reference_period": "1991-2020",
        "reference_years": len(reference_years),
        "reference_year_list": reference_years,
        "monthly_history": monthly_history,
        "climate_mean_cumulative": climate_mean,
        "historical_min_cumulative": historical_min,
        "historical_max_cumulative": historical_max,
        "historical_min_year": historical_min_year,
        "historical_max_year": historical_max_year,
        "historical_periods": historical_periods,
    }
    return profile, payload


def process_historical_station(
    filename: str,
    metadata: MetadataIndex,
    current_year: int,
) -> tuple[str, tuple[StationProfile, dict[str, Any]] | None, str | None]:
    station_id = station_id_from_filename(filename)
    try:
        content = download_station_zip(RR_HISTORICAL_URL, filename)
        observations = parse_rr_station_zip(
            content,
            station_id,
            metadata,
            date(1800, 1, 1),
            date(current_year - 1, 12, 31),
            preliminary=False,
        )
        return station_id, build_profile_payload(station_id, observations, metadata, current_year), None
    except NoUsableProductFileError as exc:
        return station_id, None, f"{filename}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return station_id, None, f"{filename}: {exc}"


def build_historical_baselines(
    root: Path,
    metadata: MetadataIndex,
    active_station_ids: set[str],
    current_year: int,
    max_workers: int,
) -> tuple[list[StationProfile], dict[str, Any]]:
    historical_files = list_station_files(RR_HISTORICAL_URL, RR_HISTORICAL_PATTERN, minimum=4000)
    selected = [
        filename for filename in historical_files
        if station_id_from_filename(filename) in active_station_ids
    ]
    if len(selected) < 1000:
        raise RuntimeError(f"Nur {len(selected)} historische RR-Dateien passen zu aktuellen Stationen.")

    target_dir = root / "station_precip_climate"
    target_dir.mkdir(parents=True, exist_ok=True)
    profiles: list[StationProfile] = []
    errors: list[str] = []

    print(f"Stationsniederschlag: {len(selected)} historische Stationsarchive werden verarbeitet.")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_historical_station, filename, metadata, current_year): filename
            for filename in selected
        }
        for index, future in enumerate(as_completed(futures), start=1):
            station_id, result, error = future.result()
            if error:
                errors.append(error)
            elif result is not None:
                profile, payload = result
                profiles.append(profile)
                atomic_write_json_compact(target_dir / f"{station_id}.json", payload)
            if index % 50 == 0 or index == len(futures):
                print(f"  historische Niederschlagsprofile: {index}/{len(futures)}")

    profiles.sort(key=lambda item: ((item.state or ""), item.name.casefold(), item.station_id))
    if len(profiles) < 500:
        examples = " | ".join(errors[:5])
        raise RuntimeError(
            f"Nur {len(profiles)} Stationsprofile erfüllen die Datenanforderungen. {examples}"
        )

    valid_ids = {profile.station_id for profile in profiles}
    for old_file in target_dir.glob("*.json"):
        if old_file.stem not in valid_ids:
            old_file.unlink()

    state = {
        "version": STATE_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_year": current_year,
        "active_files": len(active_station_ids),
        "historical_files_selected": len(selected),
        "profiles": len(profiles),
        "profile_ids": sorted(valid_ids),
        "errors": errors[:50],
    }
    atomic_write_json(root / "station_precip_state.json", state)
    return profiles, state


def state_is_stale(root: Path, current_year: int, force_full: bool) -> bool:
    if force_full:
        return True
    state_path = root / "station_precip_state.json"
    index_path = root / "station_precip_index.json"
    if not state_path.exists() or not index_path.exists():
        return True
    try:
        state = read_json(state_path)
        index = read_json(index_path)
    except (OSError, json.JSONDecodeError):
        return True
    if state.get("version") != STATE_VERSION or state.get("current_year") != current_year:
        return True
    if not index.get("ready") or not index.get("stations"):
        return True
    profile_ids = state.get("profile_ids") or []
    return any(not (root / "station_precip_climate" / f"{station_id}.json").exists() for station_id in profile_ids)


def load_profiles_from_index(root: Path) -> list[StationProfile]:
    index = read_json(root / "station_precip_index.json")
    profiles: list[StationProfile] = []
    for item in index.get("stations", []):
        profiles.append(
            StationProfile(
                station_id=item["id"],
                name=item["name"],
                state=item.get("state"),
                height=item.get("height"),
                latitude=item.get("latitude"),
                longitude=item.get("longitude"),
                start_year=item["start_year"],
                end_year=item["end_year"],
                reference_years=item["reference_years"],
                history_years=item["history_years"],
                file=item["file"],
            )
        )
    return profiles


def process_recent_station(
    filename: str,
    metadata: MetadataIndex,
    current_year: int,
) -> tuple[str, dict[date, float], str | None]:
    station_id = station_id_from_filename(filename)
    try:
        content = download_station_zip(RR_RECENT_URL, filename)
        observations = parse_rr_station_zip(
            content,
            station_id,
            metadata,
            date(current_year, 1, 1),
            date.today(),
            preliminary=True,
        )
        values = {
            observation.day: float(observation.values["rsk_high"])
            for observation in observations
            if "rsk_high" in observation.values
        }
        return station_id, values, None
    except NoUsableProductFileError as exc:
        return station_id, {}, f"{filename}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return station_id, {}, f"{filename}: {exc}"


def accepted_data_through(values_by_station: dict[str, dict[date, float]]) -> tuple[date, dict[str, Any]]:
    counts: dict[date, int] = defaultdict(int)
    for values in values_by_station.values():
        for day in values:
            counts[day] += 1
    if not counts:
        raise RuntimeError("Keine aktuellen Niederschlagswerte gelesen.")

    newest_raw = max(counts)
    reference_days = [
        day for day in counts
        if newest_raw - timedelta(days=60) <= day <= newest_raw - timedelta(days=2)
    ]
    reference_count = int(median([counts[day] for day in reference_days])) if reference_days else max(counts.values())
    minimum_count = max(MIN_CURRENT_STATIONS, int(reference_count * CURRENT_DAY_FRACTION))
    accepted = [day for day, count in counts.items() if count >= minimum_count]
    if not accepted:
        raise RuntimeError(
            f"Kein aktueller Niederschlagstag erreicht die Mindestzahl von {minimum_count} Stationen."
        )
    data_through = max(accepted)
    return data_through, {
        "newest_raw_dwd_date": newest_raw.isoformat(),
        "data_through": data_through.isoformat(),
        "latest_station_count": counts[data_through],
        "reference_station_count": reference_count,
        "minimum_station_count": minimum_count,
    }


def write_current_month_files(
    root: Path,
    current_year: int,
    data_through: date,
    profile_ids: set[str],
    values_by_station: dict[str, dict[date, float]],
) -> list[str]:
    output_dir = root / "station_precip_current"
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    for month in range(1, data_through.month + 1):
        days_in_month = (date(current_year + (month == 12), month % 12 + 1, 1) - date(current_year, month, 1)).days
        station_payload: dict[str, list[float | None]] = {}
        for station_id in sorted(profile_ids):
            values = values_by_station.get(station_id, {})
            month_values: list[float | None] = []
            has_value = False
            for day_number in range(1, days_in_month + 1):
                day = date(current_year, month, day_number)
                if day > data_through:
                    value = None
                else:
                    value = values.get(day)
                month_values.append(round_or_none(value))
                has_value = has_value or value is not None
            if has_value:
                station_payload[station_id] = month_values

        filename = f"{month:02d}.json"
        payload = {
            "year": current_year,
            "month": month,
            "data_through": data_through.isoformat(),
            "stations": station_payload,
        }
        atomic_write_json_compact(output_dir / filename, payload)
        written.append(filename)

    for old_file in output_dir.glob("*.json"):
        if old_file.name not in written:
            old_file.unlink()
    return written



def build_map_summaries(
    root: Path,
    profiles: list[StationProfile],
    current_year: int,
    data_through: date,
    current_files: list[str],
) -> dict[str, dict[str, Any]]:
    """Compact current-year values for the browser map; avoids hundreds of profile requests."""
    labels = labels_non_leap()
    last_label = data_through.strftime("%m-%d")
    try:
        last_index = labels.index(last_label)
    except ValueError:
        last_index = max(0, len([label for label in labels if label <= last_label]) - 1)
    totals: dict[str, float] = defaultdict(float)
    valid_days: dict[str, int] = defaultdict(int)
    for filename in current_files:
        payload = read_json(root / "station_precip_current" / filename)
        month = int(payload["month"])
        for station_id, values in (payload.get("stations") or {}).items():
            for day_number, value in enumerate(values, start=1):
                day = date(current_year, month, day_number)
                if day > data_through:
                    break
                if value is None:
                    continue
                totals[station_id] += float(value)
                valid_days[station_id] += 1
    expected_days = last_index + 1
    result: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        climate_value = None
        climate_curve: list[float | None] = []
        try:
            historical = read_json(root / profile.file)
            raw_curve = historical.get("climate_mean_cumulative") or []
            climate_curve = [round(float(value), 1) if value is not None else None for value in raw_curve]
            if last_index < len(climate_curve) and climate_curve[last_index] is not None:
                climate_value = float(climate_curve[last_index])
        except (OSError, ValueError, TypeError):
            climate_value = None
            climate_curve = []
        current_total = round(totals.get(profile.station_id, 0.0), 1)
        deviation = None
        if climate_value and climate_value > 0:
            deviation = round((current_total / climate_value - 1.0) * 100.0, 1)

        result[profile.station_id] = {
            "current_total": current_total,
            "climate_mean_to_date": round(climate_value, 1) if climate_value is not None else None,
            "deviation_percent": deviation,
            "valid_days": valid_days.get(profile.station_id, 0),
            "missing_days": max(0, expected_days - valid_days.get(profile.station_id, 0)),
            # Die 365 kumulierten Klimawerte erlauben im Browser beliebige Zeiträume,
            # ohne für jede Kartenstation ein separates historisches Profil nachzuladen.
            "climate_mean_cumulative": climate_curve,
        }
    return result

def build_index(
    root: Path,
    profiles: list[StationProfile],
    current_year: int,
    current_status: dict[str, Any],
    current_files: list[str],
    historical_state: dict[str, Any],
) -> dict[str, Any]:
    states = sorted({profile.state for profile in profiles if profile.state})
    data_through = date.fromisoformat(current_status["data_through"])
    map_summaries = build_map_summaries(root, profiles, current_year, data_through, current_files)
    index = {
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_year": current_year,
        "data_through": current_status["data_through"],
        "labels": labels_non_leap(),
        "reference_period": "1991-2020",
        "historical_band": "Minimum und Maximum aller vollständig vorliegenden Jahre",
        "complete_year_rule": "Jahr nur bei 365 gültigen Tageswerten; 29. Februar wird ausgelassen",
        "minimum_reference_years": MIN_REFERENCE_YEARS,
        "source": "DWD CDC, tägliche Niederschlagsbeobachtungen des erweiterten RR-Netzes (RS)",
        "source_note": (
            "Verwendet werden DWD-Stationen und rechtlich sowie qualitativ gleichgestellte Partnernetze. "
            "Historische Kurven stammen aus dem qualitätsgeprüften RR-Verzeichnis historical; "
            "das laufende Jahr stammt aus recent und ist vorläufig. Frei wählbare Zeiträume werden "
            "gegen exakt denselben Kalenderabschnitt des stationsbezogenen Mittels 1991–2020 verglichen."
        ),
        "states": states,
        "current_files": [f"station_precip_current/{name}" for name in current_files],
        "stations": [
            {
                "id": profile.station_id,
                "name": profile.name,
                "state": profile.state,
                "height": profile.height,
                "latitude": profile.latitude,
                "longitude": profile.longitude,
                "start_year": profile.start_year,
                "end_year": profile.end_year,
                "reference_years": profile.reference_years,
                "history_years": profile.history_years,
                "file": profile.file,
                "map": map_summaries.get(profile.station_id, {}),
            }
            for profile in profiles
        ],
        "status": {
            **current_status,
            "profile_count": len(profiles),
            "historical_built_at": historical_state.get("built_at"),
        },
    }
    atomic_write_json(root / "station_precip_index.json", index)
    return index


def update_station_precip(root: Path, max_workers: int = 8, force_full: bool = False) -> dict[str, Any]:
    current_year = date.today().year
    metadata = parse_metadata(download(RR_METADATA_URL, timeout=180))
    recent_files = list_station_files(RR_RECENT_URL, RR_RECENT_PATTERN, minimum=1500)
    active_station_ids = {station_id_from_filename(filename) for filename in recent_files}

    rebuilt = state_is_stale(root, current_year, force_full)
    if rebuilt:
        profiles, historical_state = build_historical_baselines(
            root,
            metadata,
            active_station_ids,
            current_year,
            max_workers,
        )
    else:
        profiles = load_profiles_from_index(root)
        historical_state = read_json(root / "station_precip_state.json")
        print(
            "Stationsniederschlag: historische Kurven werden aus dem Zwischenspeicher verwendet "
            f"({len(profiles)} Stationen)."
        )

    profile_ids = {profile.station_id for profile in profiles}
    selected_recent = [filename for filename in recent_files if station_id_from_filename(filename) in profile_ids]
    values_by_station: dict[str, dict[date, float]] = {}
    errors: list[str] = []

    print(f"Stationsniederschlag: {len(selected_recent)} aktuelle Stationsarchive werden verarbeitet.")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_recent_station, filename, metadata, current_year): filename
            for filename in selected_recent
        }
        for index, future in enumerate(as_completed(futures), start=1):
            station_id, values, error = future.result()
            if error:
                errors.append(error)
            if values:
                values_by_station[station_id] = values
            if index % 50 == 0 or index == len(futures):
                print(f"  aktuelle Niederschlagsstationen: {index}/{len(futures)}")

    data_through, current_status = accepted_data_through(values_by_station)
    current_files = write_current_month_files(
        root,
        current_year,
        data_through,
        profile_ids,
        values_by_station,
    )
    index = build_index(
        root,
        profiles,
        current_year,
        current_status,
        current_files,
        historical_state,
    )

    return {
        "rebuilt_historical": rebuilt,
        "station_count": len(profiles),
        "data_through": data_through.isoformat(),
        "current_files": len(current_files),
        "recent_files": len(selected_recent),
        "recent_errors": errors[:20],
        "latest_station_count": current_status["latest_station_count"],
        "minimum_station_count": current_status["minimum_station_count"],
        "reference_period": index["reference_period"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Erzeugt Stations-Niederschlagskurven für das Climate Dashboard.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    result = update_station_precip(args.root, max_workers=args.workers, force_full=args.full)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
