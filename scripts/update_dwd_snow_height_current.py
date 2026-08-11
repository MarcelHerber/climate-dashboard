#!/usr/bin/env python3
"""Update the current DWD snow-height hydrological year.

Step 4 only:
  * reads station_snow_height_index.json and historical profiles from Step 3
  * downloads real DWD daily KL Recent data (SHK_TAG)
  * optionally merges the historical cache for the calendar-year portion
    already archived by DWD
  * writes one compact current file per profile station
  * writes station_snow_height_current_index.json
  * does NOT modify dashboard HTML

Missing SHK_TAG remains missing. A measured value of 0 cm is retained as 0 cm.

Hydrological year:
  01 Nov previous calendar year through 31 Oct of the naming year.
  On 11 Aug 2026 this is hydro year 2026:
  01.11.2025–31.10.2026.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BASE = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl"
)
RECENT_URL = BASE + "/recent/"

PROFILE_INDEX = Path("station_snow_height_index.json")
PROFILE_DIR = Path("station_snow_height_profiles")
HISTORY_CACHE_DIR = Path(".cache/dwd-snow-height/history_v1")

OUTPUT_INDEX = Path("station_snow_height_current_index.json")
OUTPUT_DIR = Path("station_snow_height_current")

OUTPUT_VERSION = 1
WORKERS = 10
TIMEOUT = 90
TRIES = 4
UA = "climate-dashboard-dwd-snow-current/1.0 (+GitHub Actions)"
BERLIN = ZoneInfo("Europe/Berlin")

SNOW_THRESHOLDS_CM = (1, 5, 10, 20, 50, 100)


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
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last_error = exc
        except Exception as exc:
            last_error = exc

        if attempt < attempts:
            time.sleep(1.5 * attempt)

    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last_error}")


def decode_product(data: bytes) -> str:
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "MESS_DATUM" in text:
            return text

    return data.decode("latin-1", errors="replace")


def parse_recent_zip(raw: bytes) -> dict[date, float]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".txt")
            and name.split("/")[-1].lower().startswith("produkt_")
        ]
        if not members:
            raise RuntimeError("Keine produkt_*.txt im Recent-KL-ZIP.")

        product_members = [archive.read(name) for name in members]

    values: dict[date, float] = {}

    for data in product_members:
        reader = csv.DictReader(
            io.StringIO(decode_product(data)),
            delimiter=";",
        )

        raw_fields = reader.fieldnames or []
        lookup = {
            (field or "").strip().upper(): (field or "").strip()
            for field in raw_fields
        }

        snow_field = lookup.get("SHK_TAG") or lookup.get("SHK")
        date_field = lookup.get("MESS_DATUM")

        if not date_field:
            raise RuntimeError("MESS_DATUM fehlt im KL-Produkt.")
        if not snow_field:
            raise RuntimeError("SHK_TAG/SHK fehlt im KL-Produkt.")

        for raw_row in reader:
            row = {
                (key or "").strip(): (
                    value.strip() if isinstance(value, str) else value
                )
                for key, value in raw_row.items()
            }

            stamp = str(row.get(date_field) or "").strip()
            try:
                day = datetime.strptime(stamp, "%Y%m%d").date()
            except ValueError:
                continue

            raw_value = row.get(snow_field)
            if raw_value in (None, ""):
                continue

            try:
                value = float(str(raw_value).replace(",", "."))
            except ValueError:
                continue

            if (
                not math.isfinite(value)
                or value <= -900
                or value < 0
            ):
                continue

            values[day] = round(value, 1)

    return values


def hydrological_year_for_day(day: date) -> int:
    return day.year + 1 if day.month >= 11 else day.year


def hydrological_bounds(hydro_year: int) -> tuple[date, date]:
    return date(hydro_year - 1, 11, 1), date(hydro_year, 10, 31)


def current_hydrological_year(today: date) -> int:
    return hydrological_year_for_day(today)


def load_historical_baseline(
    station_id: str,
    start: date,
    end: date,
) -> dict[date, float]:
    path = HISTORY_CACHE_DIR / f"{station_id}.json.gz"
    if not path.exists():
        return {}

    payload = read_gzip_json(path)
    result: dict[date, float] = {}

    for row in payload.get("rows") or []:
        if not isinstance(row, list) or len(row) < 2:
            continue

        try:
            day = date.fromisoformat(str(row[0]))
            value = float(row[1])
        except (ValueError, TypeError):
            continue

        if start <= day <= end and math.isfinite(value) and value >= 0:
            result[day] = round(value, 1)

    return result


def load_reference_medians(
    profile_path: Path,
) -> dict[str, float]:
    profile = read_json(profile_path)
    columns = profile.get("daily_columns") or []
    try:
        md_i = columns.index("month_day")
        median_i = columns.index("median_cm")
    except ValueError as exc:
        raise RuntimeError(
            f"Profil {profile_path} ohne erwartete daily_columns."
        ) from exc

    result: dict[str, float] = {}

    for row in profile.get("daily") or []:
        if not isinstance(row, list):
            continue
        if len(row) <= max(md_i, median_i):
            continue

        month_day = row[md_i]
        raw_median = row[median_i]

        if not month_day or raw_median is None:
            continue

        try:
            value = float(raw_median)
        except (TypeError, ValueError):
            continue

        if math.isfinite(value):
            result[str(month_day)] = value

    return result


def longest_observed_snow_cover_streak(
    values: dict[date, float],
    threshold: float = 1.0,
) -> int:
    """Missing dates break a streak; they are not assumed to be 0 cm."""
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
        else:
            current = 0

        previous_day = day

    return longest


def current_summary(
    values: dict[date, float],
    medians: dict[str, float],
) -> dict[str, Any]:
    if not values:
        return {
            "valid_observation_days": 0,
            "last_observation": None,
            "last_value_cm": None,
            "last_reference_median_cm": None,
            "last_anomaly_cm": None,
            "max_cm": None,
            "max_dates": [],
            "snow_cover_days_observed": {
                str(threshold): 0
                for threshold in SNOW_THRESHOLDS_CM
            },
            "longest_observed_snow_cover_streak": 0,
        }

    ordered_days = sorted(values)
    last_day = ordered_days[-1]
    last_value = values[last_day]
    last_median = medians.get(last_day.strftime("%m-%d"))
    last_anomaly = (
        round(last_value - last_median, 1)
        if last_median is not None
        else None
    )

    maximum = max(values.values())
    max_dates = [
        day.isoformat()
        for day in ordered_days
        if values[day] == maximum
    ]

    threshold_counts = {
        str(threshold): sum(
            1
            for value in values.values()
            if value >= threshold
        )
        for threshold in SNOW_THRESHOLDS_CM
    }

    positive_days = [
        day
        for day in ordered_days
        if values[day] >= 1.0
    ]

    comparable_anomalies = []
    for day in ordered_days:
        ref = medians.get(day.strftime("%m-%d"))
        if ref is not None:
            comparable_anomalies.append(values[day] - ref)

    return {
        "valid_observation_days": len(values),
        "last_observation": last_day.isoformat(),
        "last_value_cm": round(last_value, 1),
        "last_reference_median_cm": (
            round(last_median, 1)
            if last_median is not None
            else None
        ),
        "last_anomaly_cm": last_anomaly,
        "max_cm": round(maximum, 1),
        "max_dates": max_dates,
        "snow_cover_days_observed": threshold_counts,
        "first_observed_snow_cover_day": (
            positive_days[0].isoformat()
            if positive_days
            else None
        ),
        "last_observed_snow_cover_day": (
            positive_days[-1].isoformat()
            if positive_days
            else None
        ),
        "longest_observed_snow_cover_streak": (
            longest_observed_snow_cover_streak(values, 1.0)
        ),
        "snow_depth_sum_observed_cm_days": round(
            sum(values.values()),
            1,
        ),
        "mean_observed_snow_depth_cm": round(
            sum(values.values()) / len(values),
            2,
        ),
        "max_daily_anomaly_cm": (
            round(max(comparable_anomalies), 1)
            if comparable_anomalies
            else None
        ),
        "min_daily_anomaly_cm": (
            round(min(comparable_anomalies), 1)
            if comparable_anomalies
            else None
        ),
        "statistics_note": (
            "Current-season counts use only actually observed SHK_TAG "
            "days; missing dates are not converted to 0 cm."
        ),
    }


def build_one_station(
    root: Path,
    station: dict[str, Any],
    hydro_year: int,
    period_start: date,
    period_end: date,
    today: date,
) -> tuple[str, dict[str, Any] | None, str | None]:
    station_id = str(station["id"]).zfill(5)
    profile_path = root / str(
        station.get("file")
        or f"{PROFILE_DIR}/{station_id}.json"
    )

    try:
        medians = load_reference_medians(profile_path)

        # Historical cache provides the archived part (notably Nov/Dec 2025
        # for hydrological year 2026). It is optional so the daily updater is
        # still usable if the Actions cache is temporarily unavailable.
        historical = load_historical_baseline(
            station_id,
            period_start,
            min(period_end, date(2025, 12, 31)),
        )

        recent: dict[date, float] = {}
        recent_error = None

        try:
            raw = request_bytes(
                RECENT_URL
                + f"tageswerte_KL_{station_id}_akt.zip"
            )
            parsed = parse_recent_zip(raw)
            recent = {
                day: value
                for day, value in parsed.items()
                if period_start <= day <= min(period_end, today)
            }
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                recent_error = "Recent-KL-ZIP nicht vorhanden"
            else:
                raise

        merged = dict(historical)
        merged.update(recent)

        # Never include future dates if a malformed source contains them.
        merged = {
            day: value
            for day, value in merged.items()
            if period_start <= day <= min(period_end, today)
        }

        if not merged:
            return (
                station_id,
                None,
                recent_error or "Keine SHK_TAG-Werte im aktuellen hydrologischen Jahr",
            )

        rows = []
        for day, value in sorted(merged.items()):
            reference = medians.get(day.strftime("%m-%d"))
            anomaly = (
                round(value - reference, 1)
                if reference is not None
                else None
            )
            rows.append(
                [
                    day.isoformat(),
                    round(value, 1),
                    round(reference, 1)
                    if reference is not None
                    else None,
                    anomaly,
                ]
            )

        summary = current_summary(merged, medians)
        recent_days = sorted(recent)

        payload = {
            "version": OUTPUT_VERSION,
            "station_id": station_id,
            "name": station.get("name"),
            "state": station.get("state"),
            "height": station.get("height"),
            "hydrological_year": hydro_year,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "columns": [
                "date",
                "snow_cm",
                "reference_median_cm",
                "anomaly_cm",
            ],
            "rows": rows,
            "summary": summary,
            "sources": {
                "historical_cache_days": len(historical),
                "recent_kl_days": len(recent),
                "recent_first": (
                    recent_days[0].isoformat()
                    if recent_days
                    else None
                ),
                "recent_last": (
                    recent_days[-1].isoformat()
                    if recent_days
                    else None
                ),
                "recent_warning": recent_error,
            },
        }

        return station_id, payload, None

    except Exception as exc:
        return station_id, None, str(exc)


def main() -> int:
    root = Path(".").resolve()
    index_path = root / PROFILE_INDEX

    if not index_path.exists():
        raise RuntimeError(
            "station_snow_height_index.json fehlt. "
            "Zuerst Schritt 3 ausführen."
        )

    profile_index = read_json(index_path)
    stations = profile_index.get("stations") or []

    if len(stations) < 250:
        raise RuntimeError(
            f"Zu wenige historische Schneehöhenprofile: {len(stations)}."
        )

    now_berlin = datetime.now(BERLIN)
    today = now_berlin.date()
    hydro_year = current_hydrological_year(today)
    period_start, period_end = hydrological_bounds(hydro_year)

    log("=== DWD SCHNEEHÖHE · SCHRITT 4 ===")
    log(f"Aktuelles hydrologisches Jahr: {hydro_year}")
    log(
        f"Zeitraum: {period_start:%d.%m.%Y}–"
        f"{period_end:%d.%m.%Y}"
    )
    log(f"Historische Profile: {len(stations):,}")
    log(
        "Fehlende SHK_TAG-Tage bleiben fehlend; "
        "nur gemeldete 0 cm sind 0 cm."
    )
    log()

    history_cache_available = (root / HISTORY_CACHE_DIR).exists()
    log(
        "Historischer Cache für archivierten Saisonanfang: "
        + ("vorhanden" if history_cache_available else "nicht vorhanden")
    )
    log("Prüfe DWD-Recent-KL ...")

    output_dir = root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(
                build_one_station,
                root,
                station,
                hydro_year,
                period_start,
                period_end,
                today,
            ): str(station["id"]).zfill(5)
            for station in stations
        }

        for index, future in enumerate(as_completed(futures), start=1):
            station_id = futures[future]

            try:
                sid, payload, warning = future.result()
            except Exception as exc:
                sid, payload, warning = station_id, None, str(exc)

            if payload is not None:
                results[sid] = payload
                write_json_compact(
                    output_dir / f"{sid}.json",
                    payload,
                )

            if warning:
                warnings.append(f"{sid}: {warning}")

            if index % 40 == 0 or index == len(futures):
                log(
                    f"  verarbeitet {index:,}/{len(futures):,} | "
                    f"mit Saisonwerten {len(results):,} | "
                    f"Hinweise {len(warnings):,}"
                )

    result_ids = set(results)

    # Remove current files for stations no longer in the historical profile
    # index or with no current-season measurements.
    valid_profile_ids = {
        str(station["id"]).zfill(5)
        for station in stations
    }
    for old in output_dir.glob("*.json"):
        if old.stem not in valid_profile_ids or old.stem not in result_ids:
            old.unlink()

    if len(results) < 200:
        raise RuntimeError(
            f"Nur {len(results)} Stationen mit aktuellen Saisonwerten; "
            "das ist für das bestehende Profilnetz unplausibel."
        )

    overall_last = max(
        (
            date.fromisoformat(
                payload["summary"]["last_observation"]
            )
            for payload in results.values()
            if payload["summary"].get("last_observation")
        ),
        default=None,
    )

    state_counts = Counter(
        payload.get("state")
        for payload in results.values()
    )

    station_rows = []

    for station in stations:
        sid = str(station["id"]).zfill(5)
        payload = results.get(sid)

        station_rows.append(
            {
                "id": sid,
                "name": station.get("name"),
                "state": station.get("state"),
                "height": station.get("height"),
                "reference_status": station.get(
                    "reference_status"
                ),
                "reference_years_available": station.get(
                    "reference_years_available"
                ),
                "current_available": payload is not None,
                "last_observation": (
                    payload["summary"].get("last_observation")
                    if payload
                    else None
                ),
                "last_value_cm": (
                    payload["summary"].get("last_value_cm")
                    if payload
                    else None
                ),
                "max_cm": (
                    payload["summary"].get("max_cm")
                    if payload
                    else None
                ),
                "file": (
                    f"{OUTPUT_DIR}/{sid}.json"
                    if payload
                    else None
                ),
            }
        )

    index_payload = {
        "version": OUTPUT_VERSION,
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "hydrological_year": hydro_year,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "data_through": (
            overall_last.isoformat()
            if overall_last
            else None
        ),
        "profile_station_count": len(stations),
        "stations_with_current_season_values": len(results),
        "missing_or_unavailable_count": len(stations) - len(results),
        "historical_cache_available": history_cache_available,
        "states_with_current_values": dict(state_counts),
        "columns": [
            "date",
            "snow_cm",
            "reference_median_cm",
            "anomaly_cm",
        ],
        "note": (
            "Current hydrological-year SHK_TAG observations. "
            "Missing dates remain missing and are never converted "
            "to 0 cm. Daily anomaly is measured snow depth minus "
            "the station's 1991–2020 hydrological-year median."
        ),
        "stations": station_rows,
    }

    write_json_compact(root / OUTPUT_INDEX, index_payload)

    log()
    log("=" * 92)
    log("AKTUELLE SCHNEEHÖHEN-SAISON FERTIG")
    log("=" * 92)
    log(f"Hydrologisches Jahr: {hydro_year}")
    log(
        f"Stationen mit Saisonwerten: "
        f"{len(results):,}/{len(stations):,}"
    )
    log(
        f"Netz-Datenstand: "
        f"{overall_last.isoformat() if overall_last else '—'}"
    )
    log(f"Index: {OUTPUT_INDEX}")
    log(f"Stationsdateien: {OUTPUT_DIR}/")

    log()
    log("Stichproben:")
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

    by_id = {
        str(station["id"]).zfill(5): station
        for station in stations
    }

    for sid in preferred:
        station = by_id.get(sid)
        payload = results.get(sid)

        if not station:
            continue

        if not payload:
            log(
                f"  {sid} | {station.get('name')} | "
                "keine Saisonwerte"
            )
            continue

        summary = payload["summary"]
        log(
            f"  {sid} | {station.get('name')} | "
            f"{summary['valid_observation_days']} gültige Tage | "
            f"zuletzt {summary['last_observation']} = "
            f"{summary['last_value_cm']} cm | "
            f"Maximum {summary['max_cm']} cm | "
            f"letzte Abweichung zum Median "
            f"{summary['last_anomaly_cm']} cm"
        )

    if warnings:
        log()
        log(f"Hinweise/Einzelfehler: {len(warnings)}")
        for warning in warnings[:30]:
            log(f"  - {warning}")
        if len(warnings) > 30:
            log(f"  ... weitere {len(warnings) - 30}")

    log()
    log(
        "Nächster Schritt nach Sichtung dieses Logs: "
        "Schneehöhenbereich in index.html einbauen."
    )

    return 0


def self_test() -> None:
    assert current_hydrological_year(date(2026, 8, 11)) == 2026
    assert current_hydrological_year(date(2026, 11, 1)) == 2027

    start, end = hydrological_bounds(2026)
    assert start == date(2025, 11, 1)
    assert end == date(2026, 10, 31)

    product = (
        "STATIONS_ID;MESS_DATUM;QN_4;SHK_TAG;eor\n"
        "5792;20251101;10;0;eor\n"
        "5792;20260110;10;120;eor\n"
        "5792;20260111;10;-999;eor\n"
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

    parsed = parse_recent_zip(buffer.getvalue())
    assert parsed[date(2025, 11, 1)] == 0.0
    assert parsed[date(2026, 1, 10)] == 120.0
    assert date(2026, 1, 11) not in parsed

    values = {
        date(2026, 1, 1): 5.0,
        date(2026, 1, 2): 6.0,
        # 03 Jan deliberately missing: must break the streak.
        date(2026, 1, 4): 7.0,
    }
    assert longest_observed_snow_cover_streak(values) == 2

    medians = {
        "01-01": 3.0,
        "01-02": 4.0,
        "01-04": 8.0,
    }
    summary = current_summary(values, medians)
    assert summary["last_observation"] == "2026-01-04"
    assert summary["last_value_cm"] == 7.0
    assert summary["last_anomaly_cm"] == -1.0
    assert summary["valid_observation_days"] == 3

    print("DWD snow-height current-season self-test OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
