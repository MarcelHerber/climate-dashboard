#!/usr/bin/env python3
"""Build the historical UK Met Office MIDAS Open daily TMIN/TMAX cache.

Source:
  Met Office MIDAS Open: UK daily temperature data, dataset-version-202607.

Important MIDAS timing rule:
  - TMAX for climate day D covers 09 UTC on D through 09 UTC on D+1.
  - TMIN for climate day D covers 09 UTC on D-1 through 09 UTC on D.

MIDAS daily-temperature rows may therefore contain:
  - a complete 24-hour interval ending at 09 UTC, or
  - two 12-hour intervals ending at 21 UTC and 09 UTC.

This builder never treats a single 12-hour row as a daily record.  It either
uses a complete 24-hour 09-09 row or combines both matching 12-hour halves.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import io
import json
import math
import os
import pickle
import re
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SOURCE = "Met Office MIDAS Open"
COUNTRY = "United Kingdom"
COUNTRY_CODE = "UK"

DATASET_VERSION = "202607"
DATASET_NAME = "uk-daily-temperature-obs"
PUBLIC_URL = (
    "https://catalogue.ceda.ac.uk/uuid/1854bb17ec454841b04e243a1352f25a/"
)

DATA_ROOT = (
    "https://data.ceda.ac.uk/badc/ukmo-midas-open/data/"
    f"{DATASET_NAME}/dataset-version-{DATASET_VERSION}"
)
DAP_ROOT = (
    "https://dap.ceda.ac.uk/badc/ukmo-midas-open/data/"
    f"{DATASET_NAME}/dataset-version-{DATASET_VERSION}"
)
TOKEN_URL = "https://services.ceda.ac.uk/api/token/create/"

STATION_METADATA_NAME = (
    f"midas-open_{DATASET_NAME}_dv-{DATASET_VERSION}_station-metadata.csv"
)

FORMAT_VERSION = 1
CACHE_DIR_DEFAULT = Path(".cache/europe-stations")
UA = "climate-dashboard-metoffice-uk-historical-cache/1.0 (+GitHub Actions)"
COMMISSIONING_SRC_ID = "99999"

HTTP_TIMEOUT = 120
TRIES = 4

# Very broad physical sanity envelope.  It is deliberately much wider than UK
# climatology, so it catches encoding/fill errors rather than real extremes.
TMIN_FLOOR = -60.0
TMIN_CEILING = 50.0
TMAX_FLOOR = -50.0
TMAX_CEILING = 60.0


@dataclass(frozen=True)
class StationDir:
    county: str
    dirname: str
    station_id: str
    name: str
    data_url: str


def log(msg: str = "") -> None:
    print(msg, flush=True)


def baseline_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"metoffice_uk_midas_daily_baseline_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def progress_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / (
        f"metoffice_uk_midas_progress_through_{cutoff_year}"
        f"_v{FORMAT_VERSION}.pkl.gz"
    )


def status_path(cache_dir: Path, cutoff_year: int) -> Path:
    return cache_dir / f"metoffice_uk_midas_status_through_{cutoff_year}.json"


def atomic_pickle_gzip(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with gzip.open(tmp, "wb", compresslevel=6) as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_pickle_gzip(path: Path) -> Any:
    with gzip.open(path, "rb") as f:
        return pickle.load(f)


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


def request_bytes(
    url: str,
    *,
    token: str | None = None,
    timeout: int = HTTP_TIMEOUT,
    method: str = "GET",
    data: bytes | None = None,
    basic_auth: str | None = None,
    attempts: int = TRIES,
) -> bytes:
    last: Exception | None = None

    for attempt in range(1, attempts + 1):
        headers = {
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if basic_auth:
            headers["Authorization"] = f"Basic {basic_auth}"

        req = urllib.request.Request(
            url, data=data, headers=headers, method=method
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
                if not raw:
                    raise RuntimeError("leere HTTP-Antwort")
                return raw
        except urllib.error.HTTPError as exc:
            last = exc
            retryable = exc.code in {408, 429, 500, 502, 503, 504}
            if not retryable or attempt >= attempts:
                raise
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            last = exc
            if attempt >= attempts:
                break

        wait = min(30, 2 * attempt)
        time.sleep(wait)

    raise RuntimeError(f"Abruf fehlgeschlagen: {url}: {last}")


def request_json(url: str) -> Any:
    raw = request_bytes(url)
    return json.loads(raw.decode("utf-8-sig"))


def json_listing(url: str) -> list[dict[str, Any]]:
    sep = "&" if "?" in url else "?"
    obj = request_json(url.rstrip("/") + f"/{sep}json=")
    items = obj.get("items", [])
    if not isinstance(items, list):
        raise RuntimeError(f"Ungültige CEDA-Verzeichnisliste: {url}")
    return items


def item_is_dir(item: dict[str, Any]) -> bool:
    return str(item.get("type", "")).lower() in {"dir", "directory"}


def item_is_file(item: dict[str, Any]) -> bool:
    return str(item.get("type", "")).lower() == "file"


def station_from_item(county: str, item: dict[str, Any]) -> StationDir | None:
    dirname = str(item.get("name", "")).strip()
    m = re.match(r"^(\d+)_([a-z0-9].*)$", dirname, re.I)
    if not m:
        return None

    station_id = m.group(1)
    name = m.group(2).replace("-", " ").strip()

    return StationDir(
        county=county,
        dirname=dirname,
        station_id=station_id,
        name=name,
        data_url=f"{DATA_ROOT}/{county}/{dirname}",
    )


def enumerate_public_inventory() -> list[StationDir]:
    root_items = json_listing(DATA_ROOT)
    counties = sorted(
        str(x.get("name", ""))
        for x in root_items
        if item_is_dir(x)
        and str(x.get("name", "")) != "change_log_station_files"
    )

    stations: list[StationDir] = []

    log(f"County-Verzeichnisse: {len(counties):,}")
    for i, county in enumerate(counties, 1):
        items = json_listing(f"{DATA_ROOT}/{county}")
        found = 0
        for item in items:
            if not item_is_dir(item):
                continue
            st = station_from_item(county, item)
            if st is None:
                continue
            stations.append(st)
            found += 1

        if i % 10 == 0 or i == len(counties):
            log(
                f"Inventar: {i}/{len(counties)} Counties | "
                f"Stationsverzeichnisse bisher {len(stations):,}"
            )

    stations.sort(key=lambda s: (s.county, s.dirname))
    return stations


def station_year_files(st: StationDir, cutoff_year: int) -> list[tuple[int, str]]:
    qcurl = f"{st.data_url}/qc-version-1"
    items = json_listing(qcurl)
    out: list[tuple[int, str]] = []

    for item in items:
        if not item_is_file(item):
            continue
        name = str(item.get("name", "")).strip()
        m = re.search(r"_qcv-1_(\d{4})\.csv$", name)
        if not m:
            continue
        year = int(m.group(1))
        if year > cutoff_year:
            continue
        out.append((year, f"{qcurl}/{name}"))

    out.sort()
    return out


def get_ceda_token() -> str:
    manual = os.environ.get("CEDA_ACCESS_TOKEN", "").strip()
    if manual:
        log("CEDA: verwende CEDA_ACCESS_TOKEN.")
        return manual

    username = os.environ.get("CEDA_USERNAME", "").strip()
    password = os.environ.get("CEDA_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "CEDA-Zugang fehlt. GitHub Secret CEDA_ACCESS_TOKEN setzen "
            "(alternativ CEDA_USERNAME + CEDA_PASSWORD)."
        )

    credentials = base64.b64encode(
        f"{username}:{password}".encode("utf-8")
    ).decode("ascii")

    raw = request_bytes(
        TOKEN_URL,
        method="POST",
        data=b"",
        basic_auth=credentials,
        timeout=60,
        attempts=2,
    )
    obj = json.loads(raw.decode("utf-8"))
    token = str(obj.get("access_token", "")).strip()
    if not token:
        raise RuntimeError("CEDA Token API antwortete ohne access_token.")
    log("CEDA: Token über Benutzername/Passwort erzeugt.")
    return token


def dap_url(data_url: str) -> str:
    if data_url.startswith(DATA_ROOT):
        return DAP_ROOT + data_url[len(DATA_ROOT):]
    return data_url.replace(
        "https://data.ceda.ac.uk/",
        "https://dap.ceda.ac.uk/",
        1,
    )


def decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def parse_badc_csv(text: str) -> tuple[list[str], list[list[str]]]:
    lines = text.splitlines()
    data_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if line.strip().lower().rstrip(",") == "data":
            data_idx = i
            break
    if data_idx is None:
        raise RuntimeError("Kein BADC-CSV data-Marker gefunden.")

    for i in range(data_idx + 1, len(lines)):
        if lines[i].strip().lower().rstrip(",") == "end data":
            end_idx = i
            break
    if end_idx is None:
        end_idx = len(lines)

    if data_idx + 1 >= end_idx:
        return [], []

    refs = next(csv.reader([lines[data_idx + 1]]))
    rows = list(
        csv.reader(io.StringIO("\n".join(lines[data_idx + 2:end_idx])))
    )
    rows = [r for r in rows if any(str(x).strip() for x in r)]
    return [x.strip() for x in refs], rows


def parse_station_metadata(text: str) -> tuple[list[str], list[list[str]]]:
    if "Conventions,G,BADC-CSV" in text[:1000]:
        return parse_badc_csv(text)

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return [], []
    return [x.strip() for x in rows[0]], rows[1:]


def normalize_ref(value: str) -> str:
    return re.sub(
        r"[^a-z0-9]+", "_", str(value).strip().lower()
    ).strip("_")


def field_index(refs: list[str], *names: str) -> int | None:
    norm = {normalize_ref(v): i for i, v in enumerate(refs)}
    for name in names:
        key = normalize_ref(name)
        if key in norm:
            return norm[key]
    return None


def safe_value(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return str(row[idx]).strip()


def as_float(value: str) -> float | None:
    text = str(value).strip()
    if text in {"", "NA", "N/A", "-999", "-999.0"}:
        return None
    try:
        x = float(text)
    except ValueError:
        return None
    if not math.isfinite(x):
        return None
    return x


def parse_datetime(value: str) -> datetime | None:
    text = str(value).strip()
    if not text or text in {"NA", "N/A"}:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def empty_record() -> dict[str, Any]:
    return {
        "first_date": None,
        "last_date": None,
        "observation_days": 0,
        "tmax_days": 0,
        "tmin_days": 0,
        "tmax_abs": None,
        "tmin_abs": None,
        "calendar_tmax": {},
        "calendar_tmin": {},
        "provenance_days": {},
    }


def consume_day(
    rec: dict[str, Any],
    d: date,
    tmin: float | None,
    tmax: float | None,
    provenance_parts: list[str],
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

    for provenance in sorted(set(provenance_parts)):
        rec["provenance_days"][provenance] = (
            rec["provenance_days"].get(provenance, 0) + 1
        )

    if tmax is not None:
        rec["tmax_days"] += 1
        if rec["tmax_abs"] is None or tmax > float(rec["tmax_abs"][0]):
            rec["tmax_abs"] = [float(tmax), iso]
        old = rec["calendar_tmax"].get(mmdd)
        if old is None or tmax > float(old[0]):
            rec["calendar_tmax"][mmdd] = [float(tmax), iso]

    if tmin is not None:
        rec["tmin_days"] += 1
        if rec["tmin_abs"] is None or tmin < float(rec["tmin_abs"][0]):
            rec["tmin_abs"] = [float(tmin), iso]
        old = rec["calendar_tmin"].get(mmdd)
        if old is None or tmin < float(old[0]):
            rec["calendar_tmin"][mmdd] = [float(tmin), iso]

    return True


def plausible_tmax(value: float | None) -> bool:
    return value is not None and TMAX_FLOOR <= value <= TMAX_CEILING


def plausible_tmin(value: float | None) -> bool:
    return value is not None and TMIN_FLOOR <= value <= TMIN_CEILING


def metadata_inventory(token: str) -> dict[str, dict[str, Any]]:
    url = f"{DAP_ROOT}/{STATION_METADATA_NAME}"
    raw = request_bytes(url, token=token)
    refs, rows = parse_station_metadata(decode_text(raw))
    norm_refs = [normalize_ref(x) for x in refs]

    src_idx = field_index(refs, "src_id", "source_id")
    out: dict[str, dict[str, Any]] = {}

    for row in rows:
        src = safe_value(row, src_idx)
        if not src:
            continue
        try:
            key = str(int(float(src)))
        except ValueError:
            key = src.lstrip("0") or src

        obj: dict[str, Any] = {}
        for idx, ref in enumerate(norm_refs):
            if not ref:
                continue
            value = safe_value(row, idx)
            if value not in {"", "NA", "N/A"}:
                obj[ref] = value
        out[key] = obj

    return out


def parse_temperature_rows(
    raw: bytes,
    *,
    station_id_hint: str,
    qc_counts: dict[str, Counter],
    stats: Counter,
) -> dict[tuple[datetime, int], dict[str, Any]]:
    refs, rows = parse_badc_csv(decode_text(raw))

    idx_time = field_index(refs, "ob_end_time")
    idx_hours = field_index(refs, "ob_hour_count")
    idx_version = field_index(refs, "version_num")
    idx_src = field_index(refs, "src_id")
    idx_tmax = field_index(refs, "max_air_temp")
    idx_tmin = field_index(refs, "min_air_temp")
    idx_tmax_q = field_index(refs, "max_air_temp_q")
    idx_tmin_q = field_index(refs, "min_air_temp_q")
    idx_stamp = field_index(refs, "meto_stmp_time")

    required = {
        "ob_end_time": idx_time,
        "ob_hour_count": idx_hours,
        "version_num": idx_version,
        "src_id": idx_src,
        "max_air_temp": idx_tmax,
        "min_air_temp": idx_tmin,
    }
    missing = [k for k, v in required.items() if v is None]
    if missing:
        raise RuntimeError(f"MIDAS-Spalten fehlen: {missing}")

    intervals: dict[tuple[datetime, int], dict[str, Any]] = {}

    for row in rows:
        stats["raw_rows"] += 1

        version = safe_value(row, idx_version)
        if version != "1":
            stats["rejected_version_not_1"] += 1
            continue

        src = safe_value(row, idx_src)
        if src == COMMISSIONING_SRC_ID:
            stats["rejected_commissioning"] += 1
            continue

        end = parse_datetime(safe_value(row, idx_time))
        if end is None:
            stats["rejected_bad_time"] += 1
            continue

        try:
            hours = int(float(safe_value(row, idx_hours)))
        except ValueError:
            stats["rejected_bad_hours"] += 1
            continue

        if hours not in {12, 24}:
            stats["ignored_non_12_24_hour_rows"] += 1
            continue

        tmax = as_float(safe_value(row, idx_tmax))
        tmin = as_float(safe_value(row, idx_tmin))

        qmax = safe_value(row, idx_tmax_q) or "<leer>"
        qmin = safe_value(row, idx_tmin_q) or "<leer>"
        qc_counts["tmax"][qmax] += 1
        qc_counts["tmin"][qmin] += 1

        if tmax is not None and not plausible_tmax(tmax):
            stats["qc_rejected_tmax_plausibility"] += 1
            tmax = None
        if tmin is not None and not plausible_tmin(tmin):
            stats["qc_rejected_tmin_plausibility"] += 1
            tmin = None

        if tmax is None and tmin is None:
            continue

        stamp = parse_datetime(safe_value(row, idx_stamp))
        key = (end, hours)

        candidate = {
            "tmax": tmax,
            "tmin": tmin,
            "stamp": stamp,
            "src_id": src or station_id_hint,
            "qmax": qmax,
            "qmin": qmin,
        }

        old = intervals.get(key)
        if old is None:
            intervals[key] = candidate
        else:
            # CEDA says duplicate entries should be resolved using the newest
            # Met Office receipt stamp.
            old_stamp = old.get("stamp")
            if old_stamp is None or (stamp is not None and stamp > old_stamp):
                intervals[key] = candidate
                stats["duplicate_rows_replaced_by_newer_stamp"] += 1
            else:
                stats["duplicate_rows_older_ignored"] += 1

    return intervals


def reconstruct_daily(
    intervals: dict[tuple[datetime, int], dict[str, Any]],
    cutoff_year: int,
    stats: Counter,
) -> dict[date, dict[str, Any]]:
    daily: dict[date, dict[str, Any]] = {}

    def slot(d: date) -> dict[str, Any]:
        return daily.setdefault(
            d,
            {
                "tmax": None,
                "tmin": None,
                "tmax_prov": None,
                "tmin_prov": None,
            },
        )

    # 1) Complete 24h rows ending at 09 UTC.
    #    TMAX is attributed to the preceding climate day.
    #    TMIN is attributed to the end-date climate day.
    for (end, hours), row in intervals.items():
        if hours != 24 or end.hour != 9:
            continue

        if row.get("tmax") is not None:
            dmax = end.date() - timedelta(days=1)
            if dmax.year <= cutoff_year:
                s = slot(dmax)
                s["tmax"] = float(row["tmax"])
                s["tmax_prov"] = "MIDAS_24H_09Z"
                stats["daily_tmax_from_24h"] += 1

        if row.get("tmin") is not None:
            dmin = end.date()
            if dmin.year <= cutoff_year:
                s = slot(dmin)
                s["tmin"] = float(row["tmin"])
                s["tmin_prov"] = "MIDAS_24H_09Z"
                stats["daily_tmin_from_24h"] += 1

    # 2) Combine 09-21 + 21-09 rows when there is no complete 24h element.
    #    For pair [D 09 -> D 21] and [D 21 -> D+1 09]:
    #      TMAX belongs to D.
    #      TMIN belongs to D+1.
    ends_09 = sorted(
        end for (end, hours) in intervals
        if hours == 12 and end.hour == 9
    )

    for end09 in ends_09:
        end21 = end09 - timedelta(hours=12)
        morning = intervals.get((end09, 12))
        evening = intervals.get((end21, 12))
        if morning is None or evening is None:
            stats["incomplete_12h_pairs"] += 1
            continue

        dmax = end21.date()
        dmin = end09.date()

        # Require both halves for the element. A single 12h maximum/minimum
        # must never be compared with official daily 24h records.
        if (
            dmax.year <= cutoff_year
            and slot(dmax)["tmax"] is None
            and evening.get("tmax") is not None
            and morning.get("tmax") is not None
        ):
            slot(dmax)["tmax"] = max(
                float(evening["tmax"]), float(morning["tmax"])
            )
            slot(dmax)["tmax_prov"] = "MIDAS_12H_PAIR_09_21_09"
            stats["daily_tmax_from_12h_pair"] += 1

        if (
            dmin.year <= cutoff_year
            and slot(dmin)["tmin"] is None
            and evening.get("tmin") is not None
            and morning.get("tmin") is not None
        ):
            slot(dmin)["tmin"] = min(
                float(evening["tmin"]), float(morning["tmin"])
            )
            slot(dmin)["tmin_prov"] = "MIDAS_12H_PAIR_09_21_09"
            stats["daily_tmin_from_12h_pair"] += 1

    # Final consistency check. Note that UK TMAX/TMIN for the same labelled
    # date cover different 24h windows by Met Office convention; Tmin <= Tmax
    # is therefore not a logically required relation for every labelled date.
    cleaned: dict[date, dict[str, Any]] = {}
    for d, vals in daily.items():
        if vals["tmax"] is None and vals["tmin"] is None:
            continue
        cleaned[d] = vals

    return cleaned


def merge_intervals(
    target: dict[tuple[datetime, int], dict[str, Any]],
    incoming: dict[tuple[datetime, int], dict[str, Any]],
    stats: Counter,
) -> None:
    for key, row in incoming.items():
        old = target.get(key)
        if old is None:
            target[key] = row
            continue

        old_stamp = old.get("stamp")
        new_stamp = row.get("stamp")
        if old_stamp is None or (
            new_stamp is not None and new_stamp > old_stamp
        ):
            target[key] = row
            stats["cross_file_duplicate_replaced"] += 1
        else:
            stats["cross_file_duplicate_ignored"] += 1


def process_station(
    st: StationDir,
    cutoff_year: int,
    token: str,
    metadata_by_src: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    files = station_year_files(st, cutoff_year)
    if not files:
        return (
            st.dirname,
            {},
            {},
            {
                "files_found": 0,
                "files_processed": 0,
                "years_first": None,
                "years_last": None,
                "stats": {},
                "q_tmax": {},
                "q_tmin": {},
            },
        )

    intervals: dict[tuple[datetime, int], dict[str, Any]] = {}
    stats: Counter = Counter()
    qc_counts = {"tmax": Counter(), "tmin": Counter()}

    for year, url in files:
        raw = request_bytes(dap_url(url), token=token)
        parsed = parse_temperature_rows(
            raw,
            station_id_hint=st.station_id,
            qc_counts=qc_counts,
            stats=stats,
        )
        merge_intervals(intervals, parsed, stats)
        stats["files_processed"] += 1
        stats["download_bytes"] += len(raw)

    daily = reconstruct_daily(intervals, cutoff_year, stats)
    rec = empty_record()

    for d in sorted(daily):
        vals = daily[d]
        provenance = [
            p
            for p in (vals.get("tmin_prov"), vals.get("tmax_prov"))
            if p
        ]
        consume_day(
            rec,
            d,
            vals.get("tmin"),
            vals.get("tmax"),
            provenance,
        )

    try:
        src_key = str(int(st.station_id))
    except ValueError:
        src_key = st.station_id.lstrip("0") or st.station_id

    meta = {
        "station_id": st.station_id,
        "src_id": src_key,
        "name": st.name,
        "county": st.county,
        "dirname": st.dirname,
        "dataset_metadata": metadata_by_src.get(src_key, {}),
    }

    detail = {
        "files_found": len(files),
        "files_processed": int(stats.get("files_processed", 0)),
        "years_first": files[0][0] if files else None,
        "years_last": files[-1][0] if files else None,
        "stats": dict(stats),
        "q_tmax": dict(qc_counts["tmax"]),
        "q_tmin": dict(qc_counts["tmin"]),
    }

    return st.dirname, rec, meta, detail


def fresh_progress(cutoff_year: int) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "country": COUNTRY,
        "country_code": COUNTRY_CODE,
        "dataset_version": DATASET_VERSION,
        "cutoff_year": cutoff_year,
        "complete": False,
        "inventory": {},
        "records": {},
        "station_details": {},
        "processed_station_dirs": [],
        "failed_station_dirs": {},
        "stats": {},
        "q_tmax": {},
        "q_tmin": {},
        "started_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
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
        and len(obj.get("records", {})) > 0
    )


def write_status(cache_dir: Path, cutoff_year: int, payload: dict[str, Any]) -> None:
    hottest = None
    coldest = None
    for sid, rec in payload.get("records", {}).items():
        tx = rec.get("tmax_abs")
        tn = rec.get("tmin_abs")
        if tx is not None and (
            hottest is None or float(tx[0]) > float(hottest["value"])
        ):
            hottest = {
                "station": sid,
                "value": float(tx[0]),
                "date": tx[1],
            }
        if tn is not None and (
            coldest is None or float(tn[0]) < float(coldest["value"])
        ):
            coldest = {
                "station": sid,
                "value": float(tn[0]),
                "date": tn[1],
            }

    status = {
        "format_version": payload.get("format_version"),
        "source": payload.get("source"),
        "dataset_version": payload.get("dataset_version"),
        "cutoff_year": payload.get("cutoff_year"),
        "complete": payload.get("complete"),
        "inventory_count": len(payload.get("inventory", {})),
        "station_count": len(payload.get("records", {})),
        "processed_station_count": len(
            payload.get("processed_station_dirs", [])
        ),
        "first_date": payload.get("first_date"),
        "last_date": payload.get("last_date"),
        "observation_days": payload.get("observation_days"),
        "tmax_days": payload.get("tmax_days"),
        "tmin_days": payload.get("tmin_days"),
        "stats": payload.get("stats", {}),
        "q_tmax": payload.get("q_tmax", {}),
        "q_tmin": payload.get("q_tmin", {}),
        "hottest": hottest,
        "coldest": coldest,
        "quality_note": payload.get("quality_note"),
    }
    atomic_json(status_path(cache_dir, cutoff_year), status)


def build_baseline(
    cache_dir: Path,
    cutoff_year: int,
    *,
    force: bool,
    workers: int,
    max_runtime_minutes: float,
) -> Path:
    final = baseline_path(cache_dir, cutoff_year)
    prog_file = progress_path(cache_dir, cutoff_year)

    if not force and valid_final(final, cutoff_year):
        log(f"Verwende vorhandene vollständige UK-Baseline: {final}")
        return final

    cache_dir.mkdir(parents=True, exist_ok=True)

    if force:
        final.unlink(missing_ok=True)
        prog_file.unlink(missing_ok=True)

    if prog_file.exists() and not force:
        progress = load_pickle_gzip(prog_file)
        if not isinstance(progress, dict):
            progress = fresh_progress(cutoff_year)
        log(
            "Setze UK-Zwischenstand fort: "
            f"{len(progress.get('processed_station_dirs', [])):,} Stationen fertig."
        )
    else:
        progress = fresh_progress(cutoff_year)

    token = get_ceda_token()
    started = time.monotonic()

    log()
    log("=== MET OFFICE UK MIDAS HISTORICAL BASELINE ===")
    log(f"Dataset: v{DATASET_VERSION}")
    log(f"Cutoff: {cutoff_year}-12-31")
    log("Tagesdefinition: Met Office 09-09 UTC")
    log("QC-Ebene: qc-version-1 / version_num=1")
    log("Commissioning src_id=99999: ausgeschlossen")
    log()

    stations = enumerate_public_inventory()
    metadata_by_src = metadata_inventory(token)

    # Preserve public inventory immediately.
    progress["inventory"] = {
        st.dirname: {
            "station_id": st.station_id,
            "name": st.name,
            "county": st.county,
            "dirname": st.dirname,
        }
        for st in stations
    }

    done = set(progress.get("processed_station_dirs", []))
    pending = [st for st in stations if st.dirname not in done]

    log(f"Stationsverzeichnisse gesamt: {len(stations):,}")
    log(f"Bereits abgeschlossen: {len(done):,}")
    log(f"Noch offen: {len(pending):,}")

    workers = max(1, min(int(workers), 20))
    global_stats = Counter(progress.get("stats", {}))
    global_qmax = Counter(progress.get("q_tmax", {}))
    global_qmin = Counter(progress.get("q_tmin", {}))
    failures: dict[str, str] = dict(progress.get("failed_station_dirs", {}))

    completed_this_run = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                process_station,
                st,
                cutoff_year,
                token,
                metadata_by_src,
            ): st
            for st in pending
        }

        for fut in as_completed(futures):
            st = futures[fut]

            try:
                station_key, rec, meta, detail = fut.result()

                # If this station failed in an earlier run, clear that old error.
                failures.pop(station_key, None)

                if rec.get("tmax_abs") is not None or rec.get("tmin_abs") is not None:
                    progress["records"][station_key] = rec
                    progress["station_details"][station_key] = meta

                for k, v in detail.get("stats", {}).items():
                    global_stats[k] += int(v)
                global_stats["station_files_found"] += int(
                    detail.get("files_found", 0)
                )
                global_stats["stations_without_year_files"] += int(
                    detail.get("files_found", 0) == 0
                )

                global_qmax.update(detail.get("q_tmax", {}))
                global_qmin.update(detail.get("q_tmin", {}))

                progress["processed_station_dirs"].append(station_key)
                done.add(station_key)
                completed_this_run += 1

            except Exception as exc:
                failures[st.dirname] = str(exc)

            processed_total = len(done)
            if (
                completed_this_run % 20 == 0
                or processed_total == len(stations)
            ):
                progress["stats"] = dict(global_stats)
                progress["q_tmax"] = dict(global_qmax)
                progress["q_tmin"] = dict(global_qmin)
                progress["failed_station_dirs"] = failures
                atomic_pickle_gzip(prog_file, progress)

                log(
                    f"Fortschritt: {processed_total:,}/{len(stations):,} Stationen | "
                    f"Temperaturreihen {len(progress['records']):,} | "
                    f"Fehler {len(failures):,} | "
                    f"Jahresdateien {global_stats.get('files_processed', 0):,}"
                )

            elapsed_min = (time.monotonic() - started) / 60.0
            if elapsed_min >= max_runtime_minutes:
                progress["stats"] = dict(global_stats)
                progress["q_tmax"] = dict(global_qmax)
                progress["q_tmin"] = dict(global_qmin)
                progress["failed_station_dirs"] = failures
                atomic_pickle_gzip(prog_file, progress)
                raise RuntimeError(
                    "UK-MIDAS-Laufzeitgrenze erreicht; Zwischenstand gespeichert. "
                    "Workflow erneut mit force=false starten."
                )

    progress["stats"] = dict(global_stats)
    progress["q_tmax"] = dict(global_qmax)
    progress["q_tmin"] = dict(global_qmin)
    progress["failed_station_dirs"] = failures

    if failures:
        atomic_pickle_gzip(prog_file, progress)
        sample = "; ".join(
            f"{k}: {v[:160]}" for k, v in list(failures.items())[:8]
        )
        raise RuntimeError(
            f"{len(failures)} UK-Stationen konnten nicht vollständig verarbeitet "
            f"werden. Erfolgreiche Stationen sind im Fortschrittscache gespeichert. "
            f"Workflow erneut mit force=false starten. Beispiele: {sample}"
        )

    # Remove any accidental empty record.
    progress["records"] = {
        sid: rec
        for sid, rec in progress["records"].items()
        if rec.get("tmax_abs") is not None or rec.get("tmin_abs") is not None
    }

    if not progress["records"]:
        raise RuntimeError("UK-Baseline enthält keine Temperaturreihen.")

    firsts = [
        rec["first_date"]
        for rec in progress["records"].values()
        if rec.get("first_date")
    ]
    lasts = [
        rec["last_date"]
        for rec in progress["records"].values()
        if rec.get("last_date")
    ]

    progress["first_date"] = min(firsts) if firsts else None
    progress["last_date"] = max(lasts) if lasts else None
    progress["observation_days"] = sum(
        int(rec.get("observation_days", 0))
        for rec in progress["records"].values()
    )
    progress["tmax_days"] = sum(
        int(rec.get("tmax_days", 0))
        for rec in progress["records"].values()
    )
    progress["tmin_days"] = sum(
        int(rec.get("tmin_days", 0))
        for rec in progress["records"].values()
    )

    progress["complete"] = True
    progress["completed_at_utc"] = (
        datetime.utcnow().isoformat(timespec="seconds") + "Z"
    )

    progress["parameters"] = {
        "TMAX": "max_air_temp",
        "TMIN": "min_air_temp",
    }
    progress["public_url"] = PUBLIC_URL
    progress["data_root"] = DATA_ROOT
    progress["quality_note"] = (
        "Met Office MIDAS Open daily temperature dataset v202607. "
        "Only qc-version-1/version_num=1 is used. CEDA documents version 1 "
        "as the row to use after Met Office quality processing. src_id=99999 "
        "commissioning-trial rows are excluded. The _q values are retained "
        "as distributions rather than interpreted as simple good/bad flags. "
        "Official daily TMAX/TMIN are reconstructed on the Met Office 09-09 UTC "
        "climate-day convention: complete 24h rows ending 09 UTC are preferred; "
        "otherwise both 12h halves (09-21 and 21-09) are required. A single "
        "12h row is never used as a daily record."
    )

    atomic_pickle_gzip(final, progress)
    write_status(cache_dir, cutoff_year, progress)
    prog_file.unlink(missing_ok=True)

    log()
    log("=== MET OFFICE UK BASELINE SUMMARY ===")
    log(f"Stationsinventar: {len(progress['inventory']):,}")
    log(f"Stationsreihen mit Temperatur: {len(progress['records']):,}")
    log(f"Stations-/Tage: {progress['observation_days']:,}")
    log(f"TMAX-Tage: {progress['tmax_days']:,}")
    log(f"TMIN-Tage: {progress['tmin_days']:,}")
    log(f"Datenzeitraum: {progress['first_date']} bis {progress['last_date']}")
    log(
        "TMAX Rekonstruktion: "
        f"24h={global_stats.get('daily_tmax_from_24h', 0):,} | "
        f"12h-Paare={global_stats.get('daily_tmax_from_12h_pair', 0):,}"
    )
    log(
        "TMIN Rekonstruktion: "
        f"24h={global_stats.get('daily_tmin_from_24h', 0):,} | "
        f"12h-Paare={global_stats.get('daily_tmin_from_12h_pair', 0):,}"
    )
    log(
        "QC Plausibilität verworfen: "
        f"TMAX={global_stats.get('qc_rejected_tmax_plausibility', 0):,} | "
        f"TMIN={global_stats.get('qc_rejected_tmin_plausibility', 0):,}"
    )
    log("TMAX _q Codes:", dict(global_qmax.most_common()))
    log("TMIN _q Codes:", dict(global_qmin.most_common()))
    log(f"Output: {final}")
    log("Met Office UK historische Baseline vollständig OK.")

    return final


def self_test() -> None:
    # Direct 24h row ending Jan 2 09:
    # Tmax is climate day Jan 1, Tmin is climate day Jan 2.
    i24 = {
        (datetime(2025, 1, 2, 9), 24): {
            "tmax": 12.3,
            "tmin": 1.2,
        }
    }
    stats = Counter()
    d = reconstruct_daily(i24, 2025, stats)
    assert d[date(2025, 1, 1)]["tmax"] == 12.3
    assert d[date(2025, 1, 2)]["tmin"] == 1.2

    # Two 12h halves: Jan 1 09-21 and Jan 1 21-Jan 2 09.
    i12 = {
        (datetime(2025, 1, 1, 21), 12): {
            "tmax": 14.0,
            "tmin": 4.0,
        },
        (datetime(2025, 1, 2, 9), 12): {
            "tmax": 8.0,
            "tmin": -1.0,
        },
    }
    stats = Counter()
    d = reconstruct_daily(i12, 2025, stats)
    assert d[date(2025, 1, 1)]["tmax"] == 14.0
    assert d[date(2025, 1, 2)]["tmin"] == -1.0

    # A lone 12h row must not generate a daily record.
    lone = {
        (datetime(2025, 1, 1, 21), 12): {
            "tmax": 15.0,
            "tmin": 3.0,
        }
    }
    assert reconstruct_daily(lone, 2025, Counter()) == {}

    # 24h wins over paired 12h for the same element/date.
    mixed = dict(i12)
    mixed[(datetime(2025, 1, 2, 9), 24)] = {
        "tmax": 13.7,
        "tmin": -0.8,
    }
    d = reconstruct_daily(mixed, 2025, Counter())
    assert d[date(2025, 1, 1)]["tmax"] == 13.7
    assert d[date(2025, 1, 2)]["tmin"] == -0.8

    # Compact-record extrema.
    rec = empty_record()
    consume_day(
        rec,
        date(2025, 7, 19),
        18.0,
        40.3,
        ["TEST"],
    )
    consume_day(
        rec,
        date(2025, 7, 20),
        17.2,
        38.0,
        ["TEST"],
    )
    assert rec["tmax_abs"] == [40.3, "2025-07-19"]
    assert rec["tmin_abs"] == [17.2, "2025-07-20"]

    print("Met Office UK historical cache self-test OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR_DEFAULT))
    parser.add_argument("--cutoff-year", type=int, default=2025)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--max-runtime-minutes", type=float, default=280.0)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    build_baseline(
        Path(args.cache_dir),
        args.cutoff_year,
        force=args.force,
        workers=args.workers,
        max_runtime_minutes=args.max_runtime_minutes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
