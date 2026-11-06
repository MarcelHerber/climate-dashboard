#!/usr/bin/env python3
"""DMI 80°N temperature index -> reproducible, observation/analysis-only daily JSON.

DMI is an *index* of model analyses on a regular lat/lon grid, not a physically
area-weighted Arctic temperature. The source combines ERA-40 and operational
ECMWF analyses; no forecasts, synthetic gap-filling or live browser scraping.
"""
from __future__ import annotations

import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import tarfile
import time
import urllib.error
import urllib.request

BASE = "https://download.dmi.dk/pub/plus80N_temperatureindex/"
ARCHIVE = "plus80n_temperatureindex_1958_2019.tar"
HISTORY_START = 1958
REFERENCE_END = 2002
PLOT_YEAR = 2024  # leap-year skeleton: 366 slots, day-by-calendar-date alignment
UA = "ClimateDashboard/1.0 (https://github.com/MarcelHerber/climate-dashboard)"
DATE_RE = re.compile(r"^\d{8}$")
YEAR_FILE = re.compile(r"(?:meanT|temp_clim_plus80_)(\d{4})", re.I)


def fetch(name: str, attempts: int = 3) -> bytes:
    url = BASE + name
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = response.read(6_000_000)
                if not payload or len(payload) >= 6_000_000:
                    raise ValueError(f"Bad size for {name}: {len(payload)}")
                return payload
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"DMI file unavailable: {url} ({error})")


def calendar_days() -> list[str]:
    return [(date(PLOT_YEAR, 1, 1) + timedelta(days=i)).strftime("%m-%d") for i in range(366)]


DAYS = calendar_days()


def _date(token: str, year: int) -> date | None:
    try:
        if DATE_RE.fullmatch(token):
            value = datetime.strptime(token, "%Y%m%d").date()
        elif re.fullmatch(r"\d{4}-\d\d-\d\d", token):
            value = date.fromisoformat(token)
        else:
            return None
        return value if value.year == year else None
    except ValueError:
        return None


def parse_daily(text: str, year: int) -> dict[str, float]:
    """Parse canonical 'Date Day_of_year Temp[K]' and its archived 4-col form.

    The DMI historical fourth column is the *reference* curve; the actual
    year's air temperature is column THREE. Do not confuse the two.
    """
    found: dict[str, float] = {}
    for line in text.splitlines():
        words = line.strip().split()
        if not words or words[0].startswith(("#", "!")):
            continue
        stamp = _date(words[0], year)
        val_token = None
        if stamp and len(words) >= 3:
            # Known DMI layout: Date (YYYYMMDD), day of year, Temp [K].
            if words[1].isdigit() and int(words[1]) != stamp.timetuple().tm_yday:
                continue
            val_token = words[2]
        elif len(words) >= 3 and words[0].isdigit():
            # Legacy member fallback: day-of-year, temperature[K], climate[K].
            doy = int(words[0])
            if 1 <= doy <= (366 if calendar.isleap(year) else 365):
                stamp = date(year, 1, 1) + timedelta(days=doy - 1)
                val_token = words[1]
        if stamp is None or val_token is None:
            continue
        try:
            kelvin = float(val_token)
        except ValueError:
            continue
        if 195.0 <= kelvin <= 285.0:
            key = stamp.strftime("%m-%d")
            celsius = round(kelvin - 273.15, 3)
            if key in found and abs(found[key] - celsius) > 0.05:
                raise ValueError(f"Conflicting readings for {year}-{key}")
            found[key] = celsius
    return found


def archive_years(blob: bytes) -> dict[int, dict[str, float]]:
    choices: dict[int, tuple[int, dict[str, float]]] = {}
    candidates: list[tuple[str, int]] = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tar:
        for entry in tar:
            if not entry.isfile() or entry.size > 200_000:
                continue
            year_match = YEAR_FILE.search(Path(entry.name).name)
            if not year_match:
                continue
            year = int(year_match.group(1))
            if not HISTORY_START <= year <= 2019:
                continue
            raw = tar.extractfile(entry)
            if raw is None:
                continue
            body = raw.read().decode("utf-8", "replace")
            values = parse_daily(body, year)
            if year in (1958, 2017) and len(values) < 10:
                print("DMI legacy sample", entry.name, repr(body.splitlines()[:9]), flush=True)
            candidates.append((entry.name, len(values)))
            if len(values) < 150:
                continue
            # Prefer canonical yearly running file over archival mixed format.
            score = (2 if "meant" in entry.name.lower() else 1) * 1000 + len(values)
            if year not in choices or score > choices[year][0]:
                choices[year] = (score, values)
    years = {year: values for year, (_, values) in choices.items()}
    print("DMI archive members (sample):", candidates[:12], flush=True)
    print("Historical years:", len(years), min(years, default="-"), max(years, default="-"), flush=True)
    if len(years) < 40 or any(y not in years for y in (1958, 1980, 2002)):
        raise RuntimeError("DMI tar not parsed sufficiently: verify file layout before publishing")
    return years


