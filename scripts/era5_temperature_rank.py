from __future__ import annotations

import calendar
import numpy as np

RANK_CLASS_LABELS = ['1', '2', '3', '4–9', '10–20', '21–40', '41–60', '61–76', '77']
RANK_COLORS = [
    '#D0008F', '#E31A1C', '#F46D43', '#FDB863', '#FFF7D6',
    '#D7E9F7', '#82B5D8', '#2C6AA0', '#4B177D',
]
RANK_BOUNDARIES = [0.5, 1.5, 2.5, 3.5, 9.5, 20.5, 40.5, 60.5, 76.5, 77.5]


def decode_delta_x_u8(encoded: np.ndarray) -> np.ndarray:
    arr = np.asarray(encoded, dtype=np.uint8)
    return np.mod(np.cumsum(arr, axis=-1, dtype=np.uint32), 256).astype(np.uint8)


def temperature_rank_field(current: np.ndarray, history: np.ndarray) -> np.ndarray:
    current = np.asarray(current, dtype=float)
    history = np.asarray(history, dtype=float)
    if history.ndim != current.ndim + 1:
        raise ValueError('history must have one leading year dimension')
    valid_history = np.isfinite(history)
    valid_count = valid_history.sum(axis=0)
    greater = ((history > current[None, ...]) & valid_history).sum(axis=0)
    rank = 1.0 + greater.astype(float)
    rank[(valid_count == 0) | ~np.isfinite(current)] = np.nan
    return rank


def decode_temperature_pack_values(raw: bytes, meta: dict) -> np.ndarray:
    shape=(int(meta['n_years']), int(meta['nlat']), int(meta['nlon']))
    encoded=np.frombuffer(raw,dtype=np.uint8)
    expected=int(np.prod(shape))
    if encoded.size!=expected:
        raise ValueError(f'pack size mismatch: {encoded.size} != {expected}')
    codes=decode_delta_x_u8(encoded.reshape(shape))
    values=float(meta['offset']) + codes.astype(np.float32)*float(meta['step'])
    values[codes==int(meta.get('missing',255))]=np.nan
    return values


def combine_history_temperature(month_fields: dict[int, np.ndarray], years: np.ndarray, months: list[int]) -> np.ndarray:
    years=np.asarray(years,dtype=int)
    first=np.asarray(month_fields[months[0]],dtype=float)
    numerator=np.zeros_like(first,dtype=float)
    denominator=np.zeros_like(first,dtype=float)
    for month in months:
        values=np.asarray(month_fields[month],dtype=float)
        if values.shape!=first.shape:
            raise ValueError('monthly history fields must share one shape')
        weights=np.asarray([calendar.monthrange(int(year), int(month))[1] for year in years],dtype=float)
        weights=weights.reshape((len(years),)+(1,)*(values.ndim-1))
        valid=np.isfinite(values)
        numerator += np.where(valid, values*weights, 0.0)
        denominator += np.where(valid, weights, 0.0)
    with np.errstate(invalid='ignore',divide='ignore'):
        result=numerator/denominator
    result[denominator==0]=np.nan
    return result


def area_weighted_fraction(mask: np.ndarray, valid: np.ndarray, lat: np.ndarray) -> float | None:
    mask=np.asarray(mask,dtype=bool)
    valid=np.asarray(valid,dtype=bool)
    lat=np.asarray(lat,dtype=float)
    if mask.shape!=valid.shape or mask.ndim!=2 or mask.shape[0]!=lat.size:
        raise ValueError('mask/valid/lat dimensions do not match')
    weights=np.cos(np.deg2rad(lat))[:,None]
    denominator=float(np.sum(np.where(valid,weights,0.0)))
    if denominator<=0:
        return None
    numerator=float(np.sum(np.where(valid & mask,weights,0.0)))
    return 100.0*numerator/denominator
