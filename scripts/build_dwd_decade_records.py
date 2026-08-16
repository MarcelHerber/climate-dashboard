#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from update_station_records import (
    HISTORICAL_PATTERN,
    HISTORICAL_URL,
    INTERNAL_UNKNOWN,
    METADATA_URL,
    RECENT_PATTERN,
    RECENT_URL,
    STATE_ORDER,
    STATION_ID_PATTERN,
    MetadataIndex,
    Observation,
    TopK,
    download,
    iter_downloaded_observations,
    list_station_files,
    parse_metadata,
    parse_station_zip,
)

VERSION = 2
TOP_K = 50

METRIC_CONFIG = {
    "txk_high": {"label": "Höchstes Tmax", "unit": "°C", "direction": "desc", "source_column": "TXK", "observation_key": "txk_high"},
    "txk_low": {"label": "Niedrigstes Tmax", "unit": "°C", "direction": "asc", "source_column": "TXK", "observation_key": "txk_high"},
    "tnk_high": {"label": "Höchstes Tmin", "unit": "°C", "direction": "desc", "source_column": "TNK", "observation_key": "tnk_low"},
    "tnk_low": {"label": "Tiefstes Tmin", "unit": "°C", "direction": "asc", "source_column": "TNK", "observation_key": "tnk_low"},
}

MONTH_NAMES = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]
AREAS = ["Deutschland", *STATE_ORDER]


def decade_no(day: date) -> int:
    if day.day <= 10:
        return 1
    if day.day <= 20:
        return 2
    return 3


def period_id(day: date) -> str:
    return f"month-{day.month:02d}-d{decade_no(day)}"


def build_periods() -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = []
    for month, month_name in enumerate(MONTH_NAMES, start=1):
        for decade in (1, 2, 3):
            day_range = "01.–10." if decade == 1 else "11.–20." if decade == 2 else "21.–Monatsende"
            periods.append({
                "id": f"month-{month:02d}-d{decade}",
                "month": month,
                "month_label": month_name,
                "decade": decade,
                "label": f"{month_name} · {decade}. Dekade",
                "day_range": day_range,
            })
    return periods


def entry_for(observation: Observation, value: float) -> list[Any]:
    return [round(float(value), 1), observation.day.isoformat(), observation.metadata_key, 1 if observation.preliminary else 0]


def better(metric: str, new: list[Any], old: list[Any]) -> bool:
    new_value = float(new[0])
    old_value = float(old[0])
    direction = METRIC_CONFIG[metric]["direction"]
    if new_value != old_value:
        return new_value > old_value if direction == "desc" else new_value < old_value
    if str(new[1]) != str(old[1]):
        return str(new[1]) < str(old[1])
    return str(new[2]).split(":", 1)[0] < str(old[2]).split(":", 1)[0]


