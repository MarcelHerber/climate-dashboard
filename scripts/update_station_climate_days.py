from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from dwd_common import atomic_write_json, download, read_json
from update_station_records import (
    HISTORICAL_PATTERN,
    HISTORICAL_URL,
    METADATA_URL,
    RECENT_PATTERN,
    RECENT_URL,
    STATION_ID_PATTERN,
    MetadataIndex,
    NoUsableProductFileError,
    download_station_zip,
    list_station_files,
    parse_metadata,
    parse_station_zip,
)

STATE_VERSION = 3
MIN_PROFILE_COUNT = 150
MIN_CURRENT_STATIONS = 100
CURRENT_DAY_FRACTION = 0.65
HISTORICAL_REBUILD_DAYS = 45
MIN_PERIOD_COVERAGE = 0.98
REFERENCE_START = 1991
REFERENCE_END = 2020

# Die Namen entsprechen der gewünschten Dashboard-Terminologie. Bei 30, 35
# und 40 °C werden zusätzlich die DWD-Bezeichnungen im Hinweis genannt.
CLIMATE_DAYS: list[dict[str, Any]] = [
    {
        "id": "frost",
        "label": "Frosttage",
        "short_label": "Frosttag",
        "field": "tn",
        "operator": "lt",
        "threshold": 0.0,
        "definition": "Tmin < 0 °C",
        "bit": 0,
        "color": "#4f74c8",
    },
    {
        "id": "ice",
        "label": "Eistage",
        "short_label": "Eistag",
        "field": "tx",
        "operator": "lt",
        "threshold": 0.0,
        "definition": "Tmax < 0 °C",
        "bit": 1,
        "color": "#7450a8",
    },
    {
        "id": "summer",
        "label": "Sommertage",
        "short_label": "Sommertag",
        "field": "tx",
        "operator": "ge",
        "threshold": 25.0,
        "definition": "Tmax ≥ 25 °C",
        "bit": 2,
        "color": "#e7a62b",
    },
    {
        "id": "hot",
        "label": "Hitzetage",
        "short_label": "Hitzetag",
        "field": "tx",
        "operator": "ge",
        "threshold": 30.0,
        "definition": "Tmax ≥ 30 °C",
        "dwd_name": "Heißer Tag",
        "bit": 3,
        "color": "#df6b2f",
    },
    {
        "id": "desert",
        "label": "Wüstentage",
        "short_label": "Wüstentag",
        "field": "tx",
        "operator": "ge",
        "threshold": 35.0,
        "definition": "Tmax ≥ 35 °C",
        "dwd_name": "Sehr heißer Tag",
        "bit": 4,
        "color": "#c63d2f",
    },
    {
        "id": "extreme_hot",
        "label": "Extrem heiße Tage",
        "short_label": "Extrem heißer Tag",
        "field": "tx",
        "operator": "ge",
        "threshold": 40.0,
        "definition": "Tmax ≥ 40 °C",
        "dwd_name": "Extrem heißer Tag",
        "bit": 5,
        "color": "#7f1717",
    },
    {
        "id": "tropical_night",
        "label": "Tropennächte",
        "short_label": "Tropennacht",
        "field": "tn",
        "operator": "ge",
        "threshold": 20.0,
        "definition": "Tmin ≥ 20 °C",
        "bit": 6,
        "color": "#b32f75",
    },
]

PERIODS: list[dict[str, Any]] = [
    {"id": "year", "label": "Gesamtjahr", "expected_days": 365},
    {"id": "winter", "label": "Winter (DJF)", "expected_days": 90},
    {"id": "spring", "label": "Frühling (MAM)", "expected_days": 92},
    {"id": "summer", "label": "Sommer (JJA)", "expected_days": 92},
    {"id": "autumn", "label": "Herbst (SON)", "expected_days": 91},
]
PERIOD_EXPECTED = {item["id"]: int(item["expected_days"]) for item in PERIODS}


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
    history_years: int
    reference_years: int
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
    match = STATION_ID_PATTERN.search(filename)
    if not match:
        raise ValueError(f"Stations-ID kann aus Dateiname nicht gelesen werden: {filename}")
    return match.group(1)


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def non_leap_index(day: date) -> int | None:
    if day.month == 2 and day.day == 29:
        return None
    index = day.timetuple().tm_yday - 1
    if day.month > 2 and is_leap(day.year):
        index -= 1
    return index


