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
from typing import Any, Iterable

from dwd_common import atomic_write_json, download, read_json
from update_station_records import (
    HISTORICAL_PATTERN,
    HISTORICAL_URL,
    METADATA_URL,
    STATION_ID_PATTERN,
    MetadataIndex,
    NoUsableProductFileError,
    download_station_zip,
    list_station_files,
    parse_metadata,
    parse_station_zip,
)

STATE_VERSION = 1
THRESHOLD_C = 30.0
MIN_DURATION = 3
HISTORICAL_REBUILD_DAYS = 45
MIN_PROFILE_COUNT = 150
WARM_SEASON_START = (4, 1)
WARM_SEASON_END = (10, 31)
WARM_SEASON_EXPECTED_DAYS = 214
MIN_WARM_SEASON_COVERAGE = 0.95
RECENT_WINDOW_YEARS = 11


@dataclass(frozen=True)
class HeatwaveStation:
    station_id: str
    name: str
    state: str | None
    height: int | None
    latitude: float | None
    longitude: float | None
    start_year: int
    end_year: int
    history_years: int
    event_count: int
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


def in_warm_season(day: date) -> bool:
    return (day.month, day.day) >= WARM_SEASON_START and (day.month, day.day) <= WARM_SEASON_END


def observation_tx(observation) -> float | None:
    value = observation.values.get("txk_high")
    return None if value is None else float(value)


def finalize_event(days: list[tuple[date, float]], preliminary: bool, ongoing: bool = False) -> dict[str, Any] | None:
    if len(days) < MIN_DURATION:
        return None
    values = [value for _, value in days]
    peak_index = max(range(len(values)), key=values.__getitem__)
    severity = sum(max(value - THRESHOLD_C, 0.0) for value in values)
    return {
        "start": days[0][0].isoformat(),
        "end": days[-1][0].isoformat(),
        "year": days[0][0].year,
        "duration": len(days),
        "max_tmax": round(values[peak_index], 1),
        "mean_tmax": round(sum(values) / len(values), 1),
        "severity": round(severity, 1),
        "peak_date": days[peak_index][0].isoformat(),
        "preliminary": bool(preliminary),
        "ongoing": bool(ongoing),
    }


def detect_heatwaves(values_by_day: dict[date, float], preliminary: bool, data_through: date | None = None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    sequence: list[tuple[date, float]] = []
    previous_day: date | None = None

    for day in sorted(values_by_day):
        value = values_by_day[day]
        hot = value >= THRESHOLD_C
        consecutive = previous_day is not None and day == previous_day + timedelta(days=1)
        if hot and (not sequence or consecutive):
            sequence.append((day, value))
        elif hot:
            event = finalize_event(sequence, preliminary)
            if event:
                events.append(event)
            sequence = [(day, value)]
        else:
            event = finalize_event(sequence, preliminary)
            if event:
                events.append(event)
            sequence = []
        previous_day = day

    ongoing = bool(sequence and data_through and sequence[-1][0] == data_through)
    event = finalize_event(sequence, preliminary, ongoing=ongoing)
    if event:
        events.append(event)
    return events


def annual_valid_days(values_by_day: dict[date, float]) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for day in values_by_day:
        if in_warm_season(day):
            counts[day.year] += 1
    return dict(counts)


def complete_years(valid_days: dict[int, int]) -> set[int]:
    minimum = int(WARM_SEASON_EXPECTED_DAYS * MIN_WARM_SEASON_COVERAGE + 0.999999)
    return {year for year, count in valid_days.items() if count >= minimum}


def build_historical_payload(
    station_id: str,
    observations,
    metadata: MetadataIndex,
    current_year: int,
) -> tuple[HeatwaveStation, dict[str, Any]] | None:
    values_by_day: dict[date, float] = {}
    for observation in observations:
        if observation.day.year >= current_year:
            continue
        tx = observation_tx(observation)
        if tx is not None:
            values_by_day[observation.day] = tx
    if not values_by_day:
        return None

    valid_days = annual_valid_days(values_by_day)
    eligible_years = complete_years(valid_days)
    if not eligible_years:
        return None

    all_events = detect_heatwaves(values_by_day, preliminary=False)
    events = [event for event in all_events if int(event["year"]) in eligible_years]
    counts_by_year: dict[int, int] = defaultdict(int)
    for event in events:
        counts_by_year[int(event["year"])] += 1

    annual = [
        [year, counts_by_year.get(year, 0), valid_days.get(year, 0)]
        for year in sorted(eligible_years)
    ]
    segment = metadata.segment_for(station_id, date.today())
    years = sorted(eligible_years)
    profile = HeatwaveStation(
        station_id=station_id,
        name=segment.name,
        state=None if segment.state == "__Unbekannt__" else segment.state,
        height=segment.height,
        latitude=segment.latitude,
        longitude=segment.longitude,
        start_year=years[0],
        end_year=years[-1],
        history_years=len(years),
        event_count=len(events),
        file=f"station_heatwaves_profiles/{station_id}.json",
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
        "event_count": len(events),
        "threshold_c": THRESHOLD_C,
        "minimum_duration": MIN_DURATION,
        "warm_season_coverage": MIN_WARM_SEASON_COVERAGE,
        "warm_season_expected_days": WARM_SEASON_EXPECTED_DAYS,
        "annual": annual,
        "events": events,
    }
    return profile, payload


def process_historical_station(
    filename: str,
    metadata: MetadataIndex,
    current_year: int,
) -> tuple[str, tuple[HeatwaveStation, dict[str, Any]] | None, str | None]:
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
        return station_id, build_historical_payload(station_id, observations, metadata, current_year), None
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
) -> tuple[list[HeatwaveStation], dict[str, Any]]:
    historical_files = list_station_files(HISTORICAL_URL, HISTORICAL_PATTERN, minimum=500)
    selected = [
        filename for filename in historical_files
        if station_id_from_filename(filename) in active_station_ids
    ]
    if len(selected) < 200:
        raise RuntimeError(f"Nur {len(selected)} historische KL-Dateien passen zu aktuellen Stationen.")

    target_dir = root / "station_heatwaves_profiles"
    target_dir.mkdir(parents=True, exist_ok=True)
    profiles: list[HeatwaveStation] = []
    errors: list[str] = []

    print(f"Stations-Hitzewellen: {len(selected)} historische Stationsarchive werden verarbeitet.")
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
                print(f"  historische Hitzewellenprofile: {index}/{len(futures)}")

    profiles.sort(key=lambda item: ((item.state or ""), item.name.casefold(), item.station_id))
    if len(profiles) < MIN_PROFILE_COUNT:
        examples = " | ".join(errors[:5])
        raise RuntimeError(f"Nur {len(profiles)} Hitzewellenprofile konnten aufgebaut werden. {examples}")

    valid_ids = {profile.station_id for profile in profiles}
    for old_file in target_dir.glob("*.json"):
        if old_file.stem not in valid_ids:
            old_file.unlink()

    state = {
        "version": STATE_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_year": current_year,
        "profiles": len(profiles),
        "profile_ids": sorted(valid_ids),
        "selected_historical_files": len(selected),
        "errors": errors[:50],
    }
    atomic_write_json(root / "station_heatwaves_state.json", state)
    return profiles, state


