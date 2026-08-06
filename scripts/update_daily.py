from __future__ import annotations

import csv
import io
import re
import statistics
import threading
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import requests

from dwd_common import USER_AGENT, atomic_write_json, download, read_json

RECENT_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl/recent/"
)
FILE_PATTERN = re.compile(r'href=["\'](tageswerte_KL_\d+_akt\.zip)["\']')
_thread_local = threading.local()


class NoUsableProductFileError(ValueError):
    """The archive is valid, but contains no usable daily climate product."""


def thread_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        _thread_local.session = session
    return session


def download_station_zip(filename: str, attempts: int = 5) -> bytes:
    url = RECENT_URL + filename
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = thread_session().get(url, timeout=60)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts:
                import time

                time.sleep(min(2 ** (attempt - 1), 12))
    raise RuntimeError(f"{filename}: {last_error}")


def list_station_files() -> list[str]:
    html = download(RECENT_URL).decode("utf-8", errors="replace")
    files = sorted(set(FILE_PATTERN.findall(html)))
    if len(files) < 300:
        raise RuntimeError(
            f"Im DWD-Verzeichnis wurden nur {len(files)} Stationsdateien gefunden."
        )
    return files


def parse_station_zip(
    content: bytes, start_date: date
) -> list[Tuple[date, float, str]]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        product_files = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".txt") and "produkt_klima_tag" in name.lower()
        ]

        # Some DWD archives can temporarily contain only metadata or use an
        # unexpected file name. In that case, look for any TXT file whose
        # header contains the required daily-climate columns.
        if not product_files:
            required_columns = {"STATIONS_ID", "MESS_DATUM", "TXK"}
            for name in archive.namelist():
                if not name.lower().endswith(".txt"):
                    continue
                try:
                    with archive.open(name) as candidate:
                        first_line = candidate.readline().decode(
                            "latin-1", errors="replace"
                        )
                    columns = {part.strip() for part in first_line.split(";")}
                    if required_columns.issubset(columns):
                        product_files.append(name)
                except (KeyError, OSError):
                    continue

        if not product_files:
            raise NoUsableProductFileError(
                "ZIP-Datei enthält keine auswertbare Tagesklima-Produktdatei."
            )

        with archive.open(product_files[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
            reader = csv.reader(text, delimiter=";")
            header = [column.strip() for column in next(reader)]
            try:
                station_index = header.index("STATIONS_ID")
                date_index = header.index("MESS_DATUM")
                tmax_index = header.index("TXK")
            except ValueError as exc:
                raise ValueError("Benötigte Spalten STATIONS_ID/MESS_DATUM/TXK fehlen.") from exc

            records: list[Tuple[date, float, str]] = []
            for row in reader:
                if len(row) <= max(station_index, date_index, tmax_index):
                    continue
                date_text = row[date_index].strip()
                value_text = row[tmax_index].strip().replace(",", ".")
                try:
                    measurement_date = datetime.strptime(date_text, "%Y%m%d").date()
                    value = float(value_text)
                except ValueError:
                    continue
                if measurement_date < start_date:
                    continue
                if not (-60.0 <= value <= 60.0):
                    continue
                station_id = row[station_index].strip().zfill(5)
                records.append((measurement_date, round(value, 1), station_id))
            return records


def climate_means_from_existing(existing: list[dict]) -> dict[str, float]:
    preserved: dict[str, set[float]] = defaultdict(set)
    for item in existing:
        value = item.get("climate_mean")
        if value is not None:
            preserved[item["date"][5:]].add(float(value))

    climate_means: dict[str, float] = {}
    for month_day, values in preserved.items():
        if len(values) == 1:
            climate_means[month_day] = next(iter(values))

    # Fallback/revalidation from the unchanged 1991-2020 series.
    normals: dict[str, list[float]] = defaultdict(list)
    for item in existing:
        year = int(item["date"][:4])
        if 1991 <= year <= 2020 and item.get("tmax") is not None:
            normals[item["date"][5:]].append(float(item["tmax"]))

    for month_day, values in normals.items():
        if month_day not in climate_means:
            climate_means[month_day] = sum(values) / len(values)

    if len(climate_means) < 365:
        raise RuntimeError("Klimamittel 1991-2020 konnten nicht vollständig bestimmt werden.")
    return climate_means


def update_daily(root: Path, max_workers: int = 8) -> dict:
    target = root / "daily_tmax_1881_2026.json"
    existing = read_json(target)
    if not isinstance(existing, list) or not existing:
        raise ValueError("daily_tmax_1881_2026.json ist leer oder kein JSON-Array.")

    existing_by_date = {date.fromisoformat(item["date"]): item for item in existing}
    if len(existing_by_date) != len(existing):
        raise RuntimeError("Die tägliche JSON-Datei enthält doppelte Datumswerte.")

    old_latest = max(existing_by_date)
    # DWD 'recent' normally covers well over one year. This overlap also captures corrections.
    start_date = min(old_latest - timedelta(days=550), date(date.today().year - 1, 1, 1))

    station_files = list_station_files()
    print(f"Tagesdaten: {len(station_files)} DWD-Stationsdateien")

    maxima: Dict[date, Tuple[float, str]] = {}
    counts: Dict[date, int] = defaultdict(int)
    failures: list[str] = []
    skipped_without_product: list[str] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_station_zip, filename): filename
            for filename in station_files
        }
        for number, future in enumerate(as_completed(futures), start=1):
            filename = futures[future]
            try:
                content = future.result()
                rows = parse_station_zip(content, start_date)
                for measurement_date, value, station_id in rows:
                    if measurement_date > date.today():
                        continue
                    counts[measurement_date] += 1
                    previous = maxima.get(measurement_date)
                    if previous is None or value > previous[0] or (
                        value == previous[0] and station_id < previous[1]
                    ):
                        maxima[measurement_date] = (value, station_id)
            except NoUsableProductFileError as exc:
                # A valid ZIP without a daily product contributes no TXK values.
                # Skipping it is safe because completeness is checked again below
                # using the number of reporting stations per day.
                skipped_without_product.append(f"{filename}: {exc}")
            except Exception as exc:  # noqa: BLE001 - unexpected failures remain fatal
                failures.append(f"{filename}: {exc}")
            if number % 50 == 0 or number == len(station_files):
                print(f"  verarbeitet: {number}/{len(station_files)}")

    if skipped_without_product:
        print(
            f"Warnung: {len(skipped_without_product)} Stationsdatei(en) ohne "
            "auswertbare Produktdatei wurden übersprungen:"
        )
        for message in skipped_without_product[:10]:
            print(f"  - {message}")

    successful_station_files = (
        len(station_files) - len(failures) - len(skipped_without_product)
    )
    if successful_station_files < 300:
        raise RuntimeError(
            f"Nur {successful_station_files} Stationsdateien konnten ausgewertet werden."
        )

    if failures:
        preview = "\n".join(failures[:10])
        raise RuntimeError(
            f"{len(failures)} Stationsdateien konnten nicht verarbeitet werden. "
            f"Aus Sicherheitsgründen wird nichts gespeichert.\n{preview}"
        )
    if not counts:
        raise RuntimeError("Keine gültigen TXK-Werte aus den DWD-Dateien gelesen.")

    all_dates = sorted(counts)
    newest_raw_date = max(all_dates)
    reference_dates = [
        day
        for day in all_dates
        if newest_raw_date - timedelta(days=60)
        <= day
        <= newest_raw_date - timedelta(days=2)
    ]
    if len(reference_dates) < 20:
        reference_dates = all_dates[-60:-2]
    reference_count = statistics.median(counts[day] for day in reference_dates)
    minimum_station_count = max(100, int(reference_count * 0.65))

    accepted = {
        day: maxima[day]
        for day in all_dates
        if counts[day] >= minimum_station_count and day <= date.today()
    }
    if not accepted:
        raise RuntimeError(
            f"Kein Tag erreicht die Mindestzahl von {minimum_station_count} Stationen."
        )

    earliest_accepted = min(accepted)
    if old_latest + timedelta(days=1) < earliest_accepted:
        raise RuntimeError(
            "Zwischen vorhandener Datei und DWD-Recent-Daten besteht eine Lücke. "
            "Für eine Reparatur müssten historische Stationsdateien eingelesen werden."
        )

    climate_means = climate_means_from_existing(existing)

    # Correct overlapping recent dates first.
    changed_overlap = 0
    for day, (value, _station_id) in accepted.items():
        if day in existing_by_date:
            old_value = float(existing_by_date[day]["tmax"])
            if old_value != value:
                existing_by_date[day]["tmax"] = value
                changed_overlap += 1

    # Only extend through a continuous block after the old endpoint.
    cursor = old_latest + timedelta(days=1)
    added = 0
    while cursor in accepted:
        value, _station_id = accepted[cursor]
        month_day = cursor.strftime("%m-%d")
        if month_day not in climate_means:
            raise RuntimeError(f"Klimamittel fehlt für {month_day}.")
        existing_by_date[cursor] = {
            "date": cursor.isoformat(),
            "tmax": value,
            "climate_mean": climate_means[month_day],
        }
        added += 1
        cursor += timedelta(days=1)

    latest = max(existing_by_date)
    later_accepted = [day for day in accepted if day > latest]
    if later_accepted:
        print(
            "Hinweis: Nach dem letzten zusammenhängenden Tag liegen weitere DWD-Tage vor; "
            "sie werden wegen einer Datenlücke noch nicht übernommen."
        )

    updated = [existing_by_date[day] for day in sorted(existing_by_date)]

    # Structural checks: unique, chronological and gap-free.
    previous: Optional[date] = None
    for item in updated:
        current = date.fromisoformat(item["date"])
        if previous is not None and current != previous + timedelta(days=1):
            raise RuntimeError(f"Datumsfolge ist zwischen {previous} und {current} unterbrochen.")
        value = float(item["tmax"])
        if not (-60.0 <= value <= 60.0):
            raise RuntimeError(f"Unplausibler Tmax-Wert am {current}: {value}")
        previous = current

    if len(updated) < len(existing):
        raise RuntimeError("Die aktualisierte tägliche Datei wäre kürzer als die vorhandene.")

    atomic_write_json(target, updated)

    if latest in accepted:
        latest_value, latest_station = accepted[latest]
        latest_station_count = counts[latest]
    else:
        latest_value = float(existing_by_date[latest]["tmax"])
        latest_station = None
        latest_station_count = counts.get(latest)

    return {
        "records": len(updated),
        "latest_date": latest.isoformat(),
        "latest_tmax": latest_value,
        "latest_max_station_id": latest_station,
        "latest_station_count": latest_station_count,
        "minimum_station_count": minimum_station_count,
        "reference_station_count": reference_count,
        "downloaded_station_files": len(station_files),
        "processed_station_files": successful_station_files,
        "skipped_station_files_without_product": len(skipped_without_product),
        "added_days": added,
        "corrected_days": changed_overlap,
        "newest_raw_dwd_date": newest_raw_date.isoformat(),
    }
