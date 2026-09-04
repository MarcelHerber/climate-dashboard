from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime
from typing import Any


def is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def non_leap_index(day: date) -> int | None:
    if day.month == 2 and day.day == 29:
        return None
    index = day.timetuple().tm_yday - 1
    if day.month > 2 and is_leap(day.year):
        index -= 1
    return index


def _threshold_key(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _record(days: list[date], *, earliest: bool) -> dict[str, Any] | None:
    if not days:
        return None
    target = min(days, key=lambda d: (d.month, d.day)) if earliest else max(days, key=lambda d: (d.month, d.day))
    month_day = target.strftime('%m-%d')
    years = sorted({day.year for day in days if day.strftime('%m-%d') == month_day})
    return {'month_day': month_day, 'years': years}


def _frequency_block(
    values_by_day: dict[date, float | None],
    thresholds: tuple[float, ...],
    *,
    snow: bool,
) -> dict[str, Any]:
    valid_years = [0] * 365
    counts = {_threshold_key(threshold): [0] * 365 for threshold in thresholds}
    event_days: dict[str, list[date]] = {_threshold_key(threshold): [] for threshold in thresholds}

    for day, raw_value in values_by_day.items():
        if raw_value is None:
            continue
        value = float(raw_value)
        index = non_leap_index(day)
        if index is not None:
            valid_years[index] += 1
        for threshold in thresholds:
            key = _threshold_key(threshold)
            if value >= threshold:
                event_days[key].append(day)
                if index is not None:
                    counts[key][index] += 1

    percent: dict[str, list[float | None]] = {}
    for threshold in thresholds:
        key = _threshold_key(threshold)
        series: list[float | None] = []
        for index, valid in enumerate(valid_years):
            series.append(round(counts[key][index] * 100.0 / valid, 1) if valid else None)
        percent[key] = series

    records: dict[str, dict[str, Any]] = {}
    for threshold in thresholds:
        key = _threshold_key(threshold)
        days = event_days[key]
        if snow:
            second_half = [day for day in days if day.month >= 7]
            first_half = [day for day in days if day.month <= 6]
            records[key] = {
                'earliest_second_half': _record(second_half, earliest=True),
                'latest_first_half': _record(first_half, earliest=False),
            }
        else:
            records[key] = {
                'earliest': _record(days, earliest=True),
                'latest': _record(days, earliest=False),
            }

    return {
        'thresholds': [float(threshold) for threshold in thresholds],
        'valid_years': valid_years,
        'counts': counts,
        'percent': percent,
        'records': records,
    }


def build_calendar_frequency_payload(
    tx_by_day: dict[date, float | None],
    snow_by_day: dict[date, float | None],
) -> dict[str, Any]:
    temperature = _frequency_block(tx_by_day, (25.0, 30.0, 35.0), snow=False)
    temperature.update({
        'field': 'TXK',
        'unit': '°C',
        'definition': 'Häufigkeit eines Tagesmaximums ab dem jeweiligen Schwellenwert.',
    })
    snow = _frequency_block(snow_by_day, (1.0, 5.0, 10.0), snow=True)
    snow.update({
        'field': 'SHK_TAG',
        'unit': 'cm',
        'definition': 'Häufigkeit einer gemessenen Schneehöhe ab dem jeweiligen Schwellenwert.',
    })
    return {
        'encoding': 'non_leap_day_indices_v1',
        'temperature': temperature,
        'snow': snow,
    }


def parse_snow_heights_from_kl_zip(
    content: bytes,
    start_date: date,
    end_date: date,
) -> dict[date, float]:
    result: dict[date, float] = {}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        product_files: list[str] = []
        for name in archive.namelist():
            if not name.lower().endswith('.txt'):
                continue
            try:
                with archive.open(name) as candidate:
                    first_line = candidate.readline().decode('latin-1', errors='replace')
                columns = {part.strip() for part in first_line.split(';')}
                if {'MESS_DATUM', 'SHK_TAG'}.issubset(columns):
                    product_files.append(name)
                    if 'produkt_klima_tag' in name.lower():
                        break
            except (KeyError, OSError):
                continue
        if not product_files:
            return result

        with archive.open(product_files[0]) as raw:
            text = io.TextIOWrapper(raw, encoding='latin-1', newline='')
            reader = csv.reader(text, delimiter=';')
            header = [column.strip() for column in next(reader)]
            date_index = header.index('MESS_DATUM')
            snow_index = header.index('SHK_TAG')
            maximum_index = max(date_index, snow_index)
            for row in reader:
                if len(row) <= maximum_index:
                    continue
                try:
                    day = datetime.strptime(row[date_index].strip(), '%Y%m%d').date()
                except ValueError:
                    continue
                if day < start_date or day > end_date:
                    continue
                try:
                    value = float(row[snow_index].strip().replace(',', '.'))
                except ValueError:
                    continue
                if value <= -900 or value < 0 or value > 2000:
                    continue
                result[day] = round(value, 1)
    return result
