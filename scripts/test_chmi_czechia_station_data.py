#!/usr/bin/env python3
"""
ČHMÚ / CHMI Czechia station-data probe for climate-dashboard.

Official sources
----------------
Historical daily temperature CSV:
  https://opendata.chmi.cz/meteorology/climate/historical_csv/data/daily/temperature/

Historical station metadata:
  https://opendata.chmi.cz/meteorology/climate/historical/metadata/meta1.json

Recent/current daily station JSON:
  https://opendata.chmi.cz/meteorology/climate/recent/data/daily/

Parameters used:
  TMA = daily maximum air temperature
  TMI = daily minimum air temperature

The probe:
- discovers all historical TMA/TMI station files
- pairs stations having both TMAX and TMIN
- reads official station metadata and filters to Czechia by coordinates
- reports earliest metadata start and active metadata stations
- downloads one historical TMA/TMI pair and inspects its real CSV schema/range
- discovers the latest current YYYYMM batch
- downloads current station JSONs in parallel
- counts stations with actual TMA/TMI, date range, FLAG and QUALITY values
- prints a concise summary suitable for deciding the production builder

No API key or secret is required.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

HIST_TEMP_INDEX = (
    "https://opendata.chmi.cz/meteorology/climate/"
    "historical_csv/data/daily/temperature/"
)
META1_URL = (
    "https://opendata.chmi.cz/meteorology/climate/"
    "historical/metadata/meta1.json"
)
RECENT_DAILY_INDEX = (
    "https://opendata.chmi.cz/meteorology/climate/recent/data/daily/"
)

UA = "climate-dashboard-chmi-czechia-probe/1.0"
TIMEOUT = 120
TRIES = 5

# generous Czechia bbox; enough to remove obvious foreign/test entries
CZ_LON_MIN = 12.0
CZ_LON_MAX = 19.0
CZ_LAT_MIN = 48.4
CZ_LAT_MAX = 51.2


def log(msg: str = "") -> None:
    print(msg, flush=True)


def http_bytes(url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(1, TRIES + 1):
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
                raw = response.read()
                if not raw:
                    raise RuntimeError("Leere HTTP-Antwort")
                return raw
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            RuntimeError,
        ) as exc:
            last = exc
            retryable = (
                not isinstance(exc, urllib.error.HTTPError)
                or exc.code in {408, 429, 500, 502, 503, 504}
            )
            if attempt >= TRIES or not retryable:
                raise
            wait = min(30, attempt * 3)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)
    raise RuntimeError(str(last))


def decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def hrefs(html: str) -> list[str]:
    return re.findall(
        r'href=["\']([^"\']+)["\']',
        html,
        flags=re.I,
    )


def historical_temperature_inventory() -> dict[str, Any]:
    text = decode(http_bytes(HIST_TEMP_INDEX))
    links = [urllib.parse.unquote(x) for x in hrefs(text)]

    tma: dict[str, str] = {}
    tmi: dict[str, str] = {}

    for href in links:
        name = href.rsplit("/", 1)[-1]

        m = re.fullmatch(r"dly-(.+)-TMA\.csv", name, flags=re.I)
        if m:
            station = m.group(1)
            tma[station] = urllib.parse.urljoin(HIST_TEMP_INDEX, href)
            continue

        m = re.fullmatch(r"dly-(.+)-TMI\.csv", name, flags=re.I)
        if m:
            station = m.group(1)
            tmi[station] = urllib.parse.urljoin(HIST_TEMP_INDEX, href)

    paired = sorted(set(tma) & set(tmi))

    return {
        "tma": tma,
        "tmi": tmi,
        "paired": paired,
        "html_bytes": len(text.encode("utf-8")),
    }


def parse_data_collection(obj: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    node = obj.get("data", {})
    if isinstance(node, dict):
        node = node.get("data", node)

    if not isinstance(node, dict):
        raise RuntimeError("CHMI DataCollection: data.data fehlt.")

    header = node.get("header")
    values = node.get("values")

    if isinstance(header, str):
        columns = [x.strip() for x in header.split(",")]
    elif isinstance(header, list):
        columns = [str(x).strip() for x in header]
    else:
        raise RuntimeError("CHMI DataCollection: header unbekannt.")

    if not isinstance(values, list):
        raise RuntimeError("CHMI DataCollection: values fehlt.")

    return columns, values


def load_metadata() -> dict[str, Any]:
    obj = json.loads(decode(http_bytes(META1_URL)))
    columns, rows = parse_data_collection(obj)

    idx = {name: i for i, name in enumerate(columns)}
    required = (
        "WSI", "BEGIN_DATE", "END_DATE", "FULL_NAME",
        "GEOGR1", "GEOGR2", "ELEVATION",
    )
    missing = [x for x in required if x not in idx]
    if missing:
        raise RuntimeError(f"meta1: Spalten fehlen: {missing}")

    by_wsi: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        try:
            wsi = str(row[idx["WSI"]])
            lon = float(row[idx["GEOGR1"]])
            lat = float(row[idx["GEOGR2"]])
        except (ValueError, TypeError, IndexError):
            continue

        if not (
            CZ_LON_MIN <= lon <= CZ_LON_MAX
            and CZ_LAT_MIN <= lat <= CZ_LAT_MAX
        ):
            continue

        rec = {
            "wsi": wsi,
            "begin": str(row[idx["BEGIN_DATE"]]),
            "end": str(row[idx["END_DATE"]]),
            "name": str(row[idx["FULL_NAME"]]),
            "lon": lon,
            "lat": lat,
            "elevation": row[idx["ELEVATION"]],
        }
        by_wsi[wsi].append(rec)

    for records in by_wsi.values():
        records.sort(key=lambda x: x["begin"])

    latest = {}
    for wsi, records in by_wsi.items():
        latest[wsi] = max(records, key=lambda x: x["begin"])

    earliest_begin = None
    earliest_record = None
    for records in by_wsi.values():
        for rec in records:
            begin = rec["begin"]
            if earliest_begin is None or begin < earliest_begin:
                earliest_begin = begin
                earliest_record = rec

    active_metadata = {
        wsi: rec
        for wsi, rec in latest.items()
        if rec["end"].startswith("3999-")
    }

    return {
        "columns": columns,
        "row_count": len(rows),
        "by_wsi": by_wsi,
        "latest": latest,
        "active": active_metadata,
        "earliest": earliest_record,
    }


def parse_csv_probe(raw: bytes) -> dict[str, Any]:
    text = decode(raw)
    lines = [line for line in text.splitlines() if line.strip()]

    # Try real CSV parsing with common delimiters.
    delimiter = ","
    if lines:
        candidates = {
            ",": lines[0].count(","),
            ";": lines[0].count(";"),
            "\t": lines[0].count("\t"),
        }
        delimiter = max(candidates, key=candidates.get)

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if row]

    date_candidates = []
    values = []

    for row in rows[1:]:
        for cell in row:
            cell = str(cell).strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}", cell):
                date_candidates.append(cell[:10])
            try:
                val = float(cell.replace(",", "."))
                values.append(val)
            except ValueError:
                pass

    return {
        "bytes": len(raw),
        "line_count": len(lines),
        "delimiter": repr(delimiter),
        "header": rows[0] if rows else [],
        "first_lines": lines[:8],
        "last_lines": lines[-8:],
        "first_date": min(date_candidates) if date_candidates else None,
        "last_date": max(date_candidates) if date_candidates else None,
    }


def choose_historical_sample(
    paired: list[str],
    metadata: dict[str, Any],
) -> str:
    candidates = []

    for station in paired:
        wsi = station
        records = metadata["by_wsi"].get(wsi)
        if not records:
            continue
        begin = min(x["begin"] for x in records)
        candidates.append((begin, station))

    if not candidates:
        raise RuntimeError("Keine gepaarte TMA/TMI-Station mit CZ-Metadaten.")

    candidates.sort()
    return candidates[0][1]


def current_inventory() -> dict[str, Any]:
    text = decode(http_bytes(RECENT_DAILY_INDEX))
    links = [urllib.parse.unquote(x) for x in hrefs(text)]

    pattern = re.compile(
        r"dly-(.+)-(\d{6})\.json$",
        flags=re.I,
    )

    batches: dict[str, dict[str, str]] = defaultdict(dict)

    for href in links:
        name = href.rsplit("/", 1)[-1]
        m = pattern.fullmatch(name)
        if not m:
            continue
        station, yyyymm = m.groups()
        batches[yyyymm][station] = urllib.parse.urljoin(
            RECENT_DAILY_INDEX,
            href,
        )

    if not batches:
        raise RuntimeError("Keine aktuellen CHMI Daily-Dateien gefunden.")

    latest_month = max(batches)
    return {
        "latest_month": latest_month,
        "files": batches[latest_month],
        "all_months": sorted(batches),
    }


def parse_current_station(
    station: str,
    url: str,
) -> dict[str, Any]:
    obj = json.loads(decode(http_bytes(url)))
    columns, rows = parse_data_collection(obj)
    idx = {name: i for i, name in enumerate(columns)}

    required = ("STATION", "ELEMENT", "DT", "VAL", "FLAG", "QUALITY")
    missing = [x for x in required if x not in idx]
    if missing:
        raise RuntimeError(f"{station}: aktuelle Spalten fehlen: {missing}")

    records = []
    for row in rows:
        try:
            element = str(row[idx["ELEMENT"]])
        except IndexError:
            continue
        if element not in {"TMA", "TMI"}:
            continue

        dt = str(row[idx["DT"]])
        val = row[idx["VAL"]]
        flag = str(row[idx["FLAG"]])
        quality = row[idx["QUALITY"]]

        records.append(
            {
                "element": element,
                "date": dt[:10],
                "value": val,
                "flag": flag,
                "quality": quality,
            }
        )

    return {
        "station": station,
        "records": records,
        "columns": columns,
    }


def probe_current(
    urls: dict[str, str],
    allowed_stations: set[str],
    workers: int,
) -> dict[str, Any]:
    selected = {
        station: url
        for station, url in urls.items()
        if station in allowed_stations
    }

    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(parse_current_station, station, url): station
            for station, url in selected.items()
        }

        done = 0
        total = len(future_map)

        for future in as_completed(future_map):
            station = future_map[future]
            done += 1
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append((station, str(exc)))

            if done % 50 == 0 or done == total:
                log(
                    f"Current: {done}/{total} Dateien geprüft | "
                    f"Fehler {len(errors)}"
                )

    station_elements: dict[str, set[str]] = defaultdict(set)
    dates = []
    values = {"TMA": [], "TMI": []}
    qualities = {"TMA": Counter(), "TMI": Counter()}
    flags = {"TMA": Counter(), "TMI": Counter()}
    row_count = 0

    for result in results:
        station = result["station"]
        for rec in result["records"]:
            element = rec["element"]
            station_elements[station].add(element)
            dates.append(rec["date"])
            row_count += 1

            try:
                values[element].append(float(rec["value"]))
            except (TypeError, ValueError):
                pass

            qualities[element][str(rec["quality"])] += 1
            flags[element][rec["flag"] or "(leer)"] += 1

    both = sorted(
        station
        for station, elements in station_elements.items()
        if {"TMA", "TMI"} <= elements
    )

    return {
        "file_count": len(selected),
        "parsed_files": len(results),
        "errors": errors,
        "row_count": row_count,
        "both": both,
        "station_elements": station_elements,
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
        "values": values,
        "qualities": qualities,
        "flags": flags,
    }


def self_test() -> None:
    sample = {
        "data": {
            "data": {
                "header": "STATION,ELEMENT,VTYPE,DT,VAL,FLAG,QUALITY",
                "values": [
                    ["0-203-0-x", "TMA", "20:00", "2026-08-01T20:00:00Z", 30.1, "", 0.0],
                    ["0-203-0-x", "TMI", "20:00", "2026-08-01T20:00:00Z", 15.2, "", 0.0],
                ],
            }
        }
    }
    columns, rows = parse_data_collection(sample)
    assert columns[0] == "STATION"
    assert columns[1] == "ELEMENT"
    assert len(rows) == 2

    html = """
    <a href="dly-0-203-0-ABC-TMA.csv">x</a>
    <a href="dly-0-203-0-ABC-TMI.csv">x</a>
    """
    links = hrefs(html)
    assert len(links) == 2

    print("CHMI Czechia probe self-test OK")


def probe(workers: int) -> None:
    log("=== ČHMÚ / CHMI CZECHIA STATION DATA PROBE ===")
    log("Quelle: offizielle CHMI Open Data.")
    log("TMAX = TMA | TMIN = TMI")
    log("Keine API-Keys/Secrets erforderlich.")

    log()
    log("=== HISTORISCHES TMA/TMI-INVENTAR ===")
    hist = historical_temperature_inventory()
    log(f"TMA-Dateien: {len(hist['tma']):,}")
    log(f"TMI-Dateien: {len(hist['tmi']):,}")
    log(f"Stationen mit TMA + TMI: {len(hist['paired']):,}")

    log()
    log("=== STATIONSMETADATEN ===")
    metadata = load_metadata()
    log(f"meta1 Zeilen insgesamt: {metadata['row_count']:,}")
    log(f"Stationen innerhalb CZ-BBox: {len(metadata['by_wsi']):,}")
    log(f"Davon Metadaten aktuell/offen: {len(metadata['active']):,}")

    if metadata["earliest"]:
        rec = metadata["earliest"]
        log(
            "Frühester Metadatenbeginn: "
            f"{rec['begin'][:10]} | {rec['name']} | {rec['wsi']}"
        )

    paired_cz = sorted(
        set(hist["paired"]) & set(metadata["by_wsi"])
    )
    log(f"TMA+TMI mit CZ-Metadaten: {len(paired_cz):,}")

    if not paired_cz:
        raise RuntimeError("Keine tschechischen TMA/TMI-Paare erkannt.")

    sample_station = choose_historical_sample(
        paired_cz,
        metadata,
    )
    latest_meta = metadata["latest"][sample_station]

    log()
    log("=== HISTORISCHER CSV-SAMPLE ===")
    log(
        f"Sample: {latest_meta['name']} | {sample_station} | "
        f"{latest_meta['lat']:.5f}, {latest_meta['lon']:.5f}"
    )

    tma_probe = parse_csv_probe(
        http_bytes(hist["tma"][sample_station])
    )
    tmi_probe = parse_csv_probe(
        http_bytes(hist["tmi"][sample_station])
    )

    for label, info in (("TMA", tma_probe), ("TMI", tmi_probe)):
        log(
            f"{label}: {info['bytes'] / 1024 / 1024:.2f} MB | "
            f"{info['line_count']:,} Zeilen | "
            f"{info['first_date']} bis {info['last_date']} | "
            f"Delimiter {info['delimiter']}"
        )
        log(f"{label} Header: {info['header']}")
        log(f"{label} erste Zeilen:")
        for line in info["first_lines"][:5]:
            log(f"  {line}")
        log(f"{label} letzte Zeilen:")
        for line in info["last_lines"][-5:]:
            log(f"  {line}")

    log()
    log("=== CURRENT / RECENT DAILY ===")
    current = current_inventory()
    log(
        f"Neuester YYYYMM-Batch: {current['latest_month']} | "
        f"{len(current['files']):,} Stationsdateien"
    )
    log(
        "Gefundene Monate am Root: "
        + ", ".join(current["all_months"][-8:])
    )

    current_result = probe_current(
        current["files"],
        set(paired_cz),
        workers,
    )

    log()
    log("=== CURRENT TMA/TMI SUMMARY ===")
    log(
        f"Passende Stationsdateien: {current_result['file_count']:,}"
    )
    log(
        f"Erfolgreich geparst: {current_result['parsed_files']:,}"
    )
    log(
        f"Stationen mit tatsächlichem TMA+TMI: "
        f"{len(current_result['both']):,}"
    )
    log(
        f"TMA/TMI-Zeilen: {current_result['row_count']:,}"
    )
    log(
        f"Datenzeitraum: {current_result['first_date']} bis "
        f"{current_result['last_date']}"
    )

    for element in ("TMA", "TMI"):
        vals = current_result["values"][element]
        if vals:
            log(
                f"{element} Wertebereich: "
                f"{min(vals):.1f} bis {max(vals):.1f} °C"
            )
        log(
            f"{element} QUALITY: "
            f"{dict(current_result['qualities'][element])}"
        )
        log(
            f"{element} FLAG: "
            f"{dict(current_result['flags'][element])}"
        )

    if current_result["errors"]:
        log("Current Fehler-Sample:")
        for station, error in current_result["errors"][:10]:
            log(f"  {station}: {error}")

    log()
    log("Stations-Sample mit Current TMA+TMI:")
    for station in current_result["both"][:20]:
        meta = metadata["latest"].get(station, {})
        log(
            f"  {station} | {meta.get('name', '?')} | "
            f"{meta.get('lat', '?')}, {meta.get('lon', '?')}"
        )

    log()
    log("=" * 76)
    log("=== CHMI CZECHIA PROBE SUMMARY ===")
    log("=" * 76)
    log(f"Historische TMA-Dateien: {len(hist['tma']):,}")
    log(f"Historische TMI-Dateien: {len(hist['tmi']):,}")
    log(f"TMA+TMI-Paare: {len(hist['paired']):,}")
    log(f"TMA+TMI-Paare mit CZ-Metadaten: {len(paired_cz):,}")
    log(
        "Frühester Metadatenbeginn: "
        + (
            metadata["earliest"]["begin"][:10]
            if metadata["earliest"]
            else "?"
        )
    )
    log(
        f"Historischer Sample {sample_station}: "
        f"TMA {tma_probe['first_date']}–{tma_probe['last_date']} | "
        f"TMI {tmi_probe['first_date']}–{tmi_probe['last_date']}"
    )
    log(f"Current-Batch: {current['latest_month']}")
    log(
        f"Current Stationen mit TMA+TMI: "
        f"{len(current_result['both']):,}"
    )
    log(
        f"Current Daten: {current_result['first_date']} bis "
        f"{current_result['last_date']}"
    )
    log(f"Current Parse-Fehler: {len(current_result['errors'])}")
    log("CHMI Czechia Probe OK.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    if args.self_test:
        self_test()
    else:
        probe(max(1, min(args.workers, 24)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
