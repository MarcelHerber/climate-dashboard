from __future__ import annotations

import calendar
from datetime import date

import numpy as np

from era5_running_temperature_rank import (
    PRODUCTS,
    combine_season_to_date,
    combine_year_to_date,
    extract_day_and_mtd,
)


def month_target_dates(year: int, month: int, end_day: int | None = None) -> list[str]:
    year = int(year)
    month = int(month)
    max_day = calendar.monthrange(year, month)[1]
    if end_day is None:
        end_day = max_day
    end_day = int(end_day)
    if not 1 <= end_day <= max_day:
        raise ValueError(f'end_day muss zwischen 1 und {max_day} liegen')
    return [date(year, month, day).isoformat() for day in range(1, end_day + 1)]


def build_single_year_month_products(
    *,
    times: np.ndarray,
    cube: np.ndarray,
    year: int,
    month: int,
    end_day: int,
    complete_month_fields: dict[int, np.ndarray],
    previous_december: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    times = np.asarray(times)
    cube = np.asarray(cube, dtype=float)
    year = int(year)
    month = int(month)
    end_day = int(end_day)

    if not np.issubdtype(times.dtype, np.datetime64):
        raise ValueError('Tagesdaten brauchen datetime64-Zeitstempel')
    if cube.shape[0] != times.size:
        raise ValueError('times und cube stimmen nicht überein')

    date_strings = times.astype('datetime64[D]').astype(str)
    years = np.asarray([int(value[:4]) for value in date_strings], dtype=int)
    months = np.asarray([int(value[5:7]) for value in date_strings], dtype=int)
    mask = (years == year) & (months == month)
    if not np.any(mask):
        raise ValueError(f'Keine Tagesdaten für {year}-{month:02d}')

    target_times = times[mask]
    target_cube = cube[mask]
    target_dates = np.asarray(month_target_dates(year, month, end_day))

    stacks: dict[str, list[np.ndarray]] = {product: [] for product in PRODUCTS}
    year_array = np.asarray([year], dtype=int)

    for day in range(1, end_day + 1):
        day_field, mtd = extract_day_and_mtd(target_times, target_cube, day)
        mtd_3d = mtd[None, ...]
        season = combine_season_to_date(
            complete_month_fields,
            year_array,
            month,
            day,
            mtd_3d,
            previous_december=previous_december,
        )[0]
        ytd = combine_year_to_date(
            complete_month_fields,
            year_array,
            month,
            day,
            mtd_3d,
        )[0]
        values = {
            'day': day_field,
            'month_to_date': mtd,
            'season_to_date': season,
            'year_to_date': ytd,
        }
        for product in PRODUCTS:
            stacks[product].append(np.asarray(values[product], dtype=np.float32))

    return target_dates, {
        product: np.stack(fields, axis=0)
        for product, fields in stacks.items()
    }


def rank_contribution(
    current_products: dict[str, np.ndarray],
    historical_products: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    greater_parts = []
    valid_parts = []
    for product in PRODUCTS:
        current = np.asarray(current_products[product], dtype=float)
        historical = np.asarray(historical_products[product], dtype=float)
        if current.shape != historical.shape:
            raise ValueError(f'{product}: aktuelle und historische Form weichen ab')
        valid = np.isfinite(historical)
        greater = valid & np.isfinite(current) & (historical > current)
        greater_parts.append(greater.astype(np.uint8))
        valid_parts.append(valid.astype(np.uint8))
    return (
        np.stack(greater_parts, axis=1),
        np.stack(valid_parts, axis=1),
    )