def load_profiles_from_index(root: Path) -> list[HeatwaveStation]:
    index = read_json(root / "station_heatwaves_index.json")
    return [
        HeatwaveStation(
            station_id=item["id"],
            name=item["name"],
            state=item.get("state"),
            height=item.get("height"),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            start_year=item["start_year"],
            end_year=item["end_year"],
            history_years=item["history_years"],
            event_count=item.get("event_count", 0),
            file=item["file"],
        )
        for item in index.get("stations", [])
    ]


def state_is_stale(root: Path, current_year: int, force_full: bool) -> bool:
    if force_full:
        return True
    state_path = root / "station_heatwaves_state.json"
    index_path = root / "station_heatwaves_index.json"
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


def current_tx_from_climate_day_files(root: Path, station_ids: set[str], current_year: int) -> tuple[dict[str, dict[date, float]], date]:
    climate_index = read_json(root / "station_climate_days_index.json")
    data_through = date.fromisoformat(climate_index["data_through"])
    values_by_station: dict[str, dict[date, float]] = {station_id: {} for station_id in station_ids}

    files = climate_index.get("current_files") or []
    if not files:
        raise RuntimeError("Keine aktuellen Stations-Kenntage-Dateien als Grundlage für Hitzewellen vorhanden.")
    for relative_path in files:
        payload = read_json(root / relative_path)
        year = int(payload["year"])
        month = int(payload["month"])
        if year != current_year:
            continue
        for station_id, month_values in (payload.get("stations") or {}).items():
            if station_id not in station_ids:
                continue
            for day_index, pair in enumerate(month_values, start=1):
                if not pair or len(pair) < 3 or pair[2] is None:
                    continue
                day = date(year, month, day_index)
                if day <= data_through:
                    values_by_station[station_id][day] = float(pair[2]) / 10.0
    return values_by_station, data_through


def current_payload_for_station(values_by_day: dict[date, float], data_through: date) -> dict[str, Any]:
    events = detect_heatwaves(values_by_day, preliminary=True, data_through=data_through)
    start = date(data_through.year, 4, 1)
    end = min(data_through, date(data_through.year, 10, 31))
    expected = max(0, (end - start).days + 1) if end >= start else 0
    valid = sum(1 for day in values_by_day if start <= day <= end)
    return {
        "events": events,
        "valid_warm_days": valid,
        "expected_warm_days_to_date": expected,
        "missing_warm_days": max(0, expected - valid),
    }


