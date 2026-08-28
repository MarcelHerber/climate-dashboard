from __future__ import annotations

import calendar
import numpy as np

HISTORY_START = 1950
CURRENT_YEAR = 2026
PRODUCTS = ('day', 'month_to_date', 'season_to_date', 'year_to_date')

SEASONS = {
    'spring': {'name': 'Frühling', 'start_month': 3, 'months': (3, 4, 5)},
    'summer': {'name': 'Sommer', 'start_month': 6, 'months': (6, 7, 8)},
    'autumn': {'name': 'Herbst', 'start_month': 9, 'months': (9, 10, 11)},
    'winter': {'name': 'Winter', 'start_month': 12, 'months': (12, 1, 2)},
}


def historical_years(current_year: int = CURRENT_YEAR) -> np.ndarray:
    current_year = int(current_year)
    if current_year <= HISTORY_START:
        raise ValueError(f'current_year muss nach {HISTORY_START} liegen')
    return np.arange(HISTORY_START, current_year, dtype=int)


def season_for_month(month: int) -> tuple[str, str, int]:
    month = int(month)
    if month in (3, 4, 5):
        key = 'spring'
    elif month in (6, 7, 8):
        key = 'summer'
    elif month in (9, 10, 11):
        key = 'autumn'
    elif month in (12, 1, 2):
        key = 'winter'
    else:
        raise ValueError('month muss zwischen 1 und 12 liegen')
    meta = SEASONS[key]
    return key, str(meta['name']), int(meta['start_month'])


def products_for_month(month: int) -> tuple[str, ...]:
    season_for_month(month)
    return PRODUCTS


def daily_request_year_groups(years) -> tuple[tuple[int, ...], ...]:
    values = tuple(int(year) for year in years)
    return tuple((year,) for year in values)


def product_filename(product: str) -> str:
    if product not in PRODUCTS:
        raise ValueError(f'Unbekanntes Rangprodukt: {product}')
    return f'temperature_{product}_rank.png'


def finite_mean(cube: np.ndarray) -> np.ndarray:
    cube = np.asarray(cube, dtype=float)
    if cube.ndim < 2 or cube.shape[0] == 0:
        raise ValueError('cube braucht mindestens eine Zeitstufe')
    valid = np.isfinite(cube)
    count = np.sum(valid, axis=0)
    with np.errstate(invalid='ignore', divide='ignore'):
        result = np.nansum(cube, axis=0) / count
    result[count == 0] = np.nan
    return result


