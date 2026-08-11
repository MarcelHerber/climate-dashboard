#!/usr/bin/env python3
"""Build compact historical DWD snow-height profiles from the Step-2 cache.

Step 3 only:
  * uses the existing historical cache through 2025
  * fixes the hydrological-year quality threshold at 98%
  * builds public compact profile JSONs
  * still does NOT integrate the current 2026 hydrological year
  * still does NOT modify the dashboard HTML

Output:
  station_snow_height_index.json
  station_snow_height_profiles/<station_id>.json

Hydrological year:
  01 Nov previous calendar year through 31 Oct named by its ending year.
  Example: hydrological year 2026 = 01.11.2025–31.10.2026.

Reference:
  hydrological years 1991–2020.

Quality:
  a hydrological year is accepted when >=98% of its calendar days contain
  a real valid SHK_TAG measurement. Missing values are never treated as zero.

Climatology:
  median, p16, p84, p2.5, p97.5 for 1991–2020 accepted years.
  Historical daily maximum is calculated over all accepted historical years.
"""
from __future__ import annotations

import gzip
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

CACHE_DIR = Path(".cache/dwd-snow-height/history_v1")
CACHE_MANIFEST = Path(".cache/dwd-snow-height/history_manifest_v1.json")

OUTPUT_DIR = Path("station_snow_height_profiles")
OUTPUT_INDEX = Path("station_snow_height_index.json")

PROFILE_VERSION = 1
QUALITY_THRESHOLD = 0.98
MIN_ACCEPTED_HISTORY_YEARS = 30
REFERENCE_START = 1991
REFERENCE_END = 2020
MIN_REFERENCE_YEARS_FOR_CLIMATOLOGY = 10

SNOW_THRESHOLDS_CM = (1, 5, 10, 20, 50, 100)

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


def log(message: str = "") -> None:
    print(message, flush=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_gzip_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_compact(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def hydro_year_for_day(day: date) -> int:
    return day.year + 1 if day.month >= 11 else day.year


def hydro_year_bounds(hydro_year: int) -> tuple[date, date]:
    return date(hydro_year - 1, 11, 1), date(hydro_year, 10, 31)


def expected_days(hydro_year: int) -> int:
    start, end = hydro_year_bounds(hydro_year)
    return (end - start).days + 1


def canonical_month_days() -> list[str]:
    """366-slot hydrological axis from 11-01 through 10-31 including 02-29."""
    start = date(1999, 11, 1)
    end = date(2000, 10, 31)
    result = []
    day = start
    while day <= end:
        result.append(day.strftime("%m-%d"))
        day += timedelta(days=1)
    assert len(result) == 366
    return result


HYDRO_AXIS = canonical_month_days()


def percentile(values: list[float], q: float) -> float | None:
    """Linear interpolated percentile compatible with common scientific use."""
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])

    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return float(ordered[lower])

    weight = position - lower
    return (
        float(ordered[lower]) * (1.0 - weight)
        + float(ordered[upper]) * weight
    )


