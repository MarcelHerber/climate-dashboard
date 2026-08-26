from __future__ import annotations

from datetime import date

import numpy as np

HISTORY_START = 1951
HISTORY_END = 2025
CURRENT_YEAR = 2026
PRODUCTS = ("day", "month_to_date", "summer_to_date")
TEMPERATURE_SCALE = 100
MISSING_I16 = -32768

RANK_CLASS_LABELS = ["1", "2", "3", "4–9", "10–20", "21–40", "41–60", "61–75", "76"]
RANK_COLORS = [
    "#D7198C", "#E31A1C", "#F46D43", "#FDB863", "#FFF7D6",
    "#D7E9F7", "#82B5D8", "#2C6AA0", "#4B176D",
]
RANK_BOUNDARIES = [0.5, 1.5, 2.5, 3.5, 9.5, 20.5, 40.5, 60.5, 75.5, 76.5]


def quantize_temperature(arr: np.ndarray) -> np.ndarray:
    src = np.asarray(arr, dtype=np.float32)
    out = np.full(src.shape, MISSING_I16, dtype=np.int16)
    valid = np.isfinite(src)
    if np.any(valid):
        q = np.rint(src[valid] * float(TEMPERATURE_SCALE))
        out[valid] = np.clip(q, -32767, 32767).astype(np.int16)
    return out


def dequantize_temperature(arr: np.ndarray) -> np.ndarray:
    packed = np.asarray(arr, dtype=np.int16)
    out = packed.astype(np.float32) / float(TEMPERATURE_SCALE)
    out[packed == MISSING_I16] = np.nan
    return out


def date_codes(times: np.ndarray) -> np.ndarray:
    values = np.asarray(times).astype("datetime64[D]").astype(str)
    return np.asarray([int(text[5:7]) * 100 + int(text[8:10]) for text in values], dtype=np.uint16)


def historical_years() -> np.ndarray:
    return np.arange(HISTORY_START, HISTORY_END + 1, dtype=int)


def rank_field(current: np.ndarray, history: np.ndarray) -> np.ndarray:
    current = np.asarray(current, dtype=float)
    history = np.asarray(history, dtype=float)
    if history.ndim != current.ndim + 1:
        raise ValueError("history muss genau eine führende Jahresdimension besitzen")
    valid_history = np.isfinite(history)
    valid_count = valid_history.sum(axis=0)
    greater = ((history > current[None, ...]) & valid_history).sum(axis=0)
    rank = 1.0 + greater.astype(float)
    rank[(valid_count == 0) | ~np.isfinite(current)] = np.nan
    return rank


def _finite_mean(cube: np.ndarray) -> np.ndarray:
    cube = np.asarray(cube, dtype=float)
    if cube.ndim < 3 or cube.shape[0] == 0:
        raise ValueError("cube muss Zeit x Y x X enthalten")
    count = np.sum(np.isfinite(cube), axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.nansum(cube, axis=0) / count
    out[count == 0] = np.nan
    return out


def extract_products(times: np.ndarray, cube: np.ndarray, target: date) -> dict[str, np.ndarray]:
    times = np.asarray(times).astype("datetime64[D]")
    cube = np.asarray(cube, dtype=float)
    if cube.ndim != 3 or cube.shape[0] != times.size:
        raise ValueError("Tagesdaten müssen Zeit x Y x X sein und zur Zeitachse passen")
    if target.month not in (6, 7, 8):
        raise ValueError("Sommer-Rangkarten sind nur für Juni bis August definiert")

    target64 = np.datetime64(target.isoformat())
    year_start = np.datetime64(f"{target.year:04d}-01-01")
    summer_start = np.datetime64(f"{target.year:04d}-06-01")
    month_start = np.datetime64(f"{target.year:04d}-{target.month:02d}-01")

    same_year = times >= year_start
    through_target = times <= target64
    day_mask = times == target64
    month_mask = same_year & through_target & (times >= month_start)
    summer_mask = same_year & through_target & (times >= summer_start)

    if not np.any(day_mask):
        raise ValueError(f"Zieltag {target.isoformat()} fehlt in den Tagesdaten")
    if not np.any(month_mask) or not np.any(summer_mask):
        raise ValueError(f"Unvollständige Zeitreihe bis Zieltag {target.isoformat()}")

    return {
        "day": _finite_mean(cube[day_mask]),
        "month_to_date": _finite_mean(cube[month_mask]),
        "summer_to_date": _finite_mean(cube[summer_mask]),
    }
