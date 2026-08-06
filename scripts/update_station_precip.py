from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

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

STATE_VERSION = 1
MIN_REFERENCE_YEARS = 5
MIN_HISTORY_YEARS = 5
MIN_CURRENT_STATIONS = 100
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
    match = STATION_ID_PATTERN.search(filename)
    if not match:
        raise ValueError(f"Stations-ID kann aus Dateiname nicht gelesen werden: {filename}")
    return match.group(1)


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


def build_profile_payload(
    station_id: str,
    observations,
    metadata: MetadataIndex,
    current_year: int,
) -> tuple[StationProfile, dict[str, Any]] | None:
    curves = observations_to_complete_curves(observations, current_year)
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
        "climate_mean_cumulative": climate_mean,
        "historical_min_cumulative": historical_min,
        "historical_max_cumulative": historical_max,
        "historical_min_year": historical_min_year,
        "historical_max_year": historical_max_year,
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


def build_historical_baselines(
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
    if len(profiles) < 150:
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
        content = download_station_zip(RECENT_URL, filename)
        observations = parse_station_zip(
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


def build_index(
    root: Path,
    profiles: list[StationProfile],
    current_year: int,
    current_status: dict[str, Any],
    current_files: list[str],
    historical_state: dict[str, Any],
) -> dict[str, Any]:
    states = sorted({profile.state for profile in profiles if profile.state})
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
        "source": "DWD CDC, tägliche KL-Stationswerte (RSK)",
        "source_note": (
            "Historische Kurven stammen aus dem qualitätsgeprüften DWD-Verzeichnis historical. "
            "Das laufende Jahr stammt aus recent und ist vorläufig."
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
    metadata = parse_metadata(download(METADATA_URL, timeout=120))
    recent_files = list_station_files(RECENT_URL, RECENT_PATTERN, minimum=300)
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
