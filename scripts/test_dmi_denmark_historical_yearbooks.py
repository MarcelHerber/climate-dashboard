#!/usr/bin/env python3
"""
Probe DMI's digitised Meteorological Yearbook daily CSV archive (1867-1983).

Purpose:
- discover station CSV files in STAKKEVIS/daily_data
- focus on old Danish station-number range 20000..32999
- inspect delimiters, headers, date ranges and temperature-like columns
- determine whether direct daily Tmax/Tmin columns can be parsed reliably

No authentication required.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from typing import Any

BASE = "https://download.dmi.dk/public/opendata/STAKKEVIS/daily_data/"
UA = "climate-dashboard-dmi-historical-probe/1.0"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept-Encoding": "identity"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def discover_csvs() -> list[str]:
    html = fetch_bytes(BASE).decode("utf-8", errors="replace")
    hrefs = re.findall(r'href=["\']([^"\']+\.csv)["\']', html, flags=re.I)
    return sorted({urllib.parse.urljoin(BASE, x) for x in hrefs})


def old_station_number(url: str) -> int | None:
    name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    m = re.match(r"^(\d{5})_", name)
    if not m:
        return None
    return int(m.group(1))


def likely_denmark(url: str) -> bool:
    number = old_station_number(url)
    # The DMI yearbook listing currently places Danish historical land
    # stations mainly in the 20xxx-32xxx block; 33xxx+ are Faroe/Greenland,
    # while 04xxx includes Icelandic historical stations.
    return number is not None and 20000 <= number <= 32999


def decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def norm(value: str) -> str:
    value = value.strip().lower()
    value = (
        value.replace("æ", "ae")
        .replace("ø", "oe")
        .replace("å", "aa")
    )
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "na", "null", "-", "--"}:
        return None
    text = text.replace(",", ".")
    try:
        x = float(text)
    except ValueError:
        return None
    if not -100 <= x <= 100:
        return None
    return x


def detect_date(row: dict[str, str], fields: list[str]) -> date | None:
    normalized = {norm(k): v for k, v in row.items()}

    # One-column date formats.
    for key in ("date", "dato", "datum", "day_date"):
        if key in normalized:
            text = str(normalized[key]).strip()
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    from datetime import datetime
                    return datetime.strptime(text, fmt).date()
                except ValueError:
                    pass

    year = None
    month = None
    day = None
    for key, value in normalized.items():
        if key in {"year", "aar", "ar"}:
            try:
                year = int(float(str(value).replace(",", ".")))
            except ValueError:
                pass
        elif key in {"month", "maaned", "maned"}:
            try:
                month = int(float(str(value).replace(",", ".")))
            except ValueError:
                pass
        elif key in {"day", "dag"}:
            try:
                day = int(float(str(value).replace(",", ".")))
            except ValueError:
                pass

    if year and month and day:
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def column_scores(headers: list[str]) -> tuple[list[str], list[str], list[str]]:
    tx, tn, generic = [], [], []
    for h in headers:
        n = norm(h)
        tempish = any(x in n for x in ("temp", "temperatur", "tmax", "tmin"))
        if not tempish:
            continue
        generic.append(h)
        if (
            "tmax" in n
            or "temp_max" in n
            or "max_temp" in n
            or n.endswith("_max")
            or "maximum" in n
            or "maks" in n
        ):
            tx.append(h)
        if (
            "tmin" in n
            or "temp_min" in n
            or "min_temp" in n
            or n.endswith("_min")
            or "minimum" in n
        ):
            tn.append(h)
    return tx, tn, generic


def inspect_csv(url: str) -> dict[str, Any]:
    raw = fetch_bytes(url)
    text = decode_text(raw)
    delimiter = detect_delimiter(text)

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = list(reader.fieldnames or [])
    if not headers:
        return {
            "url": url,
            "bytes": len(raw),
            "delimiter": delimiter,
            "headers": [],
            "rows": 0,
            "first_date": None,
            "last_date": None,
            "tx_candidates": [],
            "tn_candidates": [],
            "temperature_columns": [],
            "candidate_values": {},
        }

    tx, tn, generic = column_scores(headers)
    first = None
    last = None
    row_count = 0
    candidate_values: dict[str, list[float]] = {
        h: [] for h in set(tx + tn + generic)
    }

    for row in reader:
        row_count += 1
        d = detect_date(row, headers)
        if d:
            first = d if first is None or d < first else first
            last = d if last is None or d > last else last

        for h in candidate_values:
            x = parse_float(row.get(h))
            if x is not None and len(candidate_values[h]) < 500:
                candidate_values[h].append(x)

    stats = {}
    for h, vals in candidate_values.items():
        if vals:
            stats[h] = {
                "n_sample": len(vals),
                "min": min(vals),
                "max": max(vals),
                "median": statistics.median(vals),
            }

    return {
        "url": url,
        "bytes": len(raw),
        "delimiter": delimiter,
        "headers": headers,
        "rows": row_count,
        "first_date": first.isoformat() if first else None,
        "last_date": last.isoformat() if last else None,
        "tx_candidates": tx,
        "tn_candidates": tn,
        "temperature_columns": generic,
        "candidate_values": stats,
    }


def run_probe() -> None:
    log("=== DMI DÄNEMARK HISTORICAL YEARBOOK PROBE ===")

    urls = discover_csvs()
    dk = [u for u in urls if likely_denmark(u)]
    log(f"CSV-Dateien insgesamt im DMI-Verzeichnis: {len(urls)}")
    log(f"Davon wahrscheinlich historische dänische Stationen: {len(dk)}")

    if not dk:
        raise RuntimeError("Keine historischen dänischen DMI-CSV-Dateien gefunden.")

    # Pick long/recognisable records spread across Denmark plus first/last.
    preferred_ids = {20000, 21100, 25140, 27080, 30210, 31300, 32030}
    selected = []
    for u in dk:
        if old_station_number(u) in preferred_ids:
            selected.append(u)
    for u in (dk[:2] + dk[-2:]):
        if u not in selected:
            selected.append(u)
    selected = selected[:12]

    direct_both = 0
    formats = Counter()

    for i, url in enumerate(selected, 1):
        info = inspect_csv(url)
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        formats[(info["delimiter"], tuple(info["headers"]))] += 1

        log()
        log(f"[{i}/{len(selected)}] {name}")
        log(
            f"  Größe {info['bytes']/1024/1024:.2f} MB | "
            f"{info['rows']:,} Zeilen | "
            f"Datum {info['first_date']} bis {info['last_date']}"
        )
        log(f"  Trennzeichen: {repr(info['delimiter'])}")
        log("  Spalten:")
        log("    " + " | ".join(info["headers"]))
        log(f"  Tmax-Kandidaten: {info['tx_candidates'] or 'keine'}")
        log(f"  Tmin-Kandidaten: {info['tn_candidates'] or 'keine'}")
        if info["candidate_values"]:
            log("  Temperaturspalten Stichprobe:")
            for col, st in info["candidate_values"].items():
                log(
                    f"    {col}: n={st['n_sample']}, "
                    f"min={st['min']}, max={st['max']}, median={st['median']}"
                )

        if info["tx_candidates"] and info["tn_candidates"]:
            direct_both += 1

    log()
    log("=== DMI HISTORICAL PROBE SUMMARY ===")
    log(f"Geprüfte historische DK-Dateien: {len(selected)}")
    log(f"Dateien mit direktem Tmax- UND Tmin-Kandidaten: {direct_both}")
    log(f"Unterschiedliche Header-/Delimiter-Formate: {len(formats)}")

    if direct_both == 0:
        log(
            "ERGEBNIS: Keine eindeutig benannten direkten Tmax/Tmin-Spalten erkannt. "
            "Dann muss die alte Jahrbuchlogik anhand der ausgegebenen Spalten "
            "gezielt interpretiert werden."
        )
    else:
        log(
            "ERGEBNIS: Direkte Tmax/Tmin-Spalten wurden erkannt. "
            "Eine automatische 1867–1983-Baseline ist grundsätzlich möglich."
        )

    log("DMI Denmark Historical Probe OK.")


def self_test() -> None:
    headers = ["Year", "Month", "Day", "Temperature max", "Temperature min"]
    tx, tn, generic = column_scores(headers)
    assert "Temperature max" in tx
    assert "Temperature min" in tn
    assert len(generic) == 2

    row = {
        "Year": "1901",
        "Month": "7",
        "Day": "14",
        "Temperature max": "24,5",
        "Temperature min": "11,2",
    }
    assert detect_date(row, headers) == date(1901, 7, 14)
    assert parse_float("24,5") == 24.5
    print("DMI Denmark historical probe self-test OK")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
    else:
        run_probe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