def build_current_file(
    root: Path,
    profiles: list[HeatwaveStation],
    current_year: int,
) -> tuple[dict[str, Any], date]:
    station_ids = {profile.station_id for profile in profiles}
    values_by_station, data_through = current_tx_from_climate_day_files(root, station_ids, current_year)
    stations: dict[str, Any] = {}
    for profile in profiles:
        stations[profile.station_id] = current_payload_for_station(
            values_by_station.get(profile.station_id, {}),
            data_through,
        )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_year": current_year,
        "data_through": data_through.isoformat(),
        "threshold_c": THRESHOLD_C,
        "minimum_duration": MIN_DURATION,
        "stations": stations,
    }
    atomic_write_json_compact(root / "station_heatwaves_current.json", payload)
    return payload, data_through


def build_index(
    root: Path,
    profiles: list[HeatwaveStation],
    current_year: int,
    data_through: date,
    historical_state: dict[str, Any],
    current_payload: dict[str, Any],
) -> dict[str, Any]:
    states = sorted({profile.state for profile in profiles if profile.state})
    recent_start = current_year - RECENT_WINDOW_YEARS
    index = {
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_year": current_year,
        "data_through": data_through.isoformat(),
        "threshold_c": THRESHOLD_C,
        "minimum_duration": MIN_DURATION,
        "recent_period_start": recent_start,
        "recent_period_end": current_year - 1,
        "warm_season_coverage": MIN_WARM_SEASON_COVERAGE,
        "source": "DWD CDC, tägliche KL-Stationswerte (TXK)",
        "definition": (
            "Dashboard-Definition: mindestens 3 unmittelbar aufeinanderfolgende Tage mit "
            "Tmax ≥ 30,0 °C. Eine Datenlücke unterbricht ein Ereignis."
        ),
        "severity_definition": (
            "Blasengröße/Schweregrad: Summe der täglichen Überschreitungen von 30 °C "
            "über das gesamte Ereignis, angegeben in K·Tagen."
        ),
        "method_note": (
            "Historische Jahreszahlen werden nur für Jahre mit mindestens 95 % gültigen TXK-Tagen "
            "zwischen 1. April und 31. Oktober verwendet. Das laufende Jahr ist vorläufig. "
            "Die verwendete feste 30-°C-Definition ist eine Dashboard-Definition und nicht die "
            "perzentilbasierte Hitzewellendefinition des DWD."
        ),
        "current_file": "station_heatwaves_current.json",
        "states": states,
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
                "event_count": profile.event_count,
                "file": profile.file,
                "map": {
                    "current_events": len((current_payload.get("stations", {}).get(profile.station_id, {}) or {}).get("events", [])),
                    "current_heatwave_days": sum(int(event.get("duration", 0)) for event in (current_payload.get("stations", {}).get(profile.station_id, {}) or {}).get("events", [])),
                    "current_max_tmax": max([float(event.get("max_tmax", -999)) for event in (current_payload.get("stations", {}).get(profile.station_id, {}) or {}).get("events", [])], default=None),
                },
            }
            for profile in profiles
        ],
        "status": {
            "profile_count": len(profiles),
            "historical_built_at": historical_state.get("built_at"),
            "data_through": data_through.isoformat(),
        },
    }
    atomic_write_json(root / "station_heatwaves_index.json", index)
    return index


def update_station_heatwaves(
    root: Path,
    max_workers: int = 8,
    force_full: bool = False,
) -> dict[str, Any]:
    current_year = date.today().year
    climate_day_index = read_json(root / "station_climate_days_index.json")
    active_station_ids = {item["id"] for item in climate_day_index.get("stations", [])}
    if len(active_station_ids) < 100:
        raise RuntimeError("Unerwartet wenige Stations-Kenntage-Stationen als Basis gefunden.")

    rebuilt = state_is_stale(root, current_year, force_full)
    if rebuilt:
        metadata = parse_metadata(download(METADATA_URL, timeout=120))
        profiles, historical_state = build_historical_profiles(
            root,
            metadata,
            active_station_ids,
            current_year,
            max_workers,
        )
    else:
        profiles = load_profiles_from_index(root)
        historical_state = read_json(root / "station_heatwaves_state.json")
        print(
            "Stations-Hitzewellen: historische Profile werden aus dem Zwischenspeicher verwendet "
            f"({len(profiles)} Stationen)."
        )

    current_payload, data_through = build_current_file(root, profiles, current_year)
    index = build_index(root, profiles, current_year, data_through, historical_state, current_payload)
    current_event_count = sum(
        len(item.get("events", []))
        for item in current_payload.get("stations", {}).values()
    )
    return {
        "rebuilt_historical": rebuilt,
        "station_count": len(profiles),
        "data_through": data_through.isoformat(),
        "historical_event_count": sum(profile.event_count for profile in profiles),
        "current_event_count": current_event_count,
        "threshold_c": THRESHOLD_C,
        "minimum_duration": MIN_DURATION,
        "recent_period_start": index["recent_period_start"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Erzeugt Stations-Hitzewellen für das Climate Dashboard.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    result = update_station_heatwaves(args.root, max_workers=args.workers, force_full=args.full)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