def labels_non_leap() -> list[str]:
    labels: list[str] = []
    cursor = date(2001, 1, 1)
    while cursor.year == 2001:
        labels.append(cursor.strftime("%m-%d"))
        cursor += timedelta(days=1)
    return labels


def period_and_year(day: date) -> list[tuple[str, int]]:
    result = [("year", day.year)]
    if day.month in (12, 1, 2):
        result.append(("winter", day.year + 1 if day.month == 12 else day.year))
    elif day.month in (3, 4, 5):
        result.append(("spring", day.year))
    elif day.month in (6, 7, 8):
        result.append(("summer", day.year))
    else:
        result.append(("autumn", day.year))
    return result


def metric_occurs(specification: dict[str, Any], tx: float | None, tn: float | None) -> bool | None:
    value = tx if specification["field"] == "tx" else tn
    if value is None:
        return None
    threshold = float(specification["threshold"])
    if specification["operator"] == "lt":
        return value < threshold
    return value >= threshold


def observation_temperatures(observation) -> tuple[float | None, float | None]:
    tx = observation.values.get("txk_high")
    tn = observation.values.get("tnk_low")
    return (
        None if tx is None else float(tx),
        None if tn is None else float(tn),
    )


def build_profile_payload(
    station_id: str,
    observations,
    metadata: MetadataIndex,
    current_year: int,
) -> tuple[StationProfile, dict[str, Any]] | None:
    # metric -> period -> year -> [count, valid_days]
    accumulators: dict[str, dict[str, dict[int, list[int]]]] = {
        item["id"]: {period["id"]: defaultdict(lambda: [0, 0]) for period in PERIODS}
        for item in CLIMATE_DAYS
    }
    # metric -> reference year -> 365 values (0/1/None)
    reference_daily: dict[str, dict[int, list[int | None]]] = {
        item["id"]: defaultdict(lambda: [None] * 365) for item in CLIMATE_DAYS
    }
    # Kompakte Grundlage für die historischen Jahresverläufe im Browser:
    # metric -> year -> Indizes der Kalendertage, an denen der Kenntag auftrat.
    # Aus diesen Ereignistagen wird die kumulative Kurve im Dashboard rekonstruiert.
    historical_event_days: dict[str, dict[int, list[int]]] = {
        item["id"]: defaultdict(list) for item in CLIMATE_DAYS
    }
    observed_years: set[int] = set()
    daily_tx_record_max: list[float | None] = [None] * 365
    daily_tn_record_min: list[float | None] = [None] * 365
    reference_tx_daily: dict[int, list[float | None]] = defaultdict(lambda: [None] * 365)
    reference_tn_daily: dict[int, list[float | None]] = defaultdict(lambda: [None] * 365)
    hottest_candidates: list[list[Any]] = []
    coldest_candidates: list[list[Any]] = []
    warmest_night_candidates: list[list[Any]] = []

    for observation in observations:
        if observation.day.year >= current_year:
            continue
        tx, tn = observation_temperatures(observation)
        if tx is not None:
            hottest_candidates.append([observation.day.isoformat(), round(float(tx), 1)])
        if tn is not None:
            coldest_candidates.append([observation.day.isoformat(), round(float(tn), 1)])
            warmest_night_candidates.append([observation.day.isoformat(), round(float(tn), 1)])
        index = non_leap_index(observation.day)
        if index is not None:
            if tx is not None and (daily_tx_record_max[index] is None or tx > daily_tx_record_max[index]):
                daily_tx_record_max[index] = round(float(tx), 1)
            if tn is not None and (daily_tn_record_min[index] is None or tn < daily_tn_record_min[index]):
                daily_tn_record_min[index] = round(float(tn), 1)
            if REFERENCE_START <= observation.day.year <= REFERENCE_END:
                if tx is not None:
                    reference_tx_daily[observation.day.year][index] = round(float(tx), 1)
                if tn is not None:
                    reference_tn_daily[observation.day.year][index] = round(float(tn), 1)
        if index is None:
            continue
        observed_years.add(observation.day.year)
        for specification in CLIMATE_DAYS:
            metric = specification["id"]
            occurs = metric_occurs(specification, tx, tn)
            if occurs is None:
                continue
            for period, period_year in period_and_year(observation.day):
                if period_year >= current_year:
                    continue
                bucket = accumulators[metric][period][period_year]
                bucket[1] += 1
                if occurs:
                    bucket[0] += 1
            if occurs:
                historical_event_days[metric][observation.day.year].append(index)
            if REFERENCE_START <= observation.day.year <= REFERENCE_END:
                reference_daily[metric][observation.day.year][index] = 1 if occurs else 0

    if not observed_years:
        return None

    counts: dict[str, dict[str, list[list[int]]]] = {}
    valid_history_years: set[int] = set()
    for specification in CLIMATE_DAYS:
        metric = specification["id"]
        counts[metric] = {}
        for period in PERIODS:
            period_id = period["id"]
            expected = PERIOD_EXPECTED[period_id]
            minimum_valid = int(expected * MIN_PERIOD_COVERAGE + 0.999999)
            entries: list[list[int]] = []
            for year, (count, valid_days) in accumulators[metric][period_id].items():
                if valid_days >= minimum_valid:
                    entries.append([year, count, valid_days])
                    if period_id == "year":
                        valid_history_years.add(year)
            entries.sort(key=lambda item: item[0])
            counts[metric][period_id] = entries

    if not valid_history_years:
        return None

    climate_mean_cumulative: dict[str, list[float | None]] = {}
    reference_years_by_metric: dict[str, int] = {}
    for specification in CLIMATE_DAYS:
        metric = specification["id"]
        years = sorted(reference_daily[metric])
        reference_years_by_metric[metric] = len(years)
        cumulative_total = 0.0
        curve: list[float | None] = []
        for index in range(365):
            values = [reference_daily[metric][year][index] for year in years]
            valid = [value for value in values if value is not None]
            if not valid:
                curve.append(None if not curve else curve[-1])
                continue
            cumulative_total += sum(valid) / len(valid)
            curve.append(round(cumulative_total, 2))
        climate_mean_cumulative[metric] = curve

    def daily_reference_mean(source: dict[int, list[float | None]]) -> list[float | None]:
        result: list[float | None] = []
        for index in range(365):
            values = [series[index] for series in source.values() if series[index] is not None]
            result.append(round(sum(values) / len(values), 1) if values else None)
        return result

    temperature_reference_daily_mean = {
        "tx": daily_reference_mean(reference_tx_daily),
        "tn": daily_reference_mean(reference_tn_daily),
    }
    hottest_candidates.sort(key=lambda item: (-float(item[1]), item[0]))
    coldest_candidates.sort(key=lambda item: (float(item[1]), item[0]))
    warmest_night_candidates.sort(key=lambda item: (-float(item[1]), item[0]))
    temperature_extremes = {
        "hottest_days": hottest_candidates[:20],
        "coldest_nights": coldest_candidates[:20],
        "warmest_nights": warmest_night_candidates[:20],
    }

    # Nur ausreichend vollständige Gesamtjahre ausgeben. Auch Jahre ohne
    # Ereignis werden mit leerer Liste gespeichert, damit eine Nullkurve
    # als vollwertiges historisches Vergleichsjahr dargestellt werden kann.
    historical_event_days_payload: dict[str, list[list[Any]]] = {}
    for specification in CLIMATE_DAYS:
        metric = specification["id"]
        valid_years = [int(item[0]) for item in counts[metric]["year"]]
        historical_event_days_payload[metric] = [
            [year, sorted(set(historical_event_days[metric].get(year, [])))]
            for year in valid_years
        ]

    segment = metadata.segment_for(station_id, date.today())
    years = sorted(valid_history_years)
    reference_years = [year for year in years if REFERENCE_START <= year <= REFERENCE_END]
    profile = StationProfile(
        station_id=station_id,
        name=segment.name,
        state=None if segment.state == "__Unbekannt__" else segment.state,
        height=segment.height,
        latitude=segment.latitude,
        longitude=segment.longitude,
        start_year=years[0],
        end_year=years[-1],
        history_years=len(years),
        reference_years=len(reference_years),
        file=f"station_climate_days_profiles/{station_id}.json",
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
        "reference_period": f"{REFERENCE_START}-{REFERENCE_END}",
        "reference_years": len(reference_years),
        "reference_years_by_metric": reference_years_by_metric,
        "minimum_period_coverage": MIN_PERIOD_COVERAGE,
        "counts": counts,
        "climate_mean_cumulative": climate_mean_cumulative,
        "historical_event_days": historical_event_days_payload,
        "historical_curve_encoding": "non_leap_day_indices_v1",
        "temperature_daily_records": {"tx_max": daily_tx_record_max, "tn_min": daily_tn_record_min},
        "temperature_reference_daily_mean": temperature_reference_daily_mean,
        "temperature_extremes": temperature_extremes,
    }
    return profile, payload


