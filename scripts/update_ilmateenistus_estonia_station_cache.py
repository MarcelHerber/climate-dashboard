#!/usr/bin/env python3
"""
Build the historical daily Tmax/Tmin baseline for the currently active
Estonian temperature-station network from the Estonian Environment Agency
climate API.

The active station set was verified by the preceding live probe on 2026-08-17:
25 stations had both daily DTAX (Tmax) and DTAN (Tmin). 24 of them reach back
at least 30 years in the public daily archive; Roomassaare starts in 2007.

This script deliberately builds only the historical baseline through the chosen
cutoff year. It does NOT modify the Europe production workflow.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import pickle
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_ROOT = "https://keskkonnaandmed.envir.ee"
DAILY_PATH = "/f_kliima_paev"
STATION_PATH = "/f_kliima_jaam_vaatlus"
PROFILE = "apijahialad"

SOURCE = "Estonian Environment Agency climate API"
PUBLIC_URL = "https://keskkonnaportaal.ee/"
COUNTRY = "Estonia"
COUNTRY_CODE = "EE"
NETWORK = "Keskkonnaagentuur climate stations"

PARAM_TMAX = "DTAX"
PARAM_TMIN = "DTAN"
ELEMENTS = (PARAM_TMAX, PARAM_TMIN)

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
START_YEAR = 1991
USER_AGENT = "climate-dashboard-estonia-cache/1.0"
HTTP_TIMEOUT = 90
TRIES = 5
REQUEST_SLEEP = 0.20
PAGE_LIMIT = 10000

# Frozen active DTAX+DTAN network from the successful 2026-08-17 probe.
ACTIVE_STATION_CODES = (
    "AJHARK01",  # Tallinn-Harku
    "AJHELT01",  # Heltermaa
    "AJJOGE01",  # Jõgeva
    "AJJOHV01",  # Jõhvi
    "AJKIHN01",  # Kihnu
    "AJKUND01",  # Kunda
    "AJKUUS01",  # Kuusiku
    "AJNARV01",  # Narva
    "AJNIGU01",  # Lääne-Nigula
    "AJPAKR01",  # Pakri
    "AJPARN01",  # Pärnu
    "AJRIST01",  # Ristna
    "AJROOM01",  # Roomassaare
    "AJRUHN01",  # Ruhnu
    "AJSORV01",  # Sõrve
    "AJTART01",  # Tartu-Tõravere
    "AJTIIR01",  # Tiirikoja
    "AJTOOM01",  # Tooma
    "AJTURI01",  # Türi
    "AJV-MA01",  # Väike-Maarja
    "AJVALG01",  # Valga
    "AJVILJ01",  # Viljandi
    "AJVILS01",  # Vilsandi
    "AJVIRT01",  # Virtsu
    "AJVORU01",  # Võru
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"ilmateenistus_estonia_daily_baseline_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"ilmateenistus_estonia_progress_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"ilmateenistus_estonia_status_through_{cutoff_year}.json"


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as handle:
            pickle.dump(obj, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_pickle_gzip(path: Path) -> Any:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def row_date(row: dict[str, Any]) -> date | None:
    try:
        return date(int(row["aasta"]), int(row["kuu"]), int(row["paev"]))
    except (KeyError, TypeError, ValueError):
        return None


def compact_http_body(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    return " ".join(body.split())[:1500]


def api_get(
    path: str,
    params: Iterable[tuple[str, str]] = (),
    *,
    timeout: int = HTTP_TIMEOUT,
    attempts: int = TRIES,
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
            if REQUEST_SLEEP:
                time.sleep(REQUEST_SLEEP)
            try:
                req = Request(url, headers=headers)
                with urlopen(req, timeout=timeout) as response:
                    payload = response.read().decode("utf-8", errors="replace")
                data = json.loads(payload)
                if not isinstance(data, list):
                    raise RuntimeError(
                        f"Unexpected API payload type: {type(data).__name__}"
                    )
                return [row for row in data if isinstance(row, dict)]

            except HTTPError as exc:
                last_error = exc
                body = compact_http_body(exc)
                last_detail = f"HTTP {exc.code}" + (f": {body}" if body else "")

                # The live probe showed that the documented Accept-Profile can
                # currently return 406 while the default schema works.
                if exc.code == 406 and mode_index == 0:
                    log(
                        "WARN Estland API: 406 mit Accept-Profile; "
                        "wechsle auf Default-Schema."
                    )
                    if body:
                        log(f"API 406: {body}")
                    break

                retryable = exc.code in {
                    408, 425, 429, 500, 502, 503, 504
                }
                if not retryable or attempt >= attempts:
                    break
                wait = min(20.0, 2.0 * attempt)
                log(
                    f"WARN Estland API {mode_name}: {last_detail}; "
                    f"neuer Versuch in {wait:.1f}s"
                )
                time.sleep(wait)

            except (
                URLError,
                TimeoutError,
                json.JSONDecodeError,
                RuntimeError,
                OSError,
            ) as exc:
                last_error = exc
                last_detail = str(exc)
                if attempt >= attempts:
                    break
                wait = min(20.0, 2.0 * attempt)
                log(
                    f"WARN Estland API {mode_name}: {exc}; "
                    f"neuer Versuch in {wait:.1f}s"
                )
                time.sleep(wait)
        else:
            continue

        if (
            isinstance(last_error, HTTPError)
            and last_error.code == 406
            and mode_index == 0
        ):
            continue
        break

    detail = f" ({last_detail})" if last_detail else ""
    raise RuntimeError(
        f"Estland API request failed: {url}: {last_error}{detail}"
    )


def station_filter() -> str:
    return "in.(" + ",".join(ACTIVE_STATION_CODES) + ")"


def fetch_all_pages(
    path: str,
    base_params: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """
    Fetch a PostgREST result completely. We deliberately continue until an
    empty page instead of assuming the server honours our requested limit.
    This is robust against a lower server-side row cap.
    """
    out: list[dict[str, Any]] = []
    offset = 0
    seen_signatures: set[tuple[Any, ...]] = set()

    while True:
        params = [
            *base_params,
            ("limit", str(PAGE_LIMIT)),
            ("offset", str(offset)),
        ]
        page = api_get(path, params)
        if not page:
            break

        first = page[0]
        last = page[-1]
        signature = (
            offset,
            len(page),
            first.get("jaam_kood"),
            first.get("aasta"),
            first.get("kuu"),
            first.get("paev"),
            first.get("element_kood"),
            last.get("jaam_kood"),
            last.get("aasta"),
            last.get("kuu"),
            last.get("paev"),
            last.get("element_kood"),
        )
        if signature in seen_signatures:
            raise RuntimeError(
                f"Pagination repeated the same page at offset {offset}."
            )
        seen_signatures.add(signature)

        out.extend(page)
        offset += len(page)

    return out


def fetch_station_metadata() -> dict[str, dict[str, Any]]:
    rows = fetch_all_pages(
        STATION_PATH,
        [
            ("jaam_kood", station_filter()),
            ("order", "jaam_kood.asc"),
        ],
    )

    by_code: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("jaam_kood") or "").strip()
        if code not in ACTIVE_STATION_CODES:
            continue
        old = by_code.get(code)
        if old is None:
            by_code[code] = row
            continue

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

    return by_code


def fetch_year(year: int) -> list[dict[str, Any]]:
    return fetch_all_pages(
        DAILY_PATH,
        [
            ("aasta", f"eq.{year}"),
            ("jaam_kood", station_filter()),
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


def better_max(old: list[Any] | None, value: float) -> bool:
    return old is None or value > float(old[0])


def better_min(old: list[Any] | None, value: float) -> bool:
    return old is None or value < float(old[0])


def empty_record() -> dict[str, Any]:
    return {
        "first_date": None,
        "last_date": None,
        "observation_days": 0,
        "tmax_abs": None,
        "tmax_low_abs": None,
        "tmin_abs": None,
        "tmin_high_abs": None,
        "calendar_tmax": {},
        "calendar_tmin": {},
        "provenance_days": {"ESTONIA_CLIMATE_API": 0},
    }


def consume_day(
    rec: dict[str, Any],
    d: date,
    tmin: float | None,
    tmax: float | None,
) -> bool:
    if tmin is None and tmax is None:
        return False

    iso = d.isoformat()
    mmdd = d.strftime("%m-%d")

    if rec["first_date"] is None or iso < rec["first_date"]:
        rec["first_date"] = iso
    if rec["last_date"] is None or iso > rec["last_date"]:
        rec["last_date"] = iso

    rec["observation_days"] += 1
    rec["provenance_days"]["ESTONIA_CLIMATE_API"] += 1

    if tmax is not None:
        if better_max(rec["tmax_abs"], tmax):
            rec["tmax_abs"] = [float(tmax), iso]
        if better_min(rec["tmax_low_abs"], tmax):
            rec["tmax_low_abs"] = [float(tmax), iso]

        old = rec["calendar_tmax"].get(mmdd)
        if better_max(old, tmax):
            rec["calendar_tmax"][mmdd] = [float(tmax), iso]

    if tmin is not None:
        if better_min(rec["tmin_abs"], tmin):
            rec["tmin_abs"] = [float(tmin), iso]
        if better_max(rec["tmin_high_abs"], tmin):
            rec["tmin_high_abs"] = [float(tmin), iso]

        old = rec["calendar_tmin"].get(mmdd)
        if better_min(old, tmin):
            rec["calendar_tmin"][mmdd] = [float(tmin), iso]

    return True


def update_span(progress: dict[str, Any], d: date) -> None:
    iso = d.isoformat()
    if progress["first_date"] is None or iso < progress["first_date"]:
        progress["first_date"] = iso
    if progress["last_date"] is None or iso > progress["last_date"]:
        progress["last_date"] = iso


def inventory_entry(
    code: str,
    meta: dict[str, Any] | None,
    fallback_name: str | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    return {
        "id": code,
        "name": str(
            meta.get("jaam_nimi") or fallback_name or code
        ).strip(),
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "lat": number(meta.get("laiuskraad")),
        "lon": number(meta.get("pikkuskraad")),
        "elevation_m": None,
        "network": NETWORK,
        "source": SOURCE,
    }


def initial_progress(cutoff_year: int) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "cutoff_year": cutoff_year,
        "complete": False,
        "active_station_codes": list(ACTIVE_STATION_CODES),
        "inventory": {},
        "records": {},
        "processed_years": [],
        "raw_element_rows": 0,
        "rows_with_temperature": 0,
        "first_date": None,
        "last_date": None,
        "qc_rejected_inconsistent_days": 0,
    }


def valid_final(path: Path, cutoff_year: int) -> bool:
    if not path.exists():
        return False
    try:
        obj = load_pickle_gzip(path)
    except Exception:
        return False
    return (
        isinstance(obj, dict)
        and obj.get("format_version") == FORMAT_VERSION
        and obj.get("cutoff_year") == cutoff_year
        and obj.get("complete") is True
        and len(obj.get("records", {})) == len(ACTIVE_STATION_CODES)
    )


def write_status(
    cache_dir: Path,
    cutoff_year: int,
    payload: dict[str, Any],
) -> None:
    records = payload.get("records", {})
    status = {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "country": COUNTRY,
        "cutoff_year": cutoff_year,
        "complete": bool(payload.get("complete")),
        "expected_active_station_count": len(ACTIVE_STATION_CODES),
        "station_count": len(records),
        "inventory_count": len(payload.get("inventory", {})),
        "rows_with_temperature": int(
            payload.get("rows_with_temperature", 0)
        ),
        "raw_element_rows": int(payload.get("raw_element_rows", 0)),
        "first_date": payload.get("first_date"),
        "last_date": payload.get("last_date"),
        "processed_years": len(payload.get("processed_years", [])),
        "qc_rejected_inconsistent_days": int(
            payload.get("qc_rejected_inconsistent_days", 0)
        ),
        "baseline_file": str(baseline_path(cache_dir, cutoff_year)),
    }
    atomic_json(status_path(cache_dir, cutoff_year), status)


def process_year(
    rows: list[dict[str, Any]],
    progress: dict[str, Any],
    metadata: dict[str, dict[str, Any]],
    cutoff_year: int,
) -> int:
    by_day: dict[
        tuple[str, date],
        dict[str, float | None],
    ] = {}
    names: dict[str, str] = {}

    for row in rows:
        code = str(row.get("jaam_kood") or "").strip()
        element = str(row.get("element_kood") or "").strip()
        d = row_date(row)
        value = number(row.get("vaartus"))

        if code not in ACTIVE_STATION_CODES:
            continue
        if element not in ELEMENTS or d is None or d.year > cutoff_year:
            continue
        if value is None:
            continue

        names[code] = str(row.get("jaam_nimi") or code).strip()
        slot = by_day.setdefault(
            (code, d),
            {PARAM_TMAX: None, PARAM_TMIN: None},
        )
        slot[element] = value

    accepted = 0
    for (code, d), values in sorted(
        by_day.items(),
        key=lambda item: (item[0][0], item[0][1]),
    ):
        tmax = values[PARAM_TMAX]
        tmin = values[PARAM_TMIN]

        if tmin is not None and tmax is not None and tmin > tmax:
            progress["qc_rejected_inconsistent_days"] += 1
            continue

        rec = progress["records"].setdefault(code, empty_record())
        if consume_day(rec, d, tmin, tmax):
            accepted += 1
            update_span(progress, d)

    for code in ACTIVE_STATION_CODES:
        old = progress["inventory"].get(code)
        new = inventory_entry(
            code,
            metadata.get(code),
            names.get(code),
        )
        if not isinstance(old, dict):
            progress["inventory"][code] = new
        else:
            for key, value in new.items():
                if value not in (None, ""):
                    old[key] = value

    return accepted


def build_baseline(
    cache_dir: Path,
    cutoff_year: int,
    *,
    force: bool = False,
    max_runtime_minutes: float = 155.0,
) -> Path:
    if cutoff_year < START_YEAR:
        raise ValueError(
            f"cutoff year {cutoff_year} is before public daily start {START_YEAR}"
        )

    cache_dir.mkdir(parents=True, exist_ok=True)
    final = baseline_path(cache_dir, cutoff_year)
    prog_file = progress_path(cache_dir, cutoff_year)
    stat_file = status_path(cache_dir, cutoff_year)

    if force:
        final.unlink(missing_ok=True)
        prog_file.unlink(missing_ok=True)
        stat_file.unlink(missing_ok=True)

    if not force and valid_final(final, cutoff_year):
        log(f"Verwende vorhandenen Estland-Baselinecache: {final}")
        return final

    if not force and prog_file.exists():
        try:
            progress = load_pickle_gzip(prog_file)
            if (
                progress.get("format_version") != FORMAT_VERSION
                or progress.get("cutoff_year") != cutoff_year
                or tuple(progress.get("active_station_codes", ()))
                != ACTIVE_STATION_CODES
            ):
                progress = initial_progress(cutoff_year)
        except Exception:
            progress = initial_progress(cutoff_year)
    else:
        progress = initial_progress(cutoff_year)

    log("=== ESTLAND HISTORISCHE TMAX/TMIN BASELINE ===")
    log(f"Quelle: {SOURCE}")
    log(f"Elemente: {PARAM_TMAX}=Tmax | {PARAM_TMIN}=Tmin")
    log(f"Zeitraum: {START_YEAR}-01-01 bis {cutoff_year}-12-31")
    log(f"Eingefrorene aktive Stationen: {len(ACTIVE_STATION_CODES)}")
    log(
        "Hinweis: Roomassaare ist bewusst enthalten; "
        "öffentliche Reihe beginnt dort erst 2007."
    )

    metadata = fetch_station_metadata()
    log(
        f"Stationsmetadaten gefunden: {len(metadata)}/"
        f"{len(ACTIVE_STATION_CODES)}"
    )

    done = set(int(y) for y in progress.get("processed_years", []))
    years = list(range(START_YEAR, cutoff_year + 1))
    started = time.monotonic()

    for index, year in enumerate(years, start=1):
        if year in done:
            continue

        rows = fetch_year(year)
        accepted = process_year(
            rows,
            progress,
            metadata,
            cutoff_year,
        )
        progress["raw_element_rows"] += len(rows)
        progress["processed_years"].append(year)
        done.add(year)
        progress["rows_with_temperature"] = sum(
            int(rec.get("observation_days", 0))
            for rec in progress["records"].values()
        )

        atomic_pickle_gzip(prog_file, progress)

        log(
            f"Estland {year}: {len(rows):,} Element-Zeilen | "
            f"{accepted:,} Stationstage | "
            f"{len(progress['records'])} Stationsreihen | "
            f"gesamt {progress['rows_with_temperature']:,} Stationstage"
        )

        elapsed_minutes = (time.monotonic() - started) / 60.0
        if elapsed_minutes >= max_runtime_minutes:
            log(
                "Laufzeitgrenze erreicht. Zwischenstand gespeichert; "
                "Workflow mit force=false erneut starten."
            )
            return prog_file

    missing = [
        code for code in ACTIVE_STATION_CODES
        if code not in progress["records"]
    ]
    if missing:
        raise RuntimeError(
            "Für aktive Stationen fehlen historische Temperaturdaten: "
            + ", ".join(missing)
        )

    progress["complete"] = True
    payload = {
        **progress,
        "parameters": {
            "TMAX": PARAM_TMAX,
            "TMIN": PARAM_TMIN,
        },
        "public_url": PUBLIC_URL,
        "api_root": API_ROOT,
        "daily_endpoint": DAILY_PATH,
        "station_endpoint": STATION_PATH,
        "quality_note": (
            "Official Estonian Environment Agency daily climate data. "
            "Only non-finite values and days with Tmin>Tmax are rejected. "
            "The baseline contains the 25 stations verified active with both "
            "DTAX and DTAN on 2026-08-17."
        ),
    }

    atomic_pickle_gzip(final, payload)
    write_status(cache_dir, cutoff_year, payload)
    prog_file.unlink(missing_ok=True)

    log()
    log("=== ESTLAND BASELINE SUMMARY ===")
    log(f"Stationsreihen: {len(payload['records'])}")
    log(f"Inventar: {len(payload['inventory'])}")
    log(f"Stationstage: {payload['rows_with_temperature']:,}")
    log(f"Element-Zeilen: {payload['raw_element_rows']:,}")
    log(f"Datenzeitraum: {payload['first_date']} bis {payload['last_date']}")
    log(
        "Tmin>Tmax verworfen: "
        f"{payload['qc_rejected_inconsistent_days']:,}"
    )
    log(f"Output: {final}")
    log("Estland Baseline OK.")
    return final


def self_test() -> None:
    assert len(ACTIVE_STATION_CODES) == 25
    assert len(set(ACTIVE_STATION_CODES)) == 25
    assert "AJROOM01" in ACTIVE_STATION_CODES

    sample_rows = [
        {
            "jaam_kood": "AJHARK01",
            "jaam_nimi": "Tallinn-Harku",
            "aasta": 2025,
            "kuu": 7,
            "paev": 1,
            "vaartus": "28.4",
            "element_kood": "DTAX",
        },
        {
            "jaam_kood": "AJHARK01",
            "jaam_nimi": "Tallinn-Harku",
            "aasta": 2025,
            "kuu": 7,
            "paev": 1,
            "vaartus": "12.3",
            "element_kood": "DTAN",
        },
        {
            "jaam_kood": "AJHARK01",
            "jaam_nimi": "Tallinn-Harku",
            "aasta": 2025,
            "kuu": 7,
            "paev": 2,
            "vaartus": "29.1",
            "element_kood": "DTAX",
        },
        {
            "jaam_kood": "AJHARK01",
            "jaam_nimi": "Tallinn-Harku",
            "aasta": 2025,
            "kuu": 7,
            "paev": 2,
            "vaartus": "11.0",
            "element_kood": "DTAN",
        },
    ]

    progress = initial_progress(2025)
    accepted = process_year(
        sample_rows,
        progress,
        {
            "AJHARK01": {
                "jaam_kood": "AJHARK01",
                "jaam_nimi": "Tallinn-Harku",
                "laiuskraad": "59.3981",
                "pikkuskraad": "24.6029",
            }
        },
        2025,
    )
    rec = progress["records"]["AJHARK01"]
    assert accepted == 2
    assert rec["tmax_abs"] == [29.1, "2025-07-02"]
    assert rec["tmin_abs"] == [11.0, "2025-07-02"]
    assert rec["observation_days"] == 2
    assert progress["inventory"]["AJHARK01"]["country_code"] == "EE"
    assert progress["inventory"]["AJHARK01"]["lat"] == 59.3981

    bad_rows = [
        {
            "jaam_kood": "AJHARK01",
            "jaam_nimi": "Tallinn-Harku",
            "aasta": 2025,
            "kuu": 7,
            "paev": 3,
            "vaartus": "10",
            "element_kood": "DTAX",
        },
        {
            "jaam_kood": "AJHARK01",
            "jaam_nimi": "Tallinn-Harku",
            "aasta": 2025,
            "kuu": 7,
            "paev": 3,
            "vaartus": "12",
            "element_kood": "DTAN",
        },
    ]
    before = progress["qc_rejected_inconsistent_days"]
    process_year(bad_rows, progress, {}, 2025)
    assert progress["qc_rejected_inconsistent_days"] == before + 1

    print("Estonia historical cache self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--cache-dir",
        default=str(CACHE_DIR_DEFAULT),
    )
    parser.add_argument(
        "--cutoff-year",
        type=int,
        default=date.today().year - 1,
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        default=155.0,
    )
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_baseline(
        Path(args.cache_dir),
        args.cutoff_year,
        force=args.force,
        max_runtime_minutes=args.max_runtime_minutes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
