"""Compact, lossless (0.1 °C) historical DWD station temperature archive.

One JSON per station. Values are signed 16-bit deci-degrees Celsius:
for each year 366 consecutive days × (TXK, TNK, TMK), with -32768
representing missing observations. Calendar positions include Feb 29 in
leap years; a 366th slot is unused in ordinary years. The concatenated
binary is zlib-compressed and base64 encoded for lazy browser decoding.
"""
from __future__ import annotations

import base64
import struct
import zlib
from datetime import date
from typing import Any

MISSING = -32768
VALUES_PER_YEAR = 366 * 3


def build_temperature_history(
    station_id: str,
    values: dict[date, tuple[float | None, float | None, float | None, Any, Any]],
) -> dict[str, Any]:
    years: dict[int, list[int]] = {}
    counts: dict[int, list[int]] = {}
    for day, row in values.items():
        trio = row[:3]
        if not any(value is not None for value in trio):
            continue
        year_values = years.setdefault(day.year, [MISSING] * VALUES_PER_YEAR)
        count = counts.setdefault(day.year, [0, 0, 0])
        offset = (day.timetuple().tm_yday - 1) * 3
        for field, value in enumerate(trio):
            if value is None:
                continue
            scaled = int(round(float(value) * 10))
            if not -600 <= scaled <= 600:
                continue
            if year_values[offset + field] == MISSING:
                count[field] += 1
            year_values[offset + field] = scaled

    selected = sorted(years)
    binary = b"".join(struct.pack("<1098h", *years[year]) for year in selected)
    return {
        "format": "dwd-tx-tn-tm-zlib16-v1",
        "station_id": station_id,
        "source": "DWD CDC KL daily historical TXK/TNK/TMK",
        "unit": "0.1 °C",
        "years": selected,
        "counts": [[year, *counts[year]] for year in selected],
        "data": base64.b64encode(zlib.compress(binary, level=9)).decode("ascii"),
    }
