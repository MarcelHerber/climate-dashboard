#!/usr/bin/env python3
"""Fetch authoritative NOAA/CPC NAO, AO, ONI and RONI indices for GitHub Pages.

NAO/AO monthly series are arithmetic monthly means of daily CPC observations.
ONI and RONI are CPC's official 3-month overlapping seasons; no interpolation.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "climate_indices" / "index.json"
SOURCES = {
    "ao": "https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.ao.cdas.z1000.19500101_current.csv",
    "nao": "https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.nao.cdas.z500.19500101_current.csv",
    "oni": "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
    "roni": "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt",
}
SEASONS = ("DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ")
MISSING = {"", "-99", "-99.00", "-999", "-999.0", "-999.00", "-9999", "nan", "NaN", "null"}


def download(url: str, attempts: int = 3) -> str:
    for attempt in range(attempts):
        try:
            req = Request(url, headers={"User-Agent": "climate-dashboard/NOAA-indices/1.0", "Accept": "text/plain,text/csv,*/*"})
            with urlopen(req, timeout=75) as response:
                return response.read().decode("utf-8-sig", errors="replace")
        except (OSError, URLError) as exc:
            if attempt + 1 == attempts:
                raise RuntimeError(f"NOAA-Abruf fehlgeschlagen ({url}): {exc}") from exc
            time.sleep(3 * (attempt + 1))
    raise AssertionError("unreachable")


def number(value: str) -> float | None:
    raw = str(value).strip()
    if raw in MISSING:
        return None
    try:
        result = float(raw)
    except ValueError:
        return None
    return result if math.isfinite(result) and abs(result) <= 15.0 else None


def parse_daily_csv(text: str, index_name: str) -> list[list[str | float]]:
    """Handle YYYY-MM-DD,value and YEAR,MONTH,DAY,index CPC CSV variants."""
    rows = list(csv.reader(io.StringIO(text)))
    output: dict[str, float] = {}
    previous = ""
    for cells in rows:
        cells = [x.strip() for x in cells]
        if not cells or cells[0].startswith(("#", "!")):
            continue
        daily: date | None = None
        start_col = 0
        if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{2}:\d{2}:\d{2})?", cells[0]):
            iso = re.split(r"\s", cells[0])[0].replace("/", "-")
            try:
                daily = date.fromisoformat(iso)
                start_col = 1
            except ValueError:
                pass
        elif len(cells) >= 4 and re.fullmatch(r"(?:19|20)\d{2}", cells[0]):
            try:
                daily = date(int(cells[0]), int(float(cells[1])), int(float(cells[2])))
                start_col = 3
            except (ValueError, OverflowError):
                pass
        elif len(cells) >= 2 and re.fullmatch(r"\d{8}", cells[0]):
            try:
                daily = datetime.strptime(cells[0], "%Y%m%d").date()
                start_col = 1
            except ValueError:
                pass
        if daily is None or not 1950 <= daily.year <= date.today().year + 1:
            continue
        # In CPC's daily index CSV the index is the numeric column immediately
        # following the calendar date; additional columns may be quality metadata.
        values = [number(raw) for raw in cells[start_col:]]
        val = next((v for v in values if v is not None), None)
        if val is None:
            continue
        iso = daily.isoformat()
        if previous and iso < previous:
            # The source may be ordered differently; output is always sorted.
            pass
        previous = iso
        output[iso] = round(val, 3)
    result = [[key, value] for key, value in sorted(output.items())]
    if len(result) < 25000 or result[0][0] > "1952-01-01":
        raise RuntimeError(f"{index_name}: NOAA-Tagesdaten unvollständig oder nicht erkannt ({len(result)} Zeilen)")
    if date.fromisoformat(result[-1][0]) < date.today() - timedelta(days=45):
        raise RuntimeError(f"{index_name}: NOAA-Tagesdaten veraltet bis {result[-1][0]}")
    return result


def monthly_means(daily: list[list[str | float]]) -> list[list[str | float | int]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for day, value in daily:
        groups[str(day)[:7]].append(float(value))
    result = []
    for month, vals in sorted(groups.items()):
        y, m = map(int, month.split("-"))
        start = date(y, m, 1)
        stop = date(y + (m == 12), m % 12 + 1, 1)
        ndays = (stop-start).days
        # Only full/near-full months. Current month remains in daily view.
        if len(vals) >= math.ceil(ndays * .9):
            result.append([month, round(mean(vals), 3), len(vals)])
    return result


def parse_enso_seasons(text: str, name: str) -> list[list[str | float]]:
    result: dict[str, tuple[str, float]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[0] not in SEASONS or not re.fullmatch(r"(?:19|20)\d{2}", parts[1]):
            continue
        yr = int(parts[1])
        # CPC RONI: SEAS YR ANOM; CPC ONI: SEAS YR TOTAL ANOM.
        # The anomaly is always the final field, never the raw SST total.
        val = number(parts[-1])
        if val is None:
            continue
        # DJF is centered on January of label-year, NDJ on December.
        month = SEASONS.index(parts[0]) + 1
        key = f"{yr:04d}-{month:02d}"
        result[key] = (parts[0], round(val, 2))
    rows = [[key, seas, val] for key, (seas, val) in sorted(result.items())]
    if len(rows) < 880 or rows[0][0] > "1952-01":
        raise RuntimeError(f"{name}: Unzureichende CPC-Daten ({len(rows)} Jahreszeiten)")
    if rows[-1][0] < f"{date.today().year - 1}-04":
        raise RuntimeError(f"{name}: CPC-Daten sind veraltet bis {rows[-1][0]}")
    return rows


def construct(fetch=download) -> dict:
    ao = parse_daily_csv(fetch(SOURCES["ao"]), "AO")
    nao = parse_daily_csv(fetch(SOURCES["nao"]), "NAO")
    oni = parse_enso_seasons(fetch(SOURCES["oni"]), "ONI")
    roni = parse_enso_seasons(fetch(SOURCES["roni"]), "RONI")
    from update_climate_indices_extra import load_all
    extra = load_all(fetch)
    return {
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publisher": "NOAA Climate Prediction Center (CPC)",
        "source_urls": SOURCES,
        "method": {
            "nao_ao": "CPC daily standardized observed indices; monthly values are arithmetic means of the observed daily index (>=90% coverage).",
            "enso": "CPC ERSSTv6 3-month overlapping seasons; ONI absolute SST anomaly, RONI relative anomaly; official ENSO monitoring uses RONI from 2026.",
            "episodes": "Warm/cold ±0.5 degC for at least five consecutive overlapping 3-month seasons; short threshold crossings are not confirmed episodes.",
        },
        "teleconnections": {
            "nao": {"label": "Nordatlantische Oszillation", "daily": nao, "monthly": monthly_means(nao), "latest_date": nao[-1][0]},
            "ao": {"label": "Arktische Oszillation", "daily": ao, "monthly": monthly_means(ao), "latest_date": ao[-1][0]},
        },
        "enso": {
            "oni": {"label": "Oceanic Niño Index · ERSSTv6", "seasons": oni, "latest_season": oni[-1][0]},
            "roni": {"label": "Relative Oceanic Niño Index · ERSSTv6", "seasons": roni, "latest_season": roni[-1][0]},
        },
        **extra,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = construct()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(args.output)
    print("CPC Indexdaten:", {
        key: (obj["daily"][-1][0], len(obj["daily"])) for key, obj in payload["teleconnections"].items()
    }, "ENSO:", {
        key: (obj["latest_season"], len(obj["seasons"])) for key, obj in payload["enso"].items()
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
