#!/usr/bin/env python3
"""Estonian Environment Agency current-year daily Tmax/Tmin cache."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import update_ilmateenistus_estonia_station_cache as hist

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")

# Emergency guards only. They are intentionally wider than Estonian records
# and are meant to catch unit/schema/parser failures, not to diagnose weather.
CURRENT_TMAX_EMERGENCY_CEILING_C = 50.0
CURRENT_TMIN_EMERGENCY_FLOOR_C = -60.0
MAX_FRESHNESS_LAG_DAYS = 7


def log(msg: str = "") -> None:
    print(msg, flush=True)


def current_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / (
        f"ilmateenistus_estonia_current_{year}_v{FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, year: int) -> Path:
    return cache_dir / f"ilmateenistus_estonia_current_{year}_status.json"


def load_baseline(cache_dir: Path, year: int) -> dict[str, Any]:
    cutoff_year = year - 1
    path = hist.baseline_path(cache_dir, cutoff_year)

    if not hist.valid_final(path, cutoff_year):
        raise RuntimeError(
            "Estland-Historienbaseline fehlt oder ist unvollständig: "
            f"{path}"
        )

    obj = hist.load_pickle_gzip(path)
    if not isinstance(obj, dict):
        raise RuntimeError(f"Ungültiger Estland-Baselinecache: {path}")

    expected = set(hist.ACTIVE_STATION_CODES)
    actual = set(obj.get("records", {}))
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RuntimeError(
            "Estland-Baseline passt nicht zum eingefrorenen Aktivnetz. "
            f"Fehlend={missing}; zusätzlich={extra}"
        )

    return obj


def fetch_month(year: int, month: int) -> list[dict[str, Any]]:
    return hist.fetch_all_pages(
        hist.DAILY_PATH,
        [
            ("aasta", f"eq.{year}"),
            ("kuu", f"eq.{month}"),
            ("jaam_kood", hist.station_filter()),
            ("element_kood", "in.(DTAX,DTAN)"),
            (
                "select",
                "jaam_kood,jaam_nimi,aasta,kuu,paev,vaartus,element_kood",
            ),
            (
                "order",
                "jaam_kood.asc,aasta.asc,kuu.asc,paev.asc,element_kood.asc",
            ),
        ],
    )


def validate_current_day(
    sid: str,
    d: date,
    tmin: float | None,
    tmax: float | None,
) -> None:
    if (
        tmax is not None
        and float(tmax) > CURRENT_TMAX_EMERGENCY_CEILING_C
    ):
        raise RuntimeError(
            f"Estland Current Plausibilitätsfehler: {sid} "
            f"TMAX {tmax} C am {d}"
        )

    if (
        tmin is not None
        and float(tmin) < CURRENT_TMIN_EMERGENCY_FLOOR_C
    ):
        raise RuntimeError(
            f"Estland Current Plausibilitätsfehler: {sid} "
            f"TMIN {tmin} C am {d}"
        )

    if tmin is not None and tmax is not None and tmin > tmax:
        raise RuntimeError(
            f"Estland Current Plausibilitätsfehler: {sid} "
            f"TMIN {tmin} > TMAX {tmax} am {d}"
        )


def process_rows(
    rows: list[dict[str, Any]],
    *,
    year: int,
    through: date,
    records: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    """
    Pair DTAX and DTAN by station/day before consuming them.

    Returns:
      accepted station-days,
      ignored rows outside the requested year/through date.
    """
    by_day: dict[
        tuple[str, date],
        dict[str, float | None],
    ] = {}
    ignored = 0

    for row in rows:
        sid = str(row.get("jaam_kood") or "").strip()
        element = str(row.get("element_kood") or "").strip()
        d = hist.row_date(row)
        value = hist.number(row.get("vaartus"))

        if sid not in hist.ACTIVE_STATION_CODES:
            ignored += 1
            continue
        if element not in hist.ELEMENTS or d is None:
            ignored += 1
            continue
        if d.year != year or d > through:
            ignored += 1
            continue
        if value is None:
            continue

        slot = by_day.setdefault(
            (sid, d),
            {
                hist.PARAM_TMAX: None,
                hist.PARAM_TMIN: None,
            },
        )
        slot[element] = value

    accepted = 0
    for (sid, d), values in sorted(
        by_day.items(),
        key=lambda item: (item[0][0], item[0][1]),
    ):
        tmax = values[hist.PARAM_TMAX]
        tmin = values[hist.PARAM_TMIN]
        validate_current_day(sid, d, tmin, tmax)

        if tmin is None and tmax is None:
            continue

        rec = records.setdefault(sid, hist.empty_record())
        if hist.consume_day(rec, d, tmin, tmax):
            accepted += 1

    return accepted, ignored


def record_events(
    baseline: dict[str, Any],
    records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Compare the current year with the historical calendar-day baseline.

    Deliberately only the two required record directions are emitted:
      - higher Tmax
      - lower Tmin
    No lowest-Tmax or highest-Tmin events are generated.
    """
    old_records = baseline.get("records", {})
    events: list[dict[str, Any]] = []

    for sid, rec in records.items():
        old = old_records.get(sid)
        if not isinstance(old, dict):
            continue

        for mmdd, pair in rec.get("calendar_tmax", {}).items():
            prior = old.get("calendar_tmax", {}).get(mmdd)
            if prior is None:
                continue
            if float(pair[0]) > float(prior[0]):
                events.append(
                    {
                        "station_id": sid,
                        "date": str(pair[1]),
                        "element": "TMAX",
                        "value": float(pair[0]),
                        "previous_value": float(prior[0]),
                        "previous_date": str(prior[1]),
                    }
                )

        for mmdd, pair in rec.get("calendar_tmin", {}).items():
            prior = old.get("calendar_tmin", {}).get(mmdd)
            if prior is None:
                continue
            if float(pair[0]) < float(prior[0]):
                events.append(
                    {
                        "station_id": sid,
                        "date": str(pair[1]),
                        "element": "TMIN",
                        "value": float(pair[0]),
                        "previous_value": float(prior[0]),
                        "previous_date": str(prior[1]),
                    }
                )

    events.sort(
        key=lambda item: (
            item["date"],
            item["station_id"],
            item["element"],
        )
    )
    return events