def extract_day_and_mtd(
    times: np.ndarray,
    cube: np.ndarray,
    target_day: int,
    *,
    allow_missing_day: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    cube = np.asarray(cube, dtype=float)
    times = np.asarray(times)
    if cube.ndim < 3:
        raise ValueError('cube muss Zeit x Breite x Länge enthalten')
    if cube.shape[0] != times.size:
        raise ValueError('times und cube stimmen nicht überein')
    if not 1 <= int(target_day) <= 31:
        raise ValueError('target_day muss zwischen 1 und 31 liegen')

    if np.issubdtype(times.dtype, np.datetime64):
        dates = times.astype('datetime64[D]').astype(str)
        days = np.asarray([int(text[-2:]) for text in dates], dtype=int)
        mtd_mask = days <= int(target_day)
        day_mask = days == int(target_day)
    else:
        if cube.shape[0] < target_day:
            if not allow_missing_day:
                raise ValueError('Nicht genügend Zeitstufen für target_day')
            mtd_mask = np.arange(cube.shape[0]) < int(target_day)
            day_mask = np.zeros(cube.shape[0], dtype=bool)
        else:
            mtd_mask = np.arange(cube.shape[0]) < int(target_day)
            day_mask = np.arange(cube.shape[0]) == int(target_day) - 1

    if not np.any(mtd_mask):
        raise ValueError(f'Keine Zeitstufen bis Zieltag {target_day:02d}')
    if not np.any(day_mask):
        if not allow_missing_day:
            raise ValueError(f'Zieltag {target_day:02d} fehlt in den Tagesdaten')
        day = np.full(cube.shape[1:], np.nan, dtype=float)
    else:
        day = finite_mean(cube[day_mask])
    return day, finite_mean(cube[mtd_mask])


def extract_year_day_mtd(times: np.ndarray, cube: np.ndarray, years: np.ndarray, target_day: int) -> tuple[np.ndarray, np.ndarray]:
    times = np.asarray(times)
    cube = np.asarray(cube, dtype=float)
    years = np.asarray(years, dtype=int)
    if not np.issubdtype(times.dtype, np.datetime64):
        raise ValueError('extract_year_day_mtd braucht datetime64-Zeitstempel')
    if cube.shape[0] != times.size:
        raise ValueError('times und cube stimmen nicht überein')
    date_strings = times.astype('datetime64[D]').astype(str)
    time_years = np.asarray([int(text[:4]) for text in date_strings], dtype=int)
    day_fields = []
    mtd_fields = []
    for year in years:
        mask = time_years == int(year)
        if not np.any(mask):
            raise ValueError(f'Jahr {year} fehlt in den Tagesdaten')
        day, mtd = extract_day_and_mtd(
            times[mask],
            cube[mask],
            target_day,
            allow_missing_day=True,
        )
        day_fields.append(day)
        mtd_fields.append(mtd)
    return np.stack(day_fields, axis=0), np.stack(mtd_fields, axis=0)


def combine_period_to_date(
    complete_month_fields: dict[int, np.ndarray],
    years: np.ndarray,
    start_month: int,
    target_month: int,
    target_day: int,
    current_month_to_date: np.ndarray,
) -> np.ndarray:
    years = np.asarray(years, dtype=int)
    mtd = np.asarray(current_month_to_date, dtype=float)
    start_month = int(start_month)
    target_month = int(target_month)
    target_day = int(target_day)
    if not 1 <= start_month <= target_month <= 12:
        raise ValueError('Ungültiger Monatsbereich')
    if not 1 <= target_day <= 31:
        raise ValueError('target_day muss zwischen 1 und 31 liegen')
    if mtd.shape[0] != years.size:
        raise ValueError('years und current_month_to_date stimmen nicht überein')

    numerator = np.where(np.isfinite(mtd), mtd * float(target_day), 0.0)
    denominator = np.where(np.isfinite(mtd), float(target_day), 0.0)

    for month in range(start_month, target_month):
        if month not in complete_month_fields:
            raise ValueError(f'Vollständiger Monat {month:02d} fehlt')
        values = np.asarray(complete_month_fields[month], dtype=float)
        if values.shape != mtd.shape:
            raise ValueError('Monatsfelder müssen dieselbe Form besitzen')
        weights = np.asarray([calendar.monthrange(int(year), month)[1] for year in years], dtype=float)
        weights = weights.reshape((years.size,) + (1,) * (values.ndim - 1))
        valid = np.isfinite(values)
        numerator += np.where(valid, values * weights, 0.0)
        denominator += np.where(valid, weights, 0.0)

    with np.errstate(invalid='ignore', divide='ignore'):
        result = numerator / denominator
    result[denominator == 0] = np.nan
    return result


def combine_year_to_date(
    complete_month_fields: dict[int, np.ndarray],
    years: np.ndarray,
    target_month: int,
    target_day: int,
    current_month_to_date: np.ndarray,
) -> np.ndarray:
    return combine_period_to_date(
        complete_month_fields,
        years,
        1,
        target_month,
        target_day,
        current_month_to_date,
    )


def combine_winter_to_date(
    complete_month_fields: dict[int, np.ndarray],
    previous_december: np.ndarray,
    years: np.ndarray,
    target_month: int,
    target_day: int,
    current_month_to_date: np.ndarray,
) -> np.ndarray:
    years = np.asarray(years, dtype=int)
    mtd = np.asarray(current_month_to_date, dtype=float)
    previous_december = np.asarray(previous_december, dtype=float)
    target_month = int(target_month)
    if target_month not in (1, 2):
        raise ValueError('Winter über Jahreswechsel ist nur für Januar/Februar definiert')
    if previous_december.shape != mtd.shape:
        raise ValueError('Vorjahres-Dezember und MTD müssen dieselbe Form besitzen')
    if mtd.shape[0] != years.size:
        raise ValueError('years und current_month_to_date stimmen nicht überein')

    previous_valid = np.isfinite(previous_december)
    numerator = np.where(previous_valid, previous_december * 31.0, 0.0)
    denominator = np.where(previous_valid, 31.0, 0.0)

    for month in range(1, target_month):
        if month not in complete_month_fields:
            raise ValueError(f'Vollständiger Wintermonat {month:02d} fehlt')
        values = np.asarray(complete_month_fields[month], dtype=float)
        weights = np.asarray([calendar.monthrange(int(year), month)[1] for year in years], dtype=float)
        weights = weights.reshape((years.size,) + (1,) * (values.ndim - 1))
        valid = np.isfinite(values)
        numerator += np.where(valid, values * weights, 0.0)
        denominator += np.where(valid, weights, 0.0)

    current_valid = np.isfinite(mtd)
    numerator += np.where(current_valid, mtd * float(target_day), 0.0)
    denominator += np.where(current_valid, float(target_day), 0.0)

    with np.errstate(invalid='ignore', divide='ignore'):
        result = numerator / denominator
    result[(denominator == 0) | ~previous_valid] = np.nan
    return result


def combine_season_to_date(
    complete_month_fields: dict[int, np.ndarray],
    years: np.ndarray,
    target_month: int,
    target_day: int,
    current_month_to_date: np.ndarray,
    *,
    previous_december: np.ndarray | None = None,
) -> np.ndarray:
    key, _, start_month = season_for_month(target_month)
    if key != 'winter' or int(target_month) == 12:
        return combine_period_to_date(
            complete_month_fields,
            years,
            start_month,
            target_month,
            target_day,
            current_month_to_date,
        )
    if previous_december is None:
        raise ValueError('Für Januar/Februar wird der Dezember des Vorjahres benötigt')
    return combine_winter_to_date(
        complete_month_fields,
        previous_december,
        years,
        target_month,
        target_day,
        current_month_to_date,
    )


def combine_summer_to_date(
    complete_month_fields: dict[int, np.ndarray],
    years: np.ndarray,
    target_month: int,
    target_day: int,
    current_month_to_date: np.ndarray,
) -> np.ndarray:
    if int(target_month) not in (6, 7, 8):
        raise ValueError('Sommer-bis-heute ist nur für Juni, Juli oder August definiert')
    return combine_period_to_date(
        complete_month_fields,
        years,
        6,
        target_month,
        target_day,
        current_month_to_date,
    )