class DecadeAccumulator:
    def __init__(self) -> None:
        self.leaders: dict[str, dict[str, dict[str, TopK]]] = defaultdict(lambda: defaultdict(dict))
        self.station_records: dict[str, dict[str, dict[str, dict[str, list[Any]]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))

    def _leader_bucket(self, metric: str, area: str, period: str) -> TopK:
        bucket = self.leaders[metric][area].get(period)
        if bucket is None:
            proxy_metric = "txk_high" if METRIC_CONFIG[metric]["direction"] == "desc" else "tnk_low"
            bucket = TopK(proxy_metric, TOP_K)
            self.leaders[metric][area][period] = bucket
        return bucket

    def add(self, observation: Observation) -> None:
        period = period_id(observation.day)
        state = observation.state if observation.state in STATE_ORDER else INTERNAL_UNKNOWN
        areas = ["Deutschland"]
        if state in STATE_ORDER:
            areas.append(state)

        for metric, config in METRIC_CONFIG.items():
            source_key = str(config["observation_key"])
            if source_key not in observation.values:
                continue
            entry = entry_for(observation, observation.values[source_key])
            for area in areas:
                self._leader_bucket(metric, area, period).add(entry)
                station_bucket = self.station_records[metric][area][period]
                old = station_bucket.get(observation.station_id)
                if old is None or better(metric, entry, old):
                    station_bucket[observation.station_id] = entry

    def public_leaders(self, periods: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        period_ids = [item["id"] for item in periods]
        for metric in METRIC_CONFIG:
            metric_out: dict[str, Any] = {}
            for area in AREAS:
                area_out: dict[str, Any] = {}
                for pid in period_ids:
                    bucket = self.leaders.get(metric, {}).get(area, {}).get(pid)
                    area_out[pid] = bucket.entries() if bucket else []
                metric_out[area] = area_out
            result[metric] = metric_out
        return result

    def public_station_records(self, periods: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        period_ids = [item["id"] for item in periods]
        for metric in METRIC_CONFIG:
            metric_out: dict[str, Any] = {}
            for area in AREAS:
                area_out: dict[str, Any] = {}
                for pid in period_ids:
                    records = self.station_records.get(metric, {}).get(area, {}).get(pid, {})
                    area_out[pid] = {station_id: records[station_id] for station_id in sorted(records)}
                metric_out[area] = area_out
            result[metric] = metric_out
        return result


def referenced_metadata_keys(payload_part: Any, target: set[str]) -> None:
    if isinstance(payload_part, dict):
        for value in payload_part.values():
            referenced_metadata_keys(value, target)
        return
    if isinstance(payload_part, list):
        if len(payload_part) == 4 and isinstance(payload_part[1], str) and isinstance(payload_part[2], str) and ":" in payload_part[2]:
            target.add(payload_part[2])
            return
        for value in payload_part:
            referenced_metadata_keys(value, target)


def filter_station_metadata(metadata: MetadataIndex, keys: set[str]) -> dict[str, Any]:
    public = metadata.public_dict()
    return {key: public[key] for key in sorted(keys) if key in public}


def consume_archives(accumulator: DecadeAccumulator, metadata: MetadataIndex, filenames: list[str], base_url: str, start_date: date, end_date: date, preliminary: bool, max_workers: int, *, failure_tolerance: float) -> tuple[int, date | None, date | None]:
    count = 0
    first_day: date | None = None
    last_day: date | None = None
    for observations in iter_downloaded_observations(
        filenames, base_url, metadata, start_date, end_date, preliminary, max_workers,
        station_pattern=STATION_ID_PATTERN, parser=parse_station_zip, failure_tolerance=failure_tolerance,
    ):
        for observation in observations:
            accumulator.add(observation)
            count += 1
            first_day = observation.day if first_day is None else min(first_day, observation.day)
            last_day = observation.day if last_day is None else max(last_day, observation.day)
    return count, first_day, last_day


def main() -> int:
    parser = argparse.ArgumentParser(description="DWD-Dekadenrekorde für Deutschland und alle Bundesländer bauen.")
    parser.add_argument("--output", default="data/dwd_decade_records.json", help="Ziel-JSON")
    parser.add_argument("--max-workers", type=int, default=10)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    print("=== DWD DEKADENREKORDE · VERSION 2 ===", flush=True)
    print("Parameter: Tmax hoch + Tmax tief + Tmin hoch + Tmin tief", flush=True)
    print("Gebiete: Deutschland + 16 Bundesländer", flush=True)
    print("Fenster: 36 meteorologische Dekaden", flush=True)

    metadata = parse_metadata(download(METADATA_URL, timeout=90))
    print(f"Stations-Metadatensegmente: {len(metadata.segments):,}", flush=True)

    historical_files = list_station_files(HISTORICAL_URL, HISTORICAL_PATTERN, minimum=500)
    recent_files = list_station_files(RECENT_URL, RECENT_PATTERN, minimum=300)
    print(f"Historische KL-Archive: {len(historical_files):,}", flush=True)
    print(f"Aktuelle KL-Archive: {len(recent_files):,}", flush=True)

    accumulator = DecadeAccumulator()
    today = datetime.now(timezone.utc).date()

    historical_count, hist_first, hist_last = consume_archives(
        accumulator, metadata, historical_files, HISTORICAL_URL,
        date(1750, 1, 1), today, False, args.max_workers, failure_tolerance=0.005,
    )
    print(f"Historische Temperaturzeilen verarbeitet: {historical_count:,}", flush=True)

    recent_count, recent_first, recent_last = consume_archives(
        accumulator, metadata, recent_files, RECENT_URL,
        date(today.year - 2, 1, 1), today, True, args.max_workers, failure_tolerance=0.01,
    )
    print(f"Aktuelle Temperaturzeilen verarbeitet: {recent_count:,}", flush=True)

    all_first = [d for d in (hist_first, recent_first) if d is not None]
    all_last = [d for d in (hist_last, recent_last) if d is not None]
    data_start = min(all_first) if all_first else None
    data_through = max(all_last) if all_last else None

    periods = build_periods()
    leaders = accumulator.public_leaders(periods)
    station_records = accumulator.public_station_records(periods)

    metadata_keys: set[str] = set()
    referenced_metadata_keys(leaders, metadata_keys)
    referenced_metadata_keys(station_records, metadata_keys)
    stations = filter_station_metadata(metadata, metadata_keys)

    payload = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "DWD CDC daily climate KL",
        "data_start": data_start.isoformat() if data_start else None,
        "data_through": data_through.isoformat() if data_through else None,
        "areas": AREAS,
        "metrics": METRIC_CONFIG,
        "periods": periods,
        "top_k": TOP_K,
        "stations": stations,
        "leaders": leaders,
        "station_records": station_records,
        "method_note": (
            "Meteorologische Dekaden: 1.=01.–10., 2.=11.–20., 3.=21.–Monatsende. "
            "Aus den täglichen DWD-KL-Werten TXK (Tmax) und TNK (Tmin) werden je Dekade "
            "das höchste und niedrigste Tmax sowie das höchste und niedrigste Tmin bestimmt. "
            "Deutschland umfasst alle verfügbaren deutschen Stationen; Bundesländer folgen "
            "den DWD-Stationsmetadaten zum jeweiligen Beobachtungstag."
        ),
    }

    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")

    expected_metrics = {"txk_high", "txk_low", "tnk_high", "tnk_low"}
    if len(payload["areas"]) != 17:
        raise RuntimeError(f"Erwartet 17 Gebiete, erhalten: {len(payload['areas'])}")
    if len(payload["periods"]) != 36:
        raise RuntimeError(f"Erwartet 36 Dekaden, erhalten: {len(payload['periods'])}")
    if set(payload["metrics"]) != expected_metrics:
        raise RuntimeError("Unerwartete Parameter.")
    if not payload["data_through"]:
        raise RuntimeError("Kein Datenstand ermittelt.")

    print("Dekadenrekorde erfolgreich gebaut.", flush=True)
    print(f"Datenzeitraum: {payload['data_start']} bis {payload['data_through']}", flush=True)
    print(f"Gebiete: {len(payload['areas'])}", flush=True)
    print(f"Dekaden: {len(payload['periods'])}", flush=True)
    print(f"Metadatensegmente in Ausgabe: {len(payload['stations']):,}", flush=True)
    print(f"Ausgabe: {output} ({output.stat().st_size / 1024 / 1024:.1f} MB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