def process_historical_station(
    filename: str,
    metadata: MetadataIndex,
    current_year: int,
) -> tuple[str, tuple[StationProfile, dict[str, Any]] | None, str | None]:
    station_id = station_id_from_filename(filename)
    try:
        content = download_station_zip(HISTORICAL_URL, filename)
        observations = parse_station_zip(
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


def build_historical_profiles(
    root: Path,
    metadata: MetadataIndex,
    active_station_ids: set[str],
    current_year: int,
    max_workers: int,
) -> tuple[list[StationProfile], dict[str, Any]]:
    historical_files = list_station_files(HISTORICAL_URL, HISTORICAL_PATTERN, minimum=500)
    selected = [
        filename for filename in historical_files
        if station_id_from_filename(filename) in active_station_ids
    ]
    if len(selected) < 200:
        raise RuntimeError(f"Nur {len(selected)} historische KL-Dateien passen zu aktuellen Stationen.")

    target_dir = root / "station_climate_days_profiles"
    target_dir.mkdir(parents=True, exist_ok=True)
    profiles: list[StationProfile] = []
    errors: list[str] = []

    print(f"Stations-Kenntage: {len(selected)} historische Stationsarchive werden verarbeitet.")
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
                print(f"  historische Kenntageprofile: {index}/{len(futures)}")

    profiles.sort(key=lambda item: ((item.state or ""), item.name.casefold(), item.station_id))
    if len(profiles) < MIN_PROFILE_COUNT:
        examples = " | ".join(errors[:5])
        raise RuntimeError(
            f"Nur {len(profiles)} Kenntageprofile konnten aufgebaut werden. {examples}"
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
    atomic_write_json(root / "station_climate_days_state.json", state)
    return profiles, state


def state_is_stale(root: Path, current_year: int, force_full: bool) -> bool:
    if force_full:
        return True
    state_path = root / "station_climate_days_state.json"
    index_path = root / "station_climate_days_index.json"
    if not state_path.exists() or not index_path.exists():
        return True
    try:
        state = read_json(state_path)
        index = read_json(index_path)
    except (OSError, json.JSONDecodeError):
        return True
    if state.get("version") != STATE_VERSION or state.get("current_year") != current_year:
        return True
    if not index.get("ready") or len(index.get("stations", [])) < MIN_PROFILE_COUNT:
        return True
    try:
        built_at = datetime.fromisoformat(str(state["built_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return True
    return datetime.now(timezone.utc) - built_at > timedelta(days=HISTORICAL_REBUILD_DAYS)


def load_profiles_from_index(root: Path) -> list[StationProfile]:
    index = read_json(root / "station_climate_days_index.json")
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
                history_years=item["history_years"],
                reference_years=item.get("reference_years", 0),
                file=item["file"],
            )
        )
    return profiles


def event_and_valid_masks(tx: float | None, tn: float | None) -> tuple[int, int]:
    event_mask = 0
    valid_mask = 0
    for specification in CLIMATE_DAYS:
        bit = 1 << int(specification["bit"])
        occurs = metric_occurs(specification, tx, tn)
        if occurs is None:
            continue
        valid_mask |= bit
        if occurs:
            event_mask |= bit
    return event_mask, valid_mask


def process_recent_station(
    filename: str,
    metadata: MetadataIndex,
    start_date: date,
) -> tuple[str, dict[date, tuple[int, int, int | None, int | None]], str | None]:
    station_id = station_id_from_filename(filename)
    try:
        content = download_station_zip(RECENT_URL, filename)
        observations = parse_station_zip(
            content,
            station_id,
            metadata,
            start_date,
            date.today(),
            preliminary=True,
        )
        values: dict[date, tuple[int, int, int | None, int | None]] = {}
        for observation in observations:
            tx, tn = observation_temperatures(observation)
            event_mask, valid_mask = event_and_valid_masks(tx, tn)
            if valid_mask:
                values[observation.day] = (event_mask, valid_mask, None if tx is None else int(round(tx * 10)), None if tn is None else int(round(tn * 10)))
        return station_id, values, None
    except NoUsableProductFileError as exc:
        return station_id, {}, f"{filename}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return station_id, {}, f"{filename}: {exc}"


def accepted_data_through(
    values_by_station: dict[str, dict[date, tuple[int, int, int | None, int | None]]],
) -> tuple[date, dict[str, Any]]:
    counts: dict[date, int] = defaultdict(int)
    tx_bits = sum(1 << int(item["bit"]) for item in CLIMATE_DAYS if item["field"] == "tx")
    tn_bits = sum(1 << int(item["bit"]) for item in CLIMATE_DAYS if item["field"] == "tn")
    for values in values_by_station.values():
        for day, value_tuple in values.items():
            valid_mask = value_tuple[1]
            # Nur Stationen mit auswertbarem Tmax und Tmin zählen für die
            # Vollständigkeitsprüfung des jüngsten Tages.
            if (valid_mask & tx_bits) and (valid_mask & tn_bits):
                counts[day] += 1
    if not counts:
        raise RuntimeError("Keine aktuellen Temperaturwerte für Stations-Kenntage gelesen.")

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
            f"Kein aktueller Tag erreicht die Mindestzahl von {minimum_count} Temperaturstationen."
        )
    data_through = max(accepted)
    return data_through, {
        "newest_raw_dwd_date": newest_raw.isoformat(),
        "data_through": data_through.isoformat(),
        "latest_station_count": counts[data_through],
        "reference_station_count": reference_count,
        "minimum_station_count": minimum_count,
    }


def month_sequence(start: date, end: date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return months


def write_current_month_files(
    root: Path,
    data_through: date,
    profile_ids: set[str],
    values_by_station: dict[str, dict[date, tuple[int, int, int | None, int | None]]],
) -> list[str]:
    output_dir = root / "station_climate_days_current"
    output_dir.mkdir(parents=True, exist_ok=True)
    start_date = date(data_through.year - 1, 12, 1)
    written: list[str] = []

    for year, month in month_sequence(start_date, data_through):
        next_month = date(year + (month == 12), month % 12 + 1, 1)
        days_in_month = (next_month - date(year, month, 1)).days
        station_payload: dict[str, list[list[int | None] | None]] = {}
        for station_id in sorted(profile_ids):
            values = values_by_station.get(station_id, {})
            month_values: list[list[int | None] | None] = []
            has_value = False
            for day_number in range(1, days_in_month + 1):
                day = date(year, month, day_number)
                pair = values.get(day) if day <= data_through else None
                month_values.append(None if pair is None else [pair[0], pair[1], pair[2]])
                has_value = has_value or pair is not None
            if has_value:
                station_payload[station_id] = month_values

        filename = f"{year:04d}-{month:02d}.json"
        payload = {
            "year": year,
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
    data_through: date,
    current_files: list[str],
) -> dict[str, dict[str, Any]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    valid: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for filename in current_files:
        payload = read_json(root / "station_climate_days_current" / filename)
        year = int(payload["year"]); month = int(payload["month"])
        for station_id, values in (payload.get("stations") or {}).items():
            for day_number, pair in enumerate(values, start=1):
                day = date(year, month, day_number)
                if day > data_through:
                    break
                if not pair or len(pair) < 2:
                    continue
                occurrence_mask = int(pair[0]); valid_mask = int(pair[1])
                for metric in CLIMATE_DAYS:
                    bit = 1 << int(metric["bit"])
                    if valid_mask & bit:
                        valid[station_id][metric["id"]] += 1
                        if occurrence_mask & bit:
                            counts[station_id][metric["id"]] += 1
    elapsed = sum(1 for label in labels_non_leap() if f"{data_through.year}-{label}" <= data_through.isoformat())
    result: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        result[profile.station_id] = {
            "current_counts": dict(counts.get(profile.station_id, {})),
            "valid_days": dict(valid.get(profile.station_id, {})),
            "elapsed_days": elapsed,
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
    map_summaries = build_map_summaries(
        root, profiles, date.fromisoformat(current_status["data_through"]), current_files
    )
    index = {
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_year": current_year,
        "data_through": current_status["data_through"],
        "labels": labels_non_leap(),
        "reference_period": f"{REFERENCE_START}-{REFERENCE_END}",
        "minimum_period_coverage": MIN_PERIOD_COVERAGE,
        "leap_day_rule": "Der 29. Februar wird für die Vergleichbarkeit ausgelassen.",
        "source": "DWD CDC, tägliche KL-Stationswerte (TXK und TNK)",
        "current_payload_version": 2,
        "source_note": (
            "Historische Auswertungen stammen aus dem qualitätsgeprüften DWD-Verzeichnis historical. "
            "Das laufende Jahr stammt aus recent und ist vorläufig. Hitzetag entspricht dem DWD-Begriff "
            "Heißer Tag; Wüstentag entspricht dem DWD-Begriff Sehr heißer Tag."
        ),
        "climate_days": [dict(item) for item in CLIMATE_DAYS],
        "periods": PERIODS,
        "states": states,
        "current_files": [f"station_climate_days_current/{name}" for name in current_files],
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
                "history_years": profile.history_years,
                "reference_years": profile.reference_years,
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
    atomic_write_json(root / "station_climate_days_index.json", index)
    return index


def update_station_climate_days(
    root: Path,
    max_workers: int = 8,
    force_full: bool = False,
) -> dict[str, Any]:
    current_year = date.today().year
    metadata = parse_metadata(download(METADATA_URL, timeout=120))
    recent_files = list_station_files(RECENT_URL, RECENT_PATTERN, minimum=300)
    active_station_ids = {station_id_from_filename(filename) for filename in recent_files}

    rebuilt = state_is_stale(root, current_year, force_full)
    if rebuilt:
        profiles, historical_state = build_historical_profiles(
            root,
            metadata,
            active_station_ids,
            current_year,
            max_workers,
        )
    else:
        profiles = load_profiles_from_index(root)
        historical_state = read_json(root / "station_climate_days_state.json")
        print(
            "Stations-Kenntage: historische Profile werden aus dem Zwischenspeicher verwendet "
            f"({len(profiles)} Stationen)."
        )

    profile_ids = {profile.station_id for profile in profiles}
    selected_recent = [
        filename for filename in recent_files
        if station_id_from_filename(filename) in profile_ids
    ]
    start_date = date(current_year - 1, 12, 1)
    values_by_station: dict[str, dict[date, tuple[int, int, int | None, int | None]]] = {}
    errors: list[str] = []

    print(f"Stations-Kenntage: {len(selected_recent)} aktuelle Stationsarchive werden verarbeitet.")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_recent_station, filename, metadata, start_date): filename
            for filename in selected_recent
        }
        for index, future in enumerate(as_completed(futures), start=1):
            station_id, values, error = future.result()
            if error:
                errors.append(error)
            if values:
                values_by_station[station_id] = values
            if index % 50 == 0 or index == len(futures):
                print(f"  aktuelle Kenntage-Stationen: {index}/{len(futures)}")

    data_through, current_status = accepted_data_through(values_by_station)
    current_files = write_current_month_files(
        root,
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
        "climate_day_count": len(CLIMATE_DAYS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Erzeugt Stations-Kenntage für das Climate Dashboard.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    result = update_station_climate_days(args.root, max_workers=args.workers, force_full=args.full)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