def round_or_none(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def build_year_maps(
    rows: list[list[Any]],
) -> dict[int, dict[date, float]]:
    years: dict[int, dict[date, float]] = defaultdict(dict)

    for day_text, raw_value in rows:
        try:
            day = date.fromisoformat(str(day_text))
            value = float(raw_value)
        except (ValueError, TypeError):
            continue

        if not math.isfinite(value) or value < 0:
            continue

        hydro_year = hydro_year_for_day(day)
        years[hydro_year][day] = value

    return dict(years)


def accepted_years(
    years: dict[int, dict[date, float]],
) -> dict[int, dict[date, float]]:
    result = {}

    for hydro_year, values in years.items():
        # Historical cache reaches 31 Dec 2025. Hydrological year 2026 is
        # incomplete and must not enter the historical climatology.
        if hydro_year > 2025:
            continue

        coverage = len(values) / expected_days(hydro_year)
        if coverage >= QUALITY_THRESHOLD:
            result[hydro_year] = values

    return result


def longest_snow_cover_streak(
    values: dict[date, float],
    threshold: float = 1.0,
) -> int:
    if not values:
        return 0

    longest = 0
    current = 0
    previous_day: date | None = None

    for day, value in sorted(values.items()):
        if value >= threshold:
            if (
                previous_day is not None
                and day == previous_day + timedelta(days=1)
            ):
                current += 1
            else:
                current = 1
            longest = max(longest, current)
            previous_day = day
        else:
            current = 0
            previous_day = day

    return longest


def annual_summary(
    hydro_year: int,
    values: dict[date, float],
) -> dict[str, Any]:
    expected = expected_days(hydro_year)
    valid_days = len(values)
    coverage = valid_days / expected if expected else 0.0

    if not values:
        return {
            "year": hydro_year,
            "valid_days": 0,
            "coverage": 0.0,
        }

    maximum = max(values.values())
    max_dates = sorted(
        day.isoformat()
        for day, value in values.items()
        if value == maximum
    )

    positive_days = sorted(
        day
        for day, value in values.items()
        if value >= 1.0
    )

    threshold_days = {
        str(threshold): sum(
            1 for value in values.values()
            if value >= threshold
        )
        for threshold in SNOW_THRESHOLDS_CM
    }

    return {
        "year": hydro_year,
        "valid_days": valid_days,
        "expected_days": expected,
        "coverage": round(coverage, 4),
        "max_cm": round(maximum, 1),
        "max_dates": max_dates,
        "snow_cover_days": threshold_days,
        "first_snow_cover_day": (
            positive_days[0].isoformat()
            if positive_days
            else None
        ),
        "last_snow_cover_day": (
            positive_days[-1].isoformat()
            if positive_days
            else None
        ),
        "longest_snow_cover_streak": longest_snow_cover_streak(
            values,
            1.0,
        ),
        "snow_depth_sum_cm_days": round(sum(values.values()), 1),
        "mean_snow_depth_cm": round(
            sum(values.values()) / valid_days,
            2,
        ),
    }


def reference_status(reference_year_count: int) -> str:
    if reference_year_count == 30:
        return "complete"
    if reference_year_count >= 25:
        return "good"
    if reference_year_count >= 15:
        return "usable"
    if reference_year_count >= MIN_REFERENCE_YEARS_FOR_CLIMATOLOGY:
        return "limited"
    return "insufficient"


def build_daily_climatology(
    accepted: dict[int, dict[date, float]],
) -> tuple[list[list[Any]], int]:
    reference_years = [
        year
        for year in range(REFERENCE_START, REFERENCE_END + 1)
        if year in accepted
    ]

    reference_by_md: dict[str, list[float]] = defaultdict(list)
    historical_max_by_md: dict[str, float] = {}

    for hydro_year, values in accepted.items():
        is_reference = REFERENCE_START <= hydro_year <= REFERENCE_END

        for day, value in values.items():
            month_day = day.strftime("%m-%d")

            previous = historical_max_by_md.get(month_day)
            if previous is None or value > previous:
                historical_max_by_md[month_day] = value

            if is_reference:
                reference_by_md[month_day].append(value)

    climatology = []

    for month_day in HYDRO_AXIS:
        samples = reference_by_md.get(month_day, [])
        historical_max = historical_max_by_md.get(month_day)

        if len(reference_years) < MIN_REFERENCE_YEARS_FOR_CLIMATOLOGY:
            # Preserve the historical maximum even when the 1991–2020
            # climatology is too thin for robust quantiles.
            climatology.append(
                [
                    month_day,
                    len(samples),
                    None,
                    None,
                    None,
                    None,
                    None,
                    round_or_none(historical_max),
                ]
            )
            continue

        if not samples:
            climatology.append(
                [
                    month_day,
                    0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    round_or_none(historical_max),
                ]
            )
            continue

        climatology.append(
            [
                month_day,
                len(samples),
                round_or_none(float(median(samples))),
                round_or_none(percentile(samples, 0.16)),
                round_or_none(percentile(samples, 0.84)),
                round_or_none(percentile(samples, 0.025)),
                round_or_none(percentile(samples, 0.975)),
                round_or_none(historical_max),
            ]
        )

    return climatology, len(reference_years)


def profile_from_cache(
    cache_payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    rows = cache_payload.get("rows") or []
    years = build_year_maps(rows)
    accepted = accepted_years(years)

    accepted_year_numbers = sorted(accepted)

    diagnostic = {
        "accepted_year_count": len(accepted_year_numbers),
        "raw_hydro_year_count": len(years),
    }

    if len(accepted_year_numbers) < MIN_ACCEPTED_HISTORY_YEARS:
        return None, diagnostic

    annual = [
        annual_summary(hydro_year, accepted[hydro_year])
        for hydro_year in accepted_year_numbers
    ]

    climatology, reference_year_count = build_daily_climatology(accepted)

    record_max = max(
        (
            summary["max_cm"]
            for summary in annual
            if summary.get("max_cm") is not None
        ),
        default=None,
    )
    record_years = [
        summary["year"]
        for summary in annual
        if record_max is not None
        and summary.get("max_cm") == record_max
    ]

    profile = {
        "version": PROFILE_VERSION,
        "station_id": cache_payload["station_id"],
        "name": cache_payload.get("name"),
        "state": cache_payload.get("state"),
        "height": cache_payload.get("height"),
        "lat": cache_payload.get("lat"),
        "lon": cache_payload.get("lon"),
        "quality": {
            "hydrological_year_min_coverage": QUALITY_THRESHOLD,
            "accepted_history_years": len(accepted_year_numbers),
            "history_start_year": accepted_year_numbers[0],
            "history_end_year": accepted_year_numbers[-1],
            "reference_years_available": reference_year_count,
            "reference_status": reference_status(reference_year_count),
        },
        "reference": {
            "start_hydrological_year": REFERENCE_START,
            "end_hydrological_year": REFERENCE_END,
            "available_years": [
                year
                for year in range(REFERENCE_START, REFERENCE_END + 1)
                if year in accepted
            ],
        },
        "daily_columns": [
            "month_day",
            "n_reference",
            "median_cm",
            "p16_cm",
            "p84_cm",
            "p2_5_cm",
            "p97_5_cm",
            "historical_max_cm",
        ],
        "daily": climatology,
        "annual": annual,
        "records": {
            "max_snow_depth_cm": record_max,
            "hydrological_years": record_years,
        },
    }

    diagnostic["reference_year_count"] = reference_year_count
    diagnostic["reference_status"] = reference_status(reference_year_count)
    return profile, diagnostic


def main() -> int:
    root = Path(".").resolve()
    cache_dir = root / CACHE_DIR
    manifest_path = root / CACHE_MANIFEST

    log("=== DWD SCHNEEHÖHE · SCHRITT 3 ===")
    log("Kompakte historische Stationsprofile")
    log("Qualitätsgrenze: >=98% gültige SHK_TAG-Tage je hydrologischem Jahr")
    log("Referenz: hydrologische Jahre 1991–2020")
    log("Noch keine aktuelle Saison / noch keine HTML-Änderung.")
    log()

    if not cache_dir.exists() or not manifest_path.exists():
        raise RuntimeError(
            "Historischer Schneehöhen-Cache fehlt. "
            "Zuerst Workflow 'Build DWD snow-height historical cache' ausführen."
        )

    manifest = read_json(manifest_path)
    expected_candidates = int(manifest.get("candidate_count") or 0)

    cache_files = sorted(cache_dir.glob("*.json.gz"))
    if len(cache_files) < 250:
        raise RuntimeError(
            f"Historischer Cache unvollständig: nur {len(cache_files)} Stationsdateien."
        )

    log(f"Cache-Kandidaten laut Manifest: {expected_candidates:,}")
    log(f"Gefundene Stations-Caches: {len(cache_files):,}")

    output_dir = root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    stations = []
    skipped = []
    reference_status_counts = Counter()
    total_annual_rows = 0

    for index, cache_file in enumerate(cache_files, start=1):
        payload = read_gzip_json(cache_file)
        profile, diagnostic = profile_from_cache(payload)

        station_id = str(payload.get("station_id") or cache_file.name[:5])

        if profile is None:
            skipped.append(
                {
                    "station_id": station_id,
                    "name": payload.get("name"),
                    "state": payload.get("state"),
                    "accepted_history_years": diagnostic[
                        "accepted_year_count"
                    ],
                }
            )
        else:
            write_json_compact(
                output_dir / f"{station_id}.json",
                profile,
            )

            quality = profile["quality"]
            reference_status_counts[quality["reference_status"]] += 1
            total_annual_rows += len(profile["annual"])

            stations.append(
                {
                    "id": station_id,
                    "name": profile["name"],
                    "state": profile["state"],
                    "height": profile["height"],
                    "lat": profile["lat"],
                    "lon": profile["lon"],
                    "history_start_year": quality["history_start_year"],
                    "history_end_year": quality["history_end_year"],
                    "accepted_history_years": quality[
                        "accepted_history_years"
                    ],
                    "reference_years_available": quality[
                        "reference_years_available"
                    ],
                    "reference_status": quality["reference_status"],
                    "record_max_cm": profile["records"][
                        "max_snow_depth_cm"
                    ],
                    "file": f"{OUTPUT_DIR}/{station_id}.json",
                }
            )

        if index % 50 == 0 or index == len(cache_files):
            log(
                f"  verarbeitet {index:,}/{len(cache_files):,} | "
                f"Profile {len(stations):,} | "
                f"<30 Qualitätsjahre {len(skipped):,}"
            )

    valid_ids = {station["id"] for station in stations}
    for old in output_dir.glob("*.json"):
        if old.stem not in valid_ids:
            old.unlink()

    if not 250 <= len(stations) <= 280:
        raise RuntimeError(
            f"Profilzahl unplausibel: {len(stations)} "
            "(aus dem Qualitätslog wurden etwa 267 erwartet)."
        )

    stations.sort(
        key=lambda item: (
            STATE_ORDER.index(item["state"])
            if item["state"] in STATE_ORDER
            else 999,
            str(item["name"]).casefold(),
            item["id"],
        )
    )

    state_counts = Counter(
        station["state"]
        for station in stations
    )

    index_payload = {
        "version": PROFILE_VERSION,
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "historical_through": manifest.get("historical_through"),
        "hydrological_year": {
            "start": "11-01",
            "end": "10-31",
            "naming": (
                "year is named by ending calendar year; "
                "2026 = 2025-11-01 through 2026-10-31"
            ),
        },
        "quality": {
            "min_hydrological_year_coverage": QUALITY_THRESHOLD,
            "min_accepted_history_years": MIN_ACCEPTED_HISTORY_YEARS,
            "expected_valid_days_normal_year": math.ceil(
                365 * QUALITY_THRESHOLD
            ),
            "expected_valid_days_leap_hydro_year": math.ceil(
                366 * QUALITY_THRESHOLD
            ),
        },
        "reference": {
            "start_hydrological_year": REFERENCE_START,
            "end_hydrological_year": REFERENCE_END,
            "min_years_for_climatology": (
                MIN_REFERENCE_YEARS_FOR_CLIMATOLOGY
            ),
        },
        "daily_columns": [
            "month_day",
            "n_reference",
            "median_cm",
            "p16_cm",
            "p84_cm",
            "p2_5_cm",
            "p97_5_cm",
            "historical_max_cm",
        ],
        "station_count": len(stations),
        "skipped_below_30_quality_years": len(skipped),
        "states": [
            {
                "name": state,
                "count": state_counts.get(state, 0),
            }
            for state in STATE_ORDER
        ],
        "reference_status_counts": dict(reference_status_counts),
        "stations": stations,
        "source_note": (
            "DWD Climate Data Center, tägliche KL-Stationsmessungen "
            "SHK_TAG. Historische hydrologische Jahre werden nur bei "
            "mindestens 98% gültigen Tageswerten berücksichtigt. "
            "Fehlwerte werden nicht als 0 cm interpretiert."
        ),
    }

    write_json_compact(root / OUTPUT_INDEX, index_payload)

    log()
    log("=" * 92)
    log("SCHNEEHÖHEN-PROFILE FERTIG")
    log("=" * 92)
    log(f"Historische Profile: {len(stations):,}")
    log(f"Unter 30 Qualitätsjahren ausgeschlossen: {len(skipped):,}")
    log(f"Jahresstatistik-Zeilen: {total_annual_rows:,}")
    log(f"Index: {OUTPUT_INDEX}")
    log(f"Profile: {OUTPUT_DIR}/")
    log()

    log("Referenzqualität 1991–2020:")
    for status in ("complete", "good", "usable", "limited", "insufficient"):
        log(
            f"  {status}: "
            f"{reference_status_counts.get(status, 0):,}"
        )

    log()
    log("Profile nach Bundesland:")
    for state in STATE_ORDER:
        log(f"  {state}: {state_counts.get(state, 0)}")

    log()
    log("Stichproben:")
    preferred = (
        "05792",
        "00722",
        "01358",
        "05371",
        "03730",
        "02483",
        "01443",
        "01420",
        "04336",
    )

    by_id = {station["id"]: station for station in stations}
    for station_id in preferred:
        station = by_id.get(station_id)
        if not station:
            log(f"  {station_id}: kein 98%-Profil")
            continue
        log(
            f"  {station_id} | {station['name']} | "
            f"{station['accepted_history_years']} Qualitätsjahre | "
            f"Ref {station['reference_years_available']}/30 | "
            f"Status {station['reference_status']} | "
            f"Rekord {station['record_max_cm']} cm"
        )

    log()
    log(
        "Nächster Schritt nach Sichtung dieses Logs: "
        "aktuelles hydrologisches Jahr 2026 aus Recent-KL ergänzen."
    )
    return 0


def self_test() -> None:
    assert hydro_year_for_day(date(2025, 10, 31)) == 2025
    assert hydro_year_for_day(date(2025, 11, 1)) == 2026
    assert expected_days(2024) == 366
    assert expected_days(2025) == 365
    assert len(HYDRO_AXIS) == 366
    assert HYDRO_AXIS[0] == "11-01"
    assert "02-29" in HYDRO_AXIS
    assert HYDRO_AXIS[-1] == "10-31"

    values = [0.0, 10.0, 20.0, 30.0]
    assert percentile(values, 0.5) == 15.0
    assert median(values) == 15.0

    # Synthetic complete hydrological years.
    rows = []
    for hydro_year in range(1991, 2021):
        start, end = hydro_year_bounds(hydro_year)
        day = start
        while day <= end:
            rows.append(
                [
                    day.isoformat(),
                    float((hydro_year - 1990) % 20),
                ]
            )
            day += timedelta(days=1)

    years = build_year_maps(rows)
    accepted = accepted_years(years)
    assert len(accepted) == 30

    climatology, reference_year_count = build_daily_climatology(
        accepted
    )
    assert reference_year_count == 30
    assert len(climatology) == 366

    sample = next(
        item for item in climatology
        if item[0] == "01-15"
    )
    assert sample[1] == 30
    assert sample[2] is not None
    assert sample[7] is not None

    summary = annual_summary(2020, accepted[2020])
    assert summary["coverage"] == 1.0
    assert summary["valid_days"] == 366

    print("DWD snow-height profiles self-test OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
