#!/usr/bin/env python3
"""
SMHI Sweden probe for climate-dashboard station records.

Checks the official SMHI MetObs Open Data API for:
- parameter 19: daily minimum air temperature
- parameter 20: daily maximum air temperature
- CORE stations only
- station metadata / active status / coordinates
- corrected-archive CSV structure and quality codes
- latest-months JSON for current observations
- overlap/gap between corrected archive and recent data

No authentication is required.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any

BASE = "https://opendata-download-metobs.smhi.se/api/version/latest"
PARAM_TMIN = 19
PARAM_TMAX = 20
UA = "climate-dashboard-smhi-sweden-probe/1.0"
TRIES = 5


def log(msg: str = "") -> None:
    print(msg, flush=True)


def request_bytes(url: str) -> bytes:
    last = None
    for attempt in range(1, TRIES + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept-Encoding": "identity",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                return response.read()
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            last = exc
            retryable = (
                not isinstance(exc, urllib.error.HTTPError)
                or exc.code in {408, 429, 500, 502, 503, 504}
            )
            if attempt >= TRIES or not retryable:
                raise
            wait = min(20, attempt * 3)
            log(f"WARNUNG: {exc}; neuer Versuch in {wait}s …")
            time.sleep(wait)
    raise RuntimeError(str(last))


def request_json(url: str) -> dict[str, Any]:
    raw = request_bytes(url)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unerwartete JSON-Struktur: {url}")
    return payload


def parameter_url(parameter: int) -> str:
    return f"{BASE}/parameter/{parameter}.json?measuringStations=core"


def station_data_url(parameter: int, station: str, period: str, ext: str) -> str:
    return (
        f"{BASE}/parameter/{parameter}/station/{station}/"
        f"period/{period}/data.{ext}"
    )


def station_key(st: dict[str, Any]) -> str:
    return str(st.get("key", "")).strip()


def period_keys(st: dict[str, Any]) -> set[str]:
    periods = st.get("period") or []
    result = set()
    if isinstance(periods, list):
        for item in periods:
            if isinstance(item, dict) and item.get("key") is not None:
                result.add(str(item["key"]))
    return result


def station_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stations = payload.get("station") or []
    if not isinstance(stations, list):
        return {}
    out = {}
    for station in stations:
        if not isinstance(station, dict):
            continue
        key = station_key(station)
        if not key:
            continue
        # The parameter-level query is filtered to CORE, but keep a defensive
        # verification of the metadata when the field is present.
        measuring = str(station.get("measuringStations") or "").upper()
        if measuring and measuring != "CORE":
            continue
        out[key] = station
    return out


def unix_ms_to_date(value: Any) -> date | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x > 10_000_000_000:
        x /= 1000.0
    try:
        return datetime.fromtimestamp(x, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def json_values(payload: dict[str, Any]) -> list[tuple[date, float, str]]:
    values = payload.get("value") or []
    result = []
    if not isinstance(values, list):
        return result

    for item in values:
        if not isinstance(item, dict):
            continue
        d = unix_ms_to_date(item.get("date"))
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        if d is None or not math.isfinite(value):
            continue
        result.append((d, value, str(item.get("quality") or "").strip()))
    return result


def decode_csv(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def norm(text: str) -> str:
    text = text.strip().lower()
    text = (
        text.replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
    )
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def parse_date_text(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def parse_corrected_archive(
    raw: bytes,
) -> dict[str, Any]:
    text = decode_csv(raw)
    lines = text.splitlines()

    header_index = None
    delimiter = ";"

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        # SMHI archive CSV has metadata above the actual data table.
        # Locate the actual data header generically using date+quality tokens.
        lower = norm(line)
        if ("datum" in lower or "date" in lower) and (
            "kvalitet" in lower or "quality" in lower
        ):
            header_index = i
            delimiter = ";" if line.count(";") >= line.count(",") else ","
            break

    if header_index is None:
        # Fallback: find the first semicolon-rich row and inspect it.
        for i, line in enumerate(lines):
            if line.count(";") >= 2:
                fields = [norm(x) for x in line.split(";")]
                if any(x in fields for x in ("datum", "date")):
                    header_index = i
                    delimiter = ";"
                    break

    if header_index is None:
        raise RuntimeError("SMHI corrected-archive: Datenkopf nicht erkannt.")

    reader = csv.DictReader(
        io.StringIO("\n".join(lines[header_index:])),
        delimiter=delimiter,
    )
    headers = list(reader.fieldnames or [])
    normalized = {norm(h): h for h in headers if h is not None}

    date_col = None
    for candidate in ("datum", "date"):
        if candidate in normalized:
            date_col = normalized[candidate]
            break
    if date_col is None:
        raise RuntimeError(f"SMHI CSV: Datumsspalte fehlt: {headers}")

    quality_col = None
    for candidate in ("kvalitet", "quality"):
        if candidate in normalized:
            quality_col = normalized[candidate]
            break

    # Value column names vary with Swedish parameter title. Choose a numeric
    # column excluding date/time/quality metadata.
    excluded = {
        norm(date_col),
        "tid_utc",
        "time_utc",
        "tid",
        "time",
        "kvalitet",
        "quality",
    }

    rows = []
    value_column = None
    for row in reader:
        d = parse_date_text(str(row.get(date_col, "")))
        if d is None:
            continue

        if value_column is None:
            for h in headers:
                if h is None or norm(h) in excluded:
                    continue
                raw_value = str(row.get(h, "")).strip().replace(",", ".")
                try:
                    candidate_value = float(raw_value)
                except ValueError:
                    continue
                if math.isfinite(candidate_value):
                    value_column = h
                    break

        if value_column is None:
            continue

        raw_value = str(row.get(value_column, "")).strip().replace(",", ".")
        try:
            value = float(raw_value)
        except ValueError:
            continue
        if not math.isfinite(value):
            continue

        quality = str(row.get(quality_col, "") if quality_col else "").strip()
        rows.append((d, value, quality))

    return {
        "headers": headers,
        "header_index": header_index,
        "delimiter": delimiter,
        "value_column": value_column,
        "rows": rows,
    }


def best_sample_station(
    common: set[str],
    tmin: dict[str, dict[str, Any]],
    tmax: dict[str, dict[str, Any]],
    *,
    require_active: bool,
    require_periods: set[str],
) -> str | None:
    candidates = []
    for sid in common:
        a = tmin[sid]
        b = tmax[sid]
        active = bool(a.get("active")) and bool(b.get("active"))
        if require_active and not active:
            continue
        if not require_periods <= period_keys(a):
            continue
        if not require_periods <= period_keys(b):
            continue

        start = min(
            str(a.get("from") or "9999-12-31"),
            str(b.get("from") or "9999-12-31"),
        )
        candidates.append((start, sid))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def inspect_parameter(parameter: int) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    payload = request_json(parameter_url(parameter))
    stations = station_map(payload)
    return payload, stations


def run_probe() -> None:
    log("=== SMHI SCHWEDEN PROBE ===")
    log("Parameter 19 = tägliches Tmin | Parameter 20 = tägliches Tmax")
    log("Nur SMHI CORE-Netz.")
    log()

    p19, s19 = inspect_parameter(PARAM_TMIN)
    p20, s20 = inspect_parameter(PARAM_TMAX)

    common = set(s19) & set(s20)
    active_common = {
        sid for sid in common
        if bool(s19[sid].get("active")) and bool(s20[sid].get("active"))
    }
    archive_common = {
        sid for sid in common
        if "corrected-archive" in period_keys(s19[sid])
        and "corrected-archive" in period_keys(s20[sid])
    }
    recent_common = {
        sid for sid in common
        if "latest-months" in period_keys(s19[sid])
        and "latest-months" in period_keys(s20[sid])
    }

    log(f"Parameter 19 CORE-Stationen: {len(s19)}")
    log(f"Parameter 20 CORE-Stationen: {len(s20)}")
    log(f"Gemeinsame Tmax+Tmin-Stationen: {len(common)}")
    log(f"Davon aktuell aktiv: {len(active_common)}")
    log(f"Mit corrected-archive für beide Parameter: {len(archive_common)}")
    log(f"Mit latest-months für beide Parameter: {len(recent_common)}")

    if not common or not archive_common:
        raise RuntimeError("SMHI liefert keine gemeinsamen CORE-Tmax/Tmin-Archive.")

    historical_sid = best_sample_station(
        common,
        s19,
        s20,
        require_active=False,
        require_periods={"corrected-archive"},
    )
    if historical_sid is None:
        raise RuntimeError("Keine historische SMHI-Sample-Station gefunden.")

    log()
    log(f"Historische Sample-Station: {historical_sid}")
    log(f"Name: {s20[historical_sid].get('name')}")
    log(
        f"Position: {s20[historical_sid].get('latitude')}, "
        f"{s20[historical_sid].get('longitude')}"
    )
    log(f"active: {s20[historical_sid].get('active')}")
    log(f"measuringStations: {s20[historical_sid].get('measuringStations')}")

    archive_results = {}
    for parameter, label in ((PARAM_TMIN, "TMIN"), (PARAM_TMAX, "TMAX")):
        raw = request_bytes(
            station_data_url(
                parameter,
                historical_sid,
                "corrected-archive",
                "csv",
            )
        )
        parsed = parse_corrected_archive(raw)
        rows = parsed["rows"]
        if not rows:
            raise RuntimeError(
                f"SMHI corrected-archive {label} für {historical_sid} ist leer."
            )
        archive_results[label] = rows
        qualities = Counter(q or "(leer)" for _, _, q in rows)
        log()
        log(f"{label} corrected-archive:")
        log(f"  Datenkopf in CSV-Zeile: {parsed['header_index'] + 1}")
        log(f"  Trennzeichen: {repr(parsed['delimiter'])}")
        log(f"  Spalten: {' | '.join(parsed['headers'])}")
        log(f"  Wertespalte: {parsed['value_column']}")
        log(f"  Werte: {len(rows):,}")
        log(f"  Zeitraum: {min(x[0] for x in rows)} bis {max(x[0] for x in rows)}")
        log(f"  Qualitätscodes: {dict(qualities)}")
        log(
            f"  Wertebereich: {min(x[1] for x in rows):.1f} bis "
            f"{max(x[1] for x in rows):.1f} °C"
        )

    current_sid = best_sample_station(
        common,
        s19,
        s20,
        require_active=True,
        require_periods={"latest-months"},
    )
    if current_sid is None:
        raise RuntimeError("Keine aktive SMHI-Station mit latest-months für Tmax+Tmin.")

    log()
    log(f"Aktuelle Sample-Station: {current_sid} ({s20[current_sid].get('name')})")
    recent_results = {}
    for parameter, label in ((PARAM_TMIN, "TMIN"), (PARAM_TMAX, "TMAX")):
        payload = request_json(
            station_data_url(
                parameter,
                current_sid,
                "latest-months",
                "json",
            )
        )
        rows = json_values(payload)
        if not rows:
            raise RuntimeError(f"SMHI latest-months {label} ist leer.")
        recent_results[label] = rows
        qualities = Counter(q or "(leer)" for _, _, q in rows)
        log(
            f"{label} latest-months: {len(rows)} Werte | "
            f"{min(x[0] for x in rows)} bis {max(x[0] for x in rows)} | "
            f"Qualität {dict(qualities)}"
        )

    # If the current sample also has corrected archive, inspect overlap.
    if current_sid in archive_common:
        log()
        log("=== ARCHIV/CURRENT ÜBERGANG ===")
        for parameter, label in ((PARAM_TMIN, "TMIN"), (PARAM_TMAX, "TMAX")):
            parsed = parse_corrected_archive(
                request_bytes(
                    station_data_url(
                        parameter,
                        current_sid,
                        "corrected-archive",
                        "csv",
                    )
                )
            )
            archive_rows = parsed["rows"]
            recent_rows = recent_results[label]
            archive_last = max(x[0] for x in archive_rows)
            recent_first = min(x[0] for x in recent_rows)
            recent_last = max(x[0] for x in recent_rows)
            gap = (recent_first - archive_last).days
            log(
                f"{label}: Archiv bis {archive_last} | latest-months ab "
                f"{recent_first} bis {recent_last} | Abstand {gap:+d} Tage"
            )

    # Determine nominal earliest metadata dates across both parameters.
    starts = []
    for sid in common:
        for st in (s19[sid], s20[sid]):
            raw = st.get("from")
            d = unix_ms_to_date(raw)
            if d:
                starts.append((d, sid))
    starts.sort()

    log()
    log("=== SMHI SWEDEN PROBE SUMMARY ===")
    log(f"Gemeinsame CORE-Tmax/Tmin-Stationen: {len(common)}")
    log(f"Aktuell aktive gemeinsame Stationen: {len(active_common)}")
    log(f"Historische Archive für beide: {len(archive_common)}")
    if starts:
        log(
            f"Frühester Stations-Metadatenbeginn im gemeinsamen Bestand: "
            f"{starts[0][0]} (Station {starts[0][1]})"
        )
    log(f"Historische Sample-Station: {historical_sid}")
    log(f"Aktuelle Sample-Station: {current_sid}")
    log("SMHI Sweden Probe OK.")


def self_test() -> None:
    sample = """Stationsnamn;Test
Stationsnummer;12345

Datum;Tid (UTC);Lufttemperatur;Kvalitet;;
1951-01-01;00:00:00;-12.3;G;;
1951-01-02;00:00:00;-10,5;Y;;
"""
    parsed = parse_corrected_archive(sample.encode("utf-8"))
    assert parsed["value_column"] == "Lufttemperatur"
    assert parsed["rows"][0] == (date(1951, 1, 1), -12.3, "G")
    assert parsed["rows"][1] == (date(1951, 1, 2), -10.5, "Y")

    payload = {
        "value": [
            {"date": 1767225600000, "value": -2.4, "quality": "G"},
        ]
    }
    values = json_values(payload)
    assert values and values[0][1:] == (-2.4, "G")

    stations = station_map(
        {
            "station": [
                {
                    "key": 1,
                    "measuringStations": "CORE",
                    "active": True,
                    "period": [{"key": "corrected-archive"}],
                },
                {
                    "key": 2,
                    "measuringStations": "ADDITIONAL",
                },
            ]
        }
    )
    assert set(stations) == {"1"}
    print("SMHI Sweden probe self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
    else:
        run_probe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
