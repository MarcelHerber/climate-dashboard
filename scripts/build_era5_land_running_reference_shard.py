#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import importlib.util
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNING_PATH = ROOT / "scripts" / "update_era5_land_europe_running.py"
CACHE_DIR = ROOT / ".era5_running_cache_0p1"
REFERENCE_START = 1991
REFERENCE_END = 2020


def load_running():
    spec = importlib.util.spec_from_file_location("era5_running_reference_core", RUNNING_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Running-Modul konnte nicht geladen werden: {RUNNING_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.GRID = [0.1, 0.1]
    module.CACHE_DIR = CACHE_DIR
    return module


def write_output(name: str, value: str, path: str | None) -> None:
    if not path:
        print(f"{name}={value}")
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def probe(running, today: date, github_output: str | None) -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    client = running.cds_client()
    data_through = running.probe_available_day(client, today, force=False)
    month_days = calendar.monthrange(data_through.year, data_through.month)[1]
    write_output("data_through", data_through.isoformat(), github_output)
    write_output("year", str(data_through.year), github_output)
    write_output("month", f"{data_through.month:02d}", github_output)
    write_output("month_days", str(month_days), github_output)
    write_output("month_key", f"{data_through.year}-{data_through.month:02d}", github_output)
    print(f"ERA5-Land-T Datenstand: {data_through}; Referenzmonat: {data_through.month:02d}")
    return 0


def build(running, variable: str, month: int, start_year: int, end_year: int) -> int:
    if start_year < REFERENCE_START or end_year > REFERENCE_END or start_year > end_year:
        raise ValueError(f"Ungültiger Referenzbereich: {start_year}–{end_year}")
    if not 1 <= month <= 12:
        raise ValueError(f"Ungültiger Monat: {month}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    client = running.cds_client()
    years = list(range(start_year, end_year + 1))
    month_days = calendar.monthrange(REFERENCE_END, month)[1]

    if variable == "temperature":
        prefix = CACHE_DIR / f"reference_temp_{REFERENCE_START}_{REFERENCE_END}_{month:02d}_full.nc"
        files = running.request_daily_temperature_period(
            client,
            years,
            month,
            list(range(1, month_days + 1)),
            prefix,
            f"Temperatur-Referenz {running.MONTH_NAMES[month]} {start_year}–{end_year}",
        )
    elif variable == "precipitation":
        prefix = CACHE_DIR / f"reference_precip_{REFERENCE_START}_{REFERENCE_END}_{month:02d}_full.nc"
        files = running.request_precip_period(
            client,
            years,
            month,
            month_days,
            prefix,
            f"Niederschlags-Referenz {running.MONTH_NAMES[month]} {start_year}–{end_year}",
        )
    else:
        raise ValueError(variable)

    missing = [str(path) for path in files if not path.exists() or path.stat().st_size == 0]
    if missing:
        raise RuntimeError("Referenzdateien fehlen nach Download: " + ", ".join(missing[:5]))
    total_mb = sum(path.stat().st_size for path in files) / 1024 / 1024
    print(
        f"Referenz-Shard fertig: {variable} · {start_year}–{end_year} · "
        f"{len(files)} Dateien · {total_mb:.1f} MiB"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--today")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    parser.add_argument("--variable", choices=["temperature", "precipitation"])
    parser.add_argument("--month", type=int)
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    args = parser.parse_args()

    running = load_running()
    if args.probe:
        today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
        return probe(running, today, args.github_output)

    required = (args.variable, args.month, args.start_year, args.end_year)
    if any(value is None for value in required):
        parser.error("Für einen Build sind --variable, --month, --start-year und --end-year erforderlich.")
    return build(running, args.variable, args.month, args.start_year, args.end_year)


if __name__ == "__main__":
    raise SystemExit(main())