def reference_series(years: dict[int, dict[str, float]]) -> tuple[list[float | None], list[int]]:
    means, counts = [], []
    for key in DAYS:
        samples = [years[y][key] for y in range(HISTORY_START, REFERENCE_END + 1)
                   if y in years and key in years[y]]
        counts.append(len(samples))
        threshold = 7 if key == "02-29" else 35
        means.append(round(sum(samples) / len(samples), 3) if len(samples) >= threshold else None)
    if sum(v is not None for v in means) < 365:
        raise RuntimeError("Insufficient daily DMI reference 1958-2002")
    return means, counts


def build(archive_blob: bytes, running: dict[int, bytes], now: date | None = None) -> dict:
    today = now or datetime.now(timezone.utc).date()
    years = archive_years(archive_blob)
    for year, raw in running.items():
        parsed = parse_daily(raw.decode("utf-8", "replace"), year)
        if len(parsed) < 3 and year == today.year:
            raise RuntimeError(f"Current DMI year {year} contains no valid daily readings")
        if len(parsed) > 0:
            # Never let 2019 duplicate partial archive take priority.
            years[year] = parsed
    reference, counts = reference_series(years)
    newest_year = max(years)
    valid_dates = [f"{year:04d}-{day}" for year, values in years.items()
                   for day in values if date.fromisoformat(f"{year}-{day}") <= today]
    if not valid_dates:
        raise RuntimeError("DMI data contain no legitimate dates")
    cutoff = max(valid_dates)
    plotted_years = {}
    for year, values in sorted(years.items()):
        cells = [values.get(day) if date.fromisoformat(f"{year}-{day}") <= today else None for day in DAYS
                 if day != "02-29" or calendar.isleap(year)]
        # Keep all arrays aligned on the exact same month/day, including Feb 29.
        aligned = [
            round(values[k], 3) if k in values and (date.fromisoformat(f"{year}-{k}") <= today) else None
            if k != "02-29" or calendar.isleap(year) else None
            for k in DAYS
        ]
        if sum(v is not None for v in aligned) >= 150 or year == today.year:
            plotted_years[str(year)] = aligned
    if len(plotted_years) < 40:
        raise RuntimeError("Fewer than 40 historical years; not publishing corrupted index")
    return {
        "schema": 1,
        "product": "DMI +80N temperature index",
        "region": "North of 80°N",
        "unit": "°C",
        "days": DAYS,
        "reference": {
            "label": "DMI/ERA-40 1958–2002",
            "start_year": HISTORY_START,
            "end_year": REFERENCE_END,
            "temperatures": reference,
            "counts": counts,
        },
        "years": plotted_years,
        "last_date": cutoff,
        "latest_year": newest_year,
        "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "download": BASE,
            "running": f"{BASE}meanT{today.year}_running.txt",
            "archive": BASE + ARCHIVE,
            "documentation": "https://ocean.dmi.dk/arctic/meant80n.uk.php",
            "explanation": "https://ocean.dmi.dk/arctic/documentation/arctic_mean_temp_data_explanation_newest.pdf",
        },
        "note": ("DMI index from analysis fields on an unweighted geographic grid. "
                 "Not a true area-weighted Arctic mean. ERA-40 through 2002, "
                 "operational ECMWF analyses thereafter; model changes affect comparability."),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/arctic80_temperature.json")
    args = parser.parse_args()
    today = datetime.now(timezone.utc).date()
    archive_blob = fetch(ARCHIVE)
    # Include yearly DMI running files from 2019 onward, overriding the
    # archive's 2019 version, while avoiding refetching the entire history daily.
    years = list(range(2019, today.year + 1))
    annual = {year: fetch(f"meanT{year}_running.txt") for year in years}
    result = build(archive_blob, annual, today)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    tmp.replace(output)
    print(f"DMI index: {len(result['years'])} yearly curves, last date {result['last_date']}, "
          f"reference values {sum(x is not None for x in result['reference']['temperatures'])}", flush=True)


if __name__ == "__main__":
    main()