def build_current(
    cache_dir: Path,
    year: int,
    *,
    force: bool = False,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = current_path(cache_dir, year)
    stat = status_path(cache_dir, year)

    if force:
        out.unlink(missing_ok=True)
        stat.unlink(missing_ok=True)

    baseline = load_baseline(cache_dir, year)

    today = date.today()
    if year > today.year:
        raise ValueError(
            f"Current-Year-Updater kann kein zukünftiges Jahr laden: {year}"
        )
    through = today if year == today.year else date(year, 12, 31)

    log("=== ESTLAND AKTUELLES JAHR ===")
    log(
        f"{year} | {hist.PARAM_TMAX}=Tmax | "
        f"{hist.PARAM_TMIN}=Tmin | bis {through}"
    )
    log(
        f"Eingefrorenes Aktivnetz: "
        f"{len(hist.ACTIVE_STATION_CODES)} Stationen"
    )

    records: dict[str, dict[str, Any]] = {}
    inventory = dict(baseline.get("inventory", {}))
    raw_element_rows = 0
    ignored_rows = 0
    request_months = 0

    for month in range(1, through.month + 1):
        rows = fetch_month(year, month)
        raw_element_rows += len(rows)
        request_months += 1

        accepted, ignored = process_rows(
            rows,
            year=year,
            through=through,
            records=records,
        )
        ignored_rows += ignored

        station_days = sum(
            int(rec.get("observation_days", 0))
            for rec in records.values()
        )
        log(
            f"Estland Current {year}-{month:02d}: "
            f"{len(rows):,} Element-Zeilen | "
            f"{accepted:,} Stationstage | "
            f"{len(records)} Stationsreihen | "
            f"gesamt {station_days:,} Stationstage"
        )

    if not records:
        raise RuntimeError(
            f"Estland Current {year} enthält keine Stationsreihen."
        )

    expected = set(hist.ACTIVE_STATION_CODES)
    actual = set(records)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise RuntimeError(
            "Estland Current passt nicht zum eingefrorenen Aktivnetz. "
            f"Fehlend={missing}; zusätzlich={extra}"
        )

    first_dates = [
        rec["first_date"]
        for rec in records.values()
        if rec.get("first_date")
    ]
    last_dates = [
        rec["last_date"]
        for rec in records.values()
        if rec.get("last_date")
    ]
    data_first_date = min(first_dates) if first_dates else None
    data_last_date = max(last_dates) if last_dates else None
    if data_last_date is None:
        raise RuntimeError("Estland Current besitzt kein letztes Datumsfeld.")

    latest_date = date.fromisoformat(data_last_date)
    freshness_days = (through - latest_date).days
    if freshness_days < 0:
        raise RuntimeError(
            f"Estland Current enthält Zukunftsdatum {data_last_date}."
        )
    if freshness_days > MAX_FRESHNESS_LAG_DAYS:
        raise RuntimeError(
            "Estland Current ist zu alt: "
            f"letztes Datum {data_last_date}, "
            f"{freshness_days} Tage hinter {through}."
        )

    stale_stations: list[str] = []
    latest_by_station: dict[str, str] = {}
    for sid, rec in records.items():
        last_text = rec.get("last_date")
        if not last_text:
            stale_stations.append(sid)
            continue
        latest_by_station[sid] = str(last_text)
        lag = (through - date.fromisoformat(str(last_text))).days
        if lag > MAX_FRESHNESS_LAG_DAYS:
            stale_stations.append(sid)

    if stale_stations:
        raise RuntimeError(
            "Estland Current: aktive Stationen sind >"
            f"{MAX_FRESHNESS_LAG_DAYS} Tage veraltet: "
            + ", ".join(sorted(stale_stations))
        )

    station_days = sum(
        int(rec.get("observation_days", 0))
        for rec in records.values()
    )
    events = record_events(baseline, records)

    payload = {
        "format_version": FORMAT_VERSION,
        "source": hist.SOURCE,
        "country": hist.COUNTRY,
        "country_code": hist.COUNTRY_CODE,
        "year": year,
        "complete": True,
        "parameters": {
            "TMAX": hist.PARAM_TMAX,
            "TMIN": hist.PARAM_TMIN,
        },
        "active_station_codes": list(hist.ACTIVE_STATION_CODES),
        "inventory": inventory,
        "records": records,
        "latest_observation_by_station": latest_by_station,
        "data_first_date": data_first_date,
        "data_last_date": data_last_date,
        "freshness_days": freshness_days,
        "rows_with_temperature": station_days,
        "raw_element_rows": raw_element_rows,
        "ignored_rows": ignored_rows,
        "record_events": events,
        "request_months": request_months,
        "historical_cutoff_year": year - 1,
        "historical_baseline_file": str(
            hist.baseline_path(cache_dir, year - 1)
        ),
        "public_url": hist.PUBLIC_URL,
        "api_root": hist.API_ROOT,
    }

    hist.atomic_pickle_gzip(out, payload)

    status = {
        "format_version": FORMAT_VERSION,
        "source": hist.SOURCE,
        "country": hist.COUNTRY,
        "year": year,
        "complete": True,
        "expected_active_station_count": len(hist.ACTIVE_STATION_CODES),
        "station_count": len(records),
        "inventory_count": len(inventory),
        "rows_with_temperature": station_days,
        "raw_element_rows": raw_element_rows,
        "data_first_date": data_first_date,
        "data_last_date": data_last_date,
        "freshness_days": freshness_days,
        "record_event_count": len(events),
        "request_months": request_months,
        "current_file": str(out),
        "historical_baseline_file": str(
            hist.baseline_path(cache_dir, year - 1)
        ),
    }
    hist.atomic_json(stat, status)

    log()
    log("=== ESTLAND CURRENT SUMMARY ===")
    log(f"Stationsreihen mit {year}-Daten: {len(records)}")
    log(f"Inventar inkl. Historie: {len(inventory)}")
    log(f"Stationstage: {station_days:,}")
    log(f"Element-Zeilen: {raw_element_rows:,}")
    log(f"Datenzeitraum: {data_first_date} bis {data_last_date}")
    log(f"Aktualitäts-Lag: {freshness_days} Tag(e)")
    log(
        "Neue Tagesrekorde gegenüber Historie bis "
        f"{year - 1}: {len(events):,}"
    )
    log(
        "Rekordrichtungen: nur höheres Tmax und niedrigeres Tmin."
    )
    log(f"Output: {out}")
    log("Estonia current OK.")
    return out


def self_test() -> None:
    baseline = {
        "records": {
            "AJHARK01": {
                "calendar_tmax": {
                    "08-09": [30.0, "2010-08-09"],
                },
                "calendar_tmin": {
                    "08-09": [-2.0, "1999-08-09"],
                },
            }
        }
    }
    current = {
        "AJHARK01": {
            "calendar_tmax": {
                "08-09": [31.0, "2026-08-09"],
            },
            "calendar_tmin": {
                "08-09": [-3.0, "2026-08-09"],
            },
        }
    }
    events = record_events(baseline, current)
    assert len(events) == 2
    assert {item["element"] for item in events} == {"TMAX", "TMIN"}

    no_false_events = {
        "AJHARK01": {
            "calendar_tmax": {
                "08-09": [29.0, "2026-08-09"],
            },
            "calendar_tmin": {
                "08-09": [-1.0, "2026-08-09"],
            },
        }
    }
    assert record_events(baseline, no_false_events) == []

    validate_current_day(
        "AJHARK01",
        date(2026, 1, 1),
        -20.0,
        10.0,
    )

    for tmin, tmax in [
        (-61.0, -20.0),
        (-10.0, 51.0),
        (5.0, 4.0),
    ]:
        try:
            validate_current_day(
                "AJHARK01",
                date(2026, 1, 1),
                tmin,
                tmax,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError(
                "Estland Current plausibility guard accepted bad value"
            )

    rows = [
        {
            "jaam_kood": "AJHARK01",
            "jaam_nimi": "Tallinn-Harku",
            "aasta": 2026,
            "kuu": 1,
            "paev": 1,
            "vaartus": "2.0",
            "element_kood": "DTAX",
        },
        {
            "jaam_kood": "AJHARK01",
            "jaam_nimi": "Tallinn-Harku",
            "aasta": 2026,
            "kuu": 1,
            "paev": 1,
            "vaartus": "-5.0",
            "element_kood": "DTAN",
        },
    ]
    records: dict[str, dict[str, Any]] = {}
    accepted, ignored = process_rows(
        rows,
        year=2026,
        through=date(2026, 1, 2),
        records=records,
    )
    assert accepted == 1
    assert ignored == 0
    assert records["AJHARK01"]["tmax_abs"] == [
        2.0,
        "2026-01-01",
    ]
    assert records["AJHARK01"]["tmin_abs"] == [
        -5.0,
        "2026-01-01",
    ]

    print("Estonia current-year self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--cache-dir",
        default=str(CACHE_DIR_DEFAULT),
    )
    parser.add_argument(
        "--year",
        type=int,
        default=date.today().year,
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_current(
        Path(args.cache_dir),
        args.year,
        force=args.force,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
