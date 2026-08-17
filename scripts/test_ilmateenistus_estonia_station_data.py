#!/usr/bin/env python3
"""Probe Estonian Environment Agency daily Tmax/Tmin station coverage.

Official API:
  https://keskkonnaandmed.envir.ee/f_kliima_paev
  https://keskkonnaandmed.envir.ee/f_kliima_jaam_vaatlus

Daily temperature element codes:
  DTAX = daily maximum air temperature (deg C)
  DTAN = daily minimum air temperature (deg C)

The probe deliberately does not build or modify the production station cache. It
answers one question first: how many currently reporting Estonian stations have
both daily Tmax and Tmin, and how far back do those two series reach in the
public daily climate API?
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from datetime import date
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_ROOT = "https://keskkonnaandmed.envir.ee"
DAILY_PATH = "/f_kliima_paev"
STATION_PATH = "/f_kliima_jaam_vaatlus"
PROFILE = "apijahialad"
ELEMENTS = ("DTAX", "DTAN")
USER_AGENT = "climate-dashboard-estonia-probe/1.0"


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _row_date(row: dict[str, Any]) -> date | None:
    try:
        return date(int(row["aasta"]), int(row["kuu"]), int(row["paev"]))
    except (KeyError, TypeError, ValueError):
        return None


def _api_get(
    path: str,
    params: Iterable[tuple[str, str]] = (),
    *,
    timeout: int = 45,
    attempts: int = 4,
) -> list[dict[str, Any]]:
    query = urlencode(list(params), doseq=True, safe="().,*:-")
    url = f"{API_ROOT}{path}"
    if query:
        url += "?" + query

    header_modes = [
        (
            "Accept-Profile",
            {
                "Accept": "application/json",
                "Accept-Profile": PROFILE,
                "User-Agent": USER_AGENT,
            },
        ),
        (
            "default schema",
            {
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        ),
    ]

    last_error: Exception | None = None
    last_detail = ""

    for mode_index, (mode_name, headers) in enumerate(header_modes):
        for attempt in range(1, attempts + 1):
            try:
                req = Request(url, headers=headers)
                with urlopen(req, timeout=timeout) as response:
                    payload = response.read().decode("utf-8", errors="replace")
                data = json.loads(payload)
                if not isinstance(data, list):
                    raise RuntimeError(
                        f"Unexpected API payload type: {type(data).__name__}"
                    )
                if mode_index > 0:
                    print(
                        "INFO API accepted request without Accept-Profile; "
                        "using the server default schema for this run.",
                        file=sys.stderr,
                    )
                return [row for row in data if isinstance(row, dict)]

            except HTTPError as exc:
                last_error = exc
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                compact = " ".join(body.split())
                last_detail = f"HTTP {exc.code}"
                if compact:
                    last_detail += f": {compact[:1200]}"

                # The official documentation recommends Accept-Profile:
                # apijahialad. In practice PostgREST can temporarily answer
                # 406 when that exposed-schema profile is unavailable. The
                # documented browser examples work via the default schema, so
                # try that path immediately instead of retrying the same 406.
                if exc.code == 406 and mode_index == 0:
                    print(
                        "WARN API returned 406 with Accept-Profile: apijahialad; "
                        "retrying once via the server default schema.",
                        file=sys.stderr,
                    )
                    if compact:
                        print(f"API 406 response: {compact[:1200]}", file=sys.stderr)
                    break

                retryable = exc.code in {408, 425, 429, 500, 502, 503, 504}
                if not retryable or attempt == attempts:
                    break

                sleep_seconds = min(8, 1.5 * attempt)
                print(
                    f"WARN API request failed in {mode_name} mode "
                    f"({attempt}/{attempts}): {last_detail}; "
                    f"retry in {sleep_seconds:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(sleep_seconds)

            except (URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                last_detail = str(exc)
                if attempt == attempts:
                    break
                sleep_seconds = min(8, 1.5 * attempt)
                print(
                    f"WARN API request failed in {mode_name} mode "
                    f"({attempt}/{attempts}): {exc}; "
                    f"retry in {sleep_seconds:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(sleep_seconds)
        else:
            continue

        # A 406 in profile mode deliberately falls through to the default
        # schema mode. Any other terminal error should not silently switch.
        if isinstance(last_error, HTTPError) and last_error.code == 406 and mode_index == 0:
            continue
        break

    detail = f" ({last_detail})" if last_detail else ""
    raise RuntimeError(
        f"API request failed after fallback attempts: {url}: {last_error}{detail}"
    )


def _month_pairs(today: date, months_back: int) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(max(1, months_back)):
        pairs.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return pairs


def fetch_station_metadata() -> tuple[dict[str, dict[str, Any]], list[str]]:
    rows = _api_get(STATION_PATH, [("limit", "20000")])
    keys = sorted({key for row in rows[:50] for key in row})

    by_code: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("jaam_kood") or "").strip()
        if not code:
            continue
        old = by_code.get(code)
        if old is None:
            by_code[code] = row
            continue

        # The metadata service can contain several station-period rows. Prefer
        # the row with the newest start/end text so current metadata wins.
        old_rank = (
            str(old.get("jaam_periood_lopp") or "9999-12-31"),
            str(old.get("jaam_periood_algus") or ""),
        )
        new_rank = (
            str(row.get("jaam_periood_lopp") or "9999-12-31"),
            str(row.get("jaam_periood_algus") or ""),
        )
        if new_rank >= old_rank:
            by_code[code] = row

    return by_code, keys


def fetch_recent_temperature_rows(today: date, months_back: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year, month in _month_pairs(today, months_back):
        params = [
            ("aasta", f"eq.{year}"),
            ("kuu", f"eq.{month}"),
            ("element_kood", "in.(DTAX,DTAN)"),
            (
                "select",
                "jaam_kood,jaam_nimi,aasta,kuu,paev,vaartus,element_kood",
            ),
            ("order", "jaam_kood.asc,aasta.asc,kuu.asc,paev.asc,element_kood.asc"),
            ("limit", "20000"),
        ]
        part = _api_get(DAILY_PATH, params)
        print(f"Recent query {year}-{month:02d}: {len(part):,} rows")
        rows.extend(part)
    return rows


def latest_by_station_element(
    rows: Iterable[dict[str, Any]],
) -> tuple[dict[tuple[str, str], date], dict[str, str], date | None]:
    latest: dict[tuple[str, str], date] = {}
    names: dict[str, str] = {}
    newest: date | None = None

    for row in rows:
        code = str(row.get("jaam_kood") or "").strip()
        element = str(row.get("element_kood") or "").strip()
        d = _row_date(row)
        value = _number(row.get("vaartus"))
        if not code or element not in ELEMENTS or d is None or value is None:
            continue

        name = str(row.get("jaam_nimi") or code).strip()
        names[code] = name
        key = (code, element)
        if key not in latest or d > latest[key]:
            latest[key] = d
        if newest is None or d > newest:
            newest = d

    return latest, names, newest


def first_observation(code: str, element: str, end_year: int, start_year: int) -> dict[str, Any] | None:
    params = [
        ("jaam_kood", f"eq.{code}"),
        ("element_kood", f"eq.{element}"),
        ("aasta", f"gte.{start_year}"),
        ("aasta", f"lte.{end_year}"),
        ("select", "jaam_kood,jaam_nimi,aasta,kuu,paev,vaartus,element_kood"),
        ("order", "aasta.asc,kuu.asc,paev.asc"),
        ("limit", "1"),
    ]
    rows = _api_get(DAILY_PATH, params)
    return rows[0] if rows else None


def _fmt_date(d: date | None) -> str:
    return d.isoformat() if d else "-"


def _fmt_coord(value: Any) -> str:
    n = _number(value)
    return f"{n:.4f}" if n is not None else "-"


def _bucket(span_years: float | None) -> str:
    if span_years is None:
        return "no history"
    if span_years >= 30:
        return ">=30y"
    if span_years >= 20:
        return ">=20y"
    if span_years >= 10:
        return ">=10y"
    return "<10y"


def run_probe(active_lag_days: int, history_start: int, months_back: int) -> int:
    today = date.today()

    print("=== ESTONIA / KESKKONNAAGENTUUR DAILY TMAX/TMIN PROBE ===")
    print(f"API root: {API_ROOT}")
    print("Daily elements: DTAX=Tmax, DTAN=Tmin")
    print(f"Probe date: {today.isoformat()}")
    print()

    metadata, metadata_keys = fetch_station_metadata()
    print(f"Station metadata codes: {len(metadata):,}")
    print("Metadata keys sample: " + ", ".join(metadata_keys))
    print()

    recent_rows = fetch_recent_temperature_rows(today, months_back)
    latest, names, newest = latest_by_station_element(recent_rows)
    if newest is None:
        print("ERROR: No recent DTAX/DTAN values found.", file=sys.stderr)
        return 2

    active_cutoff = date.fromordinal(newest.toordinal() - active_lag_days)
    recent_codes = sorted({code for code, _element in latest})
    both_codes = sorted(
        code
        for code in recent_codes
        if (code, "DTAX") in latest and (code, "DTAN") in latest
    )
    active_codes = sorted(
        code
        for code in both_codes
        if latest[(code, "DTAX")] >= active_cutoff
        and latest[(code, "DTAN")] >= active_cutoff
    )

    print("=== CURRENT COVERAGE ===")
    print(f"Newest daily temperature date in API sample: {newest.isoformat()}")
    print(f"Active cutoff: {active_cutoff.isoformat()} (newest minus {active_lag_days} days)")
    print(f"Stations with recent DTAX or DTAN: {len(recent_codes)}")
    print(f"Stations with both DTAX + DTAN in recent sample: {len(both_codes)}")
    print(f"ACTIVE stations with both DTAX + DTAN: {len(active_codes)}")
    print()

    for code in active_codes:
        meta = metadata.get(code, {})
        name = names.get(code) or str(meta.get("jaam_nimi") or code)
        print(
            f"ACTIVE {code:10s} | {name:24.24s} | "
            f"Tmax {latest[(code, 'DTAX')].isoformat()} | "
            f"Tmin {latest[(code, 'DTAN')].isoformat()} | "
            f"lat {_fmt_coord(meta.get('laiuskraad'))} | "
            f"lon {_fmt_coord(meta.get('pikkuskraad'))}"
        )

    inactive_both = [code for code in both_codes if code not in set(active_codes)]
    if inactive_both:
        print()
        print("Recent-but-not-active DTAX+DTAN stations:")
        for code in inactive_both:
            print(
                f"  {code:10s} | {names.get(code, code):24.24s} | "
                f"Tmax {_fmt_date(latest.get((code, 'DTAX')))} | "
                f"Tmin {_fmt_date(latest.get((code, 'DTAN')))}"
            )

    print()
    print("=== HISTORICAL DEPTH OF ACTIVE DTAX+DTAN STATIONS ===")
    print(f"Public daily API window tested from {history_start} onward.")

    summaries: list[dict[str, Any]] = []
    for index, code in enumerate(active_codes, start=1):
        name = names.get(code) or str(metadata.get(code, {}).get("jaam_nimi") or code)
        first_tmax_row = first_observation(code, "DTAX", today.year, history_start)
        first_tmin_row = first_observation(code, "DTAN", today.year, history_start)
        first_tmax = _row_date(first_tmax_row or {})
        first_tmin = _row_date(first_tmin_row or {})
        start_both = max(d for d in (first_tmax, first_tmin) if d is not None) if (first_tmax and first_tmin) else None
        latest_both = min(latest[(code, "DTAX")], latest[(code, "DTAN")])
        span_years = (
            (latest_both - start_both).days / 365.2425
            if start_both is not None and latest_both >= start_both
            else None
        )
        summaries.append(
            {
                "code": code,
                "name": name,
                "first_tmax": first_tmax,
                "first_tmin": first_tmin,
                "start_both": start_both,
                "latest_both": latest_both,
                "span_years": span_years,
                "bucket": _bucket(span_years),
            }
        )
        span_text = f"{span_years:5.1f} y" if span_years is not None else "   n/a"
        print(
            f"{index:2d}/{len(active_codes):2d} {code:10s} | {name:24.24s} | "
            f"first Tmax {_fmt_date(first_tmax)} | first Tmin {_fmt_date(first_tmin)} | "
            f"both from {_fmt_date(start_both)} | {span_text} | {_bucket(span_years)}"
        )

    bucket_counts: dict[str, int] = defaultdict(int)
    for item in summaries:
        bucket_counts[item["bucket"]] += 1

    at_least_30 = sum(1 for item in summaries if item["span_years"] is not None and item["span_years"] >= 30)
    at_least_20 = sum(1 for item in summaries if item["span_years"] is not None and item["span_years"] >= 20)
    at_least_10 = sum(1 for item in summaries if item["span_years"] is not None and item["span_years"] >= 10)
    from_1991 = sum(1 for item in summaries if item["start_both"] is not None and item["start_both"].year == history_start)

    print()
    print("=== USABLE STATION SUMMARY ===")
    print(f"Active DTAX+DTAN stations:             {len(active_codes)}")
    print(f"With >=30 years overlapping history:   {at_least_30}")
    print(f"With >=20 years overlapping history:   {at_least_20}")
    print(f"With >=10 years overlapping history:   {at_least_10}")
    print(f"Both series already start in {history_start}:      {from_1991}")
    print(
        "Exclusive buckets: "
        + ", ".join(
            f"{label}={bucket_counts.get(label, 0)}"
            for label in (">=30y", ">=20y", ">=10y", "<10y", "no history")
        )
    )

    short = [item for item in summaries if item["span_years"] is None or item["span_years"] < 30]
    if short:
        print()
        print("Stations below 30 years (check predecessor/site continuity before production integration):")
        for item in short:
            span = item["span_years"]
            span_text = f"{span:.1f} y" if span is not None else "n/a"
            print(
                f"  {item['code']:10s} | {item['name']:24.24s} | "
                f"both from {_fmt_date(item['start_both'])} | {span_text}"
            )

    print()
    print("FAZIT FOR NEXT STEP")
    print(
        f"Use {at_least_30} stations immediately if we require >=30 years; "
        f"{at_least_20} stations if >=20 years is acceptable."
    )
    print("No production cache or Europe workflow was modified by this probe.")
    return 0


def self_test() -> int:
    rows = [
        {"jaam_kood": "A", "jaam_nimi": "Alpha", "aasta": 2026, "kuu": 8, "paev": 15, "vaartus": "23.4", "element_kood": "DTAX"},
        {"jaam_kood": "A", "jaam_nimi": "Alpha", "aasta": 2026, "kuu": 8, "paev": 14, "vaartus": "12,3", "element_kood": "DTAN"},
        {"jaam_kood": "A", "jaam_nimi": "Alpha", "aasta": 2026, "kuu": 8, "paev": 15, "vaartus": "13.1", "element_kood": "DTAN"},
        {"jaam_kood": "B", "jaam_nimi": "Beta", "aasta": 2026, "kuu": 8, "paev": 15, "vaartus": None, "element_kood": "DTAX"},
    ]
    latest, names, newest = latest_by_station_element(rows)
    assert newest == date(2026, 8, 15)
    assert latest[("A", "DTAX")] == date(2026, 8, 15)
    assert latest[("A", "DTAN")] == date(2026, 8, 15)
    assert names["A"] == "Alpha"
    assert _bucket(31.0) == ">=30y"
    assert _bucket(25.0) == ">=20y"
    assert _bucket(12.0) == ">=10y"
    assert _bucket(5.0) == "<10y"
    assert _bucket(None) == "no history"
    assert _month_pairs(date(2026, 1, 2), 3) == [(2026, 1), (2025, 12), (2025, 11)]
    print("Self-test OK")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--active-lag-days", type=int, default=7)
    parser.add_argument("--history-start", type=int, default=1991)
    parser.add_argument("--months-back", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    return run_probe(
        active_lag_days=max(0, args.active_lag_days),
        history_start=args.history_start,
        months_back=max(1, args.months_back),
    )


if __name__ == "__main__":
    raise SystemExit(main())
